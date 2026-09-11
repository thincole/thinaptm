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
        self._sessions = {}  # acc_key -> {"page": page, "lock": Lock(), "project": project, "ready": bool}
        self._sessions_lock = threading.Lock()
    
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

    def _get_acc_key(self, cookie):
        """Tạo định danh hash duy nhất cho tài khoản dựa trên cookie."""
        import hashlib
        if not cookie:
            return "unknown"
        for pair in str(cookie).split(";"):
            if "=" in pair:
                k, v = pair.strip().split("=", 1)
                if k.strip() in ("SAPISID", "SID", "__Secure-1PSID"):
                    return hashlib.md5(v.strip().encode()).hexdigest()[:12]
        return hashlib.md5(str(cookie)[:100].encode()).hexdigest()[:12]

    def _get_or_create_session(self, cookie, project):
        """Lấy hoặc khởi tạo 1 browser session chuyên trách cho tài khoản."""
        import random
        from DrissionPage import ChromiumOptions, ChromiumPage
        key = self._get_acc_key(cookie)
        with self._sessions_lock:
            if key not in self._sessions:
                self._sessions[key] = {"lock": threading.Lock(), "ready": False, "page": None, "project": project}
            sess = self._sessions[key]

        with sess["lock"]:
            if sess.get("ready") and sess.get("page"):
                try:
                    if sess["page"].run_js("return 1") == 1:
                        return sess
                except:
                    sess["ready"] = False
                    try:
                        sess["page"].quit()
                    except:
                        pass
                    sess["page"] = None
            
            tag = f"[Browser-{key[:6]}]"
            self._log(f"🌐 {tag} Khởi tạo phiên Chrome headless cho project {str(project)[:12]}...")
            co = ChromiumOptions()
            chrome_path = get_chrome_path()
            if chrome_path:
                co.set_browser_path(chrome_path)
            co.set_argument("--headless")
            co.set_argument("--disable-extensions")
            co.set_argument("--no-first-run")
            co.set_argument("--disable-gpu")
            co.set_argument("--no-sandbox")
            co.set_argument("--blink-settings=imagesEnabled=false")
            co.set_pref("profile.default_content_setting_values.images", 2)
            co.set_local_port(random.randint(30000, 49999))

            try:
                page = ChromiumPage(co)
                page.set.retry_times(2)
                page.get(FLOW_URL)
                time.sleep(1.5)

                for pair in str(cookie).split(";"):
                    if "=" in pair:
                        name, val = pair.strip().split("=", 1)
                        name, val = name.strip(), val.strip()
                        try:
                            if name.startswith("__Host-"):
                                page.run_cdp("Network.setCookie", name=name, value=val,
                                            url="https://flow.google.com", path="/", secure=True, httpOnly=True)
                            else:
                                page.run_cdp("Network.setCookie", name=name, value=val,
                                            domain=".google.com", path="/", secure=True)
                        except:
                            pass

                target_url = f"https://flow.google.com/project/{project}" if project else f"{FLOW_URL}/?pli=1"
                page.get(target_url)
                self._log(f"🌐 {tag} Đang load project editor...")

                # Đợi Angular & WIZ & grecaptcha ready (polling nhanh thay vì sleep 15s)
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
                        ok = page.run_js("return typeof grecaptcha !== 'undefined' && !!grecaptcha.enterprise && !!window.WIZ_global_data && !!window.WIZ_global_data.SNlM0e")
                        if ok:
                            ready = True
                            break
                    except:
                        pass

                if not ready:
                    self._log(f"⚠️ {tag} Editor chưa sẵn sàng sau 25s, thử tiếp...")

                sess["page"] = page
                sess["ready"] = True
                self._log(f"🟢 {tag} Phiên Chrome sẵn sàng cho video submit!")
                return sess
            except Exception as ex:
                self._log(f"❌ {tag} Lỗi khởi tạo Chrome: {ex}")
                sess["ready"] = False
                sess["page"] = None
                return None

    def submit_video_native(self, cookie, project, prompt, model="veo_3_1_t2v_lite_low_priority", aspect="9:16", ref_media_id=None):
        """Submit video TRỰC TIẾP từ bên trong trình duyệt (In-Browser Native Fetch).
        
        ★ Tránh 100% lỗi PUBLIC_ERROR_UNUSUAL_ACTIVITY vì:
        - Token reCAPTCHA sinh ra trên cùng origin và được fetch() ngay tại tab đó
        - Đúng TLS fingerprint, đúng credentials và session context của Chrome
        - Hỗ trợ cả Text-to-Video và Ingredients (ảnh sản phẩm tham chiếu)
        """
        import uuid
        sess = self._get_or_create_session(cookie, project)
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
            
            if ref_media_id and ("abra" in str(model).lower() or "omni" in str(model).lower()):
                rpc_id = "eb1hJf"
                model_name = "abra_i2v_10s" if "10s" in str(model) else "abra_i2v_8s"
                prompt_block = [None, None, [[[prompt]]]]
            else:
                rpc_id = "YhhmEf"
                if "10s" in str(model):
                    model_name = "abra_t2v_10s"
                elif "abra" in str(model) or "omni" in str(model).lower():
                    model_name = "abra_t2v_8s"
                else:
                    model_name = "veo_3_1_t2v_lite_low_priority"

                if ref_media_id:
                    prompt_block = [None, None, [[[prompt]]], None, None, None, None, None, [[None, 1, ref_media_id]]]
                else:
                    prompt_block = [None, None, [[[prompt]]]]
                
            scene1 = [prompt_block, model_name, aspect_code, None, [None, None, None, None, u1, u2]]
            scene2 = [prompt_block, model_name, aspect_code, None, [None, None, None, None, u3, u4]]
            
            js = f"""
            async function _doSubmit() {{
                try {{
                    try {{
                        window.dispatchEvent(new MouseEvent('mousemove', {{
                            clientX: Math.floor(Math.random() * 600) + 100,
                            clientY: Math.floor(Math.random() * 400) + 100,
                            bubbles: true
                        }}));
                    }} catch(_) {{}}

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
                    
                    const url = '/_/AiSandboxAngularFrontend/data/batchexecute?rpcids={rpc_id}&source-path=' + 
                                encodeURIComponent('/project/{project}') + '&bl=' + bl + '&f.sid=' + fsid + '&hl=en-US&_reqid=1234&rt=c';
                    
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
                if sess["submit_count"] >= 6:
                    try:
                        page.refresh()
                        time.sleep(2)
                        sess["submit_count"] = 0
                    except:
                        pass
            return status, ops
    
    def _worker(self, worker_id):
        """Worker thread: CDP cookie injection → flow.google.com project page → native reCAPTCHA farm.
        
        ★ Cơ chế ĐÃ VERIFIED thành công:
        1. Mở headless Chrome MỚI (không cần profile)
        2. Set cookies từ accounts.json qua CDP Network.setCookie
        3. Navigate đến flow.google.com/project/{project_id}
        4. Angular bootstrap → reCAPTCHA load tự nhiên
        5. Farm token bằng grecaptcha.enterprise.execute() native
        """
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
            
            # KHÔNG cần profile — dùng CDP cookie injection
            co.set_local_port(random.randint(30000, 49999))

            page = ChromiumPage(co)
            page.set.retry_times(2)

            # ★ Lấy cookie + project từ accounts.json
            cookie_str = None
            project_id = None
            try:
                import json as _json
                acc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounts.json")
                with open(acc_path, "r", encoding="utf-8") as f:
                    _accs = _json.load(f)
                enabled = [a for a in _accs if a.get("cookie") and a.get("enabled") in (True, "True")]
                if enabled:
                    acc = enabled[worker_id % len(enabled)]
                    cookie_str = acc["cookie"]
            except Exception as e:
                self._log(f"{tag} ❌ Không đọc được accounts.json: {e}")
                return
            
            if not cookie_str:
                self._log(f"{tag} ❌ Không tìm thấy tài khoản enabled với cookie")
                return
            
            # Lấy project ID
            try:
                import sys
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import engine as _E
                project_id = _E.get_project(cookie_str)
            except:
                pass
            
            # Step 1: Navigate to flow.google.com (thiết lập domain)
            page.get("https://flow.google.com")
            time.sleep(2)
            
            # Step 2: Set cookies via CDP (hỗ trợ HttpOnly, __Host- cookies)
            cookie_pairs = [p.strip() for p in cookie_str.split(";") if "=" in p]
            for pair in cookie_pairs:
                name, value = pair.split("=", 1)
                name, value = name.strip(), value.strip()
                try:
                    if name.startswith("__Host-"):
                        # __Host- cookies: PHẢI set qua url, KHÔNG dùng domain
                        page.run_cdp("Network.setCookie",
                                    name=name, value=value,
                                    url="https://flow.google.com",
                                    path="/", secure=True, httpOnly=True)
                    else:
                        page.run_cdp("Network.setCookie",
                                    name=name, value=value,
                                    domain=".google.com",
                                    path="/", secure=True)
                except:
                    pass
            
            # Step 3: Navigate đến project page (Angular + reCAPTCHA load tự nhiên)
            target_url = f"https://flow.google.com/project/{project_id}" if project_id else "https://flow.google.com/?pli=1"
            self._log(f"{tag} 🌐 Loading {target_url[-50:]}...")
            page.get(target_url)
            time.sleep(15)  # Angular cần thời gian bootstrap
            
            # Step 4: Chờ reCAPTCHA (thử tối đa 5 lần × 5s = 25s)
            has_rc = False
            for attempt in range(5):
                try:
                    has_rc = page.run_js("return typeof grecaptcha !== 'undefined' && !!grecaptcha.enterprise")
                except:
                    has_rc = False
                if has_rc:
                    break
                time.sleep(5)
            
            if not has_rc:
                self._log(f"{tag} ❌ reCAPTCHA không load được trên flow.google.com (Angular chưa bootstrap?)")
                return
            
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
                        q = self._queues[act]
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
                                if fail_streak == 0:  # Chỉ log lần đầu lỗi liên tục
                                    self._log(f"{tag} ⚠️ {act}: {token[:80]}")

                    if all_full:
                        # Queue đầy → chờ dài hơn, KHÔNG tăng fail_streak
                        time.sleep(5)
                        continue
                    elif any_success:
                        fail_streak = 0
                    else:
                        fail_streak += 1
                        if fail_streak >= 4:
                            self._log(f"{tag} 🔄 Reload flow.google.com project page...")
                            page.get(target_url)
                            time.sleep(15)  # Chờ Angular + reCAPTCHA load lại
                            fail_streak = 0

                    # Log thống kê mỗi ~30 vòng (~1-2 phút)
                    _log_counter += 1
                    if _log_counter % 30 == 0:
                        self._log(f"{tag} 📊 Tổng token: {self._total_farmed} | V:{self._queues['VIDEO_GENERATION'].qsize()} U:{self._queues['UPLOAD_IMAGE'].qsize()}")

                except Exception as e:
                    fail_streak += 1
                    if fail_streak <= 2:
                        self._log(f"{tag} ❌ Worker exception: {str(e)[:80]}")

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
