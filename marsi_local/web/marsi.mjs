import {ClimateView} from "./climate.mjs";
import {canRecord, openRecorder, replyBlob} from "./vox.mjs";

const $ = id => document.getElementById(id);
const journal = $("journal");
const voice = $("voice");
const player = $("reply-audio");
const mic = canRecord();
const sessionKey = "marsi-web-session";
const HELP = "art | sermon | bless | history | /remember TEXT | /notes | /forget | exit\nF8 or TALK opens the vox. F8 or FINISH seals the recording.";
const stampFormat = new Intl.DateTimeFormat("en-GB", {dateStyle: "short", timeStyle: "short"});
const state = {generation: 0, journalEpoch: 0, unlocked: false, session: "pi", token: "", tab: "chat", entries: new Map()};

async function request(path, {method = "GET", body, signal, headers, stream = false} = {}) {
  const parent = signal || state.connection?.signal;
  const deadline = stream ? null : new AbortController();
  const abort = () => deadline?.abort();
  let timer;
  if (deadline) {
    if (parent?.aborted) abort();
    else parent?.addEventListener("abort", abort, {once: true});
    timer = setTimeout(abort, method === "GET" ? 8000 : 245_000);
  }
  const options = {
    method, cache: "no-store", redirect: "error", signal: deadline?.signal || parent,
    headers: {Authorization: `Bearer ${state.token}`, "X-Marsi-Session": state.session, ...headers},
  };
  if (body instanceof Blob) {
    options.body = body;
    options.headers["Content-Type"] = "audio/wav";
  } else if (body !== undefined) {
    options.body = JSON.stringify(body);
    options.headers["Content-Type"] = "application/json";
  }
  try {
    const response = await fetch(path, options);
    if (!response.ok) {
      let detail = `The archive rejected the request (${response.status}).`;
      if (response.headers.get("content-type")?.includes("application/json")) {
        detail = (await response.json().catch(() => null))?.error || detail;
      }
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return stream ? response : await response.json();
  } finally {
    clearTimeout(timer);
    parent?.removeEventListener("abort", abort);
  }
}

const climate = new ClimateView(request);

function journalRequest(query = {}) {
  return request("/v1/journal?" + new URLSearchParams({session_id: state.session, ...query}));
}

function notice(id, text, error = false) {
  const label = $(id);
  label.textContent = text;
  label.dataset.error = error;
}

function link(text, kind) {
  const label = $("link");
  label.textContent = text;
  label.dataset.state = kind;
}

function selectView(tab) {
  state.tab = tab;
  $("chat").hidden = tab !== "chat";
  $("climate").hidden = tab !== "climate";
  for (const view of ["chat", "climate"]) $("tab-" + view).setAttribute("aria-pressed", view === tab);
  if (tab === "climate") climate.open();
  else climate.close();
}

function nowStamp(at) {
  const date = new Date(at);
  return Number.isNaN(date.valueOf()) ? "ARCHIVE" : stampFormat.format(date);
}

function entryNode(role, caption, words) {
  const node = document.createElement("article");
  node.className = "entry " + role;
  const stamp = document.createElement("p");
  stamp.className = "stamp";
  stamp.textContent = caption;
  const text = document.createElement("p");
  text.className = "words";
  text.textContent = words;
  node.append(stamp, text);
  return node;
}

function showWords(words, role = "system") {
  const who = role === "marsi" ? "MARSI" : "ARCHIVE";
  journal.append(entryNode(role, `[ ${who} ]`, words));
  journal.scrollTop = journal.scrollHeight;
}

function addEntries(entries, {older = false, scroll = false} = {}) {
  const atBottom = journal.scrollHeight - journal.scrollTop - journal.clientHeight < 36;
  const previousHeight = journal.scrollHeight;
  const added = [];
  for (const entry of entries) {
    if (state.entries.has(entry.id)) continue;
    const who = entry.role === "human" ? "HUMAN" : "MARSI";
    const node = entryNode(entry.role, `[ ${nowStamp(entry.at)} / ${entry.kind.toUpperCase()} ] ${who} >`, entry.text);
    if (entry.spoken_text && ["morning", "sermon", "art"].includes(entry.kind)) {
      const play = document.createElement("button");
      play.type = "button";
      play.className = "replay";
      play.textContent = "PLAY VOX";
      play.addEventListener("click", () => speakEntry(entry.id));
      node.append(play);
    }
    let nextId = Infinity;
    for (const id of state.entries.keys()) if (entry.id < id && id < nextId) nextId = id;
    journal.insertBefore(node, state.entries.get(nextId) || state.pending?.node || null);
    state.entries.set(entry.id, node);
    added.push(entry);
  }
  if (state.entries.size > 600) {
    const ids = [...state.entries.keys()].sort((a, b) => a - b);
    for (const id of older ? ids.slice(500) : ids.slice(0, -500)) {
      state.entries.get(id).remove();
      state.entries.delete(id);
    }
    if (!older) $("older").disabled = false;
  }
  if (older) journal.scrollTop += journal.scrollHeight - previousHeight;
  else if (scroll || atBottom) journal.scrollTop = journal.scrollHeight;
  return added;
}

function beginPending(label, human) {
  const node = entryNode(human ? "human" : "system", "[ CONSULTING THE COGITATOR ]", label);
  const bar = document.createElement("progress");
  bar.max = 100;
  bar.value = 2;
  bar.setAttribute("aria-label", "Estimated response progress");
  node.append(bar);
  journal.append(node);
  journal.scrollTop = journal.scrollHeight;
  const started = performance.now();
  const timer = setInterval(() => { bar.value = Math.min(92, 2 + (performance.now() - started) / 420); }, 300);
  state.pending = {node, timer, bar};
}

function endPending(success) {
  const pending = state.pending;
  if (!pending) return;
  clearInterval(pending.timer);
  if (success) pending.node.remove();
  else {
    pending.bar.remove();
    pending.node.firstChild.textContent = "[ TRANSMISSION UNSEALED ]";
  }
  state.pending = null;
}

function setControls() {
  const busy = state.busy || state.opening || state.recorder;
  $("send").disabled = Boolean(busy);
  $("talk").disabled = !mic || state.busy || state.opening || state.finishing;
  $("talk").textContent = state.recorder ? "FINISH" : "TALK";
  $("older").disabled = !state.hasOlder || state.journalBusy || Boolean(busy);
  for (const button of document.querySelectorAll("[data-command]")) button.disabled = Boolean(busy);
}

function clearAudio() {
  player.pause();
  if (state.audioUrl) {
    player.removeAttribute("src");
    player.load();
    URL.revokeObjectURL(state.audioUrl);
  }
  state.audioUrl = null;
  player.hidden = true;
}

function lockArchive(message = "") {
  state.generation += 1;
  state.connection?.abort();
  climate.reset();
  state.recorder?.cancel();
  state.recorder = null;
  state.unlocked = state.busy = state.opening = state.finishing = state.journalBusy = false;
  state.token = "";
  state.hasOlder = false;
  state.entries.clear();
  endPending(true);
  clearAudio();
  journal.replaceChildren();
  $("message").value = $("token").value = "";
  $("gate").hidden = false;
  $("connect").disabled = false;
  $("chat").hidden = $("climate").hidden = $("navigation").hidden = true;
  link("[ ARCHIVE SEALED ]", "waiting");
  notice("gate-status", message, Boolean(message));
  try { sessionStorage.removeItem(sessionKey); } catch {}
}

async function openArchive(token, session) {
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(session)) {
    notice("gate-status", "Use a session name with letters, numbers, underscores or hyphens.", true);
    return;
  }
  const generation = ++state.generation;
  state.connection?.abort();
  state.connection = new AbortController();
  state.token = token;
  state.session = session;
  $("connect").disabled = true;
  notice("gate-status", "[ LINK ] Seeking the little forge ...");
  try {
    const page = await journalRequest();
    if (generation !== state.generation) return;
    state.unlocked = true;
    state.hasOlder = page.has_more;
    state.nextRite = nextRite();
    try { sessionStorage.setItem(sessionKey, JSON.stringify({token, session})); } catch {}
    $("token").value = "";
    $("gate").hidden = true;
    $("navigation").hidden = false;
    selectView("chat");
    if (!page.entries.length) showWords("Bring me an observation, little keeper. Type help for the local command cant.");
    addEntries(page.entries, {scroll: true});
    link("[ LINK ONLINE ]", "live");
    notice("chat-status", "[ ARCHIVE ] F8 to talk.");
    setControls();
    refreshTelemetry();
  } catch (error) {
    if (generation !== state.generation) return;
    lockArchive(error.status === 401 ? "The archive seal rejected that token." : "The forge link is quiet. Try opening the archive again.");
  } finally {
    if (generation === state.generation) $("connect").disabled = false;
  }
}

