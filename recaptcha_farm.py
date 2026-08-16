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

# reCAPTCHA site key cho Google Labs Flow (public, nhúng trong page source labs.google)
# Đây là enterprise key, dùng với grecaptcha.enterprise.execute()
RECAPTCHA_SITE_KEY = "6LfhM_ApAAAAADuqA_eP-MKgjABwMikSfOjQbpaK"
RECAPTCHA_ACTION = "LABS_FLOW"
LABS_URL = "https://labs.google/fx/tools/flow"

# Số token tồn kho tối đa (token hết hạn sau ~2 phút nên không nên giữ quá nhiều)
MAX_QUEUE = 20
# Token hết hạn sau bao lâu (giây) — Google reCAPTCHA token sống ~120s
TOKEN_TTL = 100
# Thời gian chờ giữa các lần farm (giây)
FARM_INTERVAL = 8


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
    
    def __init__(self, num_workers=3, log_func=None):
        self.num_workers = num_workers
        self._log = log_func or (lambda m: print(f"[RecaptchaFarm] {m}"))
        self._queue = queue.Queue(maxsize=MAX_QUEUE)
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
            self._log("❌ Thiếu DrissionPage — không thể farm token. Dùng android_bypass.")
            return False
        
        for i in range(self.num_workers):
            t = threading.Thread(target=self._worker, args=(i,), daemon=True,
                                 name=f"RecaptchaFarm-{i}")
            t.start()
            self._workers.append(t)
            time.sleep(0.5)  # stagger khởi động để tránh dồn
        
        self._started = True
        self._log(f"✅ Trại Token đã khởi động — {self.num_workers}/{self.num_workers} luồng sẵn sàng")
        return True
    
    def stop(self):
        """Dừng farm."""
        self._stop = True
        self._started = False
        # Không join workers vì chúng là daemon threads
        self._log(f"⏹ Trại Token đã dừng. Tổng token đã farm: {self._total_farmed}")
    
    def get_token(self, timeout=15):
        """Lấy 1 token tươi từ queue. Trả token string hoặc None nếu timeout.
        Tự bỏ token quá hạn."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                token, ts = self._queue.get(timeout=min(2, deadline - time.time()))
                # Kiểm tra token còn hạn không
                if time.time() - ts < TOKEN_TTL:
                    return token
                # Token quá hạn → bỏ, lấy cái kế
                continue
            except queue.Empty:
                continue
        return None
    
    def queue_size(self):
        """Số token đang có trong kho."""
        return self._queue.qsize()
    
    def stats(self):
        """Thống kê."""
        return {
            "running": self._started,
            "workers": len(self._workers),
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
            # --- Cực kỳ tối ưu CPU cho Chrome ngầm ---
            co.set_argument("--blink-settings=imagesEnabled=false")
            co.set_argument("--disable-software-rasterizer")
            co.set_argument("--disable-dev-shm-usage")
            co.set_argument("--no-sandbox")
            co.set_argument("--disable-webgl")
            # Chặn tải ảnh ở mức profile settings
            co.set_pref("profile.default_content_setting_values.images", 2)
            co.set_pref("profile.managed_default_content_settings.images", 2)
            
            co.set_local_port(random.randint(30000, 49999))

            page = ChromiumPage(co)
            page.set.retry_times(2)

            # Load trang labs.google để có origin và script reCAPTCHA
            page.get(LABS_URL)
            time.sleep(2)

            # Inject reCAPTCHA enterprise script nếu chưa có
            inject_js = f"""
                if (!window._rcFarmReady) {{
                    var s = document.createElement('script');
                    s.src = 'https://www.google.com/recaptcha/enterprise.js?render={RECAPTCHA_SITE_KEY}';
                    s.onload = function() {{ window._rcFarmReady = true; }};
                    document.head.appendChild(s);
                }}
            """
            page.run_js(inject_js)
            time.sleep(2)

            self._log(f"{tag} 🟢 DrissionPage Chrome sẵn sàng, bắt đầu farm")

            exec_js = f"""
            return new Promise((resolve) => {{
                function executeToken() {{
                    try {{
                        if (typeof grecaptcha === 'undefined' || !grecaptcha.enterprise) {{
                            resolve('ERROR:grecaptcha_undefined');
                            return;
                        }}
                        grecaptcha.enterprise.ready(function() {{
                            grecaptcha.enterprise.execute('{RECAPTCHA_SITE_KEY}', {{action: '{RECAPTCHA_ACTION}'}})
                                .then(function(token) {{ resolve(token); }})
                                .catch(function(err) {{ resolve('ERROR:' + err); }});
                        }});
                    }} catch(e) {{
                        resolve('ERROR:' + e);
                    }}
                }}
                executeToken();
            }});
            """

            fail_streak = 0
            while not self._stop:
                try:
                    token = page.run_js(exec_js)
                    if token and isinstance(token, str) and len(token) > 20 and not token.startswith("ERROR"):
                        try:
                            self._queue.put_nowait((token, time.time()))
                            with self._lock:
                                self._total_farmed += 1
                            fail_streak = 0
                        except queue.Full:
                            pass
                    else:
                        fail_streak += 1
                        if fail_streak >= 5:
                            page.get(LABS_URL)
                            time.sleep(2)
                            page.run_js(inject_js)
                            time.sleep(2)
                            fail_streak = 0

                except Exception as e:
                    fail_streak += 1

                time.sleep(FARM_INTERVAL + random.uniform(-1, 2))

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
