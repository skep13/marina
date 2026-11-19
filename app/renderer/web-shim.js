// Only loaded when a browser gets Marina from the bridge (server/process/web.py).
// Stands in for Electron's preload.js so app.js runs unchanged on a phone.
(() => {
  const noop = () => {};

  // ?kiosk: lab3's own monitor (appliance/setup-lab3.sh screen). It shares the
  // iGPU with the models, so draw fewer frames at a lower resolution:
  // ?kiosk&fps=30&scale=0.75 are the defaults.
  const q = new URLSearchParams(location.search);
  if (q.has('kiosk')) {
    const fps = Number(q.get('fps')) || 30, scale = Number(q.get('scale')) || 0.75;
    Object.defineProperty(window, 'devicePixelRatio', { get: () => scale });
    const raf = window.requestAnimationFrame.bind(window);
    let last = 0;
    window.requestAnimationFrame = (fn) => raf(function wait(t) {
      if (t - last < 1000 / fps - 1) return raf(wait);
      last = t; fn(t);
    });
    document.documentElement.classList.add('kiosk');
  }

  window.marina = {
    web: true,
    loadVRM: async () => {
      const res = await fetch('model.vrm');
      if (!res.ok) return { error: 'There is no avatar on the server.' };
      return { name: 'model.vrm', buffer: await res.arrayBuffer() };
    },
    pickVRM: async () => ({ canceled: true }),
    quit: noop,
    minimize: noop,
    clickThrough: noop,
    captureScreen: async () => null,
    cameraAccess: async () => true,
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

  document.documentElement.classList.add('web');

  // iOS mutes Web Audio when the ring switch is on silent unless the page
  // says it is playing media.
  if (navigator.audioSession) navigator.audioSession.type = 'playback';

  document.addEventListener('DOMContentLoaded', () => {
    const foot = document.querySelector('.pick-foot');
    if (foot) foot.textContent = 'History and memory stay on your home server either way.';
  });
})();
