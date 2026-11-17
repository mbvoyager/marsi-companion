"""Small, explicit configuration with no dotenv dependency or shell evaluation."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: str | Path) -> None:
    path = Path(path)
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"{path}:{number}: expected NAME=value")
        os.environ.setdefault(key, value.strip().strip('\"\''))


def validate_url(value: str) -> str:
    url = urlsplit(value)
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
        raise ValueError("Use an http(s) URL without embedded credentials")
    if url.query or url.fragment or url.path not in ("", "/"):
        raise ValueError("Use the server's base URL, without a path or query")
    return value.rstrip("/")


def env_switch(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    if value.lower() not in ("true", "false"):
        raise ValueError(f"{name} must be true or false")
    return value.lower() == "true"


LAN_NETWORKS = tuple(ipaddress.ip_network(prefix) for prefix in
                     ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7"))


def local_ollama_url(value: str) -> str:
    url = validate_url(value)
    parsed = urlsplit(url)
    if parsed.hostname == "localhost":
        # Resolve localhost explicitly, independent of the system DNS search path.
        return f"{parsed.scheme}://127.0.0.1" + (f":{parsed.port}" if parsed.port else "")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is None or not any(address in network for network in LAN_NETWORKS):
        raise ValueError("MARSI_OLLAMA_URL needs localhost or a private LAN IP address")
    return url


@dataclass(frozen=True)
class ServerConfig:
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:1.7b"
    token: str = ""
    database: Path = ROOT / "data" / "companion.sqlite3"
    whisper_model: str = "tiny"
    whisper_language: str = "en"
    piper_model: Path | None = None
    threads: int = 3
    timeout: float = 180.0
    demo: bool = False
    observances: bool = True
    schedule_session: str = "pi"
    morning_hour: int = 7
    climate_config: Path | None = None
    admin_token: str = ""
    climate_now: bool = True
    climate_summary: bool = True
    web_search: bool = False
    web_fetch: bool = True
    searxng_port: int = 8888
    tool_calling: bool = False

    def __post_init__(self):
        if self.admin_token and (len(self.token) < 32 or self.admin_token == self.token
                                 or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", self.admin_token)):
            raise ValueError("MARSI_ADMIN_TOKEN needs 32..128 URL-safe characters and a distinct MARSI_TOKEN")
        if not 1 <= self.searxng_port <= 65535:
            raise ValueError("MARSI_SEARXNG_PORT must be 1..65535")
        if self.model.lower().endswith((":cloud", "-cloud")):
            raise ValueError("MARSI_MODEL requires an installed local Ollama model")

    @classmethod
    def from_env(cls, demo: bool = False) -> ServerConfig:
        voice = os.getenv("MARSI_PIPER_MODEL", "")
        climate = os.getenv("MARSI_CLIMATE_CONFIG", "")
        config = cls(
            ollama_url=local_ollama_url(os.getenv("MARSI_OLLAMA_URL", cls.ollama_url)),
            model=os.getenv("MARSI_MODEL", cls.model),
            token=os.getenv("MARSI_TOKEN", ""),
            database=Path(os.getenv("MARSI_DATABASE", str(cls.database))).expanduser(),
            whisper_model=os.getenv("MARSI_WHISPER_MODEL", "tiny"),
            # This deployment is English-only, including existing .env files
            # that previously selected German or automatic detection.
            whisper_language="en",
            piper_model=Path(voice).expanduser() if voice else None,
            threads=int(os.getenv("MARSI_CPU_THREADS", "3")),
            timeout=float(os.getenv("MARSI_TIMEOUT", "180")),
            demo=demo,
            observances=os.getenv("MARSI_OBSERVANCES", "true").lower() == "true",
            schedule_session=os.getenv("MARSI_COMPANION_SESSION", "pi"),
            morning_hour=int(os.getenv("MARSI_MORNING_HOUR", "7")),
            climate_config=Path(climate).expanduser() if climate else None,
            admin_token=os.getenv("MARSI_ADMIN_TOKEN", ""),
            climate_now=env_switch("MARSI_CLIMATE_NOW", True),
            climate_summary=env_switch("MARSI_CLIMATE_SUMMARY", True),
            web_search=env_switch("MARSI_WEB_SEARCH", False),
            web_fetch=env_switch("MARSI_WEB_FETCH", True),
            searxng_port=int(os.getenv("MARSI_SEARXNG_PORT", "8888")),
            tool_calling=env_switch("MARSI_TOOL_CALLING", False),
        )
        if not 1 <= config.threads <= 64 or not 1 <= config.timeout <= 600:
            raise ValueError("CPU threads must be 1..64 and timeout must be 1..600 seconds")
        if not 0 <= config.morning_hour <= 23 or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", config.schedule_session):
            raise ValueError("Morning hour must be 0..23 and companion session must be a valid session name")
        return config


def validate_bind(host: str, token: str) -> None:
    # Literal loopback only: a DNS name may resolve to a LAN address.
    if host not in ("127.0.0.1", "localhost") and len(token) < 32:
        raise ValueError("A LAN listener requires MARSI_TOKEN with at least 32 characters")
    if token and (not token.isascii() or any(c.isspace() for c in token)):
        raise ValueError("MARSI_TOKEN must be ASCII with no whitespace")
