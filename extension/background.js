/**
 * ThinAPTM Flow Bridge — Chrome Extension Background Service Worker
 *
 * Ket noi toi flow_bridge.py (nhung trong ThinAPTM, khong phai agent FastAPI
 * rieng cua FlowKit) qua WebSocket. Mint reCAPTCHA va chay batchexecute RPC
 * cua Flow ngay trong tab da dang nhap.
 *
 * Port tu extension/background.js cua du an FlowKit (E:\0 -Flowkit), rut gon:
 * - Bo hoan toan nhanh REST/Bearer cu (aisandbox-pa.googleapis.com) — Flow da
 *   ngung phat Bearer ya29 sau khi di chuyen sang flow.google.com (9/2026),
 *   nen phan proxy REST + bat token cua FlowKit la du thua cho ThinAPTM.
 * - Bo callback HTTP (sendToAgent chi con gui qua WS) — bridge cua ThinAPTM
 *   song suot phien app, khong hot-reload nhu agent FastAPI cua FlowKit nen
 *   khong can lop chiu-mat-ket-noi do.
 * - Bo khoi "telemetry gia nguoi dung" — khong ap dung cho duong batch RPC.
 * - THEM: tu nhan dien tai khoan (email) va gan vao URL WS khi ket noi — ban
 *   goc FlowKit coi moi ket noi la ngang hang/thay the cho nhau, ThinAPTM thi
 *   moi tai khoan phai luon di dung tab rieng cua no, nen can dinh danh ro.
 */

const AGENT_WS_HOST = 'ws://127.0.0.1:9333';

const flowUrls = ['https://flow.google.com/*'];
const FLOW_TAB_URL = 'https://flow.google.com/';

let ws = null;
let accountEmail = null;
let projectId = null; // Flow project id tu phat hien tu URL tab (content.js), khong phai nguoi dung go tay
let state = 'off'; // off | idle | running
let manualDisconnect = false;
let metrics = {
  requestCount: 0,   // request tieu ton captcha (gen anh/video)
  successCount: 0,
  failedCount: 0,
  lastError: null,
};

let requestLog = [];

function addRequestLog(entry) {
  requestLog.unshift(entry);
  if (requestLog.length > 100) requestLog.pop();
  broadcastRequestLog();
}

function updateRequestLog(id, updates) {
  const entry = requestLog.find((e) => e.id === id);
  if (entry) Object.assign(entry, updates);
  broadcastRequestLog();
}

function broadcastRequestLog() {
  chrome.runtime.sendMessage({ type: 'REQUEST_LOG_UPDATE', log: requestLog }).catch(() => {});
}

// ─── Khoi dong ────────────────────────────────────────────────

let initializationPromise = null;

chrome.runtime.onInstalled.addListener(() => { void ensureInitialized(); });
chrome.runtime.onStartup.addListener(() => { void ensureInitialized(); });
chrome.alarms.onAlarm.addListener(async (alarm) => {
  await ensureInitialized();
  if (alarm.name === 'reconnect') connectToAgent();
  if (alarm.name === 'keepAlive') keepAlive();
  if (alarm.name === 'tabReload' || alarm.name === 'tabReloadRetry') reloadFlowTabIfIdle();
});

// Panel cố định góc phải: bấm icon extension mở side panel thay vì popup thoáng qua.
try {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
} catch {}

// chrome.sidePanel.open() chỉ được gọi trong 1 user gesture thật (không tự mở khi
// tab load xong) — dùng phím tắt lệnh (chrome.commands) làm cổng vào, vì ThinAPTM
// tự động hoá bằng CDP Input.dispatchKeyEvent (Chrome coi là input thật, giống hệt
// cơ chế Puppeteer/Playwright dùng) ngay sau khi mở trình duyệt cho tài khoản —
// nhờ vậy panel tự hiện luôn mà không cần người dùng bấm icon thủ công.
chrome.commands.onCommand.addListener((command, tab) => {
  if (command !== 'open-panel') return;
  const windowId = tab && tab.windowId;
  if (windowId == null) return;
  chrome.sidePanel.open({ windowId }).catch(() => {});
});

function ensureInitialized() {
  if (!initializationPromise) {
    initializationPromise = initialize().catch((error) => {
      initializationPromise = null;
      console.error('[ThinAPTM Bridge] Initialization failed', error);
      throw error;
    });
  }
  return initializationPromise;
}

