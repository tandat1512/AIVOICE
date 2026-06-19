// SmartGen popup settings script

const DEFAULT_SETTINGS = {
  serverUrl: 'ws://localhost:8000/ws',
  srcLang: 'vi',
  tgtLang: 'en',
  voice: 'af_heart',
  volume: 1.0,
};

const $ = id => document.getElementById(id);

// ── Load saved settings ───────────────────────────────────────────────────────

chrome.storage.sync.get(DEFAULT_SETTINGS, settings => {
  $('server-url').value = settings.serverUrl;
  $('src-lang').value   = settings.srcLang;
  $('tgt-lang').value   = settings.tgtLang;
  $('volume').value     = settings.volume;

  fetchVoices(settings.serverUrl, settings.voice);
});

// ── Save ──────────────────────────────────────────────────────────────────────

$('btn-save').addEventListener('click', () => {
  const newSettings = {
    serverUrl: $('server-url').value.trim() || DEFAULT_SETTINGS.serverUrl,
    srcLang:   $('src-lang').value,
    tgtLang:   $('tgt-lang').value,
    voice:     $('voice').value,
    volume:    parseFloat($('volume').value),
  };

  chrome.storage.sync.set(newSettings, () => {
    const msg = $('saved-msg');
    msg.textContent = 'Saved!';
    setTimeout(() => { msg.textContent = ''; }, 2000);
  });
});

// ── Test connection ───────────────────────────────────────────────────────────

$('btn-test').addEventListener('click', () => {
  const wsUrl = $('server-url').value.trim() || DEFAULT_SETTINGS.serverUrl;
  testConnection(wsUrl);
});

$('server-url').addEventListener('change', () => {
  fetchVoices($('server-url').value.trim());
});

function wsUrlToHttp(wsUrl) {
  return wsUrl.replace(/^ws(s?):\/\//, 'http$1://').replace(/\/ws$/, '');
}

async function testConnection(wsUrl) {
  const indicator = $('conn-indicator');
  const status    = $('conn-status');

  indicator.className = 'indicator';
  status.textContent = 'Testing…';

  const httpBase = wsUrlToHttp(wsUrl);

  try {
    const res = await fetch(`${httpBase}/api/health`, { signal: AbortSignal.timeout(4000) });
    const data = await res.json();

    if (res.ok) {
      indicator.className = 'indicator ok';
      const parts = [];
      if (data.stt)       parts.push(`STT: ${data.stt}`);
      if (data.translate) parts.push(`TR: ${data.translate}`);
      if (data.tts)       parts.push(`TTS: ${data.tts}`);
      status.textContent = parts.join(' · ') || 'Connected';
    } else {
      indicator.className = 'indicator fail';
      status.textContent = `Server error ${res.status}`;
    }
  } catch (err) {
    indicator.className = 'indicator fail';
    status.textContent = 'Cannot reach server';
  }
}

async function fetchVoices(wsUrl, selectedVoice) {
  const httpBase = wsUrlToHttp(wsUrl || DEFAULT_SETTINGS.serverUrl);
  const voiceEl  = $('voice');

  try {
    const res  = await fetch(`${httpBase}/api/tts/voices`, { signal: AbortSignal.timeout(3000) });
    const data = await res.json();

    voiceEl.innerHTML = '';
    for (const v of (data.voices || [])) {
      const opt = document.createElement('option');
      opt.value = v.id;
      opt.textContent = v.name;
      opt.selected = v.id === (selectedVoice || DEFAULT_SETTINGS.voice);
      voiceEl.appendChild(opt);
    }

    if (!voiceEl.options.length) {
      voiceEl.innerHTML = '<option value="af_heart">af_heart (default)</option>';
    }
  } catch (_) {
    voiceEl.innerHTML = '<option value="af_heart">af_heart (default)</option>';
    if (selectedVoice) {
      voiceEl.value = selectedVoice;
    }
  }
}
