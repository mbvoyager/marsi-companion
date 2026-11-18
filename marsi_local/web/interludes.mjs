// Authored local-data scenes. Static content is cached; motion is capped at 15 fps.
const TYPES = ["auspex", "vox", "servitor", "hololith", "codex", "noosphere"];
const TITLES = {auspex: "AUSPEX DOMUS", vox: "TRANSMISSIO VOX", servitor: "RELATIO SERVITOR",
  hololith: "HOLOLITH", codex: "FRAGMENTUM CODEX", noosphere: "NOOSPHERIC TRANSIT"};
const fallback = {black: "#090708", bone: "#e5d9bd", amber: "#ffb000", brass: "#bca16d", dim: "#58422e", rust: "#ee8779"};

export function validPacket(packet) {
  return packet?.version === 1 && TYPES.includes(packet.type) && Number.isInteger(packet.seed) && packet.seed >= 0 && packet.seed < 2**32
    && Number.isInteger(packet.duration) && packet.duration >= 15 && packet.duration <= 30 && Array.isArray(packet.data?.sensors)
    && typeof packet.data?.machines === "object";
}

function random(seed) {
  return () => { seed = Math.imul(1664525, seed) + 1013904223 | 0; return (seed >>> 0) / 4294967296; };
}

function wrap(text, columns) {
  return String(text).split("\n").flatMap(line => {
    const lines = []; let current = "";
    for (const word of line.split(" ")) {
      if (current && current.length + word.length + 1 > columns) { lines.push(current); current = ""; }
      current += (current ? " " : "") + word;
    }
    return [...lines, current];
  });
}

function marker(ctx, x, y, style, radius = 4) {
  ctx.fillStyle = style.color;
  ctx.beginPath();
  if (style.shape === "circle") ctx.arc(x, y, radius, 0, Math.PI*2);
  else if (style.shape === "square") ctx.rect(x-radius, y-radius, radius*2, radius*2);
  else if (style.shape === "diamond") {
    ctx.moveTo(x,y-radius); ctx.lineTo(x+radius,y); ctx.lineTo(x,y+radius); ctx.lineTo(x-radius,y);
  } else { ctx.moveTo(x,y-radius); ctx.lineTo(x+radius,y+radius); ctx.lineTo(x-radius,y+radius); }
  ctx.closePath(); ctx.fill();
}

function wireModel(kind) {
  const points = [], edges = [];
  if (kind === "planet") {
    for (const latitude of [-.7, 0, .7]) {
      const offset = points.length;
      for (let i=0; i<24; i++) {
        const a = Math.PI*2*i/24, r = Math.sqrt(1-latitude**2);
        points.push([Math.cos(a)*r, latitude, Math.sin(a)*r]); edges.push([offset+i, offset+(i+1)%24]);
      }
    }
    for (let i=0; i<24; i+=4) edges.push([i,24+i],[24+i,48+i]);
  } else if (kind === "skull") {
    const outline = [[-.55,-.85],[.55,-.85],[.9,-.45],[.8,.25],[.45,.45],[.35,.85],[-.35,.85],[-.45,.45],[-.8,.25],[-.9,-.45]];
    for (const z of [-.25,.25]) points.push(...outline.map(([x,y]) => [x,y,z]));
    for (const offset of [0,10]) for (let i=0; i<10; i++) edges.push([offset+i,offset+(i+1)%10]);
    for (let i=0; i<10; i++) edges.push([i,i+10]);
    for (const x of [-.32,.32]) {
      const offset = points.length;
      points.push([x-.17,-.25,-.3],[x+.17,-.25,-.3],[x+.17,.05,-.3],[x-.17,.05,-.3]);
      for (let i=0; i<4; i++) edges.push([offset+i,offset+(i+1)%4]);
    }
  } else {
    for (const z of [-.22,.22]) for (let i=0; i<48; i++) {
      const a = Math.PI*2*i/48, r = [0,3].includes(i%4) ? 1 : .8;
      points.push([Math.cos(a)*r,Math.sin(a)*r,z]);
    }
    for (const offset of [0,48]) for (let i=0; i<48; i++) edges.push([offset+i,offset+(i+1)%48]);
    for (let i=0; i<48; i+=3) edges.push([i,i+48]);
  }
  return {points,edges};
}

