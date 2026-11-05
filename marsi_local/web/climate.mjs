const PALETTE = ["#9fbf97", "#bca273", "#da7769", "#d8cbb0"];
const DASHES = [[], [6, 3], [2, 3], [7, 3, 2, 3]];
const STATES = {fresh: "FRESH", stale: "STALE READING", waiting: "WAITING FOR DATA"};
const METRICS = ["temperature", "humidity"];
const number = new Intl.NumberFormat("en-GB", {minimumFractionDigits: 1, maximumFractionDigits: 1});
const dateTime = new Intl.DateTimeFormat("en-GB", {dateStyle: "short", timeStyle: "short"});
const clock = new Intl.DateTimeFormat("en-GB", {hour: "2-digit", minute: "2-digit"});
const day = new Intl.DateTimeFormat("en-GB", {day: "2-digit", month: "2-digit"});

function color(sensor, index) {
  return /^#[0-9a-f]{6}$/i.test(sensor.color || "") ? sensor.color : PALETTE[index % PALETTE.length];
}

function text(tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
}

function delay(ms, signal) {
  return new Promise(resolve => {
    if (signal.aborted) return resolve();
    const done = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    signal.addEventListener("abort", done, {once: true});
  });
}

function closest(points, at) {
  let low = 0;
  let high = points.length - 1;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (points[mid][0] < at) low = mid + 1;
    else high = mid;
  }
  if (low > 0 && at - points[low - 1][0] <= points[low][0] - at) return points[low - 1];
  return points[low];
}

export class ClimateView {
  constructor(request) {
    this.request = request;
    this.cards = document.querySelector("#cards");
    this.historyPanel = document.querySelector("#history");
    this.legend = document.querySelector("#legend");
    this.message = document.querySelector("#climate-message");
    this.link = document.querySelector("#climate-link");
    this.buttons = [...document.querySelectorAll("[data-period]")];
    this.canvases = Object.fromEntries(METRICS.map(metric => [metric, document.querySelector(`#${metric}-chart`)]));
    this.readouts = Object.fromEntries(METRICS.map(metric => [metric, document.querySelector(`#${metric}-readout`)]));
    this.hiddenSensors = new Set();
    this.period = "now";
    this.inspect = {};
    for (const button of this.buttons) button.addEventListener("click", () => this.select(button.dataset.period));
    for (const [metric, canvas] of Object.entries(this.canvases)) {
      canvas.addEventListener("pointerdown", event => this.inspectAt(metric, event));
      canvas.addEventListener("pointermove", event => {
        if (event.pointerType === "mouse") this.inspectAt(metric, event);
      });
      canvas.addEventListener("keydown", event => this.inspectWithKey(metric, event));
    }
    const observer = new ResizeObserver(() => this.paint());
    for (const canvas of Object.values(this.canvases)) observer.observe(canvas);
  }

  open() {
    if (this.feed) return;
    this.feed = new AbortController();
    this.setLink("[ CONNECTING ]", "waiting");
    this.render();
    this.follow(this.feed.signal);
    this.scheduleHistory();
    this.windowTimer = setInterval(() => this.scheduleHistory(), 60_000);
  }

  close() {
    this.feed?.abort();
    this.feed = null;
    this.historyRequest?.abort();
    clearTimeout(this.historyTimer);
    clearInterval(this.windowTimer);
  }

  reset() {
    this.close();
    this.snapshot = this.history = null;
    this.hiddenSensors.clear();
    this.legend.replaceChildren();
    this.legendKey = "";
    this.cards.replaceChildren();
    this.select("now");
  }

  setLink(label, state) {
    this.link.textContent = label;
    this.link.dataset.state = state;
  }

  async follow(signal) {
    let retry = 1000;
    while (!signal.aborted) {
      try {
        const response = await this.request("/v1/climate/events", {
          signal, stream: true, headers: {Accept: "text/event-stream"},
        });
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        try {
          while (!signal.aborted) {
            const {value, done} = await reader.read();
            if (done) throw new Error("Feed closed");
            buffer += decoder.decode(value, {stream: true});
            if (buffer.length > 1_000_000) throw new Error("Climate event too large");
            let boundary;
            while ((boundary = buffer.indexOf("\n\n")) >= 0) {
              const frame = buffer.slice(0, boundary);
              buffer = buffer.slice(boundary + 2);
              const line = frame.split("\n").find(part => part.startsWith("data: "));
              if (!line || signal.aborted) continue;
              const snapshot = JSON.parse(line.slice(6));
              if (!Array.isArray(snapshot.sensors)) throw new Error("Invalid climate snapshot");
              this.snapshot = snapshot;
              retry = 1000;
              this.setLink("[ LIVE ]", "live");
              this.message.textContent = "";
              this.render();
              this.scheduleHistory();
            }
          }
        } finally {
          await reader.cancel().catch(() => {});
        }
      } catch (error) {
        if (signal.aborted) return;
        this.setLink("[ LINK PAUSE ]", "waiting");
        this.message.textContent = error.status === 503
          ? "Check the climate archive on Ubuntu."
          : "Reconnecting to the climate archive ...";
        await delay(retry, signal);
        retry = Math.min(retry * 2, 8000);
      }
    }
  }

