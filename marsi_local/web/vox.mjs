export function canRecord() {
  return Boolean(globalThis.isSecureContext && navigator.mediaDevices?.getUserMedia && globalThis.AudioWorkletNode);
}

export function encodeWav(chunks, inputRate) {
  const count = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const rate = 16_000;
  const ratio = inputRate / rate;
  const frames = Math.min(15 * rate, Math.floor(count / ratio));
  if (frames < rate / 10) throw new Error("A little longer, keeper. The vox caught only a moment.");
  const samples = new Float32Array(count);
  let offset = 0;
  for (const chunk of chunks) {
    samples.set(chunk, offset);
    offset += chunk.length;
  }
  const wav = new ArrayBuffer(44 + frames * 2);
  const view = new DataView(wav);
  const tag = (at, label) => {
    for (let i = 0; i < label.length; i++) view.setUint8(at + i, label.charCodeAt(i));
  };
  tag(0, "RIFF");
  view.setUint32(4, wav.byteLength - 8, true);
  tag(8, "WAVE");
  tag(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  tag(36, "data");
  view.setUint32(40, frames * 2, true);
  for (let i = 0; i < frames; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(count, Math.max(start + 1, Math.floor((i + 1) * ratio)));
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    const value = Math.max(-1, Math.min(1, sum / (end - start)));
    view.setInt16(44 + i * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
  }
  return new Blob([wav], {type: "audio/wav"});
}

export async function openRecorder() {
  const Audio = globalThis.AudioContext || globalThis.webkitAudioContext;
  const context = new Audio();
  let stream;
  try {
    await context.resume();
    await context.audioWorklet.addModule("/web/recorder.js");
    stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true}});
    if (context.state !== "running") await context.resume();
    const node = new AudioWorkletNode(context, "marsi-recorder");
    const source = context.createMediaStreamSource(stream);
    const chunks = [];
    let finishTimer, settled = false;
    let resolve, reject;
    const finished = new Promise((yes, no) => { resolve = yes; reject = no; });
    function complete(error) {
      if (settled) return;
      settled = true;
      clearTimeout(finishTimer);
      for (const track of stream.getTracks()) track.stop();
      source.disconnect();
      node.disconnect();
      node.port.close();
      context.close().catch(() => {});
      if (error) reject(error);
      else {
        try { resolve(encodeWav(chunks, context.sampleRate)); }
        catch (failure) { reject(failure); }
      }
    }
    node.port.onmessage = ({data}) => {
      if (data === "done") complete();
      else if (data instanceof Float32Array) chunks.push(data);
    };
    node.onprocessorerror = () => complete(new Error("The vox circuit fell silent."));
    source.connect(node).connect(context.destination);
    return {
      finished,
      finish() {
        if (settled || finishTimer) return;
        node.port.postMessage("finish");
        finishTimer = setTimeout(() => complete(), 1000);
      },
      cancel() { complete(new DOMException("Recording cancelled", "AbortError")); },
    };
  } catch (error) {
    for (const track of stream?.getTracks() || []) track.stop();
    context.close().catch(() => {});
    throw error;
  }
}

export async function replyBlob(reply) {
  if (!reply.audio_base64) return null;
  if (typeof reply.audio_base64 !== "string" || reply.audio_base64.length > 10_666_668) {
    throw new Error("The vox reply exceeds its expected size.");
  }
  const raw = atob(reply.audio_base64);
  const bytes = Uint8Array.from(raw, char => char.charCodeAt(0));
  const info = reply.audio_info;
  if (!bytes.length || bytes.length > 8_000_000 || (info && info.bytes !== bytes.length)) {
    throw new Error("The vox reply arrived incomplete.");
  }
  if (info?.sha256 && globalThis.crypto?.subtle) {
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
    const hash = Array.from(digest, byte => byte.toString(16).padStart(2, "0")).join("");
    if (hash !== info.sha256) throw new Error("The vox reply failed its integrity check.");
  }
  return new Blob([bytes], {type: "audio/wav"});
}
