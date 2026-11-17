import { Lab3, SYSTEM_PROMPT, loadSettings, saveSettings, onSettingsChanged } from "../lib/lab3.js";
import { TOOLS, Tools, describeCall, blockedReason } from "../lib/tools.js";

const $ = (id) => document.getElementById(id);
const log = $("log"), input = $("input"), form = $("composer");
const sendBtn = $("send"), stopBtn = $("stop"), thinkBtn = $("think");
const statusEl = $("status"), statusText = $("status-text");
const accessBar = $("access");

const MAX_STEPS = 30;          // tool calls per task before it stops and asks
const KEEP_READS = 2;          // full page reads kept in context; older ones are shortened

const isExtension = !!globalThis.browser?.tabs;
let settings = await loadSettings();
let lab3 = new Lab3(settings);
let busy = false;
let history = [];        // this session's messages, without the system prompt
let controller = null;   // aborts the task in progress
let tools = null;        // per session: remembers the current tab and tabs it opened

function newTools() {
  return isExtension ? new Tools({ settings, confirm: askConfirm, onTab: () => {} }) : null;
}
tools = newTools();

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
  if (tools) tools.settings = settings;
  renderThink();
  checkLab3();
});

// --- page access ----------------------------------------------------------

const ALL = { origins: ["<all_urls>"] };
async function checkAccess() {
  if (!isExtension) { accessBar.hidden = true; return; }
  accessBar.hidden = await browser.permissions.contains(ALL);
}
checkAccess();
$("allow").addEventListener("click", async () => {
  // request() must be the first await after the click.
  try { await browser.permissions.request(ALL); } catch {}
  checkAccess();
});
globalThis.browser?.permissions?.onAdded?.addListener(checkAccess);
globalThis.browser?.permissions?.onRemoved?.addListener(checkAccess);

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

const scroll = () => { log.scrollTop = log.scrollHeight; };

function turnEl(who, label) {
  $("empty")?.remove();
  const el = document.createElement("section");
  el.className = `turn ${who}`;
  const tag = document.createElement("div");
  tag.className = "who";
  tag.textContent = label;
  el.append(tag);
  log.append(el);
  scroll();
  return el;
}

function block(parent, cls) {
  const b = document.createElement("div");
  b.className = cls;
  parent.append(b);
  scroll();
  return b;
}

function note(text, error = false) {
  $("empty")?.remove();
  const el = document.createElement("div");
  el.className = error ? "note error" : "note";
  el.textContent = text;
  log.append(el);
  scroll();
}

function stepEl(parent, text) {
  const s = block(parent, "step running");
  s.textContent = text;
  return {
    done(result, failed = false) {
      s.classList.remove("running");
      if (failed) s.classList.add("failed");
      if (result) s.title = result;
      const tail = document.createElement("span");
      tail.className = "res";
      tail.textContent = failed ? ` · ${result}` : "";
      s.append(tail);
    },
  };
}