async function initialize() {
  const data = await chrome.storage.local.get(['accountEmail', 'metrics', 'projectId', 'autoReloadEnabled']);
  if (data.accountEmail) accountEmail = data.accountEmail;
  if (data.projectId) projectId = data.projectId;
  if (data.metrics) Object.assign(metrics, data.metrics);
  autoReloadEnabled = data.autoReloadEnabled !== false; // mặc định BẬT
  chrome.alarms.create('keepAlive', { periodInMinutes: 0.4 });
  if (autoReloadEnabled) chrome.alarms.create('tabReload', { periodInMinutes: 60 });
  if (accountEmail) connectToAgent();
  // Chua biet email thi cho content.js bao qua SET_ACCOUNT_EMAIL roi moi connect.
}

// ─── Tự F5 tab Flow mỗi 1 giờ ─────────────────────────────────
// Trang Flow là SPA Angular nặng, chạy liên tục nhiều giờ sẽ tích RAM dần
// (đặc biệt danh sách project phình theo số video đã tạo) — F5 định kỳ vừa
// giải phóng RAM vừa tự "chữa lành" nếu tab lỡ kẹt JS. KHÔNG reload khi đang
// có request chạy dở (state === 'running') — dời lại 5 phút thay vì làm gãy
// job đang xử lý.

let autoReloadEnabled = true;

async function reloadFlowTabIfIdle() {
  if (!autoReloadEnabled) return;
  if (state === 'running') {
    chrome.alarms.create('tabReloadRetry', { delayInMinutes: 5 });
    return;
  }
  try {
    const tabs = await chrome.tabs.query({ url: flowUrls });
    for (const tab of tabs) {
      if (!tab.discarded) await chrome.tabs.reload(tab.id);
    }
    if (tabs.length) console.log('[ThinAPTM Bridge] Đã tự F5 tab Flow định kỳ');
  } catch (e) {
    console.warn('[ThinAPTM Bridge] Tự F5 tab lỗi:', e);
  }
}

void ensureInitialized();

// ─── WebSocket toi flow_bridge.py ───────────────────────────────

function wsUrl() {
  return accountEmail ? `${AGENT_WS_HOST}?email=${encodeURIComponent(accountEmail)}` : AGENT_WS_HOST;
}

function connectToAgent() {
  if (!accountEmail) return; // khong connect khi chua biet dinh danh tai khoan
  if (manualDisconnect) return;
  if (ws?.readyState === WebSocket.CONNECTING) return;
  if (ws?.readyState === WebSocket.OPEN) return;

  try {
    ws = new WebSocket(wsUrl());
  } catch (e) {
    console.error('[ThinAPTM Bridge] WS connect error:', e);
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    console.log('[ThinAPTM Bridge] Connected to bridge, account =', accountEmail);
    chrome.alarms.clear('reconnect');
    setState('idle');
    // Xóa lỗi WS_ERROR/... cũ còn sót lại từ lần kết nối trước — kết nối MỚI này đã
    // thành công, hiển thị lỗi cũ ra popup là gây hiểu lầm (đã gặp thực tế: WS_ERROR
    // đỏ vẫn hiện dù "Đã kết nối bridge" xanh, vì metrics.lastError chưa từng bị xóa).
    metrics.lastError = null;
    chrome.storage.local.set({ metrics });
    ws.send(JSON.stringify({ type: 'extension_ready', email: accountEmail }));
    // Gửi lại project id đã biết (nếu có) mỗi khi (re)connect — phòng trường hợp
    // Python restart và mất hẳn state cũ, không phải chờ content.js tick tiếp mới báo lại.
    if (projectId) {
      ws.send(JSON.stringify({ type: 'project_detected', email: accountEmail, projectId }));
    }
  };

  ws.onmessage = async ({ data }) => {
    try {
      const msg = JSON.parse(data);
      if (msg.method === 'batch_rpc') {
        await handleBatchRpc(msg);
      } else if (msg.method === 'get_status') {
        sendToAgent({
          id: msg.id,
          result: { state, accountEmail, manualDisconnect, metrics },
        });
      } else if (msg.type === 'pong') {
        // keepalive response
      }
    } catch (e) {
      console.error('[ThinAPTM Bridge] Message error:', e);
    }
  };

  ws.onclose = () => {
    setState('off');
    if (!manualDisconnect) scheduleReconnect();
  };

  ws.onerror = (e) => {
    console.error('[ThinAPTM Bridge] WS error:', e);
    metrics.lastError = 'WS_ERROR';
    chrome.storage.local.set({ metrics });
  };
}