export class InterludeView {
  constructor(container, packet, {onClose = () => {}, reduced = false} = {}) {
    if (!validPacket(packet)) throw new Error("Unsupported interlude packet");
    this.packet = packet; this.container = container; this.onClose = onClose; this.reduced = reduced;
    this.canvas = document.createElement("canvas");
    this.canvas.setAttribute("role", "img");
    this.canvas.setAttribute("aria-label", TITLES[packet.type] + ". Local machine and climate snapshot.");
    this.summary = document.createElement("p"); this.summary.className = "sr-only";
    this.summary.textContent = packet.data.sensors.map(s => `${s.name}: ${s.temperature ?? "NO SIGNAL"}${s.temperature == null ? "" : " °C"}, ${s.connection}`).join(". ");
    this.closeButton = document.createElement("button"); this.closeButton.type = "button";
    this.closeButton.textContent = "CLOSE TRANSMISSION";
    this.closeButton.addEventListener("click", () => this.close());
    container.replaceChildren(this.canvas, this.summary, this.closeButton);
    this.started = performance.now(); this.last = -100;
    this.paint = this.paint.bind(this);
    this.resize = new ResizeObserver(() => { this.cache = null; }); this.resize.observe(this.canvas);
    this.key = event => { if (event.key !== "Tab") { event.preventDefault(); event.stopPropagation(); this.close(); } };
    this.touch = () => this.close();
    document.addEventListener("keydown", this.key, true);
    this.canvas.addEventListener("pointerdown", this.touch);
    this.previousFocus = document.activeElement;
    this.closeButton.focus({preventScroll: true});
    this.timer = setTimeout(() => this.close(), packet.duration*1000);
    this.frame = requestAnimationFrame(this.paint);
  }

  close() {
    if (this.closed) return;
    this.closed = true; cancelAnimationFrame(this.frame); clearTimeout(this.timer);
    this.resize.disconnect(); document.removeEventListener("keydown", this.key, true);
    this.previousFocus?.focus?.({preventScroll: true});
    this.onClose();
  }

  text(ctx, x, y, text, color = this.colors.bone, size = 12) {
    ctx.fillStyle = color; ctx.font = `${size}px monospace`; ctx.textBaseline = "top"; ctx.textAlign = "left";
    ctx.fillText(String(text),x,y);
  }

  line(ctx,x1,y1,x2,y2,color = this.colors.dim,width = 1) {
    ctx.strokeStyle = color; ctx.lineWidth = width; ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
  }

  readingLine() {
    return ["server","pi"].map(name => {
      const value = this.packet.data.machines[name]?.temperature_c;
      return `${name.toUpperCase()}: ${value == null ? "NO SIGNAL" : value+" °C"}`;
    }).join(" / ");
  }

