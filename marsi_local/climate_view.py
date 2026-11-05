"""The Pi's climate tab, drawn with the same electoos as the journal."""
from __future__ import annotations

from datetime import datetime
from math import ceil, floor
import threading

from .client import ClientError
from .electoo import BLACK, BONE, BRASS, DIM, GREEN, RED, Electoo

PERIODS = (("now", "Jetzt"), ("3h", "3 h"), ("24h", "24 h"), ("7d", "7 Tage"))
COLORS = (GREEN, BRASS, RED, BONE)
DASHES = ((), (6, 3), (2, 3), (7, 3, 2, 3))
PANEL = "#191010"
SENSOR_STATES = {
    "fresh": ("EMPFANG", GREEN),
    "stale": ("SIGNAL ALT", RED),
    "waiting": ("WARTE AUF WERTE", BRASS),
}


class ClimateView:
    def __init__(self, parent, client, events, mono, button):
        import tkinter as tk
        from tkinter import font

        self.client, self.events, self.mono = client, events, mono
        self.stop = threading.Event()
        self.listener = None
        self.period, self.page = "now", 0
        self.snapshot = self.history = None
        self.feed_status = None
        self.history_busy = self.history_error = False
        self.history_at = 0.0
        self.dirty = True

        self.frame = tk.Frame(parent, bg=BLACK, highlightbackground=RED, highlightthickness=1)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        bar = tk.Frame(self.frame, bg=BLACK)
        bar.grid(row=0, column=0, sticky="ew", padx=5, pady=(3, 0))
        self.tabs = {}
        for key, label in PERIODS:
            tab = button(bar, label, lambda key=key: self.select(key))
            tab.pack(side="left", padx=1)
            self.tabs[key] = tab
        self.status = tk.Label(bar, text="[ VERBINDEN ]", bg=BLACK, fg=BRASS, font=(mono, -11), padx=4)
        self.status.pack(side="right")
        self.pages = tk.Frame(bar, bg=BLACK)
        self.previous = button(self.pages, "<", lambda: self.turn_page(-1))
        self.previous.pack(side="left")
        self.page_label = tk.Label(self.pages, bg=BLACK, fg=BONE, font=(mono, -11), padx=3)
        self.page_label.pack(side="left")
        self.next = button(self.pages, ">", lambda: self.turn_page(1))
        self.next.pack(side="left")

        self.canvas = tk.Canvas(self.frame, bg=BLACK, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self.invalidate)
        self.cog = Electoo(self.canvas, mono)
        self.title_font = font.Font(root=parent, family=mono, size=-13, weight="bold")
        self.label_font = font.Font(root=parent, family=mono, size=-11)
        self.select("now")

    def start(self):
        if self.listener is None:
            self.listener = threading.Thread(target=self.listen, daemon=True)
            self.listener.start()
        self.invalidate()

    def listen(self):
        delay = 1
        while not self.stop.is_set():
            try:
                for snapshot in self.client.climate_events(self.stop):
                    self.events.put(("climate", ("snapshot", snapshot)))
                    delay = 1
            except ClientError as error:
                self.events.put(("climate", ("offline", error.status)))
                self.stop.wait(delay)
                delay = min(8, delay * 2)

    def fetch_history(self, period):
        try:
            result = self.client.climate_history(period)
            if not isinstance(result.get("sensors"), list):
                result = None
        except ClientError:
            result = None
        self.events.put(("climate", ("history", (period, result))))

    def receive(self, kind, data, now):
        if kind == "snapshot":
            self.snapshot = data
            self.feed_status = None
            self.status.configure(text="[ LIVE ]", fg=GREEN)
            self.history_at = 0
        elif kind == "offline":
            self.feed_status = data
            self.status.configure(text="[ LINK PAUSE ]", fg=BRASS)
        elif kind == "history":
            self.history_busy = False
            period, result = data
            if period == self.period:
                self.history_error = result is None
                if result is None:
                    self.history_at = now + 5
                else:
                    self.history = result
        self.invalidate()

    def select(self, period):
        self.period, self.page = period, 0
        self.history = None
        self.history_error = False
        self.history_at = 0
        for key, tab in self.tabs.items():
            tab.configure(fg=GREEN if key == period else BONE, bg=PANEL if key == period else BLACK)
        self.invalidate()

    def turn_page(self, direction):
        self.page += direction
        self.invalidate()

    def invalidate(self, _event=None):
        self.dirty = True

    def tick(self, now):
        if self.period != "now" and not self.history_busy and now >= self.history_at:
            # Even in silence, history windows roll forward with the clock.
            self.history_at = now + 60
            self.history_busy = True
            threading.Thread(target=self.fetch_history, args=(self.period,), daemon=True).start()
        if self.dirty and self.canvas.winfo_ismapped():
            self.draw()
            self.dirty = False

    def page_of(self, sensors, size):
        count = max(1, ceil(len(sensors) / size))
        self.page = min(max(0, self.page), count - 1)
        if count > 1:
            if not self.pages.winfo_manager():
                self.pages.pack(side="right", padx=3)
            self.page_label.configure(text=f"{self.page + 1}/{count}")
            self.previous.configure(state="normal" if self.page > 0 else "disabled")
            self.next.configure(state="normal" if self.page < count - 1 else "disabled")
        else:
            self.pages.pack_forget()
        start = self.page * size
        return list(enumerate(sensors[start:start + size], start=start))

    def fit(self, text, width, font):
        limit = max(3, int(width / font.measure("M")))
        return text if len(text) <= limit else text[:limit - 3] + "..."

    def draw(self):
        c = self.canvas
        width, height = c.winfo_width(), c.winfo_height()
        c.delete("all")
        if self.period == "now" and self.snapshot and self.snapshot["sensors"]:
            self.draw_cards(self.snapshot["sensors"], width, height)
        elif self.period != "now" and self.history:
            self.draw_charts(self.history, width, height)
        else:
            self.pages.pack_forget()
            if self.feed_status in (404, 503):
                message = "Klima-Archiv auf Ubuntu pruefen."
            elif self.feed_status == 401:
                message = "Marsi-Token auf dem Pi pruefen."
            elif self.period != "now":
                message = "Messarchiv wird abgefragt ..." if not self.history_error else "Messarchiv wird erneut angefragt ..."
            else:
                message = "Warte auf das Klima-Archiv ..."
            self.cog.ring(width / 2, height / 2 - 17, 8, BRASS)
            c.create_text(width / 2, height / 2 + 9, text=message, fill=BONE, font=self.label_font)

    def draw_cards(self, sensors, width, height):
        columns = min(len(sensors), 2 if width >= 370 else 1)
        rows_per_page = 2 if height >= 182 else 1
        visible = self.page_of(sensors, columns * rows_per_page)
        rows = ceil(len(visible) / columns)
        w = (width - 16 - 8 * (columns - 1)) / columns
        h = min(150, (height - 16 - 8 * (rows - 1)) / rows)
        for position, (index, sensor) in enumerate(visible):
            x = 8 + (position % columns) * (w + 8)
            y = 8 + (position // columns) * (h + 8)
            self.draw_card(sensor, index, x, y, w, h)

    def draw_card(self, sensor, index, x, y, w, h):
        c = self.canvas
        accent = sensor.get("color") or COLORS[index % len(COLORS)]
        c.create_rectangle(x, y, x + w, y + h, outline=DIM, fill=PANEL, tags="climate-card")
        c.create_line(x, y + 19, x, y, x + 21, y, fill=accent, width=2)
        c.create_line(x + w - 21, y + h, x + w, y + h, x + w, y + h - 14, fill=accent)
        self.cog.ring(x + 13, y + 12, 4, accent, teeth=8)
        location = "AUSSEN" if sensor["location"] == "outdoor" else "INNEN"
        c.create_text(x + 24, y + 12, text=self.fit(sensor["name"], w - 94, self.title_font),
                      anchor="w", fill=BONE, font=self.title_font)
        c.create_text(x + w - 9, y + 12, text=f"[{location}]", anchor="e", fill=BRASS, font=self.label_font)
        readings = sensor["readings"]
        temperature = readings.get("temperature", {}).get("value")
        humidity = readings.get("humidity", {}).get("value")
        temp_text = "--" if temperature is None else f"{temperature:.1f}".replace(".", ",")
        humidity_text = "--" if humidity is None else f"{humidity:.1f}".replace(".", ",")
        c.create_text(x + 10, y + h * .44, text=temp_text + " °C", anchor="w", fill=GREEN,
                      font=(self.mono, -30 if h >= 110 else -22, "bold"), tags="climate-temperature")
        c.create_text(x + 11, y + h * .69, text=humidity_text + " % rF", anchor="w", fill=BONE,
                      font=(self.mono, -14 if h >= 110 else -12), tags="climate-humidity")
        observed = sensor.get("last_measurement_ms")
        stamp = "--" if observed is None else datetime.fromtimestamp(observed / 1000).strftime("%d.%m. %H:%M")
        label, color = SENSOR_STATES[sensor["status"]]
        c.create_text(x + 11, y + h - 9, text=stamp, anchor="w", fill=BRASS, font=self.label_font)
        c.create_text(x + w - 9, y + h - 9, text=label, anchor="e", fill=color, font=self.label_font)

    def draw_charts(self, history, width, height):
        sensors = self.page_of(history["sensors"], 4)
        columns = 4 if width >= 690 else 2
        column_width = (width - 16) / columns
        states = {sensor["id"]: sensor["status"] for sensor in (self.snapshot or {}).get("sensors", [])}
        for position, (index, sensor) in enumerate(sensors):
            x = 9 + (position % columns) * column_width
            y = 12 + (position // columns) * 15
            color = sensor.get("color") or COLORS[index % len(COLORS)]
            self.canvas.create_line(x, y, x + 20, y, fill=color, width=2, dash=DASHES[index % len(DASHES)])
            label = "AUSSEN " if sensor["location"] == "outdoor" else ""
            if states.get(sensor["id"]) == "stale":
                label += "ALT / "
            label += sensor["name"]
            self.canvas.create_text(x + 25, y, text=self.fit(label, column_width - 30, self.label_font),
                                    anchor="w", fill=BONE, font=self.label_font)
        top = 7 + 15 * ceil(len(sensors) / columns)
        chart_height = (height - top - 10) / 2
        self.plot(sensors, history, "temperature", "TEMPERATUR [°C]", top, chart_height, width)
        self.plot(sensors, history, "humidity", "LUFTFEUCHTE [% rF]", top + chart_height + 4,
                  chart_height, width, time_labels=True)

    def plot(self, sensors, history, metric, title, top, height, width, *, time_labels=False):
        c = self.canvas
        left, right = 47, width - 14
        ceiling, bottom = top + 20, top + height - (17 if time_labels else 4)
        if bottom <= ceiling or right <= left:
            return
        c.create_rectangle(8, top, width - 8, top + height, fill=PANEL, outline=DIM)
        c.create_text(13, top + 10, text=title, anchor="w", fill=BONE, font=self.title_font)
        values = [value for _, sensor in sensors for _, value in sensor["series"][metric]]
        low = floor(min(values)) if values else 0
        high = max(low + 2, ceil(max(values))) if values else (100 if time_labels else 30)
        if metric == "humidity" and high > 100:
            low, high = min(low, 98), 100
        for fraction in (0, .5, 1):
            y = bottom - fraction * (bottom - ceiling)
            c.create_line(left, y, right, y, fill=DIM)
            c.create_text(left - 5, y, text=f"{low + fraction * (high - low):g}", anchor="e",
                          fill=BRASS, font=self.label_font)
        start, end = history["from_ms"], history["to_ms"]
        for fraction, anchor in ((0, "nw"), (.5, "n"), (1, "ne")):
            x = left + fraction * (right - left)
            c.create_line(x, ceiling, x, bottom, fill=DIM)
            if time_labels:
                when = datetime.fromtimestamp((start + fraction * (end - start)) / 1000)
                stamp = when.strftime("%d.%m." if self.period == "7d" else "%H:%M")
                c.create_text(x, bottom + 3, text=stamp, anchor=anchor, fill=BRASS, font=self.label_font)
        if not values:
            c.create_text((left + right) / 2, (ceiling + bottom) / 2, text="Keine Messwerte im Zeitraum",
                          fill=BONE, font=self.label_font)
        gap = (self.snapshot or {}).get("stale_after_ms", 7_200_000)
        for index, sensor in sensors:
            color = sensor.get("color") or COLORS[index % len(COLORS)]
            coords, previous = [], None
            for at, value in sensor["series"][metric]:
                if previous is not None and at - previous >= gap:
                    self.trace(coords, color, DASHES[index % len(DASHES)])
                    coords = []
                x = left + (at - start) / max(1, end - start) * (right - left)
                y = bottom - (value - low) / (high - low) * (bottom - ceiling)
                coords.extend((x, y))
                previous = at
            self.trace(coords, color, DASHES[index % len(DASHES)])

    def trace(self, coords, color, dash):
        if len(coords) == 2:
            x, y = coords
            self.canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color, outline="", tags="climate-trace")
        elif coords:
            self.canvas.create_line(*coords, fill=color, width=2, dash=dash, tags="climate-trace")
