"""Authenticated climate operations. The HTTP handler owns authorization."""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from uuid import uuid4

from .climate import MAX_TIMESTAMP_MS, METRIC_RANGES, SENSOR_ID, RegisteredSensor, Sensor
from .core import ServiceError

LOG = logging.getLogger(__name__)
PAIRING_SECONDS = 120
PREVIEW_SECONDS = 300
MAX_PREVIEWS = 32
READING_PAGE_SIZE = 50


@dataclass(frozen=True)
class Preview:
    action: str
    scope: dict
    count: int
    match: str | RegisteredSensor
    expires: float


def _sensor_id(value):
    if not isinstance(value, str) or not SENSOR_ID.fullmatch(value):
        raise ValueError("Select a valid sensor ID.")
    return value


def _where(filters, *, require_scope=False):
    columns = {"sensor_id": "sensor_id=?", "from_ms": "observed_ms>=?", "to_ms": "observed_ms<?",
               "metric": "metric=?", "observed_ms": "observed_ms=?"}
    if not isinstance(filters, dict) or filters.keys() - columns.keys():
        raise ValueError("Use a sensor, time range or exact reading as the filter.")
    if "sensor_id" in filters:
        _sensor_id(filters["sensor_id"])
    for field in ("from_ms", "to_ms", "observed_ms"):
        if field in filters and (type(filters[field]) is not int or not 0 <= filters[field] <= MAX_TIMESTAMP_MS):
            raise ValueError("Timestamps must be UTC milliseconds.")
    if "from_ms" in filters and "to_ms" in filters and filters["from_ms"] >= filters["to_ms"]:
        raise ValueError("The end of the range must be after its start.")
    if "metric" in filters or "observed_ms" in filters:
        if (filters.keys() != {"sensor_id", "metric", "observed_ms"}
                or filters["metric"] not in tuple(METRIC_RANGES)):
            raise ValueError("An exact reading needs its sensor, metric and timestamp.")
    if require_scope and not filters:
        raise ValueError("Select a sensor or time range before deleting readings.")
    keys = [key for key in columns if key in filters]
    return " AND ".join(columns[key] for key in keys) or "1", tuple(filters[key] for key in keys)


def _matching_rows(db, where, parameters):
    rows = db.execute(f"""
        SELECT sensor_id, metric, observed_ms, value FROM climate_readings
        WHERE {where} ORDER BY sensor_id, metric, observed_ms
    """, parameters)
    digest, count = hashlib.sha256(), 0
    for row in rows:
        digest.update(json.dumps(row, separators=(",", ":")).encode() + b"\n")
        count += 1
    return count, digest.hexdigest()


def _registered_id(registry, device):
    for sensor_id, sensor in registry.items():
        if sensor.ieee_address == device["ieee_address"] or (sensor.ieee_address is None and sensor.topic == device["topic"]):
            return sensor_id
    return None