function requestFailed(error) {
  if (error.status === 401) lockArchive("The archive needs your Marsi token again.");
  else if (!error.status) link("[ LINK RETRY ]", "waiting");
}

async function refreshJournal(older = false) {
  if (!state.unlocked || state.journalBusy || state.busy || state.recorder || state.opening) return;
  const generation = state.generation;
  const epoch = state.journalEpoch;
  const ids = [...state.entries.keys()];
  if (older && (!ids.length || !state.hasOlder)) return;
  state.journalBusy = true;
  setControls();
  try {
    const page = await journalRequest(older ? {before: Math.min(...ids)} : {after: Math.max(0, ...ids)});
    if (generation !== state.generation || epoch !== state.journalEpoch) return;
    const added = addEntries(page.entries, {older});
    if (older) state.hasOlder = page.has_more;
    link("[ LINK ONLINE ]", "live");
    const spoken = added.find(entry => entry.scheduled && entry.spoken_text && ["morning", "sermon"].includes(entry.kind));
    if (!older && spoken && voice.checked && document.visibilityState === "visible" && (spoken.kind === "morning" || !quietHour())) {
      speakEntry(spoken.id);
    }
  } catch (error) {
    if (generation === state.generation) requestFailed(error);
  } finally {
    if (generation === state.generation) {
      state.journalBusy = false;
      setControls();
    }
  }
}

