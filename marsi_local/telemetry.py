"""Read numeric machine health only; no addresses, hostnames or device serials."""
from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
import threading
import time

FIELDS = {
    "cpu_percent": 100, "load1": 10000, "cpu_count": 4096,
    "ram_used_mb": 100_000_000, "ram_total_mb": 100_000_000,
    "disk_used_percent": 100, "uptime_seconds": 10_000_000_000,
    "temperature_c": 200,
}


def numeric_readings(value):
    if not isinstance(value, dict):
        raise ValueError("Readings must be an object")
    result = {}
    for key, maximum in FIELDS.items():
        number = value.get(key)
        if number is None:
            result[key] = None
        elif type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= maximum:
            raise ValueError(f"Invalid {key} reading")
        else:
            result[key] = round(number, 2)
    return result


class Telemetry:
    def __init__(self):
        self.previous = None
        self.lock = threading.Lock()
        self.pi = None
        self.pi_at = 0.0

    def receive_pi(self, readings):
        readings = numeric_readings(readings)
        with self.lock:
            self.pi, self.pi_at = readings, time.monotonic()

    def snapshot(self):
        readings = dict.fromkeys(FIELDS)
        readings["cpu_count"] = os.cpu_count()
        try:
            cpu = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
            total, idle = sum(cpu), cpu[3] + cpu[4]
            with self.lock:
                if self.previous and total > self.previous[0]:
                    readings["cpu_percent"] = round(100 * (1 - (idle - self.previous[1]) / (total - self.previous[0])), 1)
                self.previous = total, idle
        except (OSError, ValueError, IndexError):
            pass
        try:
            readings["load1"] = round(os.getloadavg()[0], 2)
        except (AttributeError, OSError):
            pass
        try:
            values = {line.split(":")[0]: int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()}
            readings["ram_total_mb"] = round(values["MemTotal"] / 1024, 1)
            readings["ram_used_mb"] = round((values["MemTotal"] - values["MemAvailable"]) / 1024, 1)
        except (OSError, ValueError, KeyError, IndexError):
            pass
        try:
            readings["uptime_seconds"] = int(float(Path("/proc/uptime").read_text().split()[0]))
        except (OSError, ValueError, IndexError):
            pass
        try:
            used = shutil.disk_usage(Path(__file__).resolve().parent)
            readings["disk_used_percent"] = round(100 * used.used / used.total, 1)
        except OSError:
            pass
        try:
            zones = sorted(Path("/sys/class/thermal").glob("thermal_zone*"))
            for zone in zones:
                kind = (zone / "type").read_text().strip().lower()
                if any(name in kind for name in ("cpu", "soc", "x86_pkg")):
                    readings["temperature_c"] = round(int((zone / "temp").read_text()) / 1000, 1)
                    break
        except (OSError, ValueError):
            pass
        return numeric_readings(readings)

    def pair(self):
        server = self.snapshot()
        with self.lock:
            pi = self.pi if time.monotonic() - self.pi_at <= 90 else None
        return {"server": server, "pi": pi}


def reading(value, suffix=""):
    return "--" if value is None else f"{value:g}{suffix}"


def inscription(name, data):
    if not data:
        return f"[{name}: LINK SILENT]"
    ram = (100 * data["ram_used_mb"] / data["ram_total_mb"]
           if data.get("ram_total_mb") and data.get("ram_used_mb") is not None else None)
    return (f"[{name}: MACHINE CANT]\n"
            f"CPU {reading(data.get('cpu_percent'), '%')}  LOAD {reading(data.get('load1'))}\n"
            f"RAM {reading(round(ram, 1) if ram is not None else None, '%')}  TEMP {reading(data.get('temperature_c'), 'C')}\n"
            f"DISK {reading(data.get('disk_used_percent'), '%')}  CORES {reading(data.get('cpu_count'))}")
