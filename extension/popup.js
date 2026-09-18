/**
 * Popup ThinAPTM Flow Bridge — cho người dùng tự nhập email tài khoản 1 lần
 * mỗi Chrome profile (thiết lập thủ công: người dùng tự đăng nhập Flow +
 * tự cài extension này, KHÔNG có launcher Python điều hướng URL kèm email
 * như phương án tự động hóa cũ).
 */

function fmtAge(ms) {
  if (!ms) return '';
  const m = Math.round(ms / 60000);
  return m < 1 ? '<1 phút' : `${m} phút`;
}

function refreshStatus() {
  chrome.runtime.sendMessage({ type: 'STATUS' }, (data) => {
    if (chrome.runtime.lastError || !data) return;
    document.getElementById('conn-dot').className = 'dot' + (data.connected ? ' on' : '');
    const box = document.getElementById('status-box');
    const m = data.metrics || {};
    box.innerHTML = `
      <div>Trạng thái: <b>${data.connected ? 'Đã kết nối bridge' : 'Chưa kết nối'}</b></div>
      <div>Tài khoản: <b>${data.accountEmail || '(chưa đặt)'}</b></div>
      <div>Yêu cầu: <b>${m.requestCount || 0}</b> | OK: <b>${m.successCount || 0}</b> | Lỗi: <b>${m.failedCount || 0}</b></div>
      ${m.lastError ? `<div style="color:#f87171">Lỗi gần nhất: ${m.lastError}</div>` : ''}
    `;
    if (data.accountEmail && !document.getElementById('email-input').value) {
      document.getElementById('email-input').value = data.accountEmail;
    }
  });
}

document.getElementById('btn-save').addEventListener('click', () => {
  const email = document.getElementById('email-input').value.trim();
  if (!email) return;
  const btn = document.getElementById('btn-save');
  btn.textContent = 'Đang lưu...';
  chrome.runtime.sendMessage({ type: 'SET_ACCOUNT_EMAIL', email }, () => {
    btn.textContent = 'Lưu & Kết nối';
    setTimeout(refreshStatus, 500);
  });
});

document.getElementById('btn-flow').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'OPEN_FLOW_TAB' });
});

document.getElementById('btn-reconnect').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'RECONNECT' }, () => {
    setTimeout(refreshStatus, 500);
  });
});

document.addEventListener('DOMContentLoaded', refreshStatus);
setInterval(refreshStatus, 2000);
