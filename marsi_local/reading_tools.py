"""Read-only climate context and deterministic intent recognition."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re


CLIMATE_RANGES = ("3h", "24h", "7d")
METRICS = {"temperature": ("temperature", "°C"), "humidity": ("humidity", "% RH")}
TEMPERATURE = r"\b(?:(?:aussen|innen)?temperatur\w*|(?:how|wie) (?:warm|cold|hot|kalt|heiss))\b"
HUMIDITY = r"\b(?:luftfeucht\w*|humidity|(?:how|wie) (?:humid|feucht))\b"
OUTDOOR = r"\b(?:outside|outdoors?|draussen|aussen|aussentemperatur|aussensensor)\b"
INDOOR = r"\b(?:inside|indoors?|drinnen|innen|innentemperatur|innensensor)\b"
LOCAL = r"\b(?:here|hier|zu hause|at home|sensor\w*|wohnzimmer|badezimmer|bad|bathroom|bedroom|kitchen|küche)\b"
REQUEST = (r"^(?:how (?:warm|cold|hot|humid)|wie (?:warm|kalt|heiss|feucht|hoch)|"
           r"what(?: is|'s) (?:the|our|my|your) |was ist (?:die|der|unsere) |"
           r"(?:show|give|tell|zeig\w*|sag\w*|nenn\w*)\b|"
           r"\b(?:current|currently|aktuell\w*|gerade|right now|measurement|messwert\w*)\b)")
DEFINITION = r"^(?:what (?:is|does) (?:relative )?(?:humidity|temperature)|was (?:ist|bedeutet) (?:relative )?(?:luftfeuchtigkeit|temperatur))\b"
REMOTE = (r"\b(?:forecast|vorhersage|tomorrow|morgen|mars|ofen|oven|cpu|gpu|prozes\w*|"
          r"human body|menschlich\w* körper|körpertemperatur|sun|sonne|absolute (?:zero|nullpunkt))\b")
HISTORY = r"\b(?:min|max|minimum|maximum|average|mean|durchschnitt\w*|mittelwert\w*|verlauf|trend|history|historie)\b"
RANGE_PATTERNS = (
    ("3h", r"\b3\s*(?:h|hours?|stunden?)\b"),
    ("24h", r"\b24\s*(?:h|hours?|stunden?)\b"),
    ("7d", r"\b7\s*(?:d|days?|tage[n]?)\b"),
)
VALUE_IN_REPLY = re.compile(r"(?<![\d.,])-?\d+(?:[.,]\d+)?\s*(?:°\s*[CF]|degrees?\s+(?:Celsius|Fahrenheit)|%)", re.I)
MAX_SENSORS_IN_CONTEXT = 8


@dataclass(frozen=True)
class ClimateIntent:
    period: str | None = None
    location: str | None = None
    metric: str | None = None


def climate_intent(text: str) -> ClimateIntent | None:
    question = text.casefold().strip().replace("’", "'")
    if re.search(DEFINITION, question) or re.search(REMOTE, question):
        return None
    temperature = bool(re.search(TEMPERATURE, question))
    humidity = bool(re.search(HUMIDITY, question))
    if not (temperature or humidity):
        return None
    outdoor, indoor = bool(re.search(OUTDOOR, question)), bool(re.search(INDOOR, question))
    period = next((label for label, pattern in RANGE_PATTERNS if re.search(pattern, question)), None)
    historical = bool(re.search(HISTORY, question))
    if not (re.search(REQUEST, question) or re.search(LOCAL, question) or outdoor or indoor or period or historical
            or question.rstrip(" ?") in ("temperature", "temperatur", "humidity", "luftfeuchtigkeit")):
        return None
    location = None if outdoor == indoor else ("outdoor" if outdoor else "indoor")
    metric = None if temperature == humidity else ("temperature" if temperature else "humidity")
    return ClimateIntent(period or ("3h" if historical else None), location, metric)


def _stamp(at_ms):
    return datetime.fromtimestamp(at_ms / 1000).astimezone().isoformat(timespec="minutes")


def _number(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _selected_sensors(data, intent):
    sensors = [sensor for sensor in data["sensors"] if intent.location is None or sensor["location"] == intent.location]
    return sensors[:MAX_SENSORS_IN_CONTEXT], len(sensors)


def _sensor_label(sensor):
    # Collapse whitespace in display labels. They remain data in the prompt.
    name = " ".join(sensor["name"].split())[:80]
    return f'{name} ({sensor["location"]})'


@dataclass(frozen=True)
class ClimateReading:
    text: str
    certain_reply: bool = True
    required_values: frozenset[str] = frozenset()

    def matches(self, reply):
        actual = frozenset(re.sub(r"\s+", "", match[0].lower().replace(",", "."))
                           .replace("degreescelsius", "°c").replace("degreecelsius", "°c")
                           for match in VALUE_IN_REPLY.finditer(reply))
        return bool(actual) and actual == self.required_values


def format_now(data, intent=ClimateIntent()):
    sensors, count = _selected_sensors(data, intent)
    if not sensors:
        scope = f" {intent.location}" if intent.location else ""
        return ClimateReading(f"I have no visible{scope} climate sensor.")
    lines, values = [], set()
    fresh = True
    metrics = (intent.metric,) if intent.metric else tuple(METRICS)
    for sensor in sensors:
        connection = sensor.get("connection", "unknown")
        measured = sensor.get("last_measurement_ms")
        newest = _stamp(measured) if measured is not None else "none"
        parts = []
        for metric in metrics:
            label, unit = METRICS[metric]
            latest = sensor["readings"].get(metric)
            if latest is None:
                parts.append(f"{label} missing")
                fresh = False
                continue
            stamp = _stamp(latest["observed_ms"])
            stale = data["generated_ms"] - latest["observed_ms"] >= data["stale_after_ms"]
            value = _number(latest["value"])
            prefix = "last recorded " if stale or connection != "connected" else ""
            parts.append(f"{prefix}{label} {value} {unit} at {stamp}" + (" (stale)" if stale else ""))
            fresh = fresh and not stale and connection == "connected"
            values.add(value + ("°c" if metric == "temperature" else "%"))
        lines.append(f"{_sensor_label(sensor)}, link {connection}, last measurement {newest}. " + ", ".join(parts) + ".")
    if count > len(sensors):
        lines.append(f"Showing {len(sensors)} of {count} visible sensors.")
    return ClimateReading("\n".join(lines), certain_reply=not fresh, required_values=frozenset(values))


def format_summary(data, intent):
    sensors, count = _selected_sensors(data, intent)
    if not sensors:
        scope = f" {intent.location}" if intent.location else ""
        return ClimateReading(f"I have no visible{scope} climate sensor for that period.")
    lines, required = [f"Last {data['range']} (min / max / mean)."], set()
    complete = True
    metrics = (intent.metric,) if intent.metric else tuple(METRICS)
    for sensor in sensors:
        parts = []
        for metric in metrics:
            label, unit = METRICS[metric]
            values = sensor["statistics"].get(metric)
            if values:
                numbers = [_number(values[key]) for key in ("min", "max", "mean")]
                sample = " / ".join(f"{number} {unit}" for number in numbers)
                required.update(number + ("°c" if metric == "temperature" else "%") for number in numbers)
            else:
                sample = "missing"
                complete = False
            parts.append(f"{label} {sample}")
        lines.append(f"{_sensor_label(sensor)}. " + ", ".join(parts) + ".")
    if count > len(sensors):
        lines.append(f"Showing {len(sensors)} of {count} visible sensors.")
    return ClimateReading("\n".join(lines), certain_reply=not complete, required_values=frozenset(required))


class ReadingTools:
    def __init__(self, config):
        self.config = config
        self.climate = None

    def climate_now(self, intent=ClimateIntent()):
        if not self.config.climate_now:
            return ClimateReading("Current climate readings are disabled in my settings.")
        if self.climate is None:
            return ClimateReading("The local climate archive is unavailable.")
        return format_now(self.climate.current(), intent)

    def climate_summary(self, range, intent=None):
        if range not in CLIMATE_RANGES:
            raise ValueError("Use a climate range of 3h, 24h or 7d.")
        if not self.config.climate_summary:
            return ClimateReading("Climate summaries are disabled in my settings.")
        if self.climate is None:
            return ClimateReading("The local climate archive is unavailable.")
        return format_summary(self.climate.archive.history(range, summary=True), intent or ClimateIntent(range))
