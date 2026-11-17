import assert from "node:assert/strict";
import {test} from "node:test";
import {setTimeout as sleep} from "node:timers/promises";
import {ClimateView} from "../marsi_local/web/climate.mjs";
import {ClimateAdminView} from "../marsi_local/web/climate-admin.mjs";

class Element {
  attributes = {};
  children = [];
  dataset = {};
  listeners = {};
  style = {setProperty() {}};
  value = "";
  open = false;

  get firstChild() { return this.children[0]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  replaceChildren(...children) { this.children = children; }
  append(...children) {
    for (const child of children) child.parent = this;
    this.children.push(...children);
  }
  prepend(...children) { this.children.unshift(...children); }
  remove() { this.parent.children = this.parent.children.filter(child => child !== this); }
  pause() {}
  reset() {}
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; this.listeners.close?.(); }
}

function mountPage(storage = new Map()) {
  const elements = new Map();
  const node = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const periods = Object.fromEntries(["now", "3h", "24h", "7d"].map(period => {
    const button = new Element();
    button.dataset.period = period;
    return [period, button];
  }));
  globalThis.document = {
    getElementById: node,
    querySelector: selector => node(selector.slice(1)),
    querySelectorAll: selector => selector === "[data-period]" ? Object.values(periods) : [],
    createElement: () => new Element(),
    addEventListener() {},
  };
  globalThis.sessionStorage = {
    setItem: (key, value) => storage.set(key, value),
    getItem: key => storage.get(key) ?? null,
    removeItem: key => storage.delete(key),
  };
  globalThis.ResizeObserver = class { observe() {} };
  globalThis.requestAnimationFrame = callback => setTimeout(callback, 0);
  return {node, periods, storage};
}

const history = {range: "24h", sensors: [
  {id: "forge", name: "Forge", location: "indoor", series: {temperature: [[1, 21]], humidity: [[1, 50]]}},
  {id: "sim-exterior", name: "Simulated exterior", location: "outdoor", series: {temperature: [[1, 8]], humidity: [[1, 70]]}},
]};
const historyRoute = "/v1/climate/history?range=24h";

async function until(check) {
  const deadline = Date.now() + 2000;
  while (!check() && Date.now() < deadline) await sleep(5);
  assert.ok(check(), "The climate view did not reach the expected state");
}

function captureIntervals(t) {
  const setInterval = globalThis.setInterval;
  const intervals = [];
  globalThis.setInterval = (...args) => {
    const timer = setInterval(...args);
    intervals.push(timer);
    return timer;
  };
  t.after(() => {
    globalThis.setInterval = setInterval;
    for (const timer of intervals) clearInterval(timer);
  });
}

test("login and page reload request the selected climate history after authentication", async t => {
  captureIntervals(t);
  const paths = [];
  globalThis.fetch = async (path, {headers, signal}) => {
    paths.push(path);
    assert.equal(headers.Authorization, "Bearer synthetic-token");
    if (path.startsWith("/v1/journal")) return Response.json({entries: [], has_more: false});
    if (path === "/v1/telemetry") return Response.json({});
    if (path === historyRoute) return Response.json(history);
    if (path === "/v1/climate/events") {
      return new Response(new ReadableStream({start(controller) {
        signal.addEventListener("abort", () => controller.close(), {once: true});
      }}));
    }
    assert.fail(`Unexpected request ${path}`);
  };

  const page = mountPage();
  const {node, periods, storage} = page;
  const submit = () => {
    node("token").value = "synthetic-token";
    node("session").value = "pi";
    node("gate-form").listeners.submit({preventDefault() {}});
  };
  await import("../marsi_local/web/marsi.mjs?first-page");
  assert.deepEqual(paths, []);
  submit();
  await until(() => node("gate").hidden === true);
  assert.equal(node("tab-admin").hidden, true);
  node("tab-climate").listeners.click();
  periods["24h"].listeners.click();
  await until(() => node("legend").children.length === 2);

  node("lock").listeners.click();
  assert.equal(storage.has("marsi-web-session"), false);
  assert.equal(node("legend").children.length, 0);
  paths.length = 0;
  submit();
  await until(() => node("legend").children.length === 2);
  assert.equal(node("climate").hidden, false);
  assert.equal(periods["24h"].attributes["aria-pressed"], "true");
  assert.ok(paths[0].startsWith("/v1/journal"));
  assert.ok(paths.includes(historyRoute));

  const saved = new Map(storage);
  node("lock").listeners.click();
  paths.length = 0;
  const reloaded = mountPage(saved);
  await import("../marsi_local/web/marsi.mjs?reloaded-page");
  await until(() => reloaded.node("legend").children.length === 2);
  assert.equal(reloaded.node("history").hidden, false);
  assert.equal(reloaded.periods["24h"].attributes["aria-pressed"], "true");
  assert.ok(paths[0].startsWith("/v1/journal"));
  assert.ok(paths.includes(historyRoute));
  reloaded.node("lock").listeners.click();
});

