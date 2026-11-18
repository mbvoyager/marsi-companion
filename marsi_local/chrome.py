"""Original, static cogitator ironwork. Redraw only when a panel changes size."""
import math
from .theme import AMBER, BLACK, BRASS, DIM, PANEL, sensor_style


def cog(canvas, x, y, radius=5, color=BRASS):
    canvas.create_oval(x-radius, y-radius, x+radius, y+radius, outline=color)
    for tooth in range(8):
        a = tooth * math.tau / 8
        canvas.create_line(x+math.cos(a)*radius, y+math.sin(a)*radius,
                           x+math.cos(a)*(radius+2), y+math.sin(a)*(radius+2), fill=color)


def sensor_mark(canvas, x, y, style, size=4, **kwargs):
    color = style["color"]
    box = (x-size, y-size, x+size, y+size)
    options = dict(fill=color, outline=color, **kwargs)
    if style["shape"] == "circle":
        return canvas.create_oval(*box, **options)
    if style["shape"] == "square":
        return canvas.create_rectangle(*box, **options)
    points = ((x, y-size, x+size, y, x, y+size, x-size, y) if style["shape"] == "diamond"
              else (x, y-size, x+size, y+size, x-size, y+size))
    return canvas.create_polygon(*points, **options)


class Chrome:
    def __init__(self, canvas, font, title):
        self.canvas, self.font, self.title = canvas, font, title
        self.key = None

    def draw(self):
        c = self.canvas
        w, h = c.winfo_width(), c.winfo_height()
        if (w, h) == self.key:
            return
        self.key = w, h
        c.delete("chrome")
        cut = min(9, h/4)
        coords = (cut, 1, w-cut, 1, w-1, cut, w-1, h-cut, w-cut, h-1,
                  cut, h-1, 1, h-cut, 1, cut)
        c.create_polygon(*coords, fill=BLACK, outline=DIM, tags="chrome")
        c.create_line(9, h-5, w-9, h-5, fill=DIM, tags="chrome")
        for x in (6, w-6):
            c.create_rectangle(x-1, 5, x+1, 7, fill=BRASS, outline="", tags="chrome")
        c.create_text(14, h/2-1, anchor="w", text="++ " + self.title + " ++",
                      fill=AMBER, font=(self.font, -13), tags="chrome")
