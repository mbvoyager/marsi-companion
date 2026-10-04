"""Original vector electoos: cached ironwork with inexpensive travelling signals."""
from __future__ import annotations

import math

BLACK, RED, GREEN = "#090708", "#b34d43", "#9fbf97"
BONE, BRASS, DIM = "#d8cbb0", "#a68b5c", "#4b332f"


class Electoo:
    def __init__(self, canvas, font, kind="band"):
        self.canvas, self.font, self.kind = canvas, font, kind
        self.key = None
        self.paths = []
        self.signals = []
        self.lenses = []

    def line(self, *points, color=BONE, width=1):
        return self.canvas.create_line(*points, fill=color, width=width)

    def ring(self, x, y, radius, color=BONE, teeth=12):
        c = self.canvas
        c.create_oval(x-radius, y-radius, x+radius, y+radius, outline=color, width=1)
        c.create_oval(x-radius*.5, y-radius*.5, x+radius*.5, y+radius*.5, outline=color)
        for tooth in range(teeth):
            angle = tooth * math.tau / teeth
            self.line(x + math.cos(angle)*radius, y + math.sin(angle)*radius,
                      x + math.cos(angle)*(radius+3), y + math.sin(angle)*(radius+3), color=color, width=2)

    def trace(self, points, color=DIM):
        self.line(*[v for point in points for v in point], color=color)
        self.paths.append(points)

    def band(self, w, h):
        c = self.canvas
        c.create_rectangle(0, 0, w, h, fill="#241111", outline="")
        for y in (3, h-4):
            self.line(0, y, w, y, color=RED)
        # Long parallel conductors with elbows and terminal rings, like an
        # illuminated manuscript rather than a random binary texture.
        for cell, x in enumerate(range(18, w, 112)):
            cy = h*.5
            self.ring(x, cy, min(12, h*.25), color=BRASS if cell % 3 == 0 else BONE)
            for lane in range(7):
                y = 6 + lane*3
                end = min(w-4, x+97)
                points = [(x+18, y), (x+48+lane*4, y),
                          (x+48+lane*4, h-y-1), (end, h-y-1)]
                self.trace(points, color=BRASS if lane % 3 == 0 else BONE)
            self.ring(x+79, cy, min(5, h*.18), color=BRASS, teeth=8)
            c.create_text(x+26, cy, text=("XII", "+O+", "III", "[V]")[cell % 4],
                          anchor="w", fill=BONE, font=(self.font, 7))
        for x in range(4, w, 12):
            self.line(x, 3, x+4, 7, x+8, 3, color=BRASS)
            self.line(x, h-4, x+4, h-8, x+8, h-4, color=BRASS)

    def rail(self, w, h):
        for lane in range(3):
            x = 3 + lane*4
            self.trace([(x, 2), (x, h-3)], BRASS if lane == 1 else DIM)
        for y in range(18, h, 58):
            self.ring(w*.5, y, 4, color=BONE, teeth=6)

    def effigy(self, w, h):
        c = self.canvas
        # Tall tapered reliquary, split skull, concentric sternum seal and
        # raised needle-finger manipulators echo the user's vertical reference.
        scale = min(w/250, h/230)
        ox, oy = w*.5, (h-230*scale)*.5
        def p(x, y):
            return ox+x*scale, oy+y*scale
        def line(coords, color=BONE, width=1):
            self.line(*[v for x, y in coords for v in p(x, y)], color=color, width=width)
        def oval(x, y, r, color=BONE, fill=""):
            a, b = p(x-r, y-r), p(x+r, y+r)
            return c.create_oval(*a, *b, outline=color, fill=fill)
        robe = [(-68, 6), (68, 6), (40, 128), (72, 221), (-72, 221), (-40, 128)]
        c.create_polygon(*[v for xy in robe for v in p(*xy)], fill="#311717", outline=RED)
        line([(-58, 11), (-28, 113), (0, 124), (28, 113), (58, 11)], BRASS)
        line([(-43, 10), (-19, 82), (0, 94), (19, 82), (43, 10)], DIM)
        # Hood contains a dark skull rather than a smiling cartoon face.
        line([(-18, 30), (0, 16), (18, 30), (15, 62), (7, 74), (-7, 74), (-15, 62)], BONE)
        line([(-18, 30), (18, 30)], BRASS)
        for x in (-8, 8):
            self.lenses.append(oval(x, 44, 4, GREEN if x > 0 else BRASS, BLACK))
        line([(-3, 54), (0, 49), (3, 54), (-3, 54)], BRASS)
        for x in (-8, -4, 0, 4, 8):
            line([(x, 60), (x, 69)], BONE)
        for sign in (-1, 1):
            # Ivory electoo strips follow the hood, with offset elbow tracks.
            for lane in range(4):
                coords = [(sign*(62-lane*4), 12), (sign*(39-lane*3), 91),
                          (sign*(39-lane*3), 105), (sign*12, 123)]
                self.trace([p(*xy) for xy in coords], BRASS if lane % 2 else BONE)
            for y in (27, 88):
                x = sign*(53 if y == 27 else 34)
                px, py = p(x, y)
                self.ring(px, py, 7*scale, color=BONE, teeth=8)
            # Raised hands have three articulated fingers and a central cog.
            arm = [(sign*38, 147), (sign*83, 180), (sign*107, 109)]
            for offset in (-4, 0, 4):
                line([(x+sign*offset, y) for x, y in arm], BRASS if offset else BONE)
            px, py = p(sign*102, 102)
            self.ring(px, py, 8*scale, color=BONE, teeth=8)
            for finger in range(3):
                line([(sign*(95+finger*7), 98), (sign*(98+finger*7), 79),
                      (sign*(94+finger*7), 62)], BONE)
            for lane in range(4):
                coords = [(sign*(20+lane*9), 210), (sign*(20+lane*9), 178),
                          (sign*(10+lane*8), 167), (sign*(10+lane*8), 155)]
                self.trace([p(*xy) for xy in coords], BRASS)
                oval(sign*(10+lane*8), 155, 2, BONE)
            line([(sign*4, 136), (sign*23, 141), (sign*40, 135)], BONE)
            line([(sign*4, 143), (sign*24, 148), (sign*45, 142)], BRASS)
        px, py = p(0, 121)
        self.ring(px, py, 18*scale, color=BRASS, teeth=16)
        self.ring(px, py, 10*scale, color=BONE, teeth=8)
        line([(0, 144), (0, 213)], BONE)
        c.create_text(*p(0, 190), text="I\nO\nI", fill=BONE, font=(self.font, max(6, int(8*scale))))
        c.create_text(w*.5, h-5, text="MARS // SEEK KNOWLEDGE", anchor="s", fill=BRASS,
                      font=(self.font, 7))

    @staticmethod
    def along(points, fraction):
        lengths = [math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(points, points[1:])]
        distance = fraction * sum(lengths)
        for a, b, length in zip(points, points[1:], lengths):
            if distance <= length and length:
                t = distance/length
                return a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t
            distance -= length
        return points[-1]

    def draw(self, now, mode="idle"):
        c = self.canvas
        w, h = max(1, c.winfo_width()), max(1, c.winfo_height())
        key = (w, h)
        if key != self.key:
            c.delete("all")
            self.paths, self.signals, self.lenses = [], [], []
            {"band": self.band, "rail": self.rail, "effigy": self.effigy}[self.kind](w, h)
            for _ in self.paths[::3]:
                self.signals.append(c.create_oval(0, 0, 3, 3, fill=GREEN, outline=""))
            self.key = key
        speed = {"idle": .11, "listening": .3, "thinking": .5, "speaking": .23}.get(mode, .11)
        color = GREEN if mode in ("listening", "speaking") else BONE
        for i, (item, path) in enumerate(zip(self.signals, self.paths[::3])):
            x, y = self.along(path, (now*speed + i*.137) % 1)
            c.coords(item, x-1.5, y-1.5, x+1.5, y+1.5)
            c.itemconfigure(item, fill=color)
        for i, item in enumerate(self.lenses):
            lit = mode != "idle" or math.sin(now*.7+i) > .6
            c.itemconfigure(item, fill=GREEN if lit else BLACK)