test("research command displays live phases and labels the final sources", async t => {
  captureIntervals(t);
  const {node} = mountPage();
  let stream;
  const encoder = new TextEncoder();
  globalThis.fetch = async (path, options) => {
    if (path.startsWith("/v1/journal")) return Response.json({entries: [], has_more: false});
    if (path === "/v1/telemetry") return Response.json({});
    assert.equal(path, "/v1/chat");
    assert.equal(options.headers.Accept, "application/x-ndjson");
    assert.equal(JSON.parse(options.body).text, "/recherche What is rain?");
    return new Response(new ReadableStream({start(controller) { stream = controller; }}),
                        {headers: {"Content-Type": "application/x-ndjson"}});
  };
  await import("../marsi_local/web/marsi.mjs?research-page");
  t.after(() => node("lock").listeners.click());
  node("token").value = "synthetic-token";
  node("session").value = "pi";
  node("gate-form").listeners.submit({preventDefault() {}});
  await until(() => node("gate").hidden === true);
  node("message").value = "/recherche What is rain?";
  node("chat-form").listeners.submit({preventDefault() {}});
  await until(() => stream);
  stream.enqueue(encoder.encode('{"progress":"sear'));
  stream.enqueue(encoder.encode('ching"}\n{"progress":"reading"}\n'));
  await until(() => node("chat-status").textContent.includes("Reading a source"));
  assert.ok(node("journal").children.some(article => article.firstChild.textContent.includes("Reading a source")));
  stream.enqueue(encoder.encode(JSON.stringify({reply: {
    source: "research", text: "Rain is liquid water.",
    sources: [{title: "Weather atlas", domain: "example.org"}],
  }}) + "\n"));
  stream.close();
  const words = () => node("journal").children.flatMap(article => article.children.map(child => child.textContent));
  await until(() => words().some(text => text?.includes("Weather atlas (example.org)")));
  assert.ok(words().some(text => text?.includes("[ INTERNET RESEARCH ]")));
  assert.ok(!words().some(text => text?.includes("Reading a source")));
});

test("live refreshes leave a history request running and coalesce a follow-up", async t => {
  mountPage();
  const requests = [];
  const view = new ClimateView((path, {signal}) => new Promise(resolve => requests.push({path, signal, resolve})));
  view.feed = new AbortController();
  t.after(() => view.close());
  view.select("24h");
  await until(() => requests.length === 1);
  view.scheduleHistory(0);
  view.scheduleHistory(0);
  await sleep(20);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].signal.aborted, false);
  requests[0].resolve(history);
  await until(() => requests.length === 2);
  assert.equal(requests[1].path, historyRoute);
  assert.equal(view.history, history);
  view.select("24h");
  assert.equal(view.history, history);
  view.close();
  assert.equal(requests[1].signal.aborted, true);
});

test("sensor cards show last report, battery warning and LQI separately from service status", () => {
  const {node} = mountPage();
  const view = new ClimateView(() => assert.fail("Unexpected network request"));
  view.statusAvailable = true;
  view.snapshot = {services: {mqtt: "online", zigbee2mqtt: "online"}, sensors: [
    {id: "forge", name: "Forge", location: "indoor", status: "stale", connection: "connected",
      last_report_ms: 1_800_000_000_000, battery_low: true,
      readings: {battery: {value: 18}, linkquality: {value: 170}}},
    {id: "sim-exterior", name: "Simulated exterior", location: "outdoor", status: "stale", connection: "lost",
      readings: {}},
  ]};
  view.render();
  const [forge, exterior] = node("cards").children;
  assert.equal(node("climate-services").textContent, "MQTT ONLINE  /  ZIGBEE2MQTT ONLINE");
  assert.deepEqual(forge.children[3].children.map(label => label.textContent), ["Battery 18% LOW", "LQI 170"]);
  assert.match(forge.children[4].children[0].textContent, /^Last report .+/);
  assert.equal(forge.children[4].children[1].textContent, "CONNECTED");
  assert.equal(exterior.children[4].children[1].textContent, "SIGNAL LOST");
  view.statusAvailable = false;
  view.render();
  assert.equal(node("cards").children[0].children[4].children[1].textContent, "SIGNAL UNKNOWN");
});

test("administration previews a selection before confirming and clears its token on lock", async t => {
  const {node, storage} = mountPage();
  const requests = [];
  const view = new ClimateAdminView(async (path, {headers, body}) => {
    requests.push({path, body});
    assert.equal(headers["X-Marsi-Admin-Token"], "synthetic-admin-token");
    if (path.endsWith("/status")) return {sensors: [], discoveries: [], services: {mqtt: "online", zigbee2mqtt: "online"}};
    if (path.endsWith("/preview")) return {action: "delete", count: 2, scope: body.filters, preview_id: "test-preview"};
    assert.ok(path.endsWith("/confirm"));
    assert.deepEqual(body, {preview_id: "test-preview", confirm: true});
    return {action: "delete", readings_deleted: 2, backup: "test.sqlite3"};
  });
  t.after(() => view.close());
  node("admin-token").value = "synthetic-admin-token";
  node("admin-login").listeners.submit({preventDefault() {}});
  await until(() => node("admin-controls").hidden === false);
  assert.equal(node("admin-token").value, "");
  assert.equal(storage.size, 0);
  node("admin-filter-sensor").value = "forge";
  node("admin-delete").listeners.click();
  await until(() => node("admin-dialog").open);
  assert.match(node("admin-preview").textContent, /Delete 2 readings/);
  node("admin-cancel").listeners.click();
  assert.equal(requests.some(({path}) => path.endsWith("/confirm")), false);

  node("admin-delete").listeners.click();
  await until(() => node("admin-dialog").open);
  node("admin-confirm").listeners.click();
  await until(() => node("admin-notice").textContent.includes("test.sqlite3"));
  node("admin-lock").listeners.click();
  assert.equal(view.token, "");
  assert.equal(node("admin-controls").hidden, true);
});
