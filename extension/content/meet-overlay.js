// SmartGen Meet overlay — injected on meet.google.com.
// Creates a draggable floating panel using Shadow DOM (isolated from Meet's CSS).

(function () {
  if (document.getElementById('smartgen-host')) return; // already injected

  // ── CSS (inlined — same source of truth as overlay.css) ──────────────────

  const CSS = `
:host {
  all: initial;
  position: fixed;
  top: 80px;
  right: 20px;
  z-index: 2147483647;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}
#sg-panel {
  width: 340px;
  background: rgba(15,15,20,0.93);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.6);
  color: #e8e8e8;
  font-size: 13px;
  overflow: hidden;
  backdrop-filter: blur(12px);
  user-select: none;
}
#sg-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(255,255,255,0.06);
  cursor: grab;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
#sg-header:active { cursor: grabbing; }
#sg-title { flex: 1; font-weight: 600; font-size: 13px; letter-spacing: 0.3px; }
.sg-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.sg-dot.connecting { background: #f59e0b; animation: pulse 1s infinite; }
.sg-dot.ready      { background: #10b981; }
.sg-dot.recording  { background: #ef4444; animation: pulse 0.8s infinite; }
.sg-dot.error      { background: #6b7280; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
#sg-close {
  background: none; border: none; color: rgba(255,255,255,0.4);
  font-size: 16px; cursor: pointer; padding: 0 2px; line-height: 1;
}
#sg-close:hover { color: #fff; }
.sg-label {
  font-size: 10px; font-weight: 600; letter-spacing: 0.8px;
  text-transform: uppercase; color: rgba(255,255,255,0.3); padding: 6px 14px 2px;
}
.sg-transcript {
  min-height: 36px; max-height: 80px; overflow-y: auto;
  padding: 8px 14px; font-size: 13px; line-height: 1.5;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.sg-transcript.vi { color: #93c5fd; }
.sg-transcript.en { color: #d1fae5; }
#sg-controls {
  display: flex; align-items: center; gap: 6px;
  padding: 10px 14px; flex-wrap: wrap;
}
#sg-controls select {
  background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);
  border-radius: 6px; color: #e8e8e8; font-size: 12px; padding: 4px 6px;
  cursor: pointer; flex: 1; min-width: 80px;
}
#sg-controls select option { background: #1a1a2e; }
#sg-toggle {
  background: #3b82f6; border: none; border-radius: 6px; color: #fff;
  font-size: 12px; font-weight: 600; padding: 5px 14px; cursor: pointer;
  white-space: nowrap; transition: background 0.15s;
}
#sg-toggle:hover  { background: #2563eb; }
#sg-toggle.active { background: #ef4444; }
#sg-toggle.active:hover { background: #dc2626; }
#sg-status-text { width: 100%; font-size: 11px; color: rgba(255,255,255,0.3); padding: 0 2px; }
`;

  // ── DOM setup ─────────────────────────────────────────────────────────────

  const host = document.createElement('div');
  host.id = 'smartgen-host';
  document.body.appendChild(host);

  const shadow = host.attachShadow({ mode: 'open' });

  shadow.innerHTML = `<style>${CSS}</style>
<div id="sg-panel">
  <div id="sg-header">
    <span class="sg-dot connecting" id="sg-dot"></span>
    <span id="sg-title">SmartGen</span>
    <button id="sg-close">×</button>
  </div>
  <div class="sg-label">VI</div>
  <div class="sg-transcript vi" id="sg-vi"></div>
  <div class="sg-label">EN</div>
  <div class="sg-transcript en" id="sg-en"></div>
  <div id="sg-controls">
    <select id="sg-source">
      <option value="mic">&#127908; Mic</option>
      <option value="tab">&#128421; Tab Audio</option>
    </select>
    <select id="sg-voice"><option value="">Loading&#8230;</option></select>
    <button id="sg-toggle">&#9654; Start</button>
    <span id="sg-status-text">Connecting&#8230;</span>
  </div>
</div>`;

  const $ = id => shadow.getElementById(id);
  const dot       = $('sg-dot');
  const viEl      = $('sg-vi');
  const enEl      = $('sg-en');
  const toggle    = $('sg-toggle');
  const sourceEl  = $('sg-source');
  const voiceEl   = $('sg-voice');
  const statusEl  = $('sg-status-text');
  const closeBtn  = $('sg-close');
  const header    = $('sg-header');
  const panel     = $('sg-panel');

  // ── State ─────────────────────────────────────────────────────────────────

  let enAccum = '';
  let enCommitted = '';
  let wsReady = false;

  // ── Helpers ───────────────────────────────────────────────────────────────

  function setDot(state) {
    dot.className = 'sg-dot ' + state;
  }

  function setStatus(text) {
    statusEl.textContent = text;
  }

  // ── Dragging ──────────────────────────────────────────────────────────────

  let dragging = false, dragX = 0, dragY = 0, startRight = 0, startTop = 0;

  header.addEventListener('mousedown', ev => {
    if (ev.target === closeBtn) return;
    dragging = true;
    dragX = ev.clientX;
    dragY = ev.clientY;
    const rect = host.getBoundingClientRect();
    startRight = window.innerWidth - rect.right;
    startTop = rect.top;
    ev.preventDefault();
  });

  document.addEventListener('mousemove', ev => {
    if (!dragging) return;
    const dx = dragX - ev.clientX;
    const dy = ev.clientY - dragY;
    host.style.right = Math.max(0, startRight + dx) + 'px';
    host.style.top   = Math.max(0, startTop + dy) + 'px';
  });

  document.addEventListener('mouseup', () => { dragging = false; });

  // ── Voice list ────────────────────────────────────────────────────────────

  chrome.storage.sync.get({ serverUrl: 'ws://localhost:8000/ws', voice: 'af_heart' }, async ({ serverUrl, voice }) => {
    const httpBase = serverUrl.replace(/^ws(s?):\/\//, 'http$1://').replace(/\/ws$/, '');
    try {
      const res = await fetch(`${httpBase}/api/tts/voices`);
      const data = await res.json();
      voiceEl.innerHTML = '';
      for (const v of data.voices || []) {
        const opt = document.createElement('option');
        opt.value = v.id;
        opt.textContent = v.name;
        opt.selected = v.id === voice;
        voiceEl.appendChild(opt);
      }
    } catch (_) {
      voiceEl.innerHTML = '<option value="af_heart">af_heart</option>';
    }
  });

  voiceEl.addEventListener('change', () => {
    chrome.storage.sync.set({ voice: voiceEl.value });
  });

  // ── Start / Stop ──────────────────────────────────────────────────────────

  toggle.addEventListener('click', async () => {
    const bridge = window._sgBridge;
    if (!bridge) return;

    if (!bridge.isRecording()) {
      toggle.disabled = true;
      setStatus('Starting…');
      try {
        await bridge.start(sourceEl.value, { srcLang: 'vi', tgtLang: 'en' });
        toggle.textContent = '■ Stop';
        toggle.classList.add('active');
        setDot('recording');
        setStatus('Recording…');
      } catch (err) {
        setStatus('Error: ' + (err.message || 'could not start'));
        setDot('error');
      } finally {
        toggle.disabled = false;
      }
    } else {
      bridge.stop();
      toggle.textContent = '▶ Start';
      toggle.classList.remove('active');
      setDot(wsReady ? 'ready' : 'connecting');
      setStatus(wsReady ? 'Ready' : 'Connecting…');
      viEl.textContent = '';
      enEl.textContent = '';
      enAccum = '';
      enCommitted = '';
    }
  });

  closeBtn.addEventListener('click', () => {
    if (window._sgBridge?.isRecording()) window._sgBridge.stop();
    host.remove();
  });

  // ── Bridge event listeners ────────────────────────────────────────────────

  document.addEventListener('smartgen:status', ev => {
    const { status } = ev.detail;
    wsReady = status === 'ready' || status === 'recording';

    if (status === 'recording') {
      setDot('recording');
      setStatus('Recording…');
    } else if (status === 'ready') {
      setDot('ready');
      if (!window._sgBridge?.isRecording()) setStatus('Ready');
    } else {
      setDot('connecting');
      setStatus('Connecting…');
    }
  });

  document.addEventListener('smartgen:msg', ev => {
    const msg = ev.detail;

    if (msg.type === 'ws_status') {
      wsReady = msg.connected;
      if (!window._sgBridge?.isRecording()) {
        setDot(msg.connected ? 'ready' : 'connecting');
        setStatus(msg.connected ? 'Ready' : 'Connecting…');
      }
      return;
    }

    if (msg.type === 'sync') {
      viEl.textContent = msg.committed + (msg.interim ? ' ' + msg.interim : '');
      viEl.scrollTop = viEl.scrollHeight;
    }

    if (msg.type === 'commit') {
      viEl.textContent = msg.text || viEl.textContent;
    }

    if (msg.type === 'trans_stream_c') {
      enAccum += msg.token;
      enEl.textContent = enCommitted + enAccum;
      enEl.scrollTop = enEl.scrollHeight;
    }

    if (msg.type === 'clear_trans_i') {
      enAccum = '';
      enEl.textContent = enCommitted;
    }
  });


})();