class ClimateAdmin:
    def __init__(self, climate):
        self.climate = climate
        self.memory = climate.archive.memory
        self.lock = threading.Lock()
        self.previews = {}
        self.pairing_until_ms = 0
        with self.memory.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS climate_admin_log (
                    id INTEGER PRIMARY KEY,
                    at_ms INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    readings_deleted INTEGER NOT NULL,
                    backup TEXT NOT NULL
                )
            """)

    def status(self):
        registry = self.climate.archive.registered()
        devices = self.climate.discovered()
        discoveries = []
        for device in devices.values():
            existing = _registered_id(registry, device)
            if existing is None or registry[existing].detached:
                discoveries.append(device)
        with self.climate.archive.updates:
            services = self.climate.services.copy()
        return {
            "sensors": [{**sensor.public(sensor_id), "hidden": sensor.hidden, "detached": sensor.detached,
                         "can_unpair": any(_registered_id({sensor_id: sensor}, device) is not None
                                           for device in devices.values()) and not sensor.detached}
                        for sensor_id, sensor in registry.items()],
            "discoveries": discoveries,
            "services": services,
            "pairing_until_ms": self.pairing_until_ms if self.pairing_until_ms > self._now() else None,
        }

    def pairing(self, payload):
        opened = payload.get("open")
        if type(opened) is not bool:
            raise ValueError("Set open to true or false.")
        with self.lock:
            self.climate.bridge_request("permit_join", {"time": PAIRING_SECONDS if opened else 0,
                                                       "device": "coordinator"})
            self.pairing_until_ms = self._now() + PAIRING_SECONDS * 1000 if opened else 0
        return self.status()

    def save_sensor(self, payload):
        details = Sensor.from_entry(payload)
        show = payload.get("show", False)
        if type(show) is not bool:
            raise ValueError("Set show to true or false.")
        with self.lock:
            registry = self.climate.archive.registered()
            if "device_id" in payload:
                device = self.climate.discovered().get(_sensor_id(payload["device_id"]))
                if device is None:
                    raise ServiceError("This device is no longer in the Zigbee discovery list.", 409)
                ieee = device["ieee_address"]
                existing = _registered_id(registry, device)
                sensor_id = existing or ieee
                if existing is None and sensor_id in registry:
                    raise ServiceError("This sensor ID is already registered.", 409)
                if any(other != sensor_id and sensor.topic == device["topic"] for other, sensor in registry.items()):
                    raise ServiceError("Another sensor uses this MQTT topic.", 409)
                with self.memory.connect() as db:
                    db.execute("""
                        INSERT INTO climate_sensors (id, name, location, color, room, topic, ieee_address)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (id) DO UPDATE SET name=excluded.name, location=excluded.location,
                            color=excluded.color, room=excluded.room, topic=excluded.topic,
                            ieee_address=excluded.ieee_address, hidden=0, detached=0
                    """, (sensor_id, details.name, details.location, details.color, details.room, device["topic"], ieee))
            else:
                sensor_id = _sensor_id(payload.get("id"))
                sensor = registry.get(sensor_id)
                if sensor is None:
                    raise ServiceError("Sensor not found.", 404)
                if show and sensor.detached:
                    raise ServiceError("Pair this sensor again before showing it.", 409)
                with self.memory.connect() as db:
                    db.execute("""
                        UPDATE climate_sensors SET name=?, location=?, color=?, room=?, hidden=? WHERE id=?
                    """, (details.name, details.location, details.color, details.room, sensor.hidden and not show, sensor_id))
            self.climate.sync_topics()
        return {**self.status(), "saved_id": sensor_id}

    def readings(self, payload):
        where, parameters = _where(payload.get("filters", {}))
        offset = payload.get("offset", 0)
        if type(offset) is not int or not 0 <= offset <= 2_147_483_647:
            raise ValueError("Invalid reading offset.")
        with self.memory.connect() as db:
            rows = db.execute(f"""
                SELECT sensor_id, metric, observed_ms, value FROM climate_readings WHERE {where}
                ORDER BY observed_ms DESC, sensor_id, metric LIMIT ? OFFSET ?
            """, (*parameters, READING_PAGE_SIZE + 1, offset)).fetchall()
        return {"rows": [{"sensor_id": sensor, "metric": metric, "observed_ms": at, "value": value}
                         for sensor, metric, at, value in rows[:READING_PAGE_SIZE]],
                "previous_offset": max(0, offset - READING_PAGE_SIZE) if offset else None,
                "next_offset": offset + READING_PAGE_SIZE if len(rows) > READING_PAGE_SIZE else None}

    def preview(self, payload):
        action = payload.get("action")
        with self.lock:
            if action == "delete":
                scope = payload.get("filters", {})
                where, parameters = _where(scope, require_scope=True)
                with self.memory.connect() as db:
                    count, match = _matching_rows(db, where, parameters)
                if count == 0:
                    raise ServiceError("No readings match this selection.", 409)
                name = None
            elif action in ("hide", "unpair"):
                sensor_id = _sensor_id(payload.get("id"))
                match = self.climate.archive.registered().get(sensor_id)
                if match is None or match.detached or (action == "hide" and match.hidden):
                    raise ServiceError("This sensor cannot be removed with that action.", 409)
                if action == "unpair":
                    self._unpair_address(sensor_id, match)
                scope = {"sensor_id": sensor_id}
                with self.memory.connect() as db:
                    count = db.execute("SELECT count(*) FROM climate_readings WHERE sensor_id=?", (sensor_id,)).fetchone()[0]
                name = match.details.name
            else:
                raise ValueError("Select hide, unpair or delete.")
            now = time.monotonic()
            self.previews = {key: preview for key, preview in self.previews.items() if preview.expires > now}
            if len(self.previews) >= MAX_PREVIEWS:
                self.previews.pop(next(iter(self.previews)))
            key = uuid4().hex
            self.previews[key] = Preview(action, scope.copy(), count, match, now + PREVIEW_SECONDS)
        return {"preview_id": key, "action": action, "scope": scope, "count": count,
                "sensor_name": name, "expires_in_s": PREVIEW_SECONDS}

    def confirm(self, payload):
        key = payload.get("preview_id")
        if payload.get("confirm") is not True or not isinstance(key, str):
            raise ValueError("Confirm the current preview before continuing.")
        with self.lock:
            preview = self.previews.pop(key, None)
            if preview is None or preview.expires <= time.monotonic():
                raise ServiceError("That preview expired. Create a new preview.", 409)
            if preview.action == "delete":
                backup = self._delete(preview)
            else:
                backup = self._remove(preview)
        result = {"action": preview.action, "readings_deleted": preview.count if preview.action == "delete" else 0,
                  "backup": backup}
        if preview.action != "delete":
            result["status"] = self.status()
        return result

    def _delete(self, preview):
        where, parameters = _where(preview.scope, require_scope=True)
        with self.memory.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if _matching_rows(db, where, parameters) != (preview.count, preview.match):
                raise ServiceError("The selection changed since the preview. Check the updated count.", 409)
            backup = self._backup()
            count = db.execute(f"DELETE FROM climate_readings WHERE {where}", parameters).rowcount
            self._audit(db, preview, backup, count)
        self.climate.archive.changed()
        return backup

    def _unpair_address(self, sensor_id, sensor):
        for device in self.climate.discovered().values():
            if _registered_id({sensor_id: sensor}, device) is not None:
                return device["ieee_address"]
        raise ServiceError("The sensor is missing from the Zigbee device list. Refresh the list or hide it locally.", 409)

    def _remove(self, preview):
        sensor_id = preview.scope["sensor_id"]
        sensor = self.climate.archive.registered().get(sensor_id)
        if sensor != preview.match:
            raise ServiceError("The sensor changed since the preview. Check it again.", 409)
        unpair = preview.action == "unpair"
        ieee = self._unpair_address(sensor_id, sensor) if unpair else sensor.ieee_address
        backup = self._backup()
        if unpair:
            self.climate.bridge_request("device/remove", {"id": ieee, "force": False}, timeout=20)
        with self.memory.connect() as db:
            db.execute("UPDATE climate_sensors SET hidden=1, detached=?, ieee_address=? WHERE id=?", (unpair, ieee, sensor_id))
            self._audit(db, preview, backup, 0)
        self.climate.sync_topics()
        return backup

    @staticmethod
    def _now():
        return time.time_ns() // 1_000_000

    def _audit(self, db, preview, backup, count):
        db.execute("""
            INSERT INTO climate_admin_log (at_ms, action, scope, readings_deleted, backup) VALUES (?, ?, ?, ?, ?)
        """, (self._now(), preview.action, json.dumps(preview.scope, sort_keys=True), count, backup))

    def _backup(self):
        source_path = self.memory.path.resolve()
        directory = source_path.parent / "climate-backups"
        partial = None
        try:
            directory.mkdir(mode=0o700, exist_ok=True)
            if directory.is_symlink():
                raise OSError("Backup directory is a symlink")
            if os.name == "posix":
                directory.chmod(0o700)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            handle, filename = tempfile.mkstemp(prefix=f"climate-{stamp}-", suffix=".partial", dir=directory)
            partial = Path(filename)
            os.close(handle)
            final = partial.with_suffix(".sqlite3")
            uri = source_path.as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=5)) as source, closing(sqlite3.connect(partial)) as target:
                source.backup(target)
                if target.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise sqlite3.DatabaseError("Backup integrity check failed")
            partial.replace(final)
            return final.name
        except (OSError, sqlite3.Error) as error:
            if partial is not None:
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass
            LOG.warning("Climate backup failed (%s)", type(error).__name__)
            raise ServiceError("Could not create the database backup. The operation was cancelled.", 503) from error
