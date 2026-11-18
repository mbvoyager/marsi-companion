"""One authored design definition, shared by Tk, CSS and browser plots."""
from functools import lru_cache
import json
from pathlib import Path
import re
from datetime import datetime, timezone


@lru_cache(maxsize=1)
def definition():
    return json.loads(Path(__file__).with_name("web").joinpath("cogitator.json").read_text(encoding="utf-8"))


COLORS = definition()["colors"]
BLACK, PANEL, RED, GREEN = (COLORS[key] for key in ("black", "panel", "red", "green"))
BONE, BRASS, DIM, AMBER = (COLORS[key] for key in ("bone", "brass", "dim", "amber"))
MUTED, FAULT = COLORS["muted"], COLORS["rust"]
FPS = definition()["layout"]["fps"]
TYPE = definition()["type"]
LAYOUT = definition()["layout"]


def css():
    rules = [f"--{key}: {value}" for key, value in COLORS.items()]
    for group in ("layout", "type"):
        rules.extend(f"--{group}-{key}: {value}px" for key, value in definition()[group].items())
    rules.extend(f"--sensor-{index}: {style['color']}" for index, style in enumerate(definition()["sensors"]))
    return ":root {\n  " + ";\n  ".join(rules) + ";\n}\n"


def sensor_style(sensor, index):
    patterns = definition()["sensors"]
    count = len(patterns)
    style = dict(patterns[index % count])
    # Continue with new combinations as the registry grows: four colours,
    # four line patterns and four shapes give 64 distinct default identities.
    style["dash"] = patterns[(index+index//count) % count]["dash"]
    style["shape"] = patterns[(index+index//(count*count)) % count]["shape"]
    color = sensor.get("color")
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        style["color"] = color
    return style


def imperial_date(now=None):
    """Fictional M42 display: UTC check/year-fraction/last-three-year digits.

    This is a presentation convention, not a claim that today's Gregorian year
    belongs to the setting's 42nd millennium. Leap years use their actual length.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    fraction = min(999, int(1000 * (now-start).total_seconds() / (end-start).total_seconds()))
    return f"0.{fraction:03d}{now.year % 1000:03d}.M42"
