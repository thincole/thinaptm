"""
RecaptchaFarm — Trại Token reCAPTCHA cho Google Flow API (học từ AutoVeo3).

AutoVeo3 chạy "Trại Token" với 5 luồng ẩn danh liên tục farm reCAPTCHA token tươi.
Mỗi request API kèm token thật → Google coi là người dùng hợp lệ → ít bị rate-limit.

Cách dùng:
    farm = RecaptchaFarm(num_workers=5)
    farm.start()
    token = farm.get_token(timeout=30)  # lấy token tươi, hoặc None nếu timeout
    farm.stop()

Nếu không lấy được token → caller tự fallback về "android_bypass".
"""
import threading, time, queue, os, json

# reCAPTCHA site key cho Google Flow (nhúng trong page source flow.google.com: key xZbWve)
# Đây là enterprise key, dùng với grecaptcha.enterprise.execute()
RECAPTCHA_SITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
RECAPTCHA_ACTION = "VIDEO_GENERATION"
# ★ PHẢI dùng flow.google.com — token reCAPTCHA phải khớp domain với BOQ endpoint
# labs.google tạo token cho domain labs.google → bị reject khi gửi đến flow.google.com
FLOW_URL = "https://flow.google.com"
LABS_URL = FLOW_URL

# Số token tồn kho tối đa (token hết hạn sau ~2 phút nên không nên giữ quá nhiều)
MAX_QUEUE = 20
# Token hết hạn sau bao lâu (giây) — Google reCAPTCHA token sống ~120s
TOKEN_TTL = 100
# Thời gian chờ giữa các lần farm (giây)
FARM_INTERVAL = 3
# Số trình duyệt farm tối đa mở đồng thời (mỗi tài khoản 1 Chrome ẩn ~150-250MB RAM)
MAX_FARM_BROWSERS = 6


def get_chrome_path():
    """Lấy đường dẫn Google Chrome chuẩn trên Windows."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def get_chrome_for_testing_path():
    """Lấy đường dẫn bản 'Chrome for Testing' (chrome_for_testing/chrome-win64/chrome.exe) — BẮT
    BUỘC dùng bản này thay vì Chrome thường để nạp extension unpacked cho Extension mode, vì từ
    Chrome 136-137 (2025) Chrome thường CHẶN nạp extension unpacked (kể cả 'Load unpacked' thủ
    công) khi trình duyệt đang bị điều khiển qua CDP (đúng cách DrissionPage hoạt động) — biện
    pháp bảo mật mới của Google. Trả None nếu chưa tải (script/README hướng dẫn cách tải)."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_for_testing", "chrome-win64", "chrome.exe")
    return p if os.path.isfile(p) else None


