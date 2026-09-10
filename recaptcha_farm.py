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
FLOW_URL = "https://labs.google/fx/tools/flow"
LABS_URL = FLOW_URL

# Số token tồn kho tối đa (token hết hạn sau ~2 phút nên không nên giữ quá nhiều)
MAX_QUEUE = 20
# Token hết hạn sau bao lâu (giây) — Google reCAPTCHA token sống ~120s
TOKEN_TTL = 100
# Thời gian chờ giữa các lần farm (giây)
FARM_INTERVAL = 3


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
        self._queues = {
            "VIDEO_GENERATION": queue.Queue(maxsize=MAX_QUEUE),
            "UPLOAD_IMAGE": queue.Queue(maxsize=MAX_QUEUE),
        }
        self._queue = self._queues["VIDEO_GENERATION"]
        self._stop = False
        self._workers = []
        self._started = False
        self._total_farmed = 0
        self._lock = threading.Lock()
    
    def start(self):
        """Khởi động farm. Trả True nếu thành công."""
        if self._started:
            return True
        self._stop = False
        self._log(f"🐑 Khởi động Trại Token: {self.num_workers} luồng...")
        
        # Kiểm tra DrissionPage
        try:
            from DrissionPage import ChromiumOptions, ChromiumPage
        except ImportError:
            self._log("❌ Thiếu DrissionPage — không thể farm token.")
            return False
        
        for i in range(self.num_workers):
            t = threading.Thread(target=self._worker, args=(i,), daemon=True,
                                 name=f"RecaptchaFarm-{i}")
            t.start()
            self._workers.append(t)
            time.sleep(0.5)
        
        self._started = True
        self._log(f"✅ Trại Token đã khởi động — {self.num_workers}/{self.num_workers} luồng sẵn sàng")
        return True
    
    def stop(self):
        """Dừng farm."""
        self._stop = True
        self._started = False
        self._log(f"⏹ Trại Token đã dừng. Tổng token đã farm: {self._total_farmed}")
    
    def get_token(self, timeout=15, action="VIDEO_GENERATION"):
        """Lấy 1 token tươi từ queue cho action tương ứng (VIDEO_GENERATION hoặc UPLOAD_IMAGE).
        Trả token string hoặc None nếu timeout. Tự bỏ token quá hạn.
        Tự động fallback sang queue còn lại nếu queue yêu cầu đang tạm hết."""
        q = self._queues.get(action, self._queue)
        alt_action = "UPLOAD_IMAGE" if action == "VIDEO_GENERATION" else "VIDEO_GENERATION"
        alt_q = self._queues.get(alt_action)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                item = q.get(timeout=min(1.0, max(0.1, deadline - time.time())))
                if isinstance(item, tuple):
                    token, ts = item
                    if time.time() - ts < TOKEN_TTL:
                        return token
                elif isinstance(item, str):
                    return item
            except queue.Empty:
                if alt_q and not alt_q.empty():
                    try:
                        item = alt_q.get_nowait()
                        if isinstance(item, tuple):
                            token, ts = item
                            if time.time() - ts < TOKEN_TTL:
                                return token
                        elif isinstance(item, str):
                            return item
                    except queue.Empty:
                        pass
                continue
        return None
    
    def qsize(self, action="VIDEO_GENERATION"):
        """Số token tươi hiện có trong queue."""
        return self._queues.get(action, self._queue).qsize()
    
    def stats(self):
        """Thống kê farm."""
        return {
            "workers": len(self._workers),
            "started": self._started,
            "queued_video": self._queues["VIDEO_GENERATION"].qsize(),
            "queued_upload": self._queues["UPLOAD_IMAGE"].qsize(),
            "queued": self._queue.qsize(),
            "total_farmed": self._total_farmed,
        }
    
    def _worker(self, worker_id):
        """Worker thread: mở Chrome headless qua DrissionPage, farm token liên tục."""
        import random
        try:
            from DrissionPage import ChromiumOptions, ChromiumPage
        except ImportError:
            self._log("❌ Thiếu DrissionPage — không thể farm token.")
            return

        tag = f"[Farm-{worker_id}]"
        page = None

        try:
            co = ChromiumOptions()
            chrome_path = get_chrome_path()
            if chrome_path:
                co.set_browser_path(chrome_path)
            co.set_argument("--disable-extensions")
            co.set_argument("--mute-audio")
            co.set_argument("--no-first-run")
            co.set_argument("--no-default-browser-check")
            co.set_argument("--disable-gpu")
            co.set_argument("--headless")
            co.set_argument("--blink-settings=imagesEnabled=false")
            co.set_argument("--disable-software-rasterizer")
            co.set_argument("--disable-dev-shm-usage")
            co.set_argument("--no-sandbox")
            co.set_argument("--disable-webgl")
            co.set_pref("profile.default_content_setting_values.images", 2)
            co.set_pref("profile.managed_default_content_settings.images", 2)
            
            # Chọn profile có sẵn — MỖI worker cần 1 profile RIÊNG (không được dùng chung user-data-dir)
            pdir = self.profile_dir
            if not pdir:
                profiles_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_profiles")
                if os.path.exists(profiles_dir):
                    sub = [os.path.join(profiles_dir, d) for d in os.listdir(profiles_dir)
                           if os.path.isdir(os.path.join(profiles_dir, d)) and not d.startswith("_farm_")]
                    # Ưu tiên các profile đã đăng nhập (như colecole2627_gmail.com)
                    auth_candidates = [p for p in sub if "cole" in os.path.basename(p).lower()]
                    source_pool = auth_candidates if auth_candidates else sub
                    if source_pool:
                        source_profile = source_pool[worker_id % len(source_pool)]
                        # Tạo bản copy riêng cho worker này để tránh lock conflict
                        farm_profile = os.path.join(profiles_dir, f"_farm_{worker_id}")
                        if not os.path.exists(farm_profile):
                            import shutil
                            try:
                                shutil.copytree(source_profile, farm_profile, 
                                              ignore=shutil.ignore_patterns("*.lock", "*.lck", "lockfile", "SingletonLock", "SingletonSocket", "SingletonCookie"),
                                              dirs_exist_ok=True)
                                self._log(f"{tag} Copied profile from {os.path.basename(source_profile)} -> _farm_{worker_id}")
                            except Exception as e:
                                self._log(f"{tag} Profile copy failed: {e}, using fresh profile")
                                os.makedirs(farm_profile, exist_ok=True)
                        pdir = farm_profile
            if pdir:
                co.set_user_data_path(pdir)

            co.set_local_port(random.randint(30000, 49999))

            page = ChromiumPage(co)
            page.set.retry_times(2)

            page.get(FLOW_URL)
            time.sleep(5)

            self._log(f"{tag} 🟢 DrissionPage Chrome sẵn sàng, bắt đầu farm")

            def _build_exec_js(act):
                return f"""
                return new Promise((resolve) => {{
                    try {{
                        if (typeof grecaptcha === 'undefined' || !grecaptcha.enterprise) {{
                            resolve('ERROR:grecaptcha_undefined');
                            return;
                        }}
                        grecaptcha.enterprise.ready(function() {{
                            grecaptcha.enterprise.execute('{RECAPTCHA_SITE_KEY}', {{action: '{act}'}})
                                .then(function(token) {{ resolve(token); }})
                                .catch(function(err) {{ resolve('ERROR:' + err); }});
                        }});
                    }} catch(e) {{
                        resolve('ERROR:' + e);
                    }}
                }});
                """
            exec_js_map = {act: _build_exec_js(act) for act in ["VIDEO_GENERATION", "UPLOAD_IMAGE"]}

            fail_streak = 0
            while not self._stop:
                try:
                    any_success = False
                    for act, js_code in exec_js_map.items():
                        q = self._queues[act]
                        if q.qsize() < MAX_QUEUE:
                            token = page.run_js(js_code)
                            if token and isinstance(token, str) and len(token) > 20 and not token.startswith("ERROR"):
                                try:
                                    q.put_nowait((token, time.time()))
                                    with self._lock:
                                        self._total_farmed += 1
                                    any_success = True
                                except queue.Full:
                                    pass

                    if any_success:
                        fail_streak = 0
                    else:
                        fail_streak += 1
                        if fail_streak >= 4:
                            page.get(FLOW_URL)
                            time.sleep(5)
                            fail_streak = 0

                except Exception as e:
                    fail_streak += 1

                # Sleep ngắn khi thành công (farm nhanh hơn), dài hơn khi fail liên tục
                if any_success:
                    time.sleep(FARM_INTERVAL + random.uniform(-0.5, 1))
                else:
                    time.sleep(1.5 + random.uniform(0, 1))

        except Exception as e:
            self._log(f"{tag} ❌ Worker crash: {str(e)[:100]}")
        finally:
            try:
                if page:
                    page.quit()
            except Exception:
                pass
            



# ============ SINGLETON cho toàn app ============
_farm_instance = None
_farm_lock = threading.Lock()


def get_farm(num_workers=3, log_func=None):
    """Lấy hoặc tạo singleton RecaptchaFarm."""
    global _farm_instance
    with _farm_lock:
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