function scheduleReconnect() {
  chrome.alarms.create('reconnect', { delayInMinutes: 0.083 }); // ~5s
}

function keepAlive() {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'ping' }));
  } else {
    connectToAgent();
  }
}

function sendToAgent(msg) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

// ─── Giai reCAPTCHA ──────────────────────────────────────────

async function requestCaptchaFromTab(tabId, requestId, pageAction) {
  try {
    return await chrome.tabs.sendMessage(tabId, {
      type: 'GET_CAPTCHA',
      requestId,
      pageAction,
    });
  } catch (error) {
    const msg = error?.message || '';
    const shouldInject =
      msg.includes('Receiving end does not exist') ||
      msg.includes('Could not establish connection');
    if (!shouldInject) throw error;

    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content.js'],
    });
    await sleep(200);
    return await chrome.tabs.sendMessage(tabId, {
      type: 'GET_CAPTCHA',
      requestId,
      pageAction,
    });
  }
}

/** Chrome tu dong "discard" tab bi cho nen de tiet kiem RAM; tab van hien
 *  trong chrome.tabs.query nhung goi xuyen-context se loi. Reload de "hoi
 *  sinh" no. */
async function reviveTabIfNeeded(tab) {
  if (!tab?.discarded) return tab;
  try {
    await chrome.tabs.reload(tab.id);
    await sleep(2500);
    return await chrome.tabs.get(tab.id);
  } catch {
    return null;
  }
}

function captchaFromTab(tabId, requestId, captchaAction) {
  return Promise.race([
    requestCaptchaFromTab(tabId, requestId, captchaAction),
    new Promise((_, rej) => setTimeout(() => rej(new Error('CAPTCHA_TIMEOUT')), 30000)),
  ]);
}