// Just enough markdown for the model's replies: **bold**, `code`, headings.
const esc = (t) => t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
function renderText(el, text) {
  el.innerHTML = esc(text)
    .replace(/^#{1,6} (.*)$/gm, "<strong>$1</strong>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`\n]+)`/g, "<code>$1</code>");
}

// The confirm card: everything that will be sent, then Allow / Refuse.
let pendingConfirm = null;
let currentTurn = null;   // where confirm cards go
function askConfirm({ title, why, url, fields }) {
  return new Promise((resolve) => {
    const card = document.createElement("div");
    card.className = "confirm";
    const h = document.createElement("div");
    h.className = "c-title";
    h.textContent = `confirm · ${title}`;
    const w = document.createElement("div");
    w.className = "c-why";
    w.textContent = `${why}${url ? ` · ${new URL(url).host}` : ""}`;
    card.append(h, w);
    if (fields?.length) {
      const dl = document.createElement("dl");
      for (const f of fields) {
        const dt = document.createElement("dt"); dt.textContent = f.field;
        const dd = document.createElement("dd"); dd.textContent = f.value;
        dl.append(dt, dd);
      }
      card.append(dl);
    }
    const row = document.createElement("div");
    row.className = "c-row";
    const yes = document.createElement("button"); yes.type = "button"; yes.className = "send"; yes.textContent = "allow";
    const no = document.createElement("button"); no.type = "button"; no.className = "send stop"; no.textContent = "refuse";
    row.append(yes, no);
    card.append(row);
    (currentTurn || log).append(card);
    scroll();
    yes.focus();
    const finish = (ok) => {
      pendingConfirm = null;
      row.remove();
      card.classList.add(ok ? "allowed" : "refused");
      const r = document.createElement("div");
      r.className = "c-result";
      r.textContent = ok ? "allowed" : "refused";
      card.append(r);
      resolve(ok);
    };
    pendingConfirm = finish;
    yes.addEventListener("click", () => finish(true));
    no.addEventListener("click", () => finish(false));
  });
}

// Older page reads are the bulk of the context; keep the latest few whole.
function compact(msgs) {
  let reads = 0;
  return msgs.slice().reverse().map((m) => {
    if (m.role === "tool" && m.content.startsWith("PAGE CONTENT")) {
      reads++;
      if (reads > KEEP_READS) return { ...m, content: m.content.split("\n---\n")[0] + "\n---\n(older read dropped to save space; read again if needed)" };
    }
    return m;
  }).reverse();
}

async function tabContext() {
  if (!isExtension) return "";
  try {
    const t = await tools.currentTab();
    const blocked = blockedReason(t.url, settings.blocked);
    return `[current tab ${t.id}: ${t.title} — ${t.url}${blocked ? " — BLOCKED, don't read or act on it" : ""}]\n\n`;
  } catch { return ""; }
}

async function run(text) {
  busy = true;
  sendBtn.hidden = true;
  stopBtn.hidden = false;
  controller = new AbortController();
  const signal = controller.signal;
  signal.addEventListener("abort", () => pendingConfirm?.(false));   // stop = refuse

  turnEl("you", "you").append(Object.assign(document.createElement("div"), { className: "body", textContent: text }));
  if (tools) tools.tabId = null;    // each task starts on the tab in front
  history.push({ role: "user", content: (await tabContext()) + text });

  const turn = turnEl("agent", `agent · ${settings.model}`);
  currentTurn = turn;
  turn.classList.add("working");
  const started = performance.now();
  let steps = 0;

  try {
    for (;;) {
      let trace = null, traceText = null, body = null, reply = "", calls = [];
      for await (const d of lab3.chat([{ role: "system", content: SYSTEM_PROMPT }, ...compact(history)],
                                      { think: settings.think, tools: isExtension ? TOOLS : undefined, signal })) {
        if (d.type === "think") {
          if (!trace) {
            trace = document.createElement("details");
            trace.className = "thinking";
            trace.innerHTML = "<summary>thinking…</summary>";
            traceText = document.createElement("div");
            traceText.className = "trace";
            trace.append(traceText);
            turn.append(trace);
          }
          traceText.textContent += d.text;
        } else if (d.type === "text") {
          reply += d.text;
          if (!body && reply.trim()) { body = block(turn, "body live"); }
          if (body) renderText(body, reply.trimStart());
        } else if (d.type === "tools") {
          calls = d.calls;
        }
        scroll();
      }
      if (trace) trace.querySelector("summary").textContent = "thought";
      body?.classList.remove("live");

      const msg = { role: "assistant", content: reply.trim() };
      if (calls.length) {
        msg.tool_calls = calls.map((c) => ({ id: c.id, type: "function", function: { name: c.name, arguments: JSON.stringify(c.args) } }));
      }
      history.push(msg);
      if (!calls.length) break;

      for (const c of calls) {
        if (++steps > MAX_STEPS) throw new Error(`stopped after ${MAX_STEPS} steps; say "continue" to keep going`);
        const s = stepEl(turn, describeCall(c));
        let result;
        try {
          if (c.args._unparsed !== undefined) throw new Error("couldn't read the tool arguments");
          result = String(await tools.run(c.name, c.args));
          s.done(result.split("\n")[0]);
        } catch (e) {
          result = `error: ${e.message}`;
          s.done(e.message, true);
        }
        history.push({ role: "tool", tool_call_id: c.id, content: result });
        if (signal.aborted) throw new DOMException("stopped", "AbortError");
      }
    }
  } catch (e) {
    if (e.name === "AbortError") turn.classList.add("cut");
    else {
      note(`error: ${e.message}`, true);
      if (/lab3|fetch|network/i.test(e.message)) setStatus("down", "offline", e.message);
    }
  } finally {
    pendingConfirm?.(false);
    const secs = ((performance.now() - started) / 1000).toFixed(1);
    const foot = block(turn, "foot");
    foot.textContent = `${steps ? `${steps} step${steps > 1 ? "s" : ""} · ` : ""}${secs}s`;
    turn.classList.remove("working");
    // A stopped task can leave an assistant tool call with no answer; drop it.
    while (history.length && history.at(-1).role === "assistant" && history.at(-1).tool_calls) history.pop();
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
  tools = newTools();
  log.textContent = "";
  const empty = document.createElement("div");
  empty.id = "empty";
  empty.className = "empty";
  empty.innerHTML = '<p class="prompt">&gt; ready_</p><p>Cleared. New session.</p>';
  log.append(empty);
  input.focus();
});

$("settings").addEventListener("click", () => {
  if (globalThis.browser?.runtime?.openOptionsPage) browser.runtime.openOptionsPage();
  else window.open("../options/options.html", "_blank");
});

input.focus();