def hide_pid_windows_from_taskbar(pid):
    """Ẩn toàn bộ cửa sổ của tiến trình Chrome khỏi màn hình và Taskbar Windows (SW_HIDE + ToolWindow)."""
    if not pid:
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        SWP_FRAMECHANGED = 0x0020
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        hwnds = []
        def enum_cb(hwnd, lparam):
            lpdw_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lpdw_pid))
            if lpdw_pid.value == pid:
                hwnds.append(hwnd)
            return True

        cb = WNDENUMPROC(enum_cb)
        hdesk = user32.OpenInputDesktop(0, False, 0x0100)
        if hdesk:
            user32.EnumDesktopWindows(hdesk, cb, 0)
            user32.CloseDesktop(hdesk)
        if not hwnds:
            user32.EnumWindows(cb, 0)

        for hwnd in hwnds:
            try:
                ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ex_style |= WS_EX_TOOLWINDOW
                ex_style &= ~WS_EX_APPWINDOW
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
                # Đẩy hoàn toàn ra khỏi tọa độ màn hình và ẩn vĩnh viễn (SW_HIDE = 0)
                user32.SetWindowPos(hwnd, 0, -32000, -32000, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
                user32.ShowWindow(hwnd, 0)
            except Exception:
                pass
    except Exception:
        pass


def _inject_cookies(page, cookie_str, url=FLOW_URL, clear_old=False):
    """Set cookie vào ChromiumPage qua CDP Network.setCookie (hỗ trợ HttpOnly/__Host- cookies) —
    dùng chung cho mọi nơi cần inject cookie tài khoản vào 1 session browser đang mở.
    clear_old=True: xoá cookie google.com cũ trước khi inject (chống cookie bán-chết)."""
    if not cookie_str:
        return
    if clear_old:
        try:
            cdp_cookies = page.run_cdp("Network.getCookies", urls=["https://flow.google.com", "https://accounts.google.com", "https://www.google.com"])
            for c in cdp_cookies.get("cookies", []):
                if "google" in c.get("domain", ""):
                    try:
                        page.run_cdp("Network.deleteCookies", name=c["name"], domain=c["domain"], path=c.get("path", "/"))
                    except Exception:
                        pass
        except Exception:
            pass
    for pair in str(cookie_str).split(";"):
        if "=" not in pair:
            continue
        name, val = pair.strip().split("=", 1)
        name, val = name.strip(), val.strip()
        try:
            if name.startswith("__Host-"):
                page.run_cdp("Network.setCookie", name=name, value=val, url=url, path="/", secure=True, httpOnly=True)
            else:
                page.run_cdp("Network.setCookie", name=name, value=val, domain=".google.com", path="/", secure=True)
        except Exception:
            pass


class RecaptchaFarm:
    """Trại Token reCAPTCHA — farm token tươi bằng headless Chrome.
    
    Mỗi worker mở 1 tab Chrome, load trang labs.google, gọi
    grecaptcha.enterprise.execute() định kỳ để lấy token mới.
    Token được lưu vào queue thread-safe, kèm timestamp.
    """
    
    def __init__(self, num_workers=2, log_func=None, profile_dir=None):
        self.num_workers = num_workers
        self.profile_dir = profile_dir
        def _safe_print(m):
            try:
                print(f"[RecaptchaFarm] {m}")
            except Exception:
                print(f"[RecaptchaFarm] {str(m).encode('ascii', 'replace').decode()}")
        self._log = log_func or _safe_print
        # Hàng đợi token GẮN THEO TÀI KHOẢN: acc_key -> {action: Queue}. Token của tài khoản nào
        # chỉ dùng cho submit của tài khoản đó (cùng IP proxy + cùng phiên → khớp bối cảnh reCAPTCHA).
        self._acc_queues = {}          # acc_key -> {"VIDEO_GENERATION": Queue, "UPLOAD_IMAGE": Queue}
        self._acc_queues_lock = threading.Lock()
        self._proxy_resolver = None    # fn(email) -> proxy_str (lấy live từ ProxyPool, xử lý cả xoay proxy)
        self._stop = False
        self._workers = []
        self._started = False
        self._total_farmed = 0
        self._lock = threading.Lock()
        self._sessions = {}  # acc_key -> {"page": page, "lock": Lock(), "project": project, "ready": bool}
        self._sessions_lock = threading.Lock()
        self._need_cookie_reload = False

    def set_proxy_resolver(self, fn):
        """App gắn callback email->proxy_str (từ ProxyPool). Worker gọi để lấy đúng proxy hiện tại."""
        self._proxy_resolver = fn

    def _acc_queues_for(self, acc_key):
        with self._acc_queues_lock:
            q = self._acc_queues.get(acc_key)
            if q is None:
                q = {"VIDEO_GENERATION": queue.Queue(maxsize=MAX_QUEUE),
                     "UPLOAD_IMAGE": queue.Queue(maxsize=MAX_QUEUE)}
                self._acc_queues[acc_key] = q
            return q

    def reload_cookies(self):
        """Báo hiệu cho tất cả worker nạp lại cookie mới từ accounts.json."""
        self._need_cookie_reload = True
    
    def start(self):
        """Khởi động farm: MỖI TÀI KHOẢN enabled 1 trình duyệt riêng (bind cố định, chạy qua đúng
        proxy của tài khoản đó). Trả True nếu thành công."""
        if self._started:
            return True
        self._stop = False

        try:
            from DrissionPage import ChromiumOptions, ChromiumPage
        except ImportError:
            self._log("❌ Thiếu DrissionPage — không thể farm token.")
            return False

        # Danh sách tài khoản sẽ farm (mỗi tài khoản 1 browser). Đọc từ accounts.json.
        try:
            acc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.json")
            with open(acc_path, "r", encoding="utf-8") as f:
                _accs = json.load(f)
            enabled = [a for a in _accs if a.get("cookie") and a.get("enabled") in (True, "True")
                       and a.get("status") != "dead" and a.get("role", "main") == "main"]
        except Exception as e:
            self._log(f"❌ Không đọc được accounts.json: {e}")
            return False
        if not enabled:
            self._log("⚠️ Không có tài khoản enabled nào để farm token.")
            return False

        if len(enabled) > MAX_FARM_BROWSERS:
            self._log(f"⚠️ Có {len(enabled)} tài khoản nhưng chỉ mở tối đa {MAX_FARM_BROWSERS} trình duyệt farm "
                      f"(giới hạn RAM). {len(enabled) - MAX_FARM_BROWSERS} tài khoản dư sẽ thiếu token — "
                      f"nên bật ≤ {MAX_FARM_BROWSERS} tài khoản, hoặc tăng MAX_FARM_BROWSERS.")
            enabled = enabled[:MAX_FARM_BROWSERS]

        try:
            from thin_aptm import get_acc_email
        except Exception:
            get_acc_email = lambda a: str(a.get("email") or a.get("id") or "").strip().lower()

        self.num_workers = len(enabled)
        self._log(f"🐑 Khởi động Trại Token: {self.num_workers} trình duyệt (mỗi tài khoản 1 browser qua proxy riêng)...")
        for i, acc in enumerate(enabled):
            email = get_acc_email(acc)
            t = threading.Thread(target=self._worker, args=(i, email, acc.get("cookie")), daemon=True,
                                 name=f"RecaptchaFarm-{i}")
            t.start()
            self._workers.append(t)
            time.sleep(0.5)

        self._started = True
        self._log(f"✅ Trại Token đã khởi động — {self.num_workers} trình duyệt sẵn sàng")
        return True
    
    def stop(self):
        """Dừng farm và đóng toàn bộ browser sessions."""
        self._stop = True
        self._started = False
        with self._sessions_lock:
            for key, sess in list(self._sessions.items()):
                try:
                    if sess.get("page"):
                        sess["page"].quit()
                except Exception:
                    pass
            self._sessions.clear()
        self._log(f"⏹ Trại Token đã dừng. Tổng token đã farm: {self._total_farmed}")
    
    def _collect_queues(self, action, email):
        """Trả danh sách (queue chính, queue phụ) sẽ lấy token.
        Có email → CHỈ queue của tài khoản đó (token phải khớp bối cảnh, không lấy nhầm tài khoản khác).
        Không email → gộp tất cả queue (luồng phụ/legacy)."""
        alt = "UPLOAD_IMAGE" if action == "VIDEO_GENERATION" else "VIDEO_GENERATION"
        if email:
            qs = self._acc_queues_for(self._get_acc_key(None, email=email))
            return [qs.get(action)], [qs.get(alt)]
        with self._acc_queues_lock:
            mains = [qs.get(action) for qs in self._acc_queues.values() if qs.get(action)]
            alts = [qs.get(alt) for qs in self._acc_queues.values() if qs.get(alt)]
        return mains, alts

    def get_token(self, timeout=15, action="VIDEO_GENERATION", email=None):
        """Lấy 1 token tươi cho action, GẮN THEO TÀI KHOẢN nếu có email.
        Trả token string hoặc None nếu timeout. Tự bỏ token quá hạn."""
        mains, alts = self._collect_queues(action, email)
        deadline = time.time() + timeout
        def _drain(qlist):
            for q in qlist:
                if not q:
                    continue
                try:
                    item = q.get_nowait()
                except queue.Empty:
                    continue
                if isinstance(item, tuple):
                    token, ts = item
                    if time.time() - ts < TOKEN_TTL:
                        return token
                elif isinstance(item, str):
                    return item
            return None
        while time.time() < deadline:
            tok = _drain(mains)
            if tok:
                return tok
            tok = _drain(alts)          # cùng tài khoản, action còn lại (token reCAPTCHA dùng chung action được)
            if tok:
                return tok
            time.sleep(min(0.3, max(0.05, deadline - time.time())))
        return None

    def qsize(self, action="VIDEO_GENERATION", email=None):
        """Số token tươi hiện có trong queue."""
        mains, _ = self._collect_queues(action, email)
        return sum(q.qsize() for q in mains if q)

    def stats(self):
        """Thống kê farm."""
        return {
            "workers": len(self._workers),
            "started": self._started,
            "queued_video": self.qsize("VIDEO_GENERATION"),
            "queued_upload": self.qsize("UPLOAD_IMAGE"),
            "total_farmed": self._total_farmed,
        }

    def _find_profile_dir(self, email=None, cookie=None):
        """Tìm thư mục profile tương ứng của tài khoản."""
        here = os.path.dirname(os.path.abspath(__file__))
        profiles_root = os.path.join(here, "_profiles")
        if email:
            p = os.path.join(profiles_root, str(email).replace("@", "_"))
            if os.path.isdir(p):
                return p
        if cookie:
            try:
                acc_path = os.path.join(here, "accounts.json")
                if os.path.isfile(acc_path):
                    with open(acc_path, "r", encoding="utf-8") as f:
                        accs = json.load(f)
                    for a in accs:
                        if a.get("cookie") == cookie or (email and (a.get("email") == email or a.get("id") == email)):
                            acc_em = a.get("email") or a.get("id") or ""
                            if acc_em:
                                p = os.path.join(profiles_root, acc_em.replace("@", "_"))
                                if os.path.isdir(p):
                                    return p
            except Exception:
                pass
        return None

    def _get_acc_key(self, cookie, email=None):
        """Tạo định danh hash duy nhất cho tài khoản dựa trên email hoặc cookie."""
        import hashlib
        if email:
            return str(email).strip().lower()
        if not cookie:
            return "unknown"
        for pair in str(cookie).split(";"):
            if "=" in pair:
                k, v = pair.strip().split("=", 1)
                if k.strip() in ("SAPISID", "SID", "__Secure-1PSID"):
                    return hashlib.md5(v.strip().encode()).hexdigest()[:12]
        return hashlib.md5(str(cookie)[:100].encode()).hexdigest()[:12]

    def reset_session(self, key_or_email):
        """Đóng và xóa browser session của tài khoản khi cookie được làm mới hoặc cần reset."""
        if not key_or_email:
            return
        target = str(key_or_email).strip().lower()
        with self._sessions_lock:
            for k, sess in list(self._sessions.items()):
                if k == target or target in k or k in target:
                    try:
                        if sess.get("page"):
                            sess["page"].quit()
                    except Exception:
                        pass
                    sess["ready"] = False
                    sess["page"] = None
                    self._sessions.pop(k, None)
                    self._log(f"🔄 Đã reset browser session cho {key_or_email}")

    def get_wiz_tokens_from_browser(self, cookie=None, project=None, email=None):
        """Lấy (at, fsid, bl, account_id) từ browser session đã mở sẵn.
        Đây là FALLBACK khi get_wiz_tokens() HTTP parsing fail (Google thay đổi page).
        Browser session chạy JavaScript nên lấy được window.WIZ_global_data.SNlM0e.
        CHỈ dùng session đã có sẵn, KHÔNG tạo session mới."""
        # Ưu tiên session khớp email/cookie
        target_key = self._get_acc_key(cookie, email=email) if (cookie or email) else None
        candidates = []
        with self._sessions_lock:
            if target_key and target_key in self._sessions:
                candidates.append(self._sessions[target_key])
            else:
                # Tìm tất cả session đang sẵn sàng
                candidates = [s for s in self._sessions.values() if s.get("ready") and s.get("page")]

        for sess in candidates:
            # Khoá session trước khi thao tác page — tránh 2 thread cùng dùng chung 1 ChromiumPage
            # đồng thời (vd. submit_video_native đang chạy trên cùng session này).
            lock = sess.get("lock")
            if lock and not lock.acquire(timeout=5):
                continue
            try:
                if not sess.get("ready") or not sess.get("page"):
                    continue
                page = sess["page"]

                # CHẶN LỖI PHANTOM TOKEN: Không lấy token từ trang đăng nhập!
                try:
                    curr_url = str(page.url).lower()
                    if "accounts.google.com" in curr_url or "identityfrontend" in curr_url:
                        continue
                except Exception:
                    pass

                js = """
                (function() {
                    var w = window.WIZ_global_data || {};
                    return JSON.stringify({
                        at: w.SNlM0e || '',
                        fsid: w.FdrFJe || '',
                        bl: w.cfb2h || '',
                        account_id: w['oPEP7c'] || w['S06Grb'] || ''
                    });
                })()
                """
                raw = page.run_js(js)
                if raw:
                    data = json.loads(raw)
                    at = data.get("at") or None
                    fsid = data.get("fsid") or None
                    bl = data.get("bl") or "boq_labs-ai-sandbox-frontend_20260907.00_p0"
                    account_id = data.get("account_id") or None
                    if at:
                        return at, fsid, bl, account_id
            except Exception as ex:
                self._log(f"get_wiz_tokens_from_browser error: {ex}")
                continue
            finally:
                if lock:
                    lock.release()
        return None, None, None, None

    def _get_or_create_session(self, cookie, project, email=None):
        """Lấy hoặc khởi tạo 1 browser session chuyên trách cho tài khoản.
        Tự động ưu tiên dùng user profile đã đăng nhập sẵn để tránh bị reCAPTCHA Enterprise chặn."""
        import random
        from DrissionPage import ChromiumOptions, ChromiumPage
        key = self._get_acc_key(cookie, email=email)
        with self._sessions_lock:
            if key not in self._sessions:
                self._sessions[key] = {"lock": threading.Lock(), "ready": False, "page": None, "project": project, "cookie": cookie}
            sess = self._sessions[key]

        with sess["lock"]:
            # Nếu cookie của tài khoản đã thay đổi -> reset phiên cũ
            if sess.get("cookie") and cookie and sess.get("cookie") != cookie:
                self._log(f"🔄 [Browser-{key[:10]}] Cookie đã đổi → Khởi tạo lại Chrome...")
                try:
                    if sess.get("page"):
                        sess["page"].quit()
                except Exception:
                    pass
                sess["page"] = None
                sess["ready"] = False
                sess["cookie"] = cookie

            if sess.get("ready") and sess.get("page"):
                try:
                    if sess["page"].run_js("return 1") == 1:
                        return sess
                except Exception:
                    sess["ready"] = False
                    try:
                        sess["page"].quit()
                    except Exception:
                        pass
                    sess["page"] = None
            
            tag = f"[Browser-{key[:10]}]"
            profile_dir = self._find_profile_dir(email=email, cookie=cookie)

            co = ChromiumOptions()
            chrome_path = get_chrome_path()
            if chrome_path:
                co.set_browser_path(chrome_path)
            # ★ Kỹ thuật Chiến Hust: KHÔNG dùng --headless (Google phát hiện qua WebGL/Canvas)
            # Thay vào đó đẩy cửa sổ ra ngoài màn hình → Chrome render thật 100% nhưng ẩn
            co.set_argument("--window-position=-30000,0")
            co.set_argument("--window-size=1280,900")
            co.set_argument("--start-minimized")
            co.set_argument("--no-first-run")
            co.set_argument("--no-default-browser-check")
            co.set_argument("--disable-gpu")
            co.set_argument("--disable-blink-features=AutomationControlled")
            co.set_local_port(random.randint(20000, 39999))

            if profile_dir:
                self._log(f"🌐 {tag} Nạp profile người dùng: {os.path.basename(profile_dir)} (headless)...")
                co.set_user_data_path(profile_dir)
            else:
                self._log(f"🌐 {tag} Không có profile sẵn → Dùng Chrome headless + CDP cookie injection...")
                co.set_argument("--disable-extensions")
                co.set_argument("--no-sandbox")
                co.set_argument("--blink-settings=imagesEnabled=false")
                co.set_pref("profile.default_content_setting_values.images", 2)

            try:
                page = ChromiumPage(co)
                page.set.retry_times(2)
                hide_pid_windows_from_taskbar(getattr(page, "process_id", None))

                # ★ Nạp Stealth Script & BotoxSign Hooking từ TstGoogleFlow v1.0.6
                try:
                    import browser_stealth
                    browser_stealth.apply_stealth(page, log_fn=self._log)
                    browser_stealth.setup_botox_hook(page, log_fn=self._log)
                except Exception as _stealth_ex:
                    self._log(f"⚠️ {tag} Lỗi nạp stealth/botox hook: {_stealth_ex}")

                # Luôn inject cookie mới nhất từ accounts.json qua CDP để đảm bảo không bị dùng cookie cũ trong profile
                if cookie:
                    try:
                        page.get(FLOW_URL)
                        time.sleep(1.0)
                        _inject_cookies(page, cookie, clear_old=True)
                    except Exception:
                        pass

                target_url = f"https://flow.google.com/project/{project}" if project else f"{FLOW_URL}/project/513f3b20-fa17-4be7-89b5-f179860de580"
                page.get(target_url)
                self._log(f"🌐 {tag} Đang load project editor...")

                # Đợi Angular & WIZ & grecaptcha ready
                ready = False
                for _ in range(25):
                    time.sleep(1)
                    try:
                        curr = page.url
                        if "accounts.google.com" in curr or "identityfrontend" in curr:
                            self._log(f"❌ {tag} Cookie hết hạn (redirect Google login)")
                            sess["ready"] = False
                            sess["page"] = None
                            try: page.quit()
                            except: pass
                            return None
                        ok = page.run_js("return typeof grecaptcha !== 'undefined' && !!grecaptcha.enterprise && typeof grecaptcha.enterprise.execute === 'function' && !!window.WIZ_global_data && !!window.WIZ_global_data.SNlM0e")
                        if ok:
                            ready = True
                            break
                    except:
                        pass

                if not ready:
                    self._log(f"⚠️ {tag} Editor chưa hoàn toàn sẵn sàng sau 25s, vẫn tiếp tục submit...")

                sess["page"] = page
                sess["ready"] = True
                sess["cookie"] = cookie
                self._log(f"🟢 {tag} Phiên Chrome sẵn sàng cho video submit!")
                return sess
            except Exception as ex:
                self._log(f"❌ {tag} Lỗi khởi tạo Chrome: {ex}")
                sess["ready"] = False
                sess["page"] = None
                return None

    def submit_video_native(self, cookie, project, prompt, model="veo_3_1_t2v_lite_low_priority", aspect="9:16", ref_media_id=None, email=None):
        """Submit video TRỰC TIẾP từ bên trong trình duyệt (In-Browser Native Fetch).
        
        ★ Tránh 100% lỗi PUBLIC_ERROR_UNUSUAL_ACTIVITY vì:
        - Sử dụng persistent profile Chrome thật của tài khoản (nếu có)
        - Token reCAPTCHA sinh ra trên cùng origin và được fetch() ngay tại tab đó
        - Đúng TLS fingerprint, đúng credentials và session context của Chrome
        - Hỗ trợ cả Text-to-Video và Ingredients (ảnh sản phẩm tham chiếu)
        """
        import uuid
        sess = self._get_or_create_session(cookie, project, email=email)
        if not sess:
            return "auth", []

        with sess["lock"]:
            page = sess.get("page")
            if not page:
                return "auth", []
            # Google Flow BOQ RPC (YhhmEf / eb1hJf): 1 = Dọc 9:16 (PORTRAIT), 2 = Ngang 16:9 (LANDSCAPE)
            aspect_code = 2 if (aspect and ("16:9" in str(aspect) or "LANDSCAPE" in str(aspect))) else 1
            
            u1, u2, u3, u4 = [str(uuid.uuid4()).upper() for _ in range(4)]
            parent_u = str(uuid.uuid4()).upper()
            
            # Xác định model có phải dòng trả phí (abra/omni) không
            is_paid_model = ("abra" in str(model).lower() or "omni" in str(model).lower())
            
            if ref_media_id and is_paid_model:
                # Image-to-Video qua eb1hJf — CHỈ cho model trả phí (tốn credit)
                rpc_id = "eb1hJf"
                model_name = "abra_i2v_10s" if "10s" in str(model) else "abra_i2v_8s"
                prompt_block = [None, None, [[[prompt]]]]
                scene1 = [prompt_block, model_name, aspect_code, None, [None, ref_media_id], [None, None, None, None, u1, u2]]
                scene2 = [prompt_block, model_name, aspect_code, None, [None, ref_media_id], [None, None, None, None, u3, u4]]
            else:
                # Text-to-Video qua YhhmEf — Veo 3.1 Lite (miễn phí, 0 credit)
                # LƯU Ý: Ingredient format (ref_media_id) trên YhhmEf bị Google chặn (UNUSUAL_ACTIVITY)
                # → bỏ qua ref_media_id, chỉ dùng prompt text thuần
                rpc_id = "YhhmEf"
                if "10s" in str(model):
                    model_name = "abra_t2v_10s"
                elif is_paid_model:
                    model_name = "abra_t2v_8s"
                else:
                    model_name = "veo_3_1_t2v_lite_low_priority"
                prompt_block = [None, None, [[[prompt]]]]
                scene1 = [prompt_block, model_name, aspect_code, None, [None, None, None, None, u1, u2]]
                scene2 = [prompt_block, model_name, aspect_code, None, [None, None, None, None, u3, u4]]
            
            js = f"""
            async function _doSubmit() {{
                try {{
                    await new Promise(r => grecaptcha.enterprise.ready(r));
                    const rcToken = await grecaptcha.enterprise.execute('{RECAPTCHA_SITE_KEY}', {{action: 'VIDEO_GENERATION'}});
                    
                    const at = window.WIZ_global_data ? window.WIZ_global_data.SNlM0e : '';
                    const bl = window.WIZ_global_data ? window.WIZ_global_data.cfb2h : '';
                    const fsid = window.WIZ_global_data ? window.WIZ_global_data.FdrFJe : '';
                    
                    const clientCtx = [null, 22, null, null, null, '{project}', null, null, null, null, [rcToken, 1]];
                    const scenes = {json.dumps([scene1, scene2])};
                    const payload = JSON.stringify([scenes, clientCtx, ['{parent_u}', {aspect_code}]]);
                    
                    const freq = [[['{rpc_id}', payload, null, 'generic']]];
                    const body = new URLSearchParams();
                    body.append('f.req', JSON.stringify(freq));
                    body.append('at', at);
                    
                    // Dynamic _reqid counter (mô phỏng browser thật, tăng dần mỗi request)
                    if (!window._thinaptm_reqid) window._thinaptm_reqid = Math.floor(Math.random() * 100000);
                    window._thinaptm_reqid += Math.floor(Math.random() * 50000) + 10000;
                    const reqId = window._thinaptm_reqid;
                    
                    const url = '/_/AiSandboxAngularFrontend/data/batchexecute?rpcids={rpc_id}&source-path=' + 
                                encodeURIComponent('/project/{project}') + '&bl=' + bl + '&f.sid=' + fsid + '&hl=en-US&_reqid=' + reqId + '&rt=c';
                    
                    const resp = await fetch(url, {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                            'X-Same-Domain': '1'
                        }},
                        body: body
                    }});
                    
                    const text = await resp.text();
                    try {{
                        const xsrfMatch = text.match(/\\["xsrf","([^"]+)"/);
                        if (xsrfMatch && window.WIZ_global_data) {{
                            window.WIZ_global_data.SNlM0e = xsrfMatch[1];
                        }}
                    }} catch(_) {{}}

                    return text;
                }} catch(e) {{
                    return 'ERROR: ' + e;
                }}
            }}
            return _doSubmit();
            """
            try:
                raw_text = page.run_js(js)
            except Exception as ex:
                self._log(f"run_js exception: {ex}")
                return "retry_soft", []

            ops = []
            status = "failed"
            if raw_text and "wrb.fr" in raw_text:
                if "PUBLIC_ERROR_UNUSUAL_ACTIVITY" in raw_text:
                    sess["ready"] = False
                    try: page.quit()
                    except: pass
                    sess["page"] = None
                    return "unusual", []
                if "PUBLIC_ERROR_PROMINENT_PEOPLE" in raw_text or "AUDIO_FILTERED" in raw_text:
                    return "vi phạm cs", []
                if "PUBLIC_ERROR_USER_QUOTA_REACHED" in raw_text:
                    return "quota_hard", []
                try:
                    for line in raw_text.splitlines():
                        line = line.strip()
                        if line.startswith("[") and "wrb.fr" in line:
                            chunk = json.loads(line)
                            for item in chunk:
                                if isinstance(item, list) and len(item) > 2 and item[0] == "wrb.fr" and item[1] in ("YhhmEf", "eb1hJf"):
                                    inner = json.loads(item[2])
                                    if isinstance(inner, list):
                                        if len(inner) > 3 and isinstance(inner[3], list) and inner[3]:
                                            for op_item in inner[3]:
                                                if isinstance(op_item, list) and len(op_item) > 0 and op_item[0]:
                                                    ops.append(str(op_item[0]))
                                        if not ops and len(inner) > 2 and isinstance(inner[2], list):
                                            for op_item in inner[2]:
                                                if isinstance(op_item, list) and len(op_item) > 0 and op_item[0]:
                                                    ops.append(str(op_item[0]))
                                        if ops:
                                            status = "ok"
                except Exception as ex:
                    self._log(f"Parse error: {ex}")

            if status == "ok":
                sess["submit_count"] = sess.get("submit_count", 0) + 1
            return status, ops
    
    def _worker(self, worker_id, acc_email, acc_cookie):
        """Worker: MỖI TÀI KHOẢN 1 trình duyệt, chạy qua ĐÚNG proxy của tài khoản đó, farm token
        gắn theo tài khoản. Token sinh ra cùng IP proxy + cùng phiên với lệnh submit REST → khớp bối
        cảnh reCAPTCHA Enterprise → không bị PUBLIC_ERROR_UNUSUAL_ACTIVITY."""
        import random
        try:
            from DrissionPage import ChromiumOptions, ChromiumPage
        except ImportError:
            self._log("❌ Thiếu DrissionPage — không thể farm token.")
            return

        acc_key = self._get_acc_key(acc_cookie, email=acc_email)
        acc_q = self._acc_queues_for(acc_key)
        short = (acc_email or acc_key)[:16]
        tag = f"[Farm {short}]"

        def _resolve_proxy():
            try:
                return self._proxy_resolver(acc_email) if self._proxy_resolver else None
            except Exception:
                return None

        while not self._stop:
            page = None
            try:
                # Lấy proxy hiện tại của tài khoản (chờ tối đa ~20s nếu app chưa gán xong)
                proxy_str = _resolve_proxy()
                for _ in range(20):
                    if proxy_str or self._stop:
                        break
                    time.sleep(1)
                    proxy_str = _resolve_proxy()

                proxy_creds = None
                co = ChromiumOptions()
                chrome_path = get_chrome_path()
                if chrome_path:
                    co.set_browser_path(chrome_path)
                co.set_argument("--mute-audio")
                co.set_argument("--no-first-run")
                co.set_argument("--no-default-browser-check")
                co.set_argument("--disable-gpu")
                co.set_argument("--window-position=-30000,0")
                co.set_argument("--window-size=800,600")
                co.set_argument("--start-minimized")
                co.set_argument("--blink-settings=imagesEnabled=false")
                co.set_argument("--disable-software-rasterizer")
                co.set_argument("--disable-dev-shm-usage")
                co.set_argument("--no-sandbox")
                co.set_argument("--disable-blink-features=AutomationControlled")
                co.set_pref("profile.default_content_setting_values.images", 2)
                co.set_pref("profile.managed_default_content_settings.images", 2)
                co.set_local_port(random.randint(30000, 49999))

                # ★ Cắm proxy của tài khoản. Auth (user:pass) xử lý bằng CDP trong setup_botox_hook.
                if proxy_str:
                    import re as _re
                    _pd = None
                    try:
                        import thin_aptm as _T
                        _pd = _T.ProxyPool._to_dict(proxy_str)
                    except Exception:
                        _pd = None
                    _url = (_pd or {}).get("http") or ""
                    if _url.startswith("socks"):
                        co.set_argument("--proxy-server", _url.split("#")[0])   # WARP socks5, không auth
                    elif _url:
                        _m = _re.match(r"https?://(?:([^:]+):([^@]+)@)?([^:]+):(\d+)", _url)
                        if _m:
                            _u, _p, _h, _pt = _m.group(1), _m.group(2), _m.group(3), _m.group(4)
                            co.set_argument("--proxy-server", f"http://{_h}:{_pt}")
                            if _u:
                                proxy_creds = (_u, _p or "")
                    self._log(f"{tag} 🌐 Farm qua proxy {(_url.split('@')[-1] if _url else '?')[:34]}")
                else:
                    self._log(f"{tag} ⚠️ Không có proxy → farm bằng IP máy (có thể bị gắn cờ do lệch IP với submit)")

                page = ChromiumPage(co)
                page.set.retry_times(2)
                hide_pid_windows_from_taskbar(getattr(page, "process_id", None))

                # ★ Stealth
                try:
                    import browser_stealth
                    browser_stealth.apply_stealth(page, log_fn=self._log)
                except Exception as _stealth_ex:
                    self._log(f"{tag} ⚠️ Lỗi nạp stealth: {_stealth_ex}")

                # ★ Xác thực proxy MỘT LẦN (Chrome cache creds cả phiên) — làm TRƯỚC, rồi mới bật botox
                if proxy_creds:
                    try:
                        browser_stealth.prime_proxy_auth(page, proxy_creds[0], proxy_creds[1], log_fn=self._log)
                    except Exception as _pex:
                        self._log(f"{tag} ⚠️ Lỗi xác thực proxy: {_pex}")

                # ★ Xác nhận IP thật Chrome đang dùng (sau khi proxy sẵn sàng)
                if proxy_str:
                    try:
                        page.get("https://api.ipify.org?format=json")
                        time.sleep(1.0)
                        _ipbody = page.run_js("return document.body ? document.body.innerText : ''") or ""
                        _ip = ""
                        try:
                            import json as _j; _ip = _j.loads(_ipbody).get("ip", "")
                        except Exception:
                            pass
                        if _ip:
                            self._log(f"{tag} ✅ IP farm = {_ip}")
                    except Exception:
                        pass

                # ★ BotoxSign hook (pattern hẹp — chỉ vá js, không làm chậm trang)
                try:
                    browser_stealth.setup_botox_hook(page, log_fn=self._log)
                except Exception as _bex:
                    self._log(f"{tag} ⚠️ Lỗi nạp botox hook: {_bex}")

                # Cookie CỐ ĐỊNH theo tài khoản của worker này (đọc bản mới nhất từ accounts.json)
                cookie_str = acc_cookie
                project_id = None
                try:
                    acc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.json")
                    with open(acc_path, "r", encoding="utf-8") as f:
                        _accs = json.load(f)
                    for a in _accs:
                        if str(a.get("email") or a.get("id") or "").strip().lower() == str(acc_email).strip().lower() and a.get("cookie"):
                            cookie_str = a["cookie"]
                            break
                except Exception:
                    pass

                if not cookie_str:
                    self._log(f"{tag} ❌ Không có cookie")
                    time.sleep(10)
                    continue

                # Lấy project ID
                try:
                    import sys
                    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                    import engine as _E
                    project_id = _E.get_project(cookie_str)
                except Exception:
                    pass
                
                # Step 1: Navigate to flow.google.com (thiết lập domain)
                page.get("https://flow.google.com")
                time.sleep(2)
                
                # Step 2: Set cookies via CDP (hỗ trợ HttpOnly, __Host- cookies)
                _inject_cookies(page, cookie_str)
                
                # Step 3: Navigate đến project page (Angular + reCAPTCHA load tự nhiên)
                target_url = f"https://flow.google.com/project/{project_id}" if project_id else "https://flow.google.com/project/513f3b20-fa17-4be7-89b5-f179860de580"
                self._log(f"{tag} 🌐 Loading {target_url[-50:]}...")
                page.get(target_url)
                time.sleep(15)  # Angular cần thời gian bootstrap
                
                # Step 4: Chờ reCAPTCHA (thử tối đa 6 lần × 4s = 24s)
                has_rc = False
                for attempt in range(6):
                    try:
                        has_rc = page.run_js("return typeof grecaptcha !== 'undefined' && !!grecaptcha.enterprise")
                    except Exception:
                        has_rc = False
                    if has_rc:
                        break
                    time.sleep(4)
                
                if not has_rc:
                    self._log(f"{tag} ⚠️ reCAPTCHA chưa sẵn sàng trên flow.google.com, tự động thử lại...")
                    continue
                
                self._log(f"{tag} 🟢 reCAPTCHA native OK trên flow.google.com, bắt đầu farm")

                def _build_exec_js(act):
                    return f"""
                    async function _exec() {{
                        try {{
                            if (typeof grecaptcha === 'undefined' || !grecaptcha.enterprise) {{
                                return 'ERROR:grecaptcha_undefined';
                            }}
                            await new Promise(r => grecaptcha.enterprise.ready(r));
                            var token = await grecaptcha.enterprise.execute('{RECAPTCHA_SITE_KEY}', {{action: '{act}'}});
                            return token;
                        }} catch(e) {{
                            return 'ERROR:' + e;
                        }}
                    }}
                    return _exec();
                    """
                exec_js_map = {act: _build_exec_js(act) for act in ["VIDEO_GENERATION", "UPLOAD_IMAGE"]}

                fail_streak = 0
                _log_counter = 0
                while not self._stop:
                    try:
                        any_success = False
                        all_full = True
                        for act, js_code in exec_js_map.items():
                            q = acc_q[act]          # queue GẮN THEO TÀI KHOẢN của worker này
                            if q.qsize() < MAX_QUEUE:
                                all_full = False
                                token = page.run_js(js_code)
                                if token and isinstance(token, str) and len(token) > 20 and not token.startswith("ERROR"):
                                    try:
                                        q.put_nowait((token, time.time()))
                                        with self._lock:
                                            self._total_farmed += 1
                                        any_success = True
                                    except queue.Full:
                                        pass
                                elif token and isinstance(token, str) and token.startswith("ERROR"):
                                    if fail_streak == 0:
                                        self._log(f"{tag} ⚠️ {act}: {token[:80]}")

                        if all_full:
                            time.sleep(5)
                            continue
                        elif any_success:
                            fail_streak = 0
                        else:
                            fail_streak += 1
                            need_reload = self._need_cookie_reload or (fail_streak >= 3)
                            curr_u = ""
                            try: curr_u = str(page.url).lower()
                            except Exception: pass
                            if "about" in curr_u or "accounts.google.com" in curr_u or "signin" in curr_u:
                                need_reload = True

                            if need_reload:
                                self._log(f"{tag} 🔄 Nạp lại cookie mới của tài khoản từ accounts.json...")
                                try:
                                    _acc_path2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.json")
                                    with open(_acc_path2, "r", encoding="utf-8") as f:
                                        _accs = json.load(f)
                                    # CHỈ nạp cookie mới của CHÍNH tài khoản này (không round-robin sang TK khác)
                                    for a in _accs:
                                        if str(a.get("email") or a.get("id") or "").strip().lower() == str(acc_email).strip().lower() and a.get("cookie"):
                                            cookie_str = a["cookie"]
                                            break
                                    project_id = _E.get_project(cookie_str) or project_id or "513f3b20-fa17-4be7-89b5-f179860de580"
                                    target_url = f"https://flow.google.com/project/{project_id}"
                                except Exception as ex:
                                    self._log(f"{tag} ⚠️ Lỗi đọc accounts.json: {ex}")

                                try:
                                    page.get("https://flow.google.com")
                                    time.sleep(2)
                                    _inject_cookies(page, cookie_str)
                                    self._log(f"{tag} 🌐 Tải lại {target_url[-40:]} với cookie mới...")
                                    page.get(target_url)
                                    time.sleep(12)
                                    fail_streak = 0
                                    self._need_cookie_reload = False
                                    self._log(f"{tag} ✅ Đã nạp lại cookie mới thành công!")
                                except Exception as ex:
                                    self._log(f"{tag} ❌ Lỗi inject cookie: {ex}")
                            elif fail_streak >= 5:
                                self._log(f"{tag} 🔄 Reload flow.google.com project page...")
                                page.get(target_url)
                                time.sleep(10)
                                fail_streak = 0

                        # Log thống kê mỗi ~30 vòng (~1-2 phút)
                        _log_counter += 1
                        if _log_counter % 30 == 0:
                            self._log(f"{tag} 📊 Token TK: V:{acc_q['VIDEO_GENERATION'].qsize()} U:{acc_q['UPLOAD_IMAGE'].qsize()} | tổng farm {self._total_farmed}")

                    except Exception as e:
                        fail_streak += 1
                        if fail_streak <= 2:
                            self._log(f"{tag} ❌ Worker exception: {str(e)[:80]}")

                    if any_success:
                        time.sleep(FARM_INTERVAL + random.uniform(-0.5, 1))
                    else:
                        time.sleep(1.5 + random.uniform(0, 1))

            except Exception as e:
                self._log(f"{tag} ❌ Worker crash: {str(e)[:100]}")
                time.sleep(5)
            finally:
                try:
                    if page:
                        page.quit()
                except Exception:
                    pass
            



EXTENSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extension")


class ExtensionBrowserPool:
    """Mở 1 trình duyệt Chrome thật/tài khoản, có nạp sẵn ThinAPTM Flow Bridge
    extension, đăng nhập đúng cookie, điều hướng tới flow.google.com — dùng cho
    chế độ 'Extension' của tab Server-Video (thay vì trại farm token + REST).

    KHÁC RecaptchaFarm: trình duyệt sống suốt phiên chạy (không phải cycle liên
    tục để farm token), KHÔNG ẩn ngoài màn hình (theo lựa chọn người dùng — ưu
    tiên dễ debug ở giai đoạn đầu), và KHÔNG cần botoxSign hook (kỹ thuật đó
    dành riêng cho đường REST cũ trích xuất hàm ký nội bộ — Extension mode gọi
    thẳng window.grecaptcha.enterprise.execute() trong trang, không cần vá gì).
    """

    def __init__(self, log_func=None):
        def _safe_print(m):
            try:
                print(f"[ExtBrowserPool] {m}")
            except Exception:
                print(f"[ExtBrowserPool] {str(m).encode('ascii', 'replace').decode()}")
        self._log = log_func or _safe_print
        self._proxy_resolver = None
        self._pages = {}          # email -> ChromiumPage
        self._lock = threading.Lock()
        self._stop = False

    def set_proxy_resolver(self, fn):
        self._proxy_resolver = fn

    def start_account(self, email, cookie, flow_project_id=None):
        """Mở 1 trình duyệt cho đúng tài khoản này. Gọi lại nhiều lần cho cùng
        email là an toàn (bỏ qua nếu đã có trình duyệt đang chạy). FAIL-CLOSED
        theo đúng mục tiêu "đồng nhất IP": không có cookie hoặc không có proxy
        thì KHÔNG mở trình duyệt (thay vì âm thầm chạy bằng IP máy/chưa đăng nhập)."""
        with self._lock:
            existing = self._pages.get(email)
        if existing is not None:
            # Xác nhận trình duyệt cũ THẬT SỰ còn sống + extension còn kết nối bridge — không chỉ
            # dựa vào việc còn nằm trong self._pages (đã gặp thực tế: trình duyệt/kết nối cũ đã
            # chết nhưng vẫn được coi là "đang chạy" nên lần gọi sau KHÔNG mở trình duyệt mới,
            # trong khi worker lại thấy bridge chưa kết nối -> kẹt vĩnh viễn, không ai mở lại).
            alive = False
            try:
                alive = existing.run_js("return 1") == 1
            except Exception:
                alive = False
            if alive:
                try:
                    import flow_bridge as _FB
                    alive = _FB.is_account_connected(email)
                except Exception:
                    pass
            if alive:
                return True
            with self._lock:
                self._pages.pop(email, None)
            try:
                existing.quit()
            except Exception:
                pass
            self._log(f"[{email[:16]}] ♻️ Trình duyệt cũ đã mất kết nối — mở lại từ đầu.")

        if not cookie:
            self._log(f"❌ [{email[:16]}] Chưa có cookie — vào tab Tài khoản bấm 'Auto login' trước rồi thử lại.")
            return False

        try:
            from DrissionPage import ChromiumOptions, ChromiumPage
        except ImportError:
            self._log("❌ Thiếu DrissionPage — không thể mở trình duyệt Extension mode.")
            return False

        def _resolve_proxy():
            try:
                return self._proxy_resolver(email) if self._proxy_resolver else None
            except Exception:
                return None

        # Chờ tối đa ~20s nếu proxy pool app chưa nạp xong lúc hàm này được gọi (gọi
        # ngay khi bấm Bắt Đầu, trước khi proxy được gán) — y hệt cách recaptcha_farm._worker
        # đã làm cho trại token, tránh mở trình duyệt "trần" bằng IP máy do gọi quá sớm.
        proxy_str = _resolve_proxy()
        for _ in range(20):
            if proxy_str or self._stop:
                break
            time.sleep(1)
            proxy_str = _resolve_proxy()

        if not proxy_str:
            self._log(f"❌ [{email[:16]}] Hết proxy khả dụng trong pool — KHÔNG mở trình duyệt bằng IP máy "
                      f"(phá mục tiêu đồng nhất IP). Thêm proxy vào pool rồi thử lại.")
            return False

        co = ChromiumOptions()
        chrome_path = get_chrome_for_testing_path() or get_chrome_path()
        if chrome_path:
            co.set_browser_path(chrome_path)
        profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "_profiles", str(email).replace("@", "_"))
        co.set_user_data_path(profile_dir)
        co.set_argument("--no-first-run")
        co.set_argument("--no-default-browser-check")
        co.set_argument("--disable-blink-features=AutomationControlled")
        # Thu nhỏ xuống taskbar ngay khi mở — Chrome không cho JS/extension chặn nút X để hỏi xác
        # nhận trước khi thoát, nên cách thực tế để giảm nguy cơ người dùng bấm nhầm tắt cửa sổ
        # đang chạy là không để nó nằm chắn ngay trước mắt. Vẫn xem lại được bất cứ lúc nào qua
        # taskbar khi cần kiểm tra.
        co.set_argument("--start-minimized")
        # BẮT BUỘC: không set thì DrissionPage cố kết nối cổng debug MẶC ĐỊNH 9222 —
        # nếu chưa có Chrome nào tự mở sẵn trên đúng cổng đó, "ChromiumPage(co)" báo
        # "Browser connect failed... port 9222" như đã gặp thực tế. Mỗi trình duyệt
        # (mỗi tài khoản) phải có 1 cổng riêng, giống hệt cách recaptcha_farm._worker
        # đã làm cho farm token.
        import random as _random
        co.set_local_port(_random.randint(30000, 49999))
        if os.path.isdir(EXTENSION_DIR):
            co.add_extension(EXTENSION_DIR)
        else:
            self._log(f"❌ Không tìm thấy thư mục extension tại {EXTENSION_DIR}")
            return False

        proxy_creds = None
        if proxy_str:
            import re as _re
            try:
                import thin_aptm as _T
                _pd = _T.ProxyPool._to_dict(proxy_str)
            except Exception:
                _pd = None
            _url = (_pd or {}).get("http") or ""
            if _url.startswith("socks"):
                co.set_argument("--proxy-server", _url.split("#")[0])
            elif _url:
                _m = _re.match(r"https?://(?:([^:]+):([^@]+)@)?([^:]+):(\d+)", _url)
                if _m:
                    _u, _p, _h, _pt = _m.group(1), _m.group(2), _m.group(3), _m.group(4)
                    co.set_argument("--proxy-server", f"http://{_h}:{_pt}")
                    if _u:
                        proxy_creds = (_u, _p or "")
            # BẮT BUỘC: không có dòng này thì Chrome route LUÔN cả traffic tới 127.0.0.1:<cổng
            # bridge> (WebSocket nội bộ ThinAPTM <-> extension) qua proxy ở xa — proxy đó không thể
            # route ngược về localhost của chính máy mình nên extension KHÔNG BAO GIỜ kết nối được
            # bridge (mọi request tới bridge sẽ mãi timeout dù browser/Flow vẫn hoạt động bình
            # thường, vì Flow đi ra ngoài qua proxy vẫn ổn — chỉ riêng kết nối ngược về localhost
            # là bị proxy nuốt mất). Đã xác nhận đúng nguyên nhân qua thực tế: bridge chỉ từng kết
            # nối được ở các lần KHÔNG dùng proxy.
            co.set_argument("--proxy-bypass-list", "127.0.0.1;localhost;<local>")
            self._log(f"[{email[:16]}] 🌐 Extension mode qua proxy {(_url.split('@')[-1] if _url else '?')[:34]}")
        else:
            self._log(f"[{email[:16]}] ⚠️ Không có proxy → chạy bằng IP máy")

        try:
            page = ChromiumPage(co)
        except Exception as e:
            self._log(f"[{email[:16]}] ❌ Không mở được trình duyệt: {e}")
            return False

        try:
            import browser_stealth
            browser_stealth.apply_stealth(page, log_fn=self._log)
            if proxy_creds:
                browser_stealth.prime_proxy_auth(page, proxy_creds[0], proxy_creds[1], log_fn=self._log)
        except Exception as e:
            self._log(f"[{email[:16]}] ⚠️ Lỗi nạp stealth/proxy-auth: {e}")

        # Nếu profile này đã có phiên Chrome THẬT đang sống (vừa login qua login.py với đúng
        # profile_dir + proxy này) → dùng LUÔN session tự nhiên đó, KHÔNG tiêm cookie đè lên.
        # Lý do: cookie lưu trong accounts.json chỉ là 1 tập con đã lọc (_labs_cookie), tiêm qua
        # CDP Network.setCookie đè lên 1 session thật đang sống dễ làm lệch các cookie xoay vòng
        # (SIDCC/__Secure-1PSIDTS...) → Google phát hiện bất thường, báo CookieMismatch — đã gặp
        # thực tế dù proxy + profile khớp hệt lúc login.
        # QUAN TRỌNG: kiểm tra bằng cookie THẬT đang có trong trình duyệt (page.cookies() sau khi
        # điều hướng), KHÔNG dùng sự tồn tại của file "Local State" — Chrome tạo file đó ngay khi
        # mở lần đầu dù CHƯA đăng nhập gì cả (đã gặp thực tế: lần mở đầu thất bại vẫn để lại file
        # này, khiến lần mở sau tưởng nhầm "đã có session" rồi bỏ qua tiêm cookie, để lại trình
        # duyệt hoàn toàn trống).
        try:
            page.get("https://flow.google.com")
            time.sleep(1.5)
            has_real_session = False
            try:
                live_cookies = page.cookies(all_domains=True) or []
                has_real_session = any(
                    "google" in (c.get("domain", "") or "") and c.get("name") in
                    ("SID", "__Secure-1PSID", "__Secure-3PSID", "HSID", "SSID", "OSID", "__Secure-OSID")
                    for c in live_cookies
                )
            except Exception:
                has_real_session = False
            if not has_real_session:
                _inject_cookies(page, cookie)
            else:
                self._log(f"[{email[:16]}] 🍪 Dùng phiên Chrome thật đã có sẵn trong profile (không tiêm cookie đè).")
        except Exception as e:
            self._log(f"[{email[:16]}] ⚠️ Lỗi inject cookie: {e}")

        # KHÔNG đoán bừa 1 UUID project cố định khi chưa biết flow_project_id thật của tài khoản
        # này — project đó thuộc về tài khoản KHÁC (thường là tài khoản đầu tiên từng test), TK
        # khác không có quyền truy cập sẽ bị Google trả "Project not found" (404), rơi vào trang
        # lỗi mà content.js không nhận diện được (script tự tạo project mới chỉ tìm nút "Dự án
        # mới" trên trang chủ, không có trên trang 404) → kẹt vĩnh viễn, không tự phục hồi được.
        # Chưa biết project thật → điều hướng thẳng về TRANG CHỦ, để content.js tự phát hiện +
        # tự bấm "Dự án mới" đúng luồng đã thiết kế.
        target_url = (f"https://flow.google.com/project/{flow_project_id}?_tam_email={email}"
                      if flow_project_id else f"https://flow.google.com/?_tam_email={email}")
        try:
            page.get(target_url)
        except Exception as e:
            self._log(f"[{email[:16]}] ❌ Không điều hướng được tới Flow: {e}")
            try:
                page.quit()
            except Exception:
                pass
            return False

        # Xác nhận extension THỰC SỰ đã kết nối bridge trước khi báo thành công — nếu không,
        # đóng luôn trình duyệt vừa mở (tránh treo cửa sổ vô ích không ai theo dõi).
        try:
            import flow_bridge as _FB
            connected = False
            for _ in range(30):
                if _FB.is_account_connected(email):
                    connected = True
                    break
                if self._stop:
                    break
                time.sleep(1)
            if not connected:
                self._log(f"❌ [{email[:16]}] Trình duyệt đã mở nhưng extension không tự kết nối bridge sau 30s "
                          f"— kiểm tra extension đã cài đúng chưa. Đang đóng trình duyệt này lại.")
                try:
                    page.quit()
                except Exception:
                    pass
                return False
        except Exception as e:
            self._log(f"[{email[:16]}] ⚠️ Lỗi kiểm tra kết nối bridge: {e}")

        with self._lock:
            self._pages[email] = page
        self._log(f"[{email[:16]}] 🧩 Đã mở trình duyệt Extension mode, extension đã kết nối bridge thành công.")
        return True

    def is_running(self, email):
        with self._lock:
            return email in self._pages

    def stop_account(self, email):
        with self._lock:
            page = self._pages.pop(email, None)
        if page:
            try:
                page.quit()
            except Exception:
                pass

    def stop_all(self):
        self._stop = True
        with self._lock:
            emails = list(self._pages.keys())
        for email in emails:
            self.stop_account(email)


