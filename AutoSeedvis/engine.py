"""
Thìn Aptm — Engine tạo VIDEO + ẢNH Google Flow bằng android_bypass.
HTTP client: pyreqwest_impersonate (TLS giống AutoVeo3) → fallback curl_cffi.
Auth: cookie labs.google -> bearer. Video: submit -> poll -> tải mp4.
"""
import json, time, base64, os, uuid, urllib.parse, threading

# ── TLS Impersonation: ưu tiên pyreqwest_impersonate (Rust, TLS chuẩn Chrome như AutoVeo3) ──
# AutoVeo3 dùng pyreqwest_impersonate qua ai_transport.pyd (193KB) → TLS ClientHello giống hệt Chrome.
# Fallback curl_cffi nếu chưa cài pyreqwest_impersonate.
_USE_PYREQWEST = False
try:
    import pyreqwest_impersonate as pri
    _USE_PYREQWEST = True
except ImportError:
    pri = None
from curl_cffi import requests as cffi

# --- Global Proxy Auth Guard ---
ON_PROXY_ERROR_CALLBACK = None

def _check_n_handle_proxy_error(err_str, proxy):
    if not proxy:
        return
    # kiểm tra xem có phải lỗi proxy 407/tunnel failed không
    if "407" in err_str or "tunnel failed" in err_str.lower():
        if ON_PROXY_ERROR_CALLBACK:
            try:
                ON_PROXY_ERROR_CALLBACK(proxy)
            except Exception:
                pass

# Bọc các request để bắt lỗi proxy toàn cục
_orig_get = cffi.get
_orig_post = cffi.post
_orig_delete = cffi.delete

def _wrap_req(fn):
    def wrapper(*args, **kwargs):
        proxy = kwargs.get("proxies")
        try:
            r = fn(*args, **kwargs)
            if hasattr(r, "status_code") and r.status_code == 407:
                _check_n_handle_proxy_error("status 407", proxy)
            return r
        except Exception as e:
            err_msg = str(e)
            if "407" in err_msg or "tunnel failed" in err_msg.lower():
                _check_n_handle_proxy_error(err_msg, proxy)
            raise e
    return wrapper

cffi.get = _wrap_req(_orig_get)
cffi.post = _wrap_req(_orig_post)
cffi.delete = _wrap_req(_orig_delete)

# ── Session HTTP tái sử dụng THEO TỪNG THREAD (không chia sẻ 1 Session giữa nhiều thread) ──
# curl_cffi.Session không đảm bảo an toàn khi nhiều thread cùng dùng 1 Session để gọi đồng thời
# (mỗi request module-level cffi.get/post trước đây tự mở kết nối mới, tốn TLS handshake lặp lại
# nhất là với poll_video gọi lặp mỗi 5-20s). Mỗi thread tự giữ Session riêng theo chữ ký proxy,
# vẫn tái sử dụng kết nối cho các lệnh gọi tuần tự trong cùng 1 worker mà không có rủi ro race.
_thread_local_sessions = threading.local()

def _proxy_sig(proxy):
    if not proxy:
        return None
    if isinstance(proxy, dict):
        return proxy.get("http") or proxy.get("https") or str(sorted(proxy.items()))
    return str(proxy)

def _get_session(proxy=None, bucket="web"):
    """Session HTTP tái sử dụng theo (thread, bucket, proxy).

    `bucket` tách cookie jar: "web" cho luồng đăng nhập/cookie (labs.google, accounts.google.com,
    boq_execute — jar chứa cookie Google thật), "api" cho REST aisandbox (xác thực bằng Bearer),
    để request API không mang theo cookie đăng nhập không cần thiết.

    Mọi request qua session PHẢI truyền **_kw(): session giữ keep-alive, một request thiếu
    "impersonate" sẽ mở connection với TLS fingerprint lệch, và các request sau tái dùng connection đó.
    """
    cache = getattr(_thread_local_sessions, "cache", None)
    if cache is None:
        cache = {}
        _thread_local_sessions.cache = cache
    key = (bucket, _proxy_sig(proxy))
    sess = cache.get(key)
    if sess is None:
        sess = cffi.Session()
        sess.get = _wrap_req(sess.get)
        sess.post = _wrap_req(sess.post)
        cache[key] = sess
    return sess


def _api_session(proxy=None):
    """Session cho REST API aisandbox-pa.googleapis.com (xác thực bằng Bearer)."""
    return _get_session(proxy, bucket="api")

# ── Chặn memory leak cho các cache toàn cục chạy 24/7 ──
# Các cache theo cookie/token (_wiz_cache, _session_token_cache, _tier_cache, _refresh_locks) không
# bao giờ tự dọn entry cũ khi cookie đổi/tài khoản bị xoá — với app chạy liên tục nhiều ngày, dict
# này phình to vô hạn. Giới hạn kích thước, evict entry cũ nhất khi vượt ngưỡng.
_CACHE_MAX_SIZE = 500

def _cache_put_ts(cache, lock, key, value, max_size=_CACHE_MAX_SIZE):
    """Ghi vào cache dict có field 'ts' trong value, evict entry có 'ts' cũ nhất khi vượt max_size."""
    with lock:
        cache[key] = value
        if len(cache) > max_size:
            oldest_key = min(cache, key=lambda k: cache[k].get("ts", 0) if isinstance(cache[k], dict) else 0)
            if oldest_key != key:
                cache.pop(oldest_key, None)

BASE = "https://aisandbox-pa.googleapis.com/v1"
KEY = "AIzaSyBtrm0o5ab1c-Ec8ZuLcGt3oJAA5VWt3pY"
FLOW_BASE = "https://flow.google.com"
FLOW_BATCHEXECUTE = f"{FLOW_BASE}/_/AiSandboxAngularFrontend/data/batchexecute"
RECAPTCHA_SITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
RECAPTCHA_ACTION = "VIDEO_GENERATION"
UA_FF = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) Gecko/20100101 Firefox/151.0"
UA_CH = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
BYPASS_TOKEN = "android_bypass"
APP_ANDROID = "RECAPTCHA_APPLICATION_TYPE_ANDROID"
IMP = "chrome_131"  # pyreqwest_impersonate dùng version cụ thể
IMP_CFFI = "chrome110"  # curl_cffi: dùng version cụ thể (chrome110 hỗ trợ rộng)
# Kiểm tra IMP_CFFI có được build hiện tại hỗ trợ hay không — tra cứu OFFLINE trong danh sách
# target của curl_cffi, KHÔNG gửi request mạng lúc import (chậm khởi động + fail khi offline).
def _cffi_target_supported(name):
    try:
        from curl_cffi.requests import BrowserType
        return name in {m.value for m in BrowserType}
    except Exception:
        pass
    try:
        import typing
        from curl_cffi.requests.impersonate import BrowserTypeLiteral
        return name in set(typing.get_args(BrowserTypeLiteral))
    except Exception:
        return True   # không tra được → cứ giữ nguyên, request đầu tiên sẽ tự báo lỗi

if not _cffi_target_supported(IMP_CFFI):
    IMP_CFFI = "chrome"  # fallback generic

# MỌI endpoint aisandbox-pa.googleapis.com BẮT BUỘC có ?key= — thiếu key thì Google Frontend
# từ chối ngay ở tầng định tuyến và trả về trang HTML "Error 400 (Bad Request)!!1" (không phải lỗi JSON).
GEN_T2V = f"{BASE}/video:batchAsyncGenerateVideoText?key={KEY}"
GEN_I2V = f"{BASE}/video:batchAsyncGenerateVideoReferenceImages?key={KEY}"
# XÁC MINH THẬT bằng kỹ thuật 404 (endpoint bịa) vs 400 JSON (endpoint thật) — xem submit_video_start_end_rest/extend_video_rest
GEN_START_END = f"{BASE}/video:batchAsyncGenerateVideoStartAndEndImage?key={KEY}"
GEN_EXTEND = f"{BASE}/video:batchAsyncGenerateVideoExtendVideo?key={KEY}"
CHECK = f"{BASE}/video:batchCheckAsyncVideoGenerationStatus?key={KEY}"

VID_ASPECTS = {"Dọc 9:16 (TikTok)": "VIDEO_ASPECT_RATIO_PORTRAIT", "Ngang 16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE"}
IMG_ASPECTS = {"Dọc 9:16 (TikTok)": "IMAGE_ASPECT_RATIO_PORTRAIT", "Ngang 16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE", "Vuông 1:1": "IMAGE_ASPECT_RATIO_SQUARE"}
VID_MODELS = {
    "Veo 3.1 (miễn phí)": "veo_3_1_t2v_lite_low_priority",
    "⚡ Omni Flash (Credit, 8s)": "abra_i2v_8s",
    "⚡ Omni Flash (Credit, 10s)": "abra_i2v_10s",
}
VID_I2V_MODELS = {
    "veo_3_1": "veo_3_1_r2v_lite_low_priority",
    "abra": None,  # Omni Flash: abra_i2v đã là i2v sẵn, không cần đổi model
}
VID_I2V_MODEL = "veo_3_1_r2v_lite_low_priority"

# Model dự phòng khi model MIỄN PHÍ báo hết hạn mức trong ngày (autoveo3.md §5.3 "model rotation
# fallback"): tự thử model Omni Flash (TỐN CREDIT) thay vì cách ly cả tài khoản 2 giờ ngay lập tức.
# MẶC ĐỊNH TẮT (submit_video(..., allow_model_fallback=True) để bật) vì đây là quyết định tốn tiền thật,
# không nên tự động âm thầm chuyển sang model trả phí mà không hỏi.
MODEL_FALLBACK = {
    "veo_3_1_t2v_lite_low_priority": "abra_i2v_8s",
    "veo_3_1_r2v_lite_low_priority": "abra_i2v_8s",
}

# Mô tả giọng nói cố định — gắn vào cuối mọi prompt để giữ giọng nhất quán giữa các video
# Đặt chuỗi rỗng "" để tắt.
VOICE_DESC = ""

VOICE_PRESETS = {
    "vi": "Narrated by a young Vietnamese woman, approximately 20 years old, with a deep, powerful, and authoritative voice speaking in Vietnamese",
    "id": "Narrated by a young Indonesian woman, approximately 20 years old, with a deep, powerful, and authoritative voice speaking in Bahasa Indonesia",
    "my": "Narrated by a young Malaysian man, approximately 25 years old, with a clear, engaging, and authoritative voice speaking in Bahasa Melayu",
    "ph": "Narrated by a young Filipino woman, approximately 20 years old, with a deep, powerful, and authoritative voice speaking in Filipino (Tagalog)",
    "en": "Narrated by a young woman, approximately 20 years old, with a deep, powerful, and authoritative voice speaking in clear, natural English",
}

def get_voice_for_lang(lang_code):
    """Trả về mô tả giọng nói preset theo mã ngôn ngữ (vi/id/en)."""
    return VOICE_PRESETS.get(lang_code, VOICE_PRESETS["vi"])

ERROR_LOG_FUNC = None

# ── Debug API trace ──
# Mặc định TẮT. Trước đây mọi lệnh submit_video đều ghi vào debug_api.txt không giới hạn
# → file phình tới hàng chục GB khi chạy 24/7. Bật bằng biến môi trường THINAPTM_DEBUG_API=1
# hoặc gán engine.DEBUG_API = True. Khi bật, file tự xoay vòng ở DEBUG_API_MAX_BYTES.
DEBUG_API = os.environ.get("THINAPTM_DEBUG_API", "").strip() in ("1", "true", "True", "yes")
DEBUG_API_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_api.txt")
DEBUG_API_MAX_BYTES = 8 * 1024 * 1024   # 8 MB → giữ 1 bản .old, tối đa ~16 MB trên đĩa
_dbg_lock = threading.Lock()


