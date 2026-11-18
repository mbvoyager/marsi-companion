"""Cached Tk scenes. Animation changes existing items only, at most 15 fps."""
import math
import random
import textwrap

from .chrome import sensor_mark
from .interludes import TYPES
from .theme import AMBER, BLACK, BONE, BRASS, DIM, FAULT, GREEN

TITLES = {"auspex": "AUSPEX DOMUS", "vox": "TRANSMISSIO VOX", "servitor": "RELATIO SERVITOR",
          "hololith": "HOLOLITH", "codex": "FRAGMENTUM CODEX", "noosphere": "NOOSPHERIC TRANSIT"}


class SceneRandom:
    """Portable decorative PRNG, identical to the browser's 32-bit sequence."""
    def __init__(self, seed):
        self.state = seed

    def random(self):
        self.state = (1664525*self.state+1013904223) & 0xffffffff
        return self.state/4294967296

    def randrange(self, stop):
        return int(self.random()*stop)


def wire_model(kind):
    points, edges = [], []
    if kind == "planet":
        for latitude in (-.7, 0, .7):
            offset = len(points)
            for i in range(24):
                a = math.tau*i/24
                points.append((math.cos(a)*math.sqrt(1-latitude**2), latitude, math.sin(a)*math.sqrt(1-latitude**2)))
                edges.append((offset+i, offset+(i+1) % 24))
        for i in range(0, 24, 4):
            edges.extend(((i, 24+i), (24+i, 48+i)))
    elif kind == "skull":
        outline = ((-.55,-.85),(.55,-.85),(.9,-.45),(.8,.25),(.45,.45),(.35,.85),(-.35,.85),(-.45,.45),(-.8,.25),(-.9,-.45))
        for z in (-.25, .25):
            points.extend((x, y, z) for x, y in outline)
        n = len(outline)
        edges.extend((offset+i, offset+(i+1) % n) for offset in (0, n) for i in range(n))
        edges.extend((i, n+i) for i in range(n))
        for x in (-.32, .32):
            offset = len(points)
            points.extend(((x-.17,-.25,-.3),(x+.17,-.25,-.3),(x+.17,.05,-.3),(x-.17,.05,-.3)))
            edges.extend((offset+i, offset+(i+1) % 4) for i in range(4))
    else:
        for z in (-.22, .22):
            for i in range(48):
                a = math.tau*i/48
                radius = 1 if i % 4 in (0, 3) else .8
                points.append((math.cos(a)*radius, math.sin(a)*radius, z))
        edges.extend((offset+i, offset+(i+1) % 48) for offset in (0, 48) for i in range(48))
        edges.extend((i, i+48) for i in range(0, 48, 3))
    return points, edges


def project(points, angle, cx, cy, radius):
    result = []
    for x, y, z in points:
        xr, zr = x*math.cos(angle)+z*math.sin(angle), -x*math.sin(angle)+z*math.cos(angle)
        yr, zr = y*.94-zr*.34, y*.34+zr*.94
        depth = 3/(3+zr)
        result.append((cx+xr*radius*depth, cy+yr*radius*depth))
    return result


def machine_rows(data):
    data = data or {}
    def number(key, suffix=""):
        value = data.get(key)
        return "NO SIGNAL" if value is None else f"{value:g}{suffix}"
    ram, total = data.get("ram_used_mb"), data.get("ram_total_mb")
    memory = "NO SIGNAL" if ram is None or not total else f"{ram:g}/{total:g} MiB"
    uptime = data.get("uptime_seconds")
    return (("Warmth of the Spirit", number("temperature_c", " °C"), data.get("temperature_c"), 100),
            ("Load of the Litany", number("load1"), data.get("load1"), data.get("cpu_count") or 1),
            ("Memory Reliquary", memory, ram, total or 1),
            ("Days since Consecration", "NO SIGNAL" if uptime is None else f"{uptime/86400:.1f} d",
             None if uptime is None else uptime/86400, 30))


