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
from uuid import uuid4

from .config import ServerConfig, load_env
from .core import Memory, ServiceError

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
SENSOR_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
IEEE_ADDRESS = re.compile(r"0x[0-9a-f]{16}")
SENSOR_IMPORT = "climate-sensors-v1"
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
    room: str = ""

    @classmethod
    def from_entry(cls, entry) -> Sensor:
        if not isinstance(entry, dict):
            raise ValueError("Each sensor needs a name and location")
        name, location, color = entry.get("name"), entry.get("location"), entry.get("color")
        room = entry.get("room", "")
        if not isinstance(name, str) or not name.strip() or not name.isprintable() or len(name) > 80:
            raise ValueError("Sensor names must be printable text up to 80 characters")
        if location not in ("indoor", "outdoor"):
            raise ValueError("Sensor location must be indoor or outdoor")
        if color is not None and (not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color)):
            raise ValueError("Sensor color must be a hex color such as #a68b5c")
        if not isinstance(room, str) or len(room) > 80 or (room and not room.isprintable()):
            raise ValueError("Sensor rooms must be printable text up to 80 characters")
        return cls(name.strip(), location, color, room.strip())


@dataclass(frozen=True)
class RegisteredSensor:
    details: Sensor
    topic: str
    ieee_address: str | None = None
    hidden: bool = False
    detached: bool = False

    def public(self, sensor_id):
        return {"id": sensor_id, **asdict(self.details)}


@dataclass(frozen=True)
class ClimateConfig:
    sensors: dict[str, Sensor]
    host: str = "127.0.0.1"
    port: int = 1883
    base_topic: str = "zigbee2mqtt"
    username: str = ""
    password_file: Path | None = None

    def topic(self, suffix: str) -> str:
        return f"{self.base_topic}/{suffix}"

    @classmethod
    def for_archive(cls, path: Path, database: Path) -> ClimateConfig:
        use_seed = True
        if database.is_file():
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
                use_seed = not registry_imported(db)
        return cls.load(path, use_seed=use_seed)

    @classmethod
    def load(cls, path: Path, *, use_seed=True) -> ClimateConfig:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("Climate configuration must be a JSON object")
        mqtt = raw.get("mqtt", {})
        sensors = raw.get("sensors", {}) if use_seed else {}
        if not isinstance(mqtt, dict) or not isinstance(sensors, dict):
            raise ValueError("Climate mqtt and sensors settings must be JSON objects")

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
            if not SENSOR_ID.fullmatch(sensor_id) or sensor_id == "bridge":
                raise ValueError("Use a device topic suffix of 1..64 letters, numbers, underscores or hyphens")
            configured[sensor_id] = Sensor.from_entry(entry)

        secret = path.parent / Path(password_file).expanduser() if password_file else None
        return cls(configured, host, port, base_topic, username, secret)


def registry_imported(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='migrations'").fetchone()
                and db.execute("SELECT 1 FROM migrations WHERE name=?", (SENSOR_IMPORT,)).fetchone())


def registered_sensors(db):
    rows = db.execute("""
        SELECT id, name, location, color, room, topic, ieee_address, hidden, detached
        FROM climate_sensors ORDER BY rowid
    """)
    return {sensor_id: RegisteredSensor(Sensor(name, location, color, room), topic, ieee, bool(hidden), bool(detached))
            for sensor_id, name, location, color, room, topic, ieee, hidden, detached in rows}


