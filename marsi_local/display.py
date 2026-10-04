"""A phosphor archive with original ASCII artwork and read-only machine cant."""
from __future__ import annotations

import base64
from datetime import datetime
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from .ambient import Ambient, quiet_hour
from .client import ClientError, HELP, command
from .liturgy import BLACK, GREEN, RED, without_emoji
from .electoo import BONE, BRASS, Electoo
from .telemetry import Telemetry, reading
from .config import ROOT
from .audio import CHECK_COMMAND


class Display:
    def __init__(self, root, client, windowed=False):
        import tkinter as tk
        from tkinter import font as tkfont
        self.tk, self.root, self.client = tk, root, client
        self.mono = tkfont.nametofont("TkFixedFont").actual("family")
        self.events = queue.Queue()
        self.busy = self.recording = self.closed = self.polling = False
        self.stop = threading.Event()
        self.mode, self.animation = "idle", "happy"
        self.last_interaction = time.monotonic()
        self.playback = None
        self.generation = 0
        self.entries = {}
        self.cursor = self.before = 0
        self.has_more = False
        self.restored = False
        self.last_poll = 0.0
        self.local = Telemetry()
        self.readings = {"pi": None, "server": None}
        self.pending_spoken = None
        state_dir = Path(os.getenv("MARSI_PI_STATE_DIR", str(ROOT / "data")))
        self.voice_marker = state_dir / ("pi-voice-" + client.session + ".txt")
        try:
            self.last_spoken = int(self.voice_marker.read_text())
        except (OSError, ValueError):
            self.last_spoken = 0
        self.hotkey_held = False
        self.hotkey_release = None
        self.ambient = Ambient(
            minimum=float(os.getenv("MARSI_RITUAL_MIN_SECONDS", "600")),
            maximum=float(os.getenv("MARSI_RITUAL_MAX_SECONDS", "1200")),
            quiet_start=int(os.getenv("MARSI_QUIET_START", "22")),
            quiet_end=int(os.getenv("MARSI_QUIET_END", "8")),
        )
        self.speak = tk.BooleanVar(value=os.getenv("MARSI_SPEAK", "true").lower() == "true")
        self.rituals = tk.BooleanVar(value=os.getenv("MARSI_RITUALS", "true").lower() == "true")
        self.ritual_speech = os.getenv("MARSI_RITUAL_SPEECH", "false").lower() == "true"
        self.observance_speech = os.getenv("MARSI_OBSERVANCE_SPEECH", "true").lower() == "true"
        self.morning_override = os.getenv("MARSI_MORNING_SPEECH_DURING_QUIET", "true").lower() == "true"
        root.title("MARSI // ARCHIVUM MARTIS")
        root.geometry("800x480")
        root.minsize(480, 320)
        root.configure(bg=BLACK)
        root.attributes("-fullscreen", not windowed)
        root.bind("<Escape>", lambda event: root.attributes("-fullscreen", False))
        root.bind("<Control-q>", lambda event: self.close())
        root.bind("<KeyPress-F8>", self.hotkey)
        root.bind("<KeyRelease-F8>", self.release_hotkey)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        self.frieze = tk.Canvas(root, bg=BLACK, highlightthickness=0, height=52)
        self.frieze.grid(row=0, column=0, sticky="ew")
        self.status = tk.StringVar(value="[BOOT] Opening the machine-flow aperture...")
        tk.Label(root, textvariable=self.status, bg=BLACK, fg=BRASS,
                 font=(self.mono, 9), anchor="w", padx=8, pady=4).grid(row=1, column=0, sticky="ew")
        body = tk.Frame(root, bg=BLACK)
        body.grid(row=2, column=0, sticky="nsew", padx=7)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        archive = tk.Frame(body, bg=BLACK, highlightbackground=RED, highlightthickness=1)
        archive.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        archive.columnconfigure(1, weight=1)
        archive.rowconfigure(1, weight=1)
        tools = tk.Frame(archive, bg=BLACK)
        tools.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.older = self.button(tools, "[ OLDER TRANSMISSIONS ]", self.load_older)
        self.older.pack(side="left", expand=True, fill="x")
        self.button(tools, "LATEST", self.jump_latest).pack(side="right")
        self.rail = tk.Canvas(archive, bg=BLACK, highlightthickness=0, width=17)
        self.rail.grid(row=1, column=0, sticky="ns")
        self.archive_font = tkfont.Font(family=self.mono, size=10)
        self.reply = tk.Text(archive, bg=BLACK, fg=BONE, font=self.archive_font,
                             wrap="word", relief="flat", padx=8, pady=6, state="disabled",
                             selectbackground=RED, selectforeground=GREEN, insertbackground=GREEN,
                             width=1, height=1)
        self.reply.grid(row=1, column=1, sticky="nsew")
        self.reply.tag_configure("human", foreground=GREEN)
        self.reply.tag_configure("marsi", foreground=BONE)
        self.reply.tag_configure("system", foreground=BRASS)
        self.scroll = tk.Canvas(archive, bg=BLACK, highlightthickness=0, width=10)
        self.scroll.grid(row=1, column=2, sticky="ns")
        def scroll_change(first, last):
            height = max(1, self.scroll.winfo_height())
            self.scroll.delete("all")
            self.scroll.create_rectangle(2, float(first) * height, 8,
                                         max(float(first) * height + 8, float(last) * height), fill=RED, outline="")
        self.scroll_change = scroll_change
        self.reply.configure(yscrollcommand=scroll_change)
        self.scroll.bind("<Configure>", lambda event: scroll_change(*self.reply.yview()))
        for event in ("<Button-1>", "<B1-Motion>"):
            self.scroll.bind(event, lambda event: self.reply.yview_moveto(event.y / max(1, self.scroll.winfo_height())))
        side = tk.Frame(body, bg=BLACK, width=252)
        side.grid(row=0, column=1, sticky="ns")
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(1, weight=1)
        self.unit_label = tk.Label(side, text="[ MARSI / MARS RELIQUARY ]", bg=BLACK, fg=BONE,
                                   font=(self.mono, 10, "bold"))
        self.unit_label.grid(row=0, column=0, sticky="ew")
        self.canvas = tk.Canvas(side, bg=BLACK, highlightthickness=0, height=180, width=249)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.meters = tk.StringVar()
        self.meter_label = tk.Label(side, textvariable=self.meters, bg=BLACK, fg=GREEN,
                                   font=(self.mono, 8), justify="left", anchor="nw")
        self.meter_label.grid(row=2, column=0, sticky="nw")
        self.seal = tk.Label(side, text="[ AWAITING DATA ]\nKNOWLEDGE IS THE OFFERING", bg=BLACK, fg=BRASS,
                            font=(self.mono, 8), justify="left")
        self.seal.grid(row=3, column=0, sticky="sw", pady=3)
        self.lower_frieze = tk.Canvas(root, bg=BLACK, highlightthickness=0, height=24)
        self.lower_frieze.grid(row=3, column=0, sticky="ew", pady=(3, 0))
        self.electoos = [Electoo(self.frieze, self.mono), Electoo(self.lower_frieze, self.mono),
                        Electoo(self.rail, self.mono, "rail"), Electoo(self.canvas, self.mono, "effigy")]
        controls = tk.Frame(root, bg=BLACK)
        controls.grid(row=4, column=0, sticky="ew", padx=7, pady=5)
        controls.columnconfigure(1, weight=1)
        tk.Label(controls, text=">", bg=BLACK, fg=GREEN, font=(self.mono, 12)).grid(row=0, column=0)
        self.input = tk.Entry(controls, bg=BLACK, fg=GREEN, insertbackground=GREEN,
                              selectbackground=RED, relief="flat", highlightthickness=1,
                              highlightbackground=RED, highlightcolor=GREEN, font=(self.mono, 11))
        self.input.grid(row=0, column=1, sticky="ew", padx=4)
        self.input.bind("<Return>", lambda event: self.send_text())
        self.send = self.button(controls, "SEND", self.send_text)
        self.send.grid(row=0, column=2, padx=2)
        self.talk = self.button(controls, "TALK [F8]", self.toggle_record)
        self.talk.grid(row=0, column=3, padx=2)
        options = tk.Frame(controls, bg=BLACK)
        options.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        for label, variable in (("Voice", self.speak), ("Idle rites", self.rituals)):
            toggle = self.button(options, ("[X] " if variable.get() else "[ ] ") + label,
                                 lambda variable=variable: variable.set(not variable.get()))
            toggle.configure(fg=GREEN)
            toggle.pack(side="left", padx=1)
            variable.trace_add("write", lambda *args, label=label, variable=variable, toggle=toggle:
                               toggle.configure(text=("[X] " if variable.get() else "[ ] ") + label))
        for label, action in (("ART", self.manual_art), ("BLESS", self.manual_ritual),
                              ("FORGET", self.forget), ("HELP", lambda: self.show_text(HELP))):
            self.button(options, label, action).pack(side="left", padx=2)
        root.bind("<Configure>", lambda event: self.resize() if event.widget is root else None)
        self.side = side
        self.show_text("ARCHIVUM MARTIS // MACHINE-FLOW APERTURE\n"
                       "Mars reliquary -> near-side Terra\n"
                       "Bring me an observation, little keeper.\nType help for the local command cant.")
        self.resize()
        self.input.focus_set()
        root.after(50, self.tick)

    def button(self, parent, text, action):
        return self.tk.Button(parent, text=text, command=action, bg=BLACK, fg=RED,
                              activebackground=RED, activeforeground=GREEN, disabledforeground=RED,
                              relief="flat", highlightbackground=RED, highlightthickness=1,
                              borderwidth=0, font=(self.mono, 9), padx=4, pady=2)

    def resize(self):
        compact = self.root.winfo_width() < 640 or self.root.winfo_height() < 400
        self.side.configure(width=142 if compact else 252)
        self.canvas.configure(height=86 if compact else 160, width=139 if compact else 249)
        self.frieze.configure(height=30 if compact else 52)
        self.lower_frieze.configure(height=18 if compact else 24)
        size = 8 if compact else 10
        available = max(60, self.root.winfo_width() - (142 if compact else 252) - 54)
        self.archive_font.configure(size=size)
        while size > 5 and self.archive_font.measure("+" + "=" * 38 + "+") > available - 16:
            size -= 1
            self.archive_font.configure(size=size)
        self.meter_label.configure(font=(self.mono, 7 if compact else 8))
        self.unit_label.configure(text="[ MARSI / MARS ]" if compact else "[ MARSI / MARS RELIQUARY ]",
                                  font=(self.mono, 7 if compact else 10, "bold"))
        if compact:
            self.seal.grid_remove()
        else:
            self.seal.grid()

    def show_text(self, text, tag="system"):
        bottom = self.reply.yview()[1] >= 0.98
        self.reply.configure(state="normal")
        self.reply.insert("end", without_emoji(text) + "\n\n", tag)
        self.reply.configure(state="disabled")
        if bottom:
            self.reply.see("end")

    def formatted(self, entry):
        try:
            stamp = datetime.fromisoformat(entry["at"]).astimezone().strftime("%d.%m %H:%M")
        except ValueError:
            stamp = "ARCHIVE"
        label = "HUMAN" if entry["role"] == "human" else "MARSI"
        return f"[{stamp} / {entry['kind'].upper()}] {label} >\n{without_emoji(entry['text'])}\n\n"

    def receive_entries(self, entries, *, older=False, initial=False):
        new = [entry for entry in entries if entry["id"] not in self.entries]
        if not new:
            return
        previous_last = max(self.entries, default=0)
        bottom = self.reply.yview()[1] >= 0.98
        for entry in new:
            self.entries[entry["id"]] = entry
        self.before = min(self.entries)
        self.reply.configure(state="normal")
        if older:
            for entry in reversed(new):
                self.reply.insert("1.0", self.formatted(entry), entry["role"])
            self.reply.see("1.0")
        else:
            for entry in new:
                self.reply.insert("end", self.formatted(entry), entry["role"])
                if entry.get("scheduled") and entry["kind"] in ("morning", "sermon") and entry.get("spoken_text") and entry["id"] > self.last_spoken:
                    self.pending_spoken = entry
        out_of_order = not older and min(entry["id"] for entry in new) < previous_last
        if len(self.entries) > 600 or out_of_order:
            ordered = sorted(self.entries)
            keep = (ordered[:500] if older else ordered[-500:]) if len(ordered) > 600 else ordered
            self.entries = {key: self.entries[key] for key in keep}
            self.before = min(keep)
            self.reply.delete("1.0", "end")
            for key in keep:
                entry = self.entries[key]
                self.reply.insert("end", self.formatted(entry), entry["role"])
        self.reply.configure(state="disabled")
        if (bottom or initial) and not older:
            self.reply.see("end")

    def poll(self, older=False):
        if self.polling or self.closed:
            return
        self.polling = True
        generation, cursor, before = self.generation, self.cursor, self.before
        initial = not self.restored
        def collect():
            try:
                if older:
                    page = self.client.journal(before=before)
                    self.events.put(("archive", (generation, page, True, False)))
                else:
                    local = self.local.snapshot()
                    self.events.put(("local", local))
                    readings = self.client.telemetry(local)
                    self.events.put(("telemetry", readings))
                    page = self.client.journal(after=cursor)
                    self.events.put(("archive", (generation, page, False, initial)))
            except (ClientError, ValueError):
                self.events.put(("offline", None))
            finally:
                self.events.put(("polled", None))
        threading.Thread(target=collect, daemon=True).start()

    def load_older(self):
        if self.before and self.has_more:
            self.poll(older=True)
        else:
            self.status.set("[ARCHIVE] No older transmissions in this session.")

    def set_busy(self, busy, mode="idle"):
        self.busy, self.mode = busy, mode
        self.send.configure(state="disabled" if busy else "normal")
        self.talk.configure(state="normal" if self.recording or not busy else "disabled")

    def jump_latest(self):
        if self.closed:
            return
        self.generation += 1
        self.entries.clear()
        self.cursor = self.before = 0
        self.restored = self.has_more = False
        self.reply.configure(state="normal")
        self.reply.delete("1.0", "end")
        self.reply.configure(state="disabled")
        self.last_poll = 0

    def worker(self, task, speak):
        from .pi import play
        try:
            result = task()
            self.events.put(("reply", result))
            if speak and result.get("audio_base64"):
                self.events.put(("speaking", None))
                try:
                    play(base64.b64decode(result["audio_base64"], validate=True), self.set_playback)
                    if result.get("entry_id"):
                        self.events.put(("spoken", result["entry_id"]))
                except (OSError, subprocess.SubprocessError, ValueError) as error:
                    self.events.put(("warning", f"[VOX] {error}. Run {CHECK_COMMAND}"))
        except Exception as error:
            detail = str(error) if isinstance(error, (ClientError, ValueError)) else "Request failed. Check the Pi display log and server diagnostics."
            self.events.put(("error", detail))
        finally:
            self.events.put(("done", None))

    def start_task(self, task, speak=False):
        self.set_busy(True, "thinking")
        self.status.set("[COGITATOR] Consulting the little archive...")
        threading.Thread(target=self.worker, args=(task, speak), daemon=True).start()

    def send_text(self):
        text = self.input.get().strip()
        action = command(text)
        if action == "exit":
            self.close()
            return
        if self.busy or not text:
            return
        self.input.delete(0, "end")
        self.last_interaction = time.monotonic()
        if action == "help":
            self.show_text(HELP)
        elif action == "forget":
            self.forget()
        elif action == "history":
            self.load_older()
        elif action == "notes":
            self.start_task(lambda: {"text": "Saved notes:\n" + "\n".join(self.client.notes()["notes"]), "source": "system"})
        elif text.startswith("/remember "):
            self.start_task(lambda: {"text": "Saved notes:\n" + "\n".join(self.client.remember(text[10:])["notes"]), "source": "system"})
        else:
            speak = self.speak.get()
            task = {"art": self.client.art, "sermon": self.client.sermon, "ritual": self.client.ritual}.get(action)
            self.start_task(lambda: task(speak) if task else self.client.chat(text, speak), speak)

    def hotkey(self, event):
        if self.hotkey_release is not None:
            self.root.after_cancel(self.hotkey_release)
            self.hotkey_release = None
        if not self.hotkey_held:
            self.hotkey_held = True
            self.toggle_record()
        return "break"

    def release_hotkey(self, event):
        def released():
            self.hotkey_held = False
            self.hotkey_release = None
        self.hotkey_release = self.root.after(40, released)
        return "break"

    def toggle_record(self):
        from .pi import record
        if self.recording:
            self.stop.set()
            self.recording = False
            self.talk.configure(text="TALK [F8]", state="disabled")
            self.mode = "thinking"
            self.status.set("[AUDITORY] Recording sealed; consulting the cogitator...")
        elif not self.busy:
            self.last_interaction = time.monotonic()
            self.recording = True
            self.stop = threading.Event()
            self.set_busy(True, "listening")
            self.talk.configure(text="FINISH [F8]")
            self.status.set("[AUDITORY] Listening. Press F8 / Finish. Maximum 15 seconds.")
            speak = self.speak.get()
            def capture():
                recording = record(self.stop)
                self.events.put(("recorded", None))
                if self.closed:
                    raise ValueError("Marsi has closed.")
                return self.client.voice(recording, speak)
            threading.Thread(target=self.worker, args=(capture, speak), daemon=True).start()

    def manual_art(self):
        if not self.busy:
            self.last_interaction = time.monotonic()
            speak = self.speak.get()
            self.start_task(lambda: self.client.art(speak), speak)

    def manual_ritual(self):
        if not self.busy:
            self.last_interaction = time.monotonic()
            speak = self.speak.get()
            self.start_task(lambda: self.client.ritual(speak), speak)

    def forget(self):
        if self.busy:
            return
        from tkinter import messagebox
        if messagebox.askyesno("Forget this session?", "Delete this session's server journal, working context and saved notes? Backups are separate.", parent=self.root):
            self.last_interaction = time.monotonic()
            self.generation += 1
            def erase():
                self.client.forget()
                return {"text": "A clean little dataslate. This session has been forgotten. ^^", "source": "forgotten"}
            self.start_task(erase)

    def scheduled_voice(self, now):
        entry = self.pending_spoken
        if not entry or self.busy:
            return
        age = (datetime.now().astimezone() - datetime.fromisoformat(entry["at"])).total_seconds()
        if age > 600 or not self.speak.get() or not self.rituals.get() or not self.observance_speech:
            self.pending_spoken = None
            return
        allowed = not quiet_hour(datetime.now().hour, self.ambient.quiet_start, self.ambient.quiet_end)
        if entry["kind"] == "morning" and self.morning_override:
            allowed = True
        if allowed and now - self.last_interaction >= 10:
            self.pending_spoken = None
            self.start_task(lambda: self.client.speak_entry(entry["id"]), True)

    def tick(self):
        if self.closed:
            return
        while True:
            try:
                kind, result = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "reply":
                self.animation = result.get("animation", "happy")
                if result.get("source") == "forgotten":
                    self.entries.clear()
                    self.cursor = self.before = 0
                    self.has_more = self.restored = False
                    self.pending_spoken = None
                    self.reply.configure(state="normal")
                    self.reply.delete("1.0", "end")
                    self.reply.configure(state="disabled")
                if result.get("entries"):
                    self.receive_entries(result["entries"])
                elif result.get("source") != "playback":
                    self.show_text(result["text"])
                self.status.set("[HEARD] " + result["heard"][:80] if result.get("heard") else "[RECEIVED] Transmission sealed.")
                if result.get("voice_error"):
                    self.status.set("[VOX] " + result["voice_error"])
            elif kind == "archive":
                generation, page, older, initial = result
                if generation != self.generation:
                    continue
                self.receive_entries(page["entries"], older=older, initial=initial)
                if page["entries"] and not older:
                    self.cursor = max(self.cursor, max(entry["id"] for entry in page["entries"]))
                if older or initial:
                    self.has_more = page["has_more"]
                self.restored = True
                self.older.configure(state="normal" if self.has_more else "disabled")
                if page["has_more"] and not older and not initial:
                    self.last_poll = 0
                if self.status.get().startswith(("[BOOT]", "[LINK SILENT]")):
                    self.status.set("[LINK] Archive open. Type help / press F8 to talk. ^^")
            elif kind == "telemetry":
                self.readings = result
            elif kind == "local":
                self.readings["pi"] = result
            elif kind == "offline":
                self.readings["server"] = None
                if not self.busy:
                    self.status.set("[LINK SILENT] Retrying archive and machine readings...")
            elif kind == "polled":
                self.polling = False
            elif kind == "speaking":
                self.mode = "speaking"
            elif kind == "spoken":
                self.last_spoken = max(self.last_spoken, result)
                try:
                    self.voice_marker.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.voice_marker.with_suffix(".tmp")
                    temporary.write_text(str(self.last_spoken))
                    temporary.replace(self.voice_marker)
                except OSError:
                    self.status.set("[VOX] Could not save the spoken-observance marker.")
            elif kind == "audio_status":
                self.show_text("[VOX / LOCAL CHECK]\n" + "\n".join(result)
                               + "\nClose Marsi, then run " + CHECK_COMMAND)
            elif kind in ("warning", "error"):
                self.status.set(result)
                self.show_text("[UNSEALED / " + kind.upper() + "] " + result)
            elif kind == "recorded":
                self.recording = False
                self.mode = "thinking"
                self.talk.configure(text="TALK [F8]", state="disabled")
            elif kind == "done":
                self.recording = False
                self.talk.configure(text="TALK [F8]")
                self.set_busy(False)
                self.last_interaction = time.monotonic()
                self.last_poll = 0
        now = time.monotonic()
        if now - self.last_poll >= 10 and not self.polling:
            self.last_poll = now
            self.poll()
        self.scheduled_voice(now)
        if self.restored and self.ambient.due(now, datetime.now().hour, self.last_interaction, self.busy, self.rituals.get()):
            speak = self.ritual_speech and self.speak.get()
            self.start_task(lambda: self.client.ritual(speak), speak)
        self.draw(now)
        self.root.after(200, self.tick)

    def draw(self, now):
        for electoo in self.electoos:
            electoo.draw(now, self.mode)
        phrases = {"listening": "[ RECEIVING / VOX ]\nEVERY WORD, A DATUM",
                   "thinking": "[ CORRELATING DATA ]\nSEEK THE HIDDEN PATTERN",
                   "speaking": "[ TRANSMITTING / VOX ]\nKNOWLEDGE RETURNS TO TERRA"}
        self.seal.configure(text=phrases.get(self.mode, "[ AWAITING DATA ]\nKNOWLEDGE IS THE OFFERING"))
        meters = []
        for name in ("pi", "server"):
            data = self.readings.get(name)
            if data is None:
                meters.extend((name.upper() + " / LINK SILENT", "DATA UNAVAILABLE"))
                continue
            meters.extend((f"{name.upper()} CPU {reading(data.get('cpu_percent'), '%')} / {reading(data.get('temperature_c'), 'C')}",
                           f"LOAD {reading(data.get('load1'))} / DISK {reading(data.get('disk_used_percent'), '%')}"))
        self.meters.set("\n".join(meters))

    def close(self):
        self.closed = True
        self.stop.set()
        if self.playback is not None:
            try:
                self.playback.terminate()
            except OSError:
                pass
        self.root.destroy()

    def set_playback(self, process):
        self.playback = process
        if self.closed and process is not None:
            try:
                process.terminate()
            except OSError:
                pass
