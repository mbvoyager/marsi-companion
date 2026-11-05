"""Archive configured Zigbee2MQTT readings in Marsi's local database."""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import random
import re
import sqlite3
import time

from .config import ServerConfig, load_env
from .core import Memory

LOG = logging.getLogger(__name__)
METRIC_RANGES = {
    "temperature": (-273.15, 200),
    "humidity": (0, 100),
    "battery": (0, 100),
    "linkquality": (0, 255),
}
MAX_TIMESTAMP_MS = 253_402_300_799_999


@dataclass(frozen=True)
class Sensor:
    name: str
    location: str
    color: str | None = None


@dataclass(frozen=True)
class ClimateConfig:
    sensors: dict[str, Sensor]
    host: str = "127.0.0.1"
    port: int = 1883
    base_topic: str = "zigbee2mqtt"
    username: str = ""
    password_file: Path | None = None

    def topic(self, sensor_id: str) -> str:
        return f"{self.base_topic}/{sensor_id}"

    @classmethod
    def load(cls, path: Path) -> ClimateConfig:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("Climate configuration must be a JSON object")
        mqtt = raw.get("mqtt", {})
        sensors = raw.get("sensors")
        if not isinstance(mqtt, dict) or not isinstance(sensors, dict) or not sensors:
            raise ValueError("Climate configuration needs a nonempty sensors object and optional mqtt settings")

        host = mqtt.get("host", cls.host)
        port = mqtt.get("port", cls.port)
        base_topic = mqtt.get("base_topic", cls.base_topic)
        if not isinstance(host, str) or not host or any(c.isspace() or not c.isprintable() for c in host):
            raise ValueError("mqtt.host must be a hostname or IP address")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("mqtt.port must be an integer from 1 to 65535")
        if not isinstance(base_topic, str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", base_topic):
            raise ValueError("mqtt.base_topic must be a topic prefix without wildcards")

        username = mqtt.get("username", "")
        password_file = mqtt.get("password_file", "")
        if (not isinstance(username, str) or (username and not username.isprintable())
                or not isinstance(password_file, str) or bool(username) != bool(password_file)):
            raise ValueError("Configure mqtt.username and mqtt.password_file together")

        configured = {}
        for sensor_id, entry in sensors.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", sensor_id) or sensor_id == "bridge":
                raise ValueError("Use a device topic suffix of 1..64 letters, numbers, underscores or hyphens")
            if not isinstance(entry, dict):
                raise ValueError("Each sensor needs a name and location")
            name, location, color = entry.get("name"), entry.get("location"), entry.get("color")
            if not isinstance(name, str) or not name.strip() or not name.isprintable() or len(name) > 80:
                raise ValueError("Sensor names must be printable text up to 80 characters")
            if location not in ("indoor", "outdoor"):
                raise ValueError("Sensor location must be indoor or outdoor")
            if color is not None and (not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color)):
                raise ValueError("Sensor color must be a hex color such as #a68b5c")
            configured[sensor_id] = Sensor(name.strip(), location, color)

        secret = path.parent / Path(password_file).expanduser() if password_file else None
        return cls(configured, host, port, base_topic, username, secret)


def _observed_ms(last_seen) -> int:
    if last_seen is None:
        return time.time_ns() // 1_000_000
    if type(last_seen) is int and 0 <= last_seen <= MAX_TIMESTAMP_MS:
        return last_seen
    if isinstance(last_seen, str) and len(last_seen) <= 64:
        text = last_seen[:-1] + "+00:00" if last_seen.endswith("Z") else last_seen
        stamp = datetime.fromisoformat(text)
        if stamp.utcoffset() is not None:
            millis = round(stamp.timestamp() * 1000)
            if 0 <= millis <= MAX_TIMESTAMP_MS:
                return millis
    raise ValueError("Invalid last_seen timestamp")


