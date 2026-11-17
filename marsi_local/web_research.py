"""Bounded HTTP GET access for an explicitly requested research turn."""
from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPException
import ipaddress
import json
import logging
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import quote, urlencode, urljoin, urlsplit


LOG = logging.getLogger(__name__)
MAX_QUERY = 500
MAX_DOWNLOAD = 2_000_000
MAX_RESULTS = 5
MAX_TEXT = 2_400
MAX_REDIRECTS = 3
SEARCH_TIMEOUT = 10
FETCH_TIMEOUT = 8
REDIRECTS = {301, 302, 303, 307, 308}
_NETWORK_SLOTS = threading.BoundedSemaphore(2)
_WEB_PORTS = {"http": 80, "https": 443}
_IPV6_TRANSITIONS = tuple(ipaddress.ip_network(prefix) for prefix in
                          ("2002::/16", "2001::/32", "64:ff9b::/96", "64:ff9b:1::/48"))
_TYPED = re.compile(r"^/(?:recherche|research)(?=\s|$)\s*", re.I)
_SPOKEN = re.compile(r"^(?:marsi|marcy|marci)[\s,:.!?]+research(?=[\s,:.!?]|$)[\s,:.!?]*", re.I)
_OVERRIDES = re.compile(
    r"\b(?:(?:ignore|disregard|forget|override)\b.{0,100}\b(?:instructions|rules|prompt)|"
    r"ignoriere\b.{0,100}\b(?:anweisungen|regeln))\b", re.I,
)


class ResearchError(Exception):
    pass


def research_query(text: str, *, spoken=False) -> str | None:
    match = (_SPOKEN if spoken else _TYPED).match(text.strip())
    return match.string[match.end():].strip() if match else None


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    domain: str
    excerpt: str

    def citation(self):
        return {"title": self.title, "url": self.url, "domain": self.domain}


def public_ip(ip):
    address = ipaddress.ip_address(ip)
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        elif address.is_site_local or any(address in subnet for subnet in _IPV6_TRANSITIONS):
            return False
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and not address.is_loopback and not address.is_link_local and not address.is_unspecified)


def web_address(url):
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise ResearchError("Invalid result URL.")
    if "\\" in url or any(character.isspace() or not character.isprintable() for character in url):
        raise ResearchError("Invalid result URL.")
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in _WEB_PORTS or not parsed.hostname or parsed.username is not None or "%" in parsed.hostname:
            raise ValueError
        if parsed.port is not None and parsed.port != _WEB_PORTS[parsed.scheme]:
            raise ValueError
        host = parsed.hostname.encode("idna").decode("ascii")
        if not re.fullmatch(r"[A-Za-z0-9.:-]+", host):
            raise ValueError
    except ValueError as error:
        raise ResearchError("Use a public HTTP or HTTPS result URL.") from error
    try:
        numeric = ipaddress.ip_address(host)
    except ValueError:
        numeric = None
    if numeric is not None and not public_ip(numeric):
        raise ResearchError("The address is outside the public Internet.")
    return parsed, host


def resolve_public(host, port):
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(item[0] not in (socket.AF_INET, socket.AF_INET6)
                            or (item[0] == socket.AF_INET6 and item[4][3]) or not public_ip(item[4][0])
                            for item in addresses):
        raise ResearchError("The address is outside the public Internet.")
    # Prefer IPv4 on dual-stack sites so a broken IPv6 route does not stall a turn.
    family, _, _, _, address = min(addresses, key=lambda item: item[0] != socket.AF_INET)
    return family, address


class NetworkBudget:
    def __init__(self, deadline):
        self.deadline = deadline
        self.active_socket = None
        self.lock = threading.Lock()
        self.closed = False

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ResearchError("The research request timed out.")
        return remaining

    def attach(self, sock):
        with self.lock:
            if self.closed:
                sock.close()
                raise ResearchError("The research request timed out.")
            self.active_socket = sock

    def close(self):
        with self.lock:
            self.closed = True
            if self.active_socket is not None:
                try:
                    self.active_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.active_socket.close()


def within_budget(operation, deadline, seconds):
    budget = NetworkBudget(min(deadline, time.monotonic() + seconds))
    if not _NETWORK_SLOTS.acquire(blocking=False):
        raise ResearchError("The research connection is busy.")
    result = queue.Queue(maxsize=1)

    def work():
        try:
            result.put((operation(budget), None))
        except Exception as error:
            result.put((None, error))
        finally:
            _NETWORK_SLOTS.release()

    try:
        threading.Thread(target=work, daemon=True).start()
    except RuntimeError:
        _NETWORK_SLOTS.release()
        raise ResearchError("The research connection is busy.") from None
    try:
        value, error = result.get(timeout=budget.remaining())
        if isinstance(error, ResearchError):
            raise error
        if error is not None:
            LOG.info("Research request failed (%s)", type(error).__name__)
            raise ResearchError("The research service or page did not respond.") from None
        return value
    except queue.Empty:
        raise ResearchError("The research request timed out.") from None
    finally:
        budget.close()


class PinnedConnection(HTTPConnection):
    """Connect to the checked sockaddr. Keep the original hostname for Host and TLS."""

    def __init__(self, host, port, family, address, tls, budget):
        super().__init__(host, port, timeout=budget.remaining())
        self.family, self.address, self.tls, self.budget = family, address, tls, budget

    def connect(self):
        sock = socket.socket(self.family, socket.SOCK_STREAM)
        self.sock = sock
        self.budget.attach(sock)
        sock.settimeout(self.budget.remaining())
        sock.connect(self.address)
        if self.tls:
            context = ssl.create_default_context()
            self.sock = context.wrap_socket(sock, server_hostname=self.host, do_handshake_on_connect=False)
            self.budget.attach(self.sock)
            self.sock.settimeout(self.budget.remaining())
            self.sock.do_handshake()


