// SmartGen real backend client.
// Plain (non-module) script so the Babel-transpiled view scripts can call it via
// the global `window.SG`. Implements the same wire protocol as the legacy web/app.js:
//
//   client -> server : binary Int16 PCM 16kHz  +  JSON {type:config|stop}
//   server -> client : word | sync | correction | translation_update
//                      | trans_stream_c | trans_stream_i | clear_trans_i
//                      | tts_start | <binary PCM 24kHz> | tts_end | tts_cancel
//                      | info | error
//
// The view layer subscribes through callbacks instead of touching the DOM, so the
// SmartGen React UI renders real STT / translation / TTS data.

(function () {
  'use strict';

  // ── REST helpers ────────────────────────────────────────────────────────────
  async function _json(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url} → ${r.status}`);
    return r.json();
  }

  async function _postJson(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) {
      let msg = `${url} failed with ${r.status}`;
      try {
        const j = await r.json();
        msg = j.detail || msg;
      } catch (_) {}
      throw new Error(msg);
    }
    return r.json();
  }

  async function _putJson(url, body) {
    const r = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) {
      let msg = `${url} failed with ${r.status}`;
      try {
        const j = await r.json();
        msg = j.detail || msg;
      } catch (_) {}
      throw new Error(msg);
    }
    return r.json();
  }

  async function _deleteJson(url) {
    const r = await fetch(url, { method: 'DELETE' });
    if (!r.ok) {
      let msg = `${url} failed with ${r.status}`;
      try {
        const j = await r.json();
        msg = j.detail || msg;
      } catch (_) {}
      throw new Error(msg);
    }
    return r.json();
  }

  async function _postForm(url, form) {
    const r = await fetch(url, { method: 'POST', body: form });
    if (!r.ok) {
      let msg = `${url} failed with ${r.status}`;
      try {
        const j = await r.json();
        msg = j.detail || msg;
      } catch (_) {}
      throw new Error(msg);
    }
    return r.json();
  }

  async function _downloadJson(url, body) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) {
      let msg = `${url} failed with ${r.status}`;
      try {
        const j = await r.json();
        msg = j.detail || msg;
      } catch (_) {}
      throw new Error(msg);
    }
    const blob = await r.blob();
    let name = 'smartgen-export';
    const cd = r.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename\*=UTF-8''([^;]+)/);
    if (m) name = decodeURIComponent(m[1]);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // Poll /api/health until the server responds OK.
  // Resolves true when ready, false if timed out.
  // intervalMs = how often to retry, maxMs = total wait budget.
  async function waitForServer({ onStatus, intervalMs = 2000, maxMs = 90000 } = {}) {
    const deadline = Date.now() + maxMs;
    let attempt = 0;
    while (Date.now() < deadline) {
      try {
        const h = await fetch('/api/health', { signal: AbortSignal.timeout(3000) });
        if (h.ok) return true;
      } catch (_) { /* server not yet up */ }
      attempt++;
      if (typeof onStatus === 'function') {
        onStatus(`Chờ server… (${attempt})`);
      }
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    return false; // timed out
  }

  const SG = {
    fetchSttModels:       () => _json('/api/models').catch(() => ({ available: [], active: {} })),
    fetchTranslateModels: () => _json('/api/translate/models').catch(() => ({ models: [], default: '' })),
    fetchVoices:          () => _json('/api/tts/voices').catch(() => ({ voices: [], default: '' })),
    health:               () => _json('/api/health').catch(() => null),
    translateText:         (payload) => _postJson('/api/translate/text', payload),
    convertCurrency:       ({ amount, from, to }) => _json(`/api/currency/convert?amount=${encodeURIComponent(amount)}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`),
    detectCurrency:        (text) => _json(`/api/currency/detect?text=${encodeURIComponent(text)}`),
    translateImage:        ({ file, srcLang, tgtLang, translateModel, ocrEngine, ocrLang }) => {
      const form = new FormData();
      form.append('file', file);
      form.append('src_lang', srcLang || 'vie_Latn');
      form.append('tgt_lang', tgtLang || 'eng_Latn');
      form.append('translate_model', translateModel || '');
      form.append('ocr_engine', ocrEngine || '');
      form.append('ocr_lang', ocrLang || '');
      return _postForm('/api/translate/image', form);
    },
    translateAudioFile:    ({ file, srcLang, tgtLang, translateModel }) => {
      const form = new FormData();
      form.append('file', file);
      form.append('src_lang', srcLang || 'vie_Latn');
      form.append('tgt_lang', tgtLang || 'eng_Latn');
      form.append('translate_model', translateModel || '');
      return _postForm('/api/translate/audio-file', form);
    },
    travelAssist:          ({ file, text, srcLang, targetLanguage, homeCurrency, translateModel, ocrEngine, ocrLang }) => {
      const form = new FormData();
      if (file) form.append('file', file);
      form.append('text', text || '');
      form.append('src_lang', srcLang || 'jpn_Jpan');
      form.append('target_language', targetLanguage || 'vie_Latn');
      form.append('home_currency', homeCurrency || 'VND');
      form.append('translate_model', translateModel || '');
      form.append('ocr_engine', ocrEngine || '');
      form.append('ocr_lang', ocrLang || '');
      return _postForm('/api/travel/assist', form);
    },
    fetchGlossary:         () => _json('/api/glossary'),
    createGlossary:        (payload) => _postJson('/api/glossary', payload),
    updateGlossary:        (id, payload) => _putJson(`/api/glossary/${encodeURIComponent(id)}`, payload),
    deleteGlossary:        (id) => _deleteJson(`/api/glossary/${encodeURIComponent(id)}`),
    searchMemory:          ({ q, srcLang, tgtLang, limit }) => _json(`/api/memory/search?q=${encodeURIComponent(q)}&src_lang=${encodeURIComponent(srcLang||'')}&tgt_lang=${encodeURIComponent(tgtLang||'')}&limit=${encodeURIComponent(limit||5)}`),
    addMemory:             (payload) => _postJson('/api/memory', payload),
    exportFile:            (payload) => _downloadJson('/api/export', payload),
    postForm:              _postForm,
  };

  // Replay one line of translated text through the server TTS engine.
  // Returns a Promise that resolves when playback finishes (or rejects on error).
  SG.ttsSay = async function (text, { voice = '', speed = 1.0 } = {}) {
    if (!text || !text.trim()) return;
    const r = await fetch('/api/tts/say', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice }),
    });
    if (!r.ok) throw new Error('tts/say ' + r.status);
    const buf = await r.arrayBuffer();          // raw Int16 PCM @ sample_rate
    const sr = parseInt(r.headers.get('X-Sample-Rate') || '24000', 10);
    const int16 = new Int16Array(buf);
    const f32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 32768;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const ab = ctx.createBuffer(1, f32.length, sr);
    ab.copyToChannel(f32, 0);
    const node = ctx.createBufferSource();
    node.buffer = ab;
    node.playbackRate.value = Math.max(0.5, Math.min(3, speed));
    node.connect(ctx.destination);
    await new Promise((res) => { node.onended = res; node.start(); });
    try { ctx.close(); } catch (_) {}
  };

  // ── Session ─────────────────────────────────────────────────────────────────
  // opts: { src, tgt, backend, model, translateModel, voice, speed, muted,
  //         source ('mic'|'tab'), levelRef,
  //         onStatus, onReady, onTranscript, onTranslation, onMode,
  //         onLatency, onError, onClose }
  SG.createSession = function (opts) {
    const o = opts || {};
    const cb = (name, ...args) => { if (typeof o[name] === 'function') o[name](...args); };

    let ws = null, ac = null, node = null, stream = null, player = null;
    let levelTimer = null;
    let running = false;

    // STT text state
    let committed = '';
    let interim = '';
    let lastCommittedSentence = '';

    // Translation state
    const trChunks = new Map();   // id -> {text, speaker} (committed sentences)
    let stablePreview = '';       // trans_stream_c accumulation (locks into a chunk)
    let volatilePreview = '';     // trans_stream_i accumulation (cleared by clear_trans_i)
    let interimGen = 0;

    // TTS state
    let curUtterance = null;
    let ttsStart = 0;
    let firstAudioSeen = false;
    let sentenceDispatchTime = 0;

    function emitTranscript() {
      cb('onTranscript', { committed, interim });
    }
    function emitTranslation() {
      const list = [];
      for (const [id, c] of trChunks) if (c.text && c.text.trim()) list.push({ id, text: c.text.trim(), speaker: c.speaker || 0 });
      const preview = (stablePreview + ' ' + volatilePreview).trim();
      cb('onTranslation', { committed: list, preview });
    }

    function handleTranslationUpdate(delta) {
      if (!delta) return;
      const committedChunks = delta.committed || [];
      const seen = new Set();
      for (const c of committedChunks) {
        seen.add(c.id);
        const t = (c.text || '').trim();
        if (!t) continue;
        trChunks.set(c.id, { text: t, speaker: c.speaker || 0 });
      }
      for (const id of Array.from(trChunks.keys())) if (!seen.has(id)) trChunks.delete(id);
      if (committedChunks.length) stablePreview = '';   // preview locked into chunks
      volatilePreview = (delta.volatile_interim || []).map((c) => c.text).join(' ');
      emitTranslation();
    }

    function onMessage(ev) {
      // Binary frames = TTS PCM audio chunks.
      if (ev.data instanceof ArrayBuffer) {
        if (player && curUtterance) {
          player.enqueueChunk(curUtterance, ev.data);
          if (!firstAudioSeen && ttsStart) {
            const ms = Math.round(performance.now() - ttsStart);
            cb('onLatency', ms);
            firstAudioSeen = true;
          }
        }
        return;
      }

      let m; try { m = JSON.parse(ev.data); } catch { return; }

      switch (m.type) {
        case 'info':
          if (m.msg === 'ready') { cb('onStatus', 'listening'); cb('onReady'); cb('onMode', 'listening'); }
          else cb('onStatus', m.msg);
          break;

        case 'error':
          cb('onError', m.msg); cb('onMode', 'idle');
          break;

        case 'word':
          if (interim) {
            const iw = interim.trim().split(/\s+/);
            if (iw[0] === m.word) interim = iw.slice(1).join(' ');
          }
          committed += (committed ? ' ' : '') + m.word;
          cb('onMode', 'listening');
          emitTranscript();
          break;

        case 'sync': {
          const newCommitted = (m.committed || '').trim();
          if (newCommitted !== lastCommittedSentence) {
            if (newCommitted.endsWith('.') && !lastCommittedSentence.endsWith('.')) {
              sentenceDispatchTime = performance.now();
              cb('onMode', 'translating');
            }
            lastCommittedSentence = newCommitted;
          }
          committed = m.committed || '';
          interim = m.interim || '';
          emitTranscript();
          break;
        }

        case 'translation_update':
          handleTranslationUpdate(m.delta);
          break;

        case 'trans_stream_c':
          stablePreview += m.token || '';
          cb('onMode', 'translating');
          emitTranslation();
          break;

        case 'trans_stream_i':
          if (m.gen === undefined || m.gen === interimGen) {
            volatilePreview += m.token || '';
            emitTranslation();
          }
          break;

        case 'clear_trans_i':
          interimGen++;
          volatilePreview = '';
          emitTranslation();
          break;

        case 'correction':
          committed = m.text || '';
          interim = '';
          emitTranscript();
          cb('onCorrection', { committed });
          break;

        case 'tts_start':
          curUtterance = m.utterance_id;
          ttsStart = performance.now();
          firstAudioSeen = false;
          cb('onMode', 'speaking');
          break;

        case 'tts_end':
          if (running) cb('onMode', 'listening');
          break;

        case 'tts_cancel':
          if (player) player.cancel(m.utterance_id);
          if (running) cb('onMode', 'listening');
          break;
      }
    }

    async function start() {
      if (running) return;
      running = true;
      committed = interim = lastCommittedSentence = '';
      trChunks.clear(); stablePreview = volatilePreview = '';
      curUtterance = null; firstAudioSeen = false;

      cb('onStatus', 'connecting');

      // ── STEP 1: Capture audio (MUST be first — needs live user-gesture context) ──
      // getDisplayMedia / getUserMedia must be called synchronously from a user
      // gesture. Any await before this (e.g. health poll) would break tab capture
      // in Chrome/Edge because the user-activation token expires after ~1 async hop.
      const wantTab = o.source === 'tab' || o.source === 'youtube' || o.source === 'meet';
      try {
        if (wantTab) {
          const disp = await navigator.mediaDevices.getDisplayMedia({
            video: { width: 1, height: 1, frameRate: 1 },
            audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, sampleRate: 48000 },
          });
          const tracks = disp.getAudioTracks();
          if (!tracks.length) {
            cb('onError', "Không có audio — bật 'Chia sẻ âm thanh tab' trong hộp thoại");
            stop(); return;
          }
          // Drop the video track immediately — we only need audio.
          disp.getVideoTracks().forEach((t) => t.stop());
          stream = new MediaStream(tracks);
        } else {
          stream = await navigator.mediaDevices.getUserMedia({
            audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          });
        }
      } catch (e) {
        cb('onError', (wantTab ? 'Bắt audio tab thất bại: ' : 'Micro bị từ chối: ') + e.message);
        stop(); return;
      }

      // ── STEP 2: Wait for server to be ready (models loaded) ─────────────────
      const serverReady = await waitForServer({
        onStatus: (msg) => cb('onStatus', msg),
        intervalMs: 2000,
        maxMs: 90000,
      });
      if (!serverReady) {
        cb('onError', 'Server không phản hồi sau 90 giây. Kiểm tra terminal.');
        running = false;
        return;
      }
      cb('onStatus', 'connecting');

      // ── STEP 3: Open WebSocket ───────────────────────────────────────────────
      const wsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
      ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';

      ws.onopen = () => {
        ws.send(JSON.stringify({
          type: 'config',
          src: o.src, tgt: o.tgt,
          backend: o.backend || '',
          model: o.model || '',
          translate_model: o.translateModel || '',
          voice: o.voice || '',
          vad: o.vad || 0,
        }));
        cb('onStatus', 'loading');
      };
      ws.onmessage = onMessage;
      ws.onerror = () => cb('onError', 'WebSocket error');
      ws.onclose = () => { cleanup(); cb('onClose'); };

      // ── STEP 4: Build audio pipeline and connect to worklet ─────────────────
      ac = new AudioContext({ sampleRate: 48000 });
      // Resume AudioContext — browsers auto-suspend it when created without
      // an active audio-output gesture (common with tab-capture sources).
      if (ac.state === 'suspended') await ac.resume();

      try {
        await ac.audioWorklet.addModule('/static/worklets/pcm-worklet.js');
      } catch (e) {
        cb('onError', 'Worklet load: ' + e.message); stop(); return;
      }

      const { StreamingAudioPlayer } = await import('/static/audio-player.js');
      player = new StreamingAudioPlayer(ac, 24000);
      player.setMuted(!!o.muted);
      player.setPlaybackRate(o.speed || 1.0);

      const srcNode = ac.createMediaStreamSource(stream);
      const hpf = ac.createBiquadFilter();
      hpf.type = 'highpass'; hpf.frequency.value = 80; hpf.Q.value = 0.7;
      const gain = ac.createGain();
      // Tab audio is already mixed/normalized; mic needs more boost.
      gain.gain.value = wantTab ? 1.2 : 2.0;

      node = new AudioWorkletNode(ac, 'pcm-worklet');
      node.port.onmessage = (e) => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(e.data);
      };

      // Mic level → orb (writes the shared ref directly; no React re-render).
      const analyser = ac.createAnalyser();
      analyser.fftSize = 256;
      const buf = new Float32Array(analyser.fftSize);
      levelTimer = setInterval(() => {
        if (!ac) return;
        analyser.getFloatTimeDomainData(buf);
        let sum = 0; for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
        const rms = Math.sqrt(sum / buf.length);
        const lvl = Math.min(1, rms * 3.6);
        if (o.levelRef) o.levelRef.current = lvl;
        cb('onLevel', lvl);
      }, 90);

      srcNode.connect(hpf);
      hpf.connect(gain);
      gain.connect(analyser);
      gain.connect(node);
      node.connect(ac.destination);
    }

    function cleanup() {
      if (levelTimer) { clearInterval(levelTimer); levelTimer = null; }
      if (player && curUtterance) { try { player.cancel(curUtterance); } catch (_) {} }
      player = null; curUtterance = null;
      try { node && node.disconnect(); } catch (_) {}
      try { stream && stream.getTracks().forEach((t) => t.stop()); } catch (_) {}
      try { ac && ac.close(); } catch (_) {}
      node = stream = ac = null;
      if (o.levelRef) o.levelRef.current = 0;
    }

    function stop() {
      running = false;
      if (ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ type: 'stop' })); } catch (_) {}
        ws.close();
      }
      ws = null;
      cleanup();
      cb('onMode', 'idle');
      cb('onStatus', 'idle');
    }

    return {
      start,
      stop,
      isRunning: () => running,
      setMuted: (b) => { o.muted = b; if (player) player.setMuted(b); },
      setSpeed: (x) => { o.speed = x; if (player) player.setPlaybackRate(x); },
      setLang: (src, tgt) => {
        o.src = src; o.tgt = tgt;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'config', src, tgt }));
        }
      },
      setVoice: (v) => {
        o.voice = v;
        if (v && ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'config', voice: v }));
        }
      },
      setVad: (ms) => {
        o.vad = ms;
        if (ms && ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'config', vad: ms }));
        }
      },
    };
  };

  // ── YouTube transcript dubbing (mode A) ──────────────────────────────────────
  // Embed the YouTube player, read its caption transcript (NO STT), translate +
  // TTS each line a few seconds ahead of the playhead, and play the Vietnamese
  // audio synced to player.getCurrentTime(). Original audio is muted. Same callback
  // shape as createSession so the Studio can swap it into sessionRef.
  // opts: { url, hostEl, speed, onStatus, onReady, onMode, onTranscript, onTranslation, onError, onClose }
  SG.createYoutubeDub = function (opts) {
    const o = opts || {};
    const cb = (name, ...args) => { if (typeof o[name] === 'function') o[name](...args); };
    const YT2NLLB = { en:'eng_Latn', vi:'vie_Latn', ja:'jpn_Jpan', ko:'kor_Hang', zh:'zho_Hans', fr:'fra_Latn', es:'spa_Latn', de:'deu_Latn', ru:'rus_Cyrl', th:'tha_Thai', id:'ind_Latn', pt:'por_Latn' };
    const toNllb = (c) => YT2NLLB[c] || YT2NLLB[(c || '').split('-')[0]] || 'eng_Latn';
    const tgtNllb = toNllb(o.tgt || 'vi');   // user's target language -> NLLB code
    function extractId(s) {
      const m = (s || '').match(/(?:v=|youtu\.be\/|\/shorts\/|\/embed\/|\/live\/)([A-Za-z0-9_-]{11})/);
      if (m) return m[1];
      if (/^[A-Za-z0-9_-]{11}$/.test((s || '').trim())) return s.trim();
      return null;
    }
    function ensureApi() {
      return new Promise((res) => {
        if (window.YT && window.YT.Player) { res(); return; }
        const prev = window.onYouTubeIframeAPIReady;
        window.onYouTubeIframeAPIReady = () => { if (typeof prev === 'function') prev(); res(); };
        if (!document.getElementById('yt-iframe-api')) {
          const s = document.createElement('script');
          s.id = 'yt-iframe-api'; s.src = 'https://www.youtube.com/iframe_api';
          document.head.appendChild(s);
        }
      });
    }

    let actx = null, player = null, ticking = false, lastT = 0, nextIdx = 0, nextFree = 0, wake = null;
    let snips = [], srcNllb = 'eng_Latn', speed = o.speed || 1.0;
    let tgtChunks = [], chunkId = 0;
    const prepared = {};        // i -> { audio }   (audio === null = synthesis gave up)
    const translated = {};      // i -> string      ('' = empty / gave up)
    const trAttempts = {}, ttsAttempts = {};
    const _dbg = { played: 0, skipLate: 0, skipBacklog: 0, nullAudio: 0, _t: 0 };
    try { window.__ytdub = _dbg; } catch (_) {}
    let _badge = null;
    function ensureBadge() {
      if (_badge || typeof document === 'undefined' || !document.body) return;
      _badge = document.createElement('div');
      _badge.style.cssText = 'position:fixed;left:10px;bottom:10px;z-index:99999;background:#111;color:#0f0;font:12px monospace;padding:6px 10px;border-radius:6px;cursor:pointer;opacity:.9';
      _badge.title = 'Bấm để bật tiếng lồng (mở khoá AudioContext)';
      _badge.onclick = () => { ensureCtx(); if (actx) actx.resume(); };
      document.body.appendChild(_badge);
    }
    function updateBadge() {
      if (!_badge) return;
      const st = actx ? actx.state : 'none';
      _badge.textContent = '🔊 ' + st + ' · phát:' + _dbg.played + (st !== 'running' ? ' — BẤM ĐỂ BẬT TIẾNG' : '');
      _badge.style.color = (st === 'running') ? '#3f6' : '#f55';
    }
    function removeBadge() { if (_badge) { try { _badge.remove(); } catch (_) {} _badge = null; } }

    function ensureCtx() {
      if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)();
      if (actx.state === 'suspended') actx.resume();
    }
    async function translate(text) {
      if (srcNllb === tgtNllb) return text;   // caption already in the target language
      const r = await fetch('/api/youtube/translate', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ text, src_lang: srcNllb, tgt_lang: tgtNllb }), signal: AbortSignal.timeout(15000) });
      return ((await r.json()).translated_text || '').trim();
    }
    async function tts(text, synthSpeed = speed) {
      if (!text) return null;
      // Vietnamese -> VITS (/api/youtube/tts); English -> Kokoro (/api/tts/say).
      let resp, defSr;
      if (o.tgt === 'vi') {
        resp = await fetch('/api/youtube/tts', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ text, speed: synthSpeed }), signal: AbortSignal.timeout(15000) });
        defSr = '22050';
      } else {
        resp = await fetch('/api/tts/say', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ text, voice: o.voice || '' }), signal: AbortSignal.timeout(15000) });
        defSr = '24000';
      }
      const sr = parseInt(resp.headers.get('X-Sample-Rate') || defSr, 10);
      const i16 = new Int16Array(await resp.arrayBuffer());
      const f32 = new Float32Array(i16.length);
      for (let k = 0; k < i16.length; k++) f32[k] = i16[k] / 32768;
      const ab = actx.createBuffer(1, f32.length, sr);
      ab.getChannelData(0).set(f32);
      return ab;
    }
    // ── Two-stage prep, both single-flight (one fetch at a time so the box is never
    // flooded). Translation runs on the GPU (NLLB_DEVICE=cuda) AHEAD of TTS on the
    // CPU, in parallel, so the on-screen translation is always ready in time while
    // voice synthesis — the slower, CPU-bound stage — fills the audio buffer behind
    // it. Transient failures RETRY instead of permanently dropping a line (that was
    // the old "translated a bit then froze" bug). Text is shown in sync even when a
    // voice clip is late/skipped, so the translation never appears to stall.
    const MAX_PREPARED = 12;   // cap ready-but-unplayed audio clips ahead (client RAM)
    const TR_AHEAD = 40;       // translate up to this many lines ahead of the playhead
    const STALE_S = 1.5;       // (kept) translation grace
    const MAX_WAIT_S = 5;      // wait up to this long for a line's VOICE before showing its text alone — keeps text+voice TOGETHER
    const MAX_BACKLOG_S = 3.0; // anti-overlap guard for back-to-back clips
    let prefetching = false;
    async function translateLoop() {
      if (!prefetching) return;
      let job = -1;
      for (let i = nextIdx; i < snips.length && i < nextIdx + TR_AHEAD; i++) {
        if (translated[i] === undefined && (trAttempts[i] || 0) < 3) { job = i; break; }
      }
      if (job < 0) { setTimeout(translateLoop, 150); return; }   // far enough ahead — re-check soon
      try {
        translated[job] = await translate(snips[job].text);
      } catch (e) {
        trAttempts[job] = (trAttempts[job] || 0) + 1;
        if (trAttempts[job] >= 3) translated[job] = '';          // give up -> empty (line keeps flowing)
      }
      translateLoop();                                           // chain to the next line
    }
    async function ttsLoop() {
      if (!prefetching) return;
      let job = -1, ready = 0;
      for (let i = nextIdx; i < snips.length; i++) {
        if (prepared[i] && prepared[i].audio) ready++;
        if (ready >= MAX_PREPARED) break;                        // audio buffer full enough
        if (translated[i] !== undefined && prepared[i] === undefined && (ttsAttempts[i] || 0) < 2) { job = i; break; }
      }
      if (job < 0) { setTimeout(ttsLoop, 100); return; }
      try {
        const txt = translated[job] || '';
        // The Vietnamese VITS voice is slow/deliberate, so synthesize it brisker
        // (1.4x native VITS time-stretch — about the most it compresses, no pitch
        // shift, sounds like an energetic narrator and synthesizes ~4x faster). The
        // remaining window-fit is done at playback. Without this the dub piles up and
        // lines get dropped.
        const synthSpeed = (o.tgt === 'vi') ? Math.max(speed, 1.4) : speed;
        const audio = txt ? await tts(txt, synthSpeed) : null;
        prepared[job] = { audio };
      } catch (e) {
        ttsAttempts[job] = (ttsAttempts[job] || 0) + 1;
        if (ttsAttempts[job] >= 2) prepared[job] = { audio: null };
      }
      ttsLoop();
    }
    function startPrefetch() {
      if (prefetching) return;
      prefetching = true;
      translateLoop();   // GPU stage
      ttsLoop();         // CPU stage (runs in parallel with the above)
    }
    function emitPanes() {
      // No source-transcript mirror — the YouTube dub only shows the translation.
      cb('onTranslation', { committed: tgtChunks.slice(), preview: '' });
    }
    function windowFor(i) {
      const nx = snips[i + 1];
      return nx ? (nx.start - snips[i].start) : (snips[i].dur || 3);
    }
    function showText(i) {
      const txt = (translated[i] || '').trim();
      if (txt) { tgtChunks.push({ id: ++chunkId, text: txt, speaker: 0 }); emitPanes(); }
    }
    function playClip(i) {
      const d = prepared[i];
      if (!d || !d.audio) { _dbg.nullAudio++; return; }
      cb('onMode', 'speaking');
      // Base rate: VITS already baked `speed` into the vi audio; Kokoro (en) did not.
      const baseRate = (o.tgt === 'vi') ? 1 : Math.max(0.5, Math.min(3, speed));
      // Residual fit: the vi clip was already time-stretched at synth, so only nudge it
      // (1.35x) if the estimate undershot; en (Kokoro has no speed param) fits here.
      const W = windowFor(i);
      let rate = baseRate;
      if (W > 0.4 && d.audio.duration / rate > W) {
        const resid = (o.tgt === 'vi') ? 1.7 : 1.6;
        rate = Math.min(baseRate * resid, d.audio.duration / W);
      }
      rate = Math.max(0.5, Math.min(2.0, rate));
      const s = actx.createBufferSource();
      s.buffer = d.audio;
      s.playbackRate.value = rate;
      s.connect(actx.destination);
      const at = Math.max(actx.currentTime, nextFree);
      s.start(at); nextFree = at + d.audio.duration / rate;
      _dbg.played++;
      if (_dbg.played <= 6) console.log('[ytdub] PLAY', i, 'state', actx.state, 'at', at.toFixed(2), 'ct', actx.currentTime.toFixed(2), 'dur', d.audio.duration.toFixed(2), 'rate', rate.toFixed(2));
    }
    function tick() {
      if (!ticking) return;
      if (player && player.getCurrentTime) {
        const t = player.getCurrentTime();
        if (Math.abs(t - lastT) > 1.5) {            // user seeked -> resync (keep translations, drop audio buffer)
          for (const k in prepared) delete prepared[k];
          for (const k in ttsAttempts) delete ttsAttempts[k];
          nextIdx = snips.findIndex((s) => s.start >= t - 0.2);
          if (nextIdx < 0) nextIdx = snips.length;
          nextFree = actx.currentTime;
        }
        lastT = t;
        while (nextIdx < snips.length && snips[nextIdx].start <= t) {
          const cur = nextIdx;
          const trReady = translated[cur] !== undefined;
          const audReady = prepared[cur] !== undefined;
          const gaveUpWaiting = snips[cur].start < t - MAX_WAIT_S;
          // Keep TEXT and VOICE together: wait until BOTH are ready before emitting the
          // line. Only after waiting too long do we fall back to text-only, so one stuck
          // clip can't stall the whole dub.
          if ((!trReady || !audReady) && !gaveUpWaiting) break;
          showText(cur);
          if (audReady) playClip(cur); else _dbg.skipLate++;
          delete prepared[cur];
          nextIdx++;
        }
      }
      if ((_dbg._t = _dbg._t + 1) % 30 === 0)
        console.log('[ytdub] stats', JSON.stringify(_dbg), 'ctx', actx && actx.state, 'nextIdx', nextIdx);
      updateBadge();
      setTimeout(tick, 100);
    }

    async function start() {
      try {
        ensureCtx();
        // Unlock audio inside the user gesture: some browsers keep a bare AudioContext
        // silent until a source has played from a gesture. Start a 1-sample silent buffer.
        try { const _b = actx.createBuffer(1, 1, 22050); const _s = actx.createBufferSource(); _s.buffer = _b; _s.connect(actx.destination); _s.start(0); } catch (_) {}
        if (actx && actx.state === 'suspended') { try { await actx.resume(); } catch (_) {} }
        console.log('[ytdub] start: ctx.state =', actx && actx.state);
        ensureBadge();
        // Warm the Vietnamese VITS model now (it lazy-loads ~2-3s on first call) so the
        // very first dubbed line is not delayed by a cold model load.
        if (o.tgt === 'vi') fetch('/api/youtube/tts', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ text:'xin chào', speed: 1.4 }) }).catch(()=>{});
        // Safety net: the YouTube Play button is a cross-origin gesture and does NOT
        // resume OUR AudioContext, so if it is still suspended, wake it on the next
        // click/keypress anywhere on the page (otherwise audio is scheduled silently).
        wake = () => { if (actx && actx.state === 'suspended') { actx.resume(); console.log('[ytdub] wake->resume; state', actx.state); } };
        document.addEventListener('pointerdown', wake, true);
        document.addEventListener('keydown', wake, true);
        cb('onStatus', 'connecting');
        const id = extractId(o.url);
        if (!id) { cb('onError', 'Link YouTube không hợp lệ.'); return; }
        const r = await fetch('/api/youtube/transcript?id=' + encodeURIComponent(id) + '&src=');
        const j = await r.json();
        if (j.error) { cb('onError', 'Lỗi transcript: ' + j.error); return; }
        snips = j.snippets || []; srcNllb = toNllb(j.lang);
        if (!snips.length) { cb('onError', 'Video này không có phụ đề để lồng tiếng.'); return; }
        await ensureApi();
        const host = o.hostEl; if (host) host.innerHTML = '';
        const target = document.createElement('div');
        if (host) host.appendChild(target);
        player = new YT.Player(target, {
          videoId: id,
          playerVars: { rel: 0, modestbranding: 1, autoplay: 0 },
          events: {
            onReady: (e) => { try { e.target.mute(); } catch (_) {} startPrefetch(); cb('onReady'); cb('onStatus', 'listening'); },
            onStateChange: (e) => {
              if (e.data === YT.PlayerState.PLAYING) {
                ensureCtx();
                if (actx) { if (actx.state === 'suspended') actx.resume(); nextFree = actx.currentTime; }  // anchor the audio clock to "now"
                console.log('[ytdub] PLAYING: ctx.state =', actx && actx.state, 'ct', actx && actx.currentTime.toFixed(2));
                cb('onMode', 'translating');
                if (!ticking) { ticking = true; tick(); }
              }
            },
          },
        });
      } catch (e) { cb('onError', (e && e.message) || 'Không tải được video.'); }
    }
    function stop() {
      ticking = false;
      prefetching = false;
      removeBadge();
      if (wake) { document.removeEventListener('pointerdown', wake, true); document.removeEventListener('keydown', wake, true); wake = null; }
      try { if (player && player.destroy) player.destroy(); } catch (_) {}
      player = null;
      try { if (actx) actx.close(); } catch (_) {}
      actx = null;
      cb('onClose');
    }
    return { start, stop, setSpeed: (s) => { speed = s; }, setVoice: () => {}, setVad: () => {}, setLang: () => {} };
  };

  window.SG = SG;
})();
