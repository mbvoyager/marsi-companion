"""Cheap, explicitly estimated request timing; no server progress is implied."""
from collections import defaultdict, deque
from dataclasses import dataclass
from math import ceil
from statistics import median


class ResponseTimes:
    """Learn from the last five completed requests of each kind, in RAM only."""
    DEFAULTS = {"chat": 45, "chat-voice": 60, "voice": 75, "voice-silent": 60,
                "rite": 10, "archive": 5}

    def __init__(self):
        self.samples = defaultdict(lambda: deque(maxlen=5))

    def estimate(self, kind):
        samples = self.samples[kind]
        return max(5, min(180, median(samples) if samples else self.DEFAULTS.get(kind, 45)))

    def observe(self, kind, seconds):
        self.samples[kind].append(max(0, seconds))


@dataclass
class Transmission:
    kind: str
    text: str | None
    at: str
    started: float
    estimate: float

    def progress(self, now):
        elapsed = max(0, now - self.started)
        # Never claim completion while the request is still outstanding.
        percent = min(95, int(90 * elapsed / max(1, self.estimate)))
        filled = percent * 16 // 100
        bar = "#" * filled + "." * (16 - filled)
        timing = (f"{elapsed:.0f}s elapsed / ~{ceil(self.estimate - elapsed)}s remaining"
                  if elapsed < self.estimate else
                  f"{elapsed:.0f}s elapsed / a longer thought")
        return f"[COGITATOR / ESTIMATE]\n[{bar}] ~{percent}%\n{timing}\n\n"
