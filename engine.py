"""
Thìn Aptm — Engine tạo VIDEO + ẢNH Google Flow bằng android_bypass.
HTTP client: pyreqwest_impersonate (TLS giống AutoVeo3) → fallback curl_cffi.
Auth: cookie labs.google -> bearer. Video: submit -> poll -> tải mp4.
"""
import json, time, base64, os, uuid, urllib.parse

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
# Fallback nếu chrome110 không tồn tại
try:
    cffi.get("https://labs.google", impersonate=IMP_CFFI, timeout=5)
except Exception:
    IMP_CFFI = "chrome"  # fallback generic

GEN_T2V = f"{BASE}/video:batchAsyncGenerateVideoText"
GEN_I2V = f"{BASE}/video:batchAsyncGenerateVideoReferenceImages"
CHECK = f"{BASE}/video:batchCheckAsyncVideoGenerationStatus?key={KEY}"

VID_ASPECTS = {"Dọc 9:16 (TikTok)": "VIDEO_ASPECT_RATIO_PORTRAIT", "Ngang 16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE"}
IMG_ASPECTS = {"Dọc 9:16 (TikTok)": "IMAGE_ASPECT_RATIO_PORTRAIT", "Ngang 16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE", "Vuông 1:1": "IMAGE_ASPECT_RATIO_SQUARE"}
VID_MODELS = {"Veo 3.1 (nhanh)": "veo_3_1_t2v_lite_low_priority", "Veo 3.1 (chất lượng)": "veo_3_1_t2v"}
VID_I2V_MODEL = "veo_3_1_r2v_lite_low_priority"

# Mô tả giọng nói cố định — gắn vào cuối mọi prompt để giữ giọng nhất quán giữa các video
# Đặt chuỗi rỗng "" để tắt.
VOICE_DESC = ""

VOICE_PRESETS = {
    "vi": "Narrated by a young Vietnamese woman, approximately 20 years old, with a deep, powerful, and authoritative voice speaking in Vietnamese",
    "id": "Narrated by a young Indonesian woman, approximately 20 years old, with a deep, powerful, and authoritative voice speaking in Bahasa Indonesia",
    "ph": "Narrated by a young Filipino woman, approximately 20 years old, with a deep, powerful, and authoritative voice speaking in Filipino (Tagalog)",
    "en": "Narrated by a young woman, approximately 20 years old, with a deep, powerful, and authoritative voice speaking in clear, natural English",
}

def get_voice_for_lang(lang_code):
    """Trả về mô tả giọng nói preset theo mã ngôn ngữ (vi/id/en)."""
    return VOICE_PRESETS.get(lang_code, VOICE_PRESETS["vi"])

ERROR_LOG_FUNC = None

def _log_err(msg):
    if ERROR_LOG_FUNC:
        try:
            ERROR_LOG_FUNC(f"[Engine] {msg}")
        except Exception:
            pass
    else:
        print("[ENGINE ERROR]", msg)


def _kw(t=60, proxy=None):
    """Keyword args cho HTTP request. Chọn đúng impersonate theo thư viện đang dùng."""
    d = {"impersonate": (IMP if _USE_PYREQWEST else IMP_CFFI), "timeout": t}
    if proxy:
        d["proxies"] = proxy
    return d


def _http_get(url, headers, **kwargs):
    """GET request qua pyreqwest_impersonate (ưu tiên) hoặc curl_cffi."""
    if _USE_PYREQWEST:
        try:
            client = pri.Client(impersonate=IMP, timeout=kwargs.get('timeout', 60))
            proxy = kwargs.get('proxies')
            if proxy:
                p = proxy.get('https') or proxy.get('http')
                if p:
                    client = pri.Client(impersonate=IMP, timeout=kwargs.get('timeout', 60), proxy=p)
            return client.get(url, headers=headers)
        except Exception:
            pass  # fallback
    return cffi.get(url, headers=headers, **_kw(kwargs.get('timeout', 60), kwargs.get('proxies')))