  build(width, height) {
    this.w = width; this.h = height; this.rng = random(this.packet.seed);
    this.colors = Object.fromEntries(Object.entries(fallback).map(([key,value]) => [key,
      getComputedStyle(this.container).getPropertyValue("--"+key).trim() || value]));
    this.ratio = Math.min(globalThis.devicePixelRatio || 1,2);
    this.cache = document.createElement("canvas"); this.cache.width = width*this.ratio; this.cache.height = height*this.ratio;
    const ctx = this.cache.getContext("2d"), c = this.colors, data = this.packet.data;
    ctx.scale(this.ratio,this.ratio);
    ctx.strokeStyle = c.dim; ctx.strokeRect(.5,.5,width-1,height-1);
    this.text(ctx,12,12,"++ "+TITLES[this.packet.type]+" ++",c.amber,14);
    this.line(ctx,12,36,width-12,36);
    this.text(ctx,12,height-22,this.packet.type === "auspex"
      ? `SCHEMATIC / ${Math.min(6,data.sensors.length)} OF ${data.sensors.length} / TOUCH TO CLOSE`
      : "LOCAL SNAPSHOT / TOUCH OR KEY TO CLOSE",c.brass,11);
    this.top = 48; this.bottom = height-34;
    if (this.packet.type === "auspex") {
      const stacked = width < 480;
      const radius = Math.min(stacked ? width*.37 : width*.22,(this.bottom-this.top)*(stacked ? .26 : .45),140);
      this.radar = {cx: stacked ? width/2 : radius+20, cy: this.top+radius+4, radius, lost: []};
      const {cx,cy} = this.radar;
      ctx.strokeStyle = c.dim;
      for (const f of [1,.7,.36]) { ctx.beginPath(); ctx.arc(cx,cy,radius*f,0,Math.PI*2); ctx.stroke(); }
      this.line(ctx,cx-radius,cy,cx+radius,cy); this.line(ctx,cx,cy-radius,cx,cy+radius);
      if (!data.sensors.length) this.text(ctx,20,cy+radius+12,"SENSORS: NO SIGNAL",c.brass);
      data.sensors.slice(0,6).forEach((sensor,i) => {
        const angle = this.rng()*Math.PI*2, r = radius*(sensor.location === "outdoor" ? .91 : .3+this.rng()*.4);
        const x = cx+Math.cos(angle)*r,y = cy+Math.sin(angle)*r;
        marker(ctx,x,y,sensor.connection === "lost" ? {...sensor.style,color:c.rust} : sensor.style);
        if (sensor.connection === "lost") this.radar.lost.push([x,y]);
        const tx = stacked ? 20 : cx+radius+20;
        const ty = stacked ? cy+radius+15+i*33 : this.top+i*45;
        marker(ctx,tx+3,ty+6,sensor.style,3);
        const max = Math.max(8,Math.floor((width-tx-22)/7.3));
        this.text(ctx,tx+13,ty,sensor.name.slice(0,max));
        this.text(ctx,tx+13,ty+15,(sensor.location === "outdoor" ? "OUT " : "IN ")+
          (sensor.temperature == null ? "NO SIGNAL" : sensor.temperature.toFixed(1)+" °C"),sensor.connection === "lost" ? c.rust : c.amber);
      });
    } else if (this.packet.type === "vox") {
      this.text(ctx,14,this.top,`ORIGIN ${data.origin}`,c.brass,11);
      this.text(ctx,14,this.top+18,`${data.imperial_date} / ${data.channel}`,c.brass,11);
      this.vox = wrap(data.lines.join("\n\n")+(data.corrupted ? "\n[DATA CORRUPTED]" : "")+"\n\n++ END TRANSMISSION ++",Math.floor((width-30)/7.3));
    } else if (this.packet.type === "servitor") {
      const col = (width-36)/2, row = Math.min(58,(this.bottom-this.top-75)/4);
      ["server","pi"].forEach((name,index) => {
        const x = 12+index*(col+12), m = data.machines[name] || {};
        this.text(ctx,x,this.top,name === "server" ? "COGITATOR" : "CORPUS / PI",c.brass);
        const rows = [
          ["Warmth of the Spirit",m.temperature_c == null ? "NO SIGNAL" : m.temperature_c+" °C",m.temperature_c,100],
          ["Load of the Litany",m.load1 ?? "NO SIGNAL",m.load1,m.cpu_count || 1],
          ["Memory Reliquary",m.ram_used_mb == null ? "NO SIGNAL" : `${m.ram_used_mb}/${m.ram_total_mb} MiB`,m.ram_used_mb,m.ram_total_mb || 1],
          ["Days since Consecration",m.uptime_seconds == null ? "NO SIGNAL" : (m.uptime_seconds/86400).toFixed(1)+" d",m.uptime_seconds == null ? null : m.uptime_seconds/86400,30]
        ];
        rows.forEach(([label,value,amount,max],i) => {
          const y = this.top+25+i*row;
          this.text(ctx,x,y,label,c.bone,11); this.text(ctx,x,y+15,value,c.amber,12);
          ctx.fillStyle = "#251e14"; ctx.fillRect(x,y+row-8,col,3);
          if (amount != null) { ctx.fillStyle = c.amber; ctx.fillRect(x,y+row-8,col*Math.max(0,Math.min(1,amount/max)),3); }
        });
      });
      wrap("THOUGHT FOR THE DAY: "+data.thought,Math.floor((width-26)/6.7)).forEach((line,i) => this.text(ctx,12,this.bottom-36+i*14,line,c.brass,11));
    } else if (this.packet.type === "hololith") {
      this.model = wireModel(data.model); this.text(ctx,12,this.bottom-12,this.readingLine(),c.brass,11);
    } else if (this.packet.type === "codex") {
      const lines = wrap(data.codex.title.toUpperCase()+"\n\n"+data.codex.facts.join("\n\n"),Math.floor((width-30)/7.3));
      lines.slice(0,Math.floor((this.bottom-this.top-20)/17)).forEach((line,i) => this.text(ctx,14,this.top+i*17,line,i === 0 ? c.amber : c.bone));
      this.text(ctx,width-75,this.bottom-12,"[SEALED]",c.brass,11);
    } else {
      this.hex = [];
      for (let x=12; x<width-48; x+=52) for (let y=this.top; y<this.bottom-28; y+=18) this.hex.push([x,y]);
      this.text(ctx,12,this.bottom-14,this.readingLine(),c.amber,11);
    }
  }

