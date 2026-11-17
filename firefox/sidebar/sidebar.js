import { Lab3, SYSTEM_PROMPT, loadSettings, saveSettings, onSettingsChanged } from "../lib/lab3.js";

const $ = (id) => document.getElementById(id);
const log = $("log"), input = $("input"), form = $("composer");
const sendBtn = $("send"), stopBtn = $("stop"), thinkBtn = $("think");
const statusEl = $("status"), statusText = $("status-text");

let settings = await loadSettings();
let lab3 = new Lab3(settings);
let busy = false;
let history = [];        // this session's messages, without the system prompt
let controller = null;   // aborts the reply in progress

// --- status --------------------------------------------------------------

function setStatus(state, text, title = text) {
  statusEl.dataset.state = state;
  statusText.textContent = text;
  statusEl.title = title;
}

async function checkLab3() {
  if (!settings.key) {
    setStatus("down", "no key", "Add lab3's browser key in settings.");
    return;
  }
  try {
    await lab3.check();
    setStatus("ok", settings.model, `lab3 · ${settings.model} (${settings.baseURL})`);
  } catch (e) {
    setStatus("down", "offline", `${settings.baseURL}: ${e.message}`);
  }
}
checkLab3();
setInterval(() => { if (!busy) checkLab3(); }, 20000);

onSettingsChanged(async () => {
  settings = await loadSettings();
  lab3 = new Lab3(settings);
  renderThink();
  checkLab3();
});

// --- thinking toggle ------------------------------------------------------

function renderThink() {
  thinkBtn.setAttribute("aria-pressed", String(settings.think));
  thinkBtn.title = settings.think
    ? "Thinking: on (slower, better at multi-step tasks)"
    : "Thinking: off (faster answers)";
}
renderThink();
thinkBtn.addEventListener("click", async () => {
  settings.think = !settings.think;
  renderThink();
  await saveSettings({ think: settings.think });
});

// --- log ------------------------------------------------------------------

function turnEl(who, label) {
  $("empty")?.remove();
  const el = document.createElement("section");
  el.className = `turn ${who}`;
  const tag = document.createElement("div");
  tag.className = "who";
  tag.textContent = label;
  const body = document.createElement("div");
  body.className = "body";
  el.append(tag, body);
  log.append(el);
  log.scrollTop = log.scrollHeight;
  return { el, body };
}

function note(text, error = false) {
  const el = document.createElement("div");
  el.className = error ? "note error" : "note";
  el.textContent = text;
  log.append(el);
  log.scrollTop = log.scrollHeight;
}

async function run(text) {
  busy = true;
  sendBtn.hidden = true;
  stopBtn.hidden = false;

  turnEl("you", "you").body.textContent = text;
  history.push({ role: "user", content: text });

  const { el, body } = turnEl("agent", `agent · ${settings.model}`);
  el.classList.add("working");
  let trace = null, traceText = null, reply = "";
  const started = performance.now();
  controller = new AbortController();

  try {
    const messages = [{ role: "system", content: SYSTEM_PROMPT }, ...history];
    for await (const d of lab3.chat(messages, { think: settings.think, signal: controller.signal })) {
      if (d.type === "think") {
        if (!trace) {
          trace = document.createElement("details");
          trace.className = "thinking";
          trace.innerHTML = "<summary>thinking…</summary>";
          traceText = document.createElement("div");
          traceText.className = "trace";
          trace.append(traceText);
          el.insertBefore(trace, body);
        }
        traceText.textContent += d.text;
      } else {
        reply += d.text;
        body.textContent = reply.trimStart();
      }
      log.scrollTop = log.scrollHeight;
    }
  } catch (e) {
    if (e.name === "AbortError") el.classList.add("cut");
    else {
      note(`error: ${e.message}`, true);
      setStatus("down", "offline", e.message);
    }
  } finally {
    if (trace) {
      const secs = ((performance.now() - started) / 1000).toFixed(1);
      trace.querySelector("summary").textContent = `thought · ${secs}s total`;
    }
    el.classList.remove("working");
    reply = reply.trim();
    if (reply) history.push({ role: "assistant", content: reply });
    else if (!el.classList.contains("cut")) body.textContent = "(no answer)";
    controller = null;
    busy = false;
    stopBtn.hidden = true;
    sendBtn.hidden = false;
    input.focus();
  }
}

// --- composer -------------------------------------------------------------

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
  sendBtn.disabled = !input.value.trim();
}
autosize();
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    form.requestSubmit();
  }
  if (e.key === "Escape") controller?.abort();
});
form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;
  if (!settings.key) {
    note("no key: click cfg and paste lab3's browser key first.", true);
    return;
  }
  input.value = "";
  autosize();
  run(text);
});
stopBtn.addEventListener("click", () => controller?.abort());

$("clear").addEventListener("click", () => {
  if (busy) controller?.abort();
  history = [];
  log.textContent = "";
  const empty = document.createElement("div");
  empty.id = "empty";
  empty.className = "empty";
  empty.innerHTML = '<p class="prompt">&gt; ready_</p><p>New session.</p>';
  log.append(empty);
  input.focus();
});

$("settings").addEventListener("click", () => {
  if (globalThis.browser?.runtime?.openOptionsPage) browser.runtime.openOptionsPage();
  else window.open("../options/options.html", "_blank");
});

input.focus();
