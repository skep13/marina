// Injected into a tab by the sidebar (scripting.executeScript). Turns the page
// into a text outline with short refs (e12) and carries out actions by ref.
// Safe to inject more than once: it sets itself up a single time per page.
(() => {
  if (globalThis.__browserAgent) return;

  const MAX_OUTLINE = 14000;   // characters of outline sent to the model
  const MAX_TEXT = 16000;      // characters of plain text for "text" mode
  const refs = new Map();      // "e12" -> element
  const ids = new WeakMap();   // element -> "e12"
  let next = 1;

  const refOf = (el) => {
    let id = ids.get(el);
    if (!id) { id = `e${next++}`; ids.set(el, id); }
    refs.set(id, el);
    return id;
  };

  const clean = (s, n = 120) => {
    s = (s || "").replace(/\s+/g, " ").trim();
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  };

  function visible(el) {
    if (!el.isConnected) return false;
    const st = getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden" || st.visibility === "collapse") return false;
    if (el.type === "hidden") return false;
    const r = el.getBoundingClientRect();
    // Custom checkboxes often hide the real input; keep those if their label shows.
    if (r.width === 0 && r.height === 0) {
      if ((el.type === "checkbox" || el.type === "radio") && el.labels?.[0]) return visible(el.labels[0]);
      return false;
    }
    return true;
  }

  function labelOf(el) {
    const by = el.getAttribute("aria-labelledby");
    if (by) {
      const t = by.split(/\s+/).map((i) => document.getElementById(i)?.textContent || "").join(" ");
      if (clean(t)) return clean(t);
    }
    if (el.getAttribute("aria-label")) return clean(el.getAttribute("aria-label"));
    if (el.labels?.length) return clean([...el.labels].map((l) => l.textContent).join(" "));
    if (el.placeholder) return clean(el.placeholder);
    if (el.title) return clean(el.title);
    if (["BUTTON", "A", "SUMMARY"].includes(el.tagName) || el.getAttribute("role")) {
      const t = clean(el.innerText || el.textContent);
      if (t) return t;
      const img = el.querySelector("img[alt]");
      if (img) return clean(img.alt);
    }
    if (el.type === "submit" || el.type === "button") return clean(el.value);
    return clean(el.name || el.id || "");
  }

  // The question a radio/checkbox group answers: its fieldset legend or group label.
  function groupOf(el) {
    const fs = el.closest("fieldset");
    if (fs?.querySelector("legend")) return clean(fs.querySelector("legend").textContent, 160);
    const g = el.closest('[role="radiogroup"],[role="group"]');
    if (g) return labelOf(g) || "";
    return "";
  }

  const SENSITIVE = /pass(word|code)?|pwd|card.?number|cc-?(num|csc|exp)|cvv|cvc|security.?code|iban|sort.?code|account.?number|routing|ssn|social.?security|national.?insurance|passport|pin\b/i;
  function sensitive(el) {
    if (el.type === "password") return true;
    const ac = (el.getAttribute("autocomplete") || "").toLowerCase();
    if (ac.startsWith("cc-") || ac.includes("password") || ac === "one-time-code") return true;
    return SENSITIVE.test(`${el.name} ${el.id} ${labelOf(el)}`);
  }

  const RISKY = /\b(submit|send|post|publish|pay|buy|purchase|order|checkout|check out|place|book|reserve|donate|subscribe|delete|remove|erase|cancel (my )?(account|subscription)|confirm|sign up|register|apply|transfer|finish|complete)\b/i;

  // Would clicking this send something off the page?
  function riskOf(el) {
    const label = labelOf(el);
    const form = el.form || el.closest("form");
    const isSubmit =
      (el.tagName === "BUTTON" && (el.type === "submit" || !el.getAttribute("type")) && form) ||
      (el.tagName === "INPUT" && (el.type === "submit" || el.type === "image"));
    if (isSubmit) return { risky: true, why: "submits a form" };
    if (RISKY.test(label)) return { risky: true, why: `the button says "${label}"` };
    return { risky: false };
  }

  function valueOf(el) {
    if (sensitive(el)) return el.value ? "(hidden)" : "";
    if (el.tagName === "SELECT") return clean([...el.selectedOptions].map((o) => o.text).join(", "));
    if (el.type === "checkbox" || el.type === "radio") return el.checked ? "checked" : "unchecked";
    return clean(el.value, 200);
  }

  function describe(el) {
    const tag = el.tagName;
    const role = el.getAttribute("role");
    const id = refOf(el);
    const label = labelOf(el);
    const flags = [];
    if (el.required || el.getAttribute("aria-required") === "true") flags.push("required");
    if (el.disabled || el.getAttribute("aria-disabled") === "true") flags.push("disabled");
    if (el.getAttribute("aria-invalid") === "true" || (el.validationMessage && el.matches?.(":user-invalid")))
      flags.push(`invalid: ${clean(el.validationMessage || "check this field", 80)}`);
    const f = flags.length ? ` (${flags.join(", ")})` : "";

    if (tag === "A") return `[${id}] link "${label}"${el.href ? ` → ${clean(el.href, 90)}` : ""}`;
    if (tag === "SELECT") {
      const opts = [...el.options].slice(0, 40).map((o) => (o.selected ? `*${clean(o.text, 40)}` : clean(o.text, 40)));
      return `[${id}] select "${label}" = "${valueOf(el)}"${f} options: ${opts.join(" | ")}${el.options.length > 40 ? " | …" : ""}`;
    }
    if (tag === "TEXTAREA") return `[${id}] textarea "${label}" = "${valueOf(el)}"${f}`;
    if (tag === "INPUT") {
      const t = el.type || "text";
      if (t === "checkbox" || t === "radio") {
        const g = groupOf(el);
        return `[${id}] ${t} "${label}"${g ? ` in "${g}"` : ""} ${valueOf(el)}${f}`;
      }
      if (["submit", "button", "reset", "image"].includes(t)) return `[${id}] button "${label}"${f}`;
      if (sensitive(el)) return `[${id}] ${t} "${label}" (sensitive: the agent never fills this)${f}`;
      return `[${id}] ${t === "text" ? "textbox" : t} "${label}" = "${valueOf(el)}"${f}`;
    }
    if (role === "checkbox" || role === "radio" || role === "switch")
      return `[${id}] ${role} "${label}" ${el.getAttribute("aria-checked") === "true" ? "checked" : "unchecked"}${f}`;
    if (role === "combobox" || role === "listbox") return `[${id}] ${role} "${label}"${f}`;
    if (role === "tab") return `[${id}] tab "${label}"${el.getAttribute("aria-selected") === "true" ? " selected" : ""}`;
    if (role === "option" || role === "menuitem") return `[${id}] ${role} "${label}"`;
    if (el.isContentEditable) return `[${id}] editable "${label}" = "${clean(el.innerText, 200)}"`;
    return `[${id}] button "${label}"${f}`;
  }

  const INTERACTIVE =
    'a[href],button,input,select,textarea,summary,[role=button],[role=link],[role=checkbox],[role=radio],' +
    '[role=switch],[role=tab],[role=option],[role=menuitem],[role=combobox],[role=listbox],[contenteditable=""],[contenteditable=true]';

  function outline() {
    const lines = [];
    let size = 0, cut = false;
    const push = (s) => {
      if (cut) return;
      if (size + s.length > MAX_OUTLINE) { cut = true; lines.push("… (outline cut short; scroll or ask for text mode)"); return; }
      lines.push(s); size += s.length + 1;
    };
    const seenText = new Set();

    const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_ELEMENT, {
      acceptNode(el) {
        if (["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "svg"].includes(el.tagName)) return NodeFilter.FILTER_REJECT;
        if (el.getAttribute("aria-hidden") === "true") return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    for (let el = walker.currentNode; el; el = walker.nextNode()) {
      if (cut) break;
      if (/^H[1-6]$/.test(el.tagName) && visible(el)) {
        const t = clean(el.innerText, 160);
        if (t) push(`${"#".repeat(+el.tagName[1])} ${t}`);
        continue;
      }
      if (el.matches(INTERACTIVE)) {
        if (!visible(el)) continue;
        push(describe(el));
        continue;
      }
      if (el.tagName === "LEGEND" || el.tagName === "LABEL") continue;   // shown with their fields
      if (["P", "LI", "TD", "TH", "DT", "DD", "BLOCKQUOTE", "FIGCAPTION", "PRE"].includes(el.tagName) ||
          (el.tagName === "DIV" && !el.querySelector("div,p,ul,ol,table,section,article,form,h1,h2,h3,h4,h5,h6"))) {
        if (el.closest("a,button,label,[role=button]") || el.querySelector(INTERACTIVE)) continue;
        if (!visible(el)) continue;
        const t = clean(el.innerText, 300);
        if (t && t.length > 1 && !seenText.has(t)) { seenText.add(t); push(t); }
      }
    }
    const frames = document.querySelectorAll("iframe").length;
    if (frames) push(`(${frames} embedded frame${frames > 1 ? "s" : ""} not read)`);
    return lines.join("\n");
  }

  function mainText() {
    const root = document.querySelector("article, main, [role=main]") || document.body;
    const t = (root.innerText || "").replace(/\n{3,}/g, "\n\n").trim();
    return t.length > MAX_TEXT ? t.slice(0, MAX_TEXT) + "\n… (cut short)" : t;
  }

  function el(ref) {
    const e = refs.get(ref);
    if (!e || !e.isConnected) throw new Error(`${ref} is no longer on the page; read it again`);
    return e;
  }

  // Set a value so React/Vue/Angular notice it.
  function setValue(e, value) {
    const proto = e.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype
      : e.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    e.focus();
    if (setter) setter.call(e, value); else e.value = value;
    e.dispatchEvent(new Event("input", { bubbles: true }));
    e.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // Everything filled in the form this element belongs to, for the confirm card.
  function formSummary(e) {
    const form = e.form || e.closest("form");
    if (!form) return [];
    return [...form.querySelectorAll("input,select,textarea")]
      .filter((f) => visible(f) && !["submit", "button", "reset", "image", "hidden"].includes(f.type))
      .filter((f) => (f.type === "checkbox" || f.type === "radio") ? f.checked : valueOf(f))
      .slice(0, 40)
      .map((f) => {
        const g = (f.type === "radio" || f.type === "checkbox") ? groupOf(f) : "";
        return { field: g || labelOf(f) || f.name || "field", value: (f.type === "radio" || f.type === "checkbox") ? labelOf(f) : valueOf(f) };
      });
  }

  const api = {
    info: () => ({ title: document.title, url: location.href }),

    read(mode = "outline") {
      return { title: document.title, url: location.href, content: mode === "text" ? mainText() : outline() };
    },

    // What clicking `ref` would do, before doing it.
    inspect(ref) {
      const e = el(ref);
      return { label: labelOf(e), ...riskOf(e), fields: formSummary(e), url: location.href };
    },

    click(ref) {
      const e = el(ref);
      e.scrollIntoView({ block: "center" });
      e.focus?.();
      e.click();
      return `clicked ${ref} "${labelOf(e)}"`;
    },

    type(ref, text, submit = false) {
      const e = el(ref);
      if (sensitive(e)) throw new Error("that's a password or payment field; the agent never fills those. Ask Jacob to type it.");
      e.scrollIntoView({ block: "center" });
      if (e.isContentEditable) {
        e.focus();
        e.textContent = text;
        e.dispatchEvent(new InputEvent("input", { bubbles: true }));
      } else {
        setValue(e, text);
      }
      if (submit) e.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      return `typed into ${ref} "${labelOf(e)}"`;
    },

    select(ref, option) {
      const e = el(ref);
      if (e.tagName !== "SELECT") throw new Error(`${ref} isn't a dropdown; click it, then click the option`);
      const want = String(option).trim().toLowerCase();
      const o = [...e.options].find((o) => o.text.trim().toLowerCase() === want || o.value.toLowerCase() === want)
        || [...e.options].find((o) => o.text.trim().toLowerCase().includes(want));
      if (!o) throw new Error(`no option like "${option}" in ${ref}`);
      setValue(e, o.value);
      return `selected "${clean(o.text)}" in ${ref}`;
    },

    check(ref, on = true) {
      const e = el(ref);
      const isOn = e.type === "checkbox" || e.type === "radio" ? e.checked : e.getAttribute("aria-checked") === "true";
      if (isOn !== on) { e.scrollIntoView({ block: "center" }); e.click(); }
      return `${ref} "${labelOf(e)}" is ${on ? "checked" : "unchecked"}`;
    },

    scroll(direction = "down") {
      const h = window.innerHeight * 0.85;
      if (direction === "top") window.scrollTo(0, 0);
      else if (direction === "bottom") window.scrollTo(0, document.body.scrollHeight);
      else window.scrollBy(0, direction === "up" ? -h : h);
      return `scrolled ${direction}`;
    },
  };

  globalThis.__browserAgent = api;
})();