async function solveCaptcha(requestId, captchaAction) {
  let tabs = await chrome.tabs.query({ url: flowUrls });
  // Ưu tiên thử các tab ĐANG Ở TRONG 1 project (/project/<uuid>) trước — trang chủ/marketing
  // (flow.google.com/about, /) không tải window.grecaptcha.enterprise nên luôn timeout 22s vô
  // ích nếu thử trước; có thể có nhiều tab flow.google.com cùng lúc (tab cũ còn sót lại từ lần
  // mở trước, hoặc do FlowKit gốc hỗ trợ nhiều tab) nên vẫn giữ fallback thử hết danh sách.
  tabs.sort((a, b) => (/\/project\//.test(b.url || '') ? 1 : 0) - (/\/project\//.test(a.url || '') ? 1 : 0));

  if (!tabs.length) {
    try {
      await chrome.tabs.create({ url: FLOW_TAB_URL, active: false });
      await sleep(3000);
      tabs = await chrome.tabs.query({ url: flowUrls });
    } catch (e) {
      return { error: e.message || 'NO_FLOW_TAB' };
    }
    if (!tabs.length) return { error: 'NO_FLOW_TAB' };
  }

  const errors = [];
  for (const candidate of tabs) {
    const tab = await reviveTabIfNeeded(candidate);
    if (!tab) continue;
    try {
      const resp = await captchaFromTab(tab.id, requestId, captchaAction);
      if (!resp?.token) {
        errors.push(resp?.error || 'NO_TOKEN');
        continue;
      }
      return resp;
    } catch (e) {
      const msg = e?.message || '';
      errors.push(msg);
      if (
        msg.includes('No current window') ||
        msg.includes('No tab with id') ||
        msg.includes('Receiving end does not exist')
      ) {
        continue;
      }
      return { error: msg };
    }
  }

  try {
    await chrome.tabs.create({ url: FLOW_TAB_URL, active: false });
    await sleep(3000);
    const fresh = await chrome.tabs.query({ url: flowUrls });
    const target = fresh.find((t) => !t.discarded) || fresh[0];
    if (!target) return { error: 'NO_FLOW_TAB' };
    return await captchaFromTab(target.id, requestId, captchaAction);
  } catch (e) {
    return { error: e?.message || errors[0] || 'NO_FLOW_TAB' };
  }
}

// ─── Chay RPC ngay trong tab (duong hien hanh) ─────────────
//
// Frontend Flow ky moi request bang cookie + token `at` theo trang, va moi
// lenh generate mang 1 reCAPTCHA dung-1-lan. Khong the replay tu ngoai tab,
// nen request phai do chinh trang Flow phat ra: mint captcha tuoi qua cau
// noi grecaptcha, roi chay POST batchexecute trong MAIN world cua trang, noi
// at / f.sid / bl dang ton tai.

const CAPTCHA_SLOT = '__CAPTCHA__';
const MAX_RPC_TEXT = 32000000; // rieng listing project da vuot 17MB

async function runBatchRpc(cmd) {
  const tabs = await chrome.tabs.query({ url: flowUrls });
  let candidate = tabs.find((t) => !t.discarded) || tabs[0];
  if (!candidate) {
    try {
      await chrome.tabs.create({ url: FLOW_TAB_URL, active: false });
      await sleep(5000);
      const fresh = await chrome.tabs.query({ url: flowUrls });
      candidate = fresh.find((t) => !t.discarded) || fresh[0];
    } catch (e) {
      return { error: e?.message || 'NO_FLOW_TAB' };
    }
    if (!candidate) return { error: 'NO_FLOW_TAB' };
  }
  const tab = await reviveTabIfNeeded(candidate);
  if (!tab) return { error: 'FLOW_TAB_DISCARDED' };

  let freq = cmd.freq;
  if (cmd.captchaAction) {
    const solved = await solveCaptcha(cmd.id, cmd.captchaAction);
    if (!solved?.token) return { error: `CAPTCHA_FAILED: ${solved?.error || 'no token'}` };
    freq = freq.split(CAPTCHA_SLOT).join(solved.token);
  }

  const [injected] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: 'MAIN',
    args: [cmd.rpcid, freq, MAX_RPC_TEXT, cmd.match || null],
    func: async (rpcid, freqStr, maxText, match) => {
      const wiz = globalThis.WIZ_global_data || {};
      const at = wiz.SNlM0e;
      const sid = wiz.FdrFJe;
      const bl = wiz.cfb2h;
      if (!at) return { error: 'NO_AT_TOKEN' };
      const reqid = Math.floor(Math.random() * 900000) + 100000;
      const url =
        `/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=${encodeURIComponent(rpcid)}` +
        `&f.sid=${encodeURIComponent(sid || '')}&bl=${encodeURIComponent(bl || '')}` +
        `&hl=en-AU&_reqid=${reqid}&rt=c`;
      const resp = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'content-type': 'application/x-www-form-urlencoded;charset=UTF-8',
          'x-same-domain': '1',
        },
        body: new URLSearchParams({ 'f.req': freqStr, at }),
      });
      const text = await resp.text();
      if (match) {
        const found = text.indexOf(match);
        return {
          status: resp.status,
          matched: found !== -1,
          text: found === -1 ? '' : text.slice(found, found + 800),
        };
      }
      return { status: resp.status, text: text.slice(0, maxText) };
    },
  });

  return injected?.result || { error: 'NO_INJECTION_RESULT' };
}

async function handleBatchRpc(msg) {
  const { id, params } = msg;
  const { rpcid, freq, captchaAction, match } = params || {};
  if (!rpcid || !freq) {
    sendToAgent({ id, status: 400, error: 'INVALID_BATCH_RPC' });
    return;
  }

  setState('running');
  const hasCaptcha = !!captchaAction;
  if (hasCaptcha) metrics.requestCount++;
  const visible = hasCaptcha;
  if (visible) {
    addRequestLog({
      id, type: `RPC:${rpcid}`, time: new Date().toISOString(),
      status: 'processing', error: null, url: rpcid,
      payloadSummary: freq.slice(0, 200),
    });
  }

  try {
    const out = await runBatchRpc({ id, rpcid, freq, captchaAction, match });
    if (out.error) {
      if (hasCaptcha) { metrics.failedCount++; metrics.lastError = out.error; }
      if (visible) updateRequestLog(id, { status: 'failed', error: out.error });
      sendToAgent({ id, status: 502, error: out.error });
    } else {
      if (hasCaptcha) { metrics.successCount++; metrics.lastError = null; }
      if (visible) {
        updateRequestLog(id, {
          status: 'success', httpStatus: out.status,
          responseSummary: (out.text || '').slice(0, 300),
        });
      }
      sendToAgent({ id, status: out.status, data: out.text });
    }
  } catch (e) {
    const err = e?.message || 'BATCH_RPC_FAILED';
    if (hasCaptcha) { metrics.failedCount++; metrics.lastError = err; }
    if (visible) updateRequestLog(id, { status: 'failed', error: err });
    sendToAgent({ id, status: 500, error: err });
  }

  chrome.storage.local.set({ metrics });
  setState('idle');
}

