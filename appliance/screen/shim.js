// Stands in for the Electron preload (aiws/orb/preload.js) so the laptop
// orb's renderer runs as a plain web page on lab3's monitor.
//
// Chat goes to Marina's bridge through the box's proxy (/marina/chat/stream,
// same origin, key added by Caddy), so it's her: persona, memory, moods. No
// screen helper or agent here: lab3 has nothing on screen for her to look at.
//
// Kept light because it shares the iGPU and RAM with the models: the sphere
// renders at half resolution and at most 30 frames a second.
(() => {
  const BRIDGE = '/marina';
  const MAX_FPS = 30;

  // Half-resolution sphere: it's a soft glow, upscaling doesn't show.
  Object.defineProperty(window, 'devicePixelRatio', { get: () => 0.5 });

  // Cap animation frames.
  const raf = window.requestAnimationFrame.bind(window);
  let lastFrame = 0;
  window.requestAnimationFrame = (fn) => raf(function tick(t) {
    if (t - lastFrame < 1000 / MAX_FPS - 1) return raf(tick);
    lastFrame = t; fn(t);
  });

  const listeners = {};
  const emit = (ch, v) => (listeners[ch] || []).forEach((fn) => fn(v));
  const streams = new Map();

  async function* events(res) {
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
        if (line) { try { yield JSON.parse(line); } catch {} }
      }
    }
  }

  async function chat(id, messages) {
    const last = [...messages].reverse().find((m) => m.role === 'user');
    const text = typeof last?.content === 'string' ? last.content : last?.content?.[0]?.text || '';
    const ctl = new AbortController();
    streams.set(id, { ctl, chunks: 0 });
    try {
      const res = await fetch(BRIDGE + '/chat/stream', {
        method: 'POST', signal: ctl.signal, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, speak: false }),
      });
      if (!res.ok) throw new Error(`${res.status} ${(await res.text()).slice(0, 200)}`);
      for await (const ev of events(res)) {
        if (ev.type === 'chunk' && ev.reply) {
          streams.get(id).chunks++;
          emit('chat-delta', { id, piece: (streams.get(id).chunks > 1 ? ' ' : '') + ev.reply });
        } else if (ev.type === 'error') {
          throw new Error(ev.message || 'error');
        }
      }
      emit('chat-done', { id });
    } catch (e) {
      emit('chat-done', { id, error: ctl.signal.aborted ? 'stopped' : String(e.message || e) });
    } finally {
      streams.delete(id);
    }
  }

  const store = {
    get() { try { return JSON.parse(localStorage.getItem('orb-settings') || '{}'); } catch { return {}; } },
    set(s) { try { localStorage.setItem('orb-settings', JSON.stringify(s)); } catch {} },
  };

  window.orb = {
    settings: async () => store.get(),
    saveSettings: async (s) => { store.set(s); return true; },
    toggle: async () => {},                       // always open on the monitor
    context: async () => ({ window: null, selection: '', activity: [] }),
    chat: async (id, messages) => { chat(id, messages); return true; },
    stopChat: async (id) => {
      const s = streams.get(id);
      fetch(BRIDGE + '/interrupt', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chunks: s ? s.chunks : 0 }) }).catch(() => {});
      s?.ctl.abort();
      return true;
    },
    api: async () => { throw new Error('not on lab3'); },
    setupStatus: async () => ({ lab3: true, tailscale: null }),
    setKey: async () => ({ ok: false }),
    tailscaleUp: async () => ({ ok: false }),
    on: (ch, fn) => { (listeners[ch] = listeners[ch] || []).push(fn); },
  };

  // Module scripts run before DOMContentLoaded, so app.js is listening by now.
  document.addEventListener('DOMContentLoaded', () => emit('expanded', true));
})();