def seed_sensors(config):
    return {sensor_id: RegisteredSensor(details, sensor_id, sensor_id if IEEE_ADDRESS.fullmatch(sensor_id) else None)
            for sensor_id, details in config.sensors.items()}


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
        self.memory = memory
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
                CREATE TABLE IF NOT EXISTS climate_sensors (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    location TEXT NOT NULL,
                    color TEXT,
                    room TEXT NOT NULL,
                    topic TEXT NOT NULL UNIQUE,
                    ieee_address TEXT UNIQUE,
                    hidden INTEGER NOT NULL DEFAULT 0,
                    detached INTEGER NOT NULL DEFAULT 0
                );
            """)
            db.execute("BEGIN IMMEDIATE")
            if not registry_imported(db):
                db.executemany("""
                    INSERT INTO climate_sensors (id, name, location, color, room, topic, ieee_address)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, ((sensor_id, sensor.details.name, sensor.details.location, sensor.details.color,
                       sensor.details.room, sensor.topic, sensor.ieee_address)
                      for sensor_id, sensor in seed_sensors(config).items()))
                db.execute("INSERT INTO migrations (name) VALUES (?)", (SENSOR_IMPORT,))

    def registered(self):
        with self.memory.connect() as db:
            return registered_sensors(db)

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
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM climate_sensors WHERE id=? AND detached=0", (sensor_id,)).fetchone():
                return
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
            for sensor_id, sensor in registered_sensors(db).items():
                if sensor.hidden or sensor.detached:
                    continue
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
                    **sensor.public(sensor_id), "status": status,
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
            for sensor_id, sensor in registered_sensors(db).items():
                if sensor.hidden or sensor.detached:
                    continue
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
                sensors.append({**sensor.public(sensor_id), "series": series})
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
    def __init__(self, config: ClimateConfig, memory: Memory, *, management=False):
        self.config = config
        self.bridge_state_topic = f"{config.base_topic}/bridge/state"
        self.device_list_topic = f"{config.base_topic}/bridge/devices"
        self.bridge_replies = {f"{config.base_topic}/bridge/response/{action}": action
                               for action in ("permit_join", "device/remove")} if management else {}
        self.bridge_topics = [self.bridge_state_topic]
        if management:
            self.bridge_topics.extend((self.device_list_topic, *self.bridge_replies))
        self.devices = {}
        self.pending_bridge = self.bridge_reply = None
        self.services = {"mqtt": "offline", "zigbee2mqtt": "unknown"}
        self.client = _mqtt_client(config)
        self.archive = ClimateArchive(memory, config)
        self.topics = self._sensor_topics()
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

    def _sensor_topics(self):
        return {self.config.topic(sensor.topic): sensor_id for sensor_id, sensor in self.archive.registered().items()
                if not sensor.detached}

    def sync_topics(self):
        with self.archive.updates:
            topics = self._sensor_topics()
            removed = sorted(self.topics.keys() - topics.keys())
            added = sorted(topics.keys() - self.topics.keys())
            self.topics = topics
            if self.services["mqtt"] == "online":
                if removed:
                    self.client.unsubscribe(removed)
                if added:
                    self.client.subscribe([(topic, 1) for topic in added])
            self.archive.changed()

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

    def discovered(self):
        with self.archive.updates:
            return self.devices.copy()

    def bridge_request(self, action, payload, *, timeout=10):
        transaction = uuid4().hex
        updates = self.archive.updates
        with updates:
            if action not in self.bridge_replies.values() or any(state != "online" for state in self.services.values()):
                raise ServiceError("Zigbee2MQTT is unavailable.", 503)
            if self.pending_bridge is not None:
                raise ServiceError("A Zigbee operation is already in progress.", 409)
            self.pending_bridge = (action, transaction)
            self.bridge_reply = None
        try:
            sent = self.client.publish(self.config.topic("bridge/request/" + action),
                                       json.dumps({**payload, "transaction": transaction}), qos=0, retain=False)
            if sent.rc != 0:
                raise ServiceError("The Zigbee command could not be sent.", 503)
            with updates:
                updates.wait_for(lambda: self.bridge_reply is not None
                                 or any(state != "online" for state in self.services.values()), timeout=timeout)
                reply = self.bridge_reply
            if reply is None:
                raise ServiceError("Zigbee2MQTT did not confirm the operation. Check its device list before retrying.", 504)
            if reply.get("status") != "ok" or not isinstance(reply.get("data"), dict):
                raise ServiceError("Zigbee2MQTT rejected the operation. Check the device and its connection.", 502)
            return reply["data"]
        finally:
            with updates:
                self.pending_bridge = self.bridge_reply = None

    def _service_state(self, **state):
        with self.archive.updates:
            if any(self.services[name] != value for name, value in state.items()):
                self.services.update(state)
                if state.get("mqtt") == "offline" or state.get("zigbee2mqtt") == "offline":
                    self.devices = {}
                self.archive.changed()

    def _connected(self, client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            self._service_state(mqtt="offline", zigbee2mqtt="unknown")
            LOG.warning("Climate MQTT connection refused (%s)", reason)
            return
        with self.archive.updates:
            self._service_state(mqtt="online", zigbee2mqtt="unknown")
            client.subscribe([(topic, 1) for topic in (*self.topics, *self.bridge_topics)])

    def _connect_failed(self, _client, _userdata):
        self._service_state(mqtt="offline", zigbee2mqtt="unknown")
        LOG.warning("Climate MQTT unavailable. Retrying.")

    def _disconnected(self, _client, _userdata, _flags, reason, _properties):
        self._service_state(mqtt="offline", zigbee2mqtt="unknown")
        if reason.is_failure:
            LOG.warning("Climate MQTT link lost. Reconnecting.")

    def _subscribed(self, _client, _userdata, _mid, reasons, _properties):
        if len(reasons) == len(self.topics) + len(self.bridge_topics):
            accepted = sum(not reason.is_failure for reason in reasons[:len(self.topics)])
            if accepted < len(self.topics):
                LOG.warning("Climate MQTT subscription incomplete (%d/%d topics)", accepted, len(self.topics))
            else:
                LOG.info("Climate MQTT subscribed to %d sensor topic(s)", accepted)
            if any(reason.is_failure for reason in reasons[len(self.topics):]):
                LOG.warning("Climate MQTT bridge subscription rejected")
        elif any(reason.is_failure for reason in reasons):
            LOG.warning("Climate MQTT sensor subscription rejected")
        else:
            LOG.info("Climate MQTT added %d sensor topic(s)", len(reasons))

    def _received(self, _client, _userdata, message):
        if message.topic in self.bridge_topics:
            self._received_bridge(message)
            return
        with self.archive.updates:
            sensor_id = self.topics.get(message.topic)
        # A retained snapshot replayed on subscription is not a fresh report.
        if sensor_id is None or message.retain:
            return
        try:
            self.archive.record(sensor_id, message.payload)
        except sqlite3.Error as error:
            LOG.error("Climate reading could not be stored (%s)", type(error).__name__)

    def _received_bridge(self, message):
        limit = 1_000_000 if message.topic == self.device_list_topic else 4096
        try:
            payload = json.loads(message.payload) if len(message.payload) <= limit else None
        except (ValueError, RecursionError):
            return
        if message.topic == self.device_list_topic and isinstance(payload, list):
            devices = {}
            for item in payload:
                device = _climate_device(item)
                if device is not None:
                    devices[device["ieee_address"]] = device
            with self.archive.updates:
                self.devices = devices
        elif message.topic == self.bridge_state_topic and isinstance(payload, dict):
            if payload.get("state") in ("online", "offline"):
                self._service_state(zigbee2mqtt=payload["state"])
        elif not message.retain and isinstance(payload, dict):
            request = self.bridge_replies.get(message.topic), payload.get("transaction")
            with self.archive.updates:
                if request == self.pending_bridge:
                    self.bridge_reply = payload
                    self.archive.updates.notify_all()


def _climate_device(item):
    if (not isinstance(item, dict) or item.get("type") == "Coordinator" or item.get("supported") is not True
            or (item.get("interview_completed") is not True and item.get("interview_state") != "SUCCESSFUL")):
        return None
    ieee, topic = item.get("ieee_address"), item.get("friendly_name")
    if not isinstance(ieee, str) or not IEEE_ADDRESS.fullmatch(ieee):
        return None
    if (not isinstance(topic, str) or not topic or len(topic) > 160 or not topic.isprintable()
            or topic.split("/", 1)[0] in ("", "bridge") or any(char in topic for char in "+#")):
        return None
    definition = item.get("definition")
    exposes = definition.get("exposes") if isinstance(definition, dict) else None
    if not isinstance(exposes, list) or not any(isinstance(field, dict) and field.get("property") in CLIMATE_METRICS
                                               for field in exposes):
        return None
    model = definition.get("model")
    return {"ieee_address": ieee, "topic": topic, "model": model[:80] if isinstance(model, str) else ""}


def _check_archive(database: Path, config: ClimateConfig) -> None:
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
        sensors = registered_sensors(db) if registry_imported(db) else seed_sensors(config)
        for sensor_id, sensor in sensors.items():
            print(sensor.details.name)
            readings = _latest_readings(db, sensor_id)
            for metric in METRIC_RANGES:
                reading = readings.get(metric)
                if reading is None:
                    print(f"  {metric}: waiting for first reading")
                else:
                    stamp = datetime.fromtimestamp(reading["observed_ms"] / 1000, timezone.utc)
                    print(f"  {metric}: {reading['value']:g}  [{stamp.isoformat(timespec='milliseconds')}]")


def _simulate(config: ClimateConfig, database: Path, interval: float | None) -> None:
    sensors = seed_sensors(config)
    if database.is_file():
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
            if registry_imported(db):
                sensors = registered_sensors(db)
    sensors = [sensor for sensor_id, sensor in sensors.items() if sensor_id.startswith("sim-") and not sensor.detached]
    if not sensors:
        raise ValueError("Register a simulated sensor with an ID starting with sim-")
    client = _mqtt_client(config)
    client.connect(config.host, config.port, keepalive=30)
    client.loop_start()
    try:
        while True:
            for sensor in sensors:
                indoor = sensor.details.location == "indoor"
                payload = {
                    "temperature": round((21 if indoor else 10) + random.uniform(-2, 2), 2),
                    "humidity": round((45 if indoor else 70) + random.uniform(-5, 5), 2),
                    "battery": 90,
                    "linkquality": 180,
                    "last_seen": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                }
                sent = client.publish(config.topic(sensor.topic), json.dumps(payload), qos=1)
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
        config = ClimateConfig.for_archive(server.climate_config, server.database)
        if args.check:
            _check_archive(server.database, config)
        else:
            _simulate(config, server.database, args.interval)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Climate check failed: {error}\n")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
