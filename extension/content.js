/**
 * Content script — cau noi giua background.js va injected.js.
 * Inject injected.js vao MAIN world de dung duoc window.grecaptcha.
 * Port tu FlowKit, THEM 1 doan rieng cua ThinAPTM: doc email tai khoan tu
 * URL launcher Python da dieu huong toi (?_tam_email=...), bao 1 lan cho
 * background.js de no tu nhan dien dung tai khoan khi ket noi bridge —
 * ban goc FlowKit khong can cai nay vi coi moi ket noi la ngang hang nhau,
 * ThinAPTM thi 1 tai khoan phai luon di dung tab cua chinh no.
 */
(function () {
  const s = document.createElement('script');
  s.src = chrome.runtime.getURL('injected.js');
  s.onload = () => s.remove();
  (document.head || document.documentElement).appendChild(s);
})();

// --- Bao email tai khoan cho background.js (chi 1 lan, neu URL co tham so) ---
try {
  const params = new URLSearchParams(window.location.search);
  const email = params.get('_tam_email');
  if (email) {
    chrome.runtime.sendMessage({ type: 'SET_ACCOUNT_EMAIL', email }).catch(() => {});
  }
} catch {}

// --- Tu phat hien Flow project UUID tu URL tab + tu bam "Du an moi" neu dang
// o man hinh chinh (chua vao project nao) — KHONG can nguoi dung tu tay copy
// UUID dan vao accounts.json, va moi lan chay lai deu tu nhan dung project
// hien tai (hoac tu tao moi neu dang o man hinh chinh). ---
(function () {
  const PROJECT_RE = /\/project\/([0-9a-fA-F-]{36})/;
  // Da thu nhieu ngon ngu vi giao dien Flow doi theo tai khoan/khu vuc.
  const NEW_PROJECT_RE = /dự án mới|du an moi|new project|nouveau projet|nuevo proyecto|neues projekt|新規プロジェクト|새 프로젝트|新项目/i;
  let lastProjectId = null;
  let clickAttempts = 0;
  const MAX_CLICK_ATTEMPTS = 6; // ~ 6 x 5s = 30s trước khi bỏ cuộc, báo lỗi rõ ràng

  function reportProjectId(pid) {
    if (!pid || pid === lastProjectId) return;
    lastProjectId = pid;
    clickAttempts = 0;
    chrome.runtime.sendMessage({ type: 'PROJECT_DETECTED', projectId: pid }).catch(() => {});
  }

  function findNewProjectButton() {
    const nodes = document.querySelectorAll('button, [role="button"], a, div, span');
    for (const el of nodes) {
      const text = (el.textContent || '').trim();
      if (text && text.length <= 40 && NEW_PROJECT_RE.test(text)) {
        return el;
      }
    }
    return null;
  }

  function tick() {
    const m = window.location.pathname.match(PROJECT_RE);
    if (m) {
      reportProjectId(m[1]);
      return;
    }
    // Chưa vào project nào — đang ở màn hình chính. Tự bấm "Dự án mới", thử lại
    // vài lần (Angular có thể chưa render kịp lúc đầu, hoặc lần bấm đầu không
    // trúng đúng nút) trước khi bỏ cuộc và báo lỗi rõ ràng cho người dùng tự bấm.
    if (clickAttempts >= MAX_CLICK_ATTEMPTS) return;
    const btn = findNewProjectButton();
    if (btn) {
      clickAttempts++;
      try { btn.click(); } catch {}
      if (clickAttempts >= MAX_CLICK_ATTEMPTS) {
        chrome.runtime.sendMessage({
          type: 'PROJECT_AUTOCREATE_FAILED',
          note: `Đã thử bấm "Dự án mới" ${MAX_CLICK_ATTEMPTS} lần nhưng URL không đổi sang /project/<uuid> — vào flow.google.com tự bấm tạo project thủ công 1 lần.`,
        }).catch(() => {});
      }
    }
  }

  // Chỉ tự dò/tự tạo project cho tab THẬT SỰ do ThinAPTM mở (đã từng biết accountEmail — qua
  // _tam_email trên URL hoặc người dùng tự nhập ở side panel). Extension giờ được nạp vào MỌI
  // phiên Chrome (kể cả các phiên login.py chỉ dùng để lấy cookie, không có _tam_email) — nếu
  // không chặn, tab đăng nhập thường cũng sẽ bị tự bấm "Dự án mới" một cách không mong muốn.
  try {
    chrome.storage.local.get(['accountEmail'], (data) => {
      if (data && data.accountEmail) {
        tick();
        setInterval(tick, 5000);
      }
    });
  } catch {}
})();

chrome.runtime.onMessage.addListener((msg, _, reply) => {
  if (msg.type !== 'GET_CAPTCHA') return;

  const { requestId, pageAction } = msg;

  const handler = (e) => {
    if (e.detail?.requestId === requestId) {
      window.removeEventListener('CAPTCHA_RESULT', handler);
      clearTimeout(timer);
      reply({ token: e.detail.token, error: e.detail.error });
    }
  };

  const timer = setTimeout(() => {
    window.removeEventListener('CAPTCHA_RESULT', handler);
    reply({ error: 'CONTENT_TIMEOUT' });
  }, 25000);

  window.addEventListener('CAPTCHA_RESULT', handler);

  window.dispatchEvent(new CustomEvent('GET_CAPTCHA', {
    detail: { requestId, pageAction },
  }));

  return true; // giu channel mo cho reply bat dong bo
});