def _log_api(msg):
    """Ghi 1 dòng trace API vào debug_api.txt (chỉ khi DEBUG_API bật, có xoay vòng theo dung lượng)."""
    if not DEBUG_API:
        return
    try:
        with _dbg_lock:
            try:
                if os.path.getsize(DEBUG_API_FILE) >= DEBUG_API_MAX_BYTES:
                    old = DEBUG_API_FILE + ".old"
                    if os.path.exists(old):
                        os.remove(old)
                    os.replace(DEBUG_API_FILE, old)
            except OSError:
                pass   # file chưa tồn tại hoặc đang bị khóa → cứ ghi tiếp
            with open(DEBUG_API_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _log_err(msg):
    if ERROR_LOG_FUNC:
        try:
            ERROR_LOG_FUNC(f"[Engine] {msg}")
        except Exception:
            pass
    else:
        try:
            print("[ENGINE ERROR]", msg)
        except Exception:
            try:
                print("[ENGINE ERROR]", str(msg).encode("ascii", errors="replace").decode())
            except Exception:
                pass


def _kw(t=60, proxy=None):
    """Keyword args cho HTTP request. Chọn đúng impersonate theo thư viện đang dùng."""
    d = {"impersonate": (IMP if _USE_PYREQWEST else IMP_CFFI), "timeout": t}
    if proxy:
        d["proxies"] = proxy
    return d


# ══════════════════ PHÂN LOẠI LỖI MẠNG (dùng chung mọi hàm HTTP) ══════════════════
# Trước đây mỗi hàm tự chép 1 tuple pattern giống nhau và CHỈ bắt được lỗi "không kết nối
# nổi tới proxy". Các lỗi hay gặp nhất khi chạy proxy residential — kết nối bị cắt giữa
# dòng, TLS trả rác, timeout — đều rơi vào nhánh "không rõ" và bị đánh lỗi cứng, làm mất
# job oan. Nay tách 2 nhóm rõ ràng:

# Nhóm 1: proxy/đường truyền CHẾT HẲN → nên đổi proxy ngay, retry cùng proxy là vô ích.
_PROXY_DEAD_PATTERNS = (
    "resolve proxy", "resolve host", "connect to proxy",
    "could not connect to server", "failed to connect to",
    "tunnel failed", "response 407", "proxy refused",
    "connection refused", "connection timed out",
)

# Nhóm 2: lỗi TẠM THỜI → thử lại là có cơ hội thành công.
#   "closed abruptly" / "connection was reset": proxy cắt kết nối giữa dòng
#   "invalid library" / "tls connect error": proxy trả rác không phải TLS record
#                                           (BoringSSL báo invalid library)
#   "operation timed out" / "recv failure": mạng chậm/nghẽn tạm thời
_TRANSIENT_PATTERNS = (
    "closed abruptly", "connection was reset", "connection reset",
    "recv failure", "send failure",
    "tls connect error", "invalid library",
    "operation timed out", "timed out after",
    "empty reply", "transfer closed", "http/2 stream",
    "ssl connect error", "gnutls", "unexpected eof",
)


def net_error_kind(exc):
    """Phân loại 1 exception mạng: 'proxy_dead' | 'transient' | 'other'."""
    s = str(exc).lower()
    if any(p in s for p in _PROXY_DEAD_PATTERNS):
        _set_last_proxy_error(exc)
        return "proxy_dead"
    if any(p in s for p in _TRANSIENT_PATTERNS):
        return "transient"
    return "other"


# --- Lý do proxy chết gần nhất (theo từng thread) — để UI hiển thị thay vì chỉ nói chung chung "proxy chết" ---
_proxy_err_local = threading.local()


def _set_last_proxy_error(reason):
    _proxy_err_local.msg = str(reason)


def get_last_proxy_error():
    """Lấy lý do proxy chết gần nhất của thread hiện tại (None nếu không có).
    Không xoá sau khi đọc — nhiều nơi (log nội bộ + log UI) cùng cần đọc giá trị này
    trước khi thread xử lý sự cố proxy tiếp theo và ghi đè nó."""
    return getattr(_proxy_err_local, "msg", None)


def is_net_retryable(value):
    """True nếu `value` là sentinel lỗi mạng mà caller nên requeue job (KHÔNG đánh lỗi cứng)."""
    return value in ("net_fail", "proxy_dead", "throttle")


# ---------- AUTH & BOQ ENGINE ----------
def cookie_to_dict(cookie_str):
    """Chuyển chuỗi Cookie thành dictionary cho HTTP request."""
    if not cookie_str:
        return {}
    if isinstance(cookie_str, dict):
        return cookie_str
    d = {}
    for part in str(cookie_str).split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            d[k.strip()] = v.strip()
    return d


def update_cookie_string(old_cookie, set_cookie_headers):
    """Cập nhật các cookie mới từ Set-Cookie headers vào chuỗi cookie cũ."""
    if not set_cookie_headers:
        return old_cookie
    if isinstance(set_cookie_headers, str):
        set_cookie_headers = [set_cookie_headers]

    cookie_dict = cookie_to_dict(old_cookie)
    for set_cookie in set_cookie_headers:
        first_part = set_cookie.split(";")[0]
        if "=" in first_part:
            k, v = first_part.strip().split("=", 1)
            cookie_dict[k.strip()] = v.strip()

    return "; ".join(f"{k}={v}" for k, v in cookie_dict.items())


_wiz_cache = {}
_wiz_lock = threading.Lock()


def invalidate_wiz_cache(cookie):
    if not cookie: return
    import hashlib
    ck_key = hashlib.md5(str(cookie).encode()).hexdigest()
    with _wiz_lock:
        _wiz_cache.pop(ck_key, None)

def get_wiz_tokens(cookie, proxy=None, force=False):
    """Trích xuất (at, fsid, bl, account_id) từ flow.google.com qua pure HTTP GET với cookie."""
    if not cookie:
        _log_err("get_wiz_tokens: cookie is empty/None")
        return None, None, None, None
    import hashlib
    ck_key = hashlib.md5(str(cookie).encode()).hexdigest()
    with _wiz_lock:
        if force:
            _wiz_cache.pop(ck_key, None)
        elif ck_key in _wiz_cache:
            entry = _wiz_cache[ck_key]
            if time.time() - entry.get("ts", 0) < 600:
                return entry["at"], entry["fsid"], entry["bl"], entry["account_id"]

    headers = {
        "User-Agent": UA_CH,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    # Thử với proxy trước, nếu fail thì thử trực tiếp (wiz_tokens chỉ cần lấy XSRF token từ HTML)
    attempts = [proxy, None] if proxy else [None]
    for px in attempts:
        kw = _kw(25, proxy=px)
        try:
            r = _get_session(px).get(f"{FLOW_BASE}/?pli=1", cookies=cookie_to_dict(cookie), headers=headers, **kw)
            if r.status_code == 200:
                import re
                m_snl = re.search(r'"SNlM0e":"([^"]+)"', r.text)
                m_fsid = re.search(r'"FdrFJe":"([^"]+)"', r.text)
                m_bl = re.search(r'"cfb2h":"([^"]+)"', r.text)
                m_acc = re.search(r'"S06Grb":"([^"]+)"', r.text)
                m_gmail = re.search(r'"oPEP7c":"([^"]+)"', r.text)
                at = m_snl.group(1) if m_snl else None
                fsid = m_fsid.group(1) if m_fsid else None
                bl = m_bl.group(1) if m_bl else "boq_labs-ai-sandbox-frontend_20260907.00_p0"
                account_id = m_gmail.group(1) if m_gmail else (m_acc.group(1) if m_acc else None)
                if at:
                    # Kiểm tra bl phải là trang Flow (sandbox), KHÔNG phải trang login Google
                    if bl and "sandbox" not in bl.lower() and "identityfrontend" in bl.lower():
                        _log_err(f"get_wiz_tokens: COOKIE HẾT HẠN - flow.google.com redirect về trang login (bl={bl[:50]})")
                        break  # Cookie thật sự hết hạn
                    _cache_put_ts(_wiz_cache, _wiz_lock, ck_key, {"at": at, "fsid": fsid, "bl": bl, "account_id": account_id, "ts": time.time()})
                    return at, fsid, bl, account_id
                else:
                    _log_err(f"get_wiz_tokens: HTTP 200 nhưng không tìm thấy SNlM0e. Cookie keys: {list(cookie_to_dict(cookie).keys())[:10]}. Page len: {len(r.text)}")
                    break  # Cookie thật sự hết hạn → không cần retry không proxy
            else:
                _log_err(f"get_wiz_tokens: HTTP {r.status_code} {'(via proxy)' if px else '(direct)'}")
                if px:
                    continue  # Retry trực tiếp
                break
        except Exception as e:
            _log_err(f"get_wiz_tokens error {'(via proxy)' if px else '(direct)'}: {e}")
            if px:
                continue  # Retry trực tiếp

    # ★ FALLBACK: HTML parsing thất bại → thử lấy từ native browser session (chạy JavaScript)
    # Google đã thay đổi flow.google.com — SNlM0e không còn nhúng trong HTML, chỉ load qua JS
    try:
        global _recaptcha_farm
        if _recaptcha_farm is None:
            import recaptcha_farm as RF
            _recaptcha_farm = RF.get_farm()
        if _recaptcha_farm and hasattr(_recaptcha_farm, "get_wiz_tokens_from_browser"):
            # Trích email từ cookie để tìm browser session
            import re as _re
            _em = None
            m_em = _re.search(r'(?:email|EMAIL)=([^;]+)', str(cookie))
            if m_em:
                _em = m_em.group(1).strip()
            at, fsid, bl, account_id = _recaptcha_farm.get_wiz_tokens_from_browser(
                cookie=cookie, project=None, email=_em
            )
            if at:
                if bl and "sandbox" not in bl.lower() and "identityfrontend" in bl.lower():
                    _log_err(f"get_wiz_tokens (browser): COOKIE HẾT HẠN - redirect login (bl={bl[:50]})")
                    return None, None, None, None
                _log_api(f"get_wiz_tokens: ✅ Fallback browser JS thành công! (at={at[:15]}...)")
                _cache_put_ts(_wiz_cache, _wiz_lock, ck_key, {"at": at, "fsid": fsid, "bl": bl, "account_id": account_id, "ts": time.time()})
                return at, fsid, bl, account_id
    except Exception as ex:
        _log_err(f"get_wiz_tokens browser fallback error: {ex}")

    return None, None, None, None


def boq_execute(rpc_id, payload_str, cookie, proxy=None, source_path="/", timeout=30):
    """Thực thi một RPC qua Google BOQ Batchexecute với cookie phiên."""
    if not cookie:
        return None, "auth"
    at, fsid, bl, account_id = get_wiz_tokens(cookie, proxy=proxy)
    if not at:
        _log_err(f"boq_execute {rpc_id}: get_wiz_tokens returned None (cookie keys: {list(cookie_to_dict(cookie).keys())[:5]})")
        return None, "auth"

    import random
    url = f"{FLOW_BATCHEXECUTE}?rpcids={rpc_id}&source-path={urllib.parse.quote(source_path)}&bl={bl}&f.sid={fsid or ''}&hl=en-US&_reqid={random.randint(1000, 9999)}&rt=c"
    headers = {
        "User-Agent": UA_CH,
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Origin": FLOW_BASE,
        "Referer": f"{FLOW_BASE}{source_path}",
        "X-Same-Domain": "1"
    }
    
    # Tạo SAPISIDHASH Authorization header (cần khi gửi qua proxy / IP khác)
    ck_dict = cookie_to_dict(cookie)
    sapisid = ck_dict.get("SAPISID") or ck_dict.get("__Secure-3PAPISID") or ""
    if sapisid:
        import hashlib as _hl
        ts = int(time.time())
        origin = FLOW_BASE  # https://flow.google.com
        hash_input = f"{ts} {sapisid} {origin}"
        sapisidhash = _hl.sha1(hash_input.encode()).hexdigest()
        headers["Authorization"] = f"SAPISIDHASH {ts}_{sapisidhash}"
        headers["X-Goog-Authuser"] = "0"
    
    freq = [[[rpc_id, payload_str, None, "generic"]]]
    data = {"f.req": json.dumps(freq), "at": at}
    kw = _kw(timeout, proxy=proxy)

    try:
        r = _get_session(proxy).post(url, data=urllib.parse.urlencode(data), cookies=ck_dict, headers=headers, **kw)
    except Exception as e:
        kind = net_error_kind(e)
        if kind == "proxy_dead":
            return None, "proxy_dead"
        _log_err(f"boq_execute network exception ({rpc_id}): {e}")
        return None, "net_fail"

    if "xsrf" in r.text:
        import re
        m = re.search(r'\["xsrf","([^"]+)"', r.text)
        if m:
            new_at = m.group(1)
            import hashlib
            ck_key = hashlib.md5(str(cookie).encode()).hexdigest()
            with _wiz_lock:
                if ck_key in _wiz_cache:
                    _wiz_cache[ck_key]["at"] = new_at
            data["at"] = new_at
            try:
                r = _get_session(proxy).post(url, data=urllib.parse.urlencode(data), cookies=ck_dict, headers=headers, **kw)
            except Exception:
                pass

    if r.status_code in (401, 403):
        _log_err(f"boq_execute {rpc_id}: HTTP {r.status_code} (proxy={'YES' if proxy else 'NO'}). Response: {r.text[:200]}")
        return None, "auth"
    if r.status_code == 429:
        return None, "throttle"
    if "PUBLIC_ERROR_USER_QUOTA_REACHED" in r.text or "QUOTA" in r.text.upper():
        return None, "quota_hard"
    if "PUBLIC_ERROR_UNUSUAL_ACTIVITY" in r.text or "UNUSUAL_ACTIVITY" in r.text:
        _log_err(f"boq_execute {rpc_id}: UNUSUAL_ACTIVITY! HTTP {r.status_code}. Response[:500]: {r.text[:500]}")
        return None, "unusual"

    for line in r.text.splitlines():
        if line.startswith("[["):
            try:
                parsed = json.loads(line)
                if len(parsed) > 0 and len(parsed[0]) >= 6:
                    item = parsed[0]
                    err_info = item[5]
                    if err_info:
                        err_code = err_info[0] if isinstance(err_info, list) and len(err_info) > 0 else err_info
                        # gRPC 8 = RESOURCE_EXHAUSTED (throttle / 429)
                        if err_code == 8 or "RESOURCE_EXHAUSTED" in str(err_info):
                            return None, "throttle"
                        # gRPC 7 = PERMISSION_DENIED
                        if err_code == 7 or "PERMISSION_DENIED" in str(err_info):
                            # Kiểm tra chuỗi chính xác "UNUSUAL_ACTIVITY" thay vì chỉ "UNUSUAL"
                            # để tránh false positive khi Google mô tả nội dung "unusual" với nghĩa khác.
                            err_str = str(err_info).upper()
                            if "UNUSUAL_ACTIVITY" in err_str or "PUBLIC_ERROR_UNUSUAL_ACTIVITY" in err_str:
                                return None, "unusual"
                            return None, "forbidden"
                        # gRPC 16 = UNAUTHENTICATED
                        if err_code == 16:
                            return None, "auth"
                        # gRPC 3 = INVALID_ARGUMENT
                        if err_code == 3:
                            return None, "invalid_arg"
                    if len(item) > 2 and item[2]:
                        return json.loads(item[2]), "ok"
            except Exception:
                pass

    if r.status_code == 200:
        return None, "ok_empty"
    return None, "failed"


def bearer_from_cookie(cookie, timeout=25, proxy=None):
    """Xác thực cookie Google Flow giống TstGoogleFlow 1.0.6, trả (access_token, email, cookie_mới).

    Đổi cookie lấy access token qua session endpoint của labs.google (get_session_token, có tự
    Headless OAuth Refresh) — đúng đường mà upload/submit/poll dùng. Trước đây hàm này quét mã
    SNlM0e trên trang Flow; Google đã bỏ mã đó khỏi trang nên cookie còn sống vẫn bị báo "Chết"
    (nút Check) và ensure_auth() của worker có thể tự dừng tài khoản oan.
    """
    if not cookie:
        return None, None, None
    tok = get_session_token(cookie, proxy=proxy)
    if not tok:
        return None, None, None
    email = None
    import re
    m = re.search(r'(?:email|EMAIL)=([^;]+)', cookie)
    if m:
        email = urllib.parse.unquote(m.group(1))
    return tok, email, get_refreshed_cookie(cookie) or cookie


def get_project(cookie, proxy=None):
    """Lấy projectId của tài khoản qua RPC LWkPYd."""
    if not cookie:
        return None
    res, status = boq_execute("LWkPYd", "[]", cookie, proxy=proxy)
    if status == "ok" and res and isinstance(res, list) and len(res) > 0:
        items = res[0] if isinstance(res[0], list) else res
        for item in items:
            if isinstance(item, list):
                # Ưu tiên item[4] nếu là UUID hợp lệ (không phải email)
                if len(item) > 4:
                    pid = str(item[4] or "").strip()
                    if pid and len(pid) > 10 and "@" not in pid and "-" in pid:
                        return pid
                # Kiểm tra item[1] nếu item[4] là email hoặc rỗng
                if len(item) > 1:
                    pid1 = str(item[1] or "").strip()
                    if pid1 and len(pid1) > 10 and "@" not in pid1 and "-" in pid1:
                        return pid1
    return "513f3b20-fa17-4be7-89b5-f179860de580"


def delete_project(cookie, proxy=None):
    """Xóa scene/project trên Google Flow."""
    return 0


def reset_project(cookie, proxy=None):
    """Reset / tạo project mới trên Google Flow."""
    return get_project(cookie, proxy=proxy)


def _hf(bearer):  # headers Firefox cho android_bypass
    return {"Authorization": f"Bearer {bearer}", "Content-Type": "text/plain;charset=UTF-8", "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9,vi;q=0.8", "Origin": "https://labs.google", "Referer": "https://labs.google/",
            "User-Agent": UA_FF, "Cache-Control": "no-cache", "Pragma": "no-cache", "Priority": "u=1, i",
            "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "cross-site", "X-Browser-Channel": "stable"}


def _hc(bearer):  # headers Chrome cho poll/upload (nâng cấp giống AutoVeo3 ai_transport.pyd)
    return {"Authorization": f"Bearer {bearer}", "Content-Type": "text/plain;charset=UTF-8", "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9", "Origin": "https://labs.google", "Referer": "https://labs.google/",
            "User-Agent": UA_CH,
            "Sec-Ch-Ua": '"Google Chrome";v="147", "Not:A-Brand";v="8", "Chromium";v="147"',
            "Sec-Ch-Ua-Mobile": "?0", "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "cross-site"}


# Global throttle: giãn tối thiểu 3s giữa mỗi upload request (tất cả accounts)
_upload_lock = threading.Lock()
_upload_last_ts = 0.0
_UPLOAD_MIN_GAP = 3.0  # giây tối thiểu giữa 2 lần upload

# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENT MD5 IMAGE CACHE (Học từ AutoVeo3 V5.0 & V5.7)
# ══════════════════════════════════════════════════════════════════════════════
# AutoVeo3 lưu cache vào file cfg\uploaded_image_cache.json với key: {MD5(base64)}_{userEmail}
# Giúp tái sử dụng media_id ngay lập tức (0ms mạng, 0 tốn token reCAPTCHA, 0 sợ 429)
_IMAGE_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploaded_image_cache.json")
_image_cache = {}
_image_cache_lock = threading.Lock()

def _load_image_cache():
    """Nạp bộ nhớ đệm ảnh từ file uploaded_image_cache.json trên ổ cứng."""
    global _image_cache
    with _image_cache_lock:
        if os.path.isfile(_IMAGE_CACHE_FILE):
            try:
                with open(_IMAGE_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        _image_cache = data
                        _log_api(f"PersistentImageCache: Nạp thành công {len(_image_cache)} ảnh từ disk.")
            except Exception as e:
                _log_err(f"PersistentImageCache load error: {e}")
                _image_cache = {}

def _save_image_cache():
    """Lưu bộ nhớ đệm ảnh ra file uploaded_image_cache.json an toàn."""
    with _image_cache_lock:
        try:
            temp_file = f"{_IMAGE_CACHE_FILE}.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(_image_cache, f, indent=2, ensure_ascii=False)
            if os.path.exists(_IMAGE_CACHE_FILE):
                os.replace(temp_file, _IMAGE_CACHE_FILE)
            else:
                os.rename(temp_file, _IMAGE_CACHE_FILE)
        except Exception as e:
            try:
                with open(_IMAGE_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(_image_cache, f, indent=2, ensure_ascii=False)
            except Exception as e2:
                _log_err(f"PersistentImageCache save error: {e2}")

_load_image_cache()

def compute_image_md5(image_data):
    """Tính MD5 hash của chuỗi base64 hoặc bytes ảnh (viết hoa chuẩn AutoVeo3 TinhMD5TuBase64)."""
    import hashlib
    if isinstance(image_data, str):
        raw = image_data.encode("ascii", errors="ignore")
    elif isinstance(image_data, (bytes, bytearray)):
        raw = bytes(image_data)
    else:
        raw = str(image_data).encode("utf-8")
    return hashlib.md5(raw).hexdigest().upper()

def extract_email_from_cookie(cookie_str):
    """Trích xuất email người dùng từ cookie string (chuẩn AutoVeo3 ExtractEmailFromCookie)."""
    if not cookie_str or not isinstance(cookie_str, str):
        return ""
    import re, urllib.parse
    try:
        m = re.search(r'(?i)(?:email|EMAIL)=([^;]+)', cookie_str)
        if m:
            val = m.group(1).strip().strip('"')
            return urllib.parse.unquote(val).strip()
    except Exception:
        pass
    return ""

def make_image_cache_key(md5_hash, account_tag):
    """Tạo khóa cache chuẩn AutoVeo3: {MD5}_{email_hoặc_account}."""
    tag = str(account_tag or "unknown").strip().lower()
    return f"{md5_hash}_{tag}"

def get_cached_image(cache_key):
    """Lấy media_id từ cache (nếu có)."""
    with _image_cache_lock:
        return _image_cache.get(cache_key)

def set_cached_image(cache_key, media_id):
    """Lưu media_id vào cache và ghi ra đĩa."""
    if not cache_key or not media_id:
        return
    bad_sentinels = ("throttle", "forbidden", "proxy_dead", "unauthorized", "vi phạm cs", "net_fail", "unusual")
    if any(s in str(media_id) for s in bad_sentinels):
        return
    with _image_cache_lock:
        _image_cache[cache_key] = str(media_id)
    _save_image_cache()

def clear_image_cache():
    """Xóa toàn bộ bộ nhớ đệm ảnh trên RAM và trên file đĩa (chuẩn AutoVeo3 modernButton5_Click)."""
    global _image_cache
    with _image_cache_lock:
        _image_cache.clear()
        try:
            with open(_IMAGE_CACHE_FILE, "w", encoding="utf-8") as f:
                f.write("{}")
            _log_api("PersistentImageCache: Đã xóa sạch bộ nhớ đệm ảnh.")
            return True
        except Exception as e:
            _log_err(f"clear_image_cache error: {e}")
            return False

def invalidate_cached_image(cache_key):
    """Xóa một key cụ thể khỏi cache."""
    with _image_cache_lock:
        if cache_key in _image_cache:
            del _image_cache[cache_key]
            _save_image_cache()


# ══════════════════════════════════════════════════════════════════════════════
# REST UPLOAD ENDPOINT (POST https://aisandbox-pa.googleapis.com/v1/flow/uploadImage)
# ══════════════════════════════════════════════════════════════════════════════
_session_token_cache = {}
_session_lock = threading.Lock()

def get_session_token(cookie, proxy=None, force=False):
    """Lấy access_token (Bearer) từ https://labs.google/fx/api/auth/session.
    
    Đây là phương thức auth chính cho REST API (giống TstGoogleFlow v1.0.6).
    Cache 900s (15 phút). Tự động retry 1 lần nếu thất bại.
    """
    if not cookie or not isinstance(cookie, str) or ("=" not in cookie):
        return None
    import hashlib
    ck_key = hashlib.md5(cookie.encode("utf-8", errors="ignore")).hexdigest()
    with _session_lock:
        if not force and ck_key in _session_token_cache:
            entry = _session_token_cache[ck_key]
            if time.time() - entry.get("ts", 0) < 900:  # 15 phút TTL (v1.0.6 refresh mỗi 20 phút)
                return entry.get("token")
    headers = {
        "User-Agent": UA_FF,  # v1.0.6 dùng Firefox UA
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://labs.google/fx/tools/flow",  # v1.0.6 referer cụ thể
        "Cookie": cookie,
    }
    for _retry in range(2):  # retry 1 lần nếu thất bại
        try:
            kw = _kw(30, proxy=proxy)  # v1.0.6 timeout 30s
            r = _get_session(proxy).get("https://labs.google/fx/api/auth/session", headers=headers, **kw)
            if r.status_code == 200:
                text = r.text or ""
                # v1.0.6: kiểm tra ACCESS_TOKEN_REFRESH_NEEDED hoặc session rỗng {} (chưa có NextAuth session)
                if "ACCESS_TOKEN_REFRESH_NEEDED" in text or text.strip() == "{}":
                    _log_err("get_session_token: NextAuth session cần lấy mới — thử Headless OAuth Refresh...")
                    new_ck, new_tok = headless_oauth_refresh(cookie, proxy=proxy)
                    if new_tok:
                        _log_err(f"get_session_token: ✅ Headless OAuth Refresh thành công (token len={len(new_tok)})")
                        return new_tok
                    _log_err("get_session_token: Headless OAuth Refresh thất bại — cookie cần làm mới qua browser")
                    return None
                try:
                    data = r.json() if hasattr(r, "json") else json.loads(text)
                except Exception:
                    data = {}
                tok = data.get("access_token")
                if tok:
                    _cache_put_ts(_session_token_cache, _session_lock, ck_key, {"token": tok, "ts": time.time()})
                    return tok
                # Không có access_token trong data -> thử Headless OAuth Refresh
                _log_err("get_session_token: Không có access_token trong session — thử Headless OAuth Refresh...")
                new_ck, new_tok = headless_oauth_refresh(cookie, proxy=proxy)
                if new_tok:
                    _log_err(f"get_session_token: ✅ Headless OAuth Refresh thành công (token len={len(new_tok)})")
                    return new_tok
                return None
            elif r.status_code in (401, 403):
                _log_err(f"get_session_token: HTTP {r.status_code} — thử Headless OAuth Refresh...")
                new_ck, new_tok = headless_oauth_refresh(cookie, proxy=proxy)
                if new_tok:
                    _log_err(f"get_session_token: ✅ Headless OAuth Refresh thành công (token len={len(new_tok)})")
                    return new_tok
                _log_err(f"get_session_token: HTTP {r.status_code} — cookie hết hạn")
                return None
        except Exception as e:
            _log_err(f"get_session_token error (attempt {_retry+1}): {e}")
            if _retry == 0:
                time.sleep(1)  # chờ 1s rồi retry
                continue
    return None


# ══════════════════════════════════════════════════════════════════════════════
# REST API FUNCTIONS (giống TstGoogleFlow v1.0.6)
# ══════════════════════════════════════════════════════════════════════════════

def resolve_access_token(bearer, cookie=None, proxy=None):
    """Lấy access token dùng cho REST API — CÙNG MỘT nguồn cho upload/submit/poll.

    Ưu tiên `bearer` mà caller đã có sẵn (AccountState.bearer, lấy qua bearer_from_cookie);
    chỉ khi không có mới đổi cookie lấy token mới. Trước đây upload_image dùng `bearer` còn
    submit_video/poll_video tự gọi get_session_token() nên hai bên chạy bằng 2 token khác nhau.
    """
    if bearer and isinstance(bearer, str) and "SID=" not in bearer and "OSID=" not in bearer:
        return bearer.strip()
    ck = cookie or (bearer if isinstance(bearer, str) else None)
    if not ck:
        return None
    return get_session_token(ck, proxy=proxy)


def _build_rest_headers(bearer_token):
    """Headers REST giống TstGoogleFlow v1.0.6 AddVeo3SandboxHeaders."""
    return {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "text/plain;charset=UTF-8",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        "Origin": "https://labs.google",
        "Referer": "https://labs.google/",
        "User-Agent": UA_FF,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Priority": "u=1, i",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
        "X-Browser-Channel": "stable",
    }


_tier_cache = {}
_tier_lock = threading.Lock()

def get_paygate_tier(bearer_token, proxy=None):
    """Lấy userPaygateTier của tài khoản qua GET /v1/credits (giống TstGoogleFlow v1.0.6 Veo3FetchCreditsAsync)."""
    if not bearer_token:
        return "PAYGATE_TIER_TWO"
    import hashlib
    k = hashlib.md5(bearer_token.encode("utf-8", errors="ignore")).hexdigest()
    with _tier_lock:
        if k in _tier_cache:
            entry = _tier_cache[k]
            if time.time() - entry.get("ts", 0) < 3600:
                return entry.get("tier", "PAYGATE_TIER_TWO")
    try:
        headers = _build_rest_headers(bearer_token)
        # BẮT BUỘC dùng _kw(): thiếu "impersonate" thì request đi với TLS fingerprint curl trần
        # (không giống Chrome), và "proxy=" là sai tên tham số nên request KHÔNG qua proxy.
        # Session giữ keep-alive, nên request submit ngay sau đó tái dùng đúng connection "bẩn" đó
        # → fingerprint/IP không khớp → Google Frontend chặn bằng trang HTML "Error 400 (Bad Request)".
        r = _api_session(proxy).get(f"{BASE}/credits?key={KEY}", headers=headers, **_kw(15, proxy=proxy))
        if r.status_code == 200:
            data = r.json()
            tier = data.get("userPaygateTier") or "PAYGATE_TIER_TWO"
            _cache_put_ts(_tier_cache, _tier_lock, k, {"tier": tier, "ts": time.time()})
            return tier
    except Exception:
        pass
    return "PAYGATE_TIER_TWO"


def _build_client_context(project, rc_token=None, paygate_tier=None):
    """clientContext JSON chuẩn v1.0.6 Veo3BuildVideoClientContext."""
    session_id = f";{int((time.time() + 900) * 1000)}"
    ctx = {
        "projectId": project,
        "tool": "PINHOLE",
        "userPaygateTier": paygate_tier or "PAYGATE_TIER_TWO",
        "sessionId": session_id,
    }
    if rc_token:
        ctx["recaptchaContext"] = {
            "token": rc_token,
            "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB"
        }
    return ctx


def submit_video_rest(bearer_token, project, prompt, seed, aspect, model,
                      ref_media_id=None, rc_token=None, timeout=120, proxy=None):
    """Submit video qua REST API trực tiếp (giống TstGoogleFlow v1.0.6).
    
    Trả về: (status, result)
      - ("ok", [media_id])  khi thành công
      - ("auth", None)      khi Bearer hết hạn
      - ("unusual", None)   khi bị UNUSUAL_ACTIVITY
      - ("throttle", None)  khi bị rate limit
      - ("quota_hard", None) khi hết quota
      - ("vi phạm cs", None) khi vi phạm chính sách
      - ("MODEL_ACCESS_DENIED", None) khi tài khoản không có quyền model
      - ("failed", None)    khi lỗi khác
    """
    # Chọn endpoint
    is_i2v = bool(ref_media_id)
    url = GEN_I2V if is_i2v else GEN_T2V
    
    # Build clientContext với dynamic paygate tier (v1.0.6)
    tier = get_paygate_tier(bearer_token, proxy=proxy)
    client_ctx = _build_client_context(project, rc_token, paygate_tier=tier)
    
    # Map aspect ratio
    if isinstance(aspect, str):
        if "16:9" in aspect or "LANDSCAPE" in aspect:
            aspect_code = "VIDEO_ASPECT_RATIO_LANDSCAPE"
        else:
            aspect_code = "VIDEO_ASPECT_RATIO_PORTRAIT"
    else:
        aspect_code = aspect if isinstance(aspect, str) and aspect.startswith("VIDEO_") else "VIDEO_ASPECT_RATIO_PORTRAIT"
    
    # Map model key (giữ nguyên nếu đã đúng format)
    model_key = model
    if ref_media_id and model_key and "t2v" in model_key:
        # Auto-convert T2V model → R2V cho I2V (v1.0.6)
        model_key = model_key.replace("t2v", "r2v")
    
    # Build request item (v1.0.6 payload structure)
    request_item = {
        "aspectRatio": aspect_code,
        "seed": seed,
        "textInput": {
            "structuredPrompt": {
                "parts": [{"text": prompt}]
            }
        },
        "videoModelKey": model_key,
        "metadata": {}
    }
    
    # I2V: thêm reference (v1.0.6 format)
    if ref_media_id:
        request_item["textInput"]["structuredPrompt"]["parts"].insert(0, {
            "reference": {
                "media": {"handle": "image_name", "mediaId": ref_media_id}
            }
        })
        request_item["referenceImages"] = [{
            "mediaId": ref_media_id,
            "imageUsageType": "IMAGE_USAGE_TYPE_ASSET"
        }]
    
    # Build full payload (v1.0.6)
    payload = {
        "mediaGenerationContext": {"batchId": str(uuid.uuid4())},
        "clientContext": client_ctx,
        "requests": [request_item],
        "useV2ModelConfig": True
    }
    
    def _err_ctx(status_code, text):
        _tok_s = str(bearer_token or "")
        _tok_info = f"token[len={len(_tok_s)}, {_tok_s[:10]}...]"
        if text.lstrip().startswith("<!DOCTYPE") or "Error 400 (Bad Request)" in text:
            # Google Frontend chan o tang HTTP (khong phai loi JSON cua API) → in breakdown tung phan
            # de biet chinh xac thanh phan nao lam payload phinh to bat thuong.
            _parts = request_item.get("textInput", {}).get("structuredPrompt", {}).get("parts", [])
            _sizes = " + ".join(f"{list(p.keys())[0]}:{len(json.dumps(p))}B" for p in _parts if p)
            return (f"submit_video_rest: GFE tu choi HTTP {status_code} | body={len(json.dumps(payload))}B "
                    f"[ctx={len(json.dumps(client_ctx))}B, parts=({_sizes}), refImgs="
                    f"{len(json.dumps(request_item.get('referenceImages', [])))}B] | prompt={len(str(prompt))} ky tu | "
                    f"rc_token={len(str(rc_token or ''))} | {_tok_info} | tier={tier} | "
                    f"model={model_key} | proxy={'YES' if proxy else 'NO'}")
        return (f"submit_video_rest: HTTP {status_code} (i2v={is_i2v}, model={model_key}, aspect={aspect_code}, "
                f"proxy={'YES' if proxy else 'NO'}, {_tok_info}): {text[:300]}")

    return _post_video_generate(url, payload, bearer_token, proxy, timeout, err_ctx_fn=_err_ctx)


def _post_video_generate(url, payload, bearer_token, proxy, timeout, err_ctx_fn=None):
    """POST payload tạo video (dùng chung cho T2V/I2V/Start+End/Extend) — phân loại lỗi + parse mediaId.
    Tách từ submit_video_rest() để các endpoint mới (Start+End, Extend) tái dùng nguyên logic lỗi/parse.
    err_ctx_fn(status_code, text) -> chuỗi log bổ sung khi request thất bại (mỗi loại request tự thêm ngữ cảnh)."""
    headers = _build_rest_headers(bearer_token)
    try:
        kw = _kw(timeout, proxy=proxy)
        r = _api_session(proxy).post(url, headers=headers, data=json.dumps(payload), **kw)
        text = r.text or ""
        up = text.upper()

        # Error keywords trong response body (ưu tiên nhận diện lỗi chính xác)
        if "MODEL_ACCESS_DENIED" in up:
            _log_err("_post_video_generate: Google báo MODEL_ACCESS_DENIED")
            return "MODEL_ACCESS_DENIED", None
        if "UNUSUAL_ACTIVITY" in up:
            return "unusual", None
        if "QUOTA_REACHED" in up:
            return "quota_hard", None
        if "RATE-LIMITED" in up or "RATELIMITEXCEEDED" in up or "TOO MANY REQUESTS" in up:
            return "throttle", None
        if any(tok in up for tok in POLICY_TOKENS):
            return "vi phạm cs", None

        # HTTP error codes
        if r.status_code == 401:
            return "auth", None
        if r.status_code == 403:
            # Khác 401: TstGoogleFlow retry ĐÚNG 1 LẦN bằng recaptcha token thật mới (xem submit_video())
            return "forbidden_recaptcha_retry", None
        if r.status_code == 429:
            return "throttle", None

        if r.status_code in (200, 201):
            # Parse mediaId (v1.0.6: media[0].name hoặc workflows[0].metadata.primaryMediaId)
            try:
                data = json.loads(text)
                # Path 1: workflows[0].metadata.primaryMediaId (chuẩn v1.0.6 response)
                workflows = data.get("workflows", [])
                if isinstance(workflows, list) and workflows:
                    meta = workflows[0].get("metadata", {})
                    mid = meta.get("primaryMediaId")
                    if mid:
                        _log_api(f"_post_video_generate: ✅ REST thành công (workflow)! mediaId={mid}")
                        return "ok", [str(mid)]
                # Path 2: media[0].name
                media_list = data.get("media", [])
                if isinstance(media_list, list) and media_list:
                    mid = media_list[0].get("name")
                    if mid:
                        _log_api(f"_post_video_generate: ✅ REST thành công! mediaId={mid}")
                        return "ok", [str(mid)]
                # Path 3: mediaId trực tiếp
                mid = data.get("mediaId")
                if mid:
                    _log_api(f"_post_video_generate: ✅ REST thành công (direct)! mediaId={mid}")
                    return "ok", [str(mid)]
                _log_err(f"_post_video_generate: HTTP 200 nhưng không parse được mediaId: {text[:300]}")
                return "failed", None
            except Exception as e_parse:
                _log_err(f"_post_video_generate: parse error: {e_parse}, text={text[:200]}")
                return "failed", None

        if err_ctx_fn:
            _log_err(err_ctx_fn(r.status_code, text))
        else:
            _log_err(f"_post_video_generate: HTTP {r.status_code}: {text[:300]}")
        return "failed", None

    except Exception as e:
        kind = net_error_kind(e)
        if kind == "proxy_dead":
            return "proxy_dead", None
        _log_err(f"_post_video_generate exception: {e}")
        return "failed", None


def submit_video_start_end_rest(bearer_token, project, prompt, seed, aspect, first_media_id, last_media_id,
                                model="veo_3_1_interpolation_lite_low_priority", rc_token=None, timeout=120, proxy=None):
    """Tạo video nội suy từ 2 ảnh đầu/cuối (Start & End Frame Interpolation) qua REST API.
    Endpoint + field payload (`startImage`/`endImage`) đã XÁC MINH THẬT bằng thực nghiệm (Google trả
    lỗi "Unknown name" cho field sai, không báo lỗi field cho startImage/endImage — sau đó payload đủ
    field hợp lệ thì lỗi chuyển từ 400 field-sai sang 403 reCAPTCHA, đúng dấu hiệu payload được chấp nhận).
    Trả về: cùng kiểu status với submit_video_rest() — ("ok", [media_id]) | ("auth", None) | ..."""
    tier = get_paygate_tier(bearer_token, proxy=proxy)
    client_ctx = _build_client_context(project, rc_token, paygate_tier=tier)
    aspect_code = "VIDEO_ASPECT_RATIO_LANDSCAPE" if (isinstance(aspect, str) and ("16:9" in aspect or "LANDSCAPE" in aspect)) else "VIDEO_ASPECT_RATIO_PORTRAIT"

    request_item = {
        "aspectRatio": aspect_code,
        "seed": seed,
        "textInput": {"structuredPrompt": {"parts": [{"text": prompt}]}},
        "videoModelKey": model,
        "metadata": {},
        "startImage": {"mediaId": first_media_id},
        "endImage": {"mediaId": last_media_id},
    }
    payload = {
        "mediaGenerationContext": {"batchId": str(uuid.uuid4())},
        "clientContext": client_ctx,
        "requests": [request_item],
        "useV2ModelConfig": True,
    }

    def _err_ctx(status_code, text):
        return f"submit_video_start_end_rest: HTTP {status_code} (model={model}, aspect={aspect_code}, proxy={'YES' if proxy else 'NO'}): {text[:300]}"

    return _post_video_generate(GEN_START_END, payload, bearer_token, proxy, timeout, err_ctx_fn=_err_ctx)


def extend_video_rest(bearer_token, project, prompt, source_media_id, seed, aspect,
                      model="veo_3_1_extension_lite_low_priority", rc_token=None, timeout=120, proxy=None):
    """Nối dài thêm 1 video đã tạo (Video Extend) qua REST API. `source_media_id` PHẢI là mediaId của
    1 VIDEO đã render xong (không phải ảnh). Field payload (`referenceImages`, tái dùng nguyên dạng với
    endpoint I2V thường) đã XÁC MINH THẬT bằng thực nghiệm cùng kỹ thuật "Unknown name" ở trên — CHƯA xác
    minh phần thân imageUsageType có cần đổi khác đi khi mediaId là video hay không (chưa có video thật
    để test đến cùng); nếu Google báo lỗi field lạ khi dùng thật, xem lại giá trị `imageUsageType`.
    Trả về: cùng kiểu status với submit_video_rest()."""
    tier = get_paygate_tier(bearer_token, proxy=proxy)
    client_ctx = _build_client_context(project, rc_token, paygate_tier=tier)
    aspect_code = "VIDEO_ASPECT_RATIO_LANDSCAPE" if (isinstance(aspect, str) and ("16:9" in aspect or "LANDSCAPE" in aspect)) else "VIDEO_ASPECT_RATIO_PORTRAIT"

    request_item = {
        "aspectRatio": aspect_code,
        "seed": seed,
        "textInput": {"structuredPrompt": {"parts": [{"text": prompt}]}},
        "videoModelKey": model,
        "metadata": {},
        "referenceImages": [{"mediaId": source_media_id, "imageUsageType": "IMAGE_USAGE_TYPE_ASSET"}],
    }
    payload = {
        "mediaGenerationContext": {"batchId": str(uuid.uuid4())},
        "clientContext": client_ctx,
        "requests": [request_item],
        "useV2ModelConfig": True,
    }

    def _err_ctx(status_code, text):
        return f"extend_video_rest: HTTP {status_code} (model={model}, aspect={aspect_code}, proxy={'YES' if proxy else 'NO'}): {text[:300]}"

    return _post_video_generate(GEN_EXTEND, payload, bearer_token, proxy, timeout, err_ctx_fn=_err_ctx)


_poll_success_body_logged = False  # dump 1 lần response JSON thật khi thành công, để dò field URL
                                    # tải video thay cho boq_execute("Iyc41d") đã bị Google khai tử (401)


def poll_video_rest(bearer_token, media_id, project, proxy=None, timeout_minutes=15):
    """Poll trạng thái video qua REST API (thuật toán TstGoogleFlow v1.0.6).
    
    Timing v1.0.6: initial 8s, +3s mỗi lượt, tối đa 20s interval, timeout 15 phút.
    Chuỗi delay: 8s → 11s → 14s → 17s → 20s → 20s → ...
    
    Trả về: (status, result, credits)
      - ("done", media_id, None)
      - ("failed", reason, None)
      - ("auth", None, None)
      - ("proxy_dead", None, None)
    """
    url = CHECK
    headers = _build_rest_headers(bearer_token)
    payload = json.dumps({"media": [{"name": media_id, "projectId": project}]})
    
    deadline = time.time() + timeout_minutes * 60
    delay = 8.0  # v1.0.6 initial delay
    
    attempt = 0
    while time.time() < deadline:
        time.sleep(delay)
        attempt += 1
        
        # Tăng delay theo v1.0.6: +3s mỗi lượt, tối đa 20s
        if delay < 20.0:
            delay = min(delay + 3.0, 20.0)
        
        try:
            kw = _kw(30, proxy=proxy)  # v1.0.6 single request timeout 30s
            r = _api_session(proxy).post(url, headers=headers, data=payload, **kw)
            
            if r.status_code in (401, 403):
                _log_err(f"poll_video_rest: HTTP {r.status_code} — Bearer hết hạn")
                return "auth", None, None
            
            if r.status_code != 200:
                _log_err(f"poll_video_rest: HTTP {r.status_code} attempt #{attempt}")
                continue
            
            text = r.text or ""
            
            # v1.0.6 nhận diện thành công
            if "MEDIA_GENERATION_STATUS_SUCCESSFUL" in text:
                _log_api(f"poll_video_rest: ✅ Video render thành công sau {attempt} lượt poll!")
                global _poll_success_body_logged
                if not _poll_success_body_logged:
                    _poll_success_body_logged = True
                    _log_api(f"[DEBUG 1 lần] poll_video_rest raw body khi thành công (để dò field URL video, tránh phải qua boq_execute Iyc41d đã chết): {text[:4000]}")
                return "done", media_id, None
            
            # v1.0.6 nhận diện thất bại
            if "MEDIA_GENERATION_STATUS_FAILED" in text or "STATUS_FAILED" in text:
                # Trích xuất lý do lỗi
                reason = "render_failed"
                try:
                    body = json.loads(text)
                    reasons = _find_reasons(body)
                    if reasons:
                        reason = reasons[0]
                except Exception:
                    pass
                _log_err(f"poll_video_rest: ❌ Video render thất bại: {reason}")
                return "failed", reason, None
            
        except Exception as e:
            kind = net_error_kind(e)
            if kind == "proxy_dead":
                return "proxy_dead", None, None
            _log_err(f"poll_video_rest: exception attempt #{attempt}: {e}")
    
    _log_err(f"poll_video_rest: ⏰ Timeout {timeout_minutes} phút sau {attempt} lượt poll.")
    return "failed", "timeout", None


def get_credits_rest(bearer_token, proxy=None):
    """Lấy số credits còn lại qua REST API (v1.0.6 Veo3FetchCreditsAsync).
    
    Trả về: (credits: int, paygate_tier: str) hoặc (None, None) nếu lỗi.
    """
    url = f"{BASE}/credits?key={KEY}"
    headers = _build_rest_headers(bearer_token)
    try:
        r = _api_session(proxy).get(url, headers=headers, **_kw(30, proxy=proxy))
        if r.status_code == 200:
            data = r.json() if hasattr(r, "json") else json.loads(r.text)
            credits = data.get("credits", 0)
            tier = data.get("userPaygateTier", "")
            return int(credits), tier
    except Exception as e:
        _log_err(f"get_credits_rest error: {e}")
    return None, None

# ══════════════════════════════════════════════════════════════════════════════
# HEADLESS OAUTH REFRESH (giống TstGoogleFlow v1.0.6 DoRefreshTokenAsync)
# Làm mới cookie NextAuth bằng HTTP thuần — KHÔNG cần mở trình duyệt
# ══════════════════════════════════════════════════════════════════════════════

# Per-cookie refresh lock: chỉ 1 luồng refresh / cookie tại 1 thời điểm
# (Double-Checked Locking pattern giống v1.0.6 _accountAuthLocks)
_refresh_locks = {}          # ck_key -> threading.Lock
_refresh_locks_meta = threading.Lock()

# Cookie update propagation: worker đọc cookie mới sau khi engine refresh
_cookie_updates = {}         # ck_key -> new_cookie_str
_cookie_updates_lock = threading.Lock()


def _get_refresh_lock(ck_key):
    """Lấy hoặc tạo Lock riêng cho từng cookie (per-account)."""
    with _refresh_locks_meta:
        if ck_key not in _refresh_locks:
            # Dict không đổi cookie thường xuyên nên dùng FIFO đơn giản (thứ tự chèn) để evict khi đầy
            if len(_refresh_locks) > _CACHE_MAX_SIZE:
                oldest_key = next(iter(_refresh_locks))
                _refresh_locks.pop(oldest_key, None)
            _refresh_locks[ck_key] = threading.Lock()
        return _refresh_locks[ck_key]


def get_refreshed_cookie(old_cookie):
    """Kiểm tra xem cookie này đã được refresh qua Headless OAuth chưa.

    Worker trong thin_aptm.py gọi hàm này sau mỗi engine call để cập nhật st.cookie.
    Trả về cookie string mới hoặc None.
    """
    if not old_cookie:
        return None
    import hashlib
    ck_key = hashlib.md5(old_cookie.encode("utf-8", errors="ignore")).hexdigest()
    with _cookie_updates_lock:
        return _cookie_updates.pop(ck_key, None)


def _parse_cookie_string(cookie):
    """Tách chuỗi cookie 'name=val; name2=val2' thành dict {name: val}."""
    result = {}
    if not cookie:
        return result
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, val = part.partition("=")
            result[name.strip()] = val.strip()
    return result


def _merge_cookies(old_cookie, new_pairs):
    """Merge dict cookie mới vào chuỗi cookie cũ (update existing + add new)."""
    import re
    updated = old_cookie
    for name, val in new_pairs.items():
        pattern = re.compile(rf'(?<![.\w]){re.escape(name)}=[^;]*')
        if pattern.search(updated):
            updated = pattern.sub(f"{name}={val}", updated)
        else:
            updated = f"{updated}; {name}={val}"
    return updated


def _collect_set_cookies(response, target_dict):
    """Thu thập tất cả Set-Cookie headers từ response vào target_dict."""
    try:
        sc_list = []
        if hasattr(response.headers, 'getlist'):
            sc_list = response.headers.getlist("set-cookie")
        elif hasattr(response.headers, 'get_list'):
            sc_list = response.headers.get_list("set-cookie")
        else:
            sc = response.headers.get("set-cookie")
            if sc:
                sc_list = [sc]

        for sc in sc_list:
            if not sc:
                continue
            cookie_part = sc.split(";")[0].strip()
            if "=" in cookie_part:
                name, _, val = cookie_part.partition("=")
                name = name.strip()
                if name and not name.startswith(("Path", "Domain", "Expires", "Max-Age",
                                                  "SameSite", "Secure", "HttpOnly")):
                    target_dict[name] = val.strip()
    except Exception:
        pass


def headless_oauth_refresh(cookie, proxy=None):
    """Làm mới cookie NextAuth bằng HTTP thuần (Headless OAuth Refresh — v1.0.6).

    Khi access_token bị ACCESS_TOKEN_REFRESH_NEEDED nhưng cookie Google session
    (SID, SAPISID...) vẫn còn sống, hàm này giả lập luồng OAuth redirect:
      1. Lấy CSRF token từ cookie / endpoint /api/auth/csrf
      2. POST /api/auth/signin/google → nhận OAuth URL
      3. Follow Google OAuth redirect (cookie Google tự xác thực)
      4. Nhận cookie NextAuth mới từ Set-Cookie header
      5. GET /api/auth/session → Bearer token mới

    Trả về: (new_cookie_str, access_token) hoặc (None, None) nếu thất bại.
    """
    if not cookie or not isinstance(cookie, str):
        return None, None

    import re, hashlib

    # ── DOUBLE-CHECKED LOCKING (v1.0.6 pattern) ──
    ck_key = hashlib.md5(cookie.encode("utf-8", errors="ignore")).hexdigest()

    # Check 1: Ngoài khóa — có thể luồng khác đã refresh xong
    with _session_lock:
        entry = _session_token_cache.get(ck_key)
        if entry and time.time() - entry.get("ts", 0) < 900:
            with _cookie_updates_lock:
                cached_ck = _cookie_updates.get(ck_key)
            return cached_ck, entry.get("token")

    # Lấy per-cookie lock
    lock = _get_refresh_lock(ck_key)
    if not lock.acquire(timeout=60):
        _log_err("headless_oauth_refresh: Timeout chờ lock 60s")
        return None, None

    try:
        # Check 2: Trong khóa — luồng trước có thể đã refresh thành công
        with _session_lock:
            entry = _session_token_cache.get(ck_key)
            if entry and time.time() - entry.get("ts", 0) < 900:
                with _cookie_updates_lock:
                    cached_ck = _cookie_updates.get(ck_key)
                return cached_ck, entry.get("token")

        # Cũng check cookie mới — luồng trước có thể đã update cookie
        with _cookie_updates_lock:
            if ck_key in _cookie_updates:
                new_ck = _cookie_updates[ck_key]
                new_key = hashlib.md5(new_ck.encode("utf-8", errors="ignore")).hexdigest()
                with _session_lock:
                    entry2 = _session_token_cache.get(new_key)
                    if entry2 and time.time() - entry2.get("ts", 0) < 900:
                        return new_ck, entry2.get("token")

        _log_api("headless_oauth_refresh: 🔄 Bắt đầu Headless OAuth Refresh...")

        # ── BƯỚC 1: Lấy CSRF token ──
        csrf_token = None
        cookie_dict = _parse_cookie_string(cookie)

        for csrf_name in ("__Host-next-auth.csrf-token", "next-auth.csrf-token"):
            raw = cookie_dict.get(csrf_name)
            if raw:
                csrf_token = raw.split("|")[0] if "|" in raw else raw
                break

        # Fallback: GET /api/auth/csrf endpoint
        if not csrf_token:
            try:
                h = {"User-Agent": UA_FF, "Cookie": cookie,
                     "Referer": "https://labs.google/fx/tools/flow"}
                r = _get_session(proxy).get("https://labs.google/fx/api/auth/csrf",
                             headers=h, **_kw(15, proxy=proxy))
                if r.status_code == 200:
                    data = r.json() if hasattr(r, "json") else json.loads(r.text)
                    csrf_token = data.get("csrfToken")
                    # Cũng thu thập Set-Cookie (có thể nhận csrf-token mới)
                    new_sc = {}
                    _collect_set_cookies(r, new_sc)
                    if new_sc:
                        cookie = _merge_cookies(cookie, new_sc)
            except Exception as e:
                _log_err(f"headless_oauth_refresh: Lấy CSRF từ endpoint lỗi: {e}")

        if not csrf_token:
            _log_err("headless_oauth_refresh: ❌ Không tìm thấy CSRF token")
            return None, None

        # ── BƯỚC 2: POST /api/auth/signin/google → Nhận OAuth URL ──
        headers_post = {
            "User-Agent": UA_FF,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://labs.google",
            "Referer": "https://labs.google/fx/tools/flow",
            "Cookie": cookie,
        }
        form_data = (
            f"csrfToken={urllib.parse.quote(csrf_token, safe='')}"
            f"&callbackUrl={urllib.parse.quote('https://labs.google/fx/tools/flow', safe='')}"
            f"&json=true"
        )

        kw = _kw(30, proxy=proxy)
        r = _get_session(proxy).post("https://labs.google/fx/api/auth/signin/google",
                      headers=headers_post, data=form_data, allow_redirects=False, **kw)

        # Thu thập Set-Cookie từ response POST
        post_cookies = {}
        _collect_set_cookies(r, post_cookies)
        if post_cookies:
            cookie = _merge_cookies(cookie, post_cookies)

        oauth_url = None
        if r.status_code == 200:
            try:
                data = r.json() if hasattr(r, "json") else json.loads(r.text)
                oauth_url = data.get("url")
            except Exception:
                pass
        elif r.status_code in (301, 302, 303, 307, 308):
            oauth_url = r.headers.get("Location")

        if not oauth_url:
            _log_err(f"headless_oauth_refresh: ❌ Không nhận được OAuth URL "
                     f"(HTTP {r.status_code}, text={r.text[:200] if r.text else ''})")
            return None, None

        _log_api("headless_oauth_refresh: 🔗 Nhận OAuth URL, follow redirects...")

        # ── BƯỚC 3: Follow Google OAuth redirect chain ──
        new_cookies = {}
        new_cookies.update(post_cookies)
        current_url = oauth_url

        for redirect_i in range(20):
            headers_redir = {
                "User-Agent": UA_FF,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Cookie": cookie,
            }

            try:
                r = _get_session(proxy).get(current_url, headers=headers_redir,
                             allow_redirects=False, **_kw(30, proxy=proxy))
            except Exception as e_redir:
                _log_err(f"headless_oauth_refresh: Redirect #{redirect_i} exception: {e_redir}")
                break

            _collect_set_cookies(r, new_cookies)

            if r.status_code in (301, 302, 303, 307, 308):
                next_url = r.headers.get("Location", "")
                if not next_url:
                    break
                if next_url.startswith("/"):
                    parsed = urllib.parse.urlparse(current_url)
                    next_url = f"{parsed.scheme}://{parsed.netloc}{next_url}"
                current_url = next_url
                # Cập nhật cookie header liên tục
                if new_cookies:
                    cookie = _merge_cookies(cookie, new_cookies)
                continue
            else:
                break

        # ── BƯỚC 4: Kiểm tra cookie NextAuth mới ──
        new_session = (new_cookies.get("__Secure-next-auth.session-token")
                       or new_cookies.get("next-auth.session-token"))

        if not new_session:
            _log_err(f"headless_oauth_refresh: ❌ Không nhận được cookie NextAuth mới "
                     f"(thu {len(new_cookies)} cookies: {list(new_cookies.keys())[:10]})")
            return None, None

        # ── BƯỚC 5: Merge cookie mới vào chuỗi cũ ──
        updated_cookie = _merge_cookies(cookie, new_cookies)

        # ── BƯỚC 6: Lấy access_token mới ──
        session_headers = {
            "User-Agent": UA_FF,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://labs.google/fx/tools/flow",
            "Cookie": updated_cookie,
        }
        r = _get_session(proxy).get("https://labs.google/fx/api/auth/session",
                     headers=session_headers, **_kw(30, proxy=proxy))

        if r.status_code == 200:
            text = r.text or ""
            if "ACCESS_TOKEN_REFRESH_NEEDED" not in text:
                try:
                    data = r.json() if hasattr(r, "json") else json.loads(text)
                    tok = data.get("access_token")
                    if tok:
                        new_ck_key = hashlib.md5(
                            updated_cookie.encode("utf-8", errors="ignore")).hexdigest()
                        _cache_put_ts(_session_token_cache, _session_lock, new_ck_key, {"token": tok, "ts": time.time()})
                        _cache_put_ts(_session_token_cache, _session_lock, ck_key, {"token": tok, "ts": time.time()})

                        with _cookie_updates_lock:
                            _cookie_updates[ck_key] = updated_cookie

                        _log_api(f"headless_oauth_refresh: ✅ Thành công! "
                                 f"Cookie NextAuth mới + Bearer (len={len(tok)})")
                        return updated_cookie, tok
                except Exception as e_parse:
                    _log_err(f"headless_oauth_refresh: Parse access_token lỗi: {e_parse}")

        _log_err(f"headless_oauth_refresh: ❌ GET /session thất bại "
                 f"(HTTP {r.status_code})")
        return None, None

    except Exception as e:
        _log_err(f"headless_oauth_refresh: Exception tổng: {e}")
        return None, None
    finally:
        lock.release()




def _h_rest_upload(bearer, token=None):
    """Headers chuẩn Chrome Impersonation cho REST flow/uploadImage (giống AutoVeo3)."""
    headers = {
        "User-Agent": UA_CH,
        "Content-Type": "text/plain;charset=UTF-8",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://labs.google",
        "Referer": "https://labs.google/",
        "Sec-Ch-Ua": '"Google Chrome";v="147", "Not:A-Brand";v="8", "Chromium";v="147"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
        "x-browser-channel": "stable",
        "x-browser-copyright": "Copyright 2025 Google LLC. All Rights reserved.",
        "x-browser-validation": "Aj9fzfu+SaGLBY9Oqr3S7RokOtM=",
        "x-browser-year": "2025",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif bearer and not (";" in str(bearer) or "=" in str(bearer)):
        headers["Authorization"] = f"Bearer {bearer}"
    
    if bearer and (";" in str(bearer) or "=" in str(bearer)):
        headers["Cookie"] = bearer
    return headers

def upload_image_rest(bearer, project, b64_img, filename="input_file_0.jpg", timeout=60, proxy=None, email=None):
    """Gửi yêu cầu upload ảnh tới REST endpoint https://aisandbox-pa.googleapis.com/v1/flow/uploadImage.
    Trả về: (result_or_reason, status)
      - status == "ok"        -> result là media_id (string)
      - status == "violation" -> result là mô tả vi phạm chính sách Google
      - status == "throttle"  -> lỗi 429
      - status == "auth"      -> lỗi 401
      - status == "forbidden" -> lỗi 403
      - status == "proxy_dead"-> lỗi proxy
      - status == "fallback"  -> không phân giải được hoặc lỗi REST khác (caller tự retry REST)
    """
    token = get_session_token(bearer, proxy=proxy)
    headers = _hc(token) if token else _h_rest_upload(bearer)
    session_id = f";{int(time.time()*1000)}"
    rc_ctx = get_recaptcha_context(email=email)
    payload = {
        "clientContext": {
            "sessionId": session_id,
            "projectId": project,
            "tool": "PINHOLE",
            "recaptchaContext": rc_ctx
        },
        "imageBytes": b64_img
    }
    url = f"{BASE}/flow/uploadImage?key={KEY}"
    try:
        kw = _kw(timeout, proxy=proxy)
        r = _api_session(proxy).post(url, headers=headers, json=payload, **kw)
        
        if r.status_code == 401:
            return "unauthorized", "auth"
        if r.status_code == 403:
            return "forbidden", "forbidden"
        if r.status_code == 429:
            return "throttled", "throttle"
        if r.status_code == 407:
            _set_last_proxy_error("HTTP 407 Proxy Authentication Required")
            return "proxy_dead", "proxy_dead"

        text = r.text or ""

        # Nhận diện lỗi vi phạm chính sách Google THẬT SỰ (không tính lỗi cú pháp/tham số INVALID_ARGUMENT)
        if "PUBLIC_ERROR_" in text or "SAFETY_Attribute_" in text or "BLOCK_REASON_" in text or "PROHIBITED_CONTENT" in text:
            if "PUBLIC_ERROR_MINOR" in text:
                return "Lỗi Vi Phạm CS Google - Ảnh đầu vào chứa trẻ em (PUBLIC_ERROR_MINOR)", "violation"
            if "PUBLIC_ERROR_NSFW" in text:
                return "Lỗi Vi Phạm CS Google - Ảnh đầu vào hở hang gợi dục (PUBLIC_ERROR_NSFW)", "violation"
            if "PUBLIC_ERROR_VIOLENCE" in text:
                return "Lỗi Vi Phạm CS Google - Ảnh đầu vào bạo lực/ghê rợn (PUBLIC_ERROR_VIOLENCE)", "violation"
            if "PUBLIC_ERROR_PEOPLE" in text or "PUBLIC_ERROR_PROMINENT_PEOPLE" in text:
                return "Lỗi Vi Phạm CS Google - Nhận diện người thật/người nổi tiếng (PUBLIC_ERROR_PROMINENT_PEOPLE)", "violation"
            if "SAFETY_Attribute_SEXUALLY_EXPLICIT" in text:
                return "Lỗi Vi Phạm CS Google - Nội dung gợi dục (SAFETY_Attribute_SEXUALLY_EXPLICIT)", "violation"
            if "SAFETY_Attribute_DANGEROUS_CONTENT" in text:
                return "Lỗi Vi Phạm CS Google - Nội dung nguy hại (SAFETY_Attribute_DANGEROUS_CONTENT)", "violation"
            if "SAFETY_Attribute_HARASSMENT" in text:
                return "Lỗi Vi Phạm CS Google - Quấy rối/Người nổi tiếng (SAFETY_Attribute_HARASSMENT)", "violation"
            if "BLOCK_REASON_OTHER" in text:
                return "Lỗi Vi Phạm CS Google - Bản quyền hoặc lý do khác (BLOCK_REASON_OTHER)", "violation"
            return f"Lỗi Vi Phạm CS Google: {text[:150]}", "violation"

        # Trích xuất JSON media.name
        js_start = text.find('{')
        js_end = text.rfind('}')
        if js_start >= 0 and js_end > js_start:
            try:
                clean_json_str = text[js_start:js_end + 1]
                data = json.loads(clean_json_str)
                media = data.get("media") or {}
                mid = None
                if isinstance(media, dict):
                    mid = media.get("name")
                elif isinstance(media, list) and len(media) > 0 and isinstance(media[0], dict):
                    mid = media[0].get("name")
                elif "name" in data:
                    mid = data.get("name")
                if not mid:
                    mid = data.get("mediaId")
                if mid:
                    return str(mid), "ok"
            except Exception as e_parse:
                _log_err(f"upload_image_rest parse JSON error: {e_parse}")

        if r.status_code in (200, 201):
            _log_err(f"upload_image_rest HTTP {r.status_code} nhưng không thấy media.name: {text[:200]}")
            return None, "fallback"
        else:
            _log_err(f"upload_image_rest HTTP {r.status_code}: {text[:200]}")
            return None, "fallback"

    except Exception as e:
        kind = net_error_kind(e)
        if kind == "proxy_dead":
            return "proxy_dead", "proxy_dead"
        _log_err(f"upload_image_rest exception: {e}")
        return None, "fallback"


# ---------- UPLOAD ảnh (cho I2V / ảnh tham chiếu) ----------
def upload_image(bearer, project, image_path, timeout=120, max_retries=6, proxy=None, email=None, cookie=None):
    """Upload ảnh lên Google Flow — REST Endpoint DUY NHẤT (giống TstGoogleFlow v1.0.6), KHÔNG fallback BOQ.
    Trả media_id (string) hoặc sentinel error:
      'throttle' | 'unauthorized' | 'forbidden' | 'proxy_dead' | 'vi phạm cs' | 'net_fail'
    """
    import random as _rnd, uuid, io, base64

    if not cookie and isinstance(bearer, str) and ("SID=" in bearer or "OSID=" in bearer):
        cookie = bearer
    try:
        from PIL import Image
        if isinstance(image_path, str) and (image_path.startswith("http://") or image_path.startswith("https://")):
            r_img = _get_session(proxy).get(image_path, **_kw(30, proxy=proxy))
            img = Image.open(io.BytesIO(r_img.content)).convert("RGB")
        elif hasattr(image_path, "convert"):
            img = image_path.convert("RGB")
        else:
            img = Image.open(image_path).convert("RGB")
        
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        _log_err(f"upload_image failed to process image {image_path}: {e}")
        return None

    filename = os.path.basename(str(image_path)) if isinstance(image_path, str) and os.path.isfile(str(image_path)) else "input_file_0.jpg"
    if not filename.lower().endswith((".jpg", ".jpeg")):
        filename = f"{filename}.jpg"

    # ── [BƯỚC 0]: Tra cứu Persistent MD5 Image Cache (AutoVeo3) ──
    md5_hash = compute_image_md5(b64_img)
    acc_tag = email or extract_email_from_cookie(bearer) or project or "default"
    cache_key = make_image_cache_key(md5_hash, acc_tag)
    cached_mid = get_cached_image(cache_key)
    if cached_mid:
        _log_api(f"upload_image: ⚡ CACHE HIT [MD5: {md5_hash[:8]}...] ({acc_tag[:16]}) -> {cached_mid[:30]}...")
        return cached_mid

    # Global rate limiter: giãn tối thiểu 3s giữa các upload mạng (tất cả accounts)
    global _upload_last_ts
    with _upload_lock:
        now = time.time()
        gap = _UPLOAD_MIN_GAP - (now - _upload_last_ts)
        if gap > 0:
            time.sleep(gap)
        _upload_last_ts = time.time()

    # ── Upload qua REST Endpoint DUY NHẤT (/v1/flow/uploadImage) — không fallback BOQ ──
    _rest_token = bearer
    if bearer and ("SID=" in bearer or "OSID=" in bearer):
        _rest_token = get_session_token(bearer, proxy=proxy)
    if not _rest_token:
        _log_err("upload_image: Không lấy được Bearer token → cookie hết hạn")
        return "unauthorized"

    throttle_count = 0
    for attempt in range(max_retries):
        try:
            rest_res, rest_status = upload_image_rest(_rest_token, project, b64_img, filename=filename, timeout=min(timeout, 30), proxy=proxy, email=email)
        except Exception as e:
            kind = net_error_kind(e)
            if kind == "proxy_dead":
                _log_err(f"upload_image proxy dead: {e}")
                return "proxy_dead"
            if kind == "transient" and attempt < max_retries - 1:
                wait = min(3.0 * (1.7 ** attempt), 20.0) + _rnd.uniform(0, 1.5)
                _log_err(f"upload_image lỗi mạng tạm thời (retry {attempt+1}/{max_retries}, chờ {wait:.1f}s): {e}")
                time.sleep(wait)
                continue
            _log_err(f"upload_image request exception: {e}")
            return "net_fail" if kind == "transient" else None

        if rest_status == "ok" and rest_res:
            _log_api(f"upload_image (REST): ✅ Thành công media_id={rest_res}")
            set_cached_image(cache_key, rest_res)
            return rest_res
        if rest_status == "violation":
            _log_err(f"upload_image (REST): ⚠️ Vi phạm chính sách Google ({rest_res})")
            return "vi phạm cs"
        if rest_status == "throttle":
            throttle_count += 1
            if throttle_count >= 2 or attempt >= max_retries - 1:
                _log_err(f"upload_image 429 throttled {throttle_count} lần liên tiếp — trả throttle cho caller")
                return "throttle"
            wait = _rnd.uniform(4.0, 8.0)
            _log_err(f"upload_image 429 throttled — retry {throttle_count}, chờ {wait:.1f}s")
            time.sleep(wait)
            continue
        if rest_status == "proxy_dead":
            _log_err(f"upload_image: proxy dead ({get_last_proxy_error()})")
            return "proxy_dead"
        if rest_status == "auth":
            if "SID=" in str(bearer) or "OSID=" in str(bearer):
                import hashlib
                _ck = hashlib.md5(str(bearer).encode("utf-8", errors="ignore")).hexdigest()
                with _session_lock:
                    _session_token_cache.pop(_ck, None)
            return "unauthorized"
        if rest_status == "forbidden":
            _log_err("upload_image: bị Google cấm tải ảnh (403 Forbidden)")
            return "forbidden"
        # status "fallback" hoặc lỗi HTTP khác — không còn BOQ để fallback, thử lại REST vài lần
        _log_err(f"upload_image (REST) failed status={rest_status}, res={str(rest_res)[:200]}")
        if attempt < max_retries - 1:
            time.sleep(2.0)
            continue
        return None

    if throttle_count > 0:
        return "throttle"
    return "net_fail"

def upload_audio(bearer, project, audio_path, timeout=120, max_retries=2, proxy=None):
    try:
        import base64
        with open(audio_path, "rb") as f:
            b64_audio = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        _log_err(f"upload_audio failed to read audio {audio_path}: {e}")
        return None
    
    payload = {"clientContext": {"sessionId": f";{int(time.time()*1000)}", "projectId": project, "tool": "PINHOLE",
                                 "recaptchaContext": get_recaptcha_context()},
               "audioBytes": b64_audio}
    
    throttle_count = 0
    for attempt in range(max_retries):
        try:
            r = _api_session(proxy).post(f"{BASE}/flow/uploadAudio?key={KEY}", headers=_hc(bearer), data=json.dumps(payload), **_kw(timeout, proxy=proxy))
            
            # fallback if flow/uploadAudio doesn't exist, we might try flow/uploadMedia?
            if r.status_code == 404:
                payload_fallback = {"clientContext": payload["clientContext"], "mediaBytes": b64_audio, "mimeType": "audio/wav"}
                r = _api_session(proxy).post(f"{BASE}/flow/uploadMedia?key={KEY}", headers=_hc(bearer), data=json.dumps(payload_fallback), **_kw(timeout, proxy=proxy))

            if r.status_code in (200, 201):
                media = (r.json() or {}).get("media") or {}
                media_id = media.get("name") if isinstance(media, dict) else (media[0].get("name") if media else None)
                if media_id:
                    return media_id
                else:
                    _log_err(f"upload_audio success but media ID not found. JSON: {r.json()}")
                    return None
            elif r.status_code == 429:
                throttle_count += 1
                wait = min(2 ** attempt + 3, 30)
                time.sleep(wait)
                continue
            elif r.status_code == 401:
                return None
            elif r.status_code == 403:
                return "forbidden"
            else:
                _log_err(f"upload_audio failed status: {r.status_code}, response: {r.text[:300]}")
                return None
        except Exception as e:
            _log_err(f"upload_audio request exception: {e}")
            return None
    if throttle_count > 0:
        return "throttle"
    return None


# ---------- BYPASS UPLOAD 429: Image Laundering (học từ AutoVeo3) ----------
# Khi TK chính bị 429 upload, "giặt" ảnh qua TK donor:
#   1) Upload ảnh gốc lên project DONOR (chưa bị 429)
#   2) Dùng AI tạo ảnh "y hệt" (LAUNDER_PROMPT) → media_id mới trên donor
#   3) Tải ảnh laundered về → upload lên project CHÍNH → media_id sạch
LAUNDER_PROMPT = (
    "Reproduce the reference image exactly as-is. "
    "Keep the identical subject, framing, crop, composition, "
    "camera angle, zoom level, background and all visual details. "
    "Do not zoom, pan, recrop, re-pose, or change anything about the content. "
    "If the reference has any added border, frame, padding, margin, "
    "or colored bars around the edges, remove them so the photo fills "
    "the frame edge-to-edge. "
    "Return an exact visual duplicate of the photo content "
    "with no surrounding border."
)

def upload_image_via_donor(donor_bearer, donor_project, main_bearer, main_project,
                           image_path, proxy=None, main_proxy=None, timeout=120):
    """Upload ảnh qua TK donor khi TK chính bị 429.
    [Rửa 1/2] Upload ảnh lên TK Donor -> donor_mid
    [Rửa 2/2] Gọi AI tái tạo ảnh trực tiếp TRÊN project TK chính -> nhận mediaId chính sạch.
    Cross-project reference không hoạt động nên phải dùng AI vẽ lại.
    Trả media_id (string) nếu thành công, None nếu thất bại.
    """
    import random as _rnd

    # Bước 1: Upload ảnh gốc lên project DONOR
    donor_mid = upload_image(donor_bearer, donor_project, image_path,
                             timeout=timeout, max_retries=4, proxy=proxy)
    if not donor_mid or donor_mid in ("throttle", "forbidden", "proxy_dead"):
        _log_err(f"bypass_donor: upload lên donor thất bại ({donor_mid})")
        return None

    # Bước 2: Dùng generate_image() với LAUNDER_PROMPT để "giặt" ảnh
    # Gọi AI trên project CHÍNH (main_bearer, main_project) với reference là donor_mid
    image_inputs = [{"imageInputType": "IMAGE_INPUT_TYPE_REFERENCE", "name": donor_mid}]
    seed = _rnd.randint(1, 999999)
    kind, result = generate_image(
        main_bearer, main_project, LAUNDER_PROMPT, seed,
        "IMAGE_ASPECT_RATIO_PORTRAIT",
        model="GEM_PIX_2",
        image_inputs=image_inputs,
        timeout=90,
        proxy=main_proxy or proxy,
    )
    
    if kind != "ok" or not result:
        _log_err(f"bypass_donor: generate_image trên TK chính thất bại: kind={kind}, detail={result}")
        if kind == "quota_hard":
            return "quota_hard"
        return None

    # Lấy name (mediaId chính) từ result
    new_mid = result.get("name")
    if new_mid:
        _log_err(f"bypass_donor: OK — AI tái tạo ảnh thành công, mediaId mới: {new_mid[:30]}...")
        return new_mid
        
    _log_err("bypass_donor: batchGenerateImages thành công nhưng không trả về trường 'name'.")
    return None


def _classify(r):
    """Phân loại lỗi HTTP response cho generate_image."""
    if r.status_code in (401, 403):
        return "auth", None
    txt = r.text or ""
    head = txt[:200].lower()
    if "<html" in head or "sorry" in head:
        return "ip_block", None
    if r.status_code == 429:
        return "throttle", None
    return "failed", None


# ---------- IMAGE (bypass) ----------
def generate_image(bearer, project, prompt, seed, aspect, model="GEM_PIX_2", image_inputs=None, timeout=90, proxy=None):
    ctx = {"recaptchaContext": {"token": BYPASS_TOKEN, "applicationType": APP_ANDROID}, "projectId": project, "tool": "PINHOLE", "sessionId": f";{int(time.time()*1000)}"}
    req = {"clientContext": dict(ctx), "imageModelName": model, "imageAspectRatio": aspect,
           "structuredPrompt": {"parts": [{"text": prompt}]}, "seed": seed, "imageInputs": image_inputs or []}
    payload = {"clientContext": ctx, "mediaGenerationContext": {"batchId": str(uuid.uuid4())}, "useNewMedia": True, "requests": [req]}
    try:
        r = _api_session(proxy).post(f"{BASE}/projects/{project}/flowMedia:batchGenerateImages?key={KEY}", headers=_hf(bearer), data=json.dumps(payload), **_kw(timeout, proxy=proxy))
    except Exception as exc:
        import traceback
        return "retry", f"Exception: {type(exc).__name__}: {exc}"
    if r.status_code == 200:
        body = r.json()
        for m in (body.get("media") or []):
            gi = (m.get("image") or {}).get("generatedImage") or {}
            if gi.get("fifeUrl") or gi.get("encodedImage") or m.get("name"):
                return "ok", {"fife": gi.get("fifeUrl"), "b64": gi.get("encodedImage"), "name": m.get("name")}
        # Debug: trả lý do thất bại
        debug = str(body)[:300]
        return "retry", f"200 no image: {debug}"
    # Non-200: trả status + body
    detail = f"HTTP {r.status_code}: {r.text}"
    classified = _classify(r)
    return classified[0], f"{classified[0]} — {detail}"


# ---------- VIDEO (BOQ RPC): submit -> poll -> download ----------

# ── RecaptchaContext: 2 chế độ ──
_recaptcha_farm = None  # instance RecaptchaFarm, set từ thin_aptm.py khi user bật

def set_recaptcha_farm(farm):
    """Gắn RecaptchaFarm instance. Gọi từ thin_aptm.py khi user chọn mode Token Farm."""
    global _recaptcha_farm
    _recaptcha_farm = farm


def get_recaptcha_token(timeout=15, action="VIDEO_GENERATION", email=None):
    """Lấy token reCAPTCHA Enterprise tươi từ Token Farm theo action, GẮN THEO TÀI KHOẢN (email).
    Có email → chỉ lấy token do trình duyệt của chính tài khoản đó farm (cùng IP proxy + cùng phiên
    với lệnh submit) → khớp bối cảnh, tránh UNUSUAL_ACTIVITY."""
    global _recaptcha_farm
    if _recaptcha_farm:
        tok = _recaptcha_farm.get_token(timeout=timeout, action=action, email=email)
        if tok:
            return tok
        return None  # farm đã có nhưng hết token → KHÔNG tạo farm mới
    try:
        import recaptcha_farm as RF
        farm = RF.get_farm()
        if farm and not farm._started:
            farm.start()
        _recaptcha_farm = farm
        tok = farm.get_token(timeout=timeout, action=action, email=email)
        if tok:
            return tok
    except Exception as e:
        _log_err(f"get_recaptcha_token exception: {e}")
    return None


def get_recaptcha_context(email=None):
    """Lấy recaptchaContext phù hợp cho image upload / legacy endpoints (gắn theo tài khoản nếu có email)."""
    tok = get_recaptcha_token(timeout=2, action="UPLOAD_IMAGE", email=email) or get_recaptcha_token(timeout=2, email=email)
    if tok:
        return {"applicationType": "RECAPTCHA_APPLICATION_TYPE_UNSPECIFIED", "token": tok}
    return {"applicationType": APP_ANDROID, "token": BYPASS_TOKEN}


def submit_video(bearer, project, prompt, seed, aspect, model, ref_media_id=None, timeout=120, proxy=None,
                 cookie=None, email=None, allow_model_fallback=False):
    """Submit video — REST API duy nhất (giống TstGoogleFlow v1.0.6), KHÔNG fallback BOQ/native browser.
    Cookie chết hoàn toàn (get_session_token thất bại cả 2 tầng) → trả "auth" ngay, không thử gì thêm.
    HTTP 403 → retry ĐÚNG 1 LẦN với recaptcha token thật mới, không lặp thêm.
    allow_model_fallback=True: khi hết quota model miễn phí, tự thử model Omni Flash (TỐN CREDIT) đúng
    1 lần trước khi trả quota_hard — xem MODEL_FALLBACK. Mặc định False (không tự tốn credit khi chưa hỏi)."""
    final_prompt = f"{prompt}. {VOICE_DESC}" if VOICE_DESC else prompt

    # Tự động gán cookie nếu cookie rỗng nhưng bearer thực chất là chuỗi cookie
    if not cookie and isinstance(bearer, str) and ("SID=" in bearer or "OSID=" in bearer):
        cookie = bearer

    # Tự động trích xuất email nếu chưa có
    if not email and cookie:
        import re
        m_em = re.search(r'(?:email|EMAIL)=([^;]+)', str(cookie))
        if m_em:
            email = m_em.group(1).strip()

    if not cookie:
        return "auth", None

    _bearer = resolve_access_token(bearer, cookie, proxy=proxy)
    if not _bearer:
        _log_err("submit_video: Không lấy được Bearer token → cookie hết hạn")
        return "auth", None

    _rc = get_recaptcha_token(timeout=15, action="VIDEO_GENERATION", email=email)
    if not _rc:
        _rc = get_recaptcha_token(timeout=5, action="UPLOAD_IMAGE", email=email)
    if not _rc:
        _log_api("submit_video: ⚠️ farm hết token → sẽ retry sau (token bắt buộc)")
        return "retry_soft", []

    r_status, r_ops = submit_video_rest(
        _bearer, project, final_prompt, seed, aspect, model,
        ref_media_id=ref_media_id, rc_token=_rc, timeout=timeout, proxy=proxy
    )
    if r_status == "ok" and r_ops:
        _log_api(f"submit_video: 🚀 REST API Submit thành công! ops={r_ops}")
        return "ok", r_ops

    if r_status == "forbidden_recaptcha_retry":
        _log_err("submit_video: HTTP 403 → lấy recaptcha token thật mới rồi retry đúng 1 lần...")
        _rc2 = get_recaptcha_token(timeout=15, action="VIDEO_GENERATION", email=email)
        if _rc2 and _rc2 != _rc:
            r_status2, r_ops2 = submit_video_rest(
                _bearer, project, final_prompt, seed, aspect, model,
                ref_media_id=ref_media_id, rc_token=_rc2, timeout=timeout, proxy=proxy
            )
            if r_status2 == "ok" and r_ops2:
                _log_api(f"submit_video: 🚀 Retry sau 403 thành công! ops={r_ops2}")
                return "ok", r_ops2
            r_status = r_status2 if r_status2 != "forbidden_recaptcha_retry" else "failed"
        else:
            r_status = "failed"

    if r_status == "auth":
        _log_err("submit_video: REST API trả auth → Bearer hết hạn")
        import hashlib
        _ck = hashlib.md5(cookie.encode("utf-8", errors="ignore")).hexdigest()
        with _session_lock:
            _session_token_cache.pop(_ck, None)
        return "auth", None

    if r_status == "quota_hard" and allow_model_fallback:
        fallback_model = MODEL_FALLBACK.get(model)
        if fallback_model:
            _log_err(f"submit_video: Model {model} hết quota → thử model dự phòng {fallback_model} (TỐN CREDIT), đúng 1 lần...")
            r_status3, r_ops3 = submit_video_rest(
                _bearer, project, final_prompt, seed, aspect, fallback_model,
                ref_media_id=ref_media_id, rc_token=_rc, timeout=timeout, proxy=proxy
            )
            if r_status3 == "ok" and r_ops3:
                _log_api(f"submit_video: 🚀 Thành công với model dự phòng {fallback_model}! ops={r_ops3}")
                return "ok", r_ops3
            # Model dự phòng cũng fail → trả nguyên trạng thái gốc (quota_hard) cho caller xử lý như cũ

    return r_status, None


def _find_status(o, out=None):
    out = out if out is not None else []
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "status" and isinstance(v, str):
                out.append(v)
            else:
                _find_status(v, out)
    elif isinstance(o, list):
        for v in o:
            _find_status(v, out)
    return out


# Khóa có thể chứa lý do thất bại trong response batchCheckAsyncVideoGenerationStatus
_REASON_KEYS = ("reason", "errorReason", "publicErrorMessage", "raiFilteredReason",
                "failureReason", "errorMessage", "message", "detail")


def _find_reasons(o, out=None):
    """Quét đệ quy mọi chuỗi trông giống lý do thất bại (PUBLIC_ERROR_* / *_FILTER*)."""
    out = out if out is not None else []
    if isinstance(o, dict):
        for k, v in o.items():
            if k in _REASON_KEYS and isinstance(v, str) and v.strip():
                up = v.upper()
                if "PUBLIC_ERROR" in up or "FILTER" in up or "RAI" in up or "POLICY" in up:
                    out.append(v.strip())
            else:
                _find_reasons(v, out)
    elif isinstance(o, list):
        for v in o:
            _find_reasons(v, out)
    return out


# Lý do = vi phạm chính sách vĩnh viễn (retry vô ích, KHÔNG rewrite được).
# AUDIO_FILTERED xử lý riêng ở GUI: nhờ Gemini viết lại prompt rồi thử lại.
POLICY_TOKENS = ("DANGER_FILTER", "PROMINENT_PEOPLE", "IP_INPUT_IMAGE",
                 "PUBLIC_ERROR_MINOR", "CHILD", "SEXUAL", "RAI_FILTERED")


def is_policy_reason(reason, include_audio=False):
    """True nếu `reason` là lỗi vi phạm chính sách (job nên đánh 'vi phạm cs', không retry)."""
    if not reason:
        return False
    up = str(reason).upper()
    if include_audio and "AUDIO_FILTERED" in up:
        return True
    return any(tok in up for tok in POLICY_TOKENS)


_FAIL_STATUS_TOKENS = ("FAILED", "FAILURE", "REJECTED", "CANCELLED", "CANCELED", "ERROR")
_DONE_STATUS_TOKENS = ("SUCCEEDED", "SUCCESSFUL", "COMPLETED", "COMPLETE", "DONE")


def check_video_status(bearer, ops, timeout=30, proxy=None):
    """Hỏi trạng thái render THẬT qua batchCheckAsyncVideoGenerationStatus.

    Endpoint media.getMediaUrlRedirect chỉ trả 404 cho cả 'đang render' và 'render fail'
    nên không phân biệt được. Endpoint này trả status + lý do (PUBLIC_ERROR_*).

    Trả ('done'|'failed'|'running', reason_or_None), hoặc (None, None) nếu không đọc được
    (server đổi schema / lỗi mạng) -> caller cứ tiếp tục poll như cũ.
    """
    if not ops:
        return None, None
    payloads = (
        {"operations": [{"operation": {"name": n}} for n in ops]},
        {"operations": [{"name": n} for n in ops]},
    )
    for payload in payloads:
        try:
            r = _api_session(proxy).post(CHECK, headers=_hf(bearer), data=json.dumps(payload),
                          **_kw(timeout, proxy=proxy))
        except Exception as e:
            _log_api(f"check_video_status exception: {e}")
            return None, None
        if r.status_code != 200:
            _log_api(f"check_video_status HTTP {r.status_code}: {r.text[:200]}")
            continue     # thử shape payload kế tiếp
        try:
            body = r.json() or {}
        except Exception:
            return None, None
        statuses = [s.upper() for s in _find_status(body)]
        reasons = _find_reasons(body)
        reason = reasons[0] if reasons else None
        _log_api(f"check_video_status: statuses={statuses} reason={reason}")
        if not statuses and not reason:
            return None, None
        if reason or any(any(t in s for t in _FAIL_STATUS_TOKENS) for s in statuses):
            return "failed", reason
        if statuses and all(any(t in s for t in _DONE_STATUS_TOKENS) for s in statuses):
            return "done", None
        return "running", None
    return None, None


def poll_video(bearer, ops, cookie=None, max_attempts=120, interval=5.0, timeout=60, proxy=None,
               initial_wait=20.0, status_every=6, project=None):
    """Thăm dò trạng thái render video — REST API DUY NHẤT (giống TstGoogleFlow v1.0.6), KHÔNG fallback BOQ.
    Timing: 8s → 11s → 14s → 17s → 20s (trần), timeout 15 phút — xem poll_video_rest()."""
    if not ops:
        return "failed", "ops_empty", None
    media_id = ops[0]

    _bearer = resolve_access_token(bearer, cookie, proxy=proxy)
    if not _bearer:
        _log_err("poll_video: Không lấy được Bearer token → cookie hết hạn")
        return "auth", None, None

    cookie = cookie or (bearer if isinstance(bearer, str) and "SID=" in str(bearer) else None)
    _proj = project or (get_project(cookie, proxy=proxy) if cookie else None)
    if not _proj:
        _log_err("poll_video: Không lấy được projectId")
        return "failed", "no_project", None

    return poll_video_rest(_bearer, media_id, _proj, proxy=proxy)

# ---------- GEMINI: viết lại prompt vi phạm chính sách ----------
GEMINI_MODEL = "gemini-flash-lite-latest"   # model Lite có quota dồi dào và tốc độ cao nhất
GEMINI_BEARER_MODEL = "gemini-3.7-flash"  # model dùng cho AI viết prompt qua bearer token

def rewrite_prompt(api_key, prompt, timeout=30, model=None):
    """Nhờ Gemini viết lại prompt bị lọc nội dung -> bản AN TOÀN (giữ ý, tránh vi phạm).
    Trả ('ok', prompt_mới) | ('dead', None) [key sai/hết quyền] | ('busy', None) [429/lỗi -> thử key khác]."""
    if not api_key or not prompt:
        return "busy", None
    model = model or GEMINI_MODEL
    instr = (
        "Rewrite the following text-to-video prompt so it PASSES content-safety filters. "
        "Keep the same product, scene and intent, but remove violence, weapons framed as dangerous, "
        "real people/celebrities, brand logos, and copyrighted music/audio. "
        "Output EXACTLY ONE line containing ONLY the rewritten English prompt — "
        "no preamble, no options, no quotes, no markdown.\n\nPROMPT: " + prompt
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": instr}]}], "generationConfig": {"temperature": 1.0}}
    try:
        r = _get_session(None).post(url, headers={"Content-Type": "application/json"}, data=json.dumps(payload), **_kw(timeout))
    except Exception as e:
        _log_err(f"rewrite_prompt exception: {e}")
        return "busy", None
    if r.status_code == 200:
        try:
            cand = ((r.json().get("candidates") or [{}])[0])
            parts = (cand.get("content") or {}).get("parts") or []
            text = " ".join(p.get("text", "") for p in parts).strip()
            return ("ok", text) if text else ("busy", None)   # có thể bị chính Gemini chặn -> thử lại/key khác
        except Exception:
            return "busy", None
    if r.status_code in (400, 401, 403):
        return "dead", None                                    # key sai / hết quyền → loại key
    if r.status_code == 429:
        return "busy", None                                    # key hết quota tạm → thử key khác
    _log_err(f"rewrite_prompt Gemini status {r.status_code}: {r.text[:150]}")
    return "busy", None


CHAR_STYLES = {
    "stickman": "minimalist character with round white featureless head, wearing grey t-shirt and dark pants",
    "stickman_hoodie": "minimalist character with round white featureless head, wearing dark hoodie and black pants",
    "anime": "anime-style young male character with dark messy hair, wearing casual dark clothing",
    "chibi": "cute chibi-style character with oversized round head, small body, wearing simple grey outfit",
    "silhouette": "dark silhouette of a person, strong backlit dramatic lighting",
}

def generate_video_prompts(topic, num_scenes=5, char_style="stickman", timeout=60,
                           api_key=None, cookie=None, proxy=None):
    """Dùng Gemini để sinh prompt Veo từ chủ đề tiếng Việt.
    Auth ưu tiên: api_key (Gemini API key) → cookie (bearer từ Google account).
    Trả ('ok', [list_of_prompts]) | ('dead', None) | ('busy', None)."""
    style_desc = CHAR_STYLES.get(char_style, CHAR_STYLES["stickman"])

    instr = (
        f"Take the following Vietnamese topic/theme and generate exactly {num_scenes} scenes for a vertical video.\n"
        f"For each scene, you MUST generate exactly two parts separated by a vertical bar '|':\n"
        f"Part 1 (before '|'): A detailed English text-to-video prompt for Google Veo. It must describe the character action, background, mood, lighting, metaphor, consistent style '{style_desc}', and must end with 'vertical 9:16'.\n"
        f"Part 2 (after '|'): A short, highly engaging, and powerful Vietnamese narration/voiceover line (1 sentence, no quotes) that matches the scene content and will be read aloud. It must tell a cohesive story across the scenes.\n\n"
        f"Format for each line:\n"
        f"English Prompt | Lời thoại thuyết minh tiếng Việt\n\n"
        f"Output EXACTLY {num_scenes} lines, one line per scene. No numbering, no introductory text, no markdown. The first scene should be the title/intro, and the last scene should be the conclusion.\n\n"
        f"Topic: {topic}"
    )

    # --- Xác định auth: API key hoặc bearer token ---
    if api_key:
        model = GEMINI_MODEL  # dùng model đã proven (gemini-flash-latest)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
    elif cookie:
        bearer, _email, _new_cookie = bearer_from_cookie(cookie, proxy=proxy)
        if not bearer:
            return "dead", None
        model = GEMINI_BEARER_MODEL
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {bearer}"}
    else:
        return "dead", None

    payload = {"contents": [{"parts": [{"text": instr}]}], "generationConfig": {"temperature": 1.0}}

    try:
        r = _get_session(proxy).post(url, headers=headers, data=json.dumps(payload), **_kw(timeout, proxy=proxy))
    except Exception as e:
        _log_err(f"generate_video_prompts exception: {e}")
        return "busy", None

    if r.status_code == 200:
        try:
            cand = ((r.json().get("candidates") or [{}])[0])
            parts = (cand.get("content") or {}).get("parts") or []
            text = " ".join(p.get("text", "") for p in parts).strip()

            prompts = [p.strip() for p in text.split('\n') if p.strip()]
            if not prompts:
                return "busy", "Không tìm thấy prompt trong phản hồi từ Gemini."
            return "ok", prompts
        except Exception as e:
            return "busy", f"Lỗi parse JSON: {e}"

    # Lấy thông báo lỗi chi tiết từ phản hồi JSON của Google
    try:
        err_msg = r.json().get("error", {}).get("message", r.text[:200])
    except Exception:
        err_msg = r.text[:200]

    if r.status_code in (400, 401, 403):
        _log_err(f"generate_video_prompts auth fail {r.status_code}: {err_msg}")
        return "dead", f"Lỗi xác thực {r.status_code}: {err_msg}"
    if r.status_code == 429:
        return "busy", f"Hết hạn ngạch (429): {err_msg}"

    _log_err(f"generate_video_prompts Gemini status {r.status_code}: {err_msg}")
    return "busy", f"Lỗi Google {r.status_code}: {err_msg}"


# Mã trả về đặc biệt của download_video (số byte > 0 = thành công)
DL_PROXY_DEAD = -1   # proxy chết → caller nên đổi proxy rồi requeue
DL_NET_FAIL = -2     # lỗi mạng tạm thời, đã hết lượt retry → caller nên requeue


def download_video(media_id, cookie, dst, timeout=180, proxy=None, max_retries=3):
    """Tải video trực tiếp từ Google CDN hoặc qua media_id."""
    if not media_id:
        return 0

    # Nếu media_id là URL CDN trực tiếp
    if str(media_id).startswith("http://") or str(media_id).startswith("https://"):
        return download_url(media_id, dst, timeout=timeout, proxy=proxy)

    # Nếu media_id là scene UUID: dùng Iyc41d để tìm signed URL CDN flow-content.google/video/...
    if cookie:
        try:
            proj_id = get_project(cookie, proxy=proxy) or "513f3b20-fa17-4be7-89b5-f179860de580"
            iyc_res, _ = boq_execute("Iyc41d", json.dumps([[media_id]]), cookie, proxy=proxy, timeout=30, source_path=f"/project/{proj_id}")
            if iyc_res:
                import re
                m_vids = re.findall(r'https://flow-content\.google/video/[^\s"\',]+', json.dumps(iyc_res))
                if not m_vids:
                    m_vids = re.findall(r'https://[^\s"\',]*\.google(?:usercontent)?\.com/video/[^\s"\',]+', json.dumps(iyc_res))
                if m_vids:
                    return download_url(m_vids[0], dst, timeout=timeout, proxy=proxy)
        except Exception as e:
            _log_err(f"download_video Iyc41d resolution exception: {e}")

    # Fallback trpc redirect
    H = {"Cookie": cookie or "", "User-Agent": UA_CH, "Referer": "https://flow.google.com/", "Accept": "*/*"}
    for attempt in range(max_retries):
        try:
            r = _get_session(proxy).get(f"https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name={media_id}", headers=H,
                         **_kw(timeout, proxy=proxy), allow_redirects=True, stream=True)
            try:
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("video"):
                    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                    tmp_dst = f"{dst}.part"
                    total = 0
                    first_chunk = b""
                    with open(tmp_dst, "wb") as f:
                        for chunk in r.iter_content(chunk_size=262144):
                            if not chunk:
                                continue
                            if total == 0:
                                first_chunk = chunk[:32]
                            f.write(chunk)
                            total += len(chunk)
                    if total > 10000 and (b"ftyp" in first_chunk or b"moov" in first_chunk):
                        os.replace(tmp_dst, dst)
                        return total
                    try: os.remove(tmp_dst)
                    except Exception: pass
                return 0
            finally:
                try: r.close()
                except Exception: pass
        except Exception as e:
            kind = net_error_kind(e)
            if kind == "proxy_dead":
                return DL_PROXY_DEAD
            if kind == "transient" and attempt < max_retries - 1:
                time.sleep(3.0 * (attempt + 1))
                continue
            return DL_NET_FAIL if kind == "transient" else 0
    return 0


def download_url(url, dst, timeout=120, proxy=None):
    try:
        r = _get_session(proxy).get(url, headers={"User-Agent": UA_CH}, stream=True, **_kw(timeout, proxy=proxy))
        try:
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            tmp_dst = f"{dst}.part"
            total = 0
            first_chunk = b""
            with open(tmp_dst, "wb") as f:
                for chunk in r.iter_content(chunk_size=262144):
                    if not chunk:
                        continue
                    if total == 0:
                        first_chunk = chunk[:32]
                    f.write(chunk)
                    total += len(chunk)
            # Xác thực đây là file MP4 hợp lệ, tuyệt đối KHÔNG chấp nhận HTML hoặc file hỏng
            if total > 10000 and (b"ftyp" in first_chunk or b"moov" in first_chunk or b"\x00\x00\x00" in first_chunk[:4]):
                os.replace(tmp_dst, dst)
                return total
            else:
                _log_err(f"download_url từ chối file không phải MP4 từ {url[:80]}: len={total}, header={repr(first_chunk)}")
                try: os.remove(tmp_dst)
                except Exception: pass
        finally:
            try: r.close()
            except Exception: pass
    except Exception as e:
        _log_err(f"download_url exception: {e}")
    return 0
