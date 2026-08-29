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

BASE = "https://aisandbox-pa.googleapis.com/v1"
KEY = "AIzaSyBtrm0o5ab1c-Ec8ZuLcGt3oJAA5VWt3pY"
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

GEN_T2V = f"{BASE}/video:batchAsyncGenerateVideoText"
GEN_I2V = f"{BASE}/video:batchAsyncGenerateVideoReferenceImages"
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

# Mô tả giọng nói cố định — gắn vào cuối mọi prompt để giữ giọng nhất quán giữa các video
# Đặt chuỗi rỗng "" để tắt.
VOICE_DESC = ""

VOICE_PRESETS = {
    "vi": "Narrated by a young Vietnamese woman, approximately 20 years old, with a deep, powerful, and authoritative voice speaking in Vietnamese",
    "id": "Narrated by a young Indonesian woman, approximately 20 years old, with a deep, powerful, and authoritative voice speaking in Bahasa Indonesia",
    "my": "Narrated by a young Malaysian woman, approximately 20 years old, with a deep, powerful, and authoritative voice speaking in Bahasa Melayu",
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
        return "proxy_dead"
    if any(p in s for p in _TRANSIENT_PATTERNS):
        return "transient"
    return "other"


def is_net_retryable(value):
    """True nếu `value` là sentinel lỗi mạng mà caller nên requeue job (KHÔNG đánh lỗi cứng)."""
    return value in ("net_fail", "proxy_dead", "throttle")


# ---------- AUTH ----------
def update_cookie_string(old_cookie, set_cookie_headers):
    """Cập nhật các cookie mới từ Set-Cookie headers vào chuỗi cookie cũ."""
    if not set_cookie_headers:
        return old_cookie
    if isinstance(set_cookie_headers, str):
        set_cookie_headers = [set_cookie_headers]
    
    cookie_dict = {}
    for part in old_cookie.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            cookie_dict[k.strip()] = v.strip()
            
    for set_cookie in set_cookie_headers:
        first_part = set_cookie.split(";")[0]
        if "=" in first_part:
            k, v = first_part.strip().split("=", 1)
            cookie_dict[k.strip()] = v.strip()
            
    return "; ".join(f"{k}={v}" for k, v in cookie_dict.items())


def bearer_from_cookie(cookie, timeout=25, proxy=None):
    if not cookie:
        return None, None, None
    H = {"Cookie": cookie, "User-Agent": UA_CH, "Referer": "https://labs.google/", "Accept": "application/json"}
    try:
        r = cffi.get("https://labs.google/fx/api/auth/session", headers=H, **_kw(timeout, proxy=proxy))
        if r.status_code == 200:
            set_cookies = r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list") else r.headers.get("set-cookie")
            new_cookie = update_cookie_string(cookie, set_cookies) if set_cookies else cookie
            j = r.json() or {}
            exp = j.get("expires")
            if exp:
                try:
                    from datetime import datetime
                    if datetime.fromisoformat(str(exp).replace("Z", "+00:00")).timestamp() < time.time() + 120:
                        _log_err("bearer_from_cookie: Cookie expired or close to expiration.")
                        return None, None, None
                except Exception as e:
                    _log_err(f"bearer_from_cookie date check exception: {e}")
            token = j.get("access_token")
            if not token:
                return None, None, None
            # Xác thực độ tươi thực tế của access_token với máy chủ Google OAuth2
            try:
                chk = cffi.get(f"https://oauth2.googleapis.com/tokeninfo?access_token={token}", **_kw(5, proxy=proxy))
                if chk.status_code != 200:
                    _log_err(f"bearer_from_cookie: Google OAuth access_token đã hết hạn ({chk.status_code})")
                    return None, None, None
            except Exception:
                pass
            return token, (j.get("user") or {}).get("email"), new_cookie
        else:
            _log_err(f"bearer_from_cookie failed status: {r.status_code}, response: {r.text[:200]}")
    except Exception as e:
        _log_err(f"bearer_from_cookie exception: {e}")
    return None, None, None


def get_project(cookie, proxy=None):
    if not cookie:
        return None
    inp = urllib.parse.quote(json.dumps({"json": {"pageSize": 20, "toolName": "PINHOLE", "cursor": None},
                                         "meta": {"values": {"cursor": ["undefined"]}}}))
    H = {"Cookie": cookie, "User-Agent": UA_CH, "Referer": "https://labs.google/", "Accept": "application/json"}
    try:
        r = cffi.get("https://labs.google/fx/api/trpc/project.searchUserProjects?input=" + inp, headers=H, **_kw(proxy=proxy))
        if r.status_code == 200:
            projs = (((r.json() or {}).get("result") or {}).get("data") or {}).get("json", {}).get("result", {}).get("projects", [])
            if projs:
                return projs[0]["projectId"]
        else:
            _log_err(f"searchUserProjects request failed with status: {r.status_code}, response: {r.text[:200]}")
    except Exception as e:
        _log_err(f"get_project search user projects exception: {e}")
    # tạo mới
    try:
        r = cffi.post("https://labs.google/fx/api/trpc/project.createProject",
                      headers={**H, "Content-Type": "application/json"},
                      data=json.dumps({"json": {"projectTitle": "ThinAptm", "toolName": "PINHOLE"}}), **_kw(proxy=proxy))
        if r.status_code == 200:
            d = (((r.json() or {}).get("result") or {}).get("data") or {}).get("json") or {}
            proj_id = d.get("projectId") or (d.get("result") or {}).get("projectId")
            if proj_id:
                return proj_id
        _log_err(f"createProject failed with status: {r.status_code}, response: {r.text[:200]}")
    except Exception as e:
        _log_err(f"get_project create project exception: {e}")
    return None


def delete_project(cookie, proxy=None):
    """Xóa TẤT CẢ project PINHOLE hiện có. Trả số project đã xóa."""
    if not cookie:
        return 0
    inp = urllib.parse.quote(json.dumps({"json": {"pageSize": 20, "toolName": "PINHOLE", "cursor": None},
                                         "meta": {"values": {"cursor": ["undefined"]}}}))
    H = {"Cookie": cookie, "User-Agent": UA_CH, "Referer": "https://labs.google/", "Accept": "application/json"}
    try:
        r = cffi.get("https://labs.google/fx/api/trpc/project.searchUserProjects?input=" + inp, headers=H, **_kw(proxy=proxy))
        if r.status_code != 200:
            return 0
        projs = (((r.json() or {}).get("result") or {}).get("data") or {}).get("json", {}).get("result", {}).get("projects", [])
        deleted = 0
        for p in projs:
            pid = p.get("projectId")
            if not pid:
                continue
            try:
                rd = cffi.post("https://labs.google/fx/api/trpc/project.deleteProject",
                               headers={**H, "Content-Type": "application/json"},
                               data=json.dumps({"json": {"projectId": pid}}), **_kw(proxy=proxy))
                if rd.status_code == 200:
                    deleted += 1
                    _log_err(f"delete_project: đã xóa project {pid[:12]}...")
            except Exception as e:
                _log_err(f"delete_project: lỗi xóa {pid[:12]}: {e}")
        return deleted
    except Exception as e:
        _log_err(f"delete_project exception: {e}")
        return 0


def reset_project(cookie, proxy=None):
    """Xóa project cũ + tạo project MỚI (học từ AutoVeo3: reset quota upload).
    Trả projectId mới hoặc None."""
    deleted = delete_project(cookie, proxy=proxy)
    if deleted:
        _log_err(f"reset_project: đã xóa {deleted} project cũ, tạo mới...")
    H = {"Cookie": cookie, "User-Agent": UA_CH, "Referer": "https://labs.google/", "Accept": "application/json",
         "Content-Type": "application/json"}
    try:
        r = cffi.post("https://labs.google/fx/api/trpc/project.createProject",
                      headers=H,
                      data=json.dumps({"json": {"projectTitle": "ThinAptm", "toolName": "PINHOLE"}}), **_kw(proxy=proxy))
        if r.status_code == 200:
            d = (((r.json() or {}).get("result") or {}).get("data") or {}).get("json") or {}
            proj_id = d.get("projectId") or (d.get("result") or {}).get("projectId")
            if proj_id:
                _log_err(f"reset_project: project MỚI = {proj_id[:12]}...")
                return proj_id
        _log_err(f"reset_project: createProject failed status {r.status_code}: {r.text[:200]}")
    except Exception as e:
        _log_err(f"reset_project exception: {e}")
    return None


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


# ---------- UPLOAD ảnh (cho I2V / ảnh tham chiếu) ----------
def upload_image(bearer, project, image_path, timeout=120, max_retries=4, proxy=None):
    import random as _rnd
    try:
        from PIL import Image
        import io
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        # Bơm 3 "muối" (salt pixel) tại các vị trí ngẫu nhiên để đổi hoàn toàn SHA256 & byte map
        for _ in range(3):
            px, py = _rnd.randint(0, w-1), _rnd.randint(0, h-1)
            r, g, b = img.getpixel((px, py))
            img.putpixel((px, py), (r, g, max(0, b - 1) if b > 0 else 1))
        
        buf = io.BytesIO()
        # Random chất lượng 89-95 tạo ra cấu trúc DCT block & byte stream hoàn toàn mới chống spam
        img.save(buf, format="JPEG", quality=_rnd.randint(89, 95), optimize=_rnd.choice([True, False]))
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        _log_err(f"upload_image failed to process image {image_path}: {e}")
        return None
    session_id = f";{int(time.time()*1000)}"
    payload = {"clientContext": {"sessionId": session_id, "projectId": project, "tool": "PINHOLE",
                                 "recaptchaContext": get_recaptcha_context()},
               "imageBytes": b64}
    throttle_count = 0
    for attempt in range(max_retries):
        try:
            r = cffi.post(f"{BASE}/flow/uploadImage?key={KEY}", headers=_hc(bearer), data=json.dumps(payload), **_kw(timeout, proxy=proxy))
            if r.status_code in (200, 201):
                media = (r.json() or {}).get("media") or {}
                media_id = media.get("name") if isinstance(media, dict) else (media[0].get("name") if media else None)
                if media_id:
                    return media_id
                else:
                    _log_err(f"upload_image success but media ID not found. JSON: {r.json()}")
                    return None
            elif r.status_code == 429:
                throttle_count += 1
                # Backoff tăng dần: 8→15→25→40s + random jitter
                wait = min(8.0 * (1.8 ** attempt), 45.0) + _rnd.uniform(0, 3.0)
                _log_err(f"upload_image 429 throttled — retry {attempt+1}/{max_retries}, chờ {wait:.1f}s")
                time.sleep(wait)
                continue
            elif r.status_code == 401:
                _log_err(f"upload_image 401 unauthorized")
                return "unauthorized"
            elif r.status_code == 403:
                _log_err(f"upload_image 403 PERMISSION_DENIED — account bị cấm upload ảnh")
                return "forbidden"
            else:
                _log_err(f"upload_image failed status: {r.status_code}, response: {r.text[:300]}")
                return None
        except Exception as e:
            kind = net_error_kind(e)
            if kind == "proxy_dead":
                _log_err(f"upload_image proxy dead: {e}")
                return "proxy_dead"
            if kind == "transient" and attempt < max_retries - 1:
                # Kết nối bị cắt / TLS rác / timeout → THỬ LẠI. Trước đây return None ngay
                # trong except nên bỏ luôn các lượt retry còn lại → mất job oan.
                wait = min(3.0 * (1.7 ** attempt), 20.0) + _rnd.uniform(0, 1.5)
                _log_err(f"upload_image lỗi mạng tạm thời (retry {attempt+1}/{max_retries}, chờ {wait:.1f}s): {e}")
                time.sleep(wait)
                continue
            _log_err(f"upload_image request exception: {e}")
            # Lỗi mạng nhưng đã hết lượt retry → net_fail để caller requeue thay vì đánh lỗi cứng
            return "net_fail" if kind == "transient" else None
    # Hết retry mà vẫn bị 429 → trả "throttle" để caller xử lý đúng (requeue thay vì fail)
    if throttle_count > 0:
        _log_err(f"upload_image 429 throttled {throttle_count} lần liên tiếp — trả throttle cho caller")
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
            r = cffi.post(f"{BASE}/flow/uploadAudio?key={KEY}", headers=_hc(bearer), data=json.dumps(payload), **_kw(timeout, proxy=proxy))
            
            # fallback if flow/uploadAudio doesn't exist, we might try flow/uploadMedia?
            if r.status_code == 404:
                payload_fallback = {"clientContext": payload["clientContext"], "mediaBytes": b64_audio, "mimeType": "audio/wav"}
                r = cffi.post(f"{BASE}/flow/uploadMedia?key={KEY}", headers=_hc(bearer), data=json.dumps(payload_fallback), **_kw(timeout, proxy=proxy))

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


# ---------- IMAGE (bypass) ----------
def generate_image(bearer, project, prompt, seed, aspect, model="GEM_PIX_2", image_inputs=None, timeout=90, proxy=None):
    ctx = {"recaptchaContext": {"token": BYPASS_TOKEN, "applicationType": APP_ANDROID}, "projectId": project, "tool": "PINHOLE", "sessionId": f";{int(time.time()*1000)}"}
    req = {"clientContext": dict(ctx), "imageModelName": model, "imageAspectRatio": aspect,
           "structuredPrompt": {"parts": [{"text": prompt}]}, "seed": seed, "imageInputs": image_inputs or []}
    payload = {"clientContext": ctx, "mediaGenerationContext": {"batchId": str(uuid.uuid4())}, "useNewMedia": True, "requests": [req]}
    try:
        r = cffi.post(f"{BASE}/projects/{project}/flowMedia:batchGenerateImages", headers=_hf(bearer), data=json.dumps(payload), **_kw(timeout, proxy=proxy))
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


# ---------- VIDEO (bypass): submit -> poll -> download ----------

# ── RecaptchaContext: 2 chế độ ──
# 1. "android_bypass" (mặc định): token tĩnh, nhanh nhưng dễ bị rate-limit
# 2. "token_farm": farm reCAPTCHA token tươi qua headless Chrome (giống AutoVeo3)
_recaptcha_farm = None  # instance RecaptchaFarm, set từ thin_aptm.py khi user bật

def set_recaptcha_farm(farm):
    """Gắn RecaptchaFarm instance. Gọi từ thin_aptm.py khi user chọn mode Token Farm."""
    global _recaptcha_farm
    _recaptcha_farm = farm

def get_recaptcha_context():
    """Lấy recaptchaContext phù hợp.
    - Nếu có farm + token tươi → dùng token thật + APPLICATION_TYPE_WEB
    - Fallback → android_bypass (token tĩnh)
    """
    if _recaptcha_farm:
        token = _recaptcha_farm.get_token(timeout=2)
        if token:
            return {"applicationType": "RECAPTCHA_APPLICATION_TYPE_UNSPECIFIED", "token": token}
    # Fallback: bypass tĩnh
    return {"applicationType": APP_ANDROID, "token": BYPASS_TOKEN}

def _vpayload(prompt, project, seed, aspect, model, ref_media_id=None):
    # Ghép mô tả giọng nói cố định vào cuối prompt (nếu có)
    final_prompt = f"{prompt}. {VOICE_DESC}" if VOICE_DESC else prompt
    aspect_enum = VID_ASPECTS.get(aspect, aspect)
    if not str(aspect_enum).startswith("VIDEO_ASPECT_RATIO_"):
        aspect_enum = "VIDEO_ASPECT_RATIO_PORTRAIT"
    req = {"aspectRatio": aspect_enum, "seed": seed, "textInput": {"structuredPrompt": {"parts": [{"text": final_prompt}]}},
           "videoModelKey": model, "metadata": {}}
    if ref_media_id:
        req["referenceImages"] = [{"imageUsageType": "IMAGE_USAGE_TYPE_ASSET", "mediaId": ref_media_id}]
    return {"mediaGenerationContext": {"batchId": str(uuid.uuid4()), "audioFailurePreference": "BLOCK_SILENCED_VIDEOS"},
            "clientContext": {"sessionId": f";{int(time.time()*1000)}", "projectId": project, "tool": "PINHOLE",
                              "userPaygateTier": "PAYGATE_TIER_TWO",
                              "recaptchaContext": get_recaptcha_context()},
            "requests": [req], "useV2ModelConfig": True}



def _classify(r):
    """Phân loại lỗi generate. QUAN TRỌNG: mã 429/RESOURCE_EXHAUSTED KHÔNG đủ để phân biệt —
    phải đọc `reason` trong error.details (đã đo body thật):
      throttle    = USER_REQUESTS_THROTTLED (giới hạn TỐC ĐỘ) -> nghỉ NGẮN vài giây, TỰ HỒI (KHÔNG cách ly dài)
      quota_hard  = hết quota/credit ngày (QUOTA_EXCEEDED/DAILY/CREDIT/OUT_OF...) -> cách ly DÀI + đổi account
      unusual     = reCAPTCHA/UNUSUAL_ACTIVITY -> thử lại nhanh (bypass/token khác)
      ratelimit   = TOO_MUCH_TRAFFIC trần (rate theo IP) -> backoff nhẹ
      ip_block    = HTML "Sorry" (chặn IP) | auth = 401 bearer chết
    RESOURCE_EXHAUSTED không rõ reason -> coi là throttle (thực đo: submit hồi lại sau 1-2 phút, KHÔNG phải hết quota).
    """
    if r.status_code == 401:
        return "auth", None
    if r.status_code == 403:
        return "auth", None                     # PERMISSION_DENIED = cookie/project hết quyền → cần refresh hoặc cách ly
    txt = r.text
    head = txt[:200].lower()
    if "<html" in head or "sorry" in head:
        return "ip_block", None

    reason = ""
    try:
        err = (r.json() or {}).get("error", {})
        for d in err.get("details", []) or []:
            if isinstance(d, dict) and d.get("reason"):
                reason = d["reason"]; break
    except Exception:
        pass
    U = (reason + " " + txt[:400]).upper()

    if "THROTTLED" in U:
        return "throttle", None                 # giới hạn tốc độ -> nghỉ ngắn, tự hồi
    if "RECAPTCHA" in U or "UNUSUAL_ACTIVITY" in U or "PUBLIC_ERROR_UNUSUAL_ACTIVITY" in U:
        return "unusual", None
    if "TOO_MUCH_TRAFFIC" in U:
        return "ratelimit", None
    if ("QUOTA_EXCEEDED" in U or "OUT_OF_CREDIT" in U or "INSUFFICIENT" in U
            or "DAILY" in U or "QUOTA_LIMIT" in U):
        return "quota_hard", None               # hết quota thật -> cách ly dài
    if r.status_code == 429 or "RESOURCE_EXHAUSTED" in U:
        return "throttle", None                 # RESOURCE_EXHAUSTED không rõ -> throttle (mặc định an toàn)
    if "UNUSUAL" in U:
        return "unusual", None
    return "retry", None


def submit_video(bearer, project, prompt, seed, aspect, model, ref_media_id=None, timeout=120, proxy=None):
    _log_api(f"submit_video: model={model} ref={ref_media_id} aspect={aspect}")

    # I2V (có ảnh gốc) BẮT BUỘC dùng model r2v (reference->video); dùng model t2v -> render FAIL.
    # Omni Flash (abra_i2v_*) đã là model i2v sẵn → không cần đổi.
    if ref_media_id and not model.startswith("abra"):
        model = VID_I2V_MODEL
    url = GEN_I2V if ref_media_id else GEN_T2V
    payload = _vpayload(prompt, project, seed, aspect, model, ref_media_id)
    try:
        r = cffi.post(url, headers=_hf(bearer), data=json.dumps(payload), **_kw(timeout, proxy=proxy))
    except Exception as e:
        if net_error_kind(e) == "proxy_dead":
            _log_err(f"submit_video proxy dead: {e}")
            return "proxy_dead", None
        _log_err(f"submit_video HTTP client exception: {e}")
        return "retry", None
    if r.status_code == 200:
        j = r.json()
        ops = []
        for o in j.get("operations", []):
            n = (o.get("operation") or {}).get("name")
            if n:
                ops.append(n)
        if not ops:
            for m in j.get("media", []):
                if m.get("name"):
                    ops.append(m["name"])
        if not ops:
            for wf in j.get("workflows", []):
                pm_id = (wf.get("metadata") or {}).get("primaryMediaId") or wf.get("name")
                if pm_id:
                    ops.append(pm_id)
        if ops:
            _log_api(f"submit_video ok: ops={ops}")
            return "ok", ops
        else:
            _log_err(f"submit_video succeeded but no operations found in JSON: {j}")
            return "retry", None
    # 429 là throttle/quota (thường xuyên, GUI tự xử lý + ghi rõ loại) -> KHÔNG spam log ở đây.
    if r.status_code != 429:
        _log_err(f"submit_video API failed status: {r.status_code}, response: {r.text[:200]}")
    return _classify(r)


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
            r = cffi.post(CHECK, headers=_hf(bearer), data=json.dumps(payload),
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
               initial_wait=20.0, status_every=6):
    """Thăm dò trạng thái render của video.

    Kênh chính: media.getMediaUrlRedirect (302/200+video = xong).
    Kênh phụ:   batchCheckAsyncVideoGenerationStatus, gọi mỗi `status_every` lượt poll để
                phát hiện render FAIL kèm LÝ DO thật (PUBLIC_ERROR_AUDIO_FILTERED,
                DANGER_FILTER, ...). Trước đây hàm này luôn trả "policy" khi hết lượt nên
                không thể phân biệt vi phạm chính sách / timeout / audio bị lọc.

    Trả (kind, detail, credits):
      done       -> detail = media_id
      failed     -> detail = lý do thật (PUBLIC_ERROR_*) nếu đọc được, else "timeout"
      auth       -> bearer chết
      proxy_dead -> proxy hỏng
    """
    if not ops:
        return "failed", "ops_empty", None
    media_id = ops[0]
    credits = None

    # Adaptive Polling: Nghỉ trước 20s vì Google Veo luôn cần tối thiểu 20-35s để tạo video
    if initial_wait and initial_wait > 0:
        time.sleep(initial_wait)

    H = {
        "Authorization": f"Bearer {bearer}" if bearer else "",
        "Cookie": cookie if cookie else "",
        "User-Agent": UA_CH,
        "Referer": "https://labs.google/",
        "Accept": "*/*"
    }
    proxy_fail_count = 0  # Đếm lỗi proxy DNS liên tiếp
    status_supported = bool(bearer)   # tắt kênh phụ nếu server không hiểu payload

    for attempt in range(max_attempts):
        try:
            # Tắt redirect để kiểm tra Location / Content-Type
            r = cffi.get(f"https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name={media_id}",
                         headers=H, **_kw(timeout, proxy=proxy), allow_redirects=False)
            proxy_fail_count = 0  # Reset khi request thành công
        except Exception as e:
            if net_error_kind(e) == "proxy_dead":
                proxy_fail_count += 1
                if proxy_fail_count >= 5:
                    _log_err(f"poll_video proxy dead after {proxy_fail_count} consecutive DNS failures")
                    return "proxy_dead", None, credits
            _log_err(f"poll_video network exception (attempt {attempt+1}/{max_attempts}): {e}")
            time.sleep(interval)
            continue

        if r.status_code == 401:
            _log_err(f"poll_video unauthorized (401)")
            return "auth", None, credits

        if r.status_code in [302, 307] or (r.status_code == 200 and r.headers.get("content-type", "").startswith("video")):
            # Video đã render thành công và sẵn sàng để tải!
            return "done", media_id, credits

        if r.status_code in [404, 500]:
            # 404/500 = ĐANG render HOẶC render đã FAIL — endpoint này không phân biệt được.
            # Hỏi kênh phụ định kỳ để bắt lý do fail sớm thay vì chờ hết max_attempts.
            if status_supported and attempt > 0 and attempt % status_every == 0:
                kind, reason = check_video_status(bearer, ops, proxy=proxy)
                if kind is None:
                    status_supported = False      # server không trả được → thôi hỏi nữa
                elif kind == "failed":
                    _log_err(f"poll_video: render FAILED — lý do: {reason or 'không rõ'}")
                    return "failed", (reason or "render fail"), credits
                elif kind == "done":
                    return "done", media_id, credits
        else:
            _log_err(f"poll_video check unexpected status {r.status_code}, response: {r.text[:200]}")

        time.sleep(interval)

    # Hết lượt poll: hỏi kênh phụ lần cuối để biết fail thật hay chỉ chậm
    if status_supported:
        kind, reason = check_video_status(bearer, ops, proxy=proxy)
        if kind == "failed":
            _log_err(f"poll_video: render FAILED sau {max_attempts} lượt — lý do: {reason or 'không rõ'}")
            return "failed", (reason or "render fail"), credits
        if kind == "done":
            return "done", media_id, credits

    _log_err(f"poll_video timeout sau {max_attempts} lượt (không xác định được lý do).")
    return "failed", "timeout", credits

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
        r = cffi.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(payload), **_kw(timeout))
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
        r = cffi.post(url, headers=headers, data=json.dumps(payload), **_kw(timeout, proxy=proxy))
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
    H = {"Cookie": cookie, "User-Agent": UA_CH, "Referer": "https://labs.google/", "Accept": "*/*"}
    for attempt in range(max_retries):
        try:
            r = cffi.get(f"https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name={media_id}", headers=H,
                         **_kw(timeout, proxy=proxy), allow_redirects=True)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("video"):
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(r.content)
                return len(r.content)
            _log_err(f"download_video failed. status: {r.status_code}, content-type: {r.headers.get('content-type')}, response: {r.text[:200]}")
            return 0
        except Exception as e:
            kind = net_error_kind(e)
            if kind == "proxy_dead":
                _log_err(f"download_video proxy dead: {e}")
                return DL_PROXY_DEAD
            if kind == "transient" and attempt < max_retries - 1:
                # Tải dở bị cắt giữa dòng (rất hay gặp với proxy residential) → thử lại
                wait = 3.0 * (attempt + 1)
                _log_err(f"download_video lỗi mạng tạm thời (retry {attempt+1}/{max_retries}, chờ {wait:.0f}s): {e}")
                time.sleep(wait)
                continue
            _log_err(f"download_video exception: {e}")
            return DL_NET_FAIL if kind == "transient" else 0
    return DL_NET_FAIL


def download_url(url, dst, timeout=120, proxy=None):
    data = cffi.get(url, **_kw(timeout, proxy=proxy)).content
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "wb") as f:
        f.write(data)
    return len(data)
