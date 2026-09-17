"""
browser_stealth.py — Bo cong cu Chong Nhan Dien Bot (Stealth) & Hooking botoxSign cho Google Flow
Phan tich va trich xuat truc tiep tu TstGoogleFlow v1.0.6 moi nhat (DgtAutoGenerateVideoAI.dll).

Cac tinh nang cot loi:
1. Stealth Script (Real Browser Fingerprint):
   - Xoa co navigator.webdriver (tra ve undefined).
   - Gia lap 5 plugin Chrome PDF chuan.
   - Chuan hoa ngon ngu: navigator.languages = ['en-US', 'en'].
   - Unmask GPU WebGL/WebGL2: Intel Inc. / Intel(R) Iris(TM) Graphics 6100 (tranh bi phat hien SwiftShader/headless).
   - Gia lap window.chrome.runtime (OnInstalledReason, PlatformArch, PlatformOs).
   - Mock Notification.permission.

2. BotoxSign Hooking:
   - Bat va va webpack chunks cua Google Flow:
     Regex: `\\(0,([A-Za-z_$][\\w$]*)\\.botoxSign\\)\\(`
     Thay the: `(window.dgtSign=(0,$1.botoxSign))(`
   - Ham tien ich get_botox_signature() de lay chu ky hop le khi can.
"""
import re
import base64
import logging

logger = logging.getLogger("browser_stealth")

# ══════════════════════════════════════════════════════════════════════
# 1. BỘ SCRIPT CHỐNG PHÁT HIỆN BOT (REAL BROWSER STEALTH - V1.0.6)
# ══════════════════════════════════════════════════════════════════════

STEALTH_SCRIPT = """
(() => {
  // 1. Gỡ bỏ hoàn toàn cờ webdriver
  try {
    Object.defineProperty(navigator, 'webdriver', {
      get: () => undefined,
      configurable: true
    });
  } catch (_) {}

  // 2. Giả lập danh sách 5 Chrome PDF plugins chuẩn người dùng thật
  try {
    const fakePlugins = [
      { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
      { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
      { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
      { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: '' }
    ];
    Object.defineProperty(navigator, 'plugins', {
      get: () => fakePlugins,
      configurable: true
    });
  } catch (_) {}

  // 3. Chuẩn hóa ngôn ngữ trình duyệt sang US/English
  try {
    Object.defineProperty(navigator, 'languages', {
      get: () => ['en-US', 'en'],
      configurable: true
    });
  } catch (_) {}

  // 4. Mock window.navigator.permissions cho notifications
  try {
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (origQuery) {
      window.navigator.permissions.query = p =>
        p && p.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission, onchange: null })
          : origQuery.call(window.navigator.permissions, p);
    }
  } catch (_) {}

  // 5. Giả lập đối tượng window.chrome.runtime chuẩn Chrome desktop
  try {
    window.chrome = window.chrome || {};
    if (!window.chrome.runtime) {
      window.chrome.runtime = {
        OnInstalledReason: { CHROME_UPDATE: 'chrome_update' },
        PlatformArch: { X86_64: 'x86-64' },
        PlatformOs: { WIN: 'win' }
      };
    }
  } catch (_) {}

  // 6. Fake WebGL / WebGL2 Unmasked Vendor & Renderer (Intel Iris 6100)
  // Ngăn Google nhận diện môi trường ảo hóa SwiftShader hoặc driver headless
  try {
    const fakeVendor = 'Intel Inc.';
    const fakeRenderer = 'Intel(R) Iris(TM) Graphics 6100';
    if (typeof WebGLRenderingContext !== 'undefined') {
      const gp1 = WebGLRenderingContext.prototype.getParameter;
      WebGLRenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return fakeVendor;
        if (p === 37446) return fakeRenderer;
        return gp1.apply(this, arguments);
      };
    }
    if (typeof WebGL2RenderingContext !== 'undefined') {
      const gp2 = WebGL2RenderingContext.prototype.getParameter;
      WebGL2RenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return fakeVendor;
        if (p === 37446) return fakeRenderer;
        return gp2.apply(this, arguments);
      };
    }
  } catch (_) {}

  // 7. Chuẩn hóa Notification.permission không bị denied
  try {
    if (Notification.permission === 'denied') {
      Object.defineProperty(Notification, 'permission', {
        get: () => 'default',
        configurable: true
      });
    }
  } catch (_) {}

  // 8. Chuẩn bị biến toàn cục nhận chữ ký dgtSign
  try {
    if (typeof window.dgtSign === 'undefined') {
      window.dgtSign = null;
    }
  } catch (_) {}
})();
"""

