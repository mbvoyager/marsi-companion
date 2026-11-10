import assert from "node:assert/strict";
import {test} from "node:test";
import {setTimeout as sleep} from "node:timers/promises";
import {ClimateView} from "../marsi_local/web/climate.mjs";

class Element {
  attributes = {};
  children = [];
  dataset = {};
  listeners = {};
  style = {};

  addEventListener(name, listener) { this.listeners[name] = listener; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  prepend(...children) { this.children.unshift(...children); }
  pause() {}
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

test("login and page reload request the selected climate history after authentication", async t => {
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