// ─── Trang thai & Popup ──────────────────────────────────────

function setState(newState) {
  state = newState;
  const badges = { idle: '●', running: '▶', off: '○' };
  const colors = { idle: '#22c55e', running: '#f59e0b', off: '#6b7280' };
  chrome.action.setBadgeText({ text: badges[state] || '' });
  chrome.action.setBadgeBackgroundColor({ color: colors[state] || '#000' });
  broadcastStatus();
}

function broadcastStatus() {
  chrome.runtime.sendMessage({ type: 'STATUS_PUSH' }).catch(() => {});
}

chrome.runtime.onMessage.addListener((msg, _, reply) => {
  if (msg.type === 'SET_ACCOUNT_EMAIL' && msg.email) {
    const changed = accountEmail !== msg.email;
    accountEmail = msg.email;
    chrome.storage.local.set({ accountEmail });
    if (changed) {
      manualDisconnect = false;
      try { ws?.close(); } catch {}
      connectToAgent();
    }
    reply({ ok: true });
    return true;
  }

  if (msg.type === 'PROJECT_DETECTED' && msg.projectId) {
    const changed = projectId !== msg.projectId;
    projectId = msg.projectId;
    chrome.storage.local.set({ projectId });
    if (ws?.readyState === WebSocket.OPEN && accountEmail) {
      ws.send(JSON.stringify({ type: 'project_detected', email: accountEmail, projectId }));
    }
    if (changed) console.log('[ThinAPTM Bridge] Project id =', projectId);
    reply({ ok: true });
    return true;
  }

  if (msg.type === 'PROJECT_AUTOCREATE_FAILED') {
    metrics.lastError = msg.note || 'PROJECT_AUTOCREATE_FAILED';
    chrome.storage.local.set({ metrics });
    console.warn('[ThinAPTM Bridge]', metrics.lastError);
    reply({ ok: true });
    return true;
  }

  if (msg.type === 'SET_AUTORELOAD') {
    autoReloadEnabled = !!msg.enabled;
    chrome.storage.local.set({ autoReloadEnabled });
    if (autoReloadEnabled) {
      chrome.alarms.create('tabReload', { periodInMinutes: 60 });
    } else {
      chrome.alarms.clear('tabReload');
      chrome.alarms.clear('tabReloadRetry');
    }
    reply({ ok: true });
    return true;
  }

  if (msg.type === 'STATUS') {
    reply({
      connected: ws?.readyState === WebSocket.OPEN,
      accountEmail,
      projectId,
      manualDisconnect,
      metrics: {
        requestCount: metrics.requestCount,
        successCount: metrics.successCount,
        failedCount: metrics.failedCount,
        lastError: metrics.lastError,
      },
      state,
    });
    return true;
  }

  if (msg.type === 'DISCONNECT') {
    manualDisconnect = true;
    if (ws) ws.close();
    reply({ ok: true });
    return true;
  }

  if (msg.type === 'RECONNECT') {
    manualDisconnect = false;
    connectToAgent();
    reply({ ok: true });
    return true;
  }

  if (msg.type === 'REQUEST_LOG') {
    reply({ log: requestLog });
    return true;
  }

  if (msg.type === 'OPEN_FLOW_TAB') {
    chrome.tabs.query({ url: flowUrls }).then((tabs) => {
      if (tabs.length) {
        chrome.tabs.update(tabs[0].id, { active: true });
        reply({ ok: true, tabId: tabs[0].id });
      } else {
        chrome.tabs.create({ url: FLOW_TAB_URL })
          .then((tab) => reply({ ok: true, tabId: tab.id }))
          .catch((e) => reply({ error: e.message }));
      }
    }).catch((e) => reply({ error: e.message }));
    return true;
  }

  return true;
});

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

console.log('[ThinAPTM Bridge] Extension loaded');