async function refreshTelemetry() {
  if (!state.unlocked || state.tab !== "chat") return;
  const generation = state.generation;
  try {
    const telemetry = await request("/v1/telemetry");
    if (generation !== state.generation) return;
    const field = (value, unit = "") => value == null ? "--" : `${value}${unit}`;
    $("telemetry").textContent = ["pi", "server"].map(name => {
      const data = telemetry[name];
      return data ? `${name.toUpperCase()} CPU ${field(data.cpu_percent, "%")} / ${field(data.temperature_c, "C")}\nLOAD ${field(data.load1)} / DISK ${field(data.disk_used_percent, "%")}`
        : `${name.toUpperCase()} / LINK SILENT`;
    }).join("\n\n");
  } catch (error) {
    if (generation === state.generation) requestFailed(error);
  }
}

async function playReply(result, generation) {
  const blob = await replyBlob(result);
  if (!blob || generation !== state.generation) return;
  clearAudio();
  state.audioUrl = URL.createObjectURL(blob);
  player.src = state.audioUrl;
  player.hidden = false;
  try { await player.play(); }
  catch { if (generation === state.generation) notice("chat-status", "[ VOX ] Press Play to hear Marsi."); }
}

async function runTask(action, {label, human = false, forgot = false} = {}) {
  if (!state.unlocked || state.busy || state.opening || state.recorder) return;
  const generation = state.generation;
  if (forgot) state.journalEpoch += 1;
  state.busy = true;
  state.nextRite = nextRite();
  setControls();
  if (label) beginPending(label, human);
  notice("chat-status", "[ COGITATOR ] Consulting the little archive ...");
  try {
    const result = await action();
    if (generation !== state.generation) return;
    endPending(true);
    if (forgot) {
      state.entries.clear();
      journal.replaceChildren();
      state.hasOlder = false;
      clearAudio();
      showWords("The archive has been cleared for this session.");
    } else if (result.entries?.length) addEntries(result.entries, {scroll: true});
    else if (result.notes) showWords("Saved notes\n" + (result.notes.join("\n") || "[ EMPTY ]"));
    else if (result.text && result.source !== "playback") showWords(result.text, "marsi");
    link("[ LINK ONLINE ]", "live");
    notice("chat-status", result.voice_error ? "[ VOX ] " + result.voice_error : "[ RECEIVED ] Transmission sealed.");
    try { await playReply(result, generation); }
    catch (error) { if (generation === state.generation) notice("chat-status", "[ VOX ] " + error.message, true); }
  } catch (error) {
    if (generation !== state.generation) return;
    endPending(false);
    requestFailed(error);
    if (generation === state.generation) {
      notice("chat-status", "[ UNSEALED ] " + (error.status ? error.message : "The little forge link fell quiet."), true);
    }
  } finally {
    if (generation === state.generation) {
      state.busy = false;
      setControls();
      refreshJournal();
    }
  }
}

function jsonTask(path, body = {}, method = "POST") {
  return request(path, {method, body: {session_id: state.session, ...body}});
}

function speakEntry(id) {
  return runTask(() => jsonTask("/v1/speak", {entry_id: id, want_audio: true}));
}

