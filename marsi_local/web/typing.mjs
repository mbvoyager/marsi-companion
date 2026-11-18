// Complete replies already exist locally. This is a bounded display effect,
// independent of model output, audio playback and the durable journal.
const active = new Map();
export function finishTyping(node) {
  const current = active.get(node);
  if (current) { clearTimeout(current.timer); node.textContent = current.text; node.removeAttribute("aria-busy"); active.delete(node); }
}
export function finishAllTyping() { for (const node of active.keys()) finishTyping(node); }
export function typeText(node, text, {reduced = !globalThis.matchMedia || matchMedia("(prefers-reduced-motion: reduce)").matches, follow} = {}) {
  finishTyping(node);
  if (reduced || !text) { node.textContent = text; return; }
  const item = {text, count: 0}; active.set(node,item); node.setAttribute("aria-busy","true");
  const batch = Math.max(5,Math.ceil(text.length/70));
  function step() {
    if (active.get(node) !== item || node.isConnected === false) { finishTyping(node); return; }
    item.count = Math.min(text.length,item.count+batch);
    node.textContent = text.slice(0,item.count)+(item.count < text.length ? "▌" : "");
    follow?.();
    if (item.count >= text.length) { node.removeAttribute("aria-busy"); active.delete(node); }
    else item.timer = setTimeout(step,70);
  }
  node.textContent = "▌";
  item.timer = setTimeout(step,0);
}
