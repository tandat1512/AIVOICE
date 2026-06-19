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

  // ── YouTube dubbing: transcript timeline → translate all → TTS all → sync play ─
  // Flow:
  //   1. GET /api/youtube/transcript  — fetch segments with timestamps, emit to source pane
  //   2. translateLoop               — translate ALL segments in order (background)
  //   3. ttsLoop                     — TTS each translated segment in order (background)
  //   4. tick()                      — at each timestamp, play the audio + show translated text
  // onTranscript fires with { segments, currentIdx } so the Studio can show the
  // original-text timeline in the source pane (same pattern as AudioFileTranslateStudio).
  SG.createYoutubeDub = function (opts) {
    const o = opts || {};
    const cb = (name, ...args) => { if (typeof o[name] === 'function') o[name](...args); };
    const YT2NLLB = { en:'eng_Latn', vi:'vie_Latn', ja:'jpn_Jpan', ko:'kor_Hang', zh:'zho_Hans', fr:'fra_Latn', es:'spa_Latn', de:'deu_Latn', ru:'rus_Cyrl', th:'tha_Thai', id:'ind_Latn', pt:'por_Latn' };
    const toNllb = (c) => YT2NLLB[c] || YT2NLLB[(c || '').split('-')[0]] || 'eng_Latn';

    function extractId(s) {
      const m = (s || '').match(/(?:v=|youtu\.be\/|\/shorts\/|\/embed\/|\/live\/)([A-Za-z0-9_-]{11})/);
      if (m) return m[1];
      if (/^[A-Za-z0-9_-]{11}$/.test((s || '').trim())) return s.trim();
      return null;
    }
    function ensureYTApi() {
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

    let actx = null, ytPlayer = null;
    let ticking = false, prefetching = false;
    let snips = [], srcNllb = 'eng_Latn';
    const tgtNllb = toNllb(o.tgt || 'vi');
    let speed = o.speed || 1.0;
    let playIdx = 0, dispIdx = 0, nextFree = 0, lastT = 0, activeIdx = -1;

    const translated = {};   // i -> string ('' if gave up)
    const audioBufs  = {};   // i -> AudioBuffer | null (null=failed) | false (played, freed)
    const trTries = {}, ttsTries = {};

    const MAX_TTS_AHEAD = 20;  // max buffered audio clips ahead of playhead
    const MAX_WAIT_S    = 5;   // give up waiting for audio before playing the next clip
    const MAX_TEXT_WAIT_S = 1.5; // give up waiting for translation text (translateLoop is fast, this is just a safety net)

    function emitSegments() {
      const segments = snips.map((s, i) => {
        const ab = audioBufs[i];
        return {
          id: i, start: s.start, dur: s.dur, text: s.text,
          translated: translated[i] !== undefined ? (translated[i] || '') : null,
          audioReady: ab === false || (ab != null && ab !== undefined),
        };
      });
      cb('onTranscript', { segments, currentIdx: activeIdx });
    }

    function emitTranslation() {
      const committed = [];
      for (let i = 0; i <= activeIdx && i < snips.length; i++) {
        const txt = (translated[i] || '').trim();
        if (txt) committed.push({ id: i, text: txt, start: snips[i].start, speaker: 0 });
      }
      cb('onTranslation', { committed, preview: '' });
    }

    async function doTranslate(i) {
      if (srcNllb === tgtNllb) { translated[i] = snips[i].text; return; }
      const r = await fetch('/api/youtube/translate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: snips[i].text, src_lang: srcNllb, tgt_lang: tgtNllb }),
        signal: AbortSignal.timeout(20000),
      });
      translated[i] = ((await r.json()).translated_text || '').trim();
    }

    async function doTts(i) {
      const txt = translated[i];
      if (!txt) { audioBufs[i] = null; return; }
      const synthSpeed = (o.tgt === 'vi') ? Math.max(speed, 1.4) : speed;
      let resp, defSr;
      if (o.tgt === 'vi') {
        resp = await fetch('/api/youtube/tts', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: txt, speed: synthSpeed }),
          signal: AbortSignal.timeout(30000),
        });
        defSr = '22050';
      } else {
        resp = await fetch('/api/tts/say', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: txt, voice: o.voice || '' }),
          signal: AbortSignal.timeout(30000),
        });
        defSr = '24000';
      }
      const sr = parseInt(resp.headers.get('X-Sample-Rate') || defSr, 10);
      const i16 = new Int16Array(await resp.arrayBuffer());
      const f32 = new Float32Array(i16.length);
      for (let k = 0; k < i16.length; k++) f32[k] = i16[k] / 32768;
      const ab = actx.createBuffer(1, f32.length, sr);
      ab.getChannelData(0).set(f32);
      audioBufs[i] = ab;
    }

    // Translate ALL segments in order, one at a time
    async function translateLoop() {
      if (!prefetching) return;
      let job = -1;
      for (let i = 0; i < snips.length; i++) {
        if (translated[i] === undefined && (trTries[i] || 0) < 3) { job = i; break; }
      }
      if (job < 0) return; // all done
      try {
        await doTranslate(job);
      } catch (_) {
        trTries[job] = (trTries[job] || 0) + 1;
        if (trTries[job] >= 3) translated[job] = '';
      }
      emitSegments();
      if (prefetching) setTimeout(translateLoop, 30);
    }

    // TTS all translated segments in order, respecting the ahead-buffer cap
    async function ttsLoop() {
      if (!prefetching) return;
      // Count ready buffers ahead of playhead
      let readyAhead = 0;
      for (let i = playIdx; i < snips.length; i++) {
        if (audioBufs[i] instanceof AudioBuffer) readyAhead++;
        if (readyAhead >= MAX_TTS_AHEAD) break;
      }
      let job = -1;
      for (let i = 0; i < snips.length; i++) {
        if (translated[i] !== undefined && audioBufs[i] === undefined && (ttsTries[i] || 0) < 2) { job = i; break; }
      }
      if (job < 0 || readyAhead >= MAX_TTS_AHEAD) { setTimeout(ttsLoop, 200); return; }
      try {
        await doTts(job);
      } catch (_) {
        ttsTries[job] = (ttsTries[job] || 0) + 1;
        if (ttsTries[job] >= 2) audioBufs[job] = null;
      }
      emitSegments();
      if (prefetching) setTimeout(ttsLoop, 30);
    }

    function windowFor(i) {
      const nx = snips[i + 1];
      return nx ? (nx.start - snips[i].start) : (snips[i].dur || 3);
    }

    function playClip(i) {
      const ab = audioBufs[i];
      if (!(ab instanceof AudioBuffer)) return;
      cb('onMode', 'speaking');
      const baseRate = (o.tgt === 'vi') ? 1.0 : Math.max(0.5, Math.min(3, speed));
      const W = windowFor(i);
      let rate = baseRate;
      if (W > 0.4 && ab.duration / rate > W) {
        rate = Math.min(baseRate * ((o.tgt === 'vi') ? 1.7 : 1.6), ab.duration / W);
      }
      rate = Math.max(0.5, Math.min(2.0, rate));
      const src = actx.createBufferSource();
      src.buffer = ab;
      src.playbackRate.value = rate;
      src.connect(actx.destination);
      const at = Math.max(actx.currentTime, nextFree);
      src.start(at);
      nextFree = at + ab.duration / rate;
      audioBufs[i] = false; // mark as played, free AudioBuffer memory
    }

    function tick() {
      if (!ticking) return;
      if (ytPlayer && ytPlayer.getCurrentTime) {
        const t = ytPlayer.getCurrentTime();
        if (Math.abs(t - lastT) > 1.5) { // seek detected — resync
          playIdx = snips.findIndex((s) => s.start >= t - 0.2);
          if (playIdx < 0) playIdx = snips.length;
          dispIdx = playIdx;
          nextFree = actx ? actx.currentTime : 0;
        }
        lastT = t;
        let changed = false;
        // Text display advances on translation readiness alone — translateLoop runs
        // far ahead of playback, so this is rarely the bottleneck. It must NOT wait on
        // audio: TTS synthesis (CPU-bound, one clip at a time) is much slower than
        // translation, and gating text on it made the translation pane visibly lag
        // behind the (already-fast) translateLoop, even though the text was ready.
        while (dispIdx < snips.length && snips[dispIdx].start <= t) {
          const cur = dispIdx;
          const trReady = translated[cur] !== undefined;
          const gaveUp  = snips[cur].start < t - MAX_TEXT_WAIT_S;
          if (!trReady && !gaveUp) break;
          activeIdx = cur;
          changed = true;
          dispIdx++;
        }
        // Audio playback advances independently, gated on its own (slower) readiness.
        while (playIdx < snips.length && snips[playIdx].start <= t) {
          const cur = playIdx;
          const audReady = audioBufs[cur] !== undefined; // null/false/AudioBuffer all count
          const gaveUp   = snips[cur].start < t - MAX_WAIT_S;
          if (!audReady && !gaveUp) break;
          changed = true;
          playClip(cur);
          playIdx++;
        }
        if (changed) { emitTranslation(); emitSegments(); }
      }
      setTimeout(tick, 100);
    }

    async function start() {
      try {
        actx = actx || new (window.AudioContext || window.webkitAudioContext)();
        try { const b=actx.createBuffer(1,1,22050); const s=actx.createBufferSource(); s.buffer=b; s.connect(actx.destination); s.start(0); } catch(_) {}
        if (actx.state === 'suspended') await actx.resume();

        cb('onStatus', 'connecting');
        const id = extractId(o.url);
        if (!id) { cb('onError', 'Link YouTube không hợp lệ.'); return; }

        // Step 1: Fetch transcript with timeline
        const resp = await fetch('/api/youtube/transcript?id=' + encodeURIComponent(id) + '&src=');
        const data = await resp.json();
        if (data.error) { cb('onError', 'Lỗi transcript: ' + data.error); return; }
        snips   = data.snippets || [];
        srcNllb = toNllb(data.lang);
        if (!snips.length) { cb('onError', 'Video này không có phụ đề để lồng tiếng.'); return; }

        emitSegments(); // show raw segments immediately
        cb('onStatus', 'loading');

        // Step 2: Start translate → TTS pipeline for all segments
        prefetching = true;
        if (o.tgt === 'vi') fetch('/api/youtube/tts', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text:'xin chào',speed:1.4}) }).catch(()=>{});
        translateLoop();
        ttsLoop();

        // Step 3: Embed YouTube player
        await ensureYTApi();
        if (o.hostEl) o.hostEl.innerHTML = '';
        const div = document.createElement('div');
        if (o.hostEl) o.hostEl.appendChild(div);
        ytPlayer = new YT.Player(div, {
          videoId: id,
          playerVars: { rel: 0, modestbranding: 1, autoplay: 0 },
          events: {
            onReady: (e) => {
              try { e.target.mute(); } catch(_) {}
              cb('onReady'); cb('onStatus', 'listening');
            },
            onStateChange: (e) => {
              if (e.data === YT.PlayerState.PLAYING) {
                if (actx && actx.state === 'suspended') actx.resume();
                if (actx) nextFree = actx.currentTime;
                cb('onMode', 'translating');
                if (!ticking) { ticking = true; tick(); }
              } else if (e.data === YT.PlayerState.ENDED) {
                cb('onMode', 'idle');
              }
            },
          },
        });
      } catch (e) { cb('onError', (e && e.message) || 'Không tải được video.'); }
    }

    function stop() {
      ticking = false; prefetching = false;
      try { if (ytPlayer && ytPlayer.destroy) ytPlayer.destroy(); } catch(_) {}
      ytPlayer = null;
      try { if (actx) actx.close(); } catch(_) {}
      actx = null;
      cb('onClose');
    }

    return { start, stop, setSpeed: (s) => { speed = s; }, setVoice: () => {}, setVad: () => {}, setLang: () => {} };
  };

  window.SG = SG;
})();