def _http_post(url, headers, data=None, **kwargs):
    """POST request qua pyreqwest_impersonate (ưu tiên) hoặc curl_cffi."""
    if _USE_PYREQWEST:
        try:
            client = pri.Client(impersonate=IMP, timeout=kwargs.get('timeout', 60))
            proxy = kwargs.get('proxies')
            if proxy:
                p = proxy.get('https') or proxy.get('http')
                if p:
                    client = pri.Client(impersonate=IMP, timeout=kwargs.get('timeout', 60), proxy=p)
            return client.post(url, headers=headers, data=data)
        except Exception:
            pass  # fallback
    return cffi.post(url, headers=headers, data=data, **_kw(kwargs.get('timeout', 60), kwargs.get('proxies')))


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
            return j.get("access_token"), (j.get("user") or {}).get("email"), new_cookie
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
def upload_image(bearer, project, image_path, timeout=120, max_retries=2, proxy=None):
    import random as _rnd
    try:
        from PIL import Image
        import io
        import random as _rnd
        img = Image.open(image_path).convert("RGB")
        # Bơm "muối" (salt pixel) để đổi hoàn toàn mã hash của file
        w, h = img.size
        px, py = _rnd.randint(0, w-1), _rnd.randint(0, h-1)
        r, g, b = img.getpixel((px, py))
        img.putpixel((px, py), (r, g, max(0, b - 1) if b > 0 else 1))
        
        buf = io.BytesIO()
        # Random chất lượng 90-95 tiếp tục tạo ra byte map hoàn toàn mới
        img.save(buf, format="JPEG", quality=_rnd.randint(90, 95))
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        _log_err(f"upload_image failed to process image {image_path}: {e}")
        return None
    payload = {"clientContext": {"sessionId": f";{int(time.time()*1000)}", "projectId": project, "tool": "PINHOLE",
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
                wait = 4.0 + (attempt * 3.0) + _rnd.uniform(0, 1.5)
                _log_err(f"upload_image 429 throttled — retry {attempt+1}/{max_retries}, chờ {wait:.1f}s")
                time.sleep(wait)
                continue
            elif r.status_code == 401:
                _log_err(f"upload_image 401 unauthorized")
                return None  # caller sẽ refresh bearer rồi thử lại
            elif r.status_code == 403:
                _log_err(f"upload_image 403 PERMISSION_DENIED — account bị cấm upload ảnh")
                return "forbidden"
            else:
                _log_err(f"upload_image failed status: {r.status_code}, response: {r.text[:300]}")
                return None
        except Exception as e:
            err_str = str(e).lower()
            if "resolve proxy" in err_str or "resolve host" in err_str or "connect to proxy" in err_str:
                _log_err(f"upload_image proxy dead: {e}")
                return "proxy_dead"
            _log_err(f"upload_image request exception: {e}")
            return None
    # Hết retry mà vẫn bị 429 → trả "throttle" để caller xử lý đúng (requeue thay vì fail)
    if throttle_count > 0:
        _log_err(f"upload_image 429 throttled {throttle_count} lần liên tiếp — trả throttle cho caller")
        return "throttle"
    return None

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
    [Rửa 1/3] Upload ảnh lên TK Donor -> donor_mid
    [Rửa 2/3 & 3/3] Gọi AI tái tạo ảnh trực tiếp TRÊN project TK chính -> nhận mediaId chính sạch.
    Trả media_id (string) nếu thành công, None nếu thất bại.
    """
    import random as _rnd, tempfile as _tmpf

    # Bước 1: Upload ảnh gốc lên project DONOR
    donor_mid = upload_image(donor_bearer, donor_project, image_path,
                             timeout=timeout, max_retries=2, proxy=proxy)
    if not donor_mid or donor_mid in ("throttle", "forbidden"):
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
    with open('debug_api.txt', 'a', encoding='utf-8') as dbg_f:
        dbg_f.write(f"\n=== submit_video called ===\n")
        dbg_f.write(f"model: {model}\n")
        dbg_f.write(f"ref_media_id: {ref_media_id}\n")
        dbg_f.write(f"aspect: {aspect}\n")
    
    # I2V (có ảnh gốc) BẮT BUỘC dùng model r2v (reference->video); dùng model t2v -> render FAIL.
    if ref_media_id:
        model = VID_I2V_MODEL
    url = GEN_I2V if ref_media_id else GEN_T2V
    payload = _vpayload(prompt, project, seed, aspect, model, ref_media_id)
    try:
        r = cffi.post(url, headers=_hf(bearer), data=json.dumps(payload), **_kw(timeout, proxy=proxy))
    except Exception as e:
        err_str = str(e).lower()
        if "resolve proxy" in err_str or "resolve host" in err_str or "connect to proxy" in err_str:
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
            with open('debug_api.txt', 'a', encoding='utf-8') as dbg_f:
                dbg_f.write(f"submit_video succeeded, ops: {ops}\n")
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


def poll_video(bearer, ops, cookie=None, max_attempts=120, interval=3.5, timeout=60, proxy=None):
    """Thăm dò trạng thái render của video qua endpoint media.getMediaUrlRedirect."""
    if not ops:
        return "failed", "ops_empty", None
    media_id = ops[0]
    credits = None
    
    H = {
        "Authorization": f"Bearer {bearer}" if bearer else "",
        "Cookie": cookie if cookie else "",
        "User-Agent": UA_CH,
        "Referer": "https://labs.google/",
        "Accept": "*/*"
    }
    proxy_fail_count = 0  # Đếm lỗi proxy DNS liên tiếp
    
    for attempt in range(max_attempts):
        try:
            # Tắt redirect để kiểm tra Location / Content-Type
            r = cffi.get(f"https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name={media_id}", 
                         headers=H, **_kw(timeout, proxy=proxy), allow_redirects=False)
            proxy_fail_count = 0  # Reset khi request thành công
        except Exception as e:
            err_str = str(e).lower()
            if "resolve proxy" in err_str or "resolve host" in err_str or "connect to proxy" in err_str:
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
            # Video đang trong quá trình render trên máy chủ Google (trả 404/500 trong 10-30s đầu cho tới khi ready)
            pass
        else:
            _log_err(f"poll_video check unexpected status {r.status_code}, response: {r.text[:200]}")
            
        time.sleep(interval)
        
    _log_err(f"poll_video timeout or render failed after {max_attempts} attempts.")
    return "failed", "policy", credits

# ---------- GEMINI: viết lại prompt vi phạm chính sách ----------
GEMINI_MODEL = "gemini-flash-latest"   # đã kiểm: gemini-2.0-flash hay 429, 1.5 đã 404; latest chạy ổn
GEMINI_BEARER_MODEL = "gemini-3.7-flash"  # model dùng cho AI viết prompt qua bearer token (3.5-flash hay bị quota)

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
        bearer, _email = bearer_from_cookie(cookie, proxy=proxy)
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


def download_video(media_id, cookie, dst, timeout=180, proxy=None):
    H = {"Cookie": cookie, "User-Agent": UA_CH, "Referer": "https://labs.google/", "Accept": "*/*"}
    try:
        r = cffi.get(f"https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name={media_id}", headers=H,
                     **_kw(timeout, proxy=proxy), allow_redirects=True)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("video"):
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            with open(dst, "wb") as f:
                f.write(r.content)
            return len(r.content)
        else:
            _log_err(f"download_video failed. status: {r.status_code}, content-type: {r.headers.get('content-type')}, response: {r.text[:200]}")
    except Exception as e:
        err_str = str(e).lower()
        if "resolve proxy" in err_str or "resolve host" in err_str or "connect to proxy" in err_str:
            _log_err(f"download_video proxy dead: {e}")
            return -1  # Signal proxy dead
        _log_err(f"download_video exception: {e}")
    return 0


def download_url(url, dst, timeout=120, proxy=None):
    data = cffi.get(url, **_kw(timeout, proxy=proxy)).content
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "wb") as f:
        f.write(data)
    return len(data)
