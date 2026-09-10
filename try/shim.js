// Web preview shim. The desktop app talks to a Python bridge on this Mac and
// to Electron through window.marina. Neither exists on a web page, so this
// stands in for both. Replies are pre-recorded lines in her real voice, made
// with the same Kokoro setup and the same reply splitter the bridge uses.
(() => {
  const BRIDGE = 'http://127.0.0.1:8765';
  const MODEL = 'recorded preview';
  const realFetch = window.fetch.bind(window);
  const sleep = (ms, signal) => new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => { clearTimeout(t); reject(new DOMException('aborted', 'AbortError')); });
  });

  let replies = null;
  const loadReplies = () => (replies ??= realFetch('lines/replies.json').then((r) => r.json()));
  const audioCache = {};
  async function base64Of(name) {
    if (!audioCache[name]) {
      audioCache[name] = realFetch('lines/' + name).then((r) => r.arrayBuffer()).then((buf) => {
        const u = new Uint8Array(buf);
        let s = '';
        for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
        return btoa(s);
      });
    }
    return audioCache[name];
  }

  const json = (o) => new Response(JSON.stringify(o), { headers: { 'Content-Type': 'application/json' } });

  // Crude on purpose. It only has a dozen lines to choose from.
  const RULES = [
    ['bye',      /\b(bye|goodbye|good night|gn|cya|see (you|ya)|later)\b/],
    ['doing',    /(what are you (doing|up to)|wyd|busy|working on|editing)/],
    ['who',      /(who are you|what are you|your name|about yourself|introduce)/],
    ['how',      /(how are you|how's it going|how are things|you ok|you good)/],
    ['help',     /(help|can you|could you|timer|remind|assist)/],
    ['joke',     /(joke|funny|make me laugh)/],
    ['nice',     /(cute|pretty|love you|like you|beautiful|nice hair|gorgeous)/],
    // Last, so "hey what are you up to" gets the question and not a hello.
    ['greeting', /^\s*(hi|hey|hello|yo|hiya|sup|morning|evening|oi)\b/],
  ];
  let fallbackTurn = 0;
  function pick(text) {
    const t = (text || '').toLowerCase();
    for (const [key, re] of RULES) if (re.test(t)) return key;
    return (fallbackTurn++ % 2) ? 'fallback2' : 'fallback1';
  }

  function streamOf(key, { transcript, firstDelay = 500, signal } = {}) {
    const enc = new TextEncoder();
    return new Response(new ReadableStream({
      async start(ctrl) {
        const send = (o) => ctrl.enqueue(enc.encode(JSON.stringify(o) + '\n'));
        try {
          const chunks = (await loadReplies())[key] || [];
          send({ type: 'start', transcript: transcript ?? null, unprompted: transcript === undefined });
          await sleep(firstDelay, signal);
          for (let i = 0; i < chunks.length; i++) {
            const c = chunks[i];
            send({ type: 'chunk', index: i, reply: c.reply, speech: c.speech, cues: c.cues,
                   audio: c.audio ? await base64Of(c.audio) : null, visemes: [] });
            await sleep(220, signal);
          }
          send({ type: 'done', chunks: chunks.length, reply: chunks.map((c) => c.reply).join(' ') });
        } catch { /* aborted */ }
        ctrl.close();
      },
    }), { headers: { 'Content-Type': 'application/x-ndjson' } });
  }

  // Speaking first. She waits until the visitor has touched the page (browsers
  // will not play audio before that) and then has been quiet for a while.
  let touched = false;
  let lastActivity = Date.now();
  let openers = 0;
  const touch = () => { touched = true; lastActivity = Date.now(); };
  window.addEventListener('pointerdown', touch, true);
  window.addEventListener('keydown', touch, true);
  window.__preview = { touch };

  async function idleListen(signal) {
    for (;;) {
      await sleep(1000, signal);
      if (openers < 2 && touched && Date.now() - lastActivity > (openers ? 90000 : 35000)) {
        openers++;
        lastActivity = Date.now();
        return streamOf('opener', { firstDelay: 0, signal });
      }
    }
  }

  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    if (!url.startsWith(BRIDGE)) return realFetch(input, init);
    const path = url.slice(BRIDGE.length).split('?')[0];
    const body = init.body ? (() => { try { return JSON.parse(init.body); } catch { return {}; } })() : {};

    switch (path) {
      case '/health':
        return json({ ok: true, model: MODEL, llm_endpoint: 'this page', llm_using: 'web page',
                      llm_mode: 'auto', tts: 'kokoro, recorded', whisper_loaded: false,
                      recording: false, vision: null, barge_in: false,
                      idle: { enabled: true, muted: false } });
      case '/chat/stream':
        lastActivity = Date.now();
        return streamOf(pick(body.text), { transcript: body.text, signal: init.signal });
      case '/listen/stop/stream':
        lastActivity = Date.now();
        return streamOf('mic', { transcript: '', signal: init.signal });
      case '/idle/listen':
        return idleListen(init.signal);
      case '/models':
        return json({ server: [MODEL], local: [], selected: { server: MODEL, local: null },
                      mode: 'auto', current: 'server' });
      case '/backend':
        return json({ ok: true, mode: body.mode || 'auto', current: 'server', choices: ['auto', 'server', 'local'] });
      default:
        return json({ ok: true });
    }
  };

  // What Electron's preload gives the real app.
  const noop = () => {};
  function pickFile() {
    return new Promise((resolve) => {
      const f = document.createElement('input');
      f.type = 'file';
      f.accept = '.vrm';
      f.onchange = async () => {
        const file = f.files && f.files[0];
        if (!file) return resolve({ canceled: true });
        resolve({ name: file.name, buffer: await file.arrayBuffer() });
      };
      f.click();
    });
  }
  window.marina = {
    loadVRM: async () => {
      try {
        const res = await realFetch('../marina.vrm');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return { name: 'marina.vrm', buffer: await res.arrayBuffer() };
      } catch (e) {
        return { error: `Could not download her model (${e.message}).` };
      }
    },
    pickVRM: pickFile,
    quit: noop,
    minimize: noop,
    clickThrough: noop,
    captureScreen: async () => ({ error: 'Looking at the screen only works in the desktop app.' }),
    onToggleListen: noop, onPickModel: noop, onLookAtScreen: noop,
    onBridgeDown: noop, onBridgeUp: noop, onSetOpeners: noop, onInterrupt: noop,
    openersChanged: noop,
  };
})();