class InterludeView:
    def __init__(self, canvas, mono, packet, started, reduced=False):
        from tkinter import font
        if packet.get("version") != 1 or packet.get("type") not in TYPES:
            raise ValueError("Unsupported interlude packet")
        self.canvas, self.mono, self.packet = canvas, mono, packet
        self.started, self.reduced = started, reduced
        self.key = None
        self.dynamic = []
        self.sweep = self.vox_text = None
        self.last_frame = -1
        self.character_width = max(1,font.Font(root=canvas, family=mono, size=-11).measure("M"))

    def text(self, x, y, value, color=BONE, size=11, **kwargs):
        kwargs.setdefault("justify", "left")
        return self.canvas.create_text(x, y, text=value, fill=color, font=(self.mono, -size), anchor="nw", **kwargs)

    def build(self, w, h):
        c = self.canvas
        c.delete("all")
        self.dynamic, self.sweep, self.vox_text = [], None, None
        self.w, self.h = w, h
        self.rng = SceneRandom(self.packet["seed"])
        data, kind = self.packet["data"], self.packet["type"]
        self.background = c.create_polygon(9,1,w-9,1,w-1,9,w-1,h-9,w-9,h-1,9,h-1,1,h-9,1,9, outline=DIM, fill=BLACK)
        c.create_line(9, 27, w-9, 27, fill=DIM)
        self.title = self.text(12, 8, "++ " + TITLES[kind] + " ++", AMBER, 12)
        footer = (f"SCHEMATIC / {min(6,len(data['sensors']))} OF {len(data['sensors'])} / TOUCH TO CLOSE"
                  if kind == "auspex" else "LOCAL SNAPSHOT / TOUCH OR KEY TO CLOSE")
        self.text(12, h-16, footer, BRASS, 10)
        self.body_top, self.body_bottom = 36, h-24
        getattr(self, "build_" + kind)(data)
        self.scan_bar = c.create_line(9,0,w-9,0,fill="#35250b",width=3,state="hidden" if self.reduced else "normal")
        c.tag_raise(self.scan_bar,self.background)

    def build_auspex(self, data):
        c, w, top, bottom = self.canvas, self.w, self.body_top, self.body_bottom
        stacked = w < 420 and self.h >= 300
        radius = min((w-35)/2 if stacked else w*.22, (bottom-top)*(.28 if stacked else .45), 110)
        self.radar_center = cx, cy = (w/2 if stacked else radius+15), top+radius+4
        self.radar_radius = radius
        for factor in (1, .7, .36):
            c.create_oval(cx-radius*factor, cy-radius*factor, cx+radius*factor, cy+radius*factor, outline=DIM)
        c.create_line(cx-radius, cy, cx+radius, cy, fill=DIM)
        c.create_line(cx, cy-radius, cx, cy+radius, fill=DIM)
        self.sweep_glow = c.create_line(cx, cy, cx, cy-radius, fill="#5c3e08", width=5)
        self.sweep = c.create_line(cx, cy, cx, cy-radius, fill=AMBER)
        sensors = data["sensors"][:6]
        self.lost_items = []
        if not sensors:
            self.text(w*.55 if not stacked else 20, top+15 if not stacked else cy+radius+15, "SENSORS: NO SIGNAL", BRASS)
        for i, sensor in enumerate(sensors):
            a = self.rng.random()*math.tau
            distance = radius*(.91 if sensor["location"] == "outdoor" else .3+self.rng.random()*.4)
            x, y = cx+math.cos(a)*distance, cy+math.sin(a)*distance
            lost = sensor["connection"] == "lost"
            style = dict(sensor["style"], color=FAULT) if lost else sensor["style"]
            sensor_mark(c, x, y, style, 4)
            if lost:
                self.lost_items.append(c.create_oval(x-8,y-8,x+8,y+8,outline=FAULT))
            tx, ty = (18, cy+radius+14+i*34) if stacked else (cx+radius+17, top+i*max(24,(bottom-top-6)/max(1,len(sensors))))
            available = max(10, int((w-tx-22)/self.character_width))
            name = sensor["name"][:available]
            value = "NO SIGNAL" if sensor["temperature"] is None else f"{sensor['temperature']:.1f} °C"
            sensor_mark(c, tx+3, ty+6, sensor["style"], 3)
            self.text(tx+12, ty, name, BONE)
            detail = ("OUT " if sensor["location"] == "outdoor" else "IN ") + value
            self.text(tx+12, ty+13, detail, FAULT if lost else AMBER)

    def build_vox(self, data):
        lines = "\n".join(data["lines"]) + ("\n[DATA CORRUPTED]" if data["corrupted"] else "")
        width = max(16, int((self.w-28)/self.character_width))
        header = f"{data['origin']} / {data['channel']}\n{data['imperial_date']}\n"
        body = "\n".join(textwrap.fill(line, width) for line in lines.splitlines())
        capacity = max(3,int((self.body_bottom-self.body_top)/14))
        lines = (header+body).splitlines()
        self.vox_full = "\n".join(lines[:capacity-1]+["++ END TRANSMISSION ++"])
        self.vox_text = self.text(14,self.body_top,self.vox_full if self.reduced else "", BONE, width=self.w-28)
        self.vox_cursor = self.text(14,self.body_top,"", AMBER)

    def build_servitor(self, data):
        c = self.canvas
        columns = (self.w-30)/2
        row_height = max(24, (self.body_bottom-self.body_top-50)/4)
        for index, name in enumerate(("server", "pi")):
            x = 12+index*(columns+6)
            self.text(x,self.body_top,"COGITATOR" if name == "server" else "CORPUS / PI", BRASS)
            for row, (label, value, amount, maximum) in enumerate(machine_rows(data["machines"][name])):
                y = self.body_top+18+row*row_height
                if self.w < 420:
                    label = {"Warmth of the Spirit": "Spirit Warmth", "Load of the Litany": "Litany Load",
                             "Days since Consecration": "Consecrated Days"}.get(label,label)
                self.text(x,y,label,BONE,11)
                self.text(x,y+11,value,AMBER if amount is not None else BRASS,11)
                c.create_rectangle(x,y+row_height-4,x+columns-5,y+row_height-1,fill="#251e14",outline="")
                if amount is not None:
                    fill = max(0,min(1,amount/maximum))*(columns-5)
                    c.create_rectangle(x,y+row_height-4,x+fill,y+row_height-1,fill=AMBER,outline="")
        self.text(12,self.body_bottom-28,data["thought"],BRASS,10,width=self.w-24)

    def build_hololith(self, data):
        self.points, self.edges = wire_model(data["model"])
        self.radius = min(self.w*.24,(self.body_bottom-self.body_top)*.39)
        self.center = self.w/2, (self.body_top+self.body_bottom)/2-6
        self.wire_glows = [self.canvas.create_line(0,0,1,1,fill="#3f2b0e",width=3) for _ in self.edges]
        self.wires = [self.canvas.create_line(0,0,1,1,fill=AMBER) for _ in self.edges]
        self.text(12,self.body_bottom-13,self.reading_line(data),BRASS,10)

    def build_codex(self, data):
        record = data["codex"]
        title = self.text(14,self.body_top,record["title"].upper(),AMBER,12,width=self.w-28)
        body_y = self.canvas.bbox(title)[3]+8
        width = max(20,int((self.w-30)/self.character_width))
        lines = []
        for fact in record["facts"]:
            lines.extend(textwrap.wrap(fact,width)+[""])
        capacity = max(1,int((self.body_bottom-body_y-15)/14))
        self.text(14,body_y,"\n".join(lines[:capacity]),BONE,11)
        self.canvas.create_rectangle(self.w-68,self.body_bottom-14,self.w-14,self.body_bottom-4,fill=BRASS,outline="")
        self.text(self.w-65,self.body_bottom-14,"SEALED",BLACK,9)
        self.canvas.create_rectangle(14,self.body_bottom-14,91,self.body_bottom-4,fill=DIM,outline="")
        self.text(17,self.body_bottom-14,"REDACTED",BONE,9)

    def build_noosphere(self, data):
        columns = max(2,min(10,int((self.w-24)/49)))
        rows = max(2,min(12,int((self.body_bottom-self.body_top-26)/16)))
        self.real_cells = []
        for col in range(columns):
            for row in range(rows):
                name = "server" if (col,row) == (0,0) else "pi" if (col,row) == (columns-1,rows-1) else None
                value = (data["machines"].get(name) or {}).get("temperature_c") if name else None
                if value is not None:
                    self.real_cells.append(self.text(12+col*49,self.body_top+row*16,f"{value:g}C",AMBER,11))
                    continue
                item = self.text(12+col*49,self.body_top+row*16,"0000",DIM,11)
                self.dynamic.append(item)
        # Real measurements occupy a separate, steady line. Glitches never
        # change a number or make a missing reading look real.
        self.text(12,self.body_bottom-14,self.reading_line(data),AMBER,10,width=self.w-24)

    @staticmethod
    def reading_line(data):
        fields = []
        for name in ("server", "pi"):
            temperature = (data["machines"][name] or {}).get("temperature_c")
            fields.append(name.upper()+": "+("NO SIGNAL" if temperature is None else f"{temperature:g} °C"))
        return " / ".join(fields)

    def draw(self, now):
        c = self.canvas
        w,h = c.winfo_width(),c.winfo_height()
        if self.key != (w,h):
            self.build(w,h)
            self.key = w,h
        elapsed = max(0,now-self.started)
        frame = int(elapsed*15)
        if frame == self.last_frame:
            return
        self.last_frame = frame
        if not self.reduced:
            scan_y = self.body_top+(elapsed*19) % max(1,self.body_bottom-self.body_top)
            c.coords(self.scan_bar,9,scan_y,self.w-9,scan_y)
        if self.sweep:
            cx,cy = self.radar_center
            a = 0 if self.reduced else elapsed*.65-math.pi/2
            endpoint = cx+math.cos(a)*self.radar_radius,cy+math.sin(a)*self.radar_radius
            c.coords(self.sweep,cx,cy,*endpoint)
            c.coords(self.sweep_glow,cx,cy,*endpoint)
            for item in self.lost_items:
                c.itemconfigure(item,outline=FAULT if self.reduced or int(elapsed*2)%2 == 0 else DIM)
        if self.vox_text:
            count = len(self.vox_full) if self.reduced else min(len(self.vox_full),int(elapsed*55))
            c.itemconfigure(self.vox_text,text=self.vox_full[:count]+("" if count == len(self.vox_full) else " ▌"))
        if self.packet["type"] == "hololith":
            projected = project(self.points,0 if self.reduced else elapsed*.35,*self.center,self.radius)
            for items in (self.wire_glows,self.wires):
                for item,(a,b) in zip(items,self.edges):
                    c.coords(item,*projected[a],*projected[b])
        if self.packet["type"] == "noosphere" and (self.reduced and frame == 0 or not self.reduced and frame%3 == 0):
            for item in self.dynamic:
                c.itemconfigure(item,text=f"{self.rng.randrange(65536):04X}")
        if self.packet["type"] == "noosphere":
            for item in self.real_cells:
                c.itemconfigure(item,fill=AMBER if self.reduced or int(elapsed)%4 < 2 else BONE)
        remaining = self.packet["duration"]-elapsed
        color = AMBER if self.reduced or remaining > 1.5 else BRASS if remaining > .6 else DIM
        c.itemconfigure(self.title,fill=color)
        title = "++ " + TITLES[self.packet["type"]] + " ++"
        c.itemconfigure(self.title,text=title.replace("++", "##", 1) if not self.reduced and frame > 0 and frame%173 == 0 else title)
