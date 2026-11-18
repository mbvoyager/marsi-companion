import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import {setTimeout as sleep} from "node:timers/promises";
import {InterludeView, validPacket, sceneRandom} from "../marsi_local/web/interludes.mjs";
import {typeText, finishTyping} from "../marsi_local/web/typing.mjs";

const packets = JSON.parse(readFileSync(new URL("./fixtures/interludes.json",import.meta.url),"utf8"));

test("scene seed matches Tk's portable sequence", () => {
  const rng = sceneRandom(42);
  assert.deepEqual(Array.from({length:3},() => Math.floor(rng()*2**32)),[1083814273,378494188,2479403867]);
});

test("the same six JSON scenes render locally at phone and desktop widths", () => {
  const text = [];
  const context = new Proxy({fillText: (...args) => text.push(args)}, {get: (target,key) => target[key] ?? (() => {})});
  const element = tag => ({tag,clientWidth:375,clientHeight:440,
    setAttribute() {}, addEventListener() {}, focus() {}, getContext: () => context,
    replaceChildren(...children) { this.children = children; }});
  globalThis.document = {createElement:element, activeElement:element("button"),addEventListener(){},removeEventListener(){}};
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  globalThis.getComputedStyle = () => ({getPropertyValue: () => ""});
  globalThis.requestAnimationFrame = () => 1;
  globalThis.cancelAnimationFrame = () => {};
  globalThis.fetch = () => assert.fail("Rendering must not use the Internet");
  for (const width of [375,1024]) for (const packet of packets) {
    assert.ok(validPacket(packet));
    const view = new InterludeView(element("section"),packet);
    view.canvas.clientWidth = width;
    view.paint(view.started+1000);
    view.paint(view.started+2000);
    assert.equal(view.w,width);
    assert.ok(text.some(([value]) => String(value).includes("++")));
    assert.ok(view.summary.textContent.includes("Forge: 21.4 °C"));
    view.close(); assert.equal(view.closed,true);
  }
  assert.equal(validPacket({...packets[0],type:"art"}),false);
});

test("reduced motion shows the complete text and moving-block typing can be finished", async () => {
  const node = {isConnected:true, setAttribute(){},removeAttribute(){}};
  const text = "A small and rather delighted greeting from the archive. ".repeat(10);
  typeText(node,text,{reduced:true}); assert.equal(node.textContent,text);
  typeText(node,text,{reduced:false});
  await sleep(85);
  assert.ok(node.textContent.endsWith("▌"));
  assert.ok(node.textContent.length < text.length);
  finishTyping(node); assert.equal(node.textContent,text);
});

test("the web shell has no effigy and the shared theme defines sensor identities", () => {
  const html = readFileSync(new URL("../marsi_local/web/index.html",import.meta.url),"utf8");
  assert.doesNotMatch(html,/effigy|portrait|electoo/i);
  assert.match(html,/\/web\/theme.css/);
  assert.match(html,/id="interlude"/);
  const theme = JSON.parse(readFileSync(new URL("../marsi_local/web/cogitator.json",import.meta.url),"utf8"));
  assert.equal(new Set(theme.sensors.map(s => s.color)).size,4);
  assert.equal(new Set(theme.sensors.map(s => s.shape)).size,4);
  assert.equal(new Set(theme.sensors.map(s => String(s.dash))).size,4);
});