def get(host, port, family, address, tls, target, budget, types, *, limit, accept_redirect=False):
    connection = PinnedConnection(host, port, family, address, tls, budget)
    try:
        connection.request("GET", target, headers={"Accept": ", ".join(types), "Accept-Encoding": "identity",
                                                    "Connection": "close", "User-Agent": "Marsi-Research/1.0"})
        with connection.getresponse() as response:
            if accept_redirect and response.status in REDIRECTS:
                location = response.headers.get("Location")
                if not location:
                    raise ResearchError("The result page returned an empty redirect.")
                return location, None, None
            if (response.status != 200 or not response.headers.get("Content-Type")
                    or response.headers.get_content_type() not in types):
                raise ResearchError("The research server did not return the requested content type.")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ResearchError("The research server sent an unsupported encoding.")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isascii() or not length.isdecimal() or len(length) > 9
                                       or int(length) > limit):
                raise ResearchError("The research response exceeds the download limit.")
            data = bytearray()
            while True:
                budget.remaining()
                chunk = response.read1(min(65_536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > limit:
                    raise ResearchError("The research response exceeds the download limit.")
            encoding = response.headers.get_content_charset() or "utf-8"
            try:
                decoded = data.decode(encoding, errors="replace")
            except (LookupError, UnicodeError):
                decoded = data.decode("utf-8", errors="replace")
            return None, response.headers.get_content_type(), decoded
    except HTTPException as error:
        raise ResearchError("The research server returned an invalid HTTP response.") from error
    finally:
        connection.close()


def _plain_excerpt(value, limit):
    if not isinstance(value, str):
        return ""
    value = unescape(value)
    value = _OVERRIDES.sub("", value)
    value = re.sub(r"</?[A-Za-z][^>]{0,300}>", " ", value)
    # Prevent literal model role markers and control characters in excerpts.
    value = value.replace("<", " ").replace(">", " ")
    return " ".join("".join(char if char.isprintable() else " " for char in value).split())[:limit]


class PageText(HTMLParser):
    IGNORE = {"head", "script", "style", "template", "nav", "aside", "footer", "form", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = []
        self.main_depth = 0
        self.main = ""
        self.body = ""

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORE:
            self.ignored.append(tag)
        elif not self.ignored and tag in ("main", "article"):
            self.main_depth += 1

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
        elif self.main_depth and tag in ("main", "article"):
            self.main_depth -= 1

    def handle_data(self, data):
        if self.ignored:
            return
        if len(self.body) < MAX_TEXT * 2:
            self.body += " " + data[:MAX_TEXT * 2 - len(self.body)]
        if self.main_depth and len(self.main) < MAX_TEXT * 2:
            self.main += " " + data[:MAX_TEXT * 2 - len(self.main)]


class Research:
    def __init__(self, port=8888):
        self.port = port

    def web_search(self, query, deadline):
        if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY:
            raise ResearchError(f"Supply a research question of 1 to {MAX_QUERY} characters.")
        LOG.info("Research query %s", json.dumps(query, ensure_ascii=True))
        path = "/search?" + urlencode({"q": query, "format": "json", "categories": "general", "safesearch": 1})

        def search(budget):
            _, _, raw = get("127.0.0.1", self.port, socket.AF_INET, ("127.0.0.1", self.port), False,
                            path, budget, ("application/json",), limit=1_000_000)
            return json.loads(raw)

        result = within_budget(search, deadline, SEARCH_TIMEOUT)
        results = result.get("results") if isinstance(result, dict) else None
        if not isinstance(results, list):
            raise ResearchError("SearXNG did not return a result list.")
        hits, seen = [], set()
        for row in results:
            if not isinstance(row, dict):
                continue
            url = row.get("url")
            try:
                _, domain = web_address(url)
            except ResearchError:
                continue
            if url in seen:
                continue
            seen.add(url)
            title = _plain_excerpt(row.get("title"), 160) or domain
            hits.append(SearchResult(title, url, domain, _plain_excerpt(row.get("content"), 320)))
            if len(hits) >= MAX_RESULTS:
                break
        return hits

    def web_fetch(self, url, hits, deadline):
        if not any(url == result.url for result in hits):
            raise ResearchError("The page must be a result of this search.")

        def fetch(budget):
            current = url
            for step in range(MAX_REDIRECTS + 1):
                budget.remaining()
                parsed, host = web_address(current)
                port = _WEB_PORTS[parsed.scheme]
                family, address = resolve_public(host, port)
                path = quote(parsed.path or "/", safe="/:@!$&'()*+,;=-._~%")
                target = path + ("?" + quote(parsed.query, safe="/?:@!$&'()*+,;=-._~%") if parsed.query else "")
                redirect, content_type, data = get(host, port, family, address, parsed.scheme == "https",
                                                   target, budget, ("text/html", "text/plain"),
                                                   limit=MAX_DOWNLOAD, accept_redirect=True)
                if redirect is None:
                    if content_type == "text/html":
                        page = PageText()
                        page.feed(data)
                        page.close()
                        data = page.main or page.body
                    return current, host, _plain_excerpt(data, MAX_TEXT)
                if step == MAX_REDIRECTS:
                    raise ResearchError("The result page redirected too many times.")
                current = urljoin(current, redirect)
            raise AssertionError("Unreachable redirect count")

        return within_budget(fetch, deadline, FETCH_TIMEOUT)
