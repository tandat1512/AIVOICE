// SmartGen YouTube dub — content script injected directly on youtube.com/watch.
// Reads the page's own caption transcript via the SmartGen backend, translates +
// synthesizes voice ahead of the native <video> playhead, and plays the dub in
// sync — same transcript -> translate -> TTS -> sync-play pipeline as
// SG.createYoutubeDub (web/smartgen/backend.js), but driven by the real <video>
// element instead of an embedded iframe player (no iframe sandbox/CSP issues).
//
// Text display (dispIdx) and audio playback (playIdx) advance independently:
// translation is far faster than TTS synthesis, so the caption must not wait on
// the (much slower) voice clip — see the matching fix in backend.js.

(function () {
  if (document.getElementById('smartgen-yt-host')) return; // already injected

  const YT2NLLB = { en: 'eng_Latn', vi: 'vie_Latn', ja: 'jpn_Jpan', ko: 'kor_Hang', zh: 'zho_Hans', fr: 'fra_Latn', es: 'spa_Latn', de: 'deu_Latn', ru: 'rus_Cyrl', th: 'tha_Thai', id: 'ind_Latn', pt: 'por_Latn' };
  const toNllb = (c) => YT2NLLB[c] || YT2NLLB[(c || '').split('-')[0]] || 'eng_Latn';

  // ── CSS ──────────────────────────────────────────────────────────────────

  const CSS = `
:host { all: initial; position: fixed; top: 80px; right: 20px; z-index: 2147483647; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
#sg-panel { width: 300px; background: rgba(15,15,20,0.93); border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.6); color: #e8e8e8; font-size: 13px; overflow: hidden; backdrop-filter: blur(12px); user-select: none; }
#sg-header { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: rgba(255,255,255,0.06); cursor: grab; border-bottom: 1px solid rgba(255,255,255,0.08); }
#sg-header:active { cursor: grabbing; }
#sg-title { flex: 1; font-weight: 600; font-size: 13px; letter-spacing: 0.3px; }
.sg-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: #6b7280; }
.sg-dot.connecting { background: #f59e0b; animation: pulse 1s infinite; }
.sg-dot.ready { background: #10b981; }
.sg-dot.error { background: #ef4444; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
#sg-close { background: none; border: none; color: rgba(255,255,255,0.4); font-size: 16px; cursor: pointer; padding: 0 2px; line-height: 1; }
#sg-close:hover { color: #fff; }
#sg-controls { display: flex; align-items: center; gap: 6px; padding: 10px 14px; flex-wrap: wrap; }
#sg-controls select { background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; color: #e8e8e8; font-size: 12px; padding: 4px 6px; cursor: pointer; }
#sg-controls select option { background: #1a1a2e; }
#sg-toggle { background: #3b82f6; border: none; border-radius: 6px; color: #fff; font-size: 12px; font-weight: 600; padding: 5px 14px; cursor: pointer; white-space: nowrap; transition: background 0.15s; }
#sg-toggle:hover { background: #2563eb; }
#sg-toggle.active { background: #ef4444; }
#sg-toggle.active:hover { background: #dc2626; }
#sg-status { width: 100%; font-size: 11px; color: rgba(255,255,255,0.4); padding: 0 2px; }
#sg-cap { padding: 8px 14px 12px; font-size: 13px; line-height: 1.5; min-height: 20px; color: #d1fae5; border-top: 1px solid rgba(255,255,255,0.06); }
`;

  // ── DOM ──────────────────────────────────────────────────────────────────

  const host = document.createElement('div');
  host.id = 'smartgen-yt-host';
  document.documentElement.appendChild(host);
  const shadow = host.attachShadow({ mode: 'open' });
  shadow.innerHTML = `<style>${CSS}</style>
<div id="sg-panel">
  <div id="sg-header">
    <span class="sg-dot" id="sg-dot"></span>
    <span id="sg-title">SmartGen Dub</span>
    <button id="sg-close">&times;</button>
  </div>
  <div id="sg-controls">
    <select id="sg-tgt">
      <option value="en">EN</option>
      <option value="vi">VI</option>
    </select>
    <button id="sg-toggle">&#9654; Lồng tiếng</button>
    <span id="sg-status">Sẵn sàng</span>
  </div>
  <div id="sg-cap"></div>
</div>`;

  const $ = (id) => shadow.getElementById(id);
  const dot = $('sg-dot'), toggle = $('sg-toggle'), tgtSel = $('sg-tgt'), statusEl = $('sg-status'), capEl = $('sg-cap'), closeBtn = $('sg-close'), header = $('sg-header');

  chrome.storage.sync.get({ serverUrl: 'ws://localhost:8000/ws', tgtLang: 'en' }, (s) => { tgtSel.value = s.tgtLang || 'en'; });
  tgtSel.addEventListener('change', () => chrome.storage.sync.set({ tgtLang: tgtSel.value }));

  // ── Dragging ─────────────────────────────────────────────────────────────

  let dragging = false, dragX = 0, dragY = 0, startRight = 0, startTop = 0;
  header.addEventListener('mousedown', (ev) => {
    if (ev.target === closeBtn) return;
    dragging = true; dragX = ev.clientX; dragY = ev.clientY;
    const rect = host.getBoundingClientRect();
    startRight = window.innerWidth - rect.right; startTop = rect.top;
    ev.preventDefault();
  });
  document.addEventListener('mousemove', (ev) => {
    if (!dragging) return;
    host.style.right = Math.max(0, startRight + (dragX - ev.clientX)) + 'px';
    host.style.top = Math.max(0, startTop + (ev.clientY - dragY)) + 'px';
  });
  document.addEventListener('mouseup', () => { dragging = false; });
  closeBtn.addEventListener('click', () => { stopSession(); host.remove(); });

  // ── Helpers ──────────────────────────────────────────────────────────────

  function getVideoId() {
    const m = location.href.match(/(?:v=|youtu\.be\/|\/shorts\/|\/embed\/|\/live\/)([A-Za-z0-9_-]{11})/);
    return m ? m[1] : null;
  }
  function getVideoEl() {
    return document.querySelector('#movie_player video') || document.querySelector('video');
  }
  function httpBase(serverUrl) {
    return serverUrl.replace(/^ws(s?):\/\//, 'http$1://').replace(/\/ws$/, '');
  }

  // Content-script fetch() does NOT get the host_permissions CORS exemption (only
  // XMLHttpRequest does, and YouTube's page sends no CORS headers back) — relay
  // every backend call through the background service worker instead, whose
  // fetch() is a full extension-context request and is never subject to CORS.
  function sgFetch(url, opts = {}) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(
        { type: 'sg_fetch', url, method: opts.method || 'GET', headers: opts.headers, body: opts.body, binary: !!opts.binary, timeoutMs: opts.timeoutMs },
        (resp) => {
          if (chrome.runtime.lastError) { reject(new Error(chrome.runtime.lastError.message)); return; }
          if (!resp) { reject(new Error('Không nhận được phản hồi từ background.')); return; }
          if (resp.error) { reject(new Error(resp.error)); return; }
          resolve(resp);
        }
      );
    });
  }

  // ── Session (transcript -> translate -> TTS -> sync play) ──────────────────

  let session = null;

  function stopSession() {
    if (!session) return;
    session.stop();
    session = null;
    toggle.textContent = '▶ Lồng tiếng';
    toggle.classList.remove('active');
    dot.className = 'sg-dot';
    statusEl.textContent = 'Sẵn sàng';
    capEl.textContent = '';
  }

  async function startSession() {
    const id = getVideoId();
    if (!id) { statusEl.textContent = 'Không tìm thấy video.'; dot.className = 'sg-dot error'; return; }
    const video = getVideoEl();
    if (!video) { statusEl.textContent = 'Không tìm thấy trình phát.'; dot.className = 'sg-dot error'; return; }

    const { serverUrl, tgtLang } = await new Promise((res) => chrome.storage.sync.get({ serverUrl: 'ws://localhost:8000/ws', tgtLang: tgtSel.value || 'en' }, res));
    const base = httpBase(serverUrl);
    const tgt = tgtSel.value || tgtLang || 'en';
    const tgtNllb = toNllb(tgt);

    dot.className = 'sg-dot connecting';
    statusEl.textContent = 'Đang lấy phụ đề…';

    let snips = [], srcNllb = 'eng_Latn';
    try {
      const r = await sgFetch(`${base}/api/youtube/transcript?id=${encodeURIComponent(id)}&src=`, { timeoutMs: 20000 });
      const data = JSON.parse(r.text);
      if (data.error) throw new Error(data.error);
      snips = data.snippets || [];
      srcNllb = toNllb(data.lang);
      if (!snips.length) throw new Error('Video không có phụ đề.');
    } catch (e) {
      console.error('[SmartGen] transcript fetch failed:', e);
      statusEl.textContent = 'Lỗi: ' + (e.message || e);
      dot.className = 'sg-dot error';
      return;
    }

    dot.className = 'sg-dot ready';
    statusEl.textContent = `Dịch 0/${snips.length} · TTS 0/${snips.length}`;

    const actx = new (window.AudioContext || window.webkitAudioContext)();
    const translated = {}, audioBufs = {}, trTries = {}, ttsTries = {};
    let prefetching = true, ticking = true;
    let playIdx = 0, dispIdx = 0, nextFree = 0, lastT = 0, activeIdx = -1;
    const MAX_TTS_AHEAD = 20, MAX_WAIT_S = 5, MAX_TEXT_WAIT_S = 1.5;
    const wasMuted = video.muted;
    video.muted = true;

    function updateStatus() {
      const tr = Object.keys(translated).length, tts = Object.values(audioBufs).filter((b) => b !== undefined).length;
      statusEl.textContent = `Dịch ${tr}/${snips.length} · TTS ${tts}/${snips.length}`;
    }
    function showCaption() {
      const txt = (translated[activeIdx] || '').trim();
      capEl.textContent = txt;
    }

    async function doTranslate(i) {
      if (srcNllb === tgtNllb) { translated[i] = snips[i].text; return; }
      const r = await sgFetch(`${base}/api/youtube/translate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: snips[i].text, src_lang: srcNllb, tgt_lang: tgtNllb }),
        timeoutMs: 20000,
      });
      translated[i] = (JSON.parse(r.text).translated_text || '').trim();
    }

    async function doTts(i) {
      const txt = translated[i];
      if (!txt) { audioBufs[i] = null; return; }
      const synthSpeed = tgt === 'vi' ? 1.4 : 1.0;
      let resp, defSr;
      if (tgt === 'vi') {
        resp = await sgFetch(`${base}/api/youtube/tts`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: txt, speed: synthSpeed }), binary: true, timeoutMs: 30000 });
        defSr = '22050';
      } else {
        resp = await sgFetch(`${base}/api/tts/say`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: txt }), binary: true, timeoutMs: 30000 });
        defSr = '24000';
      }
      const sr = parseInt(resp.headers['x-sample-rate'] || defSr, 10);
      const binStr = atob(resp.bodyB64);
      const bytes = new Uint8Array(binStr.length);
      for (let k = 0; k < binStr.length; k++) bytes[k] = binStr.charCodeAt(k);
      const i16 = new Int16Array(bytes.buffer);
      const f32 = new Float32Array(i16.length);
      for (let k = 0; k < i16.length; k++) f32[k] = i16[k] / 32768;
      const ab = actx.createBuffer(1, f32.length, sr);
      ab.getChannelData(0).set(f32);
      audioBufs[i] = ab;
    }

    async function translateLoop() {
      if (!prefetching) return;
      let job = -1;
      for (let i = 0; i < snips.length; i++) if (translated[i] === undefined && (trTries[i] || 0) < 3) { job = i; break; }
      if (job >= 0) {
        try { await doTranslate(job); } catch (_) { trTries[job] = (trTries[job] || 0) + 1; if (trTries[job] >= 3) translated[job] = ''; }
        updateStatus();
      }
      if (prefetching) setTimeout(translateLoop, job >= 0 ? 30 : 200);
    }

    async function ttsLoop() {
      if (!prefetching) return;
      let readyAhead = 0;
      for (let i = playIdx; i < snips.length; i++) { if (audioBufs[i] instanceof AudioBuffer) readyAhead++; if (readyAhead >= MAX_TTS_AHEAD) break; }
      let job = -1;
      if (readyAhead < MAX_TTS_AHEAD) {
        for (let i = 0; i < snips.length; i++) if (translated[i] !== undefined && audioBufs[i] === undefined && (ttsTries[i] || 0) < 2) { job = i; break; }
      }
      if (job >= 0) {
        try { await doTts(job); } catch (_) { ttsTries[job] = (ttsTries[job] || 0) + 1; if (ttsTries[job] >= 2) audioBufs[job] = null; }
        updateStatus();
      }
      if (prefetching) setTimeout(ttsLoop, job >= 0 ? 30 : 200);
    }

    function windowFor(i) { const nx = snips[i + 1]; return nx ? nx.start - snips[i].start : snips[i].dur || 3; }

    function playClip(i) {
      const ab = audioBufs[i];
      if (!(ab instanceof AudioBuffer)) return;
      const baseRate = tgt === 'vi' ? 1.0 : 1.0;
      const W = windowFor(i);
      let rate = baseRate;
      if (W > 0.4 && ab.duration / rate > W) rate = Math.min(baseRate * (tgt === 'vi' ? 1.7 : 1.6), ab.duration / W);
      rate = Math.max(0.5, Math.min(2.0, rate));
      const src = actx.createBufferSource();
      src.buffer = ab; src.playbackRate.value = rate; src.connect(actx.destination);
      const at = Math.max(actx.currentTime, nextFree);
      src.start(at);
      nextFree = at + ab.duration / rate;
      audioBufs[i] = false;
    }

    function tick() {
      if (!ticking) return;
      const t = video.currentTime || 0;
      if (Math.abs(t - lastT) > 1.5) {
        playIdx = snips.findIndex((s) => s.start >= t - 0.2);
        if (playIdx < 0) playIdx = snips.length;
        dispIdx = playIdx;
        nextFree = actx.currentTime;
      }
      lastT = t;
      // Text follows translation readiness only — must not wait on the (much
      // slower) TTS pipeline, otherwise captions stall in lockstep with voice.
      while (dispIdx < snips.length && snips[dispIdx].start <= t) {
        const cur = dispIdx;
        const trReady = translated[cur] !== undefined;
        const gaveUp = snips[cur].start < t - MAX_TEXT_WAIT_S;
        if (!trReady && !gaveUp) break;
        activeIdx = cur; dispIdx++;
        showCaption();
      }
      // Audio playback advances independently, gated on its own readiness.
      while (playIdx < snips.length && snips[playIdx].start <= t) {
        const cur = playIdx;
        const audReady = audioBufs[cur] !== undefined;
        const gaveUp = snips[cur].start < t - MAX_WAIT_S;
        if (!audReady && !gaveUp) break;
        playClip(cur); playIdx++;
      }
      setTimeout(tick, 100);
    }

    translateLoop();
    ttsLoop();
    tick();

    session = {
      stop() {
        prefetching = false; ticking = false;
        try { actx.close(); } catch (_) {}
        video.muted = wasMuted;
      },
    };
  }

  toggle.addEventListener('click', async () => {
    if (session) { stopSession(); return; }
    toggle.disabled = true;
    toggle.textContent = '■ Dừng';
    toggle.classList.add('active');
    await startSession();
    if (!session) { toggle.textContent = '▶ Lồng tiếng'; toggle.classList.remove('active'); }
    toggle.disabled = false;
  });

  // ── SPA navigation: YouTube swaps videos without a full page reload ────────
  let lastId = getVideoId();
  document.addEventListener('yt-navigate-finish', () => {
    const id = getVideoId();
    if (id !== lastId) { lastId = id; stopSession(); }
  });
})();