_ext_pool_instance = None
_ext_pool_lock = threading.Lock()


def get_extension_pool(log_func=None):
    global _ext_pool_instance
    with _ext_pool_lock:
        if _ext_pool_instance is None:
            _ext_pool_instance = ExtensionBrowserPool(log_func=log_func)
        return _ext_pool_instance


def stop_extension_pool():
    global _ext_pool_instance
    with _ext_pool_lock:
        if _ext_pool_instance:
            _ext_pool_instance.stop_all()
            _ext_pool_instance = None


# ============ SINGLETON cho toàn app ============
_farm_instance = None
_farm_lock = threading.Lock()


def get_farm(num_workers=2, log_func=None):
    """Lấy hoặc tạo singleton RecaptchaFarm. Tự động khởi động lại nếu số luồng cấu hình thay đổi."""
    global _farm_instance
    with _farm_lock:
        if _farm_instance is not None and _farm_instance.num_workers != num_workers:
            try:
                _farm_instance.stop()
            except Exception:
                pass
            _farm_instance = None
        if _farm_instance is None:
            _farm_instance = RecaptchaFarm(num_workers=num_workers, log_func=log_func)
        return _farm_instance


def stop_farm():
    """Dừng singleton farm."""
    global _farm_instance
    with _farm_lock:
        if _farm_instance:
            _farm_instance.stop()
            _farm_instance = None
