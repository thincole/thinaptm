/**
 * ThinAPTM Flow Bridge — Side Panel (thay cho popup, ở lại cố định góc phải
 * trình duyệt để tiện theo dõi liên tục thay vì phải bấm mở lại mỗi lần).
 */

const TYPE_LABELS = {
  eb1hJf: 'TẠO VIDEO', ogiZ0b: 'TẠO ẢNH', jwpduf: 'KIỂM TRA',
  Zzl0ze: 'DANH SÁCH', as29s: 'LẤY MEDIA', maseQ: 'UPLOAD',
};

function formatType(rpcid) {
  if (!rpcid) return '—';
  const m = String(rpcid).match(/^RPC:(.+)$/);
  const id = m ? m[1] : rpcid;
  return TYPE_LABELS[id] || id;
}

function formatTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
  } catch { return '—'; }
}

function badgeHtml(status) {
  if (status === 'success') return '<span class="badge badge-ok">✓ xong</span>';
  if (status === 'failed') return '<span class="badge badge-fail">✗ lỗi</span>';
  return '<span class="badge badge-proc">⏳ đang chạy</span>';
}

function escHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderLog(entries) {
  const tbody = document.getElementById('log-body');
  document.getElementById('log-count').textContent = entries ? entries.length : 0;
  if (!entries || !entries.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="log-empty">Chưa có request nào</td></tr>';
    return;
  }
  tbody.innerHTML = entries.map((e) => `
    <tr title="${escHtml(e.error || e.responseSummary || '')}">
      <td>${formatTime(e.time)}</td>
      <td>${escHtml(formatType(e.type))}</td>
      <td>${badgeHtml(e.status)}</td>
    </tr>`).join('');
}

function refreshStatus() {
  chrome.runtime.sendMessage({ type: 'STATUS' }, (data) => {
    if (chrome.runtime.lastError || !data) return;
    document.getElementById('conn-dot').className = 'dot' + (data.connected ? ' on' : '');
    document.getElementById('s-conn').textContent = data.connected ? 'Đã kết nối bridge' : 'Chưa kết nối';
    document.getElementById('s-email').textContent = data.accountEmail || '(chưa đặt)';
    document.getElementById('s-project').textContent = data.projectId ? data.projectId.slice(0, 8) + '…' : 'Đang dò...';
    const m = data.metrics || {};
    document.getElementById('m-total').textContent = m.requestCount || 0;
    document.getElementById('m-ok').textContent = m.successCount || 0;
    document.getElementById('m-fail').textContent = m.failedCount || 0;
    const errRow = document.getElementById('s-err-row');
    if (m.lastError) {
      errRow.style.display = '';
      document.getElementById('s-err').textContent = m.lastError;
    } else {
      errRow.style.display = 'none';
    }
    if (data.accountEmail && !document.getElementById('email-input').value) {
      document.getElementById('email-input').value = data.accountEmail;
    }
  });
}

function refreshLog() {
  chrome.runtime.sendMessage({ type: 'REQUEST_LOG' }, (data) => {
    if (chrome.runtime.lastError) return;
    if (data && data.log) renderLog(data.log);
  });
}

document.getElementById('btn-save').addEventListener('click', () => {
  const email = document.getElementById('email-input').value.trim();
  if (!email) return;
  chrome.runtime.sendMessage({ type: 'SET_ACCOUNT_EMAIL', email }, () => setTimeout(refreshStatus, 400));
});

document.getElementById('btn-flow').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'OPEN_FLOW_TAB' });
});

document.getElementById('btn-reconnect').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'RECONNECT' }, () => setTimeout(refreshStatus, 400));
});

const chkAutoReload = document.getElementById('chk-autoreload');
chrome.storage.local.get(['autoReloadEnabled'], (d) => {
  chkAutoReload.checked = d.autoReloadEnabled !== false; // mặc định BẬT
});
chkAutoReload.addEventListener('change', () => {
  chrome.runtime.sendMessage({ type: 'SET_AUTORELOAD', enabled: chkAutoReload.checked });
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'STATUS_PUSH') refreshStatus();
  if (msg.type === 'REQUEST_LOG_UPDATE' && msg.log) renderLog(msg.log);
});

document.addEventListener('DOMContentLoaded', () => {
  refreshStatus();
  refreshLog();
});
setInterval(refreshStatus, 2000);
