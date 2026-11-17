import { DEFAULTS, Lab3, loadSettings, saveSettings } from "../lib/lab3.js";

const $ = (id) => document.getElementById(id);
const result = $("result");
const FIELDS = ["baseURL", "key", "model"];

const s = await loadSettings();
for (const f of FIELDS) $(f).value = s[f];

function read() {
  const v = Object.fromEntries(FIELDS.map((f) => [f, $(f).value.trim()]));
  v.baseURL = v.baseURL.replace(/\/+$/, "") || DEFAULTS.baseURL;
  v.model = v.model || DEFAULTS.model;
  return v;
}

function show(ok, text) {
  result.className = ok ? "ok" : "bad";
  result.textContent = text;
}

// An endpoint other than the ones in the manifest needs Firefox's permission.
// request() must be the first await after the click, or Firefox treats it as
// not user-initiated; it answers true at once if already granted.
function allowHost(url) {
  const perms = globalThis.browser?.permissions;
  if (!perms) return Promise.resolve(true);
  return perms.request({ origins: [new URL(url).origin + "/*"] });
}

async function permitted(url) {
  try { new URL(url); } catch { show(false, "That isn't a valid address."); return false; }
  let ok;
  try { ok = await allowHost(url); } catch { ok = false; }
  if (!ok) show(false, "Firefox wasn't allowed to reach that address.");
  return ok;
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const v = read();
  if (!(await permitted(v.baseURL))) return;
  await saveSettings(v);
  show(true, "Saved.");
});

$("test").addEventListener("click", async () => {
  const v = read();
  if (!(await permitted(v.baseURL))) return;
  show(true, "Checking…");
  try {
    await new Lab3(v).check();
    show(true, `OK · lab3 serves "${v.model}"`);
  } catch (e) {
    show(false, e.message);
  }
});
