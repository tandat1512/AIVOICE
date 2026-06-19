// SmartGen background service worker.
// Manages a single WebSocket connection and relays messages to/from content scripts.

const DEFAULT_SETTINGS = {
  serverUrl: 'ws://localhost:8000/ws',
  srcLang: 'vi',
  tgtLang: 'en',
  voice: 'af_heart',
  volume: 1.0,
};

let settings = { ...DEFAULT_SETTINGS };
let ws = null;
let ports = new Map();   // tabId → Port
let reconnectTimer = null;
let reconnectDelay = 1000;

// ── Settings ─────────────────────────────────────────────────────────────────

chrome.storage.sync.get(DEFAULT_SETTINGS, stored => {
  settings = { ...DEFAULT_SETTINGS, ...stored };
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'sync') return;
  for (const [key, { newValue }] of Object.entries(changes)) {
    if (key in settings) settings[key] = newValue;
  }
  // Reconnect if server URL changed
  if ('serverUrl' in changes && ws) {
    ws.close();
  }
});

// ── Keepalive alarm (fires every minute to recover stale connections) ─────────

chrome.alarms.create('keepalive', { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'keepalive' && ports.size > 0) {
    ensureWsConnected();
  }
});

// ── Port connections from content scripts ─────────────────────────────────────

chrome.runtime.onConnect.addListener(port => {
  if (port.name !== 'smartgen') return;

  const tabId = port.sender?.tab?.id;
  if (tabId == null) return;

  ports.set(tabId, port);

  port.onDisconnect.addListener(() => ports.delete(tabId));

  port.onMessage.addListener(msg => handleContentMsg(msg));

  // Tell content script current status immediately
  port.postMessage({
    type: 'ws_status',
    connected: ws?.readyState === WebSocket.OPEN,
  });

  ensureWsConnected();
});

// ── Generic REST relay (bypasses page CORS — content-script fetch() does not get
// the host_permissions CORS exemption, only the service worker's fetch does) ──────

function bufToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let binary = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type !== 'sg_fetch') return;
  (async () => {
    try {
      const resp = await fetch(msg.url, {
        method: msg.method || 'GET',
        headers: msg.headers || {},
        body: msg.body,
        signal: msg.timeoutMs ? AbortSignal.timeout(msg.timeoutMs) : undefined,
      });
      const headers = {};
      resp.headers.forEach((v, k) => { headers[k] = v; });
      if (msg.binary) {
        sendResponse({ ok: resp.ok, status: resp.status, headers, bodyB64: bufToBase64(await resp.arrayBuffer()) });
      } else {
        sendResponse({ ok: resp.ok, status: resp.status, headers, text: await resp.text() });
      }
    } catch (e) {
      sendResponse({ ok: false, status: 0, error: e.message || String(e) });
    }
  })();
  return true; // keep the message channel open for the async sendResponse above
});

// ── Content → server relay ────────────────────────────────────────────────────

function handleContentMsg(msg) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  if (msg.type === 'pcm') {
    ws.send(msg.buffer);
  } else if (msg.type === 'ext_config') {
    ws.send(JSON.stringify({
      type: 'config',
      src: msg.srcLang || settings.srcLang,
      tgt: msg.tgtLang || settings.tgtLang,
    }));
  } else if (msg.type === 'ext_stop') {
    ws.send(JSON.stringify({ type: 'stop' }));
  }
}

// ── Server → content relay ────────────────────────────────────────────────────

function broadcast(msg) {
  for (const port of ports.values()) {
    try { port.postMessage(msg); } catch (_) {}
  }
}

// ── WebSocket lifecycle ───────────────────────────────────────────────────────

function ensureWsConnected() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  connectWs();
}

function connectWs() {
  try {
    ws = new WebSocket(settings.serverUrl);
    ws.binaryType = 'arraybuffer';
  } catch (_) {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    reconnectDelay = 1000;
    broadcast({ type: 'ws_status', connected: true });
  };

  ws.onmessage = ev => {
    if (ev.data instanceof ArrayBuffer) {
      // TTS audio chunk — relay as-is (structured clone handles ArrayBuffer)
      broadcast({ type: 'audio_chunk', buffer: ev.data });
    } else {
      try {
        broadcast(JSON.parse(ev.data));
      } catch (_) {}
    }
  };

  ws.onclose = () => {
    ws = null;
    broadcast({ type: 'ws_status', connected: false });
    if (ports.size > 0) scheduleReconnect();
  };

  ws.onerror = () => ws.close();
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    if (ports.size > 0) connectWs();
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, 30000);
}