  paint(now) {
    if (this.closed) return;
    this.frame = requestAnimationFrame(this.paint);
    if (now-this.last < 1000/15) return;
    this.last = now;
    const width = Math.round(this.canvas.clientWidth), height = Math.round(this.canvas.clientHeight);
    if (!width || !height) return;
    if (!this.cache || this.w !== width || this.h !== height) this.build(width,height);
    if (this.canvas.width !== width*this.ratio) this.canvas.width = width*this.ratio;
    if (this.canvas.height !== height*this.ratio) this.canvas.height = height*this.ratio;
    const ctx = this.canvas.getContext("2d"), c = this.colors;
    ctx.setTransform(this.ratio,0,0,this.ratio,0,0);
    const elapsed = this.reduced ? 0 : (now-this.started)/1000;
    ctx.fillStyle = c.black; ctx.fillRect(0,0,width,height);
    if (!this.reduced) {
      const scanY = this.top+(elapsed*19)%Math.max(1,this.bottom-this.top);
      this.line(ctx,9,scanY,width-9,scanY,"#35250b",3);
    }
    ctx.drawImage(this.cache,0,0,width,height);
    if (this.radar) {
      const {cx,cy,radius,lost} = this.radar, angle = elapsed*.65-Math.PI/2;
      ctx.fillStyle = "#ffb00018"; ctx.beginPath(); ctx.moveTo(cx,cy); ctx.arc(cx,cy,radius,angle-.6,angle); ctx.closePath(); ctx.fill();
      this.line(ctx,cx,cy,cx+Math.cos(angle)*radius,cy+Math.sin(angle)*radius,c.amber);
      if (this.reduced || Math.floor(elapsed*2)%2 === 0) for (const [x,y] of lost) { ctx.strokeStyle=c.rust; ctx.beginPath(); ctx.arc(x,y,8,0,Math.PI*2); ctx.stroke(); }
    } else if (this.vox) {
      let remaining = this.reduced ? Infinity : Math.floor(elapsed*55);
      for (const [i,line] of this.vox.entries()) {
        const shown = line.slice(0,Math.max(0,remaining));
        this.text(ctx,14,this.top+50+i*17,shown+(remaining >= 0 && remaining < line.length ? "▌" : ""));
        remaining -= line.length+1;
      }
    } else if (this.model) {
      const radius = Math.min(width*.28,(this.bottom-this.top)*.4), a = elapsed*.35;
      const points = this.model.points.map(([x,y,z]) => {
        const xr = x*Math.cos(a)+z*Math.sin(a), zr0 = -x*Math.sin(a)+z*Math.cos(a);
        const yr = y*.94-zr0*.34, zr = y*.34+zr0*.94, scale = 3/(3+zr);
        return [width/2+xr*radius*scale,(this.top+this.bottom)/2-8+yr*radius*scale];
      });
      for (const [a,b] of this.model.edges) this.line(ctx,...points[a],...points[b],c.amber);
    } else if (this.hex) {
      if (!this.hexValues || !this.reduced && Math.floor(elapsed*5) !== this.hexAt) {
        this.hexAt = Math.floor(elapsed*5); this.hexValues = this.hex.map(() => Math.floor(this.rng()*65536).toString(16).toUpperCase().padStart(4,"0"));
      }
      this.hex.forEach(([x,y],i) => this.text(ctx,x,y,this.hexValues[i],c.dim,12));
    }
    const remaining = this.packet.duration-(now-this.started)/1000;
    if (this.canvas.style) this.canvas.style.opacity = this.reduced || remaining > 1.5 ? "1" : remaining > .6 ? ".7" : ".3";
  }
}