class ClimateArchive:
    def __init__(self, memory: Memory):
        self.memory = memory
        with memory.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS climate_readings (
                    sensor_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    observed_ms INTEGER NOT NULL,
                    value REAL NOT NULL,
                    PRIMARY KEY (sensor_id, metric, observed_ms)
                ) WITHOUT ROWID
            """)

    def record(self, sensor_id: str, payload: bytes) -> None:
        if len(payload) > 16_384:
            return
        try:
            data = json.loads(payload)
            if not isinstance(data, dict):
                return
            observed_ms = _observed_ms(data.get("last_seen"))
        except (ValueError, OverflowError, OSError, RecursionError):
            return

        rows = []
        for metric, (minimum, maximum) in METRIC_RANGES.items():
            value = data.get(metric)
            if type(value) in (int, float) and minimum <= value <= maximum:
                rows.append((sensor_id, metric, observed_ms, float(value)))
        if rows:
            with self.memory.connect() as db:
                db.executemany("""
                    INSERT INTO climate_readings (sensor_id, metric, observed_ms, value)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (sensor_id, metric, observed_ms) DO UPDATE SET value=excluded.value
                """, rows)


def _mqtt_client(config: ClimateConfig):
    try:
        from paho.mqtt import client as mqtt
    except ImportError as error:
        raise RuntimeError("Install requirements-climate.txt in the server environment") from error
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if config.password_file is not None:
        password = config.password_file.read_text(encoding="utf-8").removesuffix("\n")
        if not password or "\n" in password:
            raise ValueError("MQTT password file must contain one nonempty line")
        client.username_pw_set(config.username, password)
    return client


class ClimateSubscriber:
    def __init__(self, config: ClimateConfig, memory: Memory):
        self.config = config
        self.topics = {config.topic(sensor_id): sensor_id for sensor_id in config.sensors}
        self.client = _mqtt_client(config)
        self.archive = ClimateArchive(memory)
        self.client.on_connect = self._connected
        self.client.on_connect_fail = self._connect_failed
        self.client.on_disconnect = self._disconnected
        self.client.on_subscribe = self._subscribed
        self.client.on_message = self._received
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

    def start(self) -> None:
        self.client.connect_async(self.config.host, self.config.port, keepalive=30)
        self.client.loop_start()

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()

    def _connected(self, client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            LOG.warning("Climate MQTT connection refused (%s)", reason)
            return
        client.subscribe([(topic, 1) for topic in self.topics])

    def _connect_failed(self, _client, _userdata):
        LOG.warning("Climate MQTT unavailable. Retrying.")

    def _disconnected(self, _client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            LOG.warning("Climate MQTT link lost. Reconnecting.")

    def _subscribed(self, _client, _userdata, _mid, reasons, _properties):
        accepted = sum(not reason.is_failure for reason in reasons)
        if accepted < len(self.topics):
            LOG.warning("Climate MQTT subscription incomplete (%d/%d topics)", accepted, len(self.topics))
        else:
            LOG.info("Climate MQTT subscribed to %d sensor topic(s)", accepted)

    def _received(self, _client, _userdata, message):
        sensor_id = self.topics.get(message.topic)
        # A retained snapshot replayed on subscription is not a fresh report.
        if sensor_id is None or message.retain:
            return
        try:
            self.archive.record(sensor_id, message.payload)
        except sqlite3.Error as error:
            LOG.error("Climate reading could not be stored (%s)", type(error).__name__)


def _check_archive(database: Path, config: ClimateConfig) -> None:
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
        for sensor_id, sensor in config.sensors.items():
            print(sensor.name)
            for metric in METRIC_RANGES:
                row = db.execute("""
                    SELECT value, observed_ms FROM climate_readings
                    WHERE sensor_id=? AND metric=? ORDER BY observed_ms DESC LIMIT 1
                """, (sensor_id, metric)).fetchone()
                if row is None:
                    print(f"  {metric}: waiting for first reading")
                else:
                    value, observed_ms = row
                    stamp = datetime.fromtimestamp(observed_ms / 1000, timezone.utc)
                    print(f"  {metric}: {value:g}  [{stamp.isoformat(timespec='milliseconds')}]")


def _simulate(config: ClimateConfig, interval: float | None) -> None:
    sensors = {sensor_id: sensor for sensor_id, sensor in config.sensors.items() if sensor_id.startswith("sim-")}
    if not sensors:
        raise ValueError("Add a sensor ID starting with sim- to the climate configuration")
    client = _mqtt_client(config)
    client.connect(config.host, config.port, keepalive=30)
    client.loop_start()
    try:
        while True:
            for sensor_id, sensor in sensors.items():
                indoor = sensor.location == "indoor"
                payload = {
                    "temperature": round((21 if indoor else 10) + random.uniform(-2, 2), 2),
                    "humidity": round((45 if indoor else 70) + random.uniform(-5, 5), 2),
                    "battery": 90,
                    "linkquality": 180,
                    "last_seen": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                }
                sent = client.publish(config.topic(sensor_id), json.dumps(payload), qos=1)
                sent.wait_for_publish(timeout=5)
                if not sent.is_published():
                    raise RuntimeError("MQTT did not acknowledge the simulated reading")
            print(f"Published simulated readings for {len(sensors)} sensor(s).", flush=True)
            if interval is None:
                break
            time.sleep(interval)
    finally:
        client.disconnect()
        client.loop_stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env.server")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="Read the latest archived values from SQLite")
    action.add_argument("--simulate", action="store_true", help="Send one batch of readings for configured sim- sensors")
    parser.add_argument("--interval", type=float, help="Repeat the simulation every N seconds")
    args = parser.parse_args()
    if args.interval is not None and (not args.simulate or not math.isfinite(args.interval) or args.interval < 1):
        parser.error("Use --interval with --simulate and at least one second")
    try:
        load_env(args.env)
        server = ServerConfig.from_env()
        if server.climate_config is None:
            raise ValueError("Set MARSI_CLIMATE_CONFIG in the server environment")
        config = ClimateConfig.load(server.climate_config)
        if args.check:
            _check_archive(server.database, config)
        else:
            _simulate(config, args.interval)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Climate check failed: {error}\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