function command(input) {
  if (!input || state.busy || state.recorder || state.opening) return;
  state.nextRite = nextRite();
  const action = input.toLowerCase().replace(/^\/+/, "");
  if (action === "exit" || action === "quit") lockArchive();
  else if (action === "help") showWords(HELP);
  else if (action === "history") refreshJournal(true);
  else if (action === "notes") runTask(() => request("/v1/memory?" + new URLSearchParams({session_id: state.session})));
  else if (action === "forget") {
    if (window.confirm(`Erase the saved journal and notes for session ${state.session}?`)) {
      runTask(() => jsonTask("/v1/session", {}, "DELETE"), {forgot: true});
    }
  } else if (input.startsWith("/remember ")) {
    runTask(() => jsonTask("/v1/memory", {text: input.slice(10)}));
  } else if (["art", "sermon", "ritual", "bless"].includes(action)) {
    const rite = action === "bless" ? "ritual" : action;
    runTask(() => jsonTask("/v1/" + rite, {want_audio: voice.checked}), {label: `Preparing a little ${rite} ...`});
  } else {
    runTask(() => jsonTask("/v1/chat", {text: input, want_audio: voice.checked}), {label: input, human: true});
  }
}

async function talk() {
  if (!state.unlocked || !mic || state.busy || state.opening) return;
  selectView("chat");
  if (state.recorder) {
    state.finishing = true;
    state.recorder.finish();
    setControls();
    return;
  }
  const generation = state.generation;
  state.opening = true;
  setControls();
  notice("chat-status", "[ VOX ] Opening the microphone ...");
  let timer;
  try {
    const recorder = await openRecorder();
    if (generation !== state.generation) {
      recorder.finished.catch(() => {});
      recorder.cancel();
      return;
    }
    state.opening = false;
    state.recorder = recorder;
    setControls();
    notice("chat-status", "[ VOX ] Listening. Press FINISH or F8 within 15 seconds.");
    timer = setTimeout(() => recorder.finish(), 15_500);
    const wav = await recorder.finished;
    if (generation !== state.generation) return;
    state.recorder = null;
    state.finishing = false;
    await runTask(() => request(`/v1/voice?want_audio=${voice.checked}`, {method: "POST", body: wav}),
                  {label: "Vox recording sealed. Awaiting transcription ..."});
  } catch (error) {
    if (generation === state.generation) {
      const message = error.name === "NotAllowedError" ? "The vox needs microphone permission, little keeper." : error.message;
      notice("chat-status", "[ VOX ] " + message, true);
    }
  } finally {
    clearTimeout(timer);
    if (generation === state.generation) {
      state.opening = state.finishing = false;
      state.recorder = null;
      setControls();
    }
  }
}

function quietHour() {
  const hour = new Date().getHours();
  return hour >= 22 || hour < 8;
}

function nextRite() {
  return Date.now() + 600_000 + Math.random() * 600_000;
}

$("gate-form").addEventListener("submit", event => {
  event.preventDefault();
  openArchive($("token").value.trim(), $("session").value.trim());
});
$("chat-form").addEventListener("submit", event => {
  event.preventDefault();
  if (state.busy || state.recorder || state.opening) return;
  const input = $("message").value.trim();
  $("message").value = "";
  command(input);
});
$("older").addEventListener("click", () => refreshJournal(true));
$("latest").addEventListener("click", () => { journal.scrollTop = journal.scrollHeight; refreshJournal(); });
$("talk").addEventListener("click", talk);
$("tab-chat").addEventListener("click", () => { selectView("chat"); refreshTelemetry(); });
$("tab-climate").addEventListener("click", () => selectView("climate"));
$("lock").addEventListener("click", () => lockArchive());
for (const button of document.querySelectorAll("[data-command]")) button.addEventListener("click", () => command(button.dataset.command));
document.addEventListener("keydown", event => {
  if (event.key === "F8" && state.unlocked) {
    event.preventDefault();
    if (!event.repeat) talk();
  }
});
$("idle").addEventListener("change", () => { state.nextRite = nextRite(); });
setInterval(() => {
  if (!state.unlocked) return;
  refreshJournal();
  refreshTelemetry();
  if ($("idle").checked && document.visibilityState === "visible" && !quietHour() && Date.now() >= state.nextRite) {
    runTask(() => jsonTask("/v1/ritual"), {label: "A tiny idle rite ..."});
  }
}, 10_000);

if (!mic) {
  $("vox-hint").hidden = false;
  $("vox-hint").textContent = "[ VOX ] Open the trusted local HTTPS address to use the microphone.";
}
setControls();
try {
  const saved = JSON.parse(sessionStorage.getItem(sessionKey) || "null");
  if (saved && typeof saved.token === "string" && typeof saved.session === "string") {
    $("session").value = saved.session;
    openArchive(saved.token, saved.session);
  }
} catch {}
