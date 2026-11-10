"""Archive configured Zigbee2MQTT readings in Marsi's local database."""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import random
import re
import sqlite3
import threading
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
MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS
STALE_AFTER_MS = 2 * HOUR_MS
LINK_LOST_AFTER_MS = 3 * HOUR_MS
LOW_BATTERY_PERCENT = 20
CLIMATE_METRICS = ("temperature", "humidity")
# The period and bucket width in milliseconds. A zero width preserves the samples.
HISTORY_WINDOWS = {
    "3h": (3 * HOUR_MS, 0),
    "24h": (24 * HOUR_MS, 5 * MINUTE_MS),
    "7d": (7 * 24 * HOUR_MS, 30 * MINUTE_MS),
}


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


def _latest_readings(db, sensor_id: str, through_ms: int = MAX_TIMESTAMP_MS) -> dict:
    readings = {}
    for metric in METRIC_RANGES:
        row = db.execute("""
            SELECT value, observed_ms FROM climate_readings
            WHERE sensor_id=? AND metric=? AND observed_ms<=?
            ORDER BY observed_ms DESC LIMIT 1
        """, (sensor_id, metric, through_ms)).fetchone()
        if row is not None:
            readings[metric] = {"value": row[0], "observed_ms": row[1]}
    return readings


class ClimateArchive:
    def __init__(self, memory: Memory, config: ClimateConfig):
        self.memory, self.config = memory, config
        self.updates = threading.Condition()
        self.revision = 0
        with memory.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS climate_readings (
                    sensor_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    observed_ms INTEGER NOT NULL,
                    value REAL NOT NULL,
                    PRIMARY KEY (sensor_id, metric, observed_ms)
                ) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS climate_reports (
                    sensor_id TEXT PRIMARY KEY,
                    observed_ms INTEGER NOT NULL
                ) WITHOUT ROWID;
            """)

    def changed(self):
        with self.updates:
            self.revision += 1
            self.updates.notify_all()

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
        if not rows and data.get("last_seen") is None:
            return
        with self.memory.connect() as db:
            changed = db.executemany("""
                INSERT INTO climate_readings (sensor_id, metric, observed_ms, value)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (sensor_id, metric, observed_ms) DO UPDATE SET value=excluded.value
                WHERE climate_readings.value <> excluded.value
            """, rows).rowcount
            if observed_ms <= time.time_ns() // 1_000_000:
                changed += db.execute("""
                    INSERT INTO climate_reports VALUES (?, ?)
                    ON CONFLICT (sensor_id) DO UPDATE SET observed_ms=excluded.observed_ms
                    WHERE climate_reports.observed_ms < excluded.observed_ms
                """, (sensor_id, observed_ms)).rowcount
        if changed:
            self.changed()

    def current(self) -> dict:
        now = time.time_ns() // 1_000_000
        sensors = []
        with self.memory.connect() as db:
            db.execute("BEGIN")
            reports = dict(db.execute("SELECT sensor_id, observed_ms FROM climate_reports WHERE observed_ms<=?", (now,)))
            for sensor_id, sensor in self.config.sensors.items():
                readings = _latest_readings(db, sensor_id, now)
                measured = max((readings[metric]["observed_ms"] for metric in CLIMATE_METRICS
                                if metric in readings), default=None)
                if measured is None:
                    status = "waiting"
                else:
                    status = "stale" if now - measured >= STALE_AFTER_MS else "fresh"
                report = reports.get(sensor_id)
                for reading in readings.values():
                    at = reading["observed_ms"]
                    report = at if report is None else max(report, at)
                battery = readings.get("battery")
                sensors.append({
                    "id": sensor_id, **asdict(sensor), "status": status,
                    "last_measurement_ms": measured,
                    "last_report_ms": report,
                    "battery_low": battery is not None and battery["value"] <= LOW_BATTERY_PERCENT,
                    "readings": readings,
                })
        return {"generated_ms": now, "stale_after_ms": STALE_AFTER_MS, "sensors": sensors}

    def history(self, period: str) -> dict:
        if period not in HISTORY_WINDOWS:
            raise ValueError("Climate range must be 3h, 24h or 7d")
        duration, bucket = HISTORY_WINDOWS[period]
        end = time.time_ns() // 1_000_000
        start = end - duration
        sensors = []
        window = "FROM climate_readings WHERE sensor_id=? AND metric IN (?, ?) AND observed_ms BETWEEN ? AND ?"
        with self.memory.connect() as db:
            db.execute("BEGIN")
            for sensor_id, sensor in self.config.sensors.items():
                parameters = (sensor_id, *CLIMATE_METRICS, start, end)
                if bucket:
                    rows = db.execute(
                        f"SELECT metric, (observed_ms / ?) * ? AS at, AVG(value) {window} "
                        "GROUP BY metric, at ORDER BY metric, at",
                        (bucket, bucket, *parameters),
                    )
                else:
                    rows = db.execute(f"SELECT metric, observed_ms, value {window} ORDER BY metric, observed_ms",
                                      parameters)
                series = {metric: [] for metric in CLIMATE_METRICS}
                for metric, at, value in rows:
                    series[metric].append([max(start, at), value])
                sensors.append({"id": sensor_id, **asdict(sensor), "series": series})
        return {"range": period, "from_ms": start, "to_ms": end, "bucket_ms": bucket, "sensors": sensors}


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
        self.bridge_state_topic = f"{config.base_topic}/bridge/state"
        self.services = {"mqtt": "offline", "zigbee2mqtt": "unknown"}
        self.client = _mqtt_client(config)
        self.archive = ClimateArchive(memory, config)
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

    def current(self) -> dict:
        snapshot = self.archive.current()
        with self.archive.updates:
            services = self.services.copy()
        snapshot["services"] = services
        for sensor in snapshot["sensors"]:
            report = sensor["last_report_ms"]
            if services["mqtt"] != "online" or services["zigbee2mqtt"] != "online":
                connection = "unknown"
            elif report is None:
                connection = "waiting"
            elif snapshot["generated_ms"] - report >= LINK_LOST_AFTER_MS:
                connection = "lost"
            else:
                connection = "connected"
            sensor["connection"] = connection
        return snapshot

    def _service_state(self, **state):
        with self.archive.updates:
            if any(self.services[name] != value for name, value in state.items()):
                self.services.update(state)
                self.archive.changed()

    def _connected(self, client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            self._service_state(mqtt="offline", zigbee2mqtt="unknown")
            LOG.warning("Climate MQTT connection refused (%s)", reason)
            return
        self._service_state(mqtt="online", zigbee2mqtt="unknown")
        client.subscribe([(topic, 1) for topic in (*self.topics, self.bridge_state_topic)])

    def _connect_failed(self, _client, _userdata):
        self._service_state(mqtt="offline", zigbee2mqtt="unknown")
        LOG.warning("Climate MQTT unavailable. Retrying.")

    def _disconnected(self, _client, _userdata, _flags, reason, _properties):
        self._service_state(mqtt="offline", zigbee2mqtt="unknown")
        if reason.is_failure:
            LOG.warning("Climate MQTT link lost. Reconnecting.")

    def _subscribed(self, _client, _userdata, _mid, reasons, _properties):
        accepted = sum(not reason.is_failure for reason in reasons[:len(self.topics)])
        if accepted < len(self.topics):
            LOG.warning("Climate MQTT subscription incomplete (%d/%d topics)", accepted, len(self.topics))
        else:
            LOG.info("Climate MQTT subscribed to %d sensor topic(s)", accepted)

    def _received(self, _client, _userdata, message):
        if message.topic == self.bridge_state_topic:
            try:
                payload = json.loads(message.payload) if len(message.payload) <= 1024 else None
            except (ValueError, RecursionError):
                return
            state = payload.get("state") if isinstance(payload, dict) else None
            if state in ("online", "offline"):
                self._service_state(zigbee2mqtt=state)
            return
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
            readings = _latest_readings(db, sensor_id)
            for metric in METRIC_RANGES:
                reading = readings.get(metric)
                if reading is None:
                    print(f"  {metric}: waiting for first reading")
                else:
                    stamp = datetime.fromtimestamp(reading["observed_ms"] / 1000, timezone.utc)
                    print(f"  {metric}: {reading['value']:g}  [{stamp.isoformat(timespec='milliseconds')}]")


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
