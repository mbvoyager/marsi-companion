"""Reveal complete Tk replies with one moving block; never delay the audio."""


class Typewriter:
    def __init__(self, widget, reduced=False):
        self.widget, self.reduced = widget, reduced
        self.jobs = {}
        self.counter = 0

    def add(self, start, text):
        if self.reduced or not text:
            return
        self.counter += 1
        hidden, cursor = f"reveal-{self.counter}", f"block-{self.counter}"
        w = self.widget
        w.tag_configure(hidden, elide=True)
        w.tag_configure(cursor, foreground="#ffb000")
        w.tag_add(hidden, start, f"{start}+{len(text)}c")
        w.insert(start, "▌", cursor)
        self.jobs[hidden] = (cursor, max(5,(len(text)+69)//70))

    def finish(self):
        w = self.widget
        state = w.cget("state")
        w.configure(state="normal")
        for hidden, (cursor, _) in self.jobs.items():
            ranges = w.tag_ranges(cursor)
            if ranges:
                w.delete(*ranges)
            w.tag_delete(hidden,cursor)
        self.jobs.clear()
        w.configure(state=state)

    def tick(self):
        if not self.jobs:
            return
        w = self.widget
        bottom = w.yview()[1] >= .98
        w.configure(state="normal")
        for hidden, (cursor, batch) in list(self.jobs.items()):
            ranges = w.tag_ranges(cursor)
            if ranges:
                w.delete(*ranges)
            remaining = w.tag_ranges(hidden)
            if not remaining:
                w.tag_delete(hidden,cursor)
                self.jobs.pop(hidden)
                continue
            start,end = remaining
            next_at = w.index(f"{start}+{batch}c")
            if w.compare(next_at, ">=", end):
                w.tag_delete(hidden,cursor)
                self.jobs.pop(hidden)
            else:
                w.tag_remove(hidden,start,next_at)
                w.insert(next_at,"▌",cursor)
        w.configure(state="disabled")
        if bottom:
            w.see("end")