  select(period) {
    this.period = period;
    this.history = null;
    this.inspect = {};
    this.historyRequest?.abort();
    clearTimeout(this.historyTimer);
    for (const button of this.buttons) button.setAttribute("aria-pressed", button.dataset.period === period);
    this.render();
    this.scheduleHistory(0);
  }

  scheduleHistory(ms = 180) {
    if (!this.feed || this.period === "now") return;
    clearTimeout(this.historyTimer);
    this.historyTimer = setTimeout(() => this.fetchHistory(), ms);
  }

  async fetchHistory() {
    this.historyRequest?.abort();
    const controller = new AbortController();
    this.historyRequest = controller;
    const period = this.period;
    try {
      const history = await this.request(`/v1/climate/history?range=${period}`, {signal: controller.signal});
      if (controller.signal.aborted || period !== this.period) return;
      this.history = history;
      if (this.link.dataset.state === "live") this.message.textContent = "";
      this.render();
    } catch (error) {
      if (controller.signal.aborted) return;
      this.message.textContent = "Retrying climate history ...";
      this.scheduleHistory(5000);
    }
  }

  render() {
    const isNow = this.period === "now";
    this.cards.hidden = !isNow;
    this.historyPanel.hidden = isNow;
    if (isNow) this.renderCards();
    else {
      this.renderLegend();
      this.paint();
    }
  }

  renderCards() {
    const sensors = this.snapshot?.sensors || [];
    this.cards.replaceChildren(...sensors.map((sensor, index) => {
      const tile = document.createElement("article");
      tile.className = "sensor-card";
      tile.style.setProperty("--sensor", color(sensor, index));
      const head = text("div", "", "card-header");
      const title = text("h3", sensor.name);
      const cog = text("span", "+O+", "card-cog");
      cog.setAttribute("aria-hidden", "true");
      title.prepend(cog);
      head.append(title, text("span", sensor.location === "outdoor" ? "[ OUTDOOR ]" : "[ INDOOR ]", "badge"));
      const value = metric => sensor.readings[metric] ? number.format(sensor.readings[metric].value) : "--";
      const foot = text("div", "", "card-footer");
      const stamp = sensor.last_measurement_ms == null ? "Last reading --" : dateTime.format(sensor.last_measurement_ms);
      const state = text("span", STATES[sensor.status] || STATES.waiting);
      state.dataset.status = sensor.status;
      foot.append(text("span", stamp), state);
      tile.append(head, text("p", `${value("temperature")} °C`, "reading"),
                  text("p", `${value("humidity")} % RH`, "humidity"), foot);
      return tile;
    }));
    if (!sensors.length) this.cards.append(text("p", "Waiting for the climate archive ...", "message"));
  }

  renderLegend() {
    const states = new Map((this.snapshot?.sensors || []).map(sensor => [sensor.id, sensor.status]));
    const series = (this.history?.sensors || []).map(({id, name, location, color}) => ({id, name, location, color, state: states.get(id)}));
    const key = JSON.stringify(series);
    if (key === this.legendKey) return;
    this.legendKey = key;
    this.legend.replaceChildren(...series.map((sensor, index) => {
      const prefix = sensor.location === "outdoor" ? "OUTDOOR / " : "";
      const suffix = sensor.state === "stale" ? " / STALE" : "";
      const button = text("button", `${prefix}${sensor.name}${suffix}`);
      button.type = "button";
      button.setAttribute("aria-pressed", !this.hiddenSensors.has(sensor.id));
      const swatch = text("span", "", "swatch");
      swatch.style.color = color(sensor, index);
      if (DASHES[index % DASHES.length].length) swatch.style.borderTopStyle = "dashed";
      button.prepend(swatch);
      button.addEventListener("click", () => {
        if (this.hiddenSensors.has(sensor.id)) this.hiddenSensors.delete(sensor.id);
        else this.hiddenSensors.add(sensor.id);
        button.setAttribute("aria-pressed", !this.hiddenSensors.has(sensor.id));
        this.paint();
      });
      return button;
    }));
  }