# ══════════════════════════════════════════════════════════════════════
# 2. CẤU HÌNH VÁ CHUNK BOTOXSIGN (TstGoogleFlow v1.0.6)
# ══════════════════════════════════════════════════════════════════════

# Pattern regex chuẩn từ string [1845] của bản 1.0.6
BOTOX_PATCH_PATTERN = re.compile(r'\(0,\s*([A-Za-z_$][\w$]*)\.botoxSign\)\(')
# Replacement string từ [1847]
BOTOX_PATCH_REPLACEMENT = r'(window.dgtSign=(0,\1.botoxSign))('


def apply_stealth(page, log_fn=None):
    """Inject stealth script vào trình duyệt qua CDP trước khi load bất kỳ trang nào.
    
    Đảm bảo chạy trước mọi đoạn script của Google Flow / reCAPTCHA.
    """
    if not page:
        return False
    try:
        # Cách 1: CDP Page.addScriptToEvaluateOnNewDocument (hoạt động cho mọi navigation mới)
        page.run_cdp("Page.addScriptToEvaluateOnNewDocument", source=STEALTH_SCRIPT)
        # Cách 2: Chạy trực tiếp trong context hiện tại phòng trường hợp trang đã load
        try:
            page.run_js(STEALTH_SCRIPT)
        except Exception:
            pass
        if log_fn:
            log_fn("🛡️ [Stealth] Đã nạp cấu hình vân tay người dùng thật (Intel Iris 6100, 5 Plugins, No-Webdriver)")
        return True
    except Exception as e:
        # Fallback run_js nếu CDP không khả dụng
        try:
            page.run_js(STEALTH_SCRIPT)
            return True
        except Exception:
            if log_fn:
                log_fn(f"⚠️ [Stealth] Lỗi nạp script stealth: {e}")
            return False


def prime_proxy_auth(page, user, pwd, log_fn=None, probe_url="http://www.gstatic.com/generate_204", timeout=10):
    """Xác thực proxy (Basic auth) ĐÚNG MỘT LẦN qua CDP, rồi TẮT intercept.

    Chrome cache credentials proxy cho cả phiên sau lần trả lời đầu, nên các request sau (kể cả
    trang nặng như flow.google.com) không cần intercept nữa → không làm chậm/kẹt trang.
    KHÔNG intercept lâu dài mọi request (đó là thứ làm reCAPTCHA không load được).
    Trả True nếu đã xử lý được ít nhất 1 auth challenge (hoặc probe xong)."""
    if not page or not hasattr(page, "driver") or not page.driver:
        return False
    done = {"auth": False}

    def _on_auth(**params):
        rid = params.get("requestId")
        try:
            page.run_cdp("Fetch.continueWithAuth", requestId=rid, authChallengeResponse={
                "response": "ProvideCredentials", "username": user, "password": (pwd or "")})
            done["auth"] = True
        except Exception:
            pass

    def _on_req(**params):
        rid = params.get("requestId")
        if rid:
            try:
                page.run_cdp("Fetch.continueRequest", requestId=rid)
            except Exception:
                pass

    try:
        page.driver.set_callback("Fetch.authRequired", _on_auth)
        page.driver.set_callback("Fetch.requestPaused", _on_req)
        page.run_cdp("Fetch.enable", handleAuthRequests=True, patterns=[{"urlPattern": "*", "requestStage": "Request"}])
        try:
            page.get(probe_url)
        except Exception:
            pass
        import time as _t
        t0 = _t.time()
        while _t.time() - t0 < timeout and not done["auth"]:
            _t.sleep(0.3)
    finally:
        try:
            page.run_cdp("Fetch.disable")
        except Exception:
            pass
        try:
            page.driver.set_callback("Fetch.authRequired", None)
            page.driver.set_callback("Fetch.requestPaused", None)
        except Exception:
            pass
    if log_fn:
        log_fn(f"🔐 [Proxy] {'Đã xác thực proxy' if done['auth'] else 'Probe proxy xong (không thấy auth challenge)'}")
    return True


