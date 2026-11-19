// Loaded only inside the iPhone app (ios/), before app.js. Stands in for
// Electron's preload.js like web-shim.js does, but the page here only draws
// her: the native app talks to the bridge and feeds replies in through
// window.marinaAvatar (see the EMBEDDED block at the end of app.js).
(() => {
  const noop = () => {};

  window.marina = {
    embedded: true,
    loadVRM: async () => {
      const res = await fetch('model.vrm');
      if (!res.ok) return { error: 'The avatar is missing from the app.' };
      return { name: 'model.vrm', buffer: await res.arrayBuffer() };
    },
    pickVRM: async () => ({ canceled: true }),
    quit: noop,
    minimize: noop,
    clickThrough: noop,
    captureScreen: async () => null,
    cameraAccess: async () => false,
    openersChanged: noop,
    onToggleListen: noop,
    onToggleCall: noop,
    callChanged: noop,
    onPickModel: noop,
    onLookAtScreen: noop,
    onBridgeDown: noop,
    onBridgeUp: noop,
    onSetOpeners: noop,
    onInterrupt: noop,
    onSetPreset: noop,
    onSetStage: noop,
  };

  document.documentElement.classList.add('embedded');

  // The app draws the chat, buttons and status natively; only the canvas
  // stays. The background matches the phone page so she sits in the same
  // light as on the Mac.
  const css = `
    html.embedded, .embedded body {
      background: radial-gradient(ellipse at 50% 35%, #262b38 0%, #14161c 70%);
      -webkit-user-select: none; -webkit-touch-callout: none;
    }
    .embedded #drag-strip, .embedded #chrome, .embedded #picker,
    .embedded #bubble, .embedded #heard, .embedded #ask, .embedded #notice,
    .embedded #bar, .embedded #call, .embedded #status { display: none !important; }
  `;
  const style = document.createElement('style');
  style.textContent = css;
  document.addEventListener('DOMContentLoaded', () => document.head.append(style));

  // Tell the app when she's on screen, and pass errors up so they show
  // natively instead of vanishing.
  const post = (msg) => window.webkit?.messageHandlers?.marina?.postMessage(msg);
  window.addEventListener('error', (e) => post({ type: 'error', message: String(e.message || e) }));
  window.addEventListener('unhandledrejection', (e) => post({ type: 'error', message: String(e.reason?.message || e.reason) }));
  // The page's console goes to the app's log (Console.app / Xcode).
  for (const level of ['log', 'warn', 'error']) {
    const original = console[level].bind(console);
    console[level] = (...args) => {
      original(...args);
      try { post({ type: 'log', level, message: args.map(String).join(' ').slice(0, 500) }); } catch {}
    };
  }
  const ready = setInterval(() => {
    if (window.__marina?.vrm) { clearInterval(ready); post({ type: 'ready' }); }
  }, 250);
})();
