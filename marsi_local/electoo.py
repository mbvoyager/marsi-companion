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
        self.eyes = []
        self.grille = []
        self.figure_offset = (0, 0)
        self.head_offset = (0, 0)
        self.effigy_scale = 1

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
        # Original chibi adept: an oversized hood, large optical lenses and
        # mitten-like manipulators hugging a dataslate. The terminal's darker
        # electoo bands keep their own palette and geometry.
        scale = max(.01, min((w-10)/220, (h-18)/236))
        self.effigy_scale = scale
        ox, oy = w*.5, (h-236*scale)*.5-3
        gold, hood, cloth, metal = "#c5a260", "#882b30", "#5a2026", "#393e3c"
        cyan, rim = "#63d8df", "#235c62"
        def p(x, y):
            return ox+x*scale, oy+y*scale
        def tags(part):
            if part == "shadow":
                return ("effigy-shadow",)
            return ("effigy-figure", "effigy-" + part)
        def line(coords, color=BONE, width=1, part="body"):
            return c.create_line(*[v for xy in coords for v in p(*xy)], fill=color,
                                 width=max(1, width*scale), tags=tags(part))
        def oval(box, fill="", outline=gold, width=1, part="body"):
            return c.create_oval(*p(*box[:2]), *p(*box[2:]), fill=fill, outline=outline,
                                 width=max(1, width*scale), tags=tags(part))
        def polygon(points, fill, outline=gold, part="body"):
            return c.create_polygon(*[v for xy in points for v in p(*xy)], fill=fill,
                                    outline=outline, tags=tags(part))
        def curve(a, b, d, e):
            points = []
            for step in range(13):
                t, u = step/12, 1-step/12
                points.append(tuple(u**3*a[i] + 3*u*u*t*b[i] + 3*u*t*t*d[i] + t**3*e[i]
                                    for i in (0, 1)))
            return points
        oval((-59, 225, 59, 233), fill="#221817", outline="", part="shadow")
        # Short boots and a little bell-shaped robe, with a toothed gold hem.
        for sign in (-1, 1):
            x = sign*23
            oval((x-12, 208, x+12, 228), metal, BRASS)
            line([(x-5, 218), (x+4, 218)], DIM)
        polygon([(-38, 124), (38, 124), (46, 163), (60, 210), (44, 219),
                 (13, 223), (0, 217), (-13, 223), (-44, 219), (-60, 210)], cloth, RED)
        polygon([(-12, 137), (18, 138), (26, 215), (0, 217), (-25, 214)], hood, "")
        line([(-55, 208), (-42, 213), (-39, 207), (-31, 211), (-28, 218),
              (-12, 219), (0, 213), (12, 219), (28, 218), (31, 211),
              (39, 207), (42, 213), (55, 208)], gold, 3)
        # Robe seams carry a few sacred traces; animated beads are decorative.
        for sign in (-1, 1):
            points = [(sign*23, 194), (sign*23, 204), (sign*35, 204), (sign*35, 212)]
            line(points, BRASS)
            self.paths.append([p(*xy) for xy in points])
        oval((-31, 119, 31, 148), metal, BRASS)
        for sign in (-1, 1):
            polygon([(sign*36, 138), (sign*57, 146), (sign*65, 172),
                     (sign*46, 187), (sign*37, 164)], hood, RED)
        # The hood dominates the silhouette, with a dark face inside its trim.
        outline = (curve((-78, 118), (-107, 52), (-8, -30), (53, 6)) +
                   curve((53, 6), (73, 11), (88, 22), (92, 35)) +
                   curve((92, 35), (93, 42), (85, 43), (72, 44)) +
                   curve((72, 44), (93, 75), (98, 129), (64, 145)) +
                   curve((64, 145), (28, 154), (-56, 154), (-78, 118)))
        polygon(outline, hood, RED, "head")
        oval((-77, 8, 70, 141), "#9a3439", "", part="head")
        polygon([(54, 14), (77, 28), (87, 36), (67, 44), (77, 73),
                 (80, 108), (66, 131), (48, 145), (66, 141), (81, 119),
                 (88, 86), (73, 47), (90, 39)], "#672127", "", "head")
        oval((-68, 17, 68, 144), BLACK, gold, 3, "head")
        for i in range(17):
            angle = math.pi*.08 + i*math.tau/17
            x, y = math.cos(angle), math.sin(angle)
            line([(x*69, 81+y*63), (x*73, 81+y*67)], gold, 3, "head")
        polygon([(-15, 50), (0, 38), (15, 50), (24, 117), (-24, 117)],
                metal, "#515753", "head")
        # Large glass lenses get their own blink and gaze animation; the
        # bright cyan is confined to MARSI, leaving the approved HUD intact.
        for x in (-28, 28):
            oval((x-21, 52, x+21, 95), "#181d1c", "#646e66", 2, "head")
            lens = oval((x-17, 56, x+17, 91), cyan, rim, 2, "head")
            lower = oval((x-13, 72, x+12, 88), "#3da6b4", "", part="head")
            glow = oval((x-10, 59, x-2, 67), "#e2ffff", "", part="head")
            dot = oval((x+7, 80, x+11, 84), "#b6f4ee", "", part="head")
            closed = line([(x-15, 75), (x-8, 79), (x, 81), (x+8, 79), (x+15, 75)],
                          gold, 2, "head")
            c.itemconfigure(closed, state="hidden")
            eye_items = (lens, lower, glow, dot)
            self.eyes.append({"items": eye_items, "closed": closed,
                              "rest": [c.coords(item) for item in eye_items]})
        oval((-20, 88, 20, 125), metal, "#838b80", 2, "head")
        for x in (-8, -3, 3, 8):
            self.grille.append(line([(x, 101), (x, 115)], BRASS, 2, "head"))
        for sign in (-1, 1):
            tube = [(sign*17, 105), (sign*24, 111), (sign*29, 121),
                    (sign*37, 130), (sign*47, 132), (sign*54, 128)]
            line(tube, "#111413", 10, "head")
            line(tube, "#555b54", 6, "head")
            for x, y in tube[1:-1]:
                line([(x-3, y+2), (x+3, y-2)], "#222725", 1, "head")
        # A treasured dataslate, held close like the reference's little relic.
        polygon([(-42, 158), (31, 158), (43, 167), (43, 193), (-42, 193)], "#252a29", BRASS)
        polygon([(-42, 158), (31, 158), (31, 193), (-42, 193)], "#525953", BONE)
        polygon([(-34, 166), (23, 166), (23, 185), (-34, 185)], "#121d1b", BRASS)
        for lane in range(3):
            line([(-29, 171+lane*4), (-12+lane*5, 171+lane*4)], GREEN)
        for x in (3, 10, 17):
            oval((x-1, 175, x+1, 177), GREEN, "")
        for sign in (-1, 1):
            x = sign*43
            oval((x-12, 173, x+12, 188), metal, BRASS)
            line([(x-5, 180), (x+3, 182)], "#7c837a")
        # Tiny collar seal, deliberately simpler than the surrounding ornaments.
        px, py = p(0, 148)
        before = set(c.find_all())
        self.ring(px, py, 6*scale, gold, 8)
        for item in set(c.find_all()) - before:
            c.itemconfigure(item, tags=tags("body"))
        c.create_text(w*.5, h-5, text="MARS // SEEK KNOWLEDGE", anchor="s", fill=BRASS,
                      font=(self.font, 7))

    def animate_effigy(self, now, mode):
        c, scale = self.canvas, self.effigy_scale
        bob = math.sin(now*1.7)*1.5*scale
        # Listening leans towards the human's journal; thinking searches with
        # the eyes; speech has a soft nod instead of a flashing whole portrait.
        head_x = (-3 if mode == "listening" else math.sin(now*.7)*1.1)*scale
        head_y = (math.sin(now*5)*1.2 if mode == "speaking" else math.sin(now*.9)*.6)*scale
        old_x, old_y = self.figure_offset
        c.move("effigy-figure", -old_x, bob-old_y)
        self.figure_offset = (0, bob)
        c.move("effigy-head", head_x-self.head_offset[0], head_y-self.head_offset[1])
        self.head_offset = (head_x, head_y)
        blink = now % 5.6 < .24
        gaze = (-2.5 if mode == "listening" else math.sin(now*1.8)*2.2 if mode == "thinking" else math.sin(now*.55)) * scale
        for eye in self.eyes:
            c.itemconfigure(eye["closed"], state="normal" if blink else "hidden")
            for item, rest in zip(eye["items"], eye["rest"]):
                c.itemconfigure(item, state="hidden" if blink else "normal")
                c.coords(item, *[value + (head_x+gaze if i % 2 == 0 else bob+head_y)
                                 for i, value in enumerate(rest)])
        for i, item in enumerate(self.grille):
            c.itemconfigure(item, fill=BONE if mode == "speaking" and int(now*5+i) % 3 == 0 else BRASS)

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
            self.eyes, self.grille = [], []
            self.figure_offset = self.head_offset = (0, 0)
            {"band": self.band, "rail": self.rail, "effigy": self.effigy}[self.kind](w, h)
            for _ in self.paths[::3]:
                self.signals.append(c.create_oval(0, 0, 3, 3, fill=GREEN, outline=""))
            self.key = key
        if self.kind == "effigy":
            self.animate_effigy(now, mode)
        speed = {"idle": .11, "listening": .3, "thinking": .5, "speaking": .23}.get(mode, .11)
        color = GREEN if mode in ("listening", "speaking") else BONE
        for i, (item, path) in enumerate(zip(self.signals, self.paths[::3])):
            x, y = self.along(path, (now*speed + i*.137) % 1)
            if self.kind == "effigy":
                x, y = x+self.figure_offset[0], y+self.figure_offset[1]
            c.coords(item, x-1.5, y-1.5, x+1.5, y+1.5)
            c.itemconfigure(item, fill=color)
        for i, item in enumerate(self.lenses):
            lit = mode != "idle" or math.sin(now*.7+i) > .6
            c.itemconfigure(item, fill=GREEN if lit else BLACK)
