// Test-only stand-in for Firefox's extension APIs. "Tabs" are iframes in the
// parent harness page; scripts run inside them as the content script would.
(() => {
  const P = parent.document;
  const store = {
    baseURL: "http://127.0.0.1:4341/v1", key: "via-test-proxy", model: "browser", think: false,
    profile: "Name: Test Person\nEmail: test.person@example.com\nTown: Testville\nCountry: United Kingdom",
    blocked: "",
  };
  const frames = () => [...P.querySelectorAll("iframe.tab")];
  const asTab = (f) => ({ id: +f.dataset.id, title: f.contentDocument?.title || "", url: f.contentWindow.location.href,
                         status: f.contentDocument?.readyState === "complete" ? "complete" : "loading", active: f.classList.contains("active") });
  const frame = (id) => frames().find((f) => +f.dataset.id === +id) || (() => { throw new Error("no tab " + id); })();
  const listen = { addListener() {} };
  window.browser = {
    storage: { local: { get: async (k) => Object.fromEntries(k.map((x) => [x, store[x]])), set: async (p) => Object.assign(store, p) }, onChanged: listen },
    permissions: { contains: async () => true, request: async () => true, onAdded: listen, onRemoved: listen },
    runtime: { openOptionsPage() {} },
    tabs: {
      query: async (q) => frames().map(asTab).filter((t) => !q.active || t.active),
      get: async (id) => asTab(frame(id)),
      update: async (id, p) => { const f = frame(id); if (p.url) f.src = p.url;
        if (p.active) { frames().forEach((x) => x.classList.remove("active")); f.classList.add("active"); } return asTab(f); },
      create: async ({ url, active }) => { const f = P.createElement("iframe"); f.className = "tab"; f.dataset.id = String(Date.now() % 100000);
        f.src = url; P.getElementById("tabs").append(f); if (active !== false) { frames().forEach((x) => x.classList.remove("active")); f.classList.add("active"); }
        await new Promise((r) => f.addEventListener("load", r, { once: true })); return asTab(f); },
      remove: async (id) => frame(id).remove(),
    },
    scripting: {
      executeScript: async ({ target, files, func, args }) => {
        const w = frame(target.tabId).contentWindow;
        if (files) { for (const f of files) w.eval(await (await fetch(f)).text()); return [{ result: undefined }]; }
        return [{ result: w.eval("(" + func.toString() + ")").apply(null, args || []) }];
      },
    },
  };
})();