def setup_botox_hook(page, log_fn=None):
    """Kích hoạt CDP Fetch Interception để tự động vá (patch) chunk JS chứa botoxSign
    thành `(window.dgtSign=(0,$1.botoxSign))(` theo chuẩn TstGoogleFlow v1.0.6.
    """
    if not page or not hasattr(page, "driver") or not page.driver:
        return False

    def _on_request_paused(**params):
        request_id = params.get("requestId")
        if not request_id:
            return
        request = params.get("request", {})
        url = request.get("url", "")
        try:
            # Kiểm tra URL có phải là script chunk của Google Flow không
            is_flow_script = ("flow.google.com" in url or "labs.google" in url) and any(
                kw in url for kw in (".js", "chunk", "main")
            )
            if is_flow_script:
                try:
                    res_body = page.run_cdp("Fetch.getResponseBody", requestId=request_id)
                    body = res_body.get("body", "")
                    is_b64 = res_body.get("base64Encoded", False)
                    raw_text = base64.b64decode(body).decode("utf-8", errors="ignore") if is_b64 else body

                    if ".botoxSign" in raw_text:
                        patched_text, count = BOTOX_PATCH_PATTERN.subn(BOTOX_PATCH_REPLACEMENT, raw_text)
                        if count > 0:
                            if log_fn:
                                log_fn(f"⚡ [BotoxSign Hook] Đã vá {count} điểm botoxSign trong {url[-35:]}")
                            encoded = base64.b64encode(patched_text.encode("utf-8")).decode("ascii")
                            headers = params.get("responseHeaders", [])
                            status = params.get("responseStatusCode", 200)
                            page.run_cdp(
                                "Fetch.fulfillRequest",
                                requestId=request_id,
                                responseCode=status,
                                responseHeaders=headers,
                                body=encoded
                            )
                            return
                except Exception:
                    pass

            # Nếu không match hoặc có lỗi -> tiếp tục request bình thường
            page.run_cdp("Fetch.continueRequest", requestId=request_id)
        except Exception:
            try:
                page.run_cdp("Fetch.continueRequest", requestId=request_id)
            except Exception:
                pass

    try:
        page.driver.set_callback("Fetch.requestPaused", _on_request_paused)
        page.run_cdp("Fetch.enable", patterns=[
            {"urlPattern": "*flow.google.com*.js*", "requestStage": "Response"},
            {"urlPattern": "*labs.google*.js*", "requestStage": "Response"}
        ])
        if log_fn:
            log_fn("🛡️ [BotoxSign] Đã kích hoạt CDP Fetch interception tự động vá botoxSign.")
        return True
    except Exception as e:
        if log_fn:
            log_fn(f"⚠️ [BotoxSign] Không thể kích hoạt Fetch interception: {e}")
        return False


def get_botox_signature(page, url, method="POST"):
    """Thực thi JS lấy chữ ký botoxSign từ window.dgtSign theo chuẩn TstGoogleFlow v1.0.6 (string 1913)."""
    if not page:
        return None
    js_code = f"""
    (async () => {{
      try {{
        if (typeof window.dgtSign === 'function') {{
          var v = await window.dgtSign({{ url: "{url}", method: "{method}" }});
          if (v) return v;
        }}
      }} catch (e) {{}}
      return null;
    }})();
    """
    try:
        res = page.run_js(js_code)
        return res
    except Exception:
        return None