  paint() {
    if (this.period === "now" || this.frame) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = null;
      for (const metric of METRICS) this.drawChart(metric);
    });
  }

  inspectAt(metric, event) {
    if (!this.history) return;
    const rect = this.canvases[metric].getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (event.clientX - rect.left - 42) / (rect.width - 53)));
    this.inspect[metric] = this.history.from_ms + fraction * (this.history.to_ms - this.history.from_ms);
    this.paint();
  }

  inspectWithKey(metric, event) {
    if (!this.history || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const {from_ms: start, to_ms: end, bucket_ms: bucket} = this.history;
    const step = bucket || (end - start) / 24;
    const next = (this.inspect[metric] ?? end) + (event.key === "ArrowLeft" ? -step : step);
    this.inspect[metric] = Math.min(end, Math.max(start, next));
    this.paint();
  }

  drawChart(metric) {
    const canvas = this.canvases[metric];
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const pixelWidth = Math.round(width * ratio);
    const pixelHeight = Math.round(height * ratio);
    if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
    if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.font = "12px monospace";
    ctx.textBaseline = "middle";
    const left = 42, right = width - 11, top = 10, bottom = height - 23;
    const plotWidth = right - left, plotHeight = bottom - top;
    const history = this.history;
    const lines = (history?.sensors || []).flatMap((sensor, index) => this.hiddenSensors.has(sensor.id)
      ? [] : [{sensor, index, points: sensor.series[metric]}]);
    let min = Infinity, max = -Infinity;
    for (const line of lines) for (const [, value] of line.points) {
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
    const readout = this.readouts[metric];
    if (!Number.isFinite(min) || plotWidth <= 0) {
      ctx.fillStyle = "#d8cbb0";
      ctx.textAlign = "center";
      ctx.fillText(history ? "No samples in this period" : "Loading climate history ...", width / 2, height / 2);
      readout.textContent = "";
      return;
    }
    let low = Math.floor(min), high = Math.max(low + 2, Math.ceil(max));
    if (metric === "humidity" && high > 100) [low, high] = [Math.min(low, 98), 100];
    const start = history.from_ms, end = history.to_ms;
    const x = at => left + (at - start) / Math.max(1, end - start) * plotWidth;
    const y = value => bottom - (value - low) / (high - low) * plotHeight;
    ctx.strokeStyle = "#4b332f";
    ctx.fillStyle = "#bca273";
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    for (const fraction of [0, .5, 1]) {
      const row = bottom - fraction * plotHeight;
      const column = left + fraction * plotWidth;
      ctx.beginPath();
      ctx.moveTo(left, row);
      ctx.lineTo(right, row);
      ctx.moveTo(column, top);
      ctx.lineTo(column, bottom);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.fillText(String(low + (high - low) * fraction), left - 5, row);
      ctx.textAlign = fraction === 0 ? "left" : fraction === 1 ? "right" : "center";
      const at = start + fraction * (end - start);
      ctx.fillText((this.period === "7d" ? day : clock).format(at), column, bottom + 13);
    }
    const gap = this.snapshot?.stale_after_ms || 7_200_000;
    for (const {sensor, index, points} of lines) {
      ctx.strokeStyle = ctx.fillStyle = color(sensor, index);
      ctx.lineWidth = 2;
      ctx.setLineDash(DASHES[index % DASHES.length]);
      ctx.beginPath();
      for (let i = 0; i < points.length; i++) {
        const [at, value] = points[i];
        if (i > 0 && at - points[i - 1][0] < gap) ctx.lineTo(x(at), y(value));
        else ctx.moveTo(x(at), y(value));
      }
      ctx.stroke();
      for (let i = 0; i < points.length; i++) {
        const [at, value] = points[i];
        if ((i === 0 || at - points[i - 1][0] >= gap) && (i + 1 === points.length || points[i + 1][0] - at >= gap)) {
          ctx.beginPath();
          ctx.arc(x(at), y(value), 2.6, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
    const at = this.inspect[metric];
    if (at == null || at < start || at > end) {
      readout.textContent = "";
      return;
    }
    ctx.strokeStyle = "#d8cbb0";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(x(at), top);
    ctx.lineTo(x(at), bottom);
    ctx.stroke();
    const summaries = lines.filter(line => line.points.length).map(({sensor, index, points}) => {
      const [time, value] = closest(points, at);
      ctx.fillStyle = color(sensor, index);
      ctx.beginPath();
      ctx.arc(x(time), y(value), 4, 0, Math.PI * 2);
      ctx.fill();
      return `${sensor.name} ${number.format(value)} (${dateTime.format(time)})`;
    });
    readout.textContent = summaries.join("  /  ");
  }
}
