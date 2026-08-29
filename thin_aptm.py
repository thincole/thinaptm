"""
Thìn Aptm — Tạo VIDEO Google Flow (android_bypass). GUI 3 tab: Tài khoản / Tạo video / Hàng đợi.
Chạy: SETUP.bat (cài đủ) rồi CHAY.bat.
"""
import os, sys, json, time, threading, traceback, queue, random, collections, urllib.request, urllib.parse, uuid
from concurrent.futures import ThreadPoolExecutor

try:
    import customtkinter as ctk
    from tkinter import filedialog, messagebox
except Exception:
    print("Thiếu customtkinter -> chạy SETUP.bat"); sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import engine as E
try:
    import login as L
except Exception:
    L = None
try:
    import shopeevideo as SV
except Exception:
    SV = None

APP_VERSION = "ThinAPTM 1.2.14"
ACC_FILE = os.path.join(HERE, "accounts.json")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
ctk.set_appearance_mode("light"); ctk.set_default_color_theme("blue")
AC = "#1a73e8"; AC2 = "#1557b0"; GR = "#00897B"; RD = "#EA4335"; BG = "#f4f6fb"; CARD = "#ffffff"; T1 = "#202124"; T2 = "#5f6368"


def load_accs():
    try: return json.load(open(ACC_FILE, encoding="utf-8"))
    except Exception: return []

def save_accs(a):
    json.dump(a, open(ACC_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

SETTINGS_FILE = os.path.join(HERE, "settings.json")

def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_settings(s):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def clean_filename(s):
    for c in r'\/:*?"<>|':
        s = s.replace(c, "_")
    s = s.replace("\n", " ").replace("\r", " ")
    return s.strip()


_ACCENTS_MAP = {
    'a': 'áàảãạăắằẳẵặâấầẩẫậ',
    'A': 'ÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬ',
    'd': 'đ', 'D': 'Đ',
    'e': 'éèẻẽẹêếềểễệ',
    'E': 'ÉÈẺẼẸÊẾỀỂỄỆ',
    'i': 'íìỉĩị',
    'I': 'ÍÌỈĨỊ',
    'o': 'óòỏõọôốồổỗộơớờởỡợ',
    'O': 'ÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢ',
    'u': 'úùủũụưứừửữự',
    'U': 'ÚÙỦŨỤƯỨỪỬỮỰ',
    'y': 'ýỳỷỹỵ',
    'Y': 'ÝỲỶỸỴ',
}
# Bảng tra cứu 1 ký tự -> ký tự không dấu (O(1) thay vì quét toàn bộ map mỗi ký tự)
_ACCENTS_LOOKUP = {ch: base for base, chars in _ACCENTS_MAP.items() for ch in chars}


def remove_vietnamese_accents(s):
    """Khử dấu tiếng Việt để làm tên file/thư mục không bị lỗi font trên Windows."""
    return "".join(_ACCENTS_LOOKUP.get(c, c) for c in s)


def get_unique_out_path(directory, filename, existing_set):
    base_name, ext = os.path.splitext(filename)
    candidate = filename
    counter = 1
    full_path = os.path.join(directory, candidate)
    while os.path.exists(full_path) or full_path in existing_set:
        candidate = f"{base_name}_{counter}{ext}"
        full_path = os.path.join(directory, candidate)
        counter += 1
    return full_path


def _find_brand():
    """Tên tool + logo = file png trong thư mục (vd ThinAptm.png -> 'ThinAptm').
    Ưu tiên png trùng tên thư mục; nếu không có thì lấy png đầu tiên. Không có png -> tên mặc định."""
    try:
        pngs = [f for f in os.listdir(HERE) if f.lower().endswith(".png")]
    except Exception:
        pngs = []
    if not pngs:
        return "Thìn Aptm", None
    folder = os.path.basename(HERE.rstrip("\\/"))
    pick = next((f for f in pngs if os.path.splitext(f)[0].lower() == folder.lower()), pngs[0])
    return os.path.splitext(pick)[0], os.path.join(HERE, pick)


# ============ THAM SỐ ĐỘNG CƠ CHẠY (đo thực từ API Google Flow) ============
# 🎯 CHẾ ĐỘ AN TOÀN — giảm worker để tránh Thundering Herd (15 worker dồn upload → 429 ngay).
#     AutoVeo3 chỉ chạy 1-2 upload cùng lúc — 3 workers + AIMD sẽ tương đương.
#     3 workers → tối đa 1-2 submit thực tế (1 bận poll), tránh dồn upload gây 429.
WORKERS_PER_ACCOUNT = 8    # Tối ưu: 8 workers (Tạo max = 8)
GEN_ATTEMPTS = 60          
# --- Cổng submit THÍCH ỨNG (AIMD):
SUBMIT_START = 7.0         
SUBMIT_MIN = 2.0           # Tốc độ min = 2
SUBMIT_MAX = 20.0          # Tốc độ max = 20
SUBMIT_UP_AFTER = 5        
SUBMIT_DOWN = 0.5          # gặp throttle thì nhân giới hạn với số này (giảm nhân — multiplicative decrease)
BYPASS_QUICK = 0.4         # bypass/token trượt -> thử lại NHANH (giây)
THROTTLE_SLEEP = 8.0       # 429 → nghỉ 8s (trước để 3s quá nhanh khiến máy chủ Google ghim 429 liên tục)
QUOTA_HARD_REST = 6 * 3600 # CHỈ khi HẾT QUOTA THẬT (reason quota/credit/daily) -> cách ly dài, đổi account
AUTH_REST = 1800           # nghỉ 30' khi 401 không cứu được bằng refresh cookie
BEARER_TTL = 1200          # refresh bearer từ cookie sau 20' (bearer Google chết ~30')
JOB_MAX_CYCLES = 30        # 1 job được chuyền/thử tối đa 30 lượt (work-stealing giữa accounts cần đủ kiên nhẫn)
POLL_MAX = 60              # số lần poll trạng thái render / job
AUTO_RETRY_ROUNDS = 2      # sau khi chạy xong, TỰ retry các job lỗi thêm bao nhiêu vòng
MAX_REWRITES = 3           # prompt vi phạm -> nhờ Gemini viết lại tối đa bao nhiêu lần trước khi bỏ
# LƯU Ý: model lite (t2v_lite / r2v_lite) MIỄN PHÍ -> không tốn credit -> KHÔNG cách ly theo credit.
# Account chỉ bị throttle (giới hạn tốc độ) và tự hồi; AIMD tự giảm tốc là đủ.


def _dur_label(secs):
    """'6h' / '1.5h' / '30p' cho nhãn hiển thị."""
    if secs >= 3600:
        h = secs / 3600.0
        return f"{int(h)}h" if h == int(h) else f"{h:.1f}h"
    return f"{int(secs // 60)}p"


class ProxyPool:
    """Pool proxy dùng chung cho tất cả AccountState. Thread-safe.
    Hỗ trợ: ip:port, ip:port:user:pass, http://user:pass@ip:port"""
    def __init__(self, proxy_lines=None, disabled=False):
        self._lock = threading.Lock()
        self.disabled = disabled
        self._all = []           # tất cả proxy (string gốc)
        self._alive = []         # proxy chưa bị đánh dấu dead
        self._dead = set()       # proxy đã die
        self._assigned = {}      # email -> proxy string
        self._reverse = {}       # proxy string -> email (để đảm bảo ko trùng)
        self._cooldown = {}      # proxy string -> timestamp hết hạn cooling (429 tạm thời)
        self.PROXY_COOL_SEC = 60 # proxy bị 429 không được gán lại cho TK khác trong 60s
        if proxy_lines:
            self.load(proxy_lines)

    def load(self, proxy_lines):
        """Load danh sách proxy từ list string (mỗi phần tử 1 proxy). Tự động lọc bỏ các dòng proxy lỗi, cắt cụt (vd '97:...')."""
        with self._lock:
            valid_list = []
            for p in proxy_lines:
                s = str(p).strip()
                if not s or s.startswith("#") or s.startswith("0.0.0."):
                    continue
                # Bóc tách host để kiểm tra tính hợp lệ
                test_str = s.split("#")[0].strip()
                if test_str.startswith("http://") or test_str.startswith("https://") or test_str.startswith("socks"):
                    test_str = test_str.split("://", 1)[1]
                if "@" in test_str:
                    test_str = test_str.split("@", 1)[1]
                host_candidate = test_str.split(":")[0].strip("[]")
                # Host hợp lệ bắt buộc phải có dấu chấm hoặc dấu hai chấm, độ dài >= 4 và không phải là số nguyên cụt (như '97')
                if ("." in host_candidate or ":" in host_candidate) and not host_candidate.isdigit() and len(host_candidate) >= 4:
                    valid_list.append(s)
            self._all = valid_list
            # Giữ lại assigned cũ nếu proxy vẫn trong danh sách mới
            new_set = set(self._all)
            old_assigned = dict(self._assigned)
            self._assigned.clear(); self._reverse.clear()
            for email, px in old_assigned.items():
                if px in new_set:
                    self._assigned[email] = px
                    self._reverse[px] = email
            self._dead = {p for p in self._dead if p in new_set}
            self._alive = [p for p in self._all if p not in self._dead]


    @staticmethod
    def _to_dict(proxy_str):
        """Chuyển proxy string thành dict cho curl_cffi: {"http": ..., "https": ...}
        Hỗ trợ:
        - IPv4: ip:port | ip:port:user:pass | ip:port:userpass
        - IPv6: [ipv6]:port | [ipv6]:port:user:pass
        - URL:  http://user:pass@ip:port | http://user:pass@[ipv6]:port | socks5://...
        """
        if not proxy_str:
            return None
        s = proxy_str.strip()
        # Strip hash fragment (dùng cho WARP copies: socks5://127.0.0.1:40000#0)
        if '#' in s and (s.startswith("socks") or s.startswith("http")):
            s = s.split('#')[0]
        if s.startswith("http://") or s.startswith("https://") or s.startswith("socks"):
            url = s
        elif s.startswith("["):
            # IPv6: [2001:db8::1]:port hoặc [2001:db8::1]:port:user:pass
            bracket_end = s.index("]")
            ipv6 = s[1:bracket_end]  # phần IP không có ngoặc
            rest = s[bracket_end+1:]  # phần sau "]"
            rest_parts = rest.lstrip(":").split(":")
            if len(rest_parts) >= 3:  # port:user:pass
                port, user, passwd = rest_parts[0], rest_parts[1], rest_parts[2]
                url = f"http://{user}:{passwd}@[{ipv6}]:{port}"
            elif len(rest_parts) >= 1:  # chỉ port
                port = rest_parts[0]
                url = f"http://[{ipv6}]:{port}"
            else:
                url = f"http://[{ipv6}]"
        else:
            parts = s.split(":")
            if len(parts) >= 4:  # ip:port:user:pass (pass có thể chứa ":")
                ip, port, user = parts[0], parts[1], parts[2]
                passwd = ":".join(parts[3:])  # ghép lại phần pass (phòng pass chứa ":")
                url = f"http://{user}:{passwd}@{ip}:{port}"
            elif len(parts) == 3:  # ip:port:userpass (1 chuỗi auth dùng cho cả user lẫn pass)
                ip, port, userpass = parts[0], parts[1], parts[2]
                url = f"http://{userpass}:{userpass}@{ip}:{port}"
            elif len(parts) == 2:  # ip:port
                url = f"http://{parts[0]}:{parts[1]}"
            else:
                url = f"http://{s}"
        return {"http": url, "https": url}

    def assign(self, email):
        """Gán 1 proxy chưa ai dùng cho email. Trả proxy string hoặc None."""
        with self._lock:
            now = time.time()
            # Dọn cooldown hết hạn
            self._cooldown = {p: t for p, t in self._cooldown.items() if t > now}
            # Nếu đã gán và proxy còn sống → giữ nguyên
            if email in self._assigned and self._assigned[email] not in self._dead:
                return self._assigned[email]
            # Tìm proxy chưa ai dùng + chưa dead + chưa cooling
            for p in self._alive:
                if p not in self._reverse and p not in self._cooldown:
                    self._assigned[email] = p
                    self._reverse[p] = email
                    return p
            # Fallback: nếu tất cả đều cooling, bỏ qua cooldown
            for p in self._alive:
                if p not in self._reverse:
                    self._assigned[email] = p
                    self._reverse[p] = email
                    return p
            return None  # hết proxy

    def release(self, email):
        """Trả proxy về pool (khi account nghỉ)."""
        with self._lock:
            px = self._assigned.pop(email, None)
            if px:
                self._reverse.pop(px, None)

    def mark_dead(self, email):
        """Đánh dấu proxy hiện tại của email là dead, tự gán proxy mới.
        Trả proxy mới hoặc None."""
        with self._lock:
            old = self._assigned.pop(email, None)
            if old:
                self._reverse.pop(old, None)
                self._dead.add(old)
                self._alive = [p for p in self._alive if p != old]
            # Gán proxy mới
            for p in self._alive:
                if p not in self._reverse:
                    self._assigned[email] = p
                    self._reverse[p] = email
                    return p
            return None

    def rotate(self, email):
        """Đổi proxy cho email — trả proxy cũ về pool (với cooling), gán proxy MỚI KHÁC.
        Dùng khi proxy hiện tại bị rate-limit (429) tạm thời, KHÔNG mark dead.
        Trả (new_proxy_str, old_proxy_str) hoặc (None, old) nếu không có proxy khác."""
        with self._lock:
            now = time.time()
            self._cooldown = {p: t for p, t in self._cooldown.items() if t > now}
            old = self._assigned.get(email)
            # Đưa proxy cũ vào cooldown để TK khác không nhận lại ngay
            if old:
                self._cooldown[old] = now + self.PROXY_COOL_SEC
            # Tìm proxy khác: chưa ai dùng + khác proxy cũ + chưa cooling
            for p in self._alive:
                if p not in self._reverse and p != old and p not in self._cooldown:
                    if old:
                        self._reverse.pop(old, None)
                    self._assigned[email] = p
                    self._reverse[p] = email
                    return p, old
            # Fallback: bỏ qua cooldown nếu không còn proxy nào
            for p in self._alive:
                if p not in self._reverse and p != old:
                    if old:
                        self._reverse.pop(old, None)
                    self._assigned[email] = p
                    self._reverse[p] = email
                    return p, old
            # Không có proxy khác → giữ nguyên
            return None, old

    def get_dict(self, email):
        """Trả proxy dict cho curl_cffi {"http": ..., "https": ...} hoặc None."""
        with self._lock:
            px = self._assigned.get(email)
        return self._to_dict(px) if px else None

    def get_str(self, email):
        """Trả proxy string đang gán cho email."""
        with self._lock:
            return self._assigned.get(email)

    def stats(self):
        """Trả dict thống kê."""
        with self._lock:
            return {"total": len(self._all), "alive": len(self._alive),
                    "dead": len(self._dead), "assigned": len(self._assigned)}

    def has_proxies(self):
        """Có proxy nào trong pool không."""
        if getattr(self, "disabled", False):
            return False
        with self._lock:
            return len(self._all) > 0


class AccountState:
    """1 tài khoản trong pool + trạng thái runtime (auth, cooldown, cache ảnh). Nhiều worker dùng chung."""
    def __init__(self, acc, submit_max=SUBMIT_MAX):
        self.acc = acc
        self.email = acc.get("email") or acc.get("id") or "?"
        self.cookie = acc.get("cookie") or ""
        self.bearer = None
        self.project = None
        self.ts = 0.0             # thời điểm lấy bearer (để biết khi nào refresh)
        self.resume_at = 0.0      # nghỉ tới thời điểm này (cooldown khi throttle)
        self.rest_reason = ""     # "credit"/"quota" (cạn) | "throttle" | "auth" | "" (đang chạy)
        self.busy = 0             # số worker đang tạo video trên account này (⚡ Đang tạo)
        self._last_thr_log = 0.0  # lần cuối ghi log throttle (giới hạn 1 dòng / 30s / account)
        self.wins = 0
        self.fails = 0
        self.refcache = {}        # ref image path -> media_id (khỏi upload lại khi retry)
        self.lock = threading.Lock()   # serialize refresh-auth + refcache (KHÔNG serialize submit!)
        self.blk = threading.Lock()    # bảo vệ busy counter
        self.i2v_blocked = False           # True nếu account bị cấm upload ảnh (403) → chỉ chạy T2V
        self.img_quota_exhausted = False    # True nếu account hết quota generate_image → skip Phase 1, dùng Pillow fallback
        self.proxy = None                  # dict {"http": ..., "https": ...} cho curl_cffi, gán bởi ProxyPool
        self.upload_throttle_streak = 0    # số lần upload 429 liên tiếp → tăng thời gian nghỉ
        self.submit_throttle_streak = 0    # số lần submit 429 liên tiếp → nghỉ 30s-150s (Quy tắc 2)
        # --- Circuit Breaker (Lớp 1: Ngắt mạch tài khoản khi cookie chết) ---
        self.auth_fail_streak = 0          # số lần auth thất bại liên tiếp
        self._circuit_broken = False       # True khi bị ngắt mạch
        # --- Proxy health tracking ---
        self.proxy_fail_streak = 0         # số lần proxy fail liên tiếp (DNS/connection)
        # --- Upload Rate Limit & Luồng Upload riêng của từng tài khoản ---
        self.upload_threads = int(acc.get("upload_threads", 4)) # Mặc định 4 luồng/TK
        self.upload_inflight = 0
        self._upload_gate = threading.Condition()
        self.last_upload_ts = 0.0          # thời điểm upload gần nhất của tài khoản này
        self.upload_lock = threading.Lock() # khóa giãn cách 4s giữa các lần upload của cùng 1 tài khoản (Rule #2)
        # --- Submit Rate Limit & Lock per account (Rule #2: Khóa giãn cách 4s chống 429) ---
        self.submit_lock = threading.Lock()
        self.last_submit_ts = 0.0
        # --- Tạo & Tốc độ = upload_threads + 3 (Min 2, Max 20) ---
        calc_rate = max(2, min(20, self.upload_threads + 3))
        self.max_busy = calc_rate
        self._submit_max = float(calc_rate)
        self.submit_limit = float(calc_rate)
        self.inflight = 0                  # số submit đang bay
        self._ok_streak = 0                # số submit OK liên tiếp (để tăng dần)
        self._gate = threading.Condition()
        # --- Khởi động mềm (Warm-up chống sốc tải 429 lúc bắt đầu) ---
        self.is_warmed_up = False if self.wins == 0 else True

    def get_current_max_busy(self):
        """Khởi động mềm (Warm-up): TK mới chỉ chạy 1-2 video thăm dò để làm ấm phiên.
        Khi có 1 video thành công (wins >= 1) -> tự động mở toàn bộ max_busy."""
        if not self.is_warmed_up and self.wins == 0:
            return min(2, self.max_busy)
        self.is_warmed_up = True
        return self.max_busy

    def busy_inc(self):
        with self.blk: self.busy += 1

    def busy_dec(self):
        with self.blk: self.busy = max(0, self.busy - 1)

    def wait_upload_spacing(self, min_interval=4.0):
        """Bắt buộc mỗi lần upload của CÙNG 1 tài khoản phải cách nhau ít nhất min_interval (4s) theo Rule #2."""
        with self.upload_lock:
            elapsed = time.time() - self.last_upload_ts
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed + random.uniform(0.1, 0.4))
            self.last_upload_ts = time.time()

    def wait_submit_spacing(self, min_interval=4.0, max_interval=6.0):
        """Bắt buộc mỗi lệnh submit video của CÙNG 1 tài khoản phải cách nhau ngẫu nhiên từ 4-6 giây theo Rule #2."""
        with self.submit_lock:
            target_wait = random.uniform(min_interval, max_interval)
            elapsed = time.time() - self.last_submit_ts
            if elapsed < target_wait:
                time.sleep(target_wait - elapsed)
            self.last_submit_ts = time.time()

    def submit_guard(self, min_spacing=4.0, max_spacing=6.0):
        """Context manager giữ khóa độc quyền submit của CÙNG 1 tài khoản trong suốt quá trình gửi và đảm bảo giãn cách 4-6s."""
        import contextlib
        @contextlib.contextmanager
        def _cm():
            with self.submit_lock:
                target_wait = random.uniform(min_spacing, max_spacing)
                elapsed = time.time() - self.last_submit_ts
                if elapsed < target_wait:
                    time.sleep(target_wait - elapsed)
                try:
                    yield
                finally:
                    self.last_submit_ts = time.time()
        return _cm()

    def acquire_submit(self, stop_check):
        with self._gate:
            limit = 4.0 if self.upload_throttle_streak > 0 else self.submit_limit
            while self.inflight >= int(limit):
                if stop_check():
                    return False
                self._gate.wait(0.5)
            self.inflight += 1
            return True

    def release_submit(self):
        with self._gate:
            self.inflight = max(0, self.inflight - 1)
            self._gate.notify()

    def on_submit_ok(self):
        """Submit trót lọt -> tăng dần giới hạn khi đủ chuỗi OK."""
        with self._gate:
            self.is_warmed_up = True
            self.submit_throttle_streak = 0
            self._ok_streak += 1
            if self._ok_streak >= SUBMIT_UP_AFTER and self.submit_limit < self._submit_max:
                self.submit_limit = min(self._submit_max, self.submit_limit + 1)
                self._ok_streak = 0
                self._gate.notify_all()

    def on_throttle(self):
        """Bị throttle -> giảm giới hạn + cho TK nghỉ 30s-150s theo Rule #2."""
        with self._gate:
            self._ok_streak = 0
            self.submit_limit = max(SUBMIT_MIN, self.submit_limit * SUBMIT_DOWN)
            self.submit_throttle_streak += 1
            n = self.submit_throttle_streak
            secs = min(30.0 * (1.5 ** (n - 1)), 150.0)
            self.rest(secs, "submit_throttle")

    def should_log_throttle(self):
        """True nếu nên ghi 1 dòng log throttle (giới hạn 1 dòng / 30s / account) — tránh ngập log."""
        now = time.time()
        if now - self._last_thr_log > 30:
            self._last_thr_log = now
            return True
        return False

    def rest_remaining(self):
        return max(0.0, self.resume_at - time.time())

    def rest(self, seconds, reason=""):
        self.resume_at = time.time() + max(0, seconds)
        self.rest_reason = reason

    def on_upload_throttle(self):
        """Upload bị 429 → tăng streak, nghỉ ngắn (15-90s).
        Upload 429 thường do IP → đã xoay proxy → chỉ cần nghỉ ngắn.
        Trả số giây nghỉ."""
        self.upload_throttle_streak += 1
        n = self.upload_throttle_streak
        secs = min(15.0 * (1.5 ** (n - 1)), 90.0)  # 15, 22, 34, 51, 76, 90 (max 90s)
        self.rest(secs, "throttle")
        return secs

    def on_upload_ok(self):
        """Upload thành công → reset streak."""
        self.upload_throttle_streak = 0

    def acquire_upload(self, stop_check=lambda: False):
        """Giới hạn số luồng upload đồng thời của riêng tài khoản này."""
        with self._upload_gate:
            while self.upload_inflight >= self.upload_threads:
                if stop_check():
                    return False
                self._upload_gate.wait(0.5)
            self.upload_inflight += 1
            return True

    def release_upload(self):
        """Nhả luồng upload của tài khoản này."""
        with self._upload_gate:
            self.upload_inflight = max(0, self.upload_inflight - 1)
            self._upload_gate.notify_all()

    def set_upload_threads(self, val):
        """Thay đổi số luồng upload trong thời gian thực (real-time) mà không cần restart.
        Tạo và Tốc độ = số luồng upload + 3 (Min 2, Max 20)."""
        with self._upload_gate:
            self.upload_threads = max(2, min(20, int(val)))
            self.acc["upload_threads"] = self.upload_threads
            calc_rate = max(2, min(20, self.upload_threads + 3))
            self.max_busy = calc_rate
            with self._gate:
                self._submit_max = float(calc_rate)
                self.submit_limit = float(calc_rate)
                self._gate.notify_all()
            self._upload_gate.notify_all()

    def clear_rest(self):
        self.resume_at = 0.0
        self.rest_reason = ""

    def auto_recover_cookie(self):
        """Khi cookie bị chết, tự động gọi DrissionPage reopen_profile_cookie / login_get_cookie để lấy cookie mới 100%."""
        if L is None:
            return None
        email = self.email or self.acc.get("email") or self.acc.get("id")
        if not email or email == "?":
            return None
            
        now = time.time()
        # Chống vòng lặp bật/tắt Chrome: Mỗi tài khoản chỉ thử tự động khôi phục tối đa 1 lần mỗi 30 phút (1800s)
        if now - getattr(self, "_last_recover_time", 0.0) < 1800:
            return None
        self._last_recover_time = now

        profile_dir = os.path.join(HERE, "_profiles", str(email).replace("@", "_"))
        fresh_ck = None
        
        # 1. Thử mở lại Chrome profile cũ (rất nhanh, 3-5 giây, không cần gõ pass)
        if os.path.exists(profile_dir):
            try:
                fresh_ck = L.reopen_profile_cookie(profile_dir, timeout=30, poll=2)
            except Exception:
                fresh_ck = None
                
        # 2. Nếu profile cũ không thành công, thử dùng password/2FA nếu có trong acc
        if not fresh_ck and self.acc.get("password"):
            try:
                fresh_ck = L.login_get_cookie(
                    self.acc["email"], self.acc["password"], self.acc.get("totp", ""),
                    profile_dir=profile_dir
                )
            except Exception:
                fresh_ck = None
                
        if fresh_ck:
            res = E.bearer_from_cookie(fresh_ck, proxy=self.proxy)
            b = res[0] if isinstance(res, tuple) else None
            if b:
                self.cookie = fresh_ck
                self.acc["cookie"] = fresh_ck
                self.acc["status"] = "ok"
                self.reset_circuit_breaker()
                self.clear_rest()
                try:
                    all_accs = load_accs()
                    for target in all_accs:
                        if (target.get("email") or target.get("id")) == email:
                            target["cookie"] = fresh_ck
                            target["status"] = "ok"
                            break
                    save_accs(all_accs)
                except Exception:
                    pass
                return b
        return None

    def ensure_auth(self, force=False):
        """Bảo đảm bearer còn hạn (refresh TỪ COOKIE, không mở trình duyệt). Trả True nếu có bearer+project."""
        with self.lock:
            if not force and self.bearer and (time.time() - self.ts < BEARER_TTL):
                return True
            res = E.bearer_from_cookie(self.cookie, proxy=self.proxy)
            if isinstance(res, tuple) and len(res) == 3:
                b, em, new_cookie = res
                if new_cookie and new_cookie != self.cookie:
                    self.cookie = new_cookie
                    self.acc["cookie"] = new_cookie
            else:
                b, em = res[0], res[1] if isinstance(res, tuple) else (None, None)
            
            if not b:
                # Cookie hết hạn -> Tăng streak lỗi auth
                self.auth_fail_streak += 1
                if self.auth_fail_streak >= 2 and not self.is_circuit_broken():
                    self.trip_circuit_breaker()
                return False
            # Auth thành công → luôn reset streak (Rule 9.1)
            self.auth_fail_streak = 0
            self.bearer = b
            self.ts = time.time()
            if em:
                self.email = em
            if not self.project:
                self.project = E.get_project(self.cookie, proxy=self.proxy)
            return bool(self.project)

    # --- Circuit Breaker methods (Lớp 1) ---
    def trip_circuit_breaker(self):
        """Ngắt mạch tài khoản khi dính 2+ lỗi auth liên tiếp."""
        self._circuit_broken = True
        self.rest(60, "circuit_breaker")  # Tạm nghỉ 60s chờ Instant Health Check cứu

    def reset_circuit_breaker(self):
        """Reset circuit breaker khi cookie được làm mới thành công."""
        self.auth_fail_streak = 0
        self._circuit_broken = False

    def is_circuit_broken(self):
        return self._circuit_broken


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        # ── Đặt Explicit AppUserModelID trên Windows để thanh Taskbar hiện đúng Icon riêng thay vì icon Python ──
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('thinaptm.googleflow.app.1.0')
        except Exception:
            pass

        brand, _lp = _find_brand()
        self.title(f"{brand} ({APP_VERSION}) — Tạo Video Google Flow")

        # ── Đặt Icon ứng dụng cho Cửa sổ & Taskbar (dùng logo.ico / logo.png) ──
        _ico_file = os.path.join(HERE, "logo.ico")
        _png_file = os.path.join(HERE, "logo.png")
        if not os.path.isfile(_ico_file) and os.path.isfile(_png_file):
            try:
                from PIL import Image as _PILImg
                _im = _PILImg.open(_png_file)
                _im.save(_ico_file, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
            except Exception:
                pass
        if os.path.isfile(_ico_file):
            try:
                self.iconbitmap(_ico_file)
            except Exception:
                try:
                    self.wm_iconbitmap(_ico_file)
                except Exception:
                    pass
        self.geometry("1280x780"); self.minsize(1100, 700); self.configure(fg_color=BG)
        self.accounts = load_accs()
        self.settings = load_settings()
        self.jobs = self.settings.get("jobs", [])           # {type, prompt, ref, aspect, model, out, status}
        # Khi khởi động lại, job nào đang chạy dở (bị ngắt) -> đặt lại "chờ" để chạy lại
        for j in self.jobs:
            if j.get("status") == "đang":
                j["status"] = "chờ"
        # TỰ DỌN hàng đợi cũ khi mở app: bỏ job ĐÃ CÓ VIDEO (out tồn tại) hoặc THIẾU ẢNH GỐC
        # (ổ rời rút / file bị xóa/di chuyển) -> không còn dữ liệu cũ rác trỏ sai chỗ.
        self._startup_clean_msg = ""
        if self.jobs:
            keep = []; n_done = n_miss = 0
            for j in self.jobs:
                o = j.get("out")
                if o and os.path.exists(o):
                    n_done += 1; continue
                r = j.get("ref")
                if j.get("type") == "i2v" and r and not os.path.exists(r):
                    n_miss += 1; continue
                keep.append(j)
            if n_done or n_miss:
                self.jobs = keep
                save_settings({**self.settings, "jobs": self.jobs})   # lưu ngay để lần sau sạch
                self._startup_clean_msg = f"🧹 Tự dọn hàng đợi: bỏ {n_done} job đã có video, {n_miss} job thiếu ảnh gốc."
        self.image_paths = self.settings.get("image_paths", [])
        self.loaded_prompts = self.settings.get("custom_prompts", [])
        self._stop = False; self._running = False; self._shopee_running = False
        self.check_vars = []  # BooleanVar cho mỗi job trong hàng đợi
        self._pool_states = []  # AccountState[] của phiên chạy hiện tại (cho panel trạng thái pool)
        self._run_t0 = 0.0; self._eta_jobs = []; self._run_done0 = 0   # để tính tốc độ + ETA
        # Gemini & Groq: phân phối key xoay vòng (Round-Robin) đều cho tất cả các luồng
        self.gemini_keys = self.settings.get("gemini_keys", [])
        self._gemini_bad = set()       # key sai/hết quyền -> loại
        self._gemini_lock = threading.Lock()
        self._gemini_active = []       # danh sách key dùng cho phiên chạy hiện tại
        self._gemini_key_rr_idx = 0
        self._groq_key_rr_idx = 0
        self._ai_key_lock = threading.Lock()
        # Cookie health check: tự kiểm tra + auto re-login
        self._health_check_enabled = self.settings.get("health_check_enabled", False)
        self._health_check_interval = self.settings.get("health_check_interval", 30)  # phút
        self._health_check_timer = None
        self._health_checking = False  # đang chạy health check
        self._hc_attempted_accs = set()  # Các tài khoản đã thử bật Chrome auto health check 1 lần
        # Telegram report
        self._tg_token_saved = self.settings.get("tg_token", "")
        self._tg_chatid_saved = self.settings.get("tg_chatid", "")
        self._tg_enabled_saved = self.settings.get("tg_enabled", False)
        # Proxy pool
        self.disable_proxy = ctk.BooleanVar(value=self.settings.get("disable_proxy", False))
        self.proxy_pool = ProxyPool(self.settings.get("proxy_list", []), disabled=self.disable_proxy.get())
        # Auto HomeProxy
        self._auto_homeproxy = ctk.BooleanVar(value=self.settings.get("auto_homeproxy", False))
        self._homeproxy_token = ctk.StringVar(value=self.settings.get("homeproxy_token", ""))
        # Cloudflare WARP (1.1.1.1)
        self._warp_enabled = ctk.BooleanVar(value=self.settings.get("warp_enabled", False))
        self._warp_port = ctk.StringVar(value=str(self.settings.get("warp_port", 40000)))

        # Khởi tạo file log.txt và xóa trắng dữ liệu cũ
        self.log_path = os.path.join(HERE, "log.txt")
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write(f"--- BẮT ĐẦU PHẦN MỀM ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---\n")
        except Exception as e:
            print(f"Không thể khởi tạo log.txt: {e}")

        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        E.ERROR_LOG_FUNC = self._log
        E.ON_PROXY_ERROR_CALLBACK = self._on_global_proxy_error

        # ----- SIDEBAR -----
        side = ctk.CTkFrame(self, width=210, corner_radius=0, fg_color="#ffffff"); side.pack(side="left", fill="y")
        side.pack_propagate(False)
        ctk.CTkLabel(side, text=brand, font=("", 20, "bold"), text_color=AC).pack(pady=(22, 2), padx=18, anchor="w")
        ctk.CTkLabel(side, text=f"Tạo video Google Flow  •  {APP_VERSION}", font=("", 10), text_color=T2).pack(padx=18, anchor="w", pady=(0, 8))
        if _lp:
            try:
                from PIL import Image
                _im = Image.open(_lp); _im.thumbnail((160, 160))
                self._logo = ctk.CTkImage(light_image=_im, size=_im.size)
                ctk.CTkLabel(side, image=self._logo, text="").pack(pady=(4, 14))
            except Exception:
                pass
        else:
            ctk.CTkLabel(side, text="", height=6).pack()
        self.nav = {}
        for key, txt, icon in [("acc", "Tài khoản", "👤"), ("gen", "Tạo video", "🎬"), ("queue", "Hàng đợi", "📋"), ("shopee", "Tạo Video Shopee", "🛒"), ("server_video", "Veo3 Local", "🌐"), ("shopapi_tab", "ShopAPI", "⚡")]:
            b = ctk.CTkButton(side, text=f"  {icon}  {txt}", anchor="w", height=44, corner_radius=8,
                               fg_color="transparent", text_color=T1, hover_color="#eef2fb", font=("", 14),
                               command=lambda k=key: self._show(k))
            b.pack(fill="x", padx=12, pady=3); self.nav[key] = b
        self.lbl_qcount = ctk.CTkLabel(side, text="", font=("", 12, "bold"), text_color=GR); self.lbl_qcount.pack(pady=8)

        # ----- VERSION FOOTER -----
        ctk.CTkLabel(side, text=APP_VERSION, font=("Consolas", 10, "bold"), text_color="#9AA0A6").pack(side="bottom", pady=(0, 6))

        # ----- UPDATE BADGE FRAME (Góc dưới cùng bên trái Sidebar - Luôn hiển thị) -----
        self.update_card = ctk.CTkFrame(side, fg_color="#E8F5E9", corner_radius=10, border_color="#81C784", border_width=1)
        self.update_card.pack(side="bottom", fill="x", padx=10, pady=8)

        self.lbl_update_title = ctk.CTkLabel(self.update_card, text="✅ ĐÃ Ở BẢN MỚI NHẤT", font=("", 11, "bold"), text_color="#2E7D32")
        self.lbl_update_title.pack(pady=(8, 2), padx=6)
        self.lbl_update_sub = ctk.CTkLabel(self.update_card, text=f"Phiên bản: {APP_VERSION}", font=("", 10), text_color="#388E3C")
        self.lbl_update_sub.pack(pady=(0, 6), padx=6)

        self.btn_do_update = ctk.CTkButton(
            self.update_card,
            text="🔄 Kiểm tra lại",
            fg_color="#4CAF50",
            hover_color="#388E3C",
            text_color="#ffffff",
            height=28,
            font=("", 11, "bold"),
            command=self._start_update_checker
        )
        self.btn_do_update.pack(fill="x", padx=8, pady=(0, 8))

        # ----- CONTENT -----
        self.content = ctk.CTkFrame(self, fg_color=BG); self.content.pack(side="left", fill="both", expand=True)
        self.frames = {}
        self._build_acc(); self._build_gen(); self._build_queue(); self._build_shopee(); self._build_server_video(); self._build_shopapi_tab()
        self._show("acc")
        self.after(500, self._update_pool)        # panel trạng thái pool video (live)
        self.after(600, self._sp_update_pool)     # panel trạng thái pool Shopee (live)
        self.after(700, self._sv_update_pool)     # panel trạng thái pool Server Video (live)
        if self._startup_clean_msg:
            self._log(self._startup_clean_msg)
        self._start_telegram_polling()
        # Khởi động cơ chế tự động dọn dẹp định kỳ mỗi 30 phút ngầm (cũng tự dọn lần đầu ngay khi mở)
        self._schedule_periodic_cleanup()
        # Khởi động kiểm tra bản cập nhật mới trên GitHub ngay khi vừa vào ứng dụng
        self.after(500, self._start_update_checker)

    def _show(self, key):
        self._current_tab = key  # Track tab hiện tại cho tối ưu hiệu năng
        for f in self.frames.values(): f.pack_forget()
        self.frames[key].pack(fill="both", expand=True, padx=18, pady=16)
        for k, b in self.nav.items():
            b.configure(fg_color=("#e8f0fe" if k == key else "transparent"), text_color=(AC if k == key else T1))
        if key == "gen":
            self.after(0, self._update_pool)
        elif key == "shopee":
            self.after(0, self._sp_update_pool)
        elif key == "server_video":
            self.after(0, self._sv_update_pool)

    # ============ TAB TÀI KHOẢN ============
    def _build_acc(self):
        f = ctk.CTkFrame(self.content, fg_color=BG); self.frames["acc"] = f
        card = ctk.CTkFrame(f, fg_color="#0f1b3d", corner_radius=12); card.pack(fill="x")
        ctk.CTkLabel(card, text="Google Flow Accounts", font=("", 17, "bold"), text_color="#fff").pack(side="left", padx=20, pady=16)
        self.lbl_live = ctk.CTkLabel(card, text="0 tài khoản", font=("", 13), text_color="#7ee0c0"); self.lbl_live.pack(side="right", padx=20)
        bar = ctk.CTkFrame(f, fg_color="transparent"); bar.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(bar, text="➕ Import (email|pass|2fa)", command=self._import_accs, fg_color=AC, hover_color=AC2, height=32).pack(side="left", padx=(0, 4))
        ctk.CTkButton(bar, text="🖐 Nhập thủ công", command=self._manual_login, fg_color="#3949AB", hover_color="#283593", height=32).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="✔ Check", command=self._check_accs, fg_color=GR, hover_color="#00695C", height=32, width=80).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="🔑 Auto login", command=self._auto_login, fg_color="#00897B", hover_color="#00695C", height=32).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="🗑 Xóa tất cả", command=self._clear_accs, fg_color="#9aa0a6", hover_color="#5f6368", height=32, width=90).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="🧹 Dọn Chrome Rác", command=self._clean_orphaned_chrome_manually, fg_color="#E57373", hover_color="#EF5350", height=32).pack(side="left", padx=4)
        # Health check (cùng hàng, bên phải)
        ctk.CTkButton(bar, text="▶ Check ngay", command=self._run_health_check_now,
                      fg_color="#5C6BC0", hover_color="#3949AB", height=28, width=90,
                      font=("", 11)).pack(side="right", padx=(4, 0))
        self._hc_status_lbl = ctk.CTkLabel(bar, text="", font=("", 10), text_color=T2)
        self._hc_status_lbl.pack(side="right", padx=4)
        ctk.CTkLabel(bar, text="phút", font=("", 10), text_color=T2).pack(side="right")
        self._hc_interval_var = ctk.StringVar(value=str(self._health_check_interval))
        self._hc_interval_entry = ctk.CTkEntry(bar, width=40, height=26, textvariable=self._hc_interval_var)
        self._hc_interval_entry.pack(side="right", padx=2)
        ctk.CTkLabel(bar, text="Mỗi", font=("", 10), text_color=T2).pack(side="right", padx=2)
        self._hc_var = ctk.BooleanVar(value=self._health_check_enabled)
        self._hc_switch = ctk.CTkSwitch(bar, text="", variable=self._hc_var,
                                         command=self._toggle_health_check, width=40,
                                         progress_color=GR, fg_color="#bdbdbd")
        self._hc_switch.pack(side="right", padx=2)
        ctk.CTkLabel(bar, text="🩺", font=("", 12)).pack(side="right", padx=(4, 0))
        if self._health_check_enabled:
            self._schedule_health_check()
        # Header row + Account scroll + Proxy: 2 cột ngang hàng
        main_row = ctk.CTkFrame(f, fg_color="transparent"); main_row.pack(fill="both", expand=True, pady=(4, 0))
        main_row.columnconfigure(0, weight=7); main_row.columnconfigure(1, weight=3)

        # --- CỘT TRÁI: Account List ---
        acc_col = ctk.CTkFrame(main_row, fg_color="transparent")
        acc_col.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        hdr = ctk.CTkFrame(acc_col, fg_color="#e8eaf6", corner_radius=6, height=32); hdr.pack(fill="x"); hdr.pack_propagate(False)
        for txt, w in [("Dùng", 40), ("#", 25), ("Email", 180), ("Vai trò", 65), ("Trạng thái", 95), ("Hành động", 70), ("Cookie", 50), ("Pass", 40), ("2FA", 40)]:
            ctk.CTkLabel(hdr, text=txt, font=("Consolas", 11, "bold"), text_color=T1, width=w, anchor="w").pack(side="left", padx=(6, 0))
        self.acc_scroll = ctk.CTkScrollableFrame(acc_col, fg_color=CARD, corner_radius=8)
        self.acc_scroll.pack(fill="both", expand=True, pady=(2, 0))

        # --- CỘT PHẢI: Proxy Pool ---
        pxcard = ctk.CTkFrame(main_row, fg_color=CARD, corner_radius=10)
        pxcard.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        ctk.CTkLabel(pxcard, text="🌐 Proxy Pool",
                     font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(8, 2))
        ctk.CTkLabel(pxcard, text="Mỗi dòng 1 proxy (ip:port hoặc ip:port:user:pass)",
                     font=("", 10), text_color=T2).pack(anchor="w", padx=12)
        px_info = ctk.CTkFrame(pxcard, fg_color="transparent"); px_info.pack(fill="x", padx=12, pady=(2, 0))
        self.lbl_proxy_stats = ctk.CTkLabel(px_info, text="", font=("", 11), text_color=T2)
        self.lbl_proxy_stats.pack(side="left")
        self.chk_disable_proxy = ctk.CTkCheckBox(px_info, text="❌ Tắt", variable=self.disable_proxy, font=("", 11), checkbox_width=16, checkbox_height=16, command=self._on_disable_proxy_changed)
        self.chk_disable_proxy.pack(side="right")
        self.txt_proxy = ctk.CTkTextbox(pxcard, font=("Consolas", 11))
        self.txt_proxy.pack(fill="both", padx=12, pady=(2, 10), expand=True)
        saved_proxies = self.settings.get("proxy_list", [])
        if saved_proxies:
            self.txt_proxy.insert("1.0", "\n".join(saved_proxies))
        self._update_proxy_stats()
        # --- Auto HomeProxy ---
        hp_frame = ctk.CTkFrame(pxcard, fg_color="transparent")
        hp_frame.pack(fill="x", padx=12, pady=(4, 0))
        self.chk_auto_hp = ctk.CTkCheckBox(hp_frame, text="\U0001f3e0 Auto HomeProxy",
            variable=self._auto_homeproxy, font=("", 11), checkbox_width=16, checkbox_height=16)
        self.chk_auto_hp.pack(side="left")
        ctk.CTkButton(hp_frame, text="\U0001f504 T\u1ea3i Proxy", command=self._fetch_homeproxy_manual,
            fg_color="#5C6BC0", hover_color="#3F51B5", height=26, width=90, font=("", 10)).pack(side="right")
        self.lbl_hp_status = ctk.CTkLabel(hp_frame, text="", font=("", 10), text_color="#9e9e9e")
        self.lbl_hp_status.pack(side="right", padx=(0, 6))
        hp_token_row = ctk.CTkFrame(pxcard, fg_color="transparent")
        hp_token_row.pack(fill="x", padx=12, pady=(2, 4))
        ctk.CTkLabel(hp_token_row, text="Token:", font=("Consolas", 10), text_color="#9e9e9e").pack(side="left")
        self.ent_hp_token = ctk.CTkEntry(hp_token_row, textvariable=self._homeproxy_token,
            font=("Consolas", 10), height=24, placeholder_text="homepx..._xxx")
        self.ent_hp_token.pack(side="left", fill="x", expand=True, padx=(4, 0))
        # --- Cloudflare WARP (1.1.1.1) ---
        warp_frame = ctk.CTkFrame(pxcard, fg_color="transparent")
        warp_frame.pack(fill="x", padx=12, pady=(4, 4))
        self.chk_warp = ctk.CTkCheckBox(warp_frame, text="\U0001f310 1.1.1.1 (WARP)",
            variable=self._warp_enabled, font=("", 11), checkbox_width=16, checkbox_height=16)
        self.chk_warp.pack(side="left")
        ctk.CTkLabel(warp_frame, text="Port:", font=("Consolas", 10), text_color="#9e9e9e").pack(side="left", padx=(10, 2))
        self.ent_warp_port = ctk.CTkEntry(warp_frame, textvariable=self._warp_port,
            font=("Consolas", 10), height=24, width=60, placeholder_text="40000")
        self.ent_warp_port.pack(side="left")
        ctk.CTkButton(warp_frame, text="🧪 Test", command=self._test_warp_proxy,
            fg_color="#43A047", hover_color="#2E7D32", height=24, width=60, font=("", 10)).pack(side="left", padx=(6, 0))
        self.lbl_warp_ip = ctk.CTkLabel(warp_frame, text="", font=("Consolas", 10), text_color="#9e9e9e")
        self.lbl_warp_ip.pack(side="left", padx=(6, 0))

        self.lbl_acc_prog = ctk.CTkLabel(f, text="", font=("", 12), text_color=T2); self.lbl_acc_prog.pack(anchor="w")

        # --- reCAPTCHA + Telegram: 2 cột ngang nhau ---
        rt_row = ctk.CTkFrame(f, fg_color="transparent"); rt_row.pack(fill="x", pady=(6, 0))
        rt_row.columnconfigure(0, weight=1); rt_row.columnconfigure(1, weight=1)

        # Cột trái: reCAPTCHA Mode
        rccard = ctk.CTkFrame(rt_row, fg_color=CARD, corner_radius=10)
        rccard.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        ctk.CTkLabel(rccard, text="🔒 reCAPTCHA Mode",
                     font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(8, 2))
        rc_row = ctk.CTkFrame(rccard, fg_color="transparent"); rc_row.pack(fill="x", padx=12, pady=(2, 4))
        self._recaptcha_mode = ctk.StringVar(value=self.settings.get("recaptcha_mode", "android_bypass"))
        rc_seg = ctk.CTkSegmentedButton(rc_row, values=["android_bypass", "token_farm"],
                                         variable=self._recaptcha_mode, font=("", 11),
                                         command=self._on_recaptcha_mode_change)
        rc_seg.pack(side="left", padx=(0, 6))
        self._rc_status_lbl = ctk.CTkLabel(rc_row, text="", font=("", 10), text_color=T2)
        self._rc_status_lbl.pack(side="left")
        rc_bot = ctk.CTkFrame(rccard, fg_color="transparent"); rc_bot.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(rc_bot, text="Số luồng farm:", font=("", 11), text_color=T2).pack(side="left")
        self._rc_workers = ctk.CTkEntry(rc_bot, width=50, height=28, font=("Consolas", 11))
        self._rc_workers.pack(side="left", padx=(6, 8))
        self._rc_workers.insert(0, str(self.settings.get("recaptcha_workers", 3)))
        self._on_recaptcha_mode_change(self._recaptcha_mode.get())

        # Cột phải: Telegram Report
        tgcard = ctk.CTkFrame(rt_row, fg_color=CARD, corner_radius=10)
        tgcard.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        ctk.CTkLabel(tgcard, text="📨 Telegram Report",
                     font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(8, 2))
        tg_r1 = ctk.CTkFrame(tgcard, fg_color="transparent"); tg_r1.pack(fill="x", padx=12, pady=(2, 2))
        self.tg_enabled = ctk.BooleanVar(value=self._tg_enabled_saved)
        ctk.CTkSwitch(tg_r1, text="Bật", variable=self.tg_enabled, width=60,
                      progress_color=GR, fg_color="#bdbdbd").pack(side="left", padx=(0, 8))
        ctk.CTkLabel(tg_r1, text="Token:", font=("", 11), text_color=T2).pack(side="left", padx=(0, 4))
        self.ent_tg_token = ctk.CTkEntry(tg_r1, height=28, font=("Consolas", 10))
        self.ent_tg_token.pack(side="left", fill="x", expand=True, padx=(0, 4))
        if self._tg_token_saved:
            self.ent_tg_token.insert(0, self._tg_token_saved)
        self.ent_tg_token.configure(state="disabled")
        tg_r2 = ctk.CTkFrame(tgcard, fg_color="transparent"); tg_r2.pack(fill="x", padx=12, pady=(2, 8))
        ctk.CTkLabel(tg_r2, text="Chat ID:", font=("", 11), text_color=T2).pack(side="left", padx=(0, 4))
        self.ent_tg_chatid = ctk.CTkEntry(tg_r2, width=140, height=28, font=("Consolas", 11))
        self.ent_tg_chatid.pack(side="left", padx=(0, 8))
        if self._tg_chatid_saved:
            self.ent_tg_chatid.insert(0, self._tg_chatid_saved)
        self.ent_tg_chatid.configure(state="disabled")
        self._tg_editing = False
        self._tg_edit_btn = ctk.CTkButton(tg_r2, text="✏️ Sửa", width=55, height=28,
                                           fg_color="#78909C", hover_color="#546E7A",
                                           font=("", 11), command=self._sv_toggle_tg_edit)
        self._tg_edit_btn.pack(side="left", padx=(0, 4))
        ctk.CTkButton(tg_r2, text="🔔 Test gửi", command=self._test_telegram,
                      fg_color="#5C6BC0", hover_color="#3949AB", height=28, width=90,
                      font=("", 11)).pack(side="left", padx=4)

        # --- API KEYS (Gemini | Groq) cạnh nhau ---
        api_row = ctk.CTkFrame(f, fg_color="transparent"); api_row.pack(fill="x", pady=(6, 0))
        api_row.columnconfigure(0, weight=3); api_row.columnconfigure(1, weight=2)

        gcard = ctk.CTkFrame(api_row, fg_color=CARD, corner_radius=10)
        gcard.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
        ctk.CTkLabel(gcard, text="🔑 Gemini API Keys — dùng chung tất cả tab",
                     font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(8, 2))
        ctk.CTkLabel(gcard, text="Mỗi dòng 1 key:", font=("", 10), text_color=T2).pack(anchor="w", padx=12)
        self.txt_gemini = ctk.CTkTextbox(gcard, height=100, font=("Consolas", 11))
        self.txt_gemini.pack(fill="both", padx=12, pady=(2, 10), expand=True)
        if self.gemini_keys:
            self.txt_gemini.insert("1.0", "\n".join(self.gemini_keys))

        qcard = ctk.CTkFrame(api_row, fg_color=CARD, corner_radius=10)
        qcard.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
        ctk.CTkLabel(qcard, text="🔑 Groq API Keys — dùng chung tất cả tab",
                     font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(8, 2))
        ctk.CTkLabel(qcard, text="Mỗi dòng 1 key:", font=("", 10), text_color=T2).pack(anchor="w", padx=12)
        self.txt_groq_keys = ctk.CTkTextbox(qcard, height=100, font=("Consolas", 11))
        self.txt_groq_keys.pack(fill="both", padx=12, pady=(2, 10), expand=True)
        saved_groq = self.settings.get("groq_api_key", "")
        if saved_groq:
            self.txt_groq_keys.insert("1.0", saved_groq)

        self._refresh_acc()

        # Auto-load HomeProxy on startup if enabled
        if self._auto_homeproxy.get() and self._homeproxy_token.get().strip():
            hp_tok = self._homeproxy_token.get().strip()
            self.after(1000, lambda: threading.Thread(target=self._fetch_homeproxy, args=(hp_tok,), daemon=True).start())

    def _safe_after(self, ms, func):
        """Gọi self.after an toàn từ background thread không bao giờ ném Exception."""
        try:
            self.after(ms, func)
        except Exception:
            pass

    def _on_disable_proxy_changed(self):
        """Callback khi người dùng tick chọn Không dùng Proxy."""
        self.proxy_pool.disabled = self.disable_proxy.get()
        self._update_proxy_stats()

    def _update_proxy_stats(self):
        """Cập nhật nhãn thống kê proxy."""
        try:
            if getattr(self.proxy_pool, "disabled", False):
                self.lbl_proxy_stats.configure(text="❌ Đã tắt Proxy — tài khoản sẽ dùng IP máy chủ", text_color=RD)
                return
            st = self.proxy_pool.stats()
            if st["total"] > 0:
                self.lbl_proxy_stats.configure(
                    text=f"📊 Tổng: {st['total']} | 🟢 Sống: {st['alive']} | 💀 Chết: {st['dead']} | 🔗 Đang dùng: {st['assigned']}",
                    text_color=T2)
            else:
                self.lbl_proxy_stats.configure(text="Chưa có proxy — tài khoản sẽ dùng IP máy chủ", text_color=T2)
        except Exception:
            pass

    def _test_warp_proxy(self):
        """Test WARP proxy: kết nối qua SOCKS5 và hiển thị IP."""
        self.lbl_warp_ip.configure(text="⏳ đang test...", text_color="#FFA726")
        port_s = self._warp_port.get().strip()
        def _do_test(p_str=port_s):
            port = int(p_str or 40000)
            proxy = {"http": f"socks5://127.0.0.1:{port}", "https": f"socks5://127.0.0.1:{port}"}
            try:
                import curl_cffi.requests as cffi
                r = cffi.get("https://api.ipify.org?format=json", proxies=proxy, timeout=10)
                ip = r.json().get("ip", "?")
                self._safe_after(0, lambda: self.lbl_warp_ip.configure(text=f"✅ IP: {ip}", text_color="#43A047"))
            except Exception as e:
                err = str(e)[:40]
                self._safe_after(0, lambda: self.lbl_warp_ip.configure(text=f"❌ {err}", text_color="#E53935"))
        threading.Thread(target=_do_test, daemon=True).start()

    def _fetch_homeproxy_manual(self):
        """Nút bấm thủ công: Tải proxy từ HomeProxy API."""
        tok = self._homeproxy_token.get().strip()
        threading.Thread(target=self._fetch_homeproxy, args=(tok,), daemon=True).start()

    def _fetch_homeproxy(self, token=None):
        """Gọi HomeProxy API để lấy danh sách proxy đang chạy (Thread-safe)."""
        if token is None:
            try:
                token = self._homeproxy_token.get().strip()
            except Exception:
                token = self.settings.get("homeproxy_token", "").strip()
        if token and token.lower().startswith("bearer "):
            token = token[7:].strip()
            self._safe_after(0, lambda t=token: self._homeproxy_token.set(t))
            
        if not token:
            self._safe_after(0, lambda: self.lbl_hp_status.configure(text="❌ Chưa nhập token", text_color="#E57373"))
            self._safe_after(0, lambda: messagebox.showwarning("Lỗi HomeProxy", "Chưa nhập API Token cho HomeProxy. Vui lòng nhập token tại mục Proxy Pool."))
            return
            
        self._safe_after(0, lambda: self.lbl_hp_status.configure(text="⏳ Đang tải...", text_color="#FFB74D"))
        self._log("[HomeProxy] Đang tải proxy từ HomeProxy...")
        import requests as _rq
        import base64 as _b64
        
        def _dec(p):
            if not p: return ""
            return str(p).strip()

        def is_valid_proxy_host(h):
            if not h: return False
            h = str(h).strip()
            if len(h) < 4: return False
            if "." not in h and ":" not in h: return False
            if h.isdigit(): return False
            return True
                
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        proxy_lines = []
        
        # 1. Tìm merchant_id
        merchant_id = ""
        # Thử lấy merchant_id từ api.homeproxy.vn (ổn định hơn) trước
        for base in ["https://api.homeproxy.vn/api/v1", "https://app.homeproxy.vn/api/v2"]:
            try:
                r0 = _rq.get(f"{base}/orders?page=1&limit=1", headers=headers, timeout=10)
                if r0.status_code == 200:
                    orders_data = r0.json().get("data", [])
                    if orders_data:
                        merchant_id = str(orders_data[0].get("user", {}).get("merchant", {}).get("id", ""))
                        if merchant_id:
                            break
            except:
                pass
                
        if merchant_id:
            headers["x-merchant-id"] = merchant_id
            self._log(f"[HomeProxy] Tìm thấy merchant_id: {merchant_id}")

        # 2. Lấy danh sách proxy thực sự từ /users/proxies
        success = False
        import time as _time
        now_ms = int(_time.time() * 1000)
        
        for base in ["https://api.homeproxy.vn/api/v1", "https://app.homeproxy.vn/api/v2"]:
            try:
                r = _rq.get(f"{base}/users/proxies?page=1&limit=500", headers=headers, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    items = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []
                    for item in items:
                        status_name = item.get("status", {}).get("name", "")
                        expired_at = item.get("expiredAt", 0)
                        if status_name != "Completed":
                            continue
                        if expired_at and expired_at < now_ms:
                            continue
                            
                        px = item.get("proxy", {})
                        ip_data = px.get("ipaddress", {}) if isinstance(px.get("ipaddress"), dict) else {}
                        
                        host = ip_data.get("domain") or ip_data.get("ip") or px.get("domain") or px.get("ip") or px.get("host")
                        port = px.get("port")
                        user = px.get("username")
                        pwd = _dec(px.get("password", ""))
                        
                        if is_valid_proxy_host(host) and port:
                            try:
                                port_int = int(str(port).strip())
                                if 1 <= port_int <= 65535:
                                    line = f"{str(host).strip()}:{port_int}"
                                    if user:
                                        line += f":{str(user).strip()}:{pwd}"
                                    proxy_lines.append(line)
                            except:
                                pass
                            
                    self._log(f"[HomeProxy] Lấy thành công từ {base}/users/proxies: {len(proxy_lines)} proxy")
                    success = True
                    break
                else:
                    self._log(f"[HomeProxy] {base}/users/proxies trả về status: {r.status_code}")
            except Exception as e:
                self._log(f"[HomeProxy] Lỗi gọi {base}/users/proxies: {e}")

        # 3. Fallback lấy từ orders nếu users/proxies bị lỗi hoặc rỗng
        if not success or not proxy_lines:
            self._log("[HomeProxy] Thử fallback lấy thông tin từ danh sách đơn hàng /orders...")
            for base in ["https://api.homeproxy.vn/api/v1", "https://app.homeproxy.vn/api/v2"]:
                try:
                    r2 = _rq.get(f"{base}/orders?page=1&limit=100", headers=headers, timeout=10)
                    if r2.status_code == 200:
                        orders = r2.json().get("data", [])
                        for order in orders:
                            if order.get("status", {}).get("name") != "Completed":
                                continue
                            for prod in order.get("products", []):
                                user = prod.get("user", "")
                                pwd = _dec(prod.get("password", ""))
                                proto = prod.get("protocolType", "HTTP")
                                if user and pwd:
                                    proxy_lines.append(f"# HomeProxy order {order.get('code')} ({proto}): user={user} pass={pwd}")
                        self._log(f"[HomeProxy] Lấy thành công từ {base}/orders: {len(proxy_lines)} dòng tin nhắn proxy")
                        break
                    else:
                        self._log(f"[HomeProxy] {base}/orders trả về status: {r2.status_code}")
                except Exception as e:
                    self._log(f"[HomeProxy] Lỗi gọi {base}/orders: {e}")

        # 4. Cập nhật UI & Hiển thị cảnh báo lỗi nếu không có proxy nào hoạt động
        if proxy_lines:
            is_real = not proxy_lines[0].startswith("#")
            def _update_ui():
                if is_real:
                    self.txt_proxy.delete("1.0", "end")
                    self.txt_proxy.insert("1.0", "\n".join(proxy_lines))
                    self.proxy_pool.load(proxy_lines)
                    self._update_proxy_stats()
                    self.lbl_hp_status.configure(text=f"✅ {len(proxy_lines)} proxy", text_color="#66BB6A")
                else:
                    self.lbl_hp_status.configure(text="⚠️ Chỉ có thông tin orders", text_color="#FFB74D")
                    messagebox.showwarning("Lỗi HomeProxy", "Tải danh sách proxy thất bại:\nChỉ có thông tin tài khoản xác thực trong đơn hàng, thiếu địa chỉ IP:Port kết nối.\nVui lòng kiểm tra xem bạn đã cấu hình gói Proxy Tĩnh trong dashboard app.homeproxy.vn chưa.")
            self.after(0, _update_ui)
        else:
            def _show_err():
                self.lbl_hp_status.configure(text="⚠️ 0 proxy", text_color="#FFB74D")
                messagebox.showwarning("Lỗi HomeProxy", "Không tìm thấy bất kỳ proxy nào đang hoạt động trên tài khoản HomeProxy của bạn.\nVui lòng kiểm tra lại Token hoặc tình trạng các gói proxy.")
            self.after(0, _show_err)

    def _on_recaptcha_mode_change(self, mode):
        """Callback khi user đổi reCAPTCHA mode."""
        if mode == "token_farm":
            self._rc_status_lbl.configure(text="🐑 Token Farm sẽ khởi động khi bấm Bắt Đầu", text_color="#00897B")
        else:
            self._rc_status_lbl.configure(text="⚡ Bypass tĩnh — nhanh, không cần Chrome", text_color=T2)
            # Nếu farm đang chạy → dừng
            self._stop_recaptcha_farm()

    def _start_recaptcha_farm(self):
        """Khởi động RecaptchaFarm nếu user chọn token_farm mode."""
        if self._recaptcha_mode.get() != "token_farm":
            return
        try:
            import recaptcha_farm as RF
            num_workers = int(self._rc_workers.get().strip() or "3")
            num_workers = max(1, min(num_workers, 10))  # clamp 1-10
            farm = RF.get_farm(num_workers=num_workers, log_func=lambda m: self._log(f"[🐑] {m}"))
            if farm.start():
                E.set_recaptcha_farm(farm)
                self._rc_status_lbl.configure(text=f"🟢 Token Farm đang chạy ({num_workers} luồng)", text_color="#00897B")
            else:
                self._rc_status_lbl.configure(text="⚠️ Farm không khởi động được — dùng bypass", text_color=RD)
        except Exception as ex:
            self._log(f"[🐑] Lỗi khởi động Token Farm: {ex}")
            self._rc_status_lbl.configure(text=f"❌ Lỗi: {str(ex)[:40]}", text_color=RD)

    def _stop_recaptcha_farm(self):
        """Dừng RecaptchaFarm."""
        try:
            import recaptcha_farm as RF
            RF.stop_farm()
            E.set_recaptcha_farm(None)
        except Exception:
            pass


    def _refresh_acc(self):
        for w in self.acc_scroll.winfo_children():
            w.destroy()
        live = sum(1 for a in self.accounts if a.get("cookie") and a.get("status") == "ok")
        self.lbl_live.configure(text=f"{live}/{len(self.accounts)} dùng được")
        # Sắp xếp: Main trước, Donor sau (giữ thứ tự gốc trong cùng nhóm)
        sorted_accs = sorted(enumerate(self.accounts), key=lambda x: (0 if x[1].get("role", "main") == "main" else 1))
        for display_i, (orig_i, a) in enumerate(sorted_accs):
            if "enabled" not in a: a["enabled"] = True
            st = {"ok": "✅ Hoạt động", "dead": "❌ Chết", "new": "⏳ Chưa login"}.get(a.get("status"), "⏳ Chưa login")
            row_bg = "#ffffff" if display_i % 2 == 0 else "#f8f9fc"
            row = ctk.CTkFrame(self.acc_scroll, fg_color=row_bg, corner_radius=4, height=30)
            row.pack(fill="x", pady=1); row.pack_propagate(False)
            var = ctk.BooleanVar(value=a.get("enabled", True))
            cb = ctk.CTkCheckBox(row, text="", variable=var, width=30, checkbox_width=18, checkbox_height=18,
                                 command=lambda idx=orig_i, v=var: self._toggle_acc(idx, v))
            cb.pack(side="left", padx=(6, 0))
            ctk.CTkLabel(row, text=str(display_i + 1), font=("Consolas", 11), width=25, anchor="w", text_color=T2).pack(side="left", padx=(6, 0))
            txt_color = T1 if a.get("enabled", True) else "#bdbdbd"
            ctk.CTkLabel(row, text=(a.get('email') or a.get('id') or '?')[:28], font=("Consolas", 11), width=180, anchor="w", text_color=txt_color).pack(side="left", padx=(6, 0))
            # --- Vai trò (Main / Donor) ---
            role = a.get("role", "main")
            role_txt = "🎬 Main" if role != "donor" else "🎁 Donor"
            role_fg = AC if role != "donor" else "#E65100"
            role_hover = AC2 if role != "donor" else "#BF360C"
            ctk.CTkButton(row, text=role_txt, width=60, height=22, font=("", 10, "bold"),
                          fg_color=role_fg, hover_color=role_hover, corner_radius=4,
                          command=lambda idx=orig_i: self._toggle_role(idx)).pack(side="left", padx=(6, 0))
            st_color = {"ok": GR, "dead": RD, "new": "#F9A825"}.get(a.get("status"), "#F9A825")
            ctk.CTkLabel(row, text=st, font=("", 11), width=95, anchor="w", text_color=st_color if a.get("enabled", True) else "#bdbdbd").pack(side="left", padx=(6, 0))
            # --- Hành động (Edit / Delete) ---
            ctk.CTkButton(row, text="✏️", width=28, height=24, fg_color="#5C6BC0", hover_color="#3949AB",
                          font=("", 11), corner_radius=4,
                          command=lambda idx=orig_i: self._edit_acc(idx)).pack(side="left", padx=(6, 0))
            ctk.CTkButton(row, text="🗑", width=28, height=24, fg_color="#ef5350", hover_color="#c62828",
                          font=("", 11), corner_radius=4,
                          command=lambda idx=orig_i: self._delete_acc(idx)).pack(side="left", padx=(4, 0))
            # --- Các cột phụ (Cookie / Pass / 2FA) ---
            ctk.CTkLabel(row, text='có' if a.get('cookie') else 'không', font=("Consolas", 11), width=50, anchor="w", text_color=T2).pack(side="left", padx=(6, 0))
            has_pass = bool(a.get('password'))
            ctk.CTkLabel(row, text='có' if has_pass else '-', font=("Consolas", 11), width=40, anchor="w",
                         text_color=(GR if has_pass else "#ef5350")).pack(side="left", padx=(6, 0))
            ctk.CTkLabel(row, text='có' if a.get('totp') else '-', font=("Consolas", 11), width=40, anchor="w", text_color=T2).pack(side="left", padx=(6, 0))

        # Đồng bộ danh sách tài khoản đã chọn sang Pool của tất cả các Tab
        if hasattr(self, "pool_rows_frame"):
            self.after(0, self._update_pool)
        if hasattr(self, "_sp_pool_rows_frame"):
            self.after(0, self._sp_update_pool)
        if hasattr(self, "_sv_pool_rows_frame"):
            self.after(0, self._sv_update_pool)

    def _toggle_acc(self, idx, var):
        if idx < 0 or idx >= len(self.accounts): return
        self.accounts[idx]["enabled"] = var.get()
        save_accs(self.accounts)
        self._refresh_acc()

    def _toggle_role(self, idx):
        """Toggle vai trò tài khoản: main (←→) donor."""
        if idx < 0 or idx >= len(self.accounts): return
        a = self.accounts[idx]
        old = a.get("role", "main")
        a["role"] = "donor" if old != "donor" else "main"
        new = a["role"]
        email = a.get("email") or a.get("id") or "?"
        self._log(f"🔄 {email}: vai trò đổi từ {old} → {new}")
        save_accs(self.accounts)
        self._refresh_acc()

    def _edit_acc(self, idx):
        """Mở dialog sửa password & 2FA cho tài khoản (để auto re-login khi cookie die)."""
        if idx < 0 or idx >= len(self.accounts): return
        a = self.accounts[idx]
        email = a.get('email') or a.get('id') or '?'
        dlg = ctk.CTkToplevel(self)
        dlg.title(f"Sửa tài khoản: {email}")
        dlg.geometry("420x200"); dlg.resizable(False, False)
        dlg.grab_set()
        ctk.CTkLabel(dlg, text=f"📧 {email}", font=("", 13, "bold"), text_color=AC).pack(pady=(12, 6))
        fr_p = ctk.CTkFrame(dlg, fg_color="transparent"); fr_p.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(fr_p, text="Password:", width=80, anchor="w").pack(side="left")
        ent_pass = ctk.CTkEntry(fr_p, show="•"); ent_pass.pack(side="left", fill="x", expand=True, padx=(4, 0))
        if a.get('password'): ent_pass.insert(0, a['password'])
        fr_t = ctk.CTkFrame(dlg, fg_color="transparent"); fr_t.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(fr_t, text="2FA Secret:", width=80, anchor="w").pack(side="left")
        ent_totp = ctk.CTkEntry(fr_t); ent_totp.pack(side="left", fill="x", expand=True, padx=(4, 0))
        if a.get('totp'): ent_totp.insert(0, a['totp'])
        ctk.CTkLabel(dlg, text="💡 Cần password để auto re-login khi cookie hết hạn",
                     font=("", 10), text_color=T2).pack(pady=(2, 4))
        def save_edit():
            a['password'] = ent_pass.get().strip()
            a['totp'] = ent_totp.get().strip()
            save_accs(self.accounts)
            self._refresh_acc()
            dlg.destroy()
            self._log(f"✏️ Đã cập nhật thông tin cho {email}")
        ctk.CTkButton(dlg, text="💾 Lưu", command=save_edit, fg_color=AC, hover_color=AC2, height=34).pack(pady=(4, 12))

    def _delete_acc(self, idx):
        if idx < 0 or idx >= len(self.accounts): return
        email = self.accounts[idx].get('email') or self.accounts[idx].get('id') or '?'
        if messagebox.askyesno("Xóa tài khoản", f"Xóa tài khoản '{email}'?"):
            del self.accounts[idx]
            save_accs(self.accounts)
            self._refresh_acc()

    def _import_accs(self):
        dlg = ctk.CTkInputDialog(text="Dán mỗi dòng: email|password|2fa_secret", title="Import tài khoản")
        raw = dlg.get_input()
        if not raw: return
        for line in raw.splitlines():
            p = [x.strip() for x in line.strip().split("|")]
            if p and p[0]:
                self.accounts.append({"id": p[0], "email": p[0], "password": p[1] if len(p) > 1 else "",
                                      "totp": p[2] if len(p) > 2 else "", "cookie": "", "status": "new"})
        save_accs(self.accounts); self._refresh_acc()

    def _manual_login(self):
        if L is None:
            messagebox.showerror("Thiếu thư viện", "Chưa cài DrissionPage. Chạy SETUP.bat trước."); return
        def logp(m):
            self.after(0, lambda: self.lbl_acc_prog.configure(text=m))
            self._log(f"[Manual Login] {m}")

        # Tìm tài khoản cần login (chết / chưa login) VÀ đã có password → auto-fill
        need_login = [a for a in self.accounts
                      if a.get("enabled", True)
                      and a.get("password")
                      and not (a.get("cookie") and a.get("status") == "ok")]

        def work():
            os.makedirs(os.path.join(HERE, "_profiles"), exist_ok=True)

            # ── Pha 1: Auto login bằng password+2FA cho các tài khoản đã có credentials ──
            if need_login:
                logp(f"🔑 Tự động đăng nhập {len(need_login)} tài khoản có password...")
                for i, a in enumerate(need_login, 1):
                    if self._stop: break
                    email = a.get("email") or a.get("id") or "?"
                    profile_dir = os.path.join(HERE, "_profiles", email.replace("@", "_"))
                    logp(f"🔑 [{i}/{len(need_login)}] Đang login {email} (auto-fill email+pass+2FA)...")
                    try:
                        ck = L.login_get_cookie(a["email"], a["password"], a.get("totp", ""),
                                                profile_dir=profile_dir, log=logp)
                    except Exception as ex:
                        logp(f"❌ [{i}/{len(need_login)}] Lỗi login {email}: {ex}")
                        ck = None
                    if ck:
                        res = E.bearer_from_cookie(ck)
                        b = res[0] if isinstance(res, tuple) else res
                        em = res[1] if (isinstance(res, tuple) and len(res) > 1) else None
                        a["cookie"] = ck; a["status"] = "ok" if b else "dead"
                        if em: a["email"] = em
                        if b:
                            logp(f"✅ [{i}/{len(need_login)}] {email}: login thành công!")
                        else:
                            logp(f"⚠️ [{i}/{len(need_login)}] {email}: có cookie nhưng chưa dùng được.")
                    else:
                        a["status"] = "dead"
                        logp(f"❌ [{i}/{len(need_login)}] {email}: login thất bại.")
                    save_accs(self.accounts)
                    self.after(0, self._refresh_acc)
                logp(f"✅ Auto-fill login xong ({len(need_login)} tài khoản).")
            else:
                # ── Pha 2: Không có tài khoản nào có password → mở Chrome thủ công như cũ ──
                logp("🖐 Không có tài khoản nào cần login có password — mở Chrome để đăng nhập thủ công...")
                try:
                    ck = L.manual_login(log=logp)
                except Exception as ex:
                    logp(f"❌ Lỗi mở Chrome: {ex}")
                    ck = None
                if ck:
                    res = E.bearer_from_cookie(ck)
                    b = res[0] if isinstance(res, tuple) else res
                    em = res[1] if (isinstance(res, tuple) and len(res) > 1) else None
                    if b:
                        found = next((a for a in self.accounts if a.get("email") == em), None)
                        if found:
                            found["cookie"] = ck; found["status"] = "ok"; found["email"] = em
                        else:
                            self.accounts.append({"id": em, "email": em, "password": "", "totp": "", "cookie": ck, "status": "ok"})
                        save_accs(self.accounts)
                        self.after(0, lambda: (self._refresh_acc(), logp(f"✅ Đã thêm {em}")))
                    else:
                        logp("⚠️ Có cookie nhưng chưa dùng được — thử lại.")
                else:
                    logp("Chưa lấy được cookie (chưa đăng nhập xong / đã đóng Chrome).")
        threading.Thread(target=work, daemon=True).start()

    def _clear_accs(self):
        if messagebox.askyesno("Xóa", "Xóa tất cả tài khoản?"):
            self.accounts = []; save_accs(self.accounts); self._refresh_acc()

    def _check_accs(self):
        def work():
            def one(a):
                if a.get("cookie"):
                    res = E.bearer_from_cookie(a["cookie"])
                    b = res[0] if isinstance(res, tuple) else res
                    em = res[1] if (isinstance(res, tuple) and len(res) > 1) else None
                    a["status"] = "ok" if b else "dead"
                    if em: a["email"] = em
                return a
            self.after(0, lambda: self.lbl_acc_prog.configure(text="⏳ Đang check..."))
            with ThreadPoolExecutor(max_workers=8) as ex:
                list(ex.map(one, [a for a in self.accounts if a.get("cookie")]))
            save_accs(self.accounts)
            self.after(0, lambda: (self._refresh_acc(), self.lbl_acc_prog.configure(text="Check xong")))
        threading.Thread(target=work, daemon=True).start()

    def _auto_login(self):
        if L is None:
            messagebox.showerror("Thiếu thư viện", "Chưa cài DrissionPage. Chạy SETUP.bat trước."); return
        def logp(m):
            self.after(0, lambda: self.lbl_acc_prog.configure(text=m))
            self._log(f"[Auto Login] {m}")
        def work():
            # Bước 1: Xác minh thực tế cookie còn sống bằng cách gọi API Google Labs
            logp("🩺 Đang xác minh cookie với Google Labs...")
            verified_count = 0
            for a in self.accounts:
                if not (a.get("enabled", True) or a.get("role") == "donor"):
                    continue
                if a.get("cookie") and a.get("status") == "ok":
                    res = E.bearer_from_cookie(a["cookie"])
                    b = res[0] if isinstance(res, tuple) else res
                    if not b:
                        a["status"] = "dead"
                        logp(f"🩺 {a.get('email', '?')}: cookie đã hết hạn → cần login lại.")
                    else:
                        verified_count += 1
            save_accs(self.accounts); self.after(0, self._refresh_acc)
            # Bước 2: Tìm tài khoản cần login: chưa có cookie hoặc cookie chết
            todo = [a for a in self.accounts if (a.get("enabled", True) or a.get("role") == "donor") and not (a.get("cookie") and a.get("status") == "ok")]
            if not todo:
                logp(f"✅ Tất cả {verified_count} tài khoản đã có cookie hoạt động (đã xác minh với Google).")
                self.after(0, lambda: messagebox.showinfo("Không cần", f"Tất cả {verified_count} tài khoản đã có cookie hoạt động (đã xác minh với Google)."))
                return
            logp(f"🔑 Cần login lại {len(todo)} tài khoản...")
            os.makedirs(os.path.join(HERE, "_profiles"), exist_ok=True)
            for i, a in enumerate(todo, 1):
                if self._stop: break
                email = a.get('email') or a.get('id') or '?'
                profile_dir = os.path.join(HERE, "_profiles", email.replace("@", "_"))

                # Pha 1: Thử mở profile cũ (không cần password)
                if os.path.exists(profile_dir):
                    logp(f"🔄 [{i}/{len(todo)}] Thử profile cũ cho {email}...")
                    ck = L.reopen_profile_cookie(profile_dir, log=logp, timeout=90, poll=3)
                    if ck:
                        res = E.bearer_from_cookie(ck)
                        b = res[0] if isinstance(res, tuple) else res
                        em = res[1] if (isinstance(res, tuple) and len(res) > 1) else None
                        a["cookie"] = ck; a["status"] = "ok" if b else "dead"
                        if em: a["email"] = em
                        if b:
                            logp(f"✅ [{i}/{len(todo)}] {email}: profile login thành công!")
                            save_accs(self.accounts); self.after(0, self._refresh_acc)
                            continue

                # Pha 2: Dùng password nếu có
                if a.get("password"):
                    logp(f"🔑 [{i}/{len(todo)}] Đang login {email} bằng password...")
                    ck = L.login_get_cookie(a["email"], a["password"], a.get("totp", ""),
                                            profile_dir=profile_dir, log=logp)
                    if ck:
                        res = E.bearer_from_cookie(ck)
                        b = res[0] if isinstance(res, tuple) else res
                        em = res[1] if (isinstance(res, tuple) and len(res) > 1) else None
                        a["cookie"] = ck; a["status"] = "ok" if b else "dead"
                        if em: a["email"] = em
                    else:
                        a["status"] = "dead"
                else:
                    logp(f"⚠️ [{i}/{len(todo)}] {email}: không có profile cũ + không có password → bấm ✏️ để nhập.")
                save_accs(self.accounts); self.after(0, self._refresh_acc)
            logp("✅ Auto login xong.")
        threading.Thread(target=work, daemon=True).start()
    # ============ AUTO COOKIE HEALTH CHECK ============
    def _toggle_health_check(self):
        """Bật/tắt tự kiểm tra cookie định kỳ."""
        self._health_check_enabled = self._hc_var.get()
        if self._health_check_enabled:
            self._schedule_health_check()
            self._log("🩺 Đã BẬT tự kiểm tra cookie.")
            self._hc_status_lbl.configure(text="Đã bật", text_color=GR)
        else:
            if self._health_check_timer:
                self.after_cancel(self._health_check_timer)
                self._health_check_timer = None
            self._log("🩺 Đã TẮT tự kiểm tra cookie.")
            self._hc_status_lbl.configure(text="Đã tắt", text_color=T2)

    def _get_hc_interval_ms(self):
        """Lấy interval từ ô nhập (phút -> ms). Tối thiểu 5 phút."""
        try:
            mins = max(5, int(self._hc_interval_var.get()))
        except (ValueError, TypeError):
            mins = 30
        self._health_check_interval = mins
        return mins * 60 * 1000

    def _schedule_health_check(self):
        """Đặt lịch kiểm tra cookie lần kế tiếp."""
        if self._health_check_timer:
            self.after_cancel(self._health_check_timer)
        interval_ms = self._get_hc_interval_ms()
        self._health_check_timer = self.after(interval_ms, self._cookie_health_check)
        next_str = time.strftime("%H:%M:%S", time.localtime(time.time() + interval_ms / 1000))
        self._hc_status_lbl.configure(text=f"Lần check kế: {next_str}", text_color=GR)

    def _run_health_check_now(self):
        """Chạy health check ngay lập tức (nút bấm)."""
        if self._health_checking:
            messagebox.showinfo("Đang chạy", "Health check đang chạy, vui lòng chờ."); return
        threading.Thread(target=self._do_health_check, daemon=True).start()

    def _cookie_health_check(self):
        """Được gọi bởi timer — chạy health check rồi đặt lịch lần kế."""
        if not self._health_check_enabled:
            return
        threading.Thread(target=self._do_health_check, daemon=True).start()

    def _do_health_check(self):
        """Kiểm tra tất cả cookie → đánh dấu dead → auto re-login nếu có password."""
        if self._health_checking:
            return
        self._health_checking = True
        try:
            self.after(0, lambda: self._hc_status_lbl.configure(text="⏳ Đang check cookie...", text_color="#F9A825"))
            self._log("🩺 [Health Check] Bắt đầu kiểm tra cookie...")

            # Bước 1: Kiểm tra cookie song song
            accs_with_cookie = [a for a in self.accounts if a.get("cookie") and (a.get("enabled", True) or a.get("role") == "donor")]
            if not accs_with_cookie:
                self._log("🩺 [Health Check] Không có tài khoản nào cần check.")
                self.after(0, lambda: self._hc_status_lbl.configure(text="Không có tài khoản", text_color=T2))
                return

            dead_accs = []
            def check_one(a):
                res = E.bearer_from_cookie(a["cookie"])
                b = res[0] if isinstance(res, tuple) else res
                em = res[1] if (isinstance(res, tuple) and len(res) > 1) else None
                if b:
                    a["status"] = "ok"
                    if em: a["email"] = em
                else:
                    a["status"] = "dead"
                    dead_accs.append(a)

            with ThreadPoolExecutor(max_workers=8) as ex:
                list(ex.map(check_one, accs_with_cookie))

            save_accs(self.accounts)
            self.after(0, self._refresh_acc)

            alive = len(accs_with_cookie) - len(dead_accs)
            self._log(f"🩺 [Health Check] Kết quả: {alive} sống, {len(dead_accs)} chết.")

            # Bước 2: Auto re-login theo 2 pha (giống Chiến Hust)
            # Pha 1: Thử mở Chrome profile cũ (KHÔNG cần password) — Google session trong profile còn sống → tự lấy cookie mới
            # Pha 2: Nếu profile fail + có password → dùng password login lại
            if dead_accs and L is not None:
                still_dead = []
                self._log(f"🔄 [Health Check] Pha 1: Thử mở Chrome profile cũ cho {len(dead_accs)} tài khoản chết (không cần password)...")
                self.after(0, lambda: self._hc_status_lbl.configure(
                    text=f"🔄 Profile re-login {len(dead_accs)} tk...", text_color="#F9A825"))
                for i, a in enumerate(dead_accs, 1):
                    email = a.get("email") or a.get("id") or "?"
                    profile_dir = os.path.join(HERE, "_profiles", email.replace("@", "_"))
                    if not hasattr(self, "_hc_attempted_accs") or isinstance(self._hc_attempted_accs, set):
                        self._hc_attempted_accs = {}
                    now = time.time()
                    last_try = self._hc_attempted_accs.get(email, 0.0)
                    if now - last_try < 300:
                        self._log(f"  [{i}/{len(dead_accs)}] {email}: Đã thử khôi phục gần đây ({int(now - last_try)}s trước) → Tạm dừng để tránh vòng lặp bật/tắt.")
                        still_dead.append(a)
                        continue
                    if not os.path.exists(profile_dir):
                        self._log(f"  [{i}/{len(dead_accs)}] {email}: chưa có profile → bỏ qua pha 1.")
                        still_dead.append(a)
                        continue
                    self._hc_attempted_accs[email] = now
                    self._log(f"  [{i}/{len(dead_accs)}] {email}: đang mở profile cũ...")
                    try:
                        ck = L.reopen_profile_cookie(
                            profile_dir,
                            log=lambda m, _e=email: self._log(f"  [Profile {_e}] {m}"),
                            timeout=90, poll=3
                        )
                        if ck:
                            res = E.bearer_from_cookie(ck)
                            b = res[0] if isinstance(res, tuple) else res
                            em = res[1] if (isinstance(res, tuple) and len(res) > 1) else None
                            a["cookie"] = ck
                            a["status"] = "ok" if b else "dead"
                            if em: a["email"] = em
                            if b:
                                self._log(f"✅ [Health Check] {email}: profile re-login thành công! (không cần password)")
                            else:
                                self._log(f"⚠️ [Health Check] {email}: có cookie mới nhưng không dùng được.")
                                still_dead.append(a)
                        else:
                            still_dead.append(a)
                            self._log(f"⚠️ [Health Check] {email}: profile hết session → cần password.")
                    except Exception as ex:
                        still_dead.append(a)
                        self._log(f"⚠️ [Health Check] {email}: lỗi profile: {ex}")
                    save_accs(self.accounts)
                    self.after(0, self._refresh_acc)

                # Pha 2: Fallback dùng password cho các acc vẫn còn chết
                relogin_accs = [a for a in still_dead if a.get("password")]
                if relogin_accs:
                    self._log(f"🔑 [Health Check] Pha 2: Dùng password re-login {len(relogin_accs)} tài khoản còn chết...")
                    self.after(0, lambda: self._hc_status_lbl.configure(
                        text=f"🔑 Password login {len(relogin_accs)} tk...", text_color="#F9A825"))
                    for i, a in enumerate(relogin_accs, 1):
                        email = a.get("email") or a.get("id") or "?"
                        self._log(f"🔑 [Health Check] [{i}/{len(relogin_accs)}] Re-login {email} bằng password...")
                        try:
                            ck = L.login_get_cookie(
                                a["email"], a["password"], a.get("totp", ""),
                                profile_dir=os.path.join(HERE, "_profiles", a["email"].replace("@", "_")),
                                log=lambda m: self._log(f"  [Health Check] {m}")
                            )
                            if ck:
                                res = E.bearer_from_cookie(ck)
                                b = res[0] if isinstance(res, tuple) else res
                                em = res[1] if (isinstance(res, tuple) and len(res) > 1) else None
                                a["cookie"] = ck
                                a["status"] = "ok" if b else "dead"
                                if em: a["email"] = em
                                if b:
                                    self._log(f"✅ [Health Check] {email}: password re-login thành công!")
                                else:
                                    self._log(f"⚠️ [Health Check] {email}: có cookie mới nhưng không dùng được.")
                            else:
                                a["status"] = "dead"
                                self._log(f"❌ [Health Check] {email}: password re-login thất bại.")
                        except Exception as ex:
                            self._log(f"❌ [Health Check] {email}: lỗi re-login: {ex}")
                        save_accs(self.accounts)
                        self.after(0, self._refresh_acc)
                elif still_dead:
                    no_pass = [a.get("email", "?") for a in still_dead if not a.get("password")]
                    if no_pass:
                        self._log(f"⚠️ [Health Check] {len(no_pass)} tài khoản vẫn chết + không có password: {', '.join(no_pass[:5])}")
                        self._log("💡 Bấm ✏️ cạnh tài khoản để nhập password, hoặc dùng 'Nhập thủ công' để login.")
            elif dead_accs:
                self._log("🩺 [Health Check] Có tài khoản chết nhưng thiếu DrissionPage → không re-login được.")

            # Tổng kết
            final_alive = sum(1 for a in self.accounts if a.get("cookie") and a.get("status") == "ok" and (a.get("enabled", True) or a.get("role") == "donor"))
            self._log(f"🩺 [Health Check] Hoàn tất — {final_alive} tài khoản sẵn sàng.")
            self.after(0, lambda: self._hc_status_lbl.configure(
                text=f"✅ {final_alive} sống · {time.strftime('%H:%M')}", text_color=GR))
        except Exception as ex:
            self._log(f"❌ [Health Check] Lỗi: {ex}")
            self.after(0, lambda: self._hc_status_lbl.configure(text=f"❌ Lỗi", text_color=RD))
        finally:
            self._health_checking = False
            try:
                self._sv_sync_cookies()
            except Exception:
                pass
            # Đặt lịch lần check kế nếu vẫn bật
            if self._health_check_enabled:
                self.after(0, self._schedule_health_check)

    # ============ TAB TẠO VIDEO ============
    def _build_gen(self):
        f = ctk.CTkFrame(self.content, fg_color=BG); self.frames["gen"] = f
        top = ctk.CTkFrame(f, fg_color="transparent"); top.pack(fill="x")
        ctk.CTkLabel(top, text="🎬 Tạo Video", font=("", 20, "bold"), text_color=T1).pack(side="left")
        self.gen_mode = ctk.StringVar(value=self.settings.get("gen_mode", "i2v"))   # MẶC ĐỊNH Image → Video
        ctk.CTkRadioButton(top, text="Image → Video", variable=self.gen_mode, value="i2v", command=self._gen_mode).pack(side="right", padx=(12, 0))
        ctk.CTkRadioButton(top, text="Text → Video", variable=self.gen_mode, value="t2v", command=self._gen_mode).pack(side="right")
        # I2V: thư mục ảnh gốc
        self.r_ref = ctk.CTkFrame(f, fg_color="transparent")
        ctk.CTkLabel(self.r_ref, text="📁 Thư mục ảnh gốc:", width=150, anchor="w").pack(side="left")
        self.ent_ref = ctk.CTkEntry(self.r_ref); self.ent_ref.pack(side="left", fill="x", expand=True, padx=6)
        if "ref_dir" in self.settings:
            self.ent_ref.insert(0, self.settings["ref_dir"])
        ctk.CTkButton(self.r_ref, text="Chọn & Nạp ảnh", width=130, command=self._load_ref_images, fg_color=GR, hover_color="#00695C").pack(side="left")
        # thanh prompt
        rowb = ctk.CTkFrame(f, fg_color="transparent"); rowb.pack(fill="x", pady=(8, 2))
        ctk.CTkButton(rowb, text="📂 Nạp prompt .txt", command=self._load_prompts, fg_color="#5f6368", height=30, width=140).pack(side="left")
        self.lbl_gen_info = ctk.CTkLabel(rowb, text="Mỗi dòng .txt = prompt cho 1 ảnh (theo thứ tự). Sửa trực tiếp bên dưới.", text_color=T2, font=("", 11)); self.lbl_gen_info.pack(side="left", padx=10)
        # ── AI Viết Prompt (dùng cookie tài khoản Google AI Ultra) ──
        row_ai = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); row_ai.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(row_ai, text="🤖", font=("", 15)).pack(side="left", padx=(12, 4), pady=8)
        ctk.CTkLabel(row_ai, text="Chủ đề:", font=("", 12)).pack(side="left")
        self.ent_ai_topic = ctk.CTkTextbox(row_ai, width=320, height=45, font=("", 11))
        self.ent_ai_topic.pack(side="left", padx=6, pady=4)
        if self.settings.get("ai_topic"):
            self.ent_ai_topic.insert("1.0", self.settings["ai_topic"])
        ctk.CTkLabel(row_ai, text="Style:", font=("", 11)).pack(side="left", padx=(8, 2))
        self.opt_ai_style = ctk.CTkOptionMenu(row_ai, values=["stickman", "stickman_hoodie", "anime", "chibi", "silhouette"], width=120)
        self.opt_ai_style.pack(side="left", padx=(0, 6))
        self.opt_ai_style.set(self.settings.get("ai_char_style", "stickman"))
        ctk.CTkLabel(row_ai, text="Cảnh:", font=("", 11)).pack(side="left", padx=(4, 2))
        self.opt_ai_scenes = ctk.CTkOptionMenu(row_ai, values=["4", "5", "6", "7", "8"], width=60)
        self.opt_ai_scenes.pack(side="left", padx=(0, 6))
        self.opt_ai_scenes.set(self.settings.get("ai_num_scenes", "5"))
        self.btn_ai_gen = ctk.CTkButton(row_ai, text="🤖 AI viết prompt", command=self._ai_gen_prompt,
                                         fg_color="#8E24AA", hover_color="#6A1B9A", height=32, width=150, font=("", 12, "bold"))
        self.btn_ai_gen.pack(side="left", padx=(6, 12))
        # BOTTOM: nút thêm + cài đặt (pack trước -> nằm dưới)
        ctk.CTkButton(f, text="➕ Thêm vào hàng đợi", command=self._add_queue, fg_color=AC, hover_color=AC2, height=42, font=("", 15, "bold")).pack(side="bottom", fill="x", pady=(8, 0))
        
        rs = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); rs.pack(side="bottom", fill="x", pady=8)
        ctk.CTkLabel(rs, text="⚙", font=("", 15)).pack(side="left", padx=(12, 4), pady=10)
        ctk.CTkLabel(rs, text="Tỉ lệ:").pack(side="left")
        self.opt_aspect = ctk.CTkOptionMenu(rs, values=list(E.VID_ASPECTS.keys()), width=140)
        self.opt_aspect.pack(side="left", padx=(4, 12))
        self.opt_aspect.set(self.settings.get("aspect", "Dọc 9:16 (TikTok)"))
        
        ctk.CTkLabel(rs, text="Upload/TK:").pack(side="left")
        self.opt_upload_threads_per_acc = ctk.CTkOptionMenu(rs, values=["2", "3", "4", "5", "6", "7", "8", "9", "10"], width=60)
        self.opt_upload_threads_per_acc.pack(side="left", padx=(4, 12))
        saved_gen_up = self.settings.get("gen_upload_threads_per_acc", "4")
        self.opt_upload_threads_per_acc.set(saved_gen_up)

        ctk.CTkLabel(rs, text="Đặt tên:").pack(side="left")
        self.opt_naming = ctk.CTkOptionMenu(rs, values=["Đặt tên theo ảnh", "13 ký tự đầu prompt", "Số thứ tự (001...)", "40 ký tự đầu chủ đề"], width=150)
        self.opt_naming.pack(side="left", padx=(4, 12))
        self.opt_naming.set(self.settings.get("naming", "13 ký tự đầu prompt"))
        
        ctk.CTkLabel(rs, text="Lưu:").pack(side="left")
        self.ent_out = ctk.CTkEntry(rs, width=170)
        self.ent_out.pack(side="left", padx=4)
        if "out_dir" in self.settings:
            self.ent_out.insert(0, self.settings["out_dir"])
        ctk.CTkButton(rs, text="Chọn", width=56, command=lambda: self._pick(self.ent_out)).pack(side="left", padx=(0, 10))
        
        ctk.CTkLabel(rs, text="Veo 3.1 Lite (miễn phí)", font=("", 11, "bold"), text_color=GR).pack(side="left", padx=(0, 12))




        # MIDDLE: 1 ô prompt duy nhất (KHÔNG thumbnail -> nhẹ, chịu 25k ảnh)
        self.txt_prompts = ctk.CTkTextbox(f, font=("Consolas", 11))
        self.ref_images = self.image_paths
        self.ref_promptfile = None
        self._gen_mode()

        # Phục hồi dữ liệu ảnh & prompt đã nạp của phiên trước
        if self.gen_mode.get() == "t2v":
            t2v_p = self.settings.get("t2v_prompts", "")
            if t2v_p:
                self.txt_prompts.insert("1.0", t2v_p)
        else:
            # i2v mode
            # Phục hồi prompt từ bộ nhớ
            if self.loaded_prompts:
                if len(self.loaded_prompts) <= 3000:
                    self.txt_prompts.insert("1.0", "\n".join(self.loaded_prompts))
                else:
                    self.txt_prompts.insert("1.0", f"(Đã nạp {len(self.loaded_prompts)} prompt — file lớn nên không hiển thị.)")
            self._update_gen_info()

    def _ai_gen_prompt(self):
        """Nhờ Gemini viết prompt Veo tự động. Hỗ trợ chạy hàng loạt chủ đề (multi-topic)."""
        def make_safe_dir_name(s):
            """Chuyển tên chủ đề tiếng Việt thành tên thư mục Windows an toàn (không dấu, thay space bằng _)."""
            s = remove_vietnamese_accents(s)
            import re
            s = re.sub(r'[^a-zA-Z0-9\s_-]', '', s)
            s = s.strip().replace(' ', '_')
            # Giới hạn tối đa 40 ký tự để tránh lỗi đường dẫn quá dài trên Windows
            return s[:40].strip('_')

        raw_topic = self.ent_ai_topic.get("1.0", "end-1c").strip()
        if not raw_topic:
            messagebox.showwarning("Thiếu chủ đề", "Nhập chủ đề cho video (mỗi dòng 1 chủ đề).")
            return
        
        topics = [t.strip() for t in raw_topic.splitlines() if t.strip()]
        
        # Thu thập nguồn auth: Gemini API keys (ưu tiên) + cookies tài khoản
        gemini_keys = [l.strip() for l in self.txt_gemini.get("1.0", "end").splitlines() if l.strip()]
        accs = [a for a in self.accounts if a.get("cookie") and str(a.get("status", "")).lower() == "ok"]
        if not gemini_keys and not accs:
            messagebox.showerror("Thiếu xác thực",
                                 "Cần ít nhất 1 trong 2:\n"
                                 "• API Gemini key (tab Tài khoản → ô API Gemini)\n"
                                 "• Tài khoản Google (status OK) có cookie\n\n"
                                 "Lấy API key miễn phí: aistudio.google.com/apikey")
            return
            
        style = self.opt_ai_style.get()
        num_scenes = int(self.opt_ai_scenes.get())
        out_base = self.ent_out.get().strip()
        if not out_base:
            messagebox.showwarning("Thiếu", "Vui lòng cấu hình thư mục lưu trước khi sinh hàng loạt.")
            return

        self.btn_ai_gen.configure(state="disabled", text="⏳ Đang viết...")
        # Cache widget values on main thread before spawning background thread
        _cached_aspect = self.opt_aspect.get()
        _cached_gen_mode = self.gen_mode.get()

        def _do():
            # LUỒNG 1: Chỉ có 1 chủ đề duy nhất -> Chạy luồng cũ hiển thị lên TextBox để kiểm tra
            if len(topics) == 1:
                topic = topics[0]
                result_prompts = None
                last_error = "Không tìm thấy API key hay tài khoản hợp lệ."
                
                # 1) Thử Gemini API keys trước (ổn định nhất)
                if gemini_keys:
                    self.after(0, lambda: self._log(f"🤖 Thử {len(gemini_keys)} API key Gemini..."))
                    random.shuffle(gemini_keys)
                    for i, key in enumerate(gemini_keys):
                        key_hint = key[:8] + "..." if len(key) > 8 else key
                        status, res = E.generate_video_prompts(
                            topic, num_scenes=num_scenes, char_style=style, api_key=key)
                        
                        if status == "ok":
                            result_prompts = res
                            self.after(0, lambda k=key_hint: self._log(f"   Key {k} → OK"))
                            break
                        else:
                            last_error = res if isinstance(res, str) else f"Lỗi key {status}"
                            self.after(0, lambda k=key_hint, err=last_error: self._log(f"   Key {k} → {err}"))
                            
                # 2) Fallback: dùng cookie tài khoản
                if not result_prompts and accs:
                    self.after(0, lambda: self._log(f"🤖 Thử {len(accs)} cookie tài khoản..."))
                    random.shuffle(accs)
                    for acc in accs:
                        email = acc.get("email", "?")[:20]
                        status, res = E.generate_video_prompts(
                            topic, num_scenes=num_scenes, char_style=style, cookie=acc["cookie"])
                        
                        if status == "ok":
                            result_prompts = res
                            self.after(0, lambda e=email: self._log(f"   Cookie {e} → OK"))
                            break
                        else:
                            last_error = res if isinstance(res, str) else f"Lỗi cookie {status}"
                            self.after(0, lambda e=email, err=last_error: self._log(f"   Cookie {e} → {err}"))

                def _update():
                    self.btn_ai_gen.configure(state="normal", text="🤖 AI viết prompt")
                    if result_prompts:
                        self.txt_prompts.delete("1.0", "end")
                        self.txt_prompts.insert("1.0", "\n".join(result_prompts))
                        self.loaded_prompts = result_prompts
                        self.ref_promptfile = None
                        self._log(f"🤖 AI đã viết {len(result_prompts)} prompt cho chủ đề: {topic}")
                        self._update_gen_info()
                    else:
                        self._log(f"❌ AI viết prompt thất bại. Lỗi cuối: {last_error}")
                        messagebox.showerror("Lỗi AI", f"Không thể sinh prompt.\nChi tiết lỗi từ Google: {last_error}")
                self.after(0, _update)
                return

            # LUỒNG 2: Sinh hàng loạt (từ 2 chủ đề trở lên) -> Tự chia thư mục con và nạp THẲNG vào hàng đợi
            self.after(0, lambda: self._log(f"🤖 Bắt đầu sinh prompt hàng loạt cho {len(topics)} chủ đề..."))
            total_added = 0
            
            # Xoay tua API key và cookies để chống bị 429
            current_key_idx = 0
            current_acc_idx = 0
            
            for t_idx, topic in enumerate(topics):
                self.after(0, lambda t=topic, idx=t_idx: self._log(f"📝 ({idx+1}/{len(topics)}) Đang sinh prompt cho: '{t}'..."))
                
                result_prompts = None
                last_error = "Hết key/cookie"
                
                # Gọi Gemini bằng API keys xoay tua
                if gemini_keys:
                    for _ in range(len(gemini_keys)):
                        key = gemini_keys[current_key_idx]
                        current_key_idx = (current_key_idx + 1) % len(gemini_keys)
                        status, res = E.generate_video_prompts(
                            topic, num_scenes=num_scenes, char_style=style, api_key=key)
                        if status == "ok":
                            result_prompts = res
                            break
                        else:
                            last_error = res
                            
                # Fallback bằng cookie xoay tua
                if not result_prompts and accs:
                    for _ in range(len(accs)):
                        acc = accs[current_acc_idx]
                        current_acc_idx = (current_acc_idx + 1) % len(accs)
                        status, res = E.generate_video_prompts(
                            topic, num_scenes=num_scenes, char_style=style, cookie=acc["cookie"])
                        if status == "ok":
                            result_prompts = res
                            break
                        else:
                            last_error = res
                            
                if result_prompts:
                    # Tạo thư mục con riêng biệt cho chủ đề này
                    safe_name = make_safe_dir_name(topic)
                    sub_dir = os.path.join(out_base, safe_name)
                    os.makedirs(sub_dir, exist_ok=True)
                    
                    # Nạp thẳng các job vào hàng đợi
                    existing_set = {j["out"] for j in self.jobs}
                    aspect = E.VID_ASPECTS[_cached_aspect]
                    model = "veo_3_1_t2v_lite_low_priority"
                    job_type = _cached_gen_mode
                    
                    added_topic = 0
                    for s_idx, pr in enumerate(result_prompts):
                        if "|" in pr:
                            parts = pr.split("|")
                            prompt_val = parts[0].strip()
                            voice_val = parts[1].strip()
                        else:
                            prompt_val = pr
                            voice_val = ""
                            
                        # Đặt tên video thành phần 001.mp4, 002.mp4...
                        fn = f"{s_idx+1:03d}.mp4"
                        unique_out = os.path.join(sub_dir, fn)
                        
                        if unique_out in existing_set:
                            continue
                        existing_set.add(unique_out)
                        
                        self.jobs.append({
                            "type": job_type, 
                            "prompt": prompt_val, 
                            "voice": voice_val, 
                            "ref": None, 
                            "aspect": aspect, 
                            "model": model,
                            "out": unique_out, 
                            "status": "chờ"
                        })
                        added_topic += 1
                        total_added += 1
                        
                    self.after(0, lambda t=topic, n=added_topic: self._log(f"   ✅ Đã nạp {n} job của '{t}' vào hàng đợi."))
                    # Chờ ngắn 2 giây giữa các chủ đề để tránh rate limit
                    time.sleep(2)
                else:
                    self.after(0, lambda t=topic, err=last_error: self._log(f"   ❌ Sinh prompt thất bại cho '{t}': {err}"))
            
            def _done():
                self.btn_ai_gen.configure(state="normal", text="🤖 AI viết prompt")
                self._refresh_queue(force=True)
                self._log(f"🎉 Hoàn thành! Tự động nạp tổng cộng {total_added} job của {len(topics)} chủ đề vào Hàng Đợi.")
                messagebox.showinfo("Thành công", 
                                    f"Đã sinh prompt hàng loạt xong!\n"
                                    f"Tự động tạo các thư mục con tương ứng và nạp {total_added} job vào hàng đợi thành công!")
            self.after(0, _done)

        threading.Thread(target=_do, daemon=True).start()

    def _gen_mode(self):
        self.txt_prompts.pack_forget(); self.r_ref.pack_forget()
        if self.gen_mode.get() == "i2v":
            self.r_ref.pack(fill="x", pady=(6, 0), after=self.frames["gen"].winfo_children()[0])
        self.txt_prompts.pack(fill="both", expand=True, pady=(4, 0))
        self._update_gen_info()

    def _pick(self, ent):
        d = filedialog.askdirectory()
        if d: ent.delete(0, "end"); ent.insert(0, d)

    def _load_ref_images(self):
        d = filedialog.askdirectory()
        if not d: return
        self.ent_ref.delete(0, "end"); self.ent_ref.insert(0, d)
        # CHỈ liệt kê tên file (nhanh, KHÔNG tạo thumbnail) -> chịu được 25k ảnh không treo
        import re
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
        self.ref_images = [os.path.join(d, x) for x in sorted(os.listdir(d), key=natural_sort_key) if x.lower().endswith(IMG_EXT)]
        self.image_paths = self.ref_images
        self.ref_promptfile = None
        for cand in ("prompt.txt", "prompts.txt"):
            p = os.path.join(d, cand)
            if os.path.exists(p):
                lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
                if len(lines) <= 3000:   # nhỏ -> hiện vào ô để xem/sửa
                    self.txt_prompts.delete("1.0", "end"); self.txt_prompts.insert("1.0", "\n".join(l for l in lines if l.strip()))
                    self.loaded_prompts = [l.strip() for l in lines if l.strip()]
                else:                    # lớn -> chỉ tham chiếu file (không render, tránh treo)
                    self.ref_promptfile = p
                    self.loaded_prompts = [l.strip() for l in lines if l.strip()]
                break
        self._update_gen_info()

    def _update_gen_info(self):
        if self.gen_mode.get() != "i2v":
            self.lbl_gen_info.configure(text="Text → Video: mỗi dòng = 1 video."); return
        n = len(self.ref_images)
        if self.ref_promptfile:
            self.lbl_gen_info.configure(text=f"📁 {n} ảnh · prompt từ {os.path.basename(self.ref_promptfile)} (file lớn — ghép theo thứ tự khi tạo)")
        else:
            self.lbl_gen_info.configure(text=f"📁 {n} ảnh — mỗi dòng prompt bên dưới ghép cho 1 ảnh theo thứ tự (ảnh 1↔dòng 1...)")

    def _load_prompts(self):
        fp = filedialog.askopenfilename(filetypes=[("Text", "*.txt")])
        if not fp: return
        lines = open(fp, encoding="utf-8", errors="replace").read().splitlines()
        self.loaded_prompts = [l.strip() for l in lines if l.strip()]
        if len(lines) <= 3000:
            self.ref_promptfile = None
            self.txt_prompts.delete("1.0", "end"); self.txt_prompts.insert("1.0", "\n".join(l for l in lines if l.strip()))
        else:
            self.ref_promptfile = fp
            self.txt_prompts.delete("1.0", "end")
            self.txt_prompts.insert("1.0", f"(Đã nạp {len(lines)} prompt từ {os.path.basename(fp)} — file lớn nên không hiển thị. Ghép theo thứ tự khi tạo.)")
        self._update_gen_info()

    def _read_prompts(self):
        if self.ref_promptfile:
            return [l.strip() for l in open(self.ref_promptfile, encoding="utf-8", errors="replace").read().splitlines() if l.strip()]
        raw = [l.strip() for l in self.txt_prompts.get("1.0", "end").splitlines() if l.strip() and not l.startswith("(Đã nạp")]
        if raw:
            return raw
        return self.loaded_prompts

    def _add_queue(self):
        out = self.ent_out.get().strip()
        if not out: messagebox.showwarning("Thiếu", "Chọn thư mục lưu."); return
        aspect = E.VID_ASPECTS[self.opt_aspect.get()]; model = "veo_3_1_t2v_lite_low_priority"  # bản miễn phí (I2V engine tự đổi r2v)
        mode = self.gen_mode.get(); base = len(self.jobs); added = 0; skipped = 0
        prompts = self._read_prompts()
        naming = self.opt_naming.get()
        existing_set = {j["out"] for j in self.jobs}

        if mode == "i2v":
            if not self.ref_images: messagebox.showwarning("Thiếu ảnh", "Bấm 'Chọn & Nạp ảnh' để nạp ảnh gốc."); return
            
            # Xây dựng danh sách ID ảnh
            id_to_image = {}
            for ref in self.ref_images:
                img_name = os.path.splitext(os.path.basename(ref))[0].strip()
                id_to_image[img_name.lower()] = ref
                clean_id = clean_filename(img_name)
                if clean_id:
                    id_to_image[clean_id.lower()] = ref

            # Thử khớp từng dòng prompt với ảnh tương ứng qua ID
            pairs_to_process = []
            matched_count = 0
            for pr in prompts:
                ref = None
                part_before_pipe = pr.split('|')[0].strip()
                tokens = part_before_pipe.split()
                if tokens:
                    first_token = tokens[0].strip()
                    for tk in (first_token, clean_filename(first_token)):
                        tk_low = tk.lower()
                        if tk_low in id_to_image:
                            ref = id_to_image[tk_low]
                            break
                if not ref:
                    for cand in (part_before_pipe, clean_filename(part_before_pipe)):
                        cand_low = cand.lower()
                        if cand_low in id_to_image:
                            ref = id_to_image[cand_low]
                            break
                if ref:
                    pairs_to_process.append((pr, ref))
                    matched_count += 1

            # Sử dụng khớp theo ID nếu có ít nhất 1 dòng khớp và tỉ lệ khớp >= 10% tổng số prompt
            use_id_matching = matched_count > 0 and (matched_count >= len(prompts) * 0.1)
            
            if use_id_matching:
                self._log(f"🔍 Khớp theo ID: Đã tự động ghép {matched_count}/{len(prompts)} dòng prompt với ảnh theo ID trùng nhau.")
            else:
                # Fallback: ghép lần lượt theo chỉ mục (index-based)
                pairs_to_process = []
                for i, ref in enumerate(self.ref_images):
                    pr = prompts[i] if i < len(prompts) else (prompts[-1] if prompts else "")
                    if pr:
                        pairs_to_process.append((pr, ref))

            for pr, ref in pairs_to_process:
                if not pr: continue

                if "|" in pr:
                    parts = pr.split("|")
                    prompt_val = parts[0].strip()
                    voice_val = parts[1].strip()
                else:
                    prompt_val = pr
                    voice_val = ""

                # RESUME: đặt tên theo ảnh -> tên output CỐ ĐỊNH = tên ảnh. Rà soát thư mục output:
                # nếu video đã có -> BỎ QUA ảnh này (không làm lại). KHÔNG thêm hậu tố _1 (giữ tên ổn định
                # để lần chạy sau nhận ra "đã xong").
                if naming == "Đặt tên theo ảnh":
                    fn = clean_filename(os.path.splitext(os.path.basename(ref))[0]) or f"{base+added+1:03d}"
                    unique_out = os.path.join(out, fn + ".mp4")
                    if os.path.exists(unique_out):
                        skipped += 1; continue                 # đã có video ở output -> bỏ qua
                    if unique_out in existing_set:
                        continue                               # đã có trong hàng đợi -> bỏ qua
                    existing_set.add(unique_out)
                    self.jobs.append({"type": "i2v", "prompt": prompt_val, "voice": voice_val, "ref": ref, "aspect": aspect, "model": model,
                                      "out": unique_out, "status": "chờ"}); added += 1
                    continue

                # Các chế độ đặt tên khác (không ổn định cho resume) -> giữ hậu tố chống trùng.
                if naming == "13 ký tự đầu prompt":
                    fn = clean_filename(prompt_val[:13])
                elif naming == "40 ký tự đầu chủ đề":
                    topic_raw = self.ent_ai_topic.get("1.0", "end-1c").strip()
                    first_topic = topic_raw.splitlines()[0].strip() if topic_raw else "video"
                    fn = clean_filename(remove_vietnamese_accents(first_topic))[:40]
                else:  # Số thứ tự
                    fn = f"{base+added+1:03d}"
                if not fn:
                    fn = f"{base+added+1:03d}"
                fn = fn + ".mp4"
                unique_out = get_unique_out_path(out, fn, existing_set)
                existing_set.add(unique_out)
                self.jobs.append({"type": "i2v", "prompt": prompt_val, "voice": voice_val, "ref": ref, "aspect": aspect, "model": model,
                                  "out": unique_out, "status": "chờ"}); added += 1
        else:
            for pr in prompts:
                if "|" in pr:
                    parts = pr.split("|")
                    prompt_val = parts[0].strip()
                    voice_val = parts[1].strip()
                else:
                    prompt_val = pr
                    voice_val = ""

                if naming == "Đặt tên theo ảnh":
                    fn = clean_filename(prompt_val[:13])
                elif naming == "13 ký tự đầu prompt":
                    fn = clean_filename(prompt_val[:13])
                elif naming == "40 ký tự đầu chủ đề":
                    topic_raw = self.ent_ai_topic.get("1.0", "end-1c").strip()
                    first_topic = topic_raw.splitlines()[0].strip() if topic_raw else "video"
                    fn = clean_filename(remove_vietnamese_accents(first_topic))[:40]
                else: # Số thứ tự
                    fn = f"{base+added+1:03d}"
                if not fn:
                    fn = f"{base+added+1:03d}"

                fn = fn + ".mp4"
                unique_out = get_unique_out_path(out, fn, existing_set)
                existing_set.add(unique_out)

                self.jobs.append({"type": "t2v", "prompt": prompt_val, "voice": voice_val, "ref": None, "aspect": aspect, "model": model,
                                  "out": unique_out, "status": "chờ"}); added += 1
        if skipped:
            self._log(f"⏭ Bỏ qua {skipped} ảnh đã có video ở thư mục lưu (resume).")
        if not added:
            if skipped:
                messagebox.showinfo("Đã xong", f"Tất cả {skipped} ảnh đã có video ở thư mục lưu — không còn gì để làm.")
            else:
                messagebox.showwarning("Thiếu prompt", "Chưa có prompt.")
            return
        if skipped:
            messagebox.showinfo("Đã thêm", f"Thêm {added} job. Bỏ qua {skipped} ảnh đã có video (resume).")
        self._refresh_queue(force=True); self._show("queue")

    # ============ TAB HÀNG ĐỢI ============
    def _build_queue(self):
        f = ctk.CTkFrame(self.content, fg_color=BG); self.frames["queue"] = f
        st = ctk.CTkFrame(f, fg_color="transparent"); st.pack(fill="x")
        self.stat_lbl = {}
        for key, txt, col in [("tong", "Tổng", "#3949AB"), ("xuly", "Xử lý", "#F9A825"), ("xong", "Xong", GR), ("loi", "Lỗi", RD)]:
            c = ctk.CTkFrame(st, fg_color=CARD, corner_radius=10); c.pack(side="left", expand=True, fill="x", padx=4)
            ctk.CTkLabel(c, text=txt, font=("", 12), text_color=T2).pack(pady=(10, 0))
            lb = ctk.CTkLabel(c, text="0", font=("", 24, "bold"), text_color=col); lb.pack(pady=(0, 10)); self.stat_lbl[key] = lb
        # --- PANEL POOL VIDEO (đồng bộ thiết kế: card trắng + số to màu như ô thống kê trên) ---
        poolcard = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12); poolcard.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(poolcard, text="🎬  Pool khai thác", font=("", 14, "bold"), text_color=T1).pack(anchor="w", padx=16, pady=(12, 2))
        prow = ctk.CTkFrame(poolcard, fg_color="transparent"); prow.pack(fill="x", padx=10, pady=(2, 4))
        self.pool_stat_lbl = {}
        for key, txt, col in [("acc", "Tài khoản", AC), ("run", "Đang chạy", GR), ("gen", "Đang tạo", "#F9A825"), ("rest", "Nghỉ", T2)]:
            c = ctk.CTkFrame(prow, fg_color=BG, corner_radius=8); c.pack(side="left", expand=True, fill="x", padx=4)
            ctk.CTkLabel(c, text=txt, font=("", 11), text_color=T2).pack(pady=(6, 0))
            lb = ctk.CTkLabel(c, text="0", font=("", 20, "bold"), text_color=col); lb.pack(pady=(0, 6))
            self.pool_stat_lbl[key] = lb
        # Dòng tốc độ + ước tính thời gian hoàn thành
        self.pool_eta_lbl = ctk.CTkLabel(poolcard, text="", font=("", 12, "bold"), text_color=AC, anchor="w")
        self.pool_eta_lbl.pack(fill="x", padx=16, pady=(2, 2))
        self.pool_rows_frame = ctk.CTkFrame(poolcard, fg_color="transparent"); self.pool_rows_frame.pack(fill="x", padx=14, pady=(2, 12))
        self._pool_rows = {}          # email -> {nhãn giá trị}
        self._pool_row_sig = None     # chữ ký tập tài khoản (để biết khi nào dựng lại hàng)
        bar = ctk.CTkFrame(f, fg_color="transparent"); bar.pack(fill="x", pady=10)
        self.btn_run = ctk.CTkButton(bar, text="▶ Bắt đầu", command=self._start, fg_color=AC, hover_color=AC2, height=38, width=120, font=("", 14, "bold")); self.btn_run.pack(side="left")
        ctk.CTkButton(bar, text="■ Dừng", command=self._stop_run, fg_color="#5f6368", height=38, width=90).pack(side="left", padx=6)

        ctk.CTkButton(bar, text="↻ Retry lỗi", command=self._retry, fg_color="#9aa0a6", height=38, width=100).pack(side="left", padx=(16, 4))
        ctk.CTkButton(bar, text="🗑 Xóa xong", command=self._clear_done, fg_color="#9aa0a6", height=38, width=100).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="🗑 Xóa Vi Phạm CS", command=self._clear_violation, fg_color="#E57373", hover_color="#EF5350", height=38, width=130).pack(side="left", padx=4)

        self.use_laundering = ctk.BooleanVar(value=self.settings.get("use_laundering", False))
        self.chk_laundering = ctk.CTkCheckBox(bar, text="Rửa ảnh (Bypass 429)", variable=self.use_laundering, font=("", 11), checkbox_width=18, checkbox_height=18)
        self.chk_laundering.pack(side="left", padx=(16, 4))

        self.auto_concat = ctk.BooleanVar(value=self.settings.get("auto_concat", False))
        ctk.CTkCheckBox(bar, text="🔗 Tự ghép video", variable=self.auto_concat, font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(8, 4))

        self.remove_veo_wm = ctk.BooleanVar(value=self.settings.get("remove_veo_wm", True))
        ctk.CTkCheckBox(bar, text="🧹 Xóa logo Veo", variable=self.remove_veo_wm, font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(8, 4))

        # --- THANH GIỌNG NÓI CỐ ĐỊNH ---
        bar_voice = ctk.CTkFrame(f, fg_color=CARD, corner_radius=8); bar_voice.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(bar_voice, text="🎙 Giọng nói:", font=("", 12, "bold"), text_color=T1).pack(side="left", padx=(10, 4), pady=6)
        self.ent_voice_desc = ctk.CTkEntry(bar_voice, height=30, font=("", 11),
                                           placeholder_text="VD: Narrated by a warm, calm Vietnamese male voice, mid-30s, deep tone")
        self.ent_voice_desc.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=4)
        saved_voice = self.settings.get("voice_desc", "")
        if saved_voice:
            self.ent_voice_desc.insert(0, saved_voice)

        # --- THANH CHỌN (CHECK) ---
        bar2 = ctk.CTkFrame(f, fg_color=CARD, corner_radius=8); bar2.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(bar2, text="☑ Chọn:", font=("", 12, "bold"), text_color=T1).pack(side="left", padx=(10, 4), pady=6)
        ctk.CTkLabel(bar2, text="Từ dòng:", font=("", 11), text_color=T2).pack(side="left", padx=(4, 2))
        self.ent_check_from = ctk.CTkEntry(bar2, width=60, height=30); self.ent_check_from.pack(side="left", padx=(0, 4))
        self.ent_check_from.insert(0, "1")
        ctk.CTkLabel(bar2, text="Đến dòng:", font=("", 11), text_color=T2).pack(side="left", padx=(4, 2))
        self.ent_check_to = ctk.CTkEntry(bar2, width=60, height=30); self.ent_check_to.pack(side="left", padx=(0, 6))
        ctk.CTkButton(bar2, text="☑ Check", command=self._check_range, fg_color=AC, hover_color=AC2, height=30, width=80, font=("", 11, "bold")).pack(side="left", padx=2)
        ctk.CTkButton(bar2, text="☐ Bỏ chọn", command=self._uncheck_range, fg_color="#9aa0a6", hover_color="#5f6368", height=30, width=90, font=("", 11)).pack(side="left", padx=2)
        ctk.CTkButton(bar2, text="Chọn tất cả", command=self._select_all, fg_color="#3949AB", hover_color="#283593", height=30, width=90, font=("", 11)).pack(side="left", padx=2)
        ctk.CTkButton(bar2, text="Bỏ tất cả", command=self._deselect_all, fg_color="#9aa0a6", hover_color="#5f6368", height=30, width=80, font=("", 11)).pack(side="left", padx=2)
        self.lbl_checked = ctk.CTkLabel(bar2, text="Đã chọn: 0", font=("", 11, "bold"), text_color=AC); self.lbl_checked.pack(side="left", padx=(10, 4))
        ctk.CTkButton(bar2, text="🗑 Xóa đã chọn", command=self._delete_checked, fg_color=RD, hover_color="#c62828", height=30, width=110, font=("", 11, "bold")).pack(side="right", padx=(2, 10))
        ctk.CTkButton(bar2, text="↻ Retry đã chọn", command=self._retry_checked, fg_color=GR, hover_color="#00695C", height=30, width=120, font=("", 11, "bold")).pack(side="right", padx=2)
        ctk.CTkButton(bar2, text="📁 Đổi folder", command=self._change_folder_checked, fg_color="#5C6BC0", hover_color="#3949AB", height=30, width=100, font=("", 11)).pack(side="right", padx=2)
        ctk.CTkButton(bar2, text="✏ Đổi tên", command=self._rename_checked, fg_color="#5C6BC0", hover_color="#3949AB", height=30, width=90, font=("", 11)).pack(side="right", padx=2)

        self.progress = ctk.CTkProgressBar(f); self.progress.pack(fill="x", pady=4); self.progress.set(0)

        # Split frame to make Queue list and Log side-by-side (50/50 width)
        split_frame = ctk.CTkFrame(f, fg_color="transparent")
        split_frame.pack(fill="both", expand=True, pady=(6, 6))

        self.txt_queue = ctk.CTkTextbox(split_frame, height=250, font=("Consolas", 10))
        self.txt_queue.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self.txt_log = ctk.CTkTextbox(split_frame, height=250, font=("Consolas", 10), fg_color="#0f1b3d", text_color="#8be9c0")
        self.txt_log.pack(side="right", fill="both", expand=True, padx=(4, 0))

        # Phục hồi dữ liệu hàng đợi hiển thị của phiên trước
        self._refresh_queue(force=True)

    def _refresh_queue(self, force=False):
        # THROTTLE: 25k job -> chỉ refresh các ô đếm tối đa 1 lần/giây
        now = time.time()
        if not force and now - getattr(self, "_last_qref", 0) < 1.0:
            return
        self._last_qref = now
        tong = len(self.jobs); xong = loi = xuly = 0
        for j in self.jobs:                      # đếm 1 LẦN
            s = j["status"]
            if s == "xong": xong += 1
            elif s in ("lỗi", "vi phạm cs"): loi += 1
            elif s == "đang": xuly += 1
        self.stat_lbl["tong"].configure(text=str(tong)); self.stat_lbl["xong"].configure(text=str(xong))
        self.stat_lbl["loi"].configure(text=str(loi)); self.stat_lbl["xuly"].configure(text=str(xuly))
        self.lbl_qcount.configure(text=f"Hàng đợi: {tong}")
        if tong: self.progress.set((xong + loi) / tong)

        # Đồng bộ check_vars với số lượng jobs
        while len(self.check_vars) < len(self.jobs):
            self.check_vars.append(ctk.BooleanVar(value=False))
        if len(self.check_vars) > len(self.jobs):
            self.check_vars = self.check_vars[:len(self.jobs)]
        # Cập nhật nhãn đã chọn
        checked_count = sum(1 for v in self.check_vars if v.get())
        try:
            self.lbl_checked.configure(text=f"Đã chọn: {checked_count}")
        except Exception:
            pass

        # Cập nhật ô "Đến dòng" mặc định = tổng số dòng
        try:
            cur_to = self.ent_check_to.get().strip()
            if not cur_to:
                self.ent_check_to.insert(0, str(tong))
        except Exception:
            pass
        
        # Tránh đơ UI khi cập nhật hàng chục ngàn dòng chữ:
        # Chỉ vẽ lại khung Textbox chi tiết khi force=True hoặc sau mỗi 5 giây trong lúc đang chạy
        is_running = getattr(self, "_running", False)
        if not force and is_running and now - getattr(self, "_last_txt_ref", 0) < 5.0:
            return
        self._last_txt_ref = now

        self.txt_queue.configure(state="normal")
        self.txt_queue.delete("1.0", "end")
        # Cấu hình tag màu (chỉ 1 lần)
        self.txt_queue.tag_config("dang", foreground="#E53935")      # đỏ — đang chạy
        self.txt_queue.tag_config("xong", foreground="#2E7D32")      # xanh lá — thành công
        self.txt_queue.tag_config("loi", foreground="#E65100")        # cam đậm — lỗi
        self.txt_queue.tag_config("vipham", foreground="#AD1457")     # hồng đậm — vi phạm cs
        self.txt_queue.tag_config("cho", foreground="#555555")        # xám — chờ

        def _fmt(i, j):
            chk = "☑" if (i-1 < len(self.check_vars) and self.check_vars[i-1].get()) else "☐"
            ic = {"chờ": "⏳", "đang": "🔄", "xong": "✅", "lỗi": "❌", "vi phạm cs": "⚠️"}.get(j["status"], "")
            ref_name = os.path.basename(j["ref"])[:20] if j.get("ref") else "-"
            return f"{chk} {i:<5}{('T2V' if j['type']=='t2v' else 'I2V'):<5}{ic+' '+j['status']:<11}{ref_name:<22}{j['prompt'][:48]:<50}{os.path.basename(j['out'])}"

        header = f"Hàng đợi: {tong} job · Xong {xong} · Lỗi {loi}\n" + "-" * 90
        MAX_SHOW = 300  # Giới hạn hiển thị để UI không đơ

        if tong <= MAX_SHOW:
            # Đủ nhỏ → hiển thị toàn bộ
            lines = [header]
            tags_map = [None]  # header không cần tag
            for i, j in enumerate(self.jobs, 1):
                lines.append(_fmt(i, j))
                tags_map.append({"đang": "dang", "xong": "xong", "lỗi": "loi", "vi phạm cs": "vipham"}.get(j["status"], "cho"))
        else:
            # Quá nhiều → hiển thị thông minh: đang chạy + lỗi + đầu/cuối
            lines = [header]
            tags_map = [None]
            # 1) Jobs đang chạy (ưu tiên cao nhất)
            running = [(i, j) for i, j in enumerate(self.jobs, 1) if j["status"] == "đang"]
            if running:
                lines.append(f"\n━━━ ĐANG CHẠY ({len(running)}) ━━━")
                tags_map.append(None)
                for i, j in running:
                    lines.append(_fmt(i, j))
                    tags_map.append("dang")
            # 2) Jobs lỗi / vi phạm (cần chú ý)
            errors = [(i, j) for i, j in enumerate(self.jobs, 1) if j["status"] in ("lỗi", "vi phạm cs")]
            if errors:
                lines.append(f"\n━━━ LỖI ({len(errors)}) ━━━")
                tags_map.append(None)
                for i, j in errors[:50]:  # Giới hạn 50 lỗi
                    lines.append(_fmt(i, j))
                    tags_map.append("loi" if j["status"] == "lỗi" else "vipham")
                if len(errors) > 50:
                    lines.append(f"  ... và {len(errors) - 50} lỗi khác")
                    tags_map.append(None)
            # 3) 100 dòng đầu + 100 dòng cuối
            show_head = 100; show_tail = 100
            lines.append(f"\n━━━ DANH SÁCH (hiện {show_head} đầu + {show_tail} cuối / {tong} job) ━━━")
            tags_map.append(None)
            for i, j in enumerate(self.jobs[:show_head], 1):
                lines.append(_fmt(i, j))
                tags_map.append({"đang": "dang", "xong": "xong", "lỗi": "loi", "vi phạm cs": "vipham"}.get(j["status"], "cho"))
            if tong > show_head + show_tail:
                lines.append(f"  ... ẩn {tong - show_head - show_tail} dòng giữa ...")
                tags_map.append(None)
            for idx in range(max(show_head, tong - show_tail), tong):
                i = idx + 1; j = self.jobs[idx]
                lines.append(_fmt(i, j))
                tags_map.append({"đang": "dang", "xong": "xong", "lỗi": "loi", "vi phạm cs": "vipham"}.get(j["status"], "cho"))

        # Insert toàn bộ 1 lần (nhanh hơn insert từng dòng rất nhiều)
        full_text = "\n".join(lines)
        self.txt_queue.insert("1.0", full_text)
        # Apply tag màu theo từng dòng (bắt đầu từ dòng 1 trong textbox)
        for line_idx, tag in enumerate(tags_map):
            if tag:
                self.txt_queue.tag_add(tag, f"{line_idx+1}.0", f"{line_idx+1}.end")

    def _rolling_rate(self, window_min=10):
        """Tốc độ trung bình trượt: đếm video xong trong `window_min` phút ĐÃ HOÀN CHỈNH
        (không tính phút hiện tại đang dang dở).
        VD: lúc 10:42:xx → cửa sổ = 10:32:00 đến 10:41:59.
        Chỉ tính lại mỗi 1 phút, giữa các lần trả cache."""
        now = time.time()
        cache = getattr(self, "_rate_cache", None)
        if cache and now - cache[0] < 60:            # chưa đủ 1 phút → trả cache
            return cache[1]
        ts_deque = getattr(self, "_done_timestamps", None)
        if not ts_deque:
            rate = 0.0
        else:
            lt = time.localtime(now)
            # Đầu phút hiện tại (10:42:00) = mốc kết thúc cửa sổ (không tính phút đang chạy)
            end = now - lt.tm_sec                        # bỏ giây lẻ → đầu phút hiện tại
            start = end - window_min * 60                # lùi 10 phút → đầu cửa sổ
            count = sum(1 for ts in ts_deque if start <= ts < end)
            rate = count / window_min if count > 0 else 0.0
        self._rate_cache = (now, rate)
        return rate

    def _eta_text(self):
        """Tốc độ trượt 10 phút (video/phút) + ước tính khi nào xong."""
        jobs = getattr(self, "_eta_jobs", None) or []
        t0 = getattr(self, "_run_t0", 0.0)
        if not self._running or not jobs or not t0:
            return ""
        now = time.time()
        # còn lại = chưa xong và chưa hỏng vĩnh viễn (vi phạm chính sách / thiếu ảnh gốc)
        remaining = sum(1 for j in jobs if j["status"] not in ("xong", "vi phạm cs") and not j.get("_noretry"))
        elapsed = now - t0
        rate_min = self._rolling_rate()   # trung bình 10 phút gần nhất
        if rate_min <= 0:
            return f"⚡ Đang đo tốc độ…   ·   còn {remaining} video"
        eta_min = remaining / rate_min
        fin = time.localtime(now + eta_min * 60)
        dur = f"{int(eta_min // 60)}g{int(eta_min % 60):02d}p" if eta_min >= 60 else f"{int(eta_min)+1}p"
        return (f"⚡ {rate_min:.1f} video/phút   ·   còn {remaining} video   ·   "
                f"dự kiến xong sau {dur}  (≈ {time.strftime('%H:%M', fin)}  {time.strftime('%d/%m', fin)})")

    def _toggle_acc_enabled(self, email):
        """Đảo trạng thái dừng/chạy của tài khoản khi người dùng click nút Dừng/Chạy trên bảng Pool."""
        acc = next((a for a in self.accounts if a.get("email") == email), None)
        if not acc:
            return
        new_val = not acc.get("enabled", True)
        acc["enabled"] = new_val
        acc_name = str(email).split("@")[0][:22]
        if new_val:
            self._log(f"▶ Đã tiếp tục tài khoản [{acc_name}] (đã bật lại 'Dùng' trong tab Tài khoản)")
            if hasattr(self, "proxy_pool") and self.proxy_pool and not self.proxy_pool.get_str(email):
                self.proxy_pool.assign(email)
        else:
            self._log(f"⏹ Đã dừng tài khoản [{acc_name}] (đã bỏ chọn 'Dùng' trong tab Tài khoản)")
            if hasattr(self, "proxy_pool") and self.proxy_pool:
                self.proxy_pool.release(email)

        # Cập nhật checkbox ở Tab Tài khoản nếu UI đang vẽ
        if hasattr(self, "_acc_rows") and email in self._acc_rows:
            try:
                chk_var = self._acc_rows[email].get("var")
                if chk_var:
                    chk_var.set(new_val)
            except Exception:
                pass
        save_accs(self.accounts)

        # Cập nhật lại UI bảng Pool ngay lập tức
        self.after(0, self._update_pool)
        self.after(0, self._sp_update_pool)
        self.after(0, self._sv_update_pool)

    def _on_acc_upload_threads_change(self, st, val):
        """Thay đổi số luồng upload của riêng tài khoản này — có hiệu lực ngay lập tức trong thời gian thực."""
        try:
            num = max(2, min(10, int(val)))
            st.set_upload_threads(num)
            for a in self.accounts:
                if (a.get("email") or a.get("id")) == st.email:
                    a["upload_threads"] = num
                    break
            save_accs(self.accounts)
            if hasattr(self, '_sv_log_msg') and getattr(self, '_sv_running', False):
                self._sv_log_msg(f"⚙️ {st.email[:16]}: Đã đổi luồng Upload thành {num} (có hiệu lực ngay lập tức)")
            if hasattr(self, '_sp_log_msg') and getattr(self, '_shopee_running', False):
                self._sp_log_msg(f"⚙️ {st.email[:16]}: Đã đổi luồng Upload thành {num} (có hiệu lực ngay lập tức)")
            self._log(f"⚙️ [{st.email}] Đã đổi số luồng Upload thành {num} (có hiệu lực tức thì)")
        except Exception as e:
            self._log(f"❌ Lỗi đổi luồng upload: {e}")

    def _update_pool(self):
        """Panel POOL VIDEO (cập nhật mỗi 2s) — tối ưu chỉ redraw khi giá trị thay đổi."""
        try:
            # Fix 3: Bỏ qua nếu tab Tạo Video không hiển thị (finally vẫn reschedule)
            if getattr(self, '_current_tab', 'gen') != 'gen':
                return

            if not hasattr(self, '_pool_cache'):
                self._pool_cache = {}
            cache = self._pool_cache

            def _set(widget, key, **kwargs):
                val = tuple(sorted(kwargs.items()))
                if cache.get(key) != val:
                    widget.configure(**kwargs)
                    cache[key] = val

            _set(self.pool_eta_lbl, "_eta", text=self._eta_text())
            is_running = getattr(self, "_running", False)
            states = getattr(self, "_pool_states", None)
            if not is_running or not states:
                states = [AccountState(a) for a in self.accounts if a.get("enabled", True) and a.get("role", "main") == "main"]
            total = len(states)
            resting = sum(1 for s in states if s.rest_remaining() > 0)
            running = total - resting
            generating = sum(1 for s in states if getattr(s, "busy", 0) > 0)
            _set(self.pool_stat_lbl["acc"], "_st_acc", text=str(total))
            _set(self.pool_stat_lbl["run"], "_st_run", text=str(running if is_running else total))
            _set(self.pool_stat_lbl["gen"], "_st_gen", text=str(generating))
            _set(self.pool_stat_lbl["rest"], "_st_rest", text=str(resting if is_running else 0))

            sig = tuple(s.email for s in states)
            if sig != self._pool_row_sig:
                self._pool_row_sig = sig
                cache.clear()
                for w in self.pool_rows_frame.winfo_children():
                    w.destroy()
                self._pool_rows = {}
                if not states:
                    ctk.CTkLabel(self.pool_rows_frame, text="Chưa có tài khoản nào được chọn ở Tab 'Tài khoản'.",
                                 font=("", 11), text_color=T2).pack(anchor="w", pady=6)
                else:
                    cols = [("Tài khoản", 140), ("✅ Xong", 55), ("❌ Lỗi", 50),
                            ("⚡ Tạo", 45), ("🚀 Tốc độ", 65), ("Trạng thái", 110), ("Hành động", 65), ("📤 Upload", 60)]
                    hdr = ctk.CTkFrame(self.pool_rows_frame, fg_color="transparent"); hdr.pack(fill="x", pady=(0, 2))
                    for txt, w in cols:
                        ctk.CTkLabel(hdr, text=txt, font=("", 10, "bold"), text_color=T2, width=w, anchor="w").pack(side="left", padx=(2, 0))
                    for i, s in enumerate(states):
                        row = ctk.CTkFrame(self.pool_rows_frame, fg_color=("#f6f8fc" if i % 2 else CARD), corner_radius=6)
                        row.pack(fill="x", pady=1)
                        ctk.CTkLabel(row, text=str(s.email).split("@")[0][:22], font=("", 11), text_color=T1, width=140, anchor="w").pack(side="left", padx=(2, 0))
                        wl = ctk.CTkLabel(row, text="0", font=("", 11, "bold"), text_color=GR, width=55, anchor="w"); wl.pack(side="left", padx=(2, 0))
                        fl = ctk.CTkLabel(row, text="0", font=("", 11), text_color=RD, width=50, anchor="w"); fl.pack(side="left", padx=(2, 0))
                        bl = ctk.CTkLabel(row, text="0", font=("", 11), text_color=T1, width=45, anchor="w"); bl.pack(side="left", padx=(2, 0))
                        rl = ctk.CTkLabel(row, text="0", font=("", 11), text_color=AC, width=65, anchor="w"); rl.pack(side="left", padx=(2, 0))
                        sl = ctk.CTkLabel(row, text="", font=("", 11), text_color=GR, width=110, anchor="w"); sl.pack(side="left", padx=(2, 0))
                        ab = ctk.CTkButton(row, text="⏹ Dừng", fg_color="#E57373", hover_color="#EF5350", width=60, height=24, font=("", 11, "bold"),
                                           command=lambda e=s.email: self._toggle_acc_enabled(e))
                        ab.pack(side="left", padx=(2, 0))
                        uo = ctk.CTkOptionMenu(row, values=["2", "3", "4", "5", "6", "7", "8", "9", "10"], width=52, height=24, font=("", 11),
                                               command=lambda v, st=s: self._on_acc_upload_threads_change(st, v))
                        uo.pack(side="left", padx=(4, 0))
                        uo.set(str(getattr(s, "upload_threads", 4)))
                        self._pool_rows[s.email] = {"w": wl, "f": fl, "b": bl, "r": rl, "s": sl, "a": ab, "u": uo}

            for s in states:
                r = self._pool_rows.get(s.email)
                if not r: continue
                e = s.email
                _set(r["w"], f"m_{e}_w", text=str(s.wins))
                _set(r["f"], f"m_{e}_f", text=str(s.fails))
                _set(r["b"], f"m_{e}_b", text=str(s.busy))
                _set(r["r"], f"m_{e}_r", text=str(int(s.submit_limit)))
                is_enabled = s.acc.get("enabled", True)
                if not is_enabled:
                    _set(r["s"], f"m_{e}_s", text="⏹ đã dừng", text_color=T2)
                    _set(r["a"], f"m_{e}_a", text="▶ Chạy", fg_color="#26A69A", hover_color="#00897B")
                elif not is_running:
                    _set(r["s"], f"m_{e}_s", text="⏳ Sẵn sàng", text_color=GR)
                    _set(r["a"], f"m_{e}_a", text="⏹ Dừng", fg_color="#E57373", hover_color="#EF5350")
                else:
                    _set(r["a"], f"m_{e}_a", text="⏹ Dừng", fg_color="#E57373", hover_color="#EF5350")
                    rem = s.rest_remaining()
                    if rem > 0:
                        if s.rest_reason == "quota":
                            _set(r["s"], f"m_{e}_s", text=f"⛔ cách ly {int(rem//60)}p", text_color=RD)
                        else:
                            _set(r["s"], f"m_{e}_s", text=f"😴 nghỉ {int(rem)}s", text_color="#F9A825")
                    else:
                        _set(r["s"], f"m_{e}_s", text="🟢 đang chạy", text_color=GR)
        except Exception:
            pass
        finally:
            self.after(2000, self._update_pool)

    def _rewrite_prompt(self, prompt):
        """Xoay qua các key Gemini còn tốt, nhờ viết lại prompt vi phạm. Trả prompt mới hoặc None.
        Key sai/hết quyền (dead) -> loại; key bận/hết quota (busy) -> thử key kế."""
        with self._gemini_lock:
            keys = [k for k in self._gemini_active if k not in self._gemini_bad]
        for k in keys:
            status, text = E.rewrite_prompt(k, prompt)
            if status == "ok" and text:
                return text
            if status == "dead":
                with self._gemini_lock:
                    self._gemini_bad.add(k)
        return None

    def _log(self, m):
        """Ghi log tab Tạo Video — batch 500ms."""
        if not hasattr(self, '_log_buffer'):
            self._log_buffer = []
            self._log_flush_scheduled = False
        self._log_buffer.append(m)
        if not self._log_flush_scheduled:
            self._log_flush_scheduled = True
            self.after(500, self._flush_log)

    def _flush_log(self):
        """Flush tất cả log buffer tab Tạo Video 1 lần."""
        self._log_flush_scheduled = False
        if not hasattr(self, '_log_buffer') or not self._log_buffer:
            return
        batch = self._log_buffer[:]
        self._log_buffer.clear()
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                for m in batch:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}\n")
        except Exception:
            pass
        try:
            self.txt_log.insert("end", "\n".join(batch) + "\n")
            line_count = int(self.txt_log.index("end-1c").split(".")[0])
            if line_count > 1000:
                self.txt_log.delete("1.0", f"{line_count - 800}.0")
            self.txt_log.see("end")
        except Exception:
            pass

    def _on_global_proxy_error(self, proxy_dict):
        if not proxy_dict: return
        url = proxy_dict.get("http") or proxy_dict.get("https")
        if not url: return

        # Tìm AccountState đang chạy dùng proxy này
        st = None
        is_shopee = False
        
        # 1. Check Hàng đợi pool
        if hasattr(self, "_pool_states") and self._pool_states:
            for s in self._pool_states:
                if s.proxy == proxy_dict:
                    st = s
                    break
        
        # 2. Check Shopee pool
        if not st and hasattr(self, "_sp_pool_states") and self._sp_pool_states:
            for s in self._sp_pool_states:
                if s.proxy == proxy_dict:
                    st = s
                    is_shopee = True
                    break

        # 3. Check Donor pool
        if not st and hasattr(self, "_donor_states") and self._donor_states:
            for s in self._donor_states:
                if s.proxy == proxy_dict:
                    st = s
                    is_shopee = getattr(self, "_shopee_running", False)
                    break

        if st:
            # Đánh dấu proxy cũ là dead và đổi sang proxy mới trong pool
            with st.lock:
                old_px = self.proxy_pool.get_str(st.email)
                new_px = self.proxy_pool.mark_dead(st.email)
                
                log_func = self._sp_log_msg if is_shopee else self._log
                if new_px:
                    st.proxy = self.proxy_pool.get_dict(st.email)
                    log_func(f"  🔄 [Proxy Guard] {st.email[:16]}: phát hiện proxy lỗi 407/die → chuyển sang proxy mới {new_px[:30]}")
                else:
                    st.proxy = None
                    log_func(f"  ❌ [Proxy Guard] {st.email[:16]}: phát hiện proxy lỗi 407/die → hết proxy dự phòng, dùng IP trực tiếp.")
            # Cập nhật số liệu trên UI
            self.after(0, self._update_proxy_stats)

    def _send_telegram(self, text):
        """Gửi tin nhắn qua Telegram Bot API (chạy nền, không block UI)."""
        token = self.ent_tg_token.get().strip()
        chat_id = self.ent_tg_chatid.get().strip()
        if not token or not chat_id:
            return
        def _do():
            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                markup = {
                    "keyboard": [[{"text": "tkhangdoi"}, {"text": "tkshopee"}]],
                    "resize_keyboard": True
                }
                payload = {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": json.dumps(markup)
                }
                data = urllib.parse.urlencode(payload).encode()
                req = urllib.request.Request(url, data=data, method="POST")
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        self._log("📨 Đã gửi report Telegram.")
                    else:
                        self._log(f"⚠️ Telegram trả status {resp.status}")
            except Exception as e:
                self._log(f"⚠️ Gửi Telegram lỗi: {e}")
        threading.Thread(target=_do, daemon=True).start()

    def _build_telegram_stats(self):
        """Dựng tin nhắn thống kê chi tiết tự động dựa trên tab đang chạy."""
        is_shopee_running = getattr(self, "_shopee_running", False)
        if is_shopee_running:
            return self._build_telegram_stats_shopee()
        else:
            return self._build_telegram_stats_queue()

    def _build_telegram_stats_shopee(self):
        """Dựng tin nhắn thống kê Shopee."""
        results = getattr(self, "_sp_results", [])
        total = getattr(self, "_sp_total", 0)
        
        ok = sum(1 for r in results if r.get("status") == "success")
        err = sum(1 for r in results if r.get("error"))
        con_lai = max(0, total - ok - err)
        
        rate = getattr(self, "_sp_rolling_rate", lambda: 0.0)()
        
        elapsed_str = ""
        sp_t0 = getattr(self, "_sp_t0", 0.0)
        if sp_t0 > 0:
            elapsed = time.time() - sp_t0
            elapsed_str = f" ({_dur_label(elapsed)})"
            
        acc_lines = []
        states = list(getattr(self, "_sp_pool_states", []) or [])
        for s in states:
            rest = s.rest_remaining()
            status = f"😴 nghỉ {int(rest)}s" if rest > 0 else "🟢 chạy"
            acc_lines.append(f"  {s.email}: ✅{s.wins} ❌{s.fails} ⚡{int(s.submit_limit)} {status}")
            
        acc_section = "\n".join(acc_lines) if acc_lines else "  (Không có tài khoản hoạt động)"
        
        msg = (
            f"⏰ Thống kê Shopee{elapsed_str}\n"
            f"==============================\n"
            f"✅ Xong: {ok}/{total} · ❌ Lỗi: {err} · 📦 Còn: {con_lai}\n"
            f"⚡ Tốc độ: {rate:.1f} video/phút\n"
            f"👥 Tài khoản:\n"
            f"{acc_section}"
        )
        return msg

    def _build_telegram_stats_queue(self):
        """Dựng tin nhắn thống kê hàng đợi chính."""
        jobs_copy = list(self.jobs)
        tong = len(jobs_copy)
        xong = sum(1 for j in jobs_copy if j.get("status") == "xong")
        loi = sum(1 for j in jobs_copy if j.get("status") in ("lỗi", "vi phạm cs"))
        con_lai = sum(1 for j in jobs_copy if j.get("status") in ("chờ", "đang"))

        is_running = getattr(self, "_running", False)
        rate = 0.0
        elapsed_str = ""
        run_t0 = getattr(self, "_run_t0", 0.0)
        if is_running and run_t0 > 0:
            elapsed = time.time() - run_t0
            elapsed_str = f" ({_dur_label(elapsed)})"
            rate = self._rolling_rate()

        acc_lines = []
        states = list(getattr(self, "_pool_states", []) or [])
        if states:
            for s in states:
                rest = s.rest_remaining()
                status = f"😴 nghỉ {int(rest)}s" if rest > 0 else "🟢 chạy"
                acc_lines.append(f"  {s.email}: ✅{s.wins} ❌{s.fails} ⚡{int(s.submit_limit)} {status}")
        else:
            for a in self.accounts:
                if a.get("cookie") and a.get("enabled", True):
                    status = "🟢 ok" if a.get("status") == "ok" else ("❌ die" if a.get("status") == "dead" else "⚪ mới")
                    acc_lines.append(f"  {a.get('email')}: {status}")

        acc_section = "\n".join(acc_lines) if acc_lines else "  (Không có tài khoản)"

        msg = (
            f"⏰ Thống kê chạy{elapsed_str}\n"
            f"==============================\n"
            f"✅ Xong: {xong}/{tong} · ❌ Lỗi: {loi} · 📦 Còn: {con_lai}\n"
            f"⚡ Tốc độ: {rate:.1f} video/phút\n"
            f"👥 Tài khoản:\n"
            f"{acc_section}"
        )
        return msg

    def _start_telegram_polling(self):
        """Khởi động luồng lắng nghe lệnh từ Telegram."""
        # Khởi tạo cache cho thread nền (thread-safe vì Python GIL)
        self._cached_tg_token = self._tg_token_saved or ""
        self._cached_tg_chatid = self._tg_chatid_saved or ""
        self._cached_tg_enabled = self._tg_enabled_saved
        threading.Thread(target=self._telegram_polling_loop, daemon=True).start()

    def _update_tg_cache(self):
        """Cập nhật cache TG settings từ widget (chỉ gọi trên Main Thread)."""
        try:
            self._cached_tg_token = self.ent_tg_token.get().strip()
            self._cached_tg_chatid = self.ent_tg_chatid.get().strip()
            self._cached_tg_enabled = self.tg_enabled.get()
        except Exception:
            pass

    def _telegram_polling_loop(self):
        offset = None
        last_token = ""
        while True:
            try:
                # Đọc cache thay vì gọi .get() trên widget (tránh deadlock)
                token = self._cached_tg_token
                chat_id = self._cached_tg_chatid
                enabled = self._cached_tg_enabled

                # Cập nhật cache mỗi vòng lặp (an toàn vì schedule trên main thread)
                try:
                    self.after(0, self._update_tg_cache)
                except Exception:
                    pass

                if not token or not chat_id or not enabled:
                    time.sleep(5)
                    continue

                if token != last_token:
                    last_token = token
                    offset = None
                    
                    # Tự động đăng ký command với Telegram
                    def _init_bot_commands(tok):
                        try:
                            cmd_url = f"https://api.telegram.org/bot{tok}/setMyCommands"
                            cmds = [
                                {"command": "tkhangdoi", "description": "Thống kê hàng đợi"},
                                {"command": "tkshopee", "description": "Thống kê Shopee"}
                            ]
                            cmd_data = urllib.parse.urlencode({"commands": json.dumps(cmds)}).encode()
                            cmd_req = urllib.request.Request(cmd_url, data=cmd_data, method="POST")
                            with urllib.request.urlopen(cmd_req, timeout=10) as cmd_resp:
                                pass
                        except Exception:
                            pass
                    threading.Thread(target=_init_bot_commands, args=(token,), daemon=True).start()

                # Gọi getUpdates để lấy tin nhắn mới
                url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=10"
                if offset is not None:
                    url += f"&offset={offset}"

                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=12) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("ok"):
                            for update in data.get("result", []):
                                update_id = update["update_id"]
                                offset = update_id + 1

                                msg = update.get("message")
                                if not msg:
                                    continue

                                msg_chat_id = str(msg.get("chat", {}).get("id"))
                                if msg_chat_id != str(chat_id):
                                    continue

                                text = msg.get("text", "").strip().lower()
                                if text in ("/tkhangdoi", "tkhangdoi"):
                                    stats_text = self._build_telegram_stats_queue()
                                    self._send_telegram(stats_text)
                                elif text in ("/tkshopee", "tkshopee"):
                                    stats_text = self._build_telegram_stats_shopee()
                                    self._send_telegram(stats_text)
                                elif text in ("/tkaptm", "tkaptm", "aptmtk", "/aptmtk"):
                                    stats_text = self._build_telegram_stats()
                                    self._send_telegram(stats_text)
                    else:
                        time.sleep(5)
            except Exception:
                time.sleep(5)

    def _test_telegram(self):
        """Gửi tin nhắn test để kiểm tra Bot Token + Chat ID và cập nhật menu lệnh."""
        token = self.ent_tg_token.get().strip()
        chat_id = self.ent_tg_chatid.get().strip()
        if not token:
            messagebox.showwarning("Thiếu", "Nhập Bot Token."); return
        if not chat_id:
            messagebox.showwarning("Thiếu", "Nhập Chat ID."); return

        # Đồng bộ/Cập nhật menu lệnh ngay lập tức
        def _force_init():
            try:
                cmd_url = f"https://api.telegram.org/bot{token}/setMyCommands"
                cmds = [
                    {"command": "tkhangdoi", "description": "Thống kê hàng đợi"},
                    {"command": "tkshopee", "description": "Thống kê Shopee"}
                ]
                cmd_data = urllib.parse.urlencode({"commands": json.dumps(cmds)}).encode()
                cmd_req = urllib.request.Request(cmd_url, data=cmd_data, method="POST")
                with urllib.request.urlopen(cmd_req, timeout=10) as resp:
                    pass
            except Exception:
                pass
        threading.Thread(target=_force_init, daemon=True).start()

        self._send_telegram(f"✅ Test thành công!\n🤖 {_find_brand()[0]} đang hoạt động.")

    def _stop_run(self): self._stop = True; self._log("⏹ Đang dừng...")
    def _retry(self):
        for j in self.jobs:
            if j["status"] == "lỗi": j["status"] = "chờ"
        self._refresh_queue(force=True)
    def _clear_done(self):
        self.jobs = [j for j in self.jobs if j["status"] != "xong"]
        self.check_vars = []; self._refresh_queue(force=True)
    def _clear_violation(self):
        self.jobs = [j for j in self.jobs if j["status"] != "vi phạm cs"]
        self.check_vars = []; self._refresh_queue(force=True)

    # --- CÁC HÀM CHECK / CHỌN DÒNG ---
    def _check_range(self):
        """Check (chọn) các dòng từ 'Từ dòng' đến 'Đến dòng'."""
        try:
            fr = int(self.ent_check_from.get().strip() or "1")
            to_val = self.ent_check_to.get().strip()
            to = int(to_val) if to_val else len(self.jobs)
        except ValueError:
            messagebox.showwarning("Lỗi", "Nhập số dòng hợp lệ."); return
        fr = max(1, fr); to = min(to, len(self.jobs))
        if fr > to:
            messagebox.showwarning("Lỗi", f"Từ dòng ({fr}) phải ≤ Đến dòng ({to})."); return
        for i in range(fr - 1, to):
            if i < len(self.check_vars):
                self.check_vars[i].set(True)
        self._refresh_queue(force=True)

    def _uncheck_range(self):
        """Bỏ chọn các dòng từ 'Từ dòng' đến 'Đến dòng'."""
        try:
            fr = int(self.ent_check_from.get().strip() or "1")
            to_val = self.ent_check_to.get().strip()
            to = int(to_val) if to_val else len(self.jobs)
        except ValueError:
            messagebox.showwarning("Lỗi", "Nhập số dòng hợp lệ."); return
        fr = max(1, fr); to = min(to, len(self.jobs))
        for i in range(fr - 1, to):
            if i < len(self.check_vars):
                self.check_vars[i].set(False)
        self._refresh_queue(force=True)

    def _select_all(self):
        for v in self.check_vars: v.set(True)
        self._refresh_queue(force=True)

    def _deselect_all(self):
        for v in self.check_vars: v.set(False)
        self._refresh_queue(force=True)

    def _delete_checked(self):
        """Xóa các job đã được check (chọn)."""
        indices = [i for i, v in enumerate(self.check_vars) if v.get()]
        if not indices:
            messagebox.showinfo("Không có", "Chưa chọn dòng nào."); return
        if not messagebox.askyesno("Xóa", f"Xóa {len(indices)} job đã chọn?"):
            return
        # Xóa từ cuối lên để không bị lệch index
        for i in sorted(indices, reverse=True):
            if i < len(self.jobs):
                del self.jobs[i]
        self.check_vars = []
        self._refresh_queue(force=True)
        self._log(f"🗑 Đã xóa {len(indices)} job đã chọn.")

    def _retry_checked(self):
        """Retry (chạy lại) các job đã được check mà có status lỗi hoặc vi phạm cs."""
        indices = [i for i, v in enumerate(self.check_vars) if v.get()]
        if not indices:
            messagebox.showinfo("Không có", "Chưa chọn dòng nào."); return
        count = 0
        for i in indices:
            if i < len(self.jobs) and self.jobs[i]["status"] in ("lỗi", "vi phạm cs", "xong", "chờ"):
                self.jobs[i]["status"] = "chờ"
                count += 1
        # Bỏ chọn sau khi retry
        for v in self.check_vars: v.set(False)
        self._refresh_queue(force=True)
        self._log(f"↻ Retry {count} job đã chọn.")

    def _change_folder_checked(self):
        """Đổi thư mục output cho các job đã chọn."""
        indices = [i for i, v in enumerate(self.check_vars) if v.get()]
        if not indices:
            messagebox.showinfo("Không có", "Chưa chọn dòng nào."); return
        new_dir = filedialog.askdirectory(title="Chọn thư mục output mới")
        if not new_dir: return
        count = 0
        for i in indices:
            if i < len(self.jobs):
                old_name = os.path.basename(self.jobs[i]["out"])
                self.jobs[i]["out"] = os.path.join(new_dir, old_name)
                count += 1
        self._refresh_queue(force=True)
        self._log(f"📁 Đã đổi folder cho {count} job → {new_dir}")

    def _rename_checked(self):
        """Đổi tên file output cho các job đã chọn theo quy tắc đặt tên hiện tại."""
        indices = [i for i, v in enumerate(self.check_vars) if v.get()]
        if not indices:
            messagebox.showinfo("Không có", "Chưa chọn dòng nào."); return
        naming = self.opt_naming.get()
        existing_set = {self.jobs[i]["out"] for i in range(len(self.jobs)) if i not in set(indices)}
        count = 0
        for i in indices:
            if i >= len(self.jobs): continue
            j = self.jobs[i]
            out_dir = os.path.dirname(j["out"])
            if naming == "Đặt tên theo ảnh" and j.get("ref"):
                fn_base = os.path.splitext(os.path.basename(j["ref"]))[0]
                fn = clean_filename(fn_base)
            elif naming == "13 ký tự đầu prompt":
                fn = clean_filename(j["prompt"][:13])
            elif naming == "40 ký tự đầu chủ đề":
                topic_raw = self.ent_ai_topic.get("1.0", "end-1c").strip()
                first_topic = topic_raw.splitlines()[0].strip() if topic_raw else "video"
                fn = clean_filename(remove_vietnamese_accents(first_topic))[:40]
            else:  # Số thứ tự
                fn = f"{i+1:03d}"
            if not fn:
                fn = f"{i+1:03d}"
            fn = fn + ".mp4"
            new_out = get_unique_out_path(out_dir, fn, existing_set)
            existing_set.add(new_out)
            j["out"] = new_out
            count += 1
        self._refresh_queue(force=True)
        self._log(f"✏ Đã đổi tên {count} job theo '{naming}'")

    def _ensure_checked_accs_alive(self):
        """Tự động kiểm tra + re-login lấy lại cookie mới cho các tài khoản được chọn ('Dùng' = True) mà bị chết/hết hạn cookie."""
        dead_checked = [
            a for a in self.accounts 
            if a.get("enabled", True) 
            and a.get("role") != "donor" 
            and (not a.get("cookie") or str(a.get("status", "")).strip().lower() != "ok")
        ]
        if dead_checked:
            emails_str = ", ".join([a.get("email", "?") for a in dead_checked[:3]])
            if len(dead_checked) > 3: emails_str += "..."
            self._log(f"🔑 [Auto Recovery] Phát hiện {len(dead_checked)} tài khoản được chọn bị chết cookie [{emails_str}] ➔ Tự động re-login lấy cookie mới...")
            try:
                self._do_health_check()
            except Exception as ex:
                self._log(f"⚠️ [Auto Recovery] Lỗi health check: {ex}")

    def _start(self):
        if self._running: return
        enabled_accs = [a for a in self.accounts if a.get("enabled", True) and a.get("role") != "donor"]
        if not enabled_accs: messagebox.showwarning("Thiếu tài khoản", "Vào tab Tài khoản, tích chọn ít nhất 1 tài khoản."); return
        # Nếu có dòng đang được check → chỉ chạy các dòng đã check
        checked_indices = [i for i, v in enumerate(self.check_vars) if v.get()]
        if checked_indices:
            todo = [self.jobs[i] for i in checked_indices if i < len(self.jobs) and self.jobs[i]["status"] in ("chờ", "lỗi")]
            if not todo: messagebox.showinfo("Trống", "Các dòng đã chọn không có job chờ/lỗi."); return
            self._log(f"▶ Chạy {len(todo)} job đã chọn (từ {checked_indices[0]+1} đến {checked_indices[-1]+1})")
        else:
            todo = [j for j in self.jobs if j["status"] in ("chờ", "lỗi")]
            if not todo: messagebox.showinfo("Trống", "Không có job chờ."); return
        upload_per_acc = int(self.opt_upload_threads_per_acc.get())
        wpa = max(4, min(8, upload_per_acc))
        self._user_submit_max = float(wpa)
        # Chốt danh sách key Gemini cho phiên chạy (mỗi dòng 1 key) + reset key hỏng
        self._gemini_active = [l.strip() for l in self.txt_gemini.get("1.0", "end").splitlines() if l.strip()]
        self._gemini_bad = set()
        if self._gemini_active:
            self._log(f"🔑 Gemini: {len(self._gemini_active)} key — sẽ tự viết lại prompt vi phạm.")
        self._stop = False; self._running = True
        self.btn_run.configure(state="disabled")
        # ── Cache widget values trên Main Thread (tránh deadlock) ──
        self._cached_px_lines = [l.strip() for l in self.txt_proxy.get("1.0", "end").splitlines() if l.strip()]
        self._cached_use_laundering = self.use_laundering.get()
        self._cached_tg_enabled_run = self.tg_enabled.get()
        self._cached_remove_veo_wm = self.remove_veo_wm.get()
        self._cached_auto_concat = self.auto_concat.get()
        # Gắn mô tả giọng nói cố định vào engine (ưu tiên nhập tay, nếu trống → dùng preset Tiếng Việt)
        manual_voice = self.ent_voice_desc.get().strip()
        E.VOICE_DESC = manual_voice if manual_voice else E.get_voice_for_lang("vi")
        self._log(f"🎙 Giọng nói: {E.VOICE_DESC[:80]}{'…' if len(E.VOICE_DESC) > 80 else ''}")
        threading.Thread(target=self._run, args=(enabled_accs, todo, wpa), daemon=True).start()

    def _run(self, accs_placeholder, todo, wpa):
        accs = [a for a in self.accounts if a.get("cookie") and a.get("enabled", True) and a.get("role") != "donor"]
        if not accs:
            self._log("❌ Chưa chọn tài khoản nào (Vui lòng bật 'Dùng' trong tab Tài khoản).")
            self._running = False
            return
        """Mô hình veo3top: 1 HÀNG ĐỢI CHUNG + mỗi tài khoản chạy wpa worker, tất cả pull từ hàng đợi chung.
        Account throttle -> nghỉ (cooldown), account khác gánh; job requeue. Submit KHÔNG khóa/không sleep —
        poll inline tự giãn nhịp (worker bận ~60-90s/video), tận dụng render server-side song song."""
        try:
            # ---- Khởi động Token Farm nếu user chọn mode token_farm ----
            self._start_recaptcha_farm()

            # ---- Chuẩn bị auth từng tài khoản (refresh bearer từ cookie, không mở trình duyệt) ----
            # Cập nhật proxy pool từ cache (đã đọc trên main thread)
            # Auto HomeProxy: tải proxy tự động nếu bật
            # Cloudflare WARP (1.1.1.1) — ưu tiên cao nhất, dùng riêng WARP
            if self._warp_enabled.get():
                warp_port = int(self._warp_port.get().strip() or 40000)
                warp_str = f"socks5://127.0.0.1:{warp_port}"
                n_accs = len(accs)
                warp_lines = [f"{warp_str}#{i}" for i in range(n_accs)]
                self.proxy_pool.load(warp_lines)
                self._log(f"🌐 WARP 1.1.1.1 → tất cả {n_accs} TK dùng socks5://127.0.0.1:{warp_port}")
            elif self._auto_homeproxy.get() and self._homeproxy_token.get().strip():
                self._fetch_homeproxy()
            else:
                try:
                    if self._cached_px_lines:
                        self.proxy_pool.load(self._cached_px_lines)
                except Exception:
                    pass
            self._log(f"🔑 Chuẩn bị {len(accs)} tài khoản chính...")
            states = []
            for a in accs:
                st = AccountState(a, submit_max=self._user_submit_max)
                # Gán proxy từ pool (nếu có)
                if self.proxy_pool.has_proxies():
                    px = self.proxy_pool.assign(st.email)
                    if px:
                        st.proxy = self.proxy_pool.get_dict(st.email)
                states.append(st)
                px_info = st.proxy.get('https', 'Không proxy') if st.proxy else 'Không proxy'
                self._log(f"  ✅ {st.email[:20]} sẵn sàng | Proxy: {px_info}")
            if not states:
                self._log("❌ Không tài khoản dùng được."); return
            self._pool_states = states   # cho panel trạng thái pool đọc (live)
            self.after(0, self._update_proxy_stats)

            # ── Donor pool: TK rác chỉ dùng bypass upload 429 (role="donor", KHÔNG tích chọn) ──
            self._donor_states = []
            if self._cached_use_laundering:
                donor_accs = [a for a in self.accounts
                              if a.get("role") == "donor" and a.get("cookie") and a.get("status") == "ok"]
                for da in donor_accs:
                    ds = AccountState(da)
                    if self.proxy_pool.has_proxies():
                        px = self.proxy_pool.assign(ds.email)
                        if px:
                            ds.proxy = self.proxy_pool.get_dict(ds.email)
                    # Reset project cho donor
                    new_proj = E.reset_project(ds.cookie, proxy=ds.proxy)
                    if new_proj:
                        ds.project = new_proj
                        self._log(f"  🗑️→📁 Donor {ds.email[:20]}: reset project → {new_proj[:12]}...")
                    if ds.ensure_auth(force=True):
                        self._donor_states.append(ds)
                        self._log(f"  🎁 Donor: {ds.email[:20]} sẵn sàng (project {str(ds.project)[:8]})")
                if self._donor_states:
                    self._log(f"🛡️ {len(self._donor_states)} donor bypass 429 sẵn sàng")

            total = len(states) * wpa
            self._log(f"🚀 {len(states)} tài khoản × {wpa} luồng = {total} luồng. Bắt đầu {len(todo)} job.")

            # mốc để tính tốc độ (video/phút) + ước tính thời gian hoàn thành
            self._run_t0 = time.time()
            self._eta_jobs = todo
            self._run_done0 = sum(1 for j in todo if j["status"] == "xong")
            self._done_timestamps = collections.deque()   # ghi timestamp mỗi video xong → tính tốc độ trượt 10 phút

            # Trần upload toàn cục = 4 luồng (Rule 9.5) — tối ưu chạy 24/7, tránh bị Google
            # đánh dấu IP. Giới hạn per-account do st.acquire_upload() phụ trách.
            n_upload_threads = 4
            upload_sem = threading.Semaphore(n_upload_threads)
            jobq = queue.Queue()
            for j in todo:
                j["_cycles"] = 0
                jobq.put(j)
            done_flag = [False]

            # ── Periodic Telegram Report (mỗi 1h) ──
            last_tg_report = [time.time()]
            TG_INTERVAL = 3600  # 1 giờ
            def _tg_periodic():
                while not done_flag[0] and not self._stop:
                    time.sleep(60)
                    if time.time() - last_tg_report[0] >= TG_INTERVAL and self._cached_tg_enabled_run:
                        last_tg_report[0] = time.time()
                        msg = self._build_telegram_stats()
                        self._send_telegram(msg)
            threading.Thread(target=_tg_periodic, daemon=True).start()

            def process(st, job):
                """Trả 'success' | 'retry_soft' (đổi account) | ('fail', reason)."""
                if not st.ensure_auth():
                    st.rest(AUTH_REST, "auth"); return "retry_soft"
                bearer, project, cookie = st.bearer, st.project, st.cookie
                seed = (abs(hash(job["prompt"])) % 900000) + 1
                aspect, model = job["aspect"], job["model"]

                # 1) Upload ảnh reference (I2V) -> media_id, cache theo account (khỏi upload lại khi retry)
                ref_mid = None
                if job["type"] == "i2v" and job.get("ref"):
                    if not os.path.exists(job["ref"]):
                        return ("fail", "noimg")   # ảnh gốc không đọc được (ổ rời rút / file bị xóa) -> bỏ gọn, KHÔNG retry
                    with st.lock:
                        ref_mid = st.refcache.get(job["ref"])
                    if not ref_mid:
                        # Giới hạn upload đồng thời của RIÊNG tài khoản này (Rule 9.5) —
                        # trước đây tab này bỏ qua acquire_upload nên upload_threads không có tác dụng.
                        if not st.acquire_upload(lambda: self._stop):
                            return "retry_soft"
                        try:
                            st.wait_upload_spacing(10.0)  # giãn cách 10s giữa các lần upload cùng 1 TK
                            upload_sem.acquire()
                            try:
                                ref_mid = E.upload_image(bearer, project, job["ref"], proxy=st.proxy)
                            finally:
                                upload_sem.release()
                        finally:
                            st.release_upload()
                        if ref_mid == "proxy_dead":
                            new_px = self.proxy_pool.mark_dead(st.email)
                            st.proxy = self.proxy_pool.get_dict(st.email) if new_px else None
                            self._log(f"  🔄 {st.email[:16]}: proxy chết khi upload → {'đổi proxy mới' if new_px else 'hết proxy, dùng IP máy'}")
                            return "retry_soft"
                        if ref_mid == "net_fail":
                            # Kết nối bị cắt / TLS rác / timeout → requeue, KHÔNG đánh lỗi job
                            self._log(f"  🌐 {st.email[:16]}: lỗi mạng khi upload ảnh → trả job về hàng đợi")
                            return "retry_soft"
                        if ref_mid == "forbidden":
                            # Account bị cấm upload ảnh → đánh dấu i2v_blocked, chuyển job sang account khác
                            st.i2v_blocked = True
                            self._log(f"  🚫 {st.email[:16]}: bị cấm upload ảnh (403) — chỉ chạy T2V, I2V chuyển account khác.")
                            return "retry_soft"
                        if ref_mid == "throttle":
                            # Upload bị 429 → thử BYPASS qua donor trước khi requeue
                            st.on_throttle()
                            if self._donor_states and self.use_laundering.get():
                                donors_copy = list(self._donor_states)
                                random.shuffle(donors_copy)
                                for donor_st in donors_copy:
                                    if donor_st.ensure_auth():
                                        self._log(f"  🔄 {st.email[:16]}: 429 → bypass qua donor {donor_st.email[:16]}...")
                                        ref_mid = E.upload_image_via_donor(
                                            donor_st.bearer, donor_st.project,
                                            bearer, project, job["ref"],
                                            proxy=donor_st.proxy,
                                            main_proxy=st.proxy,
                                        )
                                        if ref_mid and ref_mid not in ("throttle", "forbidden"):
                                            self._log(f"  ✅ Bypass thành công! [{donor_st.email[:16]}]")
                                            st.on_upload_ok()  # reset streak vì bypass OK
                                            with st.lock:
                                                st.refcache[job["ref"]] = ref_mid
                                            break
                                        ref_mid = None  # reset để thử donor tiếp
                            # Nếu bypass thất bại hoặc không có donor → rotate proxy + requeue
                            if not ref_mid or ref_mid in ("throttle", "forbidden"):
                                ref_mid = None
                                new_px, old_px = self.proxy_pool.rotate(st.email)
                                if new_px:
                                    st.proxy = self.proxy_pool.get_dict(st.email)
                                    self._log(f"  🔄 {st.email[:16]}: upload 429 → đổi proxy")
                                elif st.should_log_throttle():
                                    self._log(f"  ⏳ {st.email[:16]}: upload 429 — giảm tốc (không có proxy khác)")
                                rest_s = st.on_upload_throttle()
                                self._log(f"  😴 {st.email[:16]}: nghỉ {rest_s}s (lần {st.upload_throttle_streak}) do upload 429")
                                return "retry_soft"
                        if ref_mid == "unauthorized" or (not ref_mid and st.ensure_auth(force=True)):
                            # 401 -> refresh bearer + thử lại 1 lần
                            if not st.ensure_auth(force=True):
                                return "retry_soft"
                            bearer, project = st.bearer, st.project
                            if not st.acquire_upload(lambda: self._stop):
                                return "retry_soft"
                            try:
                                st.wait_upload_spacing(10.0)
                                upload_sem.acquire()
                                try:
                                    ref_mid = E.upload_image(bearer, project, job["ref"], proxy=st.proxy)
                                finally:
                                    upload_sem.release()
                            finally:
                                st.release_upload()
                            if ref_mid == "proxy_dead":
                                new_px = self.proxy_pool.mark_dead(st.email)
                                st.proxy = self.proxy_pool.get_dict(st.email) if new_px else None
                                self._log(f"  🔄 {st.email[:16]}: proxy chết khi upload (retry) → {'đổi proxy mới' if new_px else 'hết proxy, dùng IP máy'}")
                                return "retry_soft"
                            if ref_mid in ("net_fail", "unauthorized"):
                                self._log(f"  🌐 {st.email[:16]}: upload ảnh thất bại ({ref_mid}) → trả job về hàng đợi")
                                return "retry_soft"
                            if ref_mid == "forbidden":
                                st.i2v_blocked = True
                                self._log(f"  🚫 {st.email[:16]}: bị cấm upload ảnh (403) — chỉ chạy T2V, I2V chuyển account khác.")
                                return "retry_soft"
                            if ref_mid == "throttle":
                                st.on_throttle()
                                # Thử BYPASS qua donor (lần retry thứ 2)
                                if self._donor_states and self.use_laundering.get():
                                    donors_copy = list(self._donor_states)
                                    random.shuffle(donors_copy)
                                    for donor_st in donors_copy:
                                        if donor_st.ensure_auth():
                                            self._log(f"  🔄 {st.email[:16]}: 429 (retry) → bypass qua donor {donor_st.email[:16]}...")
                                            ref_mid = E.upload_image_via_donor(
                                                donor_st.bearer, donor_st.project,
                                                bearer, project, job["ref"],
                                                proxy=donor_st.proxy,
                                                main_proxy=st.proxy,
                                            )
                                            if ref_mid and ref_mid not in ("throttle", "forbidden"):
                                                self._log(f"  ✅ Bypass thành công! [{donor_st.email[:16]}]")
                                                st.on_upload_ok()
                                                with st.lock:
                                                    st.refcache[job["ref"]] = ref_mid
                                                break
                                            ref_mid = None
                                if not ref_mid or ref_mid in ("throttle", "forbidden"):
                                    ref_mid = None
                                    new_px, old_px = self.proxy_pool.rotate(st.email)
                                    if new_px:
                                        st.proxy = self.proxy_pool.get_dict(st.email)
                                        self._log(f"  🔄 {st.email[:16]}: upload 429 → đổi proxy")
                                    elif st.should_log_throttle():
                                        self._log(f"  ⏳ {st.email[:16]}: upload 429 — giảm tốc (không có proxy khác)")
                                    rest_s = st.on_upload_throttle()
                                    self._log(f"  😴 {st.email[:16]}: nghỉ {rest_s}s (lần {st.upload_throttle_streak}) do upload 429")
                                    return "retry_soft"
                        if not ref_mid or E.is_net_retryable(ref_mid):
                            self._log(f"  🌐 {st.email[:16]}: upload ảnh không thành công ({ref_mid or 'rỗng'}) → trả job về hàng đợi")
                            return "retry_soft"
                        # Upload OK → reset streak 429. THIẾU dòng này khiến upload_throttle_streak
                        # chỉ tăng mà không bao giờ về 0: TK nghỉ leo thang tới 90s/lần và bị
                        # acquire_submit ép tốc độ về 4 vĩnh viễn dù đã upload được bình thường.
                        st.on_upload_ok()
                        with st.lock:
                            st.refcache[job["ref"]] = ref_mid

                # 2) Generate — cổng submit THÍCH ỨNG & Lock per-account (Rule #2), phân loại lỗi để xử lý ĐÚNG
                for attempt in range(GEN_ATTEMPTS):
                    if self._stop: return "retry_soft"
                    # Cổng submit THÍCH ỨNG & Lock per-account giữ khóa độc quyền giãn cách 4-6s (Rule #2)
                    if not st.acquire_submit(lambda: self._stop):
                        return "retry_soft"
                    try:
                        with st.submit_guard(4.0, 6.0):
                            kind, ops = E.submit_video(bearer, project, job["prompt"], seed, aspect, model, ref_mid, proxy=st.proxy)
                    finally:
                        st.release_submit()
                    if kind == "ok":
                        st.on_submit_ok()                         # trót lọt -> nới dần tốc độ (AIMD +)
                        pk, mid, _ = E.poll_video(bearer, ops, cookie=cookie, max_attempts=POLL_MAX, interval=8, proxy=st.proxy)
                        if pk == "done":
                            n = E.download_video(mid, cookie, job["out"], proxy=st.proxy)
                            if n == E.DL_PROXY_DEAD:
                                new_px = self.proxy_pool.mark_dead(st.email)
                                st.proxy = self.proxy_pool.get_dict(st.email) if new_px else None
                                self._log(f"  🔄 {st.email[:16]}: proxy chết khi tải video → {'đổi proxy mới' if new_px else 'hết proxy, dùng IP máy'}")
                                return "retry_soft"
                            if n == E.DL_NET_FAIL:
                                self._log(f"  🌐 {st.email[:16]}: lỗi mạng khi tải video → trả job về hàng đợi")
                                return "retry_soft"
                            if n <= 0:                          # tải hụt -> thử lại vài lần (refresh cookie nếu cần)
                                for _ in range(4):
                                    if self._stop: return "retry_soft"
                                    time.sleep(3); n = E.download_video(mid, cookie, job["out"], proxy=st.proxy)
                                    if n > 0: break
                                    if n in (E.DL_PROXY_DEAD, E.DL_NET_FAIL):
                                        return "retry_soft"
                            if n > 0:
                                if self._cached_remove_veo_wm:
                                    try:
                                        import shopeevideo
                                        shopeevideo.remove_veo_watermark(job["out"], log=self._log)
                                    except Exception as ex:
                                        self._log(f"  ⚠️ Lỗi xóa logo Veo: {ex}")
                                self._log(f"  ✅ {os.path.basename(job['out'])} ({n//1024}KB) [{st.email[:16]}]")
                                return "success"
                            return ("fail", "tải video lỗi")
                        elif pk == "failed":
                            m = mid or ""
                            # 1) AUDIO_FILTERED: lỗi do prompt → dùng Gemini viết lại rồi retry
                            if "AUDIO_FILTERED" in m.upper():
                                if self._gemini_active and job.get("_rewrites", 0) < MAX_REWRITES:
                                    new = self._rewrite_prompt(job["prompt"])
                                    if new and new.strip() != job["prompt"].strip():
                                        job["_rewrites"] = job.get("_rewrites", 0) + 1
                                        self._log(f"  ✏️ Viết lại prompt vi phạm (lần {job['_rewrites']}) -> thử lại: {new[:40]}…")
                                        job["prompt"] = new
                                        return "retry_soft"   # requeue, làm lại với prompt mới
                                # Hết lượt rewrite → lỗi thường (nút Xóa Vi Phạm CS KHÔNG xóa)
                                self._log(f"  ⚠️ Prompt vi phạm (hết lượt rewrite): {job['prompt'][:30]} ({m})")
                                return ("fail", m or "render fail")
                            # 2) Lỗi nội dung/ảnh → vi phạm cs (nút Xóa Vi Phạm CS sẽ xóa)
                            if E.is_policy_reason(m):
                                self._log(f"  ⚠️ Vi phạm chính sách: {job['prompt'][:30]} ({m})")
                                return ("fail", "policy")
                            # 3) Render quá lâu, không rõ lý do → cho requeue thử tài khoản khác
                            if m == "timeout":
                                self._log(f"  ⏱ Render quá lâu (không rõ lý do): {job['prompt'][:30]} → thử lại")
                                return "retry_soft"
                            # 4) Các lỗi render khác
                            self._log(f"  ❌ render fail: {job['prompt'][:30]} ({m})")
                            return ("fail", m or "render fail")
                        elif pk == "auth":
                            if st.ensure_auth(force=True): bearer = st.bearer
                            continue
                        else:  # timeout
                            return ("fail", "render timeout")
                    elif kind == "auth":
                        if attempt == 0 and st.ensure_auth(force=True):
                            bearer, project = st.bearer, st.project; continue
                        st.rest(AUTH_REST, "auth")
                        self._log(f"  🔒 {st.email[:16]} 401 -> nghỉ {AUTH_REST//60}p, đổi tài khoản.")
                        return "retry_soft"
                    elif kind == "throttle":
                        st.on_throttle()
                        if self.proxy_pool and self.proxy_pool.has_proxies():
                            new_px, old_px = self.proxy_pool.rotate(st.email)
                            if new_px:
                                st.proxy = self.proxy_pool.get_dict(st.email)
                                if st.rest_remaining() > 15:
                                    st.rest(15, "submit_throttle")
                                self._log(f"  🔄 {st.email[:16]}: Submit 429 → Tự động xoay Proxy mới ({st.rest_remaining():.0f}s làm mát)...")
                        if st.rest_remaining() > 0 and st.should_log_throttle():
                            self._log(f"  ⏳ {st.email[:16]}: 429 — nghỉ {st.rest_remaining():.0f}s hạ nhiệt.")
                            time.sleep(min(3.0, st.rest_remaining()))
                    elif kind == "quota_hard":
                        # HẾT QUOTA THẬT (reason quota/credit/daily) -> cách ly DÀI + đổi account (grind vô ích).
                        st.rest(QUOTA_HARD_REST, "quota")
                        self._log(f"  ⛔ {st.email[:16]} HẾT QUOTA -> cách ly {_dur_label(QUOTA_HARD_REST)}, đổi tài khoản.")
                        return "retry_soft"
                    elif kind in ("ratelimit", "ip_block"):
                        st.on_throttle()
                        new_px, old_px = self.proxy_pool.rotate(st.email)
                        if new_px:
                            st.proxy = self.proxy_pool.get_dict(st.email)
                            self._log(f"  🔄 {st.email[:16]}: IP block/rate → đổi proxy")
                        elif st.should_log_throttle():
                            self._log(f"  🌐 {st.email[:16]}: 429 rate theo IP — giảm tốc (không có proxy khác)")
                        time.sleep(1.5 + random.uniform(0, 1.0))
                    else:  # unusual / retry -> bypass trượt lượt, thử lại NHANH
                        time.sleep(BYPASS_QUICK + random.uniform(0, 0.4))
                return "retry_soft"   # hết lượt thử -> trả job về hàng đợi (không đổ lỗi account)

            def worker(st, initial_delay=0.0):
                if initial_delay > 0:
                    time.sleep(initial_delay + random.uniform(0.1, 0.4))
                while not self._stop:
                    if not st.acc.get("enabled", True):
                        time.sleep(1); continue
                    w = st.rest_remaining()
                    if w > 0:
                        time.sleep(min(w, 3)); continue        # account đang nghỉ -> không pull job
                    if not st.ensure_auth():
                        time.sleep(2); continue
                    with st.blk:
                        if st.busy >= st.get_current_max_busy():
                            time.sleep(0.5); continue
                    try:
                        job = jobq.get(timeout=2)
                    except queue.Empty:
                        if done_flag[0]: return
                        continue
                    # Account bị cấm upload ảnh → bỏ qua job I2V, trả về hàng đợi cho account khác
                    if st.i2v_blocked and job.get("type") == "i2v" and job.get("ref"):
                        jobq.put(job)
                        time.sleep(0.5)         # tránh busy-loop nếu chỉ còn job I2V
                        continue
                    if job.get("status") == "xong":
                        continue
                    if os.path.exists(job["out"]):
                        job["status"] = "xong"; self.after(0, self._refresh_queue); continue
                    job["_cycles"] = job.get("_cycles", 0) + 1
                    if job["_cycles"] > JOB_MAX_CYCLES:
                        job["status"] = "lỗi"; self.after(0, self._refresh_queue); continue
                    job["status"] = "đang"; self.after(0, self._refresh_queue)
                    st.busy_inc()
                    try:
                        outcome = process(st, job)
                    except Exception as e:
                        self._log(f"  ❌ Lỗi bất ngờ [{job['prompt'][:30]}]: {e}")
                        outcome = ("fail", str(e))
                    finally:
                        st.busy_dec()
                    if outcome == "success":
                        job["status"] = "xong"; st.wins += 1; st.clear_rest()
                        ts_deque = getattr(self, "_done_timestamps", None)
                        if ts_deque is not None: ts_deque.append(time.time())
                    elif outcome == "retry_soft":
                        job["status"] = "chờ"; jobq.put(job)   # requeue -> account SỐNG khác nhặt
                    else:
                        st.fails += 1
                        reason = outcome[1] if isinstance(outcome, tuple) and len(outcome) > 1 else "lỗi"
                        if reason == "policy":
                            job["status"] = "vi phạm cs"        # vi phạm chính sách -> không retry
                        elif reason == "noimg":
                            job["status"] = "lỗi"; job["_noretry"] = True   # thiếu ảnh gốc -> không retry vô ích
                        else:
                            job["status"] = "lỗi"
                    self.after(0, self._refresh_queue)

            threads = []
            for acc_idx, st in enumerate(states):
                stagger_delay = acc_idx * 0.8
                for _ in range(st.max_busy):
                    t = threading.Thread(target=worker, args=(st, stagger_delay), daemon=True)
                    t.start(); threads.append(t)

            def _drain():
                while not self._stop:
                    if all(j["status"] in ("xong", "lỗi", "vi phạm cs") for j in todo):
                        return
                    time.sleep(1.5)

            # Chờ tới khi mọi job kết thúc (xong/lỗi/vi phạm) hoặc user bấm Dừng
            _drain()

            # TỰ RETRY job lỗi sau khi chạy xong (bỏ qua vi phạm cs + thiếu ảnh — retry vô ích).
            for rnd in range(AUTO_RETRY_ROUNDS):
                if self._stop:
                    break
                retry = [j for j in todo if j["status"] == "lỗi" and not j.get("_noretry")]
                if not retry:
                    break
                self._log(f"↻ Tự retry {len(retry)} job lỗi (vòng {rnd+1}/{AUTO_RETRY_ROUNDS})...")
                for j in retry:
                    j["status"] = "chờ"; j["_cycles"] = 0; jobq.put(j)   # worker vẫn sống -> nhặt lại
                self.after(0, lambda: self._refresh_queue(force=True))
                _drain()

            done_flag[0] = True
            for t in threads:
                t.join(timeout=5)

            done = sum(1 for j in todo if j["status"] == "xong")
            err = sum(1 for j in todo if j["status"] == "lỗi")
            noimg = sum(1 for j in todo if j["status"] == "lỗi" and j.get("_noretry"))
            elapsed = time.time() - self._run_t0
            elapsed_str = _dur_label(elapsed)
            msg = (f"🎉 XONG hàng đợi. Thành công {done}/{len(todo)} · lỗi {err}"
                      + (f" (trong đó {noimg} thiếu ảnh gốc)" if noimg else "")
                      + (" (đã dừng)" if self._stop else "") + f" · ⏱ {elapsed_str}.")
            self._log(msg)
            acc_lines = []
            for st in states:
                line = f"   [{st.email[:20]}] xong {st.wins} · lỗi {st.fails}"
                self._log(line)
                acc_lines.append(line)

            # ── Telegram Report ──
            if self._cached_tg_enabled_run:
                tg_msg = f"📊 Video Report\n{'='*30}\n{msg}\n" + "\n".join(acc_lines)
                self._send_telegram(tg_msg)
            # ── Auto-Concat: ghép video thành 1 file khi xong ──
            if self._cached_auto_concat and done >= 2:
                self._auto_concat(todo)
            self.after(0, lambda: self._refresh_queue(force=True))
        except Exception:
            self._log("LỖI: " + traceback.format_exc())
        finally:
            self._running = False
            self.after(0, lambda: self.btn_run.configure(state="normal"))

    def _auto_concat(self, todo):
        """Tự ghép các clip vừa tạo xong thành 1 file video_final.mp4. Hỗ trợ tự sinh voiceover & vietsub, tự động gom theo thư mục để chạy resume."""
        import subprocess, tempfile
        from collections import defaultdict
        
        # Gom tất cả job có trạng thái xong và file thực sự tồn tại từ self.jobs (để hỗ trợ resume các job bị lỗi)
        jobs_by_dir = defaultdict(list)
        for j in self.jobs:
            if j.get("status") == "xong" and j.get("out") and os.path.exists(j["out"]):
                out_dir = os.path.abspath(os.path.dirname(j["out"]))
                jobs_by_dir[out_dir].append(j)

        # Duyệt qua từng thư mục chứa các clip thành phẩm để tiến hành ghép nối
        for out_dir, done_jobs in jobs_by_dir.items():
            if len(done_jobs) < 2:
                continue
                
            # Sắp xếp các job trong thư mục này theo tên file để đúng thứ tự phân cảnh (001, 002...)
            done_jobs = sorted(done_jobs, key=lambda x: x["out"])
            clips = [j["out"] for j in done_jobs]
            folder_name = os.path.basename(out_dir)
            if folder_name and folder_name.lower() not in ("fbvideo", "video", "output", "out", "temp"):
                final = os.path.join(out_dir, f"{folder_name}.mp4")
            else:
                final = os.path.join(out_dir, "video_final.mp4")
            
            # Thử xóa file cũ để ghi đè, tránh người dùng xem nhầm file cũ có 2 giọng nói
            if os.path.exists(final):
                try:
                    os.unlink(final)
                except Exception:
                    # Nếu file bị khóa (đang phát), ta mới fallback sang đánh số
                    cnt = 1
                    base_final = os.path.splitext(final)[0]
                    while os.path.exists(final):
                        final = f"{base_final}_{cnt}.mp4"
                        cnt += 1

            # Kiểm tra xem có thuyết minh (voice) hay không
            has_voice = any(j.get("voice") for j in done_jobs)
            
            if has_voice:
                try:
                    import auto_voice_sub
                    self._log(f"🎙️ Phát hiện thuyết minh trong thư mục: {os.path.basename(out_dir)}! Khởi động hậu kỳ...")
                    
                    # 1) Tự động sinh file audio thuyết minh (.mp3) bằng edge-tts cho từng cảnh
                    voice_audios = []
                    voice_texts = []
                    valid = True
                    
                    for idx, j in enumerate(done_jobs):
                        v_text = j.get("voice", "").strip()
                        if not v_text:
                            v_text = " "  
                        
                        v_audio = os.path.join(tempfile.gettempdir(), f"temp_voice_{idx}.mp3")
                        ok, err_msg = auto_voice_sub.make_voice_file(v_text, v_audio, voice="vi-VN-NamMinhNeural")
                        if ok:
                            voice_audios.append(v_audio)
                            voice_texts.append(v_text)
                        else:
                            valid = False
                            self._log(f"⚠️ Không thể sinh voice cho phân cảnh {idx+1}. Chi tiết: {err_msg}")
                            break
                    
                    if not valid:
                        self._log("⚠️ Tiến trình tạo giọng nói thất bại, hủy bỏ làm video hoàn chỉnh.")
                        continue
                    
                    # 2) Quét tìm nhạc nền (.mp3/.wav) tự động trong thư mục output (bỏ qua file temp_voice)
                    bgm_path = None
                    bgms = [os.path.join(out_dir, f) for f in os.listdir(out_dir) 
                            if f.lower().endswith(('.mp3', '.wav')) and not os.path.basename(f).startswith("temp_voice_")]
                    if bgms:
                        bgm_path = bgms[0]
                        self._log(f"🎵 Tìm thấy nhạc nền tự động: {os.path.basename(bgm_path)}")
                    
                    # 3) Gọi build video hoàn chỉnh (Chạy trong thread riêng để không treo UI)
                    def _do_build(c_list=clips, va_list=voice_audios, vt_list=voice_texts, out_p=final, bp=bgm_path):
                        try:
                            success = auto_voice_sub.build_final_video(
                                clips=c_list,
                                voice_audios=va_list,
                                voice_texts=vt_list,
                                output_path=out_p,
                                bgm_path=bp,
                                bgm_volume=0.15,
                                log_cb=self._log
                            )
                            # Dọn dẹp các file audio voice tạm
                            for path in va_list:
                                try:
                                    if os.path.exists(path):
                                        os.unlink(path)
                                except Exception:
                                    pass
                            
                            if success:
                                size_mb = os.path.getsize(out_p) / (1024 * 1024)
                                self.after(0, lambda: self._log(f"🎉 Hoàn thành video lồng tiếng & phụ đề: {os.path.basename(out_p)} ({size_mb:.1f} MB)"))
                                # Xóa các clip thành phần sau khi ghép thành công
                                for c in c_list:
                                    try:
                                        if os.path.exists(c):
                                            os.unlink(c)
                                    except Exception as ex:
                                        self.after(0, lambda c_name=os.path.basename(c), e=ex: self._log(f"⚠️ Không thể xóa clip thành phần {c_name}: {e}"))
                        except Exception as ex:
                            self.after(0, lambda: self._log(f"⚠️ Hậu kỳ video lỗi: {ex}"))
                            
                    threading.Thread(target=_do_build, daemon=True).start()
                    
                except Exception as e:
                    self._log(f"⚠️ Lỗi khởi tạo hậu kỳ tự động: {e}")
            else:
                # Fallback về ghép nối đơn giản (không voice, không sub, không re-encode)
                self._log(f"🔗 Ghép nối nhanh các clip trong thư mục: {os.path.basename(out_dir)}...")
                try:
                    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as lf:
                        for c in clips:
                            lf.write(f"file '{c.replace(os.sep, '/')}'\n")
                        list_path = lf.name
                    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", final]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    os.unlink(list_path)
                    if result.returncode == 0 and os.path.exists(final):
                        size_mb = os.path.getsize(final) / (1024 * 1024)
                        self._log(f"🔗 Đã ghép {len(clips)} clip → {os.path.basename(final)} ({size_mb:.1f} MB)")
                        # Xóa các clip thành phần sau khi ghép thành công
                        for c in clips:
                            try:
                                if os.path.exists(c):
                                    os.unlink(c)
                            except Exception as ex:
                                self._log(f"⚠️ Không thể xóa clip thành phần {os.path.basename(c)}: {ex}")
                    else:
                        self._log(f"⚠️ Ghép video lỗi: {result.stderr[:200] if result.stderr else 'unknown'}")
                except Exception as e:
                    self._log(f"⚠️ Ghép video lỗi: {e}")

    # ============ TAB TẠO VIDEO SHOPEE v3 ============
    def _build_shopee(self):
        f = ctk.CTkFrame(self.content, fg_color=BG); self.frames["shopee"] = f
        # Header
        hdr = ctk.CTkFrame(f, fg_color="#EE4D2D", corner_radius=12); hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="🛒 Tạo Video Shopee v3", font=("", 18, "bold"), text_color="#fff").pack(side="left", padx=20, pady=14)
        self._shopee_status = ctk.CTkLabel(hdr, text="Sẵn sàng", font=("", 12), text_color="#FFD3C7")
        self._shopee_status.pack(side="right", padx=20)

        # --- Cài đặt ---
        cfg = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); cfg.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(cfg, text="⚙ Cài đặt", font=("", 13, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(10, 4))

        # Row 1: Tỉ lệ + Khung cảnh + Độ dài
        row1 = ctk.CTkFrame(cfg, fg_color="transparent"); row1.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(row1, text="Tỉ lệ:", font=("", 12)).pack(side="left")
        self._sp_aspect = ctk.CTkOptionMenu(row1, values=list(E.VID_ASPECTS.keys()), width=150)
        self._sp_aspect.pack(side="left", padx=(4, 12))
        self._sp_aspect.set(self.settings.get("shopee_aspect", "Dọc 9:16 (TikTok)"))

        scene_opts = SV.SCENE_OPTIONS if SV else ["🎲 Random", "📦 Tổng kho hàng hóa"]
        ctk.CTkLabel(row1, text="Khung cảnh:", font=("", 12)).pack(side="left")
        self._sp_scene = ctk.CTkOptionMenu(row1, values=scene_opts, width=200)
        self._sp_scene.pack(side="left", padx=(4, 12))
        self._sp_scene.set(self.settings.get("shopee_scene", "🎲 Random"))

        dur_opts = ["8s"] + (SV.DURATION_OPTIONS if SV else ["16s", "24s"])
        ctk.CTkLabel(row1, text="Độ dài:", font=("", 12)).pack(side="left")
        self._sp_duration = ctk.CTkOptionMenu(row1, values=dur_opts, width=80,
                                               command=lambda v: self._sp_on_duration_change())
        self._sp_duration.pack(side="left", padx=(4, 12))
        self._sp_duration.set(self.settings.get("shopee_duration", "16s"))

        lang_opts = SV.LANG_OPTIONS if SV else ["Tiếng Anh", "Tiếng Việt"]
        ctk.CTkLabel(row1, text="Ngôn ngữ:", font=("", 12)).pack(side="left")
        self._sp_lang = ctk.CTkOptionMenu(row1, values=lang_opts, width=110)
        self._sp_lang.pack(side="left", padx=(4, 0))
        self._sp_lang.set(self.settings.get("shopee_lang", "Tiếng Việt"))

        # Row 1b: Model
        row1b_sp = ctk.CTkFrame(cfg, fg_color="transparent"); row1b_sp.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(row1b_sp, text="🤖 Model:", font=("", 12)).pack(side="left")
        self._sp_model = ctk.CTkOptionMenu(row1b_sp, values=list(E.VID_MODELS.keys()), width=220,
                                            command=lambda v: self._sp_on_model_change())
        self._sp_model.pack(side="left", padx=(4, 12))
        self._sp_model.set(self.settings.get("shopee_model", "Veo 3.1 (miễn phí)"))

        self._sp_remove_wm = ctk.BooleanVar(value=self.settings.get("shopee_remove_wm", True))
        ctk.CTkCheckBox(row1b_sp, text="🧹 Xóa logo", variable=self._sp_remove_wm,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(12, 0))

        self._sp_skip_img = ctk.BooleanVar(value=self.settings.get("shopee_skip_img", False))
        ctk.CTkCheckBox(row1b_sp, text="⏭ Bỏ qua SP đã có ảnh", variable=self._sp_skip_img,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(12, 0))

        # Row 1.5: Review Style Config
        row1_5 = ctk.CTkFrame(cfg, fg_color="transparent"); row1_5.pack(fill="x", padx=12, pady=(4, 0))
        ctk.CTkLabel(row1_5, text="Kiểu Review:", font=("", 12)).pack(side="left")
        self._sp_review_style = ctk.StringVar(value=self.settings.get("shopee_review_style", "🎲 Random"))
        style_opts = ["🎲 Random", "Review tự nhiên", "Ngồi Review", "POV (Góc nhìn thứ nhất)", "Unboxing", "UGC Authentic", "Demo Công Dụng", "So Sánh/Đánh Giá"]
        self._sp_style_menu = ctk.CTkOptionMenu(row1_5, values=style_opts, variable=self._sp_review_style, width=200)
        self._sp_style_menu.pack(side="left", padx=(4, 12))

        # AI Prompt
        ctk.CTkLabel(row1_5, text="AI Prompt:", font=("", 12)).pack(side="left")
        self._sp_ai_prompt = ctk.CTkOptionMenu(
            row1_5,
            values=["Gemini", "Groq", "Prompt A + B"],
            width=150
        )
        self._sp_ai_prompt.pack(side="left", padx=(4, 6))
        saved_sp_ai = self.settings.get("shopee_ai_prompt", "Prompt A + B")
        if saved_sp_ai == "Template (mặc định)": saved_sp_ai = "Prompt A + B"
        self._sp_ai_prompt.set(saved_sp_ai)

        ctk.CTkButton(
            row1_5,
            text="🧪 Test prompt",
            command=self._sp_test_prompt,
            fg_color="#5C6BC0",
            hover_color="#3949AB",
            height=28,
            width=100,
            font=("", 11)
        ).pack(side="left", padx=(0, 12))

        self._sp_use_laundering = ctk.BooleanVar(value=self.settings.get("shopee_use_laundering", False))
        self._sp_chk_laundering = ctk.CTkCheckBox(row1_5, text="Rửa ảnh (Bypass 429)", variable=self._sp_use_laundering, font=("", 11), checkbox_width=18, checkbox_height=18)
        self._sp_chk_laundering.pack(side="left", padx=(4, 12))

        self._sp_del_img = ctk.BooleanVar(value=self.settings.get("shopee_del_img", True))
        ctk.CTkCheckBox(row1_5, text="🗑 Xóa ảnh khi tạo xong", variable=self._sp_del_img,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(0, 12))

        self._sp_ghep_anh = ctk.BooleanVar(value=self.settings.get("shopee_ghep_anh", False))
        self._sp_chk_ghep_anh = ctk.CTkCheckBox(row1_5, text="🎞 Ghép ảnh (12s)", variable=self._sp_ghep_anh,
                                                 font=("", 11), checkbox_width=18, checkbox_height=18)
        self._sp_chk_ghep_anh.pack(side="left", padx=(0, 12))

        # Khởi tạo trạng thái model + duration
        self._sp_on_model_change()

        # Row 2: Thư mục người mẫu & Thư mục lưu
        row2 = ctk.CTkFrame(cfg, fg_color="transparent"); row2.pack(fill="x", padx=12, pady=(4, 10))
        
        # --- Phần Người mẫu ---
        ctk.CTkLabel(row2, text="👤 Người mẫu:", font=("", 12)).pack(side="left")
        self._sp_model_dir = ctk.CTkEntry(row2)
        self._sp_model_dir.pack(side="left", padx=6, fill="x", expand=True)
        if self.settings.get("shopee_model_dir"):
            self._sp_model_dir.insert(0, self.settings["shopee_model_dir"])
        self._sp_model_count = ctk.CTkLabel(row2, text="", font=("", 10), text_color=T2)
        self._sp_model_count.pack(side="left", padx=(0, 4))
        ctk.CTkButton(row2, text="Chọn", width=56, command=self._sp_pick_model,
                      fg_color="#EE4D2D", hover_color="#D73211").pack(side="left", padx=(0, 8))

        self._sp_no_model = ctk.BooleanVar(value=self.settings.get("shopee_no_model", False))
        self._sp_no_model_chk = ctk.CTkCheckBox(row2, text="Không mẫu", variable=self._sp_no_model,
                                                font=("", 11), checkbox_width=18, checkbox_height=18,
                                                command=self._sp_toggle_no_model)
        self._sp_no_model_chk.pack(side="left", padx=(0, 16))

        # --- Phần Lưu video ---
        ctk.CTkLabel(row2, text="📁 Lưu video:", font=("", 12)).pack(side="left")
        self._sp_outdir = ctk.CTkEntry(row2)
        self._sp_outdir.pack(side="left", padx=6, fill="x", expand=True)
        if self.settings.get("shopee_out_dir"):
            self._sp_outdir.insert(0, self.settings["shopee_out_dir"])
        ctk.CTkButton(row2, text="Chọn", width=56, command=lambda: self._pick(self._sp_outdir),
                      fg_color="#EE4D2D", hover_color="#D73211").pack(side="left", padx=(0, 4))

        # --- Bottom Container (để các nút ở dưới không bị lấp khi cửa sổ nhỏ) ---
        bottom_container = ctk.CTkFrame(f, fg_color="transparent")
        bottom_container.pack(side="bottom", fill="x")

        # --- Middle Container (2 hàng) ---
        middle_split = ctk.CTkFrame(f, fg_color="transparent")
        middle_split.pack(fill="both", expand=True, pady=(10, 0))

        # --- Hàng trên: Nhập sản phẩm (Tên | Đường dẫn ảnh) ---
        prod_card = ctk.CTkFrame(middle_split, fg_color=CARD, corner_radius=10)
        prod_card.pack(fill="both", expand=True, pady=(0, 5))
        lbl_row = ctk.CTkFrame(prod_card, fg_color="transparent"); lbl_row.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(lbl_row, text="📦 Danh sách sản phẩm (mỗi dòng: ảnh.jpg | Tên SP):",
                     font=("", 13, "bold"), text_color=T1).pack(side="left")
        self._sp_prod_count = ctk.CTkLabel(lbl_row, text="0 SP", font=("", 11), text_color=T2)
        self._sp_prod_count.pack(side="right")

        # Textbox nhập liệu sản phẩm
        self._sp_products = ctk.CTkTextbox(prod_card, font=("Consolas", 11))
        self._sp_products.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        # Cấu hình màu sắc cho từng trạng thái dòng
        self._sp_products.tag_config("status_success", foreground="#1B7D2C")  # xanh lá
        self._sp_products.tag_config("status_error", foreground="#D32F2F")    # đỏ
        self._sp_products.tag_config("status_running", foreground="#E65100")  # cam
        saved_products = self.settings.get("shopee_products", "")
        if saved_products:
            self._sp_products.insert("1.0", saved_products)
            # Khôi phục màu sắc cho các dòng đã có trạng thái
            self._sp_restore_line_colors()
        self._sp_count_debounce_id = None
        def _sp_debounced_count(event=None):
            if self._sp_count_debounce_id:
                self.after_cancel(self._sp_count_debounce_id)
            self._sp_count_debounce_id = self.after(500, self._sp_update_count)
        self._sp_products.bind("<KeyRelease>", _sp_debounced_count)

        # Nút import + xem trước
        btn_import_row = ctk.CTkFrame(prod_card, fg_color="transparent"); btn_import_row.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkButton(btn_import_row, text="📂 Import thư mục ảnh", width=160,
                      command=self._sp_import_folder,
                      fg_color="#5C6BC0", hover_color="#3949AB").pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_import_row, text="📄 Import tên SP (TXT)", width=160,
                      command=self._sp_import_names_txt,
                      fg_color="#43A047", hover_color="#2E7D32").pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_import_row, text="🗑 Xóa hết", width=80,
                      command=self._sp_clear_all,
                      fg_color="#E53935", hover_color="#B71C1C").pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_import_row, text="🔄 Xóa trạng thái", width=120,
                      command=self._sp_clear_status,
                      fg_color="#7B1FA2", hover_color="#4A148C").pack(side="left", padx=(0, 4))
        ctk.CTkButton(btn_import_row, text="✅ Xóa thành công", width=120,
                      command=self._sp_clear_success,
                      fg_color="#00897B", hover_color="#00695C").pack(side="left", padx=(0, 4))
        ctk.CTkLabel(btn_import_row, text="① Ảnh → ② TXT",
                     font=("", 10), text_color=T2).pack(side="left", padx=4)

        # --- Log & Progress ---
        bottom = ctk.CTkFrame(bottom_container, fg_color="transparent"); bottom.pack(fill="x", pady=(8, 0))
        self._sp_progress = ctk.CTkProgressBar(bottom, height=8, progress_color="#EE4D2D")
        self._sp_progress.pack(fill="x", pady=(0, 4))
        self._sp_progress.set(0)

        # --- Hàng dưới: Pool Status Panel (AIMD) ---
        pool_card = ctk.CTkFrame(middle_split, fg_color=CARD, corner_radius=10)
        pool_card.pack(fill="both", expand=True, pady=(5, 0))
        pool_hdr = ctk.CTkFrame(pool_card, fg_color="transparent"); pool_hdr.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(pool_hdr, text="🚀 Pool tài khoản (AIMD)", font=("", 12, "bold"), text_color=T1).pack(side="left")
        self._sp_pool_eta_lbl = ctk.CTkLabel(pool_hdr, text="", font=("", 11), text_color=AC)
        self._sp_pool_eta_lbl.pack(side="right")
        # 4 stat boxes
        stat_row = ctk.CTkFrame(pool_card, fg_color="transparent"); stat_row.pack(fill="x", padx=12, pady=2)
        self._sp_pool_stat = {}
        for key, icon, color in [("acc", "👥 Tổng", T1), ("run", "🟢 Chạy", GR), ("gen", "⚡ Tạo", AC), ("rest", "😴 Nghỉ", "#F9A825")]:
            box = ctk.CTkFrame(stat_row, fg_color="transparent"); box.pack(side="left", padx=(0, 16))
            ctk.CTkLabel(box, text=icon, font=("", 10), text_color=T2).pack(side="left")
            lbl = ctk.CTkLabel(box, text="0", font=("", 11, "bold"), text_color=color); lbl.pack(side="left", padx=(4, 0))
            self._sp_pool_stat[key] = lbl
        # Account rows container
        self._sp_pool_rows_frame = ctk.CTkScrollableFrame(pool_card, fg_color=CARD, height=80)
        self._sp_pool_rows_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._sp_pool_rows = {}
        self._sp_pool_row_sig = ()
        self._sp_pool_states = None  # set during run

        self._sp_log = ctk.CTkTextbox(bottom_container, height=120, font=("Consolas", 10), state="disabled")
        self._sp_log.pack(fill="x", pady=(4, 0))

        # --- Bảng kết quả (hiện sau khi xử lý) ---
        self._sp_result_card = ctk.CTkFrame(bottom_container, fg_color=CARD, corner_radius=10)
        result_hdr = ctk.CTkFrame(self._sp_result_card, fg_color="transparent")
        result_hdr.pack(fill="x", padx=12, pady=(8, 2))
        self._sp_result_title = ctk.CTkLabel(result_hdr, text="📊 Kết quả xử lý",
                                              font=("", 13, "bold"), text_color=T1)
        self._sp_result_title.pack(side="left")
        self._sp_result_summary = ctk.CTkLabel(result_hdr, text="", font=("", 11), text_color=T2)
        self._sp_result_summary.pack(side="right")
        self._sp_result_scroll = ctk.CTkScrollableFrame(self._sp_result_card, fg_color=CARD, height=100)
        self._sp_result_scroll.pack(fill="x", padx=8, pady=(0, 8))

        # --- Nút bấm ---
        self._sp_btn_row = ctk.CTkFrame(bottom_container, fg_color="transparent"); self._sp_btn_row.pack(fill="x", pady=(8, 0))
        self._sp_btn_start = ctk.CTkButton(self._sp_btn_row, text="▶  Bắt đầu tạo video",
                                           command=self._shopee_start, fg_color="#EE4D2D",
                                           hover_color="#D73211", height=42,
                                           font=("", 15, "bold"))
        self._sp_btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._sp_btn_stop = ctk.CTkButton(self._sp_btn_row, text="⏹ Dừng", command=self._shopee_stop,
                                          fg_color="#9aa0a6", hover_color="#5f6368",
                                          height=42, width=100, state="disabled")
        self._sp_btn_stop.pack(side="left", padx=(0, 4))
        self._sp_btn_open = ctk.CTkButton(self._sp_btn_row, text="📂 Mở thư mục",
                                          command=self._shopee_open_folder,
                                          fg_color="#5C6BC0", hover_color="#3949AB",
                                          height=42, width=120)
        self._sp_btn_open.pack(side="left")

        self._shopee_running = False
        self._shopee_stop_flag = False
        self._shopee_results = []
        self._sp_img_folder = self.settings.get("shopee_img_folder", "")  # thư mục ảnh SP
        # Xóa trắng shopee.txt mỗi lần khởi động
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "shopee.txt"), "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass

        self._sp_toggle_no_model()

    def _sp_pick_model(self):
        """Chọn thư mục chứa ảnh người mẫu."""
        from tkinter import filedialog as fd
        p = fd.askdirectory(title="Chọn thư mục chứa ảnh người mẫu")
        if p:
            self._sp_model_dir.delete(0, "end")
            self._sp_model_dir.insert(0, p)
            # Đếm số ảnh trong thư mục
            n = len(SV.list_model_images(p)) if SV else 0
            self._sp_model_count.configure(text=f"({n} ảnh)")
            self._sp_log_msg(f"👤 Thư mục người mẫu: {p} ({n} ảnh)")

    def _sp_toggle_no_model(self):
        """Bật/tắt trạng thái nhập thư mục người mẫu dựa trên nút checkbox."""
        st = "disabled" if self._sp_no_model.get() else "normal"
        self._sp_model_dir.configure(state=st)
        if self._sp_no_model.get():
            self._sp_model_count.configure(text="(Không chọn)")
        else:
            p = self._sp_model_dir.get().strip()
            if p and os.path.isdir(p):
                n = len(SV.list_model_images(p)) if SV else 0
                self._sp_model_count.configure(text=f"({n} ảnh)")
            else:
                self._sp_model_count.configure(text="")

    _SP_STATUS_PREFIXES = ("✅ ", "❌ ", "⏳ ")

    def _sp_strip_status(self, line):
        """Bỏ prefix trạng thái (✅/❌/⏳) khỏi dòng."""
        for pfx in self._SP_STATUS_PREFIXES:
            if line.startswith(pfx):
                return line[len(pfx):]
        return line

    def _sp_update_line_status(self, line_idx, status):
        """Cập nhật trạng thái cho dòng line_idx (0-indexed) trong textbox.
        status: 'success' → ✅, 'error' → ❌, 'running' → ⏳, 'clear' → bỏ prefix.
        """
        prefix_map = {"success": "✅ ", "error": "❌ ", "running": "⏳ ", "clear": ""}
        tag_map = {"success": "status_success", "error": "status_error", "running": "status_running"}
        pfx = prefix_map.get(status, "")
        tag = tag_map.get(status)
        def _do():
            try:
                tk_line = line_idx + 1  # Tk textbox 1-indexed
                content = self._sp_products.get(f"{tk_line}.0", f"{tk_line}.end")
                clean = self._sp_strip_status(content)
                new_content = pfx + clean
                self._sp_products.delete(f"{tk_line}.0", f"{tk_line}.end")
                self._sp_products.insert(f"{tk_line}.0", new_content)
                # Xóa tất cả tag cũ trên dòng này
                for t in ("status_success", "status_error", "status_running"):
                    self._sp_products.tag_remove(t, f"{tk_line}.0", f"{tk_line}.end")
                # Thêm tag mới (nếu có)
                if tag:
                    self._sp_products.tag_add(tag, f"{tk_line}.0", f"{tk_line}.end")
            except Exception:
                pass
        self.after(0, _do)

    def _sp_restore_line_colors(self):
        """Khôi phục màu sắc cho các dòng đã có trạng thái (✅/❌) khi load lại."""
        try:
            text = self._sp_products.get("1.0", "end").strip()
            for i, line in enumerate(text.splitlines()):
                tk_line = i + 1
                if line.startswith("✅ "):
                    self._sp_products.tag_add("status_success", f"{tk_line}.0", f"{tk_line}.end")
                elif line.startswith("❌ "):
                    self._sp_products.tag_add("status_error", f"{tk_line}.0", f"{tk_line}.end")
        except Exception:
            pass

    def _sp_update_count(self):
        text = self._sp_products.get("1.0", "end").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        # Đếm trạng thái
        total = len(lines)
        done = sum(1 for l in lines if l.startswith("✅"))
        fail = sum(1 for l in lines if l.startswith("❌"))
        pending = total - done - fail
        if done or fail:
            self._sp_prod_count.configure(text=f"{total} SP (✅{done} ❌{fail} ⏳{pending})")
        else:
            self._sp_prod_count.configure(text=f"{total} SP")

    def _sp_clear_status(self):
        """Xóa trạng thái ✅/❌/⏳ khỏi tất cả các dòng để chạy lại."""
        if not messagebox.askyesno("❓ Xác nhận", "Xóa trạng thái ✅/❌/⏳ của tất cả dòng?\nCác dòng sẽ quay về trạng thái chưa chạy."):
            return
        text = self._sp_products.get("1.0", "end").strip()
        lines = text.splitlines()
        new_lines = [self._sp_strip_status(l) for l in lines]
        self._sp_products.delete("1.0", "end")
        self._sp_products.insert("1.0", "\n".join(new_lines))
        # Xóa tất cả tag màu
        for t in ("status_success", "status_error", "status_running"):
            self._sp_products.tag_remove(t, "1.0", "end")
        self._sp_update_count()
        self._sp_log_msg("🔄 Đã xóa trạng thái tất cả dòng — sẵn sàng chạy lại")

    def _sp_clear_success(self):
        """Xóa các dòng đã thành công (✅) khỏi danh sách."""
        text = self._sp_products.get("1.0", "end").strip()
        lines = text.splitlines()
        kept = [l for l in lines if not l.startswith("✅ ")]
        removed = len(lines) - len(kept)
        self._sp_products.delete("1.0", "end")
        if kept:
            self._sp_products.insert("1.0", "\n".join(kept))
        # Restore màu cho các dòng còn lại
        self._sp_restore_line_colors()
        self._sp_update_count()
        self._sp_log_msg(f"✅ Đã xóa {removed} dòng thành công, còn {len(kept)} dòng")

    def _sp_clear_all(self):
        """Xóa toàn bộ danh sách sản phẩm + preview."""
        if not messagebox.askyesno("⚠️ Xác nhận xóa hết", "Xóa TOÀN BỘ danh sách sản phẩm?\nHành động này không thể hoàn tác."):
            return
        self._sp_products.delete("1.0", "end")
        self._sp_img_folder = ""
        self._sp_update_count()
        # Panel preview là tùy chọn (có thể chưa được dựng trong layout) → chỉ dọn khi tồn tại
        if hasattr(self, "_sp_preview_scroll"):
            for w in self._sp_preview_scroll.winfo_children():
                w.destroy()
            self._sp_thumb_cache = []
            ctk.CTkLabel(self._sp_preview_scroll, text="(Chưa có SP)",
                         font=("", 11), text_color=T2).pack(pady=20)
        self._sp_log_msg("🗑 Đã xóa toàn bộ danh sách SP")

    def _sp_resolve_img(self, img_path):
        """Resolve tên file thành full path nếu cần (dùng _sp_img_folder)."""
        if not img_path:
            return ""
        if os.path.isabs(img_path) and os.path.isfile(img_path):
            return img_path
        # Thử ghép với thư mục ảnh
        if self._sp_img_folder:
            full = os.path.join(self._sp_img_folder, img_path)
            if os.path.isfile(full):
                return full
        return img_path  # trả nguyên nếu không resolve được

    def _sp_import_folder(self):
        """Import ảnh từ thư mục: tự động ghép Tên Ảnh với Tên SP hiện có (nếu có).
        Format: ảnh.jpg | Tên SP.
        Tối ưu cho 20k+ ảnh: batch insert, skip auto-preview."""
        from tkinter import filedialog as fd
        folder = fd.askdirectory(title="Chọn thư mục chứa ảnh sản phẩm")
        if not folder:
            return
        _img_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}
        import re
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
        files = sorted((f for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in _img_exts), key=natural_sort_key)
        if not files:
            messagebox.showinfo("Trống", "Không tìm thấy ảnh nào trong thư mục.")
            return
        self._sp_img_folder = folder  # lưu thư mục để resolve path khi chạy

        # Đọc danh sách hiện có trong textbox
        current_text = self._sp_products.get("1.0", "end").strip()
        current_lines = [l.strip() for l in current_text.splitlines() if l.strip()]

        existing_names = []
        for cl in current_lines:
            clean = self._sp_strip_status(cl)
            if "|" in clean:
                parts = clean.split("|", 1)
                left, right = parts[0].strip(), parts[1].strip()
                if os.path.splitext(left)[1].lower() in _img_exts:
                    existing_names.append(right)
                else:
                    existing_names.append(left)
            else:
                existing_names.append(clean)

        new_lines = []
        for i, fn in enumerate(files):
            if i < len(existing_names) and existing_names[i]:
                name = existing_names[i]
            else:
                name = os.path.splitext(fn)[0]
            new_lines.append(f"{fn} | {name}")

        bulk = "\n".join(new_lines)
        self._sp_products.delete("1.0", "end")
        self._sp_products.insert("1.0", bulk)
        self._sp_update_count()
        self._sp_log_msg(f"📂 Đã import {len(files)} ảnh từ: {folder}")
        if existing_names:
            self._sp_log_msg(f"🔗 Đã tự động ghép {min(len(files), len(existing_names))} ảnh với danh sách Tên SP hiện có!")

        # Skip auto-preview cho > 200 SP (quá nặng)
        if len(files) <= 200:
            self._sp_refresh_preview()
        else:
            self._sp_log_msg(f"ℹ️ {len(files)} SP — bỏ qua preview tự động (bấm 👁 để xem trước khi cần)")

    def _sp_import_names_txt(self):
        """Import tên SP từ file TXT (mỗi dòng 1 tên).
        Ghi đè/ghép tên SP với danh sách ảnh hiện tại (hoặc thư mục ảnh đã chọn).
        Format: ảnh.jpg | Tên SP.
        Tối ưu cho 20k+ dòng: batch build, single insert.
        """
        from tkinter import filedialog as fd
        txt_path = fd.askopenfilename(title="Chọn file TXT chứa tên sản phẩm",
                                       filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if not txt_path:
            return
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                names = [l.strip() for l in f if l.strip()]
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không đọc được file: {e}")
            return
        if not names:
            messagebox.showinfo("Trống", "File TXT không có dòng nào.")
            return

        _img_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff'}

        # Đọc danh sách hiện tại
        current_text = self._sp_products.get("1.0", "end").strip()
        current_lines = [l.strip() for l in current_text.splitlines() if l.strip()]

        img_parts = []
        for cl in current_lines:
            clean = self._sp_strip_status(cl)
            if "|" in clean:
                p = clean.split("|", 1)
                left, right = p[0].strip(), p[1].strip()
                if os.path.splitext(left)[1].lower() in _img_exts:
                    img_parts.append(left)
                else:
                    img_parts.append(right)
            else:
                img_parts.append("")

        # Nếu chưa có ảnh trong textbox nhưng đã có thư mục ảnh _sp_img_folder
        if not any(img_parts) and self._sp_img_folder and os.path.isdir(self._sp_img_folder):
            import re
            def natural_sort_key(s):
                return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
            folder_files = sorted(
                (f for f in os.listdir(self._sp_img_folder) if os.path.splitext(f)[1].lower() in _img_exts),
                key=natural_sort_key
            )
            if folder_files:
                img_parts = folder_files

        new_lines = []
        for i, name in enumerate(names):
            if i < len(img_parts) and img_parts[i]:
                new_lines.append(f"{img_parts[i]} | {name}")
            else:
                new_lines.append(name)

        if len(names) < len(img_parts):
            for j in range(len(names), len(img_parts)):
                if j < len(current_lines):
                    new_lines.append(current_lines[j])
                elif img_parts[j]:
                    new_lines.append(f"{img_parts[j]} | {os.path.splitext(img_parts[j])[0]}")

        bulk = "\n".join(new_lines)
        self._sp_products.delete("1.0", "end")
        self._sp_products.insert("1.0", bulk)
        self._sp_log_msg(f"📄 Đã ghép {len(names)} tên SP từ TXT với danh sách ảnh hiện có")

        self._sp_update_count()
        n = max(len(names), len(img_parts))
        if n <= 200:
            self._sp_refresh_preview()
        else:
            self._sp_log_msg(f"ℹ️ {n} SP — bỏ qua preview tự động")

    def _sp_refresh_preview(self):
        """Parse textbox và render thumbnail preview bên phải (bỏ qua nếu panel preview chưa được dựng)."""
        if not hasattr(self, "_sp_preview_scroll"):
            return
        for w in self._sp_preview_scroll.winfo_children():
            w.destroy()
        self._sp_thumb_cache = []
        text = self._sp_products.get("1.0", "end").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            ctk.CTkLabel(self._sp_preview_scroll, text="(Chưa có SP)",
                         font=("", 11), text_color=T2).pack(pady=20)
            return
        THUMB = 40
        try:
            from PIL import Image as PILImage
        except ImportError:
            ctk.CTkLabel(self._sp_preview_scroll, text="Cần cài Pillow",
                         font=("", 11), text_color=RD).pack(pady=20)
            return
        _img_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff'}
        for i, line in enumerate(lines):
            clean = self._sp_strip_status(line) if hasattr(self, '_sp_strip_status') else line
            if "|" in clean:
                parts = clean.split("|", 1)
                left = parts[0].strip()
                right = parts[1].strip()
                if os.path.splitext(left)[1].lower() in _img_exts:
                    img_path, name = left, right
                else:
                    name, img_path = left, right
            else:
                name = clean
                img_path = ""
            row = ctk.CTkFrame(self._sp_preview_scroll, fg_color="#ffffff" if i % 2 == 0 else "#e8eaf0",
                               corner_radius=4, height=THUMB + 6)
            row.pack(fill="x", pady=1); row.pack_propagate(False)
            # Số thứ tự
            ctk.CTkLabel(row, text=f"{i+1}", font=("Consolas", 9), width=24, text_color=T2).pack(side="left", padx=2)
            # Thumbnail
            try:
                resolved = self._sp_resolve_img(img_path)
                if resolved and os.path.isfile(resolved):
                    pil_img = PILImage.open(resolved)
                    pil_img.thumbnail((THUMB, THUMB))
                    ctk_img = ctk.CTkImage(light_image=pil_img, size=(THUMB, THUMB))
                    self._sp_thumb_cache.append(ctk_img)
                    ctk.CTkLabel(row, image=ctk_img, text="", width=THUMB + 4).pack(side="left", padx=2)
                else:
                    ctk.CTkLabel(row, text="—", width=THUMB + 4, font=("", 12), text_color=T2).pack(side="left", padx=2)
            except Exception:
                ctk.CTkLabel(row, text="⚠", width=THUMB + 4, font=("", 12), text_color=RD).pack(side="left", padx=2)
            # Tên SP (cắt ngắn)
            short = name[:22] + (".." if len(name) > 22 else "")
            ctk.CTkLabel(row, text=short, font=("Consolas", 9), anchor="w", text_color=T1).pack(side="left", padx=4, fill="x")
        self._sp_log_msg(f"👁 Preview: {len(lines)} sản phẩm")

    def _sp_on_model_change(self):
        """Shopee: Khi đổi Model → Omni Flash khóa Duration, Veo mở khóa."""
        model_name = self._sp_model.get()
        if "Omni Flash" in model_name:
            for d in ("4s", "6s", "8s", "10s"):
                if d in model_name:
                    self._sp_duration.set(d)
                    break
            self._sp_duration.configure(state="disabled", fg_color="#455A64", text_color="#B0BEC5")
            # Omni Flash → cho phép ghép ảnh 12s
            if hasattr(self, '_sp_chk_ghep_anh'):
                self._sp_chk_ghep_anh.configure(state="normal")
        else:
            self._sp_duration.configure(
                state="normal",
                fg_color=ctk.ThemeManager.theme["CTkOptionMenu"]["fg_color"],
                text_color=ctk.ThemeManager.theme["CTkOptionMenu"]["text_color"]
            )
        self._sp_on_duration_change()

    def _sp_on_duration_change(self):
        """Khi đổi Độ dài: 8s → khóa AI Prompt thành 'TVC Template'; 16s/24s → mở lại."""
        dur = self._sp_duration.get()
        if dur == "8s":
            # Lưu giá trị AI hiện tại trước khi khóa
            current = self._sp_ai_prompt.get()
            if current not in ("📺 TVC Template",):
                self._sp_ai_saved_value = current
            # Khóa dropdown AI Prompt
            self._sp_ai_prompt.configure(values=["📺 TVC Template"], state="disabled",
                                          fg_color="#455A64", text_color="#B0BEC5")
            self._sp_ai_prompt.set("📺 TVC Template")
            if hasattr(self, '_sp_chk_ghep_anh'):
                self._sp_chk_ghep_anh.configure(state="normal")
        else:
            # Mở khóa dropdown AI Prompt
            self._sp_ai_prompt.configure(
                values=["Gemini", "Groq", "Prompt A + B"],
                state="normal",
                fg_color=ctk.ThemeManager.theme["CTkOptionMenu"]["fg_color"],
                text_color=ctk.ThemeManager.theme["CTkOptionMenu"]["text_color"]
            )
            # Khôi phục giá trị AI đã lưu
            if hasattr(self, '_sp_ai_saved_value') and self._sp_ai_saved_value:
                self._sp_ai_prompt.set(self._sp_ai_saved_value)
            if hasattr(self, '_sp_chk_ghep_anh') and "Omni Flash" not in self._sp_model.get():
                self._sp_ghep_anh.set(False)
                self._sp_chk_ghep_anh.configure(state="disabled")

    def _sp_test_prompt(self):
        """Tạo thử prompt video cho sản phẩm ĐẦU TIÊN trong danh sách và hiển thị cửa sổ dialog kiểm tra."""
        try:
            text = self._sp_products.get("1.0", "end").strip()
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if not lines:
                messagebox.showwarning("Thiếu sản phẩm", "Vui lòng nhập ít nhất 1 sản phẩm vào danh sách.")
                return

            # Parse SP đầu tiên (dù là format cũ hay mới)
            _img_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff'}
            first_line = self._sp_strip_status(lines[0])
            if "|" in first_line:
                parts = first_line.split("|", 1)
                left, right = parts[0].strip(), parts[1].strip()
                if os.path.splitext(left)[1].lower() in _img_exts:
                    prod_name = right or left
                else:
                    prod_name = left or right
            else:
                prod_name = first_line.strip()

            if not prod_name:
                messagebox.showwarning("Lỗi", "Không tìm thấy tên sản phẩm ở dòng đầu tiên.")
                return

            ai_mode = self._sp_ai_prompt.get()
            duration_sec = SV.parse_duration(self._sp_duration.get()) if SV else 16
            n_segments = len(SV.DURATION_MAP.get(duration_sec, [0, 1])) if SV else 2
            scene_choice = self._sp_scene.get()
            lang_val = self._sp_lang.get()
            lang_code = "vi" if "Việt" in lang_val else ("id" if "Indonesia" in lang_val else ("my" if "Malaysia" in lang_val else ("ph" if "Philippines" in lang_val else "en")))
            review_style = self._sp_review_style.get()

            if SV:
                scene_name, scene_en = SV.pick_scene(scene_choice, lang=lang_code)
            else:
                scene_name, scene_en = scene_choice, "clean minimalist desk"

            gemini_keys = [l.strip() for l in self.txt_gemini.get("1.0", "end").splitlines() if l.strip()]
            groq_keys = [l.strip() for l in self.txt_groq_keys.get("1.0", "end").splitlines() if l.strip()]

            if ai_mode == "Gemini" and not gemini_keys:
                messagebox.showwarning("Thiếu Key Gemini", "Vui lòng nạp API Key Gemini ở phần cài đặt API Key.")
                return
            if ai_mode == "Groq" and not groq_keys:
                messagebox.showwarning("Thiếu Key Groq", "Vui lòng nạp API Key Groq ở phần cài đặt API Key.")
                return

            # Mở dialog hiển thị prompt
            dlg = ctk.CTkToplevel(self)
            dlg.title(f"🧪 Test Prompt: {prod_name[:35]}")
            dlg.geometry("720x540")
            dlg.attributes("-topmost", True)
            dlg.after(100, lambda: dlg.attributes("-topmost", False))
            dlg.focus_force()

            ctk.CTkLabel(dlg, text=f"📦 Sản phẩm: {prod_name}", font=("", 13, "bold"), text_color=T1).pack(anchor="w", padx=16, pady=(12, 2))
            ctk.CTkLabel(dlg, text=f"🤖 AI Engine: {ai_mode}  |  ⏱ Độ dài: {duration_sec}s ({n_segments} đoạn)  |  🏖 Cảnh: {scene_name}", font=("", 11), text_color=T2).pack(anchor="w", padx=16, pady=(0, 8))

            txt = ctk.CTkTextbox(dlg, font=("Consolas", 10), wrap="word")
            txt.pack(fill="both", expand=True, padx=16, pady=(0, 10))
            txt.insert("1.0", f"⏳ Đang tạo prompt ({ai_mode}), vui lòng chờ trong giây lát...\n")

            def _generate():
                prompts = None
                mode_str = ai_mode
                if ai_mode == "Gemini":
                    prompts = self._sv_ai_gen_prompts(
                        prod_name, scene_en, n_segments, duration_sec, lang_code,
                        review_style, mode="gemini", gemini_keys=gemini_keys
                    )
                elif ai_mode == "Groq":
                    prompts = self._sv_ai_gen_prompts(
                        prod_name, scene_en, n_segments, duration_sec, lang_code,
                        review_style, mode="groq", groq_keys=groq_keys
                    )

                if not prompts and SV:
                    prompts = SV.build_video_prompts(
                        prod_name, scene_en, duration_sec=duration_sec,
                        lang=lang_code, review_style=review_style
                    )
                    if ai_mode in ("Gemini", "Groq"):
                        mode_str += " (Lỗi AI → Dùng Template Mặc Định)"

                def _show_ui():
                    try:
                        txt.delete("1.0", "end")
                        if not prompts:
                            txt.insert("1.0", "❌ Không sinh được prompt.")
                            return
                        header = f"=== PROMPT VIDEO TEST FOR: {prod_name} ===\nEngine: {mode_str}\nSegments: {len(prompts)}\n" + "="*60 + "\n\n"
                        body = ""
                        for idx, pr in enumerate(prompts, 1):
                            body += f"--- SEGMENT {idx} ---\n{pr}\n\n"
                        txt.insert("1.0", header + body)
                    except Exception:
                        pass

                self.after(0, _show_ui)

            threading.Thread(target=_generate, daemon=True).start()
        except Exception as err:
            messagebox.showerror("Lỗi Test Prompt", f"Xảy ra lỗi: {err}")

    def _sp_log_msg(self, msg):
        """Ghi log Shopee — batch 500ms."""
        if not hasattr(self, '_sp_log_buffer'):
            self._sp_log_buffer = []
            self._sp_log_flush_scheduled = False
        self._sp_log_buffer.append(msg)
        if not self._sp_log_flush_scheduled:
            self._sp_log_flush_scheduled = True
            self.after(500, self._sp_flush_log)

    def _sp_flush_log(self):
        """Flush tất cả log buffer Shopee vào textbox + file 1 lần duy nhất."""
        self._sp_log_flush_scheduled = False
        if not hasattr(self, '_sp_log_buffer') or not self._sp_log_buffer:
            return
        batch = self._sp_log_buffer[:]
        self._sp_log_buffer.clear()
        # Ghi file log 1 lần
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "shopee.txt"), "a", encoding="utf-8") as lf:
                for m in batch:
                    lf.write(f"[{time.strftime('%H:%M:%S')}] {m}\n")
        except Exception:
            pass
        try:
            self._sp_log.configure(state="normal")
            self._sp_log.insert("end", "\n".join(batch) + "\n")
            line_count = int(self._sp_log.index("end-1c").split(".")[0])
            if line_count > 1000:
                self._sp_log.delete("1.0", f"{line_count - 800}.0")
            self._sp_log.see("end")
            self._sp_log.configure(state="disabled")
        except Exception:
            pass

    # --- Shopee Pool Status (AIMD live update, mirrors _update_pool) ---
    def _sp_update_pool(self):
        """Panel POOL Shopee (cập nhật mỗi 2s) — tối ưu chỉ redraw khi giá trị thay đổi."""
        try:
            # Fix 3: Bỏ qua nếu tab Shopee không hiển thị
            if getattr(self, '_current_tab', '') != 'shopee':
                return

            if not hasattr(self, '_sp_pool_cache'):
                self._sp_pool_cache = {}
            cache = self._sp_pool_cache

            def _set(widget, key, **kwargs):
                val = tuple(sorted(kwargs.items()))
                if cache.get(key) != val:
                    widget.configure(**kwargs)
                    cache[key] = val

            _set(self._sp_pool_eta_lbl, "_sp_eta", text=self._sp_eta_text())
            is_running = getattr(self, "_shopee_running", False)
            states = getattr(self, "_sp_pool_states", None)
            if not is_running or not states:
                states = [AccountState(a) for a in self.accounts if a.get("enabled", True) and a.get("role", "main") == "main"]
            total = len(states)
            resting = sum(1 for s in states if s.rest_remaining() > 0)
            running = total - resting
            generating = sum(1 for s in states if getattr(s, "busy", 0) > 0)
            _set(self._sp_pool_stat["acc"], "_sp_st_acc", text=str(total))
            _set(self._sp_pool_stat["run"], "_sp_st_run", text=str(running if is_running else total))
            _set(self._sp_pool_stat["gen"], "_sp_st_gen", text=str(generating))
            _set(self._sp_pool_stat["rest"], "_sp_st_rest", text=str(resting if is_running else 0))
            sig = tuple(s.email for s in states)
            if sig != self._sp_pool_row_sig:
                self._sp_pool_row_sig = sig
                cache.clear()
                for w in self._sp_pool_rows_frame.winfo_children(): w.destroy()
                self._sp_pool_rows = {}
                if not states:
                    ctk.CTkLabel(self._sp_pool_rows_frame, text="Chưa có tài khoản nào được chọn ở Tab 'Tài khoản'.",
                                 font=("", 11), text_color=T2).pack(anchor="w", pady=6)
                else:
                    cols = [("Tài khoản", 130), ("✅ Xong", 50), ("❌ Lỗi", 45),
                            ("⚡ Tạo", 40), ("🚀 Tốc độ", 55), ("Trạng thái", 105), ("🌐 Proxy", 150), ("Hành động", 65), ("📤 Upload", 60)]
                    hdr = ctk.CTkFrame(self._sp_pool_rows_frame, fg_color="transparent"); hdr.pack(fill="x", pady=(0, 2))
                    for txt, w in cols:
                        ctk.CTkLabel(hdr, text=txt, font=("", 10, "bold"), text_color=T2, width=w, anchor="w").pack(side="left", padx=(2, 0))
                    for i, s in enumerate(states):
                        row = ctk.CTkFrame(self._sp_pool_rows_frame, fg_color=("#f6f8fc" if i % 2 else CARD), corner_radius=6)
                        row.pack(fill="x", pady=1)
                        ctk.CTkLabel(row, text=str(s.email).split("@")[0][:22], font=("", 11), text_color=T1, width=130, anchor="w").pack(side="left", padx=(2, 0))
                        wl = ctk.CTkLabel(row, text="0", font=("", 11, "bold"), text_color=GR, width=50, anchor="w"); wl.pack(side="left", padx=(2, 0))
                        fl = ctk.CTkLabel(row, text="0", font=("", 11), text_color=RD, width=45, anchor="w"); fl.pack(side="left", padx=(2, 0))
                        bl = ctk.CTkLabel(row, text="0", font=("", 11), text_color=T1, width=40, anchor="w"); bl.pack(side="left", padx=(2, 0))
                        rl = ctk.CTkLabel(row, text="0", font=("", 11), text_color=AC, width=55, anchor="w"); rl.pack(side="left", padx=(2, 0))
                        sl = ctk.CTkLabel(row, text="", font=("", 11), text_color=GR, width=105, anchor="w"); sl.pack(side="left", padx=(2, 0))
                        pl = ctk.CTkLabel(row, text="—", font=("Consolas", 10), text_color=T2, width=150, anchor="w"); pl.pack(side="left", padx=(2, 0))
                        ab = ctk.CTkButton(row, text="⏹ Dừng", fg_color="#E57373", hover_color="#EF5350", width=60, height=24, font=("", 11, "bold"),
                                           command=lambda e=s.email: self._toggle_acc_enabled(e))
                        ab.pack(side="left", padx=(2, 0))
                        uo = ctk.CTkOptionMenu(row, values=["2", "3", "4", "5", "6", "7", "8", "9", "10"], width=52, height=24, font=("", 11),
                                               command=lambda v, st=s: self._on_acc_upload_threads_change(st, v))
                        uo.pack(side="left", padx=(4, 0))
                        uo.set(str(getattr(s, "upload_threads", 4)))
                        self._sp_pool_rows[s.email] = {"w": wl, "f": fl, "b": bl, "r": rl, "s": sl, "p": pl, "a": ab, "u": uo}
            for s in states:
                r = self._sp_pool_rows.get(s.email)
                if not r: continue
                e = s.email
                _set(r["w"], f"sp_{e}_w", text=str(s.wins))
                _set(r["f"], f"sp_{e}_f", text=str(s.fails))
                _set(r["b"], f"sp_{e}_b", text=str(s.busy))
                _set(r["r"], f"sp_{e}_r", text=str(int(s.submit_limit)))
                px_str = self.proxy_pool.get_str(s.email) if self.proxy_pool else None
                if px_str:
                    parts = px_str.split(":")
                    px_display = f"{parts[0]}:{parts[1]}" if len(parts) >= 2 else px_str[:30]
                    _set(r["p"], f"sp_{e}_p", text=px_display, text_color=AC)
                else:
                    _set(r["p"], f"sp_{e}_p", text="IP trực tiếp", text_color=T2)
                is_enabled = s.acc.get("enabled", True)
                if not is_enabled:
                    _set(r["s"], f"sp_{e}_s", text="⏹ đã dừng", text_color=T2)
                    _set(r["a"], f"sp_{e}_a", text="▶ Chạy", fg_color="#26A69A", hover_color="#00897B")
                elif not is_running:
                    _set(r["s"], f"sp_{e}_s", text="⏳ Sẵn sàng", text_color=GR)
                    _set(r["a"], f"sp_{e}_a", text="⏹ Dừng", fg_color="#E57373", hover_color="#EF5350")
                else:
                    _set(r["a"], f"sp_{e}_a", text="⏹ Dừng", fg_color="#E57373", hover_color="#EF5350")
                    rem = s.rest_remaining()
                    if rem > 0:
                        if s.rest_reason == "quota":
                            _set(r["s"], f"sp_{e}_s", text=f"⛔ cách ly {int(rem//60)}p", text_color=RD)
                        else:
                            _set(r["s"], f"sp_{e}_s", text=f"😴 nghỉ {int(rem)}s", text_color="#F9A825")
                    else:
                        _set(r["s"], f"sp_{e}_s", text="🟢 đang chạy", text_color=GR)
        except Exception:
            pass
        finally:
            if self._shopee_running:
                self.after(2000, self._sp_update_pool)

    def _sp_rolling_rate(self, window_min=10):
        """Tốc độ trượt 10 phút (video/phút) cho Shopee tab."""
        ts_deque = getattr(self, "_sp_done_timestamps", None)
        if not ts_deque: return 0.0
        now = time.time()
        cutoff = now - window_min * 60
        while ts_deque and ts_deque[0] < cutoff:
            ts_deque.popleft()
        if not ts_deque: return 0.0
        elapsed_min = (now - ts_deque[0]) / 60.0
        return len(ts_deque) / max(elapsed_min, 0.5)

    def _sp_eta_text(self):
        """Tốc độ + ETA cho Shopee tab."""
        sp_todo = getattr(self, "_sp_eta_products", None)
        if not sp_todo: return ""
        remaining = sum(1 for p in sp_todo if p.get("_status") not in ("success", "noretry"))
        rate = self._sp_rolling_rate()
        if rate <= 0:
            return f"⚡ Đang đo tốc độ…   ·   còn {remaining} SP"
        eta_min = remaining / rate
        fin = time.localtime(time.time() + eta_min * 60)
        dur = f"{int(eta_min // 60)}g{int(eta_min % 60):02d}p" if eta_min >= 60 else f"{int(eta_min)+1}p"
        return (f"⚡ {rate:.1f} video/phút   ·   còn {remaining} SP   ·   "
                f"dự kiến xong sau {dur}  (≈ {time.strftime('%H:%M', fin)})")

    def _shopee_start(self):
        if SV is None:
            messagebox.showerror("Lỗi", "Module shopeevideo.py không tải được."); return
        text = self._sp_products.get("1.0", "end").strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            messagebox.showwarning("Thiếu SP", "Hãy nhập ít nhất 1 sản phẩm (Tên SP | đường dẫn ảnh)."); return
        out_dir = self._sp_outdir.get().strip()
        if not out_dir:
            messagebox.showwarning("Thiếu thư mục", "Hãy chọn thư mục lưu video."); return
        if self._sp_no_model.get():
            model_images = []
        else:
            model_dir = self._sp_model_dir.get().strip()
            if model_dir and os.path.isdir(model_dir):
                model_images = SV.list_model_images(model_dir)
            else:
                model_images = []

        # Parse danh sách sản phẩm: "ảnh.jpg | Tên SP" (format mới) hoặc "Tên SP | ảnh.jpg" (format cũ)
        # Skip các dòng đã ✅ thành công
        products = []
        skipped = 0
        _img_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff'}
        for line_idx, line in enumerate(lines):
            clean = self._sp_strip_status(line)
            if line.startswith("✅ "):
                skipped += 1
                continue  # Đã thành công → bỏ qua
            if "|" in clean:
                parts = clean.split("|", 1)
                left = parts[0].strip()
                right = parts[1].strip()
                if os.path.splitext(left)[1].lower() in _img_exts:
                    img_path, name = left, right
                else:
                    name, img_path = left, right
            else:
                name = clean.strip()
                img_path = ""
            if name:
                resolved = self._sp_resolve_img(img_path)
                products.append({"name": name, "img": resolved, "_line_idx": line_idx})
        if skipped:
            self._sp_log_msg(f"⏭ Bỏ qua {skipped} SP đã thành công (✅)")
        if not products:
            messagebox.showwarning("Thiếu SP", "Không có SP nào cần xử lý (tất cả đã ✅ hoặc trống)."); return

        # Kiểm tra ảnh SP tồn tại
        for p in products:
            if p["img"] and not os.path.isfile(p["img"]):
                messagebox.showwarning("Ảnh không tồn tại", f"Không tìm thấy ảnh: {p['img']}"); return
            if not p["img"]:
                messagebox.showwarning("Thiếu ảnh SP", f"Sản phẩm '{p['name']}' chưa có ảnh."); return

        enabled_accs = [a for a in self.accounts if a.get("enabled", True) and a.get("role") != "donor"]
        if not enabled_accs:
            messagebox.showerror("Lỗi", "Không có tài khoản nào được chọn.\nHãy tích chọn ở tab Tài khoản."); return

        self._shopee_running = True
        self._shopee_stop_flag = False
        self._sp_btn_start.configure(state="disabled")
        self._sp_btn_stop.configure(state="normal")
        self._shopee_status.configure(text="⏳ Đang xử lý...")
        self._sp_log.configure(state="normal")
        self._sp_log.delete("1.0", "end")
        self._sp_log.configure(state="disabled")
        self._sp_result_card.pack_forget()

        aspect_key = E.VID_ASPECTS.get(self._sp_aspect.get(), "VIDEO_ASPECT_RATIO_PORTRAIT")
        img_aspect = E.IMG_ASPECTS.get(self._sp_aspect.get(), "IMAGE_ASPECT_RATIO_PORTRAIT")
        scene_choice = self._sp_scene.get()
        duration_sec = SV.parse_duration(self._sp_duration.get())
        lang_val = self._sp_lang.get()
        lang_code = "vi" if "Việt" in lang_val else ("id" if "Indonesia" in lang_val else ("my" if "Malaysia" in lang_val else ("ph" if "Philippines" in lang_val else "en")))
        sp_model_key = E.VID_MODELS.get(self._sp_model.get(), "veo_3_1_t2v_lite_low_priority")
        remove_wm = self._sp_remove_wm.get()
        skip_img = self._sp_skip_img.get()
        del_img = self._sp_del_img.get()
        ghep_anh = self._sp_ghep_anh.get()
        
        self.settings["shopee_aspect"] = self._sp_aspect.get()
        self.settings["shopee_scene"] = self._sp_scene.get()
        self.settings["shopee_duration"] = self._sp_duration.get()
        self.settings["shopee_lang"] = self._sp_lang.get()
        self.settings["shopee_model"] = self._sp_model.get()
        self.settings["shopee_remove_wm"] = self._sp_remove_wm.get()
        self.settings["shopee_skip_img"] = self._sp_skip_img.get()
        self.settings["shopee_del_img"] = del_img
        self.settings["shopee_ghep_anh"] = ghep_anh
        self.settings["shopee_review_style"] = self._sp_review_style.get()
        self.settings["shopee_ai_prompt"] = self._sp_ai_prompt.get()
        self.settings["shopee_no_model"] = self._sp_no_model.get()
        self.settings["shopee_model_dir"] = self._sp_model_dir.get().strip()
        self.settings["shopee_out_dir"] = self._sp_outdir.get().strip()
        # ── Cache widget values trên Main Thread trước khi spawn thread (tránh deadlock) ──
        _sp_cached_px_lines = [l.strip() for l in self.txt_proxy.get("1.0", "end").splitlines() if l.strip()]
        _sp_cached_use_laundering = self._sp_use_laundering.get()
        _sp_cached_tg_enabled = self.tg_enabled.get()
        _sp_cached_review_style = self._sp_review_style.get()
        _sp_cached_ai_prompt = self._sp_ai_prompt.get()
        _sp_cached_gemini_keys = [l.strip() for l in self.txt_gemini.get("1.0", "end").splitlines() if l.strip()]
        _sp_cached_groq_keys = [l.strip() for l in self.txt_groq_keys.get("1.0", "end").splitlines() if l.strip()]
        _sp_cached_wpa = 4
        _sp_cached_submit_max = 7.0
        # Gắn mô tả giọng nói cố định vào engine (ưu tiên nhập tay, nếu trống → dùng preset theo ngôn ngữ)
        manual_voice = self.ent_voice_desc.get().strip()
        E.VOICE_DESC = manual_voice if manual_voice else E.get_voice_for_lang(lang_code)
        
        def work():
            accs = [a for a in self.accounts if a.get("enabled", True) and a.get("cookie") and a.get("role") != "donor"]
            if not accs:
                self._sp_log_msg("❌ Chưa chọn tài khoản nào (Vui lòng bật 'Dùng' trong tab Tài khoản).")
                self.after(0, lambda: self._sp_btn_start.configure(state="normal"))
                self.after(0, lambda: self._sp_btn_stop.configure(state="disabled"))
                self._shopee_running = False
                return
            import base64 as b64mod
            results = []
            total = len(products)
            self._sp_results = results
            self._sp_total = total
            temp_dir = os.path.join(out_dir, "_temp_shopee")
            os.makedirs(temp_dir, exist_ok=True)
            os.makedirs(out_dir, exist_ok=True)

            # ── Khởi động Token Farm nếu user chọn mode token_farm ──
            self._start_recaptcha_farm()

            # ── Cập nhật proxy pool từ cache (đã đọc trên main thread) ──
            try:
                if _sp_cached_px_lines:
                    self.proxy_pool.load(_sp_cached_px_lines)
            except Exception:
                pass

            # ── Auth tài khoản (giống main tab) ──
            # 1. Khởi tạo Donor pool
            self._donor_states = []
            if _sp_cached_use_laundering:
                donor_accs = [a for a in self.accounts if a.get("role") == "donor" and a.get("cookie")]
                for da in donor_accs:
                    ds = AccountState(da)
                    if self.proxy_pool.has_proxies():
                        self.proxy_pool.assign(ds.email)
                    ds.proxy = self.proxy_pool.get_dict(ds.email)
                    self._donor_states.append(ds)
                if self._donor_states:
                    self._sp_log_msg(f"🛡️ {len(self._donor_states)} donor bypass 429 sẵn sàng")

            # 2. Nạp trực tiếp tất cả tài khoản chính (Không check trước để tránh delay/treo)
            self._sp_log_msg(f"🔑 Chuẩn bị {len(accs)} tài khoản chính...")
            states = []
            for a in accs:
                st = AccountState(a, submit_max=_sp_cached_submit_max)
                if self.proxy_pool.has_proxies():
                    px = self.proxy_pool.assign(st.email)
                    if px:
                        st.proxy = self.proxy_pool.get_dict(st.email)
                states.append(st)
                px_info = st.proxy.get('https', 'Không proxy') if st.proxy else 'Không proxy'
                self._sp_log_msg(f"  ✅ {st.email[:20]} sẵn sàng | Proxy: {px_info}")
            if not states:
                self._sp_log_msg("❌ Không tài khoản dùng được."); return

            self._sp_pool_states = states  # cho panel pool đọc live
            self.after(0, self._sp_update_pool)  # khởi chạy live update
            self.after(0, self._update_proxy_stats)

            model_media_cache = {}  # (email, model_path) → media_id
            cache_lock = threading.Lock()
            model_uploading_locks = {}

            # ── Gán ngẫu nhiên 1 người mẫu cho mỗi sản phẩm (nếu có) ──
            product_model_map = {}
            if model_images:
                for idx, prod in enumerate(products):
                    product_model_map[idx] = random.choice(model_images)

            wpa = _sp_cached_wpa  # số worker / account (đọc từ cài đặt giao diện)
            total_workers = len(states) * wpa
            self._sp_log_msg(f"🚀 {len(states)} tài khoản × {wpa} luồng = {total_workers} luồng. "
                             f"Bắt đầu {total} SP. Tốc độ TỰ ĐỘNG (AIMD).")
            if model_images:
                self._sp_log_msg(f"👤 Thư mục người mẫu: {model_dir} ({len(model_images)} ảnh)")
            else:
                self._sp_log_msg(f"👤 Không có ảnh người mẫu → dùng prompt mô tả MC tự động")
            self._sp_log_msg(f"🏖 Khung cảnh: {scene_choice}")
            self._sp_log_msg(f"⏱ Độ dài: {duration_sec}s ({len(SV.DURATION_MAP.get(duration_sec, [0,2]))} đoạn)")

            # ── Speed tracking ──
            self._sp_t0 = time.time()
            self._sp_done_timestamps = collections.deque()
            # Track products for ETA
            for p in products:
                p["_status"] = "pending"
            self._sp_eta_products = products

            # ── Shared Job Queue ──
            n_upload_threads = max(8, sum(getattr(s, "upload_threads", 4) for s in states) * 2)
            upload_sem = threading.Semaphore(n_upload_threads)
            jobq = queue.Queue()
            for idx, prod in enumerate(products):
                prod["_idx"] = idx
                prod["_cycles"] = 0
                jobq.put(prod)
            done_flag = [False]

            results_lock = threading.Lock()
            progress_count = [0]

            # ── Periodic Telegram Report ──
            _sp_last_tg = [time.time()]
            _SP_TG_INTERVAL = 3600
            def _sp_tg_periodic():
                while not done_flag[0] and not self._shopee_stop_flag:
                    time.sleep(60)
                    if time.time() - _sp_last_tg[0] >= _SP_TG_INTERVAL and _sp_cached_tg_enabled:
                        _sp_last_tg[0] = time.time()
                        msg = self._build_telegram_stats()
                        self._send_telegram(msg)
            threading.Thread(target=_sp_tg_periodic, daemon=True).start()

            # ══════════════════════════════════════════════════════════
            # process_one: xử lý 1 SP, trả 'success' | 'retry_soft' | ('fail', reason)
            # Giống _run.process ở main tab: dùng AIMD gating cho submit_video
            # ══════════════════════════════════════════════════════════
            def process_one(st, prod):
                idx = prod["_idx"]
                line_idx = prod.get("_line_idx", idx)
                if self._shopee_stop_flag:
                    return "retry_soft"

                if not st.ensure_auth():
                    st.rest(AUTH_REST, "auth")
                    return "retry_soft"
                bearer, project, cookie = st.bearer, st.project, st.cookie

                self._sp_update_line_status(line_idx, "running")
                self._sp_log_msg(f"\n{'='*50}")
                self._sp_log_msg(f"📦 [{idx+1}/{total}] {prod['name']} [{st.email[:16]}]")

                # --- Tính tên file ---
                img_basename = os.path.splitext(os.path.basename(prod["img"]))[0] if prod.get("img") else ""
                safe_name = img_basename if img_basename else SV.clean_filename(prod["name"])
                composite_path = os.path.join(temp_dir, f"composite_{safe_name}.jpg")
                meta_path = os.path.join(temp_dir, f"meta_{safe_name}.json")

                # Chức năng Bỏ qua các SP đã tạo ảnh
                if skip_img and os.path.isfile(composite_path) and os.path.getsize(composite_path) > 1000:
                    self._sp_log_msg(f"⏭ Đã có ảnh cho {safe_name} → Bỏ qua luồng tạo Video")
                    return ("success", "Bỏ qua video do đã có ảnh (theo cài đặt)")

                # --- Load metadata phiên trước ---
                meta_loaded = False
                if os.path.isfile(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as mf:
                            meta = json.loads(mf.read())
                        scene_name = meta["scene_name"]
                        scene_en = meta["scene_en"]
                        model_img = meta["model_img"]
                        prompts_saved = meta.get("prompts")
                        meta_loaded = True
                        self._sp_log_msg(f"📋 Dùng metadata phiên trước: cảnh={scene_name}")
                    except Exception:
                        meta_loaded = False

                if not meta_loaded:
                    model_img = product_model_map.get(idx)  # None nếu không có ảnh người mẫu
                    scene_name, scene_en = SV.pick_scene(scene_choice, lang=lang_code)
                    prompts_saved = None

                # ═══ PHASE 1: TẠO ẢNH HOÀN THIỆN ═══
                gen_ok = False
                img_result = None
                if not model_img:
                    # Không có ảnh người mẫu → dùng ảnh SP + fallback prompts tự mô tả MC
                    prod["_use_fallback_prompts"] = True
                    if os.path.isfile(composite_path) and os.path.getsize(composite_path) > 1000:
                        self._sp_log_msg(f"⚡ Phase 1: Dùng ảnh đã có (không có người mẫu)")
                    else:
                        self._sp_log_msg(f"📸 Không có ảnh người mẫu → dùng ảnh SP làm reference")
                        try:
                            import shutil
                            shutil.copy2(prod["img"], composite_path)
                            self._sp_log_msg(f"  ✅ Dùng ảnh SP: {os.path.basename(prod['img'])}")
                        except Exception as ex:
                            return ("fail", f"Copy ảnh SP lỗi: {ex}")
                elif os.path.isfile(composite_path) and os.path.getsize(composite_path) > 1000:
                    self._sp_log_msg(f"⚡ Phase 1: Dùng ảnh đã có")
                else:
                    self._sp_log_msg("🎨 Phase 1: Tạo ảnh hoàn thiện...")
                    self._sp_log_msg(f"  👤 Người mẫu: {os.path.basename(model_img)}")

                    # --- Kiểm tra quota ảnh TRƯỚC khi upload (tránh tốn bandwidth vô ích) ---
                    all_img_exhausted = all(s.img_quota_exhausted for s in states)

                    if st.img_quota_exhausted and not all_img_exhausted:
                        # Account này hết quota ảnh nhưng còn account khác → requeue ngay
                        self._sp_log_msg(f"  ⏭ {st.email[:16]}: hết quota ảnh → chuyển account khác")
                        return "retry_soft"

                    if all_img_exhausted:
                        # TẤT CẢ account hết quota ảnh → dùng ảnh SP làm reference trực tiếp
                        # Prompt video sẽ MÔ TẢ MC (cô gái cầm SP) bằng text thay vì dùng ảnh composite
                        prod["_use_fallback_prompts"] = True
                        self._sp_log_msg(f"  📸 Hết quota ảnh → dùng ảnh SP làm reference + prompt mô tả MC")
                        try:
                            import shutil
                            shutil.copy2(prod["img"], composite_path)
                            self._sp_log_msg(f"  ✅ Dùng ảnh SP: {os.path.basename(prod['img'])}")
                        except Exception as ex:
                            return ("fail", f"Copy ảnh SP lỗi: {ex}")
                    else:
                        # Còn quota → upload + generate qua API

                        # Upload ảnh người mẫu (cache)
                        while True:
                            with cache_lock:
                                model_mid = model_media_cache.get((st.email, model_img))
                                if model_mid:
                                    break
                                ev = model_uploading_locks.get((st.email, model_img))
                                if ev is None:
                                    ev = threading.Event()
                                    model_uploading_locks[(st.email, model_img)] = ev
                                    is_uploader = True
                                else:
                                    is_uploader = False
                            if is_uploader:
                                break
                            else:
                                self._sp_log_msg(f"  ⏳ {st.email[:16]}: Chờ luồng khác tải xong ảnh người mẫu...")
                                ev.wait()

                        if not model_mid:
                            if not st.acquire_submit(lambda: self._shopee_stop_flag):
                                with cache_lock:
                                    ev = model_uploading_locks.pop((st.email, model_img), None)
                                    if ev: ev.set()
                                return "retry_soft"
                            if not st.acquire_upload(lambda: self._shopee_stop_flag):
                                st.release_submit()
                                with cache_lock:
                                    ev = model_uploading_locks.pop((st.email, model_img), None)
                                    if ev: ev.set()
                                return "retry_soft"
                            try:
                                time.sleep(random.uniform(2, 5))  # stagger ngoài semaphore → tránh giữ lock
                                st.wait_upload_spacing(10.0)
                                upload_sem.acquire()  # CHỜ đến lượt
                                self._sp_log_msg(f"  📤 [{st.email[:12]}] Upload ảnh người mẫu (luồng {st.upload_inflight}/{st.upload_threads})...")
                                try:
                                    mid = E.upload_image(bearer, project, model_img, proxy=st.proxy)
                                finally:
                                    upload_sem.release()
                                    st.release_submit()
                            finally:
                                st.release_upload()
                            if mid == "throttle":
                                st.on_throttle()
                                bypassed_mid = None
                                if self._donor_states and _sp_cached_use_laundering:
                                    donors_copy = list(self._donor_states)
                                    random.shuffle(donors_copy)
                                    for donor_st in donors_copy:
                                        if donor_st.ensure_auth():
                                            self._sp_log_msg(f"  {st.email[:16]}: 429 model image → bypass qua donor {donor_st.email[:16]}...")
                                            bypassed_mid = E.upload_image_via_donor(
                                                donor_st.bearer, donor_st.project,
                                                bearer, project,
                                                model_img,
                                                proxy=donor_st.proxy,
                                                main_proxy=st.proxy
                                            )
                                            if bypassed_mid == "quota_hard":
                                                st.img_quota_exhausted = True
                                                self._sp_log_msg(f"  ⛔ {st.email[:16]}: hết quota tạo ẢNH (phát hiện khi bypass) → đánh dấu")
                                                bypassed_mid = None
                                                break
                                            if bypassed_mid and bypassed_mid != "quota_hard":
                                                self._sp_log_msg(f"  Bypass model image thành công! [{donor_st.email[:16]}]")
                                                mid = bypassed_mid
                                                break
                                if not bypassed_mid:
                                    new_px, old_px = self.proxy_pool.rotate(st.email)
                                    if new_px:
                                        st.proxy = self.proxy_pool.get_dict(st.email)
                                        self._sp_log_msg(f"  🔄 {st.email[:16]}: upload 429 → đổi proxy")
                                    elif st.should_log_throttle():
                                        self._sp_log_msg(f"  ⏳ {st.email[:16]}: upload 429 — cần proxy hoặc chờ hết rate-limit")
                                    rest_s = st.on_upload_throttle()
                                    self._sp_log_msg(f"  😴 {st.email[:16]}: nghỉ {rest_s}s (lần {st.upload_throttle_streak})")
                                    with cache_lock:
                                        ev = model_uploading_locks.pop((st.email, model_img), None)
                                        if ev: ev.set()
                                    return "retry_soft"
                            if mid == "forbidden":
                                st.i2v_blocked = True
                                self._sp_log_msg(f"  🚫 {st.email[:16]}: cấm upload (403)")
                                with cache_lock:
                                    ev = model_uploading_locks.pop((st.email, model_img), None)
                                    if ev: ev.set()
                                return "retry_soft"
                            if mid and mid not in ("forbidden", "throttle"):
                                st.on_submit_ok()
                                st.on_upload_ok()
                                with cache_lock:
                                    model_media_cache[(st.email, model_img)] = mid
                                    ev = model_uploading_locks.pop((st.email, model_img), None)
                                    if ev: ev.set()
                                model_mid = mid
                            else:
                                with cache_lock:
                                    ev = model_uploading_locks.pop((st.email, model_img), None)
                                    if ev: ev.set()
                                return ("fail", "Upload ảnh người mẫu lỗi")

                        # Upload ảnh SP
                        if not st.acquire_submit(lambda: self._shopee_stop_flag):
                            return "retry_soft"
                        if not st.acquire_upload(lambda: self._shopee_stop_flag):
                            st.release_submit()
                            return "retry_soft"
                        try:
                            time.sleep(random.uniform(1, 3))  # stagger ngoài semaphore → tránh giữ lock
                            upload_sem.acquire()
                            self._sp_log_msg(f"  📤 [{st.email[:12]}] Upload ảnh sản phẩm (luồng {st.upload_inflight}/{st.upload_threads})...")
                            try:
                                product_mid = E.upload_image(bearer, project, prod["img"], proxy=st.proxy)
                            finally:
                                upload_sem.release()
                                st.release_submit()
                        finally:
                            st.release_upload()
                        if product_mid == "throttle":
                            st.on_throttle()
                            bypassed_mid = None
                            if self._donor_states and _sp_cached_use_laundering:
                                donors_copy = list(self._donor_states)
                                random.shuffle(donors_copy)
                                for donor_st in donors_copy:
                                    if donor_st.ensure_auth():
                                        self._sp_log_msg(f"  {st.email[:16]}: 429 product image → bypass qua donor {donor_st.email[:16]}...")
                                        bypassed_mid = E.upload_image_via_donor(
                                            donor_st.bearer, donor_st.project,
                                            bearer, project,
                                            prod["img"],
                                            proxy=donor_st.proxy,
                                            main_proxy=st.proxy
                                        )
                                        if bypassed_mid == "quota_hard":
                                            st.img_quota_exhausted = True
                                            self._sp_log_msg(f"  ⛔ {st.email[:16]}: hết quota tạo ẢNH (phát hiện khi bypass SP) → đánh dấu")
                                            bypassed_mid = None
                                            break
                                        if bypassed_mid and bypassed_mid != "quota_hard":
                                            self._sp_log_msg(f"  Bypass product image thành công! [{donor_st.email[:16]}]")
                                            product_mid = bypassed_mid
                                            break
                            if not bypassed_mid:
                                new_px, _ = self.proxy_pool.rotate(st.email)
                                if new_px:
                                    st.proxy = self.proxy_pool.get_dict(st.email)
                                    self._sp_log_msg(f"  🔄 {st.email[:16]}: upload SP 429 → đổi proxy")
                                rest_s = st.on_upload_throttle()
                                self._sp_log_msg(f"  😴 {st.email[:16]}: nghỉ {rest_s}s (lần {st.upload_throttle_streak})")
                                return "retry_soft"
                        if not product_mid or product_mid in ("forbidden", "throttle"):
                            return ("fail", "Upload ảnh SP lỗi")
                        st.on_submit_ok()
                        st.on_upload_ok()

                        # Generate ảnh hoàn thiện qua API (AIMD gating)
                        img_prompt = SV.build_image_prompt(prod["name"], scene_en, lang=lang_code)
                        self._sp_log_msg(f"  📝 Prompt ảnh: {img_prompt[:100]}...")
                        gen_ok = False
                        img_result = None
                        for attempt in range(3):
                            if self._shopee_stop_flag: break
                            if attempt > 0:
                                st.ensure_auth(force=True)
                                bearer, project = st.bearer, st.project
                            if attempt < 2:
                                img_inputs = [
                                    {"imageInputType": "IMAGE_INPUT_TYPE_REFERENCE", "name": model_mid},
                                    {"imageInputType": "IMAGE_INPUT_TYPE_REFERENCE", "name": product_mid},
                                ]
                            else:
                                img_inputs = [{"imageInputType": "IMAGE_INPUT_TYPE_REFERENCE", "name": model_mid}]
                                self._sp_log_msg(f"  🔄 Fallback: chỉ dùng ảnh người mẫu")
                            if not st.acquire_submit(lambda: self._shopee_stop_flag):
                                return "retry_soft"
                            try:
                                status, img_result = E.generate_image(
                                    bearer, project, img_prompt,
                                    seed=random.randint(1, 999999),
                                    aspect=img_aspect, image_inputs=img_inputs, proxy=st.proxy)
                            finally:
                                st.release_submit()
                            if status == "ok" and img_result:
                                st.on_submit_ok(); gen_ok = True; break
                            if status == "quota_hard":
                                st.img_quota_exhausted = True
                                self._sp_log_msg(f"  ⛔ {st.email[:16]}: hết quota tạo ẢNH → đánh dấu, chuyển account")
                                return "retry_soft"
                            self._sp_log_msg(f"  ⚠️ generate_image thử {attempt+1}/3: {status}")
                            time.sleep(3)

                        if not gen_ok:
                            return ("fail", "Tạo ảnh AI thất bại")

                        # Lưu ảnh
                        try:
                            if img_result.get("fife"):
                                E.download_url(img_result["fife"], composite_path, proxy=st.proxy)
                            elif img_result.get("b64"):
                                with open(composite_path, "wb") as wf:
                                    wf.write(b64mod.b64decode(img_result["b64"]))
                            self._sp_log_msg(f"  ✅ Ảnh hoàn thiện: {os.path.basename(composite_path)}")
                        except Exception as ex:
                            return ("fail", f"Lưu ảnh lỗi: {ex}")

                # ═══ PHASE 2: SINH PROMPT VIDEO ═══
                use_fallback = prod.get("_use_fallback_prompts", False)
                if prompts_saved and not use_fallback and len(prompts_saved) == len(SV.DURATION_MAP.get(duration_sec, [])):
                    prompts = prompts_saved
                    self._sp_log_msg(f"📝 Phase 2: Dùng {len(prompts)} prompt đã lưu")
                elif use_fallback:
                    prompts = SV.build_video_prompts_fallback(prod["name"], scene_en, duration_sec, lang=lang_code, review_style=_sp_cached_review_style)
                    self._sp_log_msg(f"📝 Phase 2: Sinh {len(prompts)} prompt FALLBACK (mô tả MC trong text)")
                else:
                    prompts = None
                    if _sp_cached_ai_prompt in ("Gemini", "Groq"):
                        ai_mode_lower = "gemini" if _sp_cached_ai_prompt == "Gemini" else "groq"
                        self._sp_log_msg(f"📝 Phase 2: Đang dùng AI ({_sp_cached_ai_prompt}) viết prompt cho '{prod['name']}'...")
                        prompts = self._sv_ai_gen_prompts(
                            prod["name"], scene_en, len(SV.DURATION_MAP.get(duration_sec, [0, 2])),
                            duration_sec, lang_code, _sp_cached_review_style,
                            mode=ai_mode_lower, gemini_keys=_sp_cached_gemini_keys, groq_keys=_sp_cached_groq_keys
                        )
                    if prompts:
                        self._sp_log_msg(f"📝 Phase 2: Sinh {len(prompts)} prompt qua AI ({_sp_cached_ai_prompt})")
                    else:
                        prompts = SV.build_video_prompts(prod["name"], scene_en, duration_sec, lang=lang_code, review_style=_sp_cached_review_style)
                        self._sp_log_msg(f"📝 Phase 2: Sinh {len(prompts)} prompt mới (Template)")
                n_segments = len(prompts)

                # Lưu metadata
                if not meta_loaded:
                    try:
                        meta_data = {
                            "scene_name": scene_name, "scene_en": scene_en,
                            "model_img": model_img, "prompts": prompts,
                            "lang": lang_code, "duration": duration_sec,
                        }
                        with open(meta_path, "w", encoding="utf-8") as mf:
                            mf.write(json.dumps(meta_data, ensure_ascii=False, indent=2))
                    except Exception:
                        pass
                _model_label = os.path.basename(model_img) if model_img else "Tự mô tả (prompt)"
                self._sp_log_msg(f"🏖 Cảnh: {scene_name} | 👤 Mẫu: {_model_label}")

                # ═══ PHASE 3: TẠO VIDEO THÀNH PHẦN (AIMD gating) ═══
                self._sp_log_msg(f"🎬 Phase 3: Tạo {n_segments} video thành phần...")
                clip_paths = []
                missing_segments = []
                for seg_i, vid_prompt in enumerate(prompts):
                    clip_path = os.path.join(temp_dir, f"clip_{safe_name}_{seg_i+1}.mp4")
                    if os.path.isfile(clip_path) and os.path.getsize(clip_path) > 5000:
                        self._sp_log_msg(f"  ⚡ Đoạn {seg_i+1}/{n_segments}: Đã có, bỏ qua")
                        clip_paths.append((seg_i, clip_path))
                    else:
                        missing_segments.append((seg_i, clip_path, vid_prompt))

                if missing_segments:
                    self._sp_log_msg(f"  📹 Cần tạo {len(missing_segments)}/{n_segments} đoạn")
                    # Upload ảnh hoàn thiện (hoặc dùng lại từ Phase 1)
                    comp_mid = None
                    if gen_ok and img_result and img_result.get("name"):
                        comp_mid = img_result["name"]
                        self._sp_log_msg(f"  ⚡ Tái sử dụng mediaId ảnh hoàn thiện từ Phase 1: {comp_mid[:15]}...")
                    else:
                        self._sp_log_msg("  📤 Upload ảnh hoàn thiện...")
                        if not st.acquire_submit(lambda: self._shopee_stop_flag):
                            return "retry_soft"
                        upload_sem.acquire()
                        try:
                            comp_mid = E.upload_image(bearer, project, composite_path, proxy=st.proxy)
                        finally:
                            upload_sem.release()
                            st.release_submit()
                        if comp_mid == "throttle":
                            st.on_throttle()
                            bypassed_mid = None
                            if self._donor_states and _sp_cached_use_laundering:
                                donors_copy = list(self._donor_states)
                                random.shuffle(donors_copy)
                                for donor_st in donors_copy:
                                    if donor_st.ensure_auth():
                                        self._sp_log_msg(f"  {st.email[:16]}: 429 composite image → bypass qua donor {donor_st.email[:16]}...")
                                        bypassed_mid = E.upload_image_via_donor(
                                            donor_st.bearer, donor_st.project,
                                            bearer, project,
                                            composite_path,
                                            proxy=donor_st.proxy,
                                            main_proxy=st.proxy
                                        )
                                        if bypassed_mid == "quota_hard":
                                            st.img_quota_exhausted = True
                                            self._sp_log_msg(f"  ⛔ {st.email[:16]}: hết quota tạo ẢNH (phát hiện khi bypass composite) → đánh dấu")
                                            bypassed_mid = None
                                            break
                                        if bypassed_mid and bypassed_mid != "quota_hard":
                                            self._sp_log_msg(f"  Bypass composite image thành công! [{donor_st.email[:16]}]")
                                            comp_mid = bypassed_mid
                                            break
                            if not bypassed_mid:
                                new_px, _ = self.proxy_pool.rotate(st.email)
                                if new_px:
                                    st.proxy = self.proxy_pool.get_dict(st.email)
                                    self._sp_log_msg(f"  🔄 {st.email[:16]}: upload composite 429 → đổi proxy")
                                rest_s = st.on_upload_throttle()
                                self._sp_log_msg(f"  😴 {st.email[:16]}: nghỉ {rest_s}s (lần {st.upload_throttle_streak})")
                                return "retry_soft"
                    if not comp_mid or comp_mid in ("forbidden", "throttle"):
                        return ("fail", "Upload ảnh hoàn thiện lỗi")
                    st.on_submit_ok()
                    st.on_upload_ok()

                    vid_seed = random.randint(1, 999999)
                    submitted_ops = []
                    for seg_i, clip_path, vid_prompt in missing_segments:
                        if self._shopee_stop_flag: break
                        self._sp_log_msg(f"  📹 Đoạn {seg_i+1}/{n_segments}: Đang submit...")



                        vid_ok = False
                        ops = None
                        for attempt in range(GEN_ATTEMPTS):
                            if self._shopee_stop_flag: break
                            if attempt > 0 and attempt % 3 == 0:
                                st.ensure_auth(force=True)
                                bearer, project = st.bearer, st.project

                            # ★ AIMD gating & Lock per-account: chờ slot submit và giữ khóa độc quyền giãn cách 4-6s (Rule #2)
                            if not st.acquire_submit(lambda: self._shopee_stop_flag):
                                return "retry_soft"
                            try:
                                with st.submit_guard(4.0, 6.0):
                                    v_status, ops = E.submit_video(
                                        bearer, project, vid_prompt,
                                        seed=vid_seed, aspect=aspect_key,
                                        model=sp_model_key, ref_media_id=comp_mid, proxy=st.proxy)
                            finally:
                                st.release_submit()

                            if v_status == "ok" and ops:
                                st.on_submit_ok()  # AIMD +
                                vid_ok = True; break
                            elif v_status == "throttle":
                                st.on_throttle()
                                if self.proxy_pool and self.proxy_pool.has_proxies():
                                    new_px, old_px = self.proxy_pool.rotate(st.email)
                                    if new_px:
                                        st.proxy = self.proxy_pool.get_dict(st.email)
                                        if st.rest_remaining() > 15:
                                            st.rest(15, "submit_throttle")
                                        self._sp_log_msg(f"    🔄 {st.email[:16]}: Submit 429 → Tự động xoay Proxy mới ({st.rest_remaining():.0f}s làm mát)...")
                                if st.rest_remaining() > 0 and st.should_log_throttle():
                                    self._sp_log_msg(f"    ⏳ {st.email[:16]}: 429 — nghỉ {st.rest_remaining():.0f}s")
                                    time.sleep(min(3.0, st.rest_remaining()))
                            elif v_status == "quota_hard":
                                st.rest(QUOTA_HARD_REST, "quota")
                                self._sp_log_msg(f"    ⛔ {st.email[:16]} HẾT QUOTA → cách ly, đổi tài khoản")
                                return "retry_soft"
                            elif v_status == "auth":
                                if attempt == 0 and st.ensure_auth(force=True):
                                    bearer, project = st.bearer, st.project; continue
                                st.rest(AUTH_REST, "auth"); return "retry_soft"
                            elif v_status in ("ratelimit", "ip_block"):
                                st.on_throttle()
                                new_px, _ = self.proxy_pool.rotate(st.email)
                                if new_px:
                                    st.proxy = self.proxy_pool.get_dict(st.email)
                                    self._sp_log_msg(f"    🔄 {st.email[:16]}: IP block → đổi proxy")
                                time.sleep(1.5 + random.uniform(0, 1.0))
                            else:
                                time.sleep(BYPASS_QUICK + random.uniform(0, 0.4))

                        if not vid_ok:
                            self._sp_log_msg(f"  ❌ Đoạn {seg_i+1} submit thất bại")
                            return "retry_soft"
                        submitted_ops.append((seg_i, clip_path, ops))

                    # Poll chờ render song song và download
                    for seg_i, clip_path, ops in submitted_ops:
                        if self._shopee_stop_flag: break
                        self._sp_log_msg(f"  ⏳ Đoạn {seg_i+1}: Chờ render...")
                        kind, poll_result, _ = E.poll_video(bearer, ops, cookie=cookie, max_attempts=POLL_MAX, interval=8, proxy=st.proxy)
                        if kind != "done":
                            self._sp_log_msg(f"  ❌ Đoạn {seg_i+1} render thất bại: {kind} — {poll_result}")
                            # Vi phạm chính sách → retry vô ích, dừng SP này luôn
                            if kind == "failed" and E.is_policy_reason(poll_result, include_audio=True):
                                self._sp_log_msg(f"  ⚠️ Vi phạm chính sách ({poll_result}) → bỏ SP này")
                                return ("fail", "vi phạm cs")
                            return "retry_soft"

                        # Download clip
                        sz = E.download_video(poll_result, cookie, clip_path, proxy=st.proxy)
                        if sz == E.DL_PROXY_DEAD:
                            new_px = self.proxy_pool.mark_dead(st.email)
                            st.proxy = self.proxy_pool.get_dict(st.email) if new_px else None
                            self._sp_log_msg(f"  🔄 {st.email[:16]}: proxy chết khi tải clip → {'đổi proxy mới' if new_px else 'hết proxy, dùng IP máy'}")
                            return "retry_soft"
                        # LƯU Ý: phải so sánh sz > 0. Trước đây dùng `if sz and ...` nên sentinel
                        # âm (-1/-2) là truthy → clip lỗi bị ghi nhận "OK" và ghép vào video.
                        if sz > 0 and os.path.exists(clip_path):
                            self._sp_log_msg(f"  ✅ Đoạn {seg_i+1}: OK ({sz//1024}KB)")
                            clip_paths.append((seg_i, clip_path))
                        else:
                            self._sp_log_msg(f"  ❌ Đoạn {seg_i+1}: Download thất bại (mã {sz})")
                            return "retry_soft"
                else:
                    self._sp_log_msg(f"  ⚡ Tất cả {n_segments} đoạn đã có từ phiên trước!")

                # Sắp xếp + ghép
                clip_paths.sort(key=lambda x: x[0])
                ordered_clips = [p for _, p in clip_paths]

                # ═══ PHASE 4: GHÉP VIDEO HOÀN CHỈNH ═══
                if len(ordered_clips) < n_segments:
                    existing_indices = {i for i, _ in clip_paths}
                    missing_nums = [str(i+1) for i in range(n_segments) if i not in existing_indices]
                    self._sp_log_msg(f"❌ Thiếu đoạn video: [{', '.join(missing_nums)}]")
                    return ("fail", f"Thiếu đoạn {', '.join(missing_nums)}")

                out_path = os.path.join(out_dir, f"{safe_name}.mp4")
                counter = 1
                while os.path.exists(out_path):
                    out_path = os.path.join(out_dir, f"{safe_name}_{counter}.mp4")
                    counter += 1

                self._sp_log_msg(f"🔧 Phase 4: Ghép {len(ordered_clips)} clip...")
                ok = SV.concat_videos(ordered_clips, out_path, log=self._sp_log_msg)

                if ok and os.path.exists(out_path):
                    sz = os.path.getsize(out_path)
                    self._sp_log_msg(f"✅ VIDEO HOÀN CHỈNH: {os.path.basename(out_path)} ({sz//1024}KB)")
                    if remove_wm:
                        self._sp_log_msg("🧹 Phase 5: Xóa watermark Veo...")
                        SV.remove_veo_watermark(out_path, log=self._sp_log_msg)

                    # --- Ghép ảnh khi hoàn thành (chỉ áp dụng cho video 8s) ---
                    ghep_anh_loi = False
                    if ghep_anh and duration_sec == 8:
                        self._sp_log_msg("  🎞 Bắt đầu ghép ảnh outro tạo video 12s...")
                        merged_path = os.path.join(temp_dir, f"merged12s_{safe_name}.mp4")
                        ok_m, err_m = self._run_ghep_anh_12s(out_path, composite_path, merged_path)
                        if ok_m and os.path.exists(merged_path):
                            try: os.remove(out_path)
                            except: pass
                            import shutil as _sh
                            _sh.move(merged_path, out_path)
                            self._sp_log_msg("    ✅ Ghép ảnh outro 12s thành công!")
                        else:
                            self._sp_log_msg(f"    ⚠ Ghép ảnh lỗi: {err_m}. Giữ video gốc 8s.")
                            ghep_anh_loi = True

                    for cp in ordered_clips:
                        try:
                            if os.path.isfile(cp): os.remove(cp)
                        except Exception: pass
                    for f_del in (composite_path, meta_path):
                        try:
                            if os.path.isfile(f_del): os.remove(f_del)
                        except Exception: pass
                    # Xóa ảnh SP gốc nếu bật tùy chọn
                    if del_img and prod.get("img") and os.path.isfile(prod["img"]):
                        try:
                            os.remove(prod["img"])
                            self._sp_log_msg(f"🗑 Đã xóa ảnh gốc: {os.path.basename(prod['img'])}")
                        except Exception:
                            pass
                    self._sp_log_msg(f"🗑 Đã dọn {len(ordered_clips)} clip + composite + metadata")
                    return "success"
                else:
                    return ("fail", "Ghép video FFmpeg thất bại")

            # ══════════════════════════════════════════════════════════
            # worker: giống main tab — mỗi account chạy wpa worker,
            # pull job từ hàng đợi chung, AIMD tự chỉnh tốc độ submit
            # ══════════════════════════════════════════════════════════
            SP_JOB_MAX_CYCLES = 10

            def worker(st, initial_delay=0.0):
                if initial_delay > 0:
                    time.sleep(initial_delay + random.uniform(0.1, 0.4))
                while not self._shopee_stop_flag:
                    if not st.acc.get("enabled", True):
                        time.sleep(1); continue
                    w = st.rest_remaining()
                    if w > 0:
                        time.sleep(min(w, 3)); continue
                    if not st.ensure_auth():
                        time.sleep(2); continue
                    with st.blk:
                        if st.busy >= st.get_current_max_busy():
                            time.sleep(0.5); continue
                    try:
                        prod = jobq.get(timeout=2)
                    except queue.Empty:
                        if done_flag[0]: return
                        continue
                    if prod.get("_status") == "success":
                        continue
                    prod["_cycles"] = prod.get("_cycles", 0) + 1
                    if prod["_cycles"] > SP_JOB_MAX_CYCLES:
                        prod["_status"] = "noretry"
                        line_idx = prod.get("_line_idx", prod["_idx"])
                        self._sp_update_line_status(line_idx, "error")
                        with results_lock:
                            results.append({"name": prod["name"], "img": prod["img"],
                                            "status": "error", "output": None,
                                            "error": f"Hết {SP_JOB_MAX_CYCLES} lượt thử"})
                            progress_count[0] += 1
                            c = progress_count[0]
                        self.after(0, lambda c=c, t=total: self._sp_progress.set(c / max(t, 1)))
                        self.after(0, lambda c=c, t=total: self._shopee_status.configure(text=f"⏳ {c}/{t}..."))
                        continue

                    st.busy_inc()
                    try:
                        outcome = process_one(st, prod)
                    except Exception as e:
                        self._sp_log_msg(f"  ❌ Lỗi bất ngờ [{prod['name'][:30]}]: {e}")
                        outcome = ("fail", str(e))
                    finally:
                        st.busy_dec()

                    line_idx = prod.get("_line_idx", prod["_idx"])
                    if outcome == "success":
                        prod["_status"] = "success"
                        st.wins += 1; st.clear_rest()
                        self._sp_update_line_status(line_idx, "success")
                        ts_deque = getattr(self, "_sp_done_timestamps", None)
                        if ts_deque is not None: ts_deque.append(time.time())
                        with results_lock:
                            results.append({"name": prod["name"], "img": prod["img"],
                                            "status": "success", "output": None, "error": None})
                            progress_count[0] += 1
                            c = progress_count[0]
                        self.after(0, lambda c=c, t=total: self._sp_progress.set(c / max(t, 1)))
                        self.after(0, lambda c=c, t=total: self._shopee_status.configure(text=f"⏳ {c}/{t}..."))
                    elif outcome == "retry_soft":
                        prod["_status"] = "pending"
                        jobq.put(prod)  # requeue → account khỏe hơn nhặt
                    else:
                        st.fails += 1
                        reason = outcome[1] if isinstance(outcome, tuple) and len(outcome) > 1 else "lỗi"
                        prod["_status"] = "noretry"
                        self._sp_update_line_status(line_idx, "error")
                        with results_lock:
                            results.append({"name": prod["name"], "img": prod["img"],
                                            "status": "error", "output": None, "error": reason})
                            progress_count[0] += 1
                            c = progress_count[0]
                        self.after(0, lambda c=c, t=total: self._sp_progress.set(c / max(t, 1)))
                        self.after(0, lambda c=c, t=total: self._shopee_status.configure(text=f"⏳ {c}/{t}..."))

            # ── Khởi chạy workers: cấp đúng số luồng st.max_busy, so le 0.8s giữa các TK ──
            threads = []
            for acc_idx, st in enumerate(states):
                stagger_delay = acc_idx * 0.8
                for _ in range(st.max_busy):
                    t = threading.Thread(target=worker, args=(st, stagger_delay), daemon=True)
                    t.start(); threads.append(t)

            # ── Chờ tất cả job hoàn thành ──
            def _drain():
                while not self._shopee_stop_flag:
                    if all(p.get("_status") in ("success", "noretry") for p in products):
                        return
                    time.sleep(1.5)
            _drain()

            done_flag[0] = True
            for t in threads:
                t.join(timeout=5)

            # ── Kết quả ──
            self.after(0, lambda: self._sp_progress.set(1.0))
            success = sum(1 for r in results if r["status"] == "success")
            errors = sum(1 for r in results if r.get("error"))
            elapsed = time.time() - self._sp_t0
            h, m = int(elapsed // 3600), int((elapsed % 3600) // 60)
            rate = self._sp_rolling_rate()
            self._sp_log_msg(f"\n{'='*50}")
            self._sp_log_msg(f"🏁 Kết quả: {success}/{total} video thành công.")
            if skipped:
                self._sp_log_msg(f"⏭ Đã bỏ qua {skipped} SP thành công trước đó")
            self.after(0, lambda: self._shopee_status.configure(
                text=f"✅ Xong: {success}/{total} video"))
            self.after(0, self._sp_update_count)
            self._sp_show_results(results)

            # ── Telegram Final Report ──
            done_flag[0] = True
            if _sp_cached_tg_enabled:
                acc_lines = []
                for st in states:
                    acc_lines.append(f"  {st.email[:22]}: ✅{st.wins} ❌{st.fails} ⚡{int(st.submit_limit)}")
                tg_msg = (f"🏁 Shopee Video — HOÀN TẤT\n"
                          f"{'='*30}\n"
                          f"✅ Thành công: {success}/{total}\n"
                          f"❌ Lỗi: {errors}\n"
                          f"⏭ Bỏ qua: {skipped}\n"
                          f"⚡ Tốc độ TB: {rate:.1f} video/phút\n"
                          f"⏰ Thời gian: {h}h{m}m\n"
                          f"👥 Tài khoản:\n" + "\n".join(acc_lines))
                if self._shopee_stop_flag:
                    tg_msg += "\n\n⚠️ Đã dừng bởi người dùng."
                self._send_telegram(tg_msg)

            # Phục hồi trạng thái
            self._sp_pool_states = None
            self.after(0, lambda: self._sp_btn_start.configure(state="normal"))
            self.after(0, lambda: self._sp_btn_stop.configure(state="disabled"))
            self._shopee_running = False

        threading.Thread(target=work, daemon=True).start()


    def _shopee_stop(self):
        self._shopee_stop_flag = True
        self._sp_btn_stop.configure(state="disabled")
        self._shopee_status.configure(text="⏹ Đang dừng...")
        self._sp_log_msg("⏹ Đã gửi lệnh dừng, chờ bước hiện tại hoàn tất...")

    def _shopee_open_folder(self):
        out_dir = self._sp_outdir.get().strip()
        if out_dir and os.path.isdir(out_dir):
            os.startfile(out_dir)
        else:
            messagebox.showinfo("Chưa có", "Thư mục output chưa tồn tại hoặc chưa được chọn.")

    def _sp_show_results(self, results):
        def _do():
            for w in self._sp_result_scroll.winfo_children():
                w.destroy()
            # Giữ ref ảnh thumbnail để GC không xóa
            self._sp_thumb_refs = []
            success = sum(1 for r in results if r["status"] == "success")
            fail = len(results) - success
            self._sp_result_summary.configure(
                text=f"✅ {success} thành công  |  ❌ {fail} thất bại",
                text_color=(GR if fail == 0 else RD))
            hdr = ctk.CTkFrame(self._sp_result_scroll, fg_color="#e8eaf6", corner_radius=4, height=28)
            hdr.pack(fill="x", pady=(0, 2)); hdr.pack_propagate(False)
            for txt, w_ in [("#", 30), ("Ảnh", 44), ("Tên SP", 250), ("Trạng thái", 80), ("Chi tiết", 200)]:
                ctk.CTkLabel(hdr, text=txt, font=("Consolas", 10, "bold"), width=w_, anchor="w").pack(side="left", padx=2)
            THUMB = 36  # kích thước thumbnail
            for i, r in enumerate(results):
                row_bg = "#ffffff" if i % 2 == 0 else "#f8f9fc"
                row = ctk.CTkFrame(self._sp_result_scroll, fg_color=row_bg, corner_radius=2, height=THUMB + 4)
                row.pack(fill="x", pady=1); row.pack_propagate(False)
                ctk.CTkLabel(row, text=str(i + 1), font=("Consolas", 10), width=30, anchor="w", text_color=T2).pack(side="left", padx=2)
                # Thumbnail ảnh SP
                img_path = r.get("img", "")
                try:
                    if img_path and os.path.isfile(img_path):
                        from PIL import Image as PILImage
                        pil_img = PILImage.open(img_path)
                        pil_img.thumbnail((THUMB, THUMB))
                        ctk_img = ctk.CTkImage(light_image=pil_img, size=(THUMB, THUMB))
                        self._sp_thumb_refs.append(ctk_img)
                        ctk.CTkLabel(row, image=ctk_img, text="", width=THUMB + 8).pack(side="left", padx=2)
                    else:
                        ctk.CTkLabel(row, text="—", width=THUMB + 8, font=("", 10), text_color=T2).pack(side="left", padx=2)
                except Exception:
                    ctk.CTkLabel(row, text="⚠", width=THUMB + 8, font=("", 10), text_color=T2).pack(side="left", padx=2)
                # Tên SP
                display = r.get("name", "")
                display = display[:40] + ("..." if len(display) > 40 else "")
                ctk.CTkLabel(row, text=display, font=("Consolas", 10), width=250, anchor="w", text_color=T1).pack(side="left", padx=2)
                # Trạng thái + Chi tiết
                if r["status"] == "success":
                    ctk.CTkLabel(row, text="✅ OK", font=("", 10), width=80, anchor="w", text_color=GR).pack(side="left", padx=2)
                    out_name = os.path.basename(r.get("output", ""))
                    ctk.CTkLabel(row, text=out_name, font=("Consolas", 10), width=200, anchor="w", text_color=T2).pack(side="left", padx=2)
                else:
                    ctk.CTkLabel(row, text="❌ Lỗi", font=("", 10), width=80, anchor="w", text_color=RD).pack(side="left", padx=2)
                    ctk.CTkLabel(row, text=r.get("error", ""), font=("Consolas", 10), width=200, anchor="w", text_color=RD).pack(side="left", padx=2)
            if not self._sp_result_card.winfo_ismapped():
                self._sp_result_card.pack(fill="x", pady=(4, 0), before=self._sp_btn_row)
            self._shopee_results = results
        self.after(0, _do)

    # ============ TAB TẠO VIDEO TỪ SERVER (PostgreSQL) ============
    def _build_server_video(self):
        """Tab lấy sản phẩm từ PostgreSQL Server để tạo video — chống trùng 100% đa máy."""
        import uuid
        f = ctk.CTkFrame(self.content, fg_color=BG); self.frames["server_video"] = f

        # Client ID duy nhất cho phiên làm việc này (chống trùng giữa các máy)
        self._sv_client_id = self.settings.get("sv_client_id", f"{os.environ.get('COMPUTERNAME', 'PC')}_{uuid.uuid4().hex[:6]}")

        # Header
        hdr = ctk.CTkFrame(f, fg_color="#1565C0", corner_radius=12); hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="🌐 Tạo Video từ Server (PostgreSQL)", font=("", 18, "bold"), text_color="#fff").pack(side="left", padx=20, pady=14)
        self._sv_status_lbl = ctk.CTkLabel(hdr, text="Chưa kết nối", font=("", 12), text_color="#90CAF9")
        self._sv_status_lbl.pack(side="right", padx=20)

        # --- Card Kết nối Server ---
        conn_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); conn_card.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(conn_card, text="🔗 Kết nối Server", font=("", 13, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(10, 4))
        conn_row = ctk.CTkFrame(conn_card, fg_color="transparent"); conn_row.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkLabel(conn_row, text="Server URL:", font=("", 12)).pack(side="left")
        self._sv_url = ctk.CTkEntry(conn_row, width=250)
        self._sv_url.pack(side="left", padx=(4, 8))
        url_saved = self.settings.get("sv_server_url", "http://localhost:3000").strip()
        if url_saved and not (url_saved.startswith("http://") or url_saved.startswith("https://")):
            url_saved = "http://" + url_saved
        self._sv_url.insert(0, url_saved)
        self._sv_url.configure(state="disabled")

        ctk.CTkLabel(conn_row, text="API Key:", font=("", 12)).pack(side="left")
        self._sv_apikey = ctk.CTkEntry(conn_row, width=180)
        self._sv_apikey.pack(side="left", padx=(4, 8))
        self._sv_apikey.insert(0, self.settings.get("sv_api_key", "shopee_secret_2026"))
        self._sv_apikey.configure(state="disabled")

        ctk.CTkLabel(conn_row, text="Client ID:", font=("", 11), text_color=T2).pack(side="left", padx=(8, 2))
        self._sv_client_entry = ctk.CTkEntry(conn_row, width=130, font=("Consolas", 10))
        self._sv_client_entry.pack(side="left", padx=(0, 4))
        self._sv_client_entry.insert(0, self._sv_client_id)
        self._sv_client_entry.configure(state="disabled")

        self._sv_conn_editing = False
        self._sv_edit_btn = ctk.CTkButton(conn_row, text="✏️ Sửa", width=60, height=28,
                                           fg_color="#78909C", hover_color="#546E7A",
                                           font=("", 11), command=self._sv_toggle_conn_edit)
        self._sv_edit_btn.pack(side="left", padx=(4, 8))

        # Cache giá trị cho worker thread (tránh đọc disabled widget)
        self._sv_cached_url = url_saved
        self._sv_cached_apikey = self.settings.get("sv_api_key", "shopee_secret_2026")
        self._sv_cached_client_id = self._sv_client_id

        self._sv_ping_btn = ctk.CTkButton(conn_row, text="🔄 Ping", width=70, command=self._sv_ping_server,
                                           fg_color="#1565C0", hover_color="#0D47A1", height=32)
        self._sv_ping_btn.pack(side="left", padx=(0, 4))
        self._sv_ping_lbl = ctk.CTkLabel(conn_row, text="", font=("", 11), text_color=T2)
        self._sv_ping_lbl.pack(side="left", padx=4)

        # --- Card Cài đặt Video ---
        cfg = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); cfg.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(cfg, text="⚙ Cài đặt Video", font=("", 13, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(10, 4))

        # Row 1: Tỉ lệ + Khung cảnh + Độ dài + Ngôn ngữ
        row1 = ctk.CTkFrame(cfg, fg_color="transparent"); row1.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(row1, text="Tỉ lệ:", font=("", 12)).pack(side="left")
        self._sv_aspect = ctk.CTkOptionMenu(row1, values=list(E.VID_ASPECTS.keys()), width=150)
        self._sv_aspect.pack(side="left", padx=(4, 12))
        self._sv_aspect.set(self.settings.get("sv_aspect", "Dọc 9:16 (TikTok)"))

        scene_opts = SV.SCENE_OPTIONS if SV else ["🎲 Random"]
        ctk.CTkLabel(row1, text="Khung cảnh:", font=("", 12)).pack(side="left")
        self._sv_scene = ctk.CTkOptionMenu(row1, values=scene_opts, width=200)
        self._sv_scene.pack(side="left", padx=(4, 12))
        self._sv_scene.set(self.settings.get("sv_scene", "🎲 Random"))

        dur_opts = ["8s"] + (SV.DURATION_OPTIONS if SV else ["16s", "24s"])
        ctk.CTkLabel(row1, text="Độ dài:", font=("", 12)).pack(side="left")
        self._sv_duration = ctk.CTkOptionMenu(row1, values=dur_opts, width=80,
                                               command=lambda v: self._sv_on_duration_change())
        self._sv_duration.pack(side="left", padx=(4, 12))
        self._sv_duration.set(self.settings.get("sv_duration", "16s"))

        lang_opts = SV.LANG_OPTIONS if SV else ["Tiếng Việt", "Tiếng Philippines"]
        ctk.CTkLabel(row1, text="Ngôn ngữ:", font=("", 12)).pack(side="left")
        self._sv_lang = ctk.CTkOptionMenu(row1, values=lang_opts, width=120,
                                           command=lambda v: self._sv_sync_lang_to_market(v))
        self._sv_lang.pack(side="left", padx=(4, 0))
        self._sv_lang.set(self.settings.get("sv_lang", "Tiếng Việt"))

        # Row 1b: Model (nguồn ShopAPI đã tách tab riêng)
        row1b = ctk.CTkFrame(cfg, fg_color="transparent"); row1b.pack(fill="x", padx=12, pady=4)
        # Giữ _sv_source = Local cố định (ShopAPI đã có tab riêng)
        self._sv_source = type('', (), {'get': lambda self: "Veo3 Local (Tài khoản)"})()

        self._sv_model_lbl = ctk.CTkLabel(row1b, text="🤖 Model:", font=("", 12))
        self._sv_model_lbl.pack(side="left")
        self._sv_model = ctk.CTkOptionMenu(row1b, values=list(E.VID_MODELS.keys()), width=220,
                                            command=lambda v: self._sv_on_model_change())
        self._sv_model.pack(side="left", padx=(4, 12))
        self._sv_model.set(self.settings.get("sv_model", "Veo 3.1 (miễn phí)"))

        # Row 1c: ShopAPI config (đã tách tab riêng — giữ widget cho backward compat nhưng không hiện)
        self._sv_shopapi_row = ctk.CTkFrame(cfg, fg_color="transparent")
        self._sv_shopapi_key = ctk.CTkEntry(self._sv_shopapi_row, width=300)
        _saved_shopapi_key = self.settings.get("sv_shopapi_key", "")
        if _saved_shopapi_key:
            self._sv_shopapi_key.insert(0, _saved_shopapi_key)
        self._sv_shopapi_engine = ctk.CTkOptionMenu(self._sv_shopapi_row, values=["8s (Veo3 / 500₫)", "10s (Seedance / 1.000₫)"], width=200)
        self._sv_shopapi_engine.set(self.settings.get("sv_shopapi_engine", "8s (Veo3 / 500₫)"))
        # Không pack — ShopAPI đã có tab riêng
        # Row 2: Kiểu review + Checkboxes
        row2 = ctk.CTkFrame(cfg, fg_color="transparent"); row2.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(row2, text="Kiểu Review:", font=("", 12)).pack(side="left")
        self._sv_review_style = ctk.StringVar(value=self.settings.get("sv_review_style", "🎲 Random"))
        self._sv_style_menu = ctk.CTkOptionMenu(row2, values=["🎲 Random", "Review tự nhiên", "Ngồi Review", "POV (Góc nhìn thứ nhất)", "Unboxing", "UGC Authentic", "Demo Công Dụng", "So Sánh/Đánh Giá"],
                                                  variable=self._sv_review_style, width=200)
        self._sv_style_menu.pack(side="left", padx=(4, 12))

        self._sv_remove_wm = ctk.BooleanVar(value=self.settings.get("sv_remove_wm", True))
        self._sv_chk_remove_wm = ctk.CTkCheckBox(row2, text="🧹 Xóa logo VEO", variable=self._sv_remove_wm,
                        font=("", 11), checkbox_width=18, checkbox_height=18)
        self._sv_chk_remove_wm.pack(side="left", padx=(0, 12))

        self._sv_del_img = ctk.BooleanVar(value=self.settings.get("sv_del_img", True))
        ctk.CTkCheckBox(row2, text="🗑 Xóa ảnh khi tạo xong", variable=self._sv_del_img,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left", padx=(0, 12))

        self._sv_ghep_anh = ctk.BooleanVar(value=self.settings.get("sv_ghep_anh", False))
        self._sv_chk_ghep_anh = ctk.CTkCheckBox(row2, text="🎞 Ghép ảnh (12s)", variable=self._sv_ghep_anh,
                                                 font=("", 11), checkbox_width=18, checkbox_height=18)
        self._sv_chk_ghep_anh.pack(side="left", padx=(0, 12))

        self._sv_use_laundering = ctk.BooleanVar(value=self.settings.get("sv_use_laundering", False))
        self._sv_chk_laundering = ctk.CTkCheckBox(row2, text="🧼 Rửa ảnh (Bypass 429)", variable=self._sv_use_laundering,
                        font=("", 11), checkbox_width=18, checkbox_height=18)
        self._sv_chk_laundering.pack(side="left", padx=(0, 12))

        # AI sinh prompt
        ctk.CTkLabel(row2, text="AI Prompt:", font=("", 12)).pack(side="left", padx=(8, 2))
        self._sv_ai_prompt = ctk.CTkOptionMenu(row2, values=["Gemini", "Groq", "Prompt A + B"], width=160)
        self._sv_ai_prompt.pack(side="left", padx=(2, 12))
        saved_sv_ai = self.settings.get("sv_ai_prompt", "Prompt A + B")
        if saved_sv_ai == "Template (mặc định)": saved_sv_ai = "Prompt A + B"
        self._sv_ai_prompt.set(saved_sv_ai)
        self._sv_ai_saved_value = saved_sv_ai  # lưu giá trị trước khi khóa

        ctk.CTkButton(
            row2,
            text="🧪 Test prompt",
            command=self._sv_test_prompt,
            fg_color="#5C6BC0",
            hover_color="#3949AB",
            height=28,
            width=100,
            font=("", 11)
        ).pack(side="left", padx=(0, 12))

        # Áp dụng trạng thái khóa/mở theo model + duration đã lưu
        self._sv_on_model_change()
        # Áp dụng ẩn/hiện theo nguồn Local vs Server
        self._sv_on_source_change()

        # Row 3: Đặt tên video + Thư mục lưu
        row3 = ctk.CTkFrame(cfg, fg_color="transparent"); row3.pack(fill="x", padx=12, pady=(4, 10))

        ctk.CTkLabel(row3, text="Đặt tên video:", font=("", 12)).pack(side="left")
        self._sv_naming = ctk.CTkOptionMenu(row3, values=["Theo Item ID", "15 ký tự đầu prompt", "Số thứ tự (001...)"], width=170)
        self._sv_naming.pack(side="left", padx=(4, 12))
        self._sv_naming.set(self.settings.get("sv_naming", "Theo Item ID"))

        ctk.CTkLabel(row3, text="📁 Lưu video:", font=("", 12)).pack(side="left")
        self._sv_outdir = ctk.CTkEntry(row3)
        self._sv_outdir.pack(side="left", padx=6, fill="x", expand=True)
        if self.settings.get("sv_out_dir"):
            self._sv_outdir.insert(0, self.settings["sv_out_dir"])
        ctk.CTkButton(row3, text="Chọn", width=56, command=lambda: self._pick(self._sv_outdir),
                      fg_color="#1565C0", hover_color="#0D47A1").pack(side="left", padx=(0, 4))

        # --- Card Nhận Lô Sản Phẩm ---
        claim_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); claim_card.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(claim_card, text="📦 Nhận Lô Sản Phẩm từ Database", font=("", 13, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(10, 4))

        claim_row = ctk.CTkFrame(claim_card, fg_color="transparent"); claim_row.pack(fill="x", padx=12, pady=(0, 4))

        ctk.CTkLabel(claim_row, text="Số lượng:", font=("", 12)).pack(side="left")
        self._sv_claim_limit = ctk.CTkEntry(claim_row, width=70, font=("Consolas", 12))
        self._sv_claim_limit.pack(side="left", padx=(4, 8))
        self._sv_claim_limit.insert(0, self.settings.get("sv_claim_limit", "1000"))

        ctk.CTkLabel(claim_row, text="Ưu tiên:", font=("", 12)).pack(side="left")
        self._sv_sort_by = ctk.CTkOptionMenu(claim_row, values=["Số bán cao nhất", "Hoa hồng cao nhất"], width=170)
        self._sv_sort_by.pack(side="left", padx=(4, 8))
        self._sv_sort_by.set(self.settings.get("sv_sort_by", "Số bán cao nhất"))

        ctk.CTkLabel(claim_row, text="Thị trường:", font=("", 12)).pack(side="left")
        self._sv_market = ctk.CTkOptionMenu(claim_row, values=["PH", "VN", "ID", "TH", "MY", "SG", "TW"], width=70,
                                             command=lambda v: self._sv_sync_market_to_lang(v))
        self._sv_market.pack(side="left", padx=(4, 8))
        self._sv_market.set(self.settings.get("sv_market", "PH"))

        ctk.CTkLabel(claim_row, text="ItemID từ:", font=("", 12)).pack(side="left")
        self._sv_min_item_id = ctk.CTkEntry(claim_row, width=115, font=("Consolas", 11))
        self._sv_min_item_id.pack(side="left", padx=(4, 6))
        self._sv_min_item_id.insert(0, self.settings.get("sv_min_item_id", "40000000000"))

        ctk.CTkLabel(claim_row, text="Hoa hồng từ:", font=("", 12)).pack(side="left")
        self._sv_min_commission = ctk.CTkEntry(claim_row, width=50, font=("Consolas", 11))
        self._sv_min_commission.pack(side="left", padx=(4, 8))
        self._sv_min_commission.insert(0, self.settings.get("sv_min_commission", "1%"))

        self._sv_btn_claim = ctk.CTkButton(claim_row, text="📥 Nhận Lô Sản Phẩm", width=150,
                                            command=self._sv_claim_jobs,
                                            fg_color="#1565C0", hover_color="#0D47A1", height=32,
                                            font=("", 12, "bold"))
        self._sv_btn_claim.pack(side="left", padx=(4, 4))

        self._sv_btn_release = ctk.CTkButton(claim_row, text="🔄 Giải phóng SP kẹt", width=140,
                                              command=self._sv_release_stuck,
                                              fg_color="#E57373", hover_color="#EF5350", height=32)
        self._sv_btn_release.pack(side="left", padx=(4, 0))

        self._sv_btn_clear_violation = ctk.CTkButton(claim_row, text="🗑 Xóa Vi Phạm CS", width=130,
                                                     command=self._sv_clear_violation,
                                                     fg_color="#D32F2F", hover_color="#C62828", height=32, font=("", 11, "bold"))
        self._sv_btn_clear_violation.pack(side="left", padx=(4, 0))

        # Stats row
        stat_row = ctk.CTkFrame(claim_card, fg_color="transparent"); stat_row.pack(fill="x", padx=12, pady=(0, 10))
        self._sv_stat_lbl = ctk.CTkLabel(stat_row, text="📊 Chưa có dữ liệu", font=("", 11), text_color=T2)
        self._sv_stat_lbl.pack(side="left")
        self._sv_claimed_lbl = ctk.CTkLabel(stat_row, text="", font=("", 11, "bold"), text_color="#1565C0")
        self._sv_claimed_lbl.pack(side="left", padx=(12, 0))

        # --- Bottom: Log + Progress + Buttons (định nghĩa trước để pack side="bottom") ---
        bottom = ctk.CTkFrame(f, fg_color="transparent"); bottom.pack(side="bottom", fill="x")
        
        self._sv_progress = ctk.CTkProgressBar(bottom, height=8, progress_color="#1565C0")
        self._sv_progress.pack(fill="x", pady=(4, 2)); self._sv_progress.set(0)

        self._sv_log = ctk.CTkTextbox(bottom, height=100, font=("Consolas", 10), state="disabled")
        self._sv_log.pack(fill="x", pady=(2, 4))

        btn_row = ctk.CTkFrame(bottom, fg_color="transparent"); btn_row.pack(fill="x", pady=(2, 0))
        self._sv_btn_start = ctk.CTkButton(btn_row, text="▶  Bắt đầu tạo video",
                                            command=self._sv_start, fg_color="#1565C0",
                                            hover_color="#0D47A1", height=42,
                                            font=("", 15, "bold"))
        self._sv_btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._sv_btn_stop = ctk.CTkButton(btn_row, text="⏹ Dừng", command=self._sv_stop,
                                           fg_color="#9aa0a6", hover_color="#5f6368",
                                           height=42, width=100, state="disabled")
        self._sv_btn_stop.pack(side="left", padx=(0, 4))



        self._sv_btn_open = ctk.CTkButton(btn_row, text="📂 Mở thư mục",
                                           command=lambda: os.startfile(self._sv_outdir.get().strip()) if os.path.isdir(self._sv_outdir.get().strip()) else None,
                                           fg_color="#5C6BC0", hover_color="#3949AB",
                                           height=42, width=120)
        self._sv_btn_open.pack(side="left", padx=(4, 0))

        # --- Middle Split Container (Horizontal: 50% / 50%) ---
        middle_split = ctk.CTkFrame(f, fg_color="transparent")
        middle_split.pack(fill="both", expand=True, pady=(6, 0))

        # --- Cột trái: Danh sách SP đã nhận ---
        list_card = ctk.CTkFrame(middle_split, fg_color=CARD, corner_radius=10)
        list_card.pack(side="left", fill="both", expand=True, padx=(0, 4))
        list_hdr = ctk.CTkFrame(list_card, fg_color="transparent"); list_hdr.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(list_hdr, text="📋 Danh sách SP đã nhận", font=("", 12, "bold"), text_color=T1).pack(side="left")
        self._sv_list_count = ctk.CTkLabel(list_hdr, text="0 SP", font=("", 11), text_color=T2)
        self._sv_list_count.pack(side="right")
        self._sv_video_done_lbl = ctk.CTkLabel(list_hdr, text="", font=("", 11, "bold"), text_color="#1B7D2C")
        self._sv_video_done_lbl.pack(side="right", padx=(0, 12))
        self._sv_video_done_count = 0

        self._sv_products_text = ctk.CTkTextbox(list_card, font=("Consolas", 10))
        self._sv_products_text.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._sv_products_text.tag_config("sv_success", foreground="#1B7D2C")
        self._sv_products_text.tag_config("sv_error", foreground="#D32F2F")
        self._sv_products_text.tag_config("sv_running", foreground="#E65100")

        # --- Cột phải: Pool Status Panel (AIMD) ---
        pool_card = ctk.CTkFrame(middle_split, fg_color=CARD, corner_radius=10)
        pool_card.pack(side="left", fill="both", expand=True, padx=(4, 0))
        pool_hdr = ctk.CTkFrame(pool_card, fg_color="transparent"); pool_hdr.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(pool_hdr, text="🚀 Pool tài khoản (AIMD)", font=("", 12, "bold"), text_color=T1).pack(side="left")
        self._sv_pool_eta_lbl = ctk.CTkLabel(pool_hdr, text="", font=("", 11), text_color=AC)
        self._sv_pool_eta_lbl.pack(side="right")
        # 4 stat boxes
        stat_row = ctk.CTkFrame(pool_card, fg_color="transparent"); stat_row.pack(fill="x", padx=12, pady=2)
        self._sv_pool_stat = {}
        for key, icon, color in [("acc", "👥 Tổng", T1), ("run", "🟢 Chạy", GR), ("gen", "⚡ Tạo", AC), ("rest", "😴 Nghỉ", "#F9A825")]:
            box = ctk.CTkFrame(stat_row, fg_color="transparent"); box.pack(side="left", padx=(0, 16))
            ctk.CTkLabel(box, text=icon, font=("", 10), text_color=T2).pack(side="left")
            lbl = ctk.CTkLabel(box, text="0", font=("", 11, "bold"), text_color=color); lbl.pack(side="left", padx=(4, 0))
            self._sv_pool_stat[key] = lbl
        # Account rows container
        self._sv_pool_rows_frame = ctk.CTkScrollableFrame(pool_card, fg_color=CARD)
        self._sv_pool_rows_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._sv_pool_rows = {}
        self._sv_pool_row_sig = ()
        self._sv_pool_states = None  # set during run

        # Internal state
        self._sv_running = False
        self._sv_stop_flag = False
        self._sv_claimed_products = []  # danh sách SP đã nhận từ server
        self._sv_last_video_time = 0    # thời điểm tạo video thành công gần nhất (cho 2h timeout)

    def _sv_update_pool(self):
        """Panel POOL Server (cập nhật mỗi 2s): tốc độ tự động AIMD — tối ưu chỉ redraw khi giá trị thay đổi."""
        try:
            # Fix 3: Bỏ qua nếu tab Server không hiển thị → giảm 100% CPU cho tab ẩn
            if getattr(self, '_current_tab', '') != 'server_video':
                return  # finally vẫn reschedule

            # Cache dict: lưu giá trị cũ để chỉ .configure() khi thay đổi
            if not hasattr(self, '_sv_pool_cache'):
                self._sv_pool_cache = {}
            cache = self._sv_pool_cache

            def _set(widget, key, **kwargs):
                """Chỉ gọi .configure() khi giá trị thực sự thay đổi."""
                val = tuple(sorted(kwargs.items()))
                if cache.get(key) != val:
                    widget.configure(**kwargs)
                    cache[key] = val

            eta = self._sv_eta_text()
            _set(self._sv_pool_eta_lbl, "_eta", text=eta)

            is_running = getattr(self, "_sv_running", False)
            states = getattr(self, "_sv_pool_states", None)
            if not is_running or not states:
                states = [AccountState(a) for a in self.accounts if a.get("enabled", True) and a.get("role", "main") == "main"]
            total = len(states)
            resting = sum(1 for s in states if s.rest_remaining() > 0)
            running = total - resting
            generating = sum(1 for s in states if getattr(s, "busy", 0) > 0)
            _set(self._sv_pool_stat["acc"], "_st_acc", text=str(total))
            _set(self._sv_pool_stat["run"], "_st_run", text=str(running if is_running else total))
            _set(self._sv_pool_stat["gen"], "_st_gen", text=str(generating))
            _set(self._sv_pool_stat["rest"], "_st_rest", text=str(resting if is_running else 0))

            sig = tuple(s.email for s in states)
            if sig != self._sv_pool_row_sig:
                self._sv_pool_row_sig = sig
                cache.clear()  # Reset cache khi rebuild rows
                for w in self._sv_pool_rows_frame.winfo_children(): w.destroy()
                self._sv_pool_rows = {}
                if not states:
                    ctk.CTkLabel(self._sv_pool_rows_frame, text="Chưa có tài khoản nào được chọn ở Tab 'Tài khoản'.",
                                 font=("", 11), text_color=T2).pack(anchor="w", pady=6)
                else:
                    cols = [("Tài khoản", 130), ("✅ Xong", 50), ("❌ Lỗi", 45),
                            ("⚡ Tạo", 40), ("🚀 Tốc độ", 55), ("Trạng thái", 105), ("🌐 Proxy", 150), ("Hành động", 65), ("📤 Upload", 60)]
                    hdr = ctk.CTkFrame(self._sv_pool_rows_frame, fg_color="transparent"); hdr.pack(fill="x", pady=(0, 2))
                    for txt, w in cols:
                        ctk.CTkLabel(hdr, text=txt, font=("", 10, "bold"), text_color=T2, width=w, anchor="w").pack(side="left", padx=(2, 0))
                    for i, s in enumerate(states):
                        row = ctk.CTkFrame(self._sv_pool_rows_frame, fg_color=("#f6f8fc" if i % 2 else CARD), corner_radius=6)
                        row.pack(fill="x", pady=1)
                        ctk.CTkLabel(row, text=str(s.email).split("@")[0][:22], font=("", 11), text_color=T1, width=130, anchor="w").pack(side="left", padx=(2, 0))
                        wl = ctk.CTkLabel(row, text="0", font=("", 11, "bold"), text_color=GR, width=50, anchor="w"); wl.pack(side="left", padx=(2, 0))
                        fl = ctk.CTkLabel(row, text="0", font=("", 11), text_color=RD, width=45, anchor="w"); fl.pack(side="left", padx=(2, 0))
                        bl = ctk.CTkLabel(row, text="0", font=("", 11), text_color=T1, width=40, anchor="w"); bl.pack(side="left", padx=(2, 0))
                        rl = ctk.CTkLabel(row, text="0", font=("", 11), text_color=AC, width=55, anchor="w"); rl.pack(side="left", padx=(2, 0))
                        sl = ctk.CTkLabel(row, text="", font=("", 11), text_color=GR, width=105, anchor="w"); sl.pack(side="left", padx=(2, 0))
                        pl = ctk.CTkLabel(row, text="—", font=("Consolas", 10), text_color=T2, width=150, anchor="w"); pl.pack(side="left", padx=(2, 0))
                        ab = ctk.CTkButton(row, text="⏹ Dừng", fg_color="#E57373", hover_color="#EF5350", width=60, height=24, font=("", 11, "bold"),
                                           command=lambda e=s.email: self._toggle_acc_enabled(e))
                        ab.pack(side="left", padx=(2, 0))
                        uo = ctk.CTkOptionMenu(row, values=["2", "3", "4", "5", "6", "7", "8", "9", "10"], width=52, height=24, font=("", 11),
                                               command=lambda v, st=s: self._on_acc_upload_threads_change(st, v))
                        uo.pack(side="left", padx=(4, 0))
                        uo.set(str(getattr(s, "upload_threads", 4)))
                        self._sv_pool_rows[s.email] = {"w": wl, "f": fl, "b": bl, "r": rl, "s": sl, "p": pl, "a": ab, "u": uo}

            # Fix 4: Chỉ update dòng có giá trị thay đổi (cached)
            for s in states:
                r = self._sv_pool_rows.get(s.email)
                if not r: continue
                e = s.email
                _set(r["w"], f"{e}_w", text=str(s.wins))
                _set(r["f"], f"{e}_f", text=str(s.fails))
                _set(r["b"], f"{e}_b", text=str(s.busy))
                _set(r["r"], f"{e}_r", text=str(int(s.submit_limit)))
                px_str = self.proxy_pool.get_str(s.email) if self.proxy_pool else None
                if px_str:
                    parts = px_str.split(":")
                    px_display = f"{parts[0]}:{parts[1]}" if len(parts) >= 2 else px_str[:30]
                    _set(r["p"], f"{e}_p", text=px_display, text_color=AC)
                else:
                    _set(r["p"], f"{e}_p", text="IP trực tiếp", text_color=T2)
                is_enabled = s.acc.get("enabled", True)
                if not is_enabled:
                    _set(r["s"], f"{e}_s", text="⏹ đã dừng", text_color=T2)
                    _set(r["a"], f"{e}_a", text="▶ Chạy", fg_color="#26A69A", hover_color="#00897B")
                elif not is_running:
                    _set(r["s"], f"{e}_s", text="⏳ Sẵn sàng", text_color=GR)
                    _set(r["a"], f"{e}_a", text="⏹ Dừng", fg_color="#E57373", hover_color="#EF5350")
                else:
                    _set(r["a"], f"{e}_a", text="⏹ Dừng", fg_color="#E57373", hover_color="#EF5350")
                    rem = s.rest_remaining()
                    if rem > 0:
                        if s.rest_reason == "quota":
                            _set(r["s"], f"{e}_s", text=f"⛔ cách ly {int(rem//60)}p", text_color=RD)
                        else:
                            _set(r["s"], f"{e}_s", text=f"😴 nghỉ {int(rem)}s", text_color="#F9A825")
                    else:
                        _set(r["s"], f"{e}_s", text="🟢 đang chạy", text_color=GR)
        except Exception:
            pass
        finally:
            if self._sv_running:
                self.after(2000, self._sv_update_pool)

    def _sv_rolling_rate(self, window_min=10):
        """Tốc độ trượt 10 phút (video/phút) cho Server Video tab."""
        ts_deque = getattr(self, "_sv_done_timestamps", None)
        if not ts_deque: return 0.0
        now = time.time()
        cutoff = now - window_min * 60
        while ts_deque and ts_deque[0] < cutoff:
            ts_deque.popleft()
        return len(ts_deque) / window_min

    def _sv_eta_text(self):
        """Tốc độ + ETA cho Server Video tab."""
        products = getattr(self, "_sv_claimed_products", None)
        if not products: return ""
        remaining = sum(1 for p in products if p.get("_status") not in ("success", "noretry"))
        rate = self._sv_rolling_rate()
        if rate <= 0:
            return f"⚡ Đang đo tốc độ…   ·   còn {remaining} SP"
        eta_min = remaining / rate
        fin = time.localtime(time.time() + eta_min * 60)
        dur = f"{int(eta_min // 60)}g{int(eta_min % 60):02d}p" if eta_min >= 60 else f"{int(eta_min)+1}p"
        return (f"⚡ {rate:.1f} video/phút   ·   còn {remaining} SP   ·   "
                f"dự kiến xong sau {dur}  (≈ {time.strftime('%H:%M', fin)})")

    def _sv_log_msg(self, msg):
        """Ghi log vào textbox Server Video tab — batch 500ms để giảm tải Tk event queue."""
        if not hasattr(self, '_sv_log_buffer'):
            self._sv_log_buffer = []
            self._sv_log_flush_scheduled = False
        self._sv_log_buffer.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if not self._sv_log_flush_scheduled:
            self._sv_log_flush_scheduled = True
            self.after(500, self._sv_flush_log)

    def _sv_flush_log(self):
        """Flush tất cả log buffer vào textbox 1 lần duy nhất."""
        self._sv_log_flush_scheduled = False
        if not hasattr(self, '_sv_log_buffer') or not self._sv_log_buffer:
            return
        batch = self._sv_log_buffer[:]
        self._sv_log_buffer.clear()
        try:
            self._sv_log.configure(state="normal")
            self._sv_log.insert("end", "\n".join(batch) + "\n")
            line_count = int(self._sv_log.index("end-1c").split(".")[0])
            if line_count > 1000:
                self._sv_log.delete("1.0", f"{line_count - 800}.0")
            self._sv_log.see("end")
            self._sv_log.configure(state="disabled")
        except Exception:
            pass

    def _sv_api_call(self, method, path, data=None):
        """Gọi API Server PostgreSQL (GET/POST)."""
        # Dùng cached values tránh đọc disabled widget từ worker thread
        url = self._sv_cached_url.rstrip("/") + path
        api_key = self._sv_cached_apikey
        headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
        if method == "GET":
            req = urllib.request.Request(url, headers=headers)
        else:
            body = json.dumps(data or {}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _sv_toggle_conn_edit(self):
        """Toggle chỉnh sửa Server URL / API Key / Client ID."""
        self._sv_conn_editing = not self._sv_conn_editing
        if self._sv_conn_editing:
            # Mở khóa để chỉnh sửa
            self._sv_url.configure(state="normal")
            self._sv_apikey.configure(state="normal")
            self._sv_client_entry.configure(state="normal")
            self._sv_edit_btn.configure(text="🔒 Khóa", fg_color="#E65100", hover_color="#BF360C")
        else:
            # Khóa lại → cache giá trị mới cho worker thread
            url_input = self._sv_url.get().strip()
            if url_input and not (url_input.startswith("http://") or url_input.startswith("https://")):
                url_input = "http://" + url_input
                self._sv_url.delete(0, "end")
                self._sv_url.insert(0, url_input)
            self._sv_cached_url = url_input
            self._sv_cached_apikey = self._sv_apikey.get().strip()
            self._sv_cached_client_id = self._sv_client_entry.get().strip()
            self._sv_url.configure(state="disabled")
            self._sv_apikey.configure(state="disabled")
            self._sv_client_entry.configure(state="disabled")
            self._sv_edit_btn.configure(text="✏️ Sửa", fg_color="#78909C", hover_color="#546E7A")

    def _sv_toggle_tg_edit(self):
        """Toggle chỉnh sửa Token / Chat ID Telegram."""
        self._tg_editing = not self._tg_editing
        new_state = "normal" if self._tg_editing else "disabled"
        self.ent_tg_token.configure(state=new_state)
        self.ent_tg_chatid.configure(state=new_state)
        if self._tg_editing:
            self._tg_edit_btn.configure(text="🔒 Khóa", fg_color="#E65100", hover_color="#BF360C")
        else:
            self._tg_edit_btn.configure(text="✏️ Sửa", fg_color="#78909C", hover_color="#546E7A")

    def _sv_ping_server(self):
        """Ping server và hiển thị thống kê."""
        _market = self._sv_market.get()
        def _do():
            try:
                # Health check
                url = self._sv_cached_url.rstrip("/") + "/health"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    pass
                # Video stats
                stats = self._sv_api_call("GET", f"/api/thinaptm/video-stats?market={_market}")
                s = stats.get("stats", {})
                total = s.get("total", 0)
                pending = s.get("pending", 0)
                processing = s.get("processing", 0)
                completed = s.get("completed", 0)
                self.after(0, lambda: self._sv_ping_lbl.configure(
                    text=f"🟢 Kết nối OK ({total:,} SP)", text_color=GR))
                self.after(0, lambda: self._sv_stat_lbl.configure(
                    text=f"📊 Tổng: {total:,}  |  ⏳ Chờ: {pending:,}  |  ⚙ Đang làm: {processing:,}  |  ✅ Xong: {completed:,}"))
                self.after(0, lambda: self._sv_status_lbl.configure(text=f"🟢 {total:,} SP"))
            except Exception as e:
                self.after(0, lambda: self._sv_ping_lbl.configure(
                    text=f"🔴 Lỗi: {str(e)[:50]}", text_color=RD))
        threading.Thread(target=_do, daemon=True).start()

    def _sv_claim_jobs(self):
        """Nhận lô sản phẩm từ PostgreSQL Server."""
        limit = int(self._sv_claim_limit.get().strip() or "1000")
        sort_map = {"Số bán cao nhất": "sold", "Hoa hồng cao nhất": "commission"}
        sort_by = sort_map.get(self._sv_sort_by.get(), "sold")
        market = self._sv_market.get()
        client_id = self._sv_client_entry.get().strip()
        self._sv_client_id = client_id

        min_item_id_str = self._sv_min_item_id.get().strip()
        min_comm_str = self._sv_min_commission.get().strip()
        import re as _re
        try:
            min_item_id = int(_re.sub(r'\D', '', min_item_id_str) or "40000000000")
        except Exception:
            min_item_id = 40000000000
        try:
            min_commission = float(min_comm_str.replace("%", "").strip() or "1.0")
        except Exception:
            min_commission = 1.0

        self._sv_btn_claim.configure(state="disabled", text="⏳ Đang xin...")
        self._sv_log_msg(f"📥 Đang xin {limit} SP từ Server (market={market}, sort={sort_by}, item_id>={min_item_id}, comm>={min_commission}%)...")

        def _do():
            try:
                result = self._sv_api_call("POST", "/api/thinaptm/claim-jobs", {
                    "market": market, "clientId": client_id, "limit": limit, "sortBy": sort_by,
                    "min_item_id": min_item_id, "min_commission": min_commission,
                    "minItemId": min_item_id, "minCommission": min_commission
                })
                raw_products = result.get("products", [])
                # Lọc sản phẩm thỏa mãn tiêu chí ItemID và Hoa hồng
                products = []
                for p in raw_products:
                    try:
                        iid = int(_re.sub(r'\D', '', str(p.get("item_id", 0))))
                    except Exception:
                        iid = 0
                    try:
                        raw_comm = float(p.get("commission_rate", 0) or 0)
                        # Chuẩn hóa hoa hồng: nếu DB lưu dạng thập phân <= 1.0 (VD: 0.17 cho 17%), tự động quy đổi sang % (17.0)
                        comm = raw_comm * 100.0 if 0 < raw_comm <= 1.0 else raw_comm
                        p["commission_rate"] = comm
                    except Exception:
                        comm = 0.0
                    if (min_item_id > 0 and iid < min_item_id) or comm < min_commission:
                        continue
                    products.append(p)

                count = len(products)
                self._sv_claimed_products = products
                self._sv_last_video_time = time.time()

                # Hiển thị danh sách lên textbox
                def _update_ui():
                    self._sv_products_text.configure(state="normal")
                    self._sv_products_text.delete("1.0", "end")
                    curr_symbol = "₫" if market == "VN" else ("Rp" if market == "ID" else "₱")
                    for i, p in enumerate(products):
                        name = (p.get('name', '') or '')[:55]
                        item_id = p.get('item_id', '?')
                        try:
                            price_val = float(p.get('price', 0) or 0)
                        except Exception:
                            price_val = 0.0
                        sold = p.get('sold', 0)
                        comm = float(p.get('commission_rate', 0) or 0)
                        line = f"⏳ [{i+1}] {item_id} | {name} | {curr_symbol}{price_val:,.0f} | Sold:{sold} | Comm:{comm:.1f}%\n"
                        self._sv_products_text.insert("end", line)
                    self._sv_list_count.configure(text=f"{count} SP")
                    self._sv_claimed_lbl.configure(text=f"✅ Đã nhận {count} SP — sẵn sàng tạo video!")
                    self._sv_btn_claim.configure(state="normal", text="📥 Nhận Lô Sản Phẩm")
                self.after(0, _update_ui)
                self._sv_log_msg(f"✅ Đã nhận {count} SP từ Server! Bấm ▶ để bắt đầu tạo video.")
            except Exception as e:
                self._sv_log_msg(f"❌ Lỗi nhận SP: {e}")
                self.after(0, lambda: self._sv_btn_claim.configure(state="normal", text="📥 Nhận Lô Sản Phẩm"))
        threading.Thread(target=_do, daemon=True).start()

    def _sv_release_stuck(self):
        """Giải phóng SP kẹt (processing > 2h hoặc bấm thủ công)."""
        client_id = self._sv_cached_client_id
        self._sv_log_msg(f"🔄 Đang giải phóng SP kẹt của client '{client_id}'...")

        def _do():
            try:
                # 1. Giải phóng SP của client này
                r1 = self._sv_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                released1 = r1.get("released", 0)
                # 2. Giải phóng SP kẹt > 2h của tất cả client
                r2 = self._sv_api_call("POST", "/api/thinaptm/auto-release-stuck", {"hours": 2})
                released2 = r2.get("released", 0)
                total_released = released1 + released2
                self._sv_log_msg(f"✅ Đã giải phóng {total_released} SP (Client: {released1}, Kẹt >2h: {released2})")
                # Xóa danh sách cục bộ
                self._sv_claimed_products = []
                def _clear_ui():
                    self._sv_products_text.delete("1.0", "end")
                    self._sv_list_count.configure(text="0 SP")
                    self._sv_claimed_lbl.configure(text=f"🔄 Đã giải phóng {total_released} SP")
                    self._sv_btn_claim.configure(state="normal", text="📥 Nhận Lô Sản Phẩm")
                self.after(0, _clear_ui)
                # Refresh stats
                self._sv_ping_server()
            except Exception as e:
                self._sv_log_msg(f"❌ Lỗi giải phóng: {e}")
        threading.Thread(target=_do, daemon=True).start()

    def _sv_render_products_list(self):
        """Vẽ lại danh sách SP đã nhận lên textbox (kèm prefix + màu theo trạng thái)."""
        products = self._sv_claimed_products
        market = self._sv_market.get()
        curr_symbol = "₫" if market == "VN" else ("Rp" if market == "ID" else "₱")
        pfx_map = {"success": "✅ ", "noretry": "❌ ", "running": "⏳ "}
        tag_map = {"success": "sv_success", "noretry": "sv_error", "running": "sv_running"}

        def _do():
            try:
                self._sv_products_text.configure(state="normal")
                self._sv_products_text.delete("1.0", "end")
                for i, p in enumerate(products):
                    p["_idx"] = i          # đánh lại chỉ mục cho khớp dòng textbox
                    name = (p.get("name", "") or "")[:55]
                    item_id = p.get("item_id", "?")
                    try:
                        price_val = float(p.get("price", 0) or 0)
                    except Exception:
                        price_val = 0.0
                    sold = p.get("sold", 0)
                    try:
                        comm = float(p.get("commission_rate", 0) or 0)
                    except Exception:
                        comm = 0.0
                    status = str(p.get("_status", "") or "")
                    pfx = pfx_map.get(status, "⏳ ")
                    self._sv_products_text.insert(
                        "end",
                        f"{pfx}[{i+1}] {item_id} | {name} | {curr_symbol}{price_val:,.0f} "
                        f"| Sold:{sold} | Comm:{comm:.1f}%\n")
                    tag = tag_map.get(status)
                    if tag:
                        self._sv_products_text.tag_add(tag, f"{i+1}.0", f"{i+1}.end")
                self._sv_list_count.configure(text=f"{len(products)} SP")
            except Exception:
                pass
        self.after(0, _do)

    def _sv_clear_violation(self):
        """Xóa toàn bộ sản phẩm dính lỗi 'vi phạm cs' khỏi danh sách SP đã nhận Tab Server Video."""
        before = len(self._sv_claimed_products)
        self._sv_claimed_products = [
            p for p in self._sv_claimed_products
            if str(p.get("_status", "")).strip().lower() not in ("error", "noretry", "vi_pham_cs", "vi phạm cs")
        ]
        cleared = before - len(self._sv_claimed_products)
        self._sv_render_products_list()
        self._sv_log_msg(f"🗑️ Đã xóa {cleared} sản phẩm vi phạm chính sách khỏi danh sách!")
        if cleared > 0:
            messagebox.showinfo("Đã xóa", f"Đã xóa {cleared} sản phẩm vi phạm CS khỏi danh sách!")
        else:
            messagebox.showinfo("Thông báo", "Không có sản phẩm nào vi phạm CS trong danh sách hiện tại.")

    def _sv_download_image(self, image_url, save_path):
        """Tải ảnh sản phẩm từ Shopee CDN về thư mục tạm."""
        try:
            req = urllib.request.Request(image_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                with open(save_path, "wb") as wf:
                    wf.write(resp.read())
            return True
        except Exception as e:
            self._sv_log_msg(f"⚠ Tải ảnh lỗi: {e}")
            return False

    def _sv_update_line_status(self, line_idx, status):
        """Cập nhật trạng thái dòng trong textbox (giống Shopee tab)."""
        prefix_map = {"success": "✅ ", "error": "❌ ", "running": "⏳ ", "clear": ""}
        tag_map = {"success": "sv_success", "error": "sv_error", "running": "sv_running"}
        pfx = prefix_map.get(status, "")
        tag = tag_map.get(status)
        def _do():
            try:
                tk_line = line_idx + 1
                content = self._sv_products_text.get(f"{tk_line}.0", f"{tk_line}.end")
                # Bỏ prefix cũ
                for p in ("✅ ", "❌ ", "⏳ "):
                    if content.startswith(p):
                        content = content[len(p):]
                        break
                new_content = pfx + content
                self._sv_products_text.delete(f"{tk_line}.0", f"{tk_line}.end")
                self._sv_products_text.insert(f"{tk_line}.0", new_content)
                for t in ("sv_success", "sv_error", "sv_running"):
                    self._sv_products_text.tag_remove(t, f"{tk_line}.0", f"{tk_line}.end")
                if tag:
                    self._sv_products_text.tag_add(tag, f"{tk_line}.0", f"{tk_line}.end")
            except Exception:
                pass
        self.after(0, _do)

    # --- Đồng bộ Ngôn ngữ ↔ Thị trường ---
    _SV_LANG_TO_MARKET = {
        "Tiếng Philippines": "PH", "Tiếng Việt": "VN", "Tiếng Indonesia": "ID", "Tiếng Malaysia": "MY", "Tiếng Anh": "PH"
    }
    _SV_MARKET_TO_LANG = {
        "PH": "Tiếng Philippines",
        "VN": "Tiếng Việt",
        "ID": "Tiếng Indonesia",
        "MY": "Tiếng Malaysia"
    }

    def _sv_sync_lang_to_market(self, lang_val):
        """Khi đổi Ngôn ngữ → tự động chuyển Thị trường tương ứng."""
        if getattr(self, '_sv_syncing', False):
            return
        market = self._SV_LANG_TO_MARKET.get(lang_val)
        if market:
            self._sv_syncing = True
            self._sv_market.set(market)
            self._sv_syncing = False

    def _sv_sync_market_to_lang(self, market_val):
        """Khi đổi Thị trường → tự động chuyển Ngôn ngữ tương ứng."""
        if getattr(self, '_sv_syncing', False):
            return
        lang = self._SV_MARKET_TO_LANG.get(market_val)
        if lang:
            self._sv_syncing = True
            self._sv_lang.set(lang)
            self._sv_syncing = False

    def _run_ghep_anh_12s(self, video_path, image_path, output_path):
        """Sử dụng cấu hình từ config.json trong thư mục hiện tại để ghép ảnh vào video tạo ra video 12s."""
        import json
        import subprocess
        import os
        import random
        DEFAULT_CONFIG = {
            "slow_factor": 1.05,
            "image_dur": 3.5,
            "total_dur": 12.0,
            "motion_effect": "Zoom In (Thu phóng vào)",
            "image_position": "Outro (Cuối video)",
            "image_text": "",
            "text_effect": "Random (Ngẫu nhiên)",
            "text_position": "Dưới cùng (Bottom)",
            "text_size": "60",
            "text_color": "Trắng (White)",
            "encoder": "CPU (libx264)",
            "cpu_preset": "superfast"
        }

        here = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(here, "config.json")
        if not os.path.exists(config_path):
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        config = dict(DEFAULT_CONFIG)
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                    if isinstance(user_cfg, dict):
                        config.update(user_cfg)
            except Exception:
                pass


        slow_factor = float(config.get("slow_factor", 1.05))
        image_dur = float(config.get("image_dur", 3.5))
        total_dur = float(config.get("total_dur", 12.0))
        video_dur = total_dur - image_dur

        motion_effect = config.get("motion_effect", "Zoom In (Thu phóng vào)")
        effect_map = {
            "Zoom In (Thu phóng vào)": "Zoom In",
            "Zoom Out (Thu phóng ra)": "Zoom Out",
            "Pan Left-to-Right (Trượt trái-phải)": "Pan Left-to-Right",
            "Pan Right-to-Left (Trượt phải-trái)": "Pan Right-to-Left",
            "Static (Ảnh tĩnh)": "Static"
        }
        effect = effect_map.get(motion_effect, "Zoom In")
        position = config.get("image_position", "Outro (Cuối video)")

        # Text Overlay
        raw_text = config.get("image_text", "")
        txt_lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        text_effect = config.get("text_effect", "Random (Ngẫu nhiên)")
        text_position = config.get("text_position", "Dưới cùng (Bottom)")
        text_size = config.get("text_size", "60")
        text_color = config.get("text_color", "Trắng (White)")

        # Encoder selection
        encoder_val = config.get("encoder", "CPU (libx264)")
        cpu_preset = config.get("cpu_preset", "superfast")

        # Helpers
        def check_has_audio(vp):
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'a',
                '-show_entries', 'stream=codec_name',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                vp
            ]
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, startupinfo=startupinfo)
                return len(result.stdout.strip()) > 0
            except:
                return False

        def get_video_info(vp):
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,r_frame_rate',
                '-of', 'json',
                vp
            ]
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, startupinfo=startupinfo)
                data = json.loads(result.stdout)
                stream = data['streams'][0]
                width = int(stream['width'])
                height = int(stream['height'])
                fps_str = stream['r_frame_rate']
                if '/' in fps_str:
                    num, den = fps_str.split('/')
                    fps = float(num) / float(den)
                else:
                    fps = float(fps_str)
                return width, height, fps
            except:
                pass
            return 1080, 1920, 30.0

        try:
            has_audio = check_has_audio(video_path)
            width, height, fps = get_video_info(video_path)
            fps_int = int(round(fps))
            if fps_int <= 0:
                fps_int = 30

            total_image_frames = int(image_dur * fps_int)
            max_zoom = 1.3
            w_scale = int(width * max_zoom)
            if w_scale % 2 != 0: w_scale += 1
            h_scale = int(height * max_zoom)
            if h_scale % 2 != 0: h_scale += 1

            zoom_step = 0.3 / total_image_frames

            if effect == "Zoom In":
                zoom_expr = f"min(zoom+{zoom_step:.6f},1.3)"
                x_expr = "iw/2-(iw/zoom/2)"
                y_expr = "ih/2-(ih/zoom/2)"
            elif effect == "Zoom Out":
                zoom_expr = f"max(1.3-{zoom_step:.6f}*on,1.0)"
                x_expr = "iw/2-(iw/zoom/2)"
                y_expr = "ih/2-(ih/zoom/2)"
            elif effect == "Pan Left-to-Right":
                zoom_expr = "1.3"
                x_expr = f"(iw-iw/zoom)*(on/{total_image_frames})"
                y_expr = "(ih-ih/zoom)/2"
            elif effect == "Pan Right-to-Left":
                zoom_expr = "1.3"
                x_expr = f"(iw-iw/zoom)*(1-on/{total_image_frames})"
                y_expr = "(ih-ih/zoom)/2"
            else: # Static
                zoom_expr = "1.0"
                x_expr = "0"
                y_expr = "0"

            video_filter = f"[0:v]setpts={slow_factor}*PTS,scale={width}:{height},fps={fps_int},tpad=stop_mode=clone:stop_duration={video_dur},trim=0:{video_dur},setpts=PTS-STARTPTS[v_part]"
            filter_parts = [video_filter]

            if has_audio:
                audio_slow_factor = 1.0 / slow_factor
                audio_filter = f"[0:a]atempo={audio_slow_factor},apad,atrim=0:{video_dur},asetpts=PTS-STARTPTS[a_part]"
                filter_parts.append(audio_filter)

            if effect == "Static":
                image_filter_base = (
                    f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},"
                    f"fps={fps_int},trim=0:{image_dur},setpts=PTS-STARTPTS"
                )
            else:
                image_filter_base = (
                    f"[1:v]scale={w_scale}:{h_scale}:force_original_aspect_ratio=increase,"
                    f"crop={w_scale}:{h_scale},"
                    f"zoompan=z='{zoom_expr}':d={total_image_frames}:x='{x_expr}':y='{y_expr}':s={width}x{height},"
                    f"fps={fps_int},trim=0:{image_dur},setpts=PTS-STARTPTS"
                )

            txt = ""
            if txt_lines:
                txt = random.choice(txt_lines)

            txt_effect = text_effect
            if txt_effect == "Random (Ngẫu nhiên)":
                valid_effects = ["Chữ tĩnh (Static)", "Mờ dần (Fade In/Out)", "Chạy ngang (Horizontal Scroll)", "Nhấp nháy (Blinking)"]
                txt_effect = random.choice(valid_effects)

            if txt and txt_effect != "Không chèn":
                escaped_txt = txt.replace(":", "\\:").replace("'", "'\\\\''").replace(",", "\\,")
                color_map = {
                    "Trắng (White)": "white",
                    "Vàng (Yellow)": "yellow",
                    "Đỏ (Red)": "red",
                    "Xanh lá (Green)": "green",
                    "Xanh lam (Blue)": "blue"
                }
                ffmpeg_color = color_map.get(text_color, "white")
                try:
                    f_size = int(text_size.strip())
                    if f_size <= 0: f_size = 50
                except ValueError:
                    f_size = 50

                x_val = "(w-text_w)/2"
                pos = text_position
                if pos == "Trên cùng (Top)":
                    y_val = "h*0.1"
                elif pos == "Chính giữa (Center)":
                    y_val = "(h-text_h)/2"
                else:
                    y_val = "h*0.8"

                font_path = "C:\\Windows\\Fonts\\arial.ttf"
                if os.path.exists(font_path):
                    font_opt = "fontfile='C\\:/Windows/Fonts/arial.ttf'"
                else:
                    font_opt = "font='Arial'"

                drawtext_base = (
                    f"drawtext={font_opt}:text='{escaped_txt}':"
                    f"fontsize={f_size}:fontcolor={ffmpeg_color}:box=1:boxcolor=black@0.4:boxborderw=10"
                )

                if txt_effect == "Chữ tĩnh (Static)":
                    image_filter = f"{image_filter_base},{drawtext_base}:x='{x_val}':y='{y_val}'[i_v]"
                elif txt_effect == "Mờ dần (Fade In/Out)":
                    alpha_expr = f"if(lt(t,0.5),t/0.5,if(gt(t,{image_dur}-0.5),({image_dur}-t)/0.5,1))"
                    image_filter = f"{image_filter_base},{drawtext_base}:x='{x_val}':y='{y_val}':alpha='{alpha_expr}'[i_v]"
                elif txt_effect == "Chạy ngang (Horizontal Scroll)":
                    x_scroll = f"w-t*(w+text_w)/{image_dur}"
                    image_filter = f"{image_filter_base},{drawtext_base}:x='{x_scroll}':y='{y_val}'[i_v]"
                elif txt_effect == "Nhấp nháy (Blinking)":
                    alpha_blink = "lt(mod(t,1.0),0.5)"
                    image_filter = f"{image_filter_base},{drawtext_base}:x='{x_val}':y='{y_val}':alpha='{alpha_blink}'[i_v]"
                else:
                    image_filter = f"{image_filter_base}[i_v]"
            else:
                image_filter = f"{image_filter_base}[i_v]"

            filter_parts.append(image_filter)
            image_audio_filter = f"anullsrc=r=48000:cl=stereo,atrim=0:{image_dur},asetpts=PTS-STARTPTS[i_a]"
            filter_parts.append(image_audio_filter)

            if position == "Outro (Cuối video)":
                if has_audio:
                    filter_parts.append("[v_part][a_part][i_v][i_a]concat=n=2:v=1:a=1[outv][outa]")
                    map_args = ["-map", "[outv]", "-map", "[outa]"]
                else:
                    filter_parts.append("[v_part][i_v]concat=n=2:v=1:a=0[outv]")
                    map_args = ["-map", "[outv]"]
            else:
                if has_audio:
                    filter_parts.append("[i_v][i_a][v_part][a_part]concat=n=2:v=1:a=1[outv][outa]")
                    map_args = ["-map", "[outv]", "-map", "[outa]"]
                else:
                    filter_parts.append("[i_v][v_part]concat=n=2:v=1:a=0[outv]")
                    map_args = ["-map", "[outv]"]

            filter_complex_str = "; ".join(filter_parts)

            vcodec = "libx264"
            codec_opts = ["-preset", cpu_preset, "-crf", "22"]
            if "NVIDIA" in encoder_val:
                vcodec = "h264_nvenc"
                codec_opts = ["-preset", "fast", "-gpu", "any"]
            elif "Intel" in encoder_val:
                vcodec = "h264_qsv"
                codec_opts = ["-preset", "veryfast"]
            elif "AMD" in encoder_val:
                vcodec = "h264_amf"
                codec_opts = ["-quality", "speed"]

            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-loop", "1", "-t", str(image_dur), "-i", image_path,
                "-filter_complex", filter_complex_str
            ]
            cmd.extend(map_args)
            cmd.extend(["-c:v", vcodec])
            cmd.extend(codec_opts)

            if has_audio:
                cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            cmd.append(output_path)

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            try:
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, startupinfo=startupinfo, timeout=120)
                return True, ""
            except subprocess.TimeoutExpired:
                return False, "FFmpeg timed out after 120s"
        except Exception as ex:
            return False, str(ex)

    def _sv_on_source_change(self):
        """Khi đổi Nguồn: ẩn/hiện widget Local vs Server (ShopAPI)."""
        is_server = "Server" in self._sv_source.get()

        # --- Widgets CHỈ dành cho Local (ẩn khi Server) ---
        local_widgets = []
        if hasattr(self, '_sv_model_lbl'):
            local_widgets.append(self._sv_model_lbl)
        if hasattr(self, '_sv_model'):
            local_widgets.append(self._sv_model)
        if hasattr(self, '_sv_chk_remove_wm'):
            local_widgets.append(self._sv_chk_remove_wm)
        if hasattr(self, '_sv_chk_ghep_anh'):
            local_widgets.append(self._sv_chk_ghep_anh)
        if hasattr(self, '_sv_chk_laundering'):
            local_widgets.append(self._sv_chk_laundering)

        for w in local_widgets:
            if is_server:
                w.pack_forget()
            else:
                # pack lại nếu chưa có trong layout
                if not w.winfo_ismapped():
                    w.pack(side="left", padx=(0, 12))

        # --- Duration: ẩn khi Server (thời lượng cố định theo engine) ---
        if hasattr(self, '_sv_duration'):
            if is_server:
                self._sv_duration.configure(state="disabled", fg_color="#455A64", text_color="#B0BEC5")
            else:
                self._sv_duration.configure(
                    state="normal",
                    fg_color=ctk.ThemeManager.theme["CTkOptionMenu"]["fg_color"],
                    text_color=ctk.ThemeManager.theme["CTkOptionMenu"]["text_color"]
                )

        # --- ShopAPI row: hiện khi Server, ẩn khi Local ---
        if hasattr(self, '_sv_shopapi_row'):
            if is_server:
                if not self._sv_shopapi_row.winfo_ismapped():
                    self._sv_shopapi_row.pack(fill="x", padx=12, pady=4)
            else:
                self._sv_shopapi_row.pack_forget()

    def _sv_on_model_change(self):
        """Khi đổi Model: Omni Flash → khóa Độ dài theo model (8s/10s); Veo → mở khóa."""
        model_name = self._sv_model.get()
        if "Omni Flash" in model_name:
            # Trích duration từ tên model: "⚡ Omni Flash (Credit, 8s)" → "8s"
            for d in ("4s", "6s", "8s", "10s"):
                if d in model_name:
                    self._sv_duration.set(d)
                    break
            # Khóa dropdown Duration (không cần chọn vì model đã quyết định)
            self._sv_duration.configure(state="disabled", fg_color="#455A64", text_color="#B0BEC5")
            # Omni Flash → cho phép ghép ảnh 12s
            if hasattr(self, '_sv_chk_ghep_anh'):
                self._sv_chk_ghep_anh.configure(state="normal")
        else:
            # Veo 3.1 → mở khóa Duration
            self._sv_duration.configure(
                state="normal",
                fg_color=ctk.ThemeManager.theme["CTkOptionMenu"]["fg_color"],
                text_color=ctk.ThemeManager.theme["CTkOptionMenu"]["text_color"]
            )
        # Gọi lại duration change để cập nhật AI Prompt
        self._sv_on_duration_change()

    def _sv_on_duration_change(self):
        """Khi đổi Độ dài: 8s → khóa AI Prompt thành 'TVC Template'; 16s/24s → mở lại."""
        dur = self._sv_duration.get()
        if dur == "8s":
            # Lưu giá trị AI hiện tại trước khi khóa
            current = self._sv_ai_prompt.get()
            if current not in ("📺 TVC Template",):
                self._sv_ai_saved_value = current
            # Khóa dropdown AI Prompt
            self._sv_ai_prompt.configure(values=["📺 TVC Template"], state="disabled",
                                          fg_color="#455A64", text_color="#B0BEC5")
            self._sv_ai_prompt.set("📺 TVC Template")
            if hasattr(self, '_sv_chk_ghep_anh'):
                self._sv_chk_ghep_anh.configure(state="normal")
        else:
            # Mở khóa dropdown AI Prompt
            self._sv_ai_prompt.configure(
                values=["Gemini", "Groq", "Prompt A + B"],
                state="normal",
                fg_color=ctk.ThemeManager.theme["CTkOptionMenu"]["fg_color"],
                text_color=ctk.ThemeManager.theme["CTkOptionMenu"]["text_color"]
            )
            # Khôi phục giá trị AI đã lưu
            if hasattr(self, '_sv_ai_saved_value') and self._sv_ai_saved_value:
                self._sv_ai_prompt.set(self._sv_ai_saved_value)
            if hasattr(self, '_sv_chk_ghep_anh') and "Omni Flash" not in self._sv_model.get():
                self._sv_ghep_anh.set(False)
                self._sv_chk_ghep_anh.configure(state="disabled")

    def _sv_test_prompt(self):
        """Test prompt cho tab Server — nhập tên SP để xem prompt sinh ra."""
        try:
            # Hỏi tên sản phẩm
            dlg_input = ctk.CTkInputDialog(
                text="Nhập tên sản phẩm muốn test prompt:",
                title="🧪 Test Prompt — Server"
            )
            prod_name = dlg_input.get_input()
            if not prod_name or not prod_name.strip():
                return
            prod_name = prod_name.strip()

            ai_mode = self._sv_ai_prompt.get()
            duration_sec = SV.parse_duration(self._sv_duration.get()) if SV else 16
            n_segments = len(SV.DURATION_MAP.get(duration_sec, [0, 1])) if SV else 2
            scene_choice = self._sv_scene.get()
            lang_val = self._sv_lang.get()
            lang_code = "vi" if "Việt" in lang_val else ("id" if "Indonesia" in lang_val else ("my" if "Malaysia" in lang_val else ("ph" if "Philippines" in lang_val else "en")))
            review_style = self._sv_review_style.get()

            if SV:
                scene_name, scene_en = SV.pick_scene(scene_choice, lang=lang_code)
            else:
                scene_name, scene_en = scene_choice, "clean minimalist desk"

            gemini_keys = [l.strip() for l in self.txt_gemini.get("1.0", "end").splitlines() if l.strip()]
            groq_keys = [l.strip() for l in self.txt_groq_keys.get("1.0", "end").splitlines() if l.strip()]

            if ai_mode == "Gemini" and not gemini_keys:
                messagebox.showwarning("Thiếu Key Gemini", "Vui lòng nạp API Key Gemini ở phần cài đặt API Key.")
                return
            if ai_mode == "Groq" and not groq_keys:
                messagebox.showwarning("Thiếu Key Groq", "Vui lòng nạp API Key Groq ở phần cài đặt API Key.")
                return

            # Mở dialog hiển thị prompt
            dlg = ctk.CTkToplevel(self)
            dlg.title(f"🧪 Test Prompt (Server): {prod_name[:35]}")
            dlg.geometry("720x540")
            dlg.attributes("-topmost", True)
            dlg.after(100, lambda: dlg.attributes("-topmost", False))
            dlg.focus_force()

            ctk.CTkLabel(dlg, text=f"📦 Sản phẩm: {prod_name}", font=("", 13, "bold")).pack(anchor="w", padx=16, pady=(12, 2))
            ctk.CTkLabel(dlg, text=f"🤖 AI: {ai_mode}  |  ⏱ {duration_sec}s ({n_segments} đoạn)  |  🏖 {scene_name}  |  🎬 {review_style}", font=("", 11)).pack(anchor="w", padx=16, pady=(0, 8))

            txt = ctk.CTkTextbox(dlg, font=("Consolas", 10), wrap="word")
            txt.pack(fill="both", expand=True, padx=16, pady=(0, 10))
            txt.insert("1.0", f"⏳ Đang tạo prompt ({ai_mode}), vui lòng chờ...\n")

            def _generate():
                prompts = None
                mode_str = ai_mode
                if ai_mode == "Gemini":
                    prompts = self._sv_ai_gen_prompts(
                        prod_name, scene_en, n_segments, duration_sec, lang_code,
                        review_style, mode="gemini", gemini_keys=gemini_keys
                    )
                elif ai_mode == "Groq":
                    prompts = self._sv_ai_gen_prompts(
                        prod_name, scene_en, n_segments, duration_sec, lang_code,
                        review_style, mode="groq", groq_keys=groq_keys
                    )

                if not prompts and SV:
                    prompts = SV.build_video_prompts(
                        prod_name, scene_en, duration_sec=duration_sec,
                        lang=lang_code, review_style=review_style
                    )
                    if ai_mode in ("Gemini", "Groq"):
                        mode_str += " (Lỗi AI → Dùng Template Mặc Định)"

                def _show_ui():
                    try:
                        txt.delete("1.0", "end")
                        if not prompts:
                            txt.insert("1.0", "❌ Không sinh được prompt.")
                            return
                        header = (
                            f"=== TEST PROMPT (SERVER) ===\n"
                            f"Sản phẩm: {prod_name}\n"
                            f"Engine: {mode_str}\n"
                            f"Kiểu Review: {review_style}\n"
                            f"Khung cảnh: {scene_name}\n"
                            f"Segments: {len(prompts)}\n"
                            + "=" * 60 + "\n\n"
                        )
                        body = ""
                        for idx, pr in enumerate(prompts, 1):
                            body += f"--- SEGMENT {idx} ---\n{pr}\n\n"
                        txt.insert("1.0", header + body)
                    except Exception:
                        pass

                self.after(0, _show_ui)

            threading.Thread(target=_generate, daemon=True).start()
        except Exception as err:
            messagebox.showerror("Lỗi Test Prompt", f"Xảy ra lỗi: {err}")

    def _sv_ai_gen_prompts(self, product_name, scene_en, n_segments,
                            duration_sec, lang_code, review_style,
                            mode="gemini", gemini_keys=None, groq_keys=None):
        """Gọi Gemini hoặc Groq để sinh prompt video review sản phẩm chất lượng cao.
        Trả về list[str] prompts hoặc None nếu thất bại."""
        lang_map = {"vi": "Vietnamese", "en": "English", "id": "Indonesian", "my": "Malay", "ph": "Filipino"}
        lang_name = lang_map.get(lang_code, "English")

        # Mô tả phong cách review — 7 kiểu chuyên dụng cho video affiliate
        _REVIEW_STYLE_DESCS = {
            "Review tự nhiên": (
                "NATURAL STANDING REVIEW style: The presenter stands naturally, picks up the product, "
                "walks around the scene, holds items up to camera. Free movement, energetic and authentic. "
                "Casual handheld camera feel with smooth tracking. "
                "CAMERA: Medium shot, handheld with subtle natural shake, 35mm lens feel. "
                "LIGHTING: Natural window light from the side, mixed with warm indoor ambient light, soft shadows. "
                "ENVIRONMENT: Clean but lived-in room, slightly visible background details for authenticity. "
                "ANTI-AI: Include slight camera drift, natural micro-expressions, smartphone camera quality feel."
            ),
            "Ngồi Review": (
                "SEATED DESK REVIEW style: The presenter sits behind a clean minimalist wooden desk "
                "throughout the ENTIRE video. She NEVER stands up or walks. All product interactions "
                "happen on the desk or held above it. Camera is at desk-level, frontal or slightly angled. "
                "CAMERA: Static or slow push-in, eye-level, 50mm lens feel. "
                "LIGHTING: Soft LED panel or ring light from front, warm tone, even illumination. "
                "ENVIRONMENT: Clean desk surface, minimalist background, soft bokeh. "
                "ANTI-AI: Natural hand gestures, occasional glance away from camera, realistic skin texture."
            ),
            "POV (Góc nhìn thứ nhất)": (
                "POV FIRST-PERSON style: Camera IS the viewer's eyes. We NEVER see the presenter's face. "
                "Only hands and arms visible interacting with the product. The viewer feels like THEY are "
                "the one holding, opening, and using the product themselves. "
                "CAMERA: First-person POV, over-the-shoulder or looking-down angle, handheld with natural shake. "
                "LIGHTING: Natural mixed indoor light, overhead kitchen/room light, uncontrolled ambient. "
                "ENVIRONMENT: Real desk/table/counter surface, slight clutter (pen, coffee mug, receipts) for authenticity. "
                "ANTI-AI: Slight lens flare from room lamp, visible fingerprints/dust on product, "
                "natural hand movement speed (not too smooth), iPhone camera compression feel. "
                "CRITICAL: NO face visible. Only hands and forearms. Product is the HERO."
            ),
            "Unboxing": (
                "UNBOXING style: Focus on the satisfying experience of opening packaging and revealing "
                "the product for the first time. Slow, deliberate hand movements. Build anticipation. "
                "CAMERA: Top-down flat lay angle for opening, then switch to close-up for product reveal. "
                "Handheld with subtle movement. "
                "LIGHTING: Warm overhead light, soft shadows on packaging textures, cozy atmosphere. "
                "ENVIRONMENT: Clean wooden desk or floor surface, minimal props (scissors, knife nearby). "
                "ANTI-AI: Include satisfying paper rustling and packaging sounds, tactile textures visible, "
                "slight pause of genuine excitement when product is revealed, natural finger movements "
                "(not perfectly smooth). ASMR-adjacent aesthetic — crisp sounds, deliberate slow pacing. "
                "CRITICAL: Show FULL unboxing journey — sealed box → cutting tape → lifting lid → reveal."
            ),
            "UGC Authentic": (
                "UGC AUTHENTIC style: Raw, unpolished, genuine — like a real customer sharing with friends. "
                "NOT a professional review. This should feel like someone filming with their phone in their "
                "bedroom, genuinely excited about a product they just received. "
                "CAMERA: iPhone selfie front-camera angle, slightly off-center framing, visible camera shake, "
                "occasional focus hunting, vlog-style close talking distance. "
                "LIGHTING: Messy mixed lighting — bedroom lamp + phone screen glow + window light, "
                "NOT studio lighting, slightly warm/yellow indoor tone. "
                "ENVIRONMENT: Slightly messy bedroom or living room, pillows/blankets visible, "
                "personal items in background, lived-in and imperfect. "
                "ANTI-AI: Include casual speech cadence (slight pauses, 'um'), genuine excitement not "
                "performative, natural skin texture with no filter, hair slightly imperfect, "
                "camera tilts/adjusts mid-shot. Shot on smartphone quality — slight grain, natural compression. "
                "CRITICAL: Must feel like a REAL person's phone video, NOT a commercial."
            ),
            "Demo Công Dụng": (
                "PRODUCT DEMONSTRATION style: Focus entirely on showing HOW the product works. "
                "Step-by-step functional demonstration with clear visibility of features and results. "
                "CAMERA: Alternating between close-up macro shots (product details, buttons, textures) "
                "and medium shots (hands demonstrating usage). Steady, controlled movement. "
                "LIGHTING: Bright, even, clinical-style lighting for maximum product visibility. "
                "Natural daylight or bright LED, no dramatic shadows — clarity is priority. "
                "ENVIRONMENT: Clean test surface — white/light desk, neutral background, "
                "comparison items nearby if relevant (ruler for scale, water for waterproof test). "
                "ANTI-AI: Show REAL interaction physics — weight of product visible in hand grip, "
                "realistic material textures, functional result visible (cream absorbed, device screen lit up, "
                "sound produced). Include before/after moments where relevant. "
                "CRITICAL: Product FUNCTIONALITY is the hero — every shot must demonstrate a specific feature."
            ),
            "So Sánh/Đánh Giá": (
                "COMPARISON REVIEW style: Side-by-side honest evaluation. The presenter compares "
                "the product against expectations, price point, or similar alternatives. "
                "Analytical, trustworthy, 'brutally honest' tone. "
                "CAMERA: Medium shot with both products visible, alternating close-ups on each, "
                "split-frame composition when comparing features. Steady tripod feel. "
                "LIGHTING: Consistent even lighting on both products — no favoritism in presentation. "
                "Bright, neutral-tone daylight or LED panel. "
                "ENVIRONMENT: Clean comparison surface, both products clearly labeled/visible, "
                "perhaps a notepad or checklist visible for systematic review. "
                "ANTI-AI: Show genuine contemplation (touching chin, slight frown while thinking), "
                "honest facial reactions (impressed nod OR disappointed head shake), "
                "realistic material/texture differences visible between products. "
                "CRITICAL: Must show BOTH positive and negative aspects — not purely promotional."
            ),
        }
        if review_style in ("🎲 Random", "Random") or not review_style or "random" in str(review_style).lower():
            import random as _rnd
            actual_style = _rnd.choice(list(_REVIEW_STYLE_DESCS.keys()))
            style_desc = _REVIEW_STYLE_DESCS[actual_style]
        else:
            style_desc = _REVIEW_STYLE_DESCS.get(review_style, _REVIEW_STYLE_DESCS["Review tự nhiên"])

        # Mô tả kịch bản theo số segment
        if n_segments == 2:
            flow_desc = (
                "VIDEO FLOW (2 segments × 8 seconds = 16 seconds total):\n"
                "- Segment 1 (8s): Opening — presenter discovers/picks up the product with genuine excitement, "
                "examines it closely, shows key features while speaking enthusiastically about it.\n"
                "- Segment 2 (8s): Closing — presenter demonstrates the product in use, gives final verdict "
                "with confident smile, nods approvingly, and gives a thumbs up to recommend it.\n"
                "CONTINUITY: Segment 2 must start from the EXACT pose/position where Segment 1 ended."
            )
        else:
            flow_desc = (
                "VIDEO FLOW (3 segments × 8 seconds = 24 seconds total):\n"
                "- Segment 1 (8s): Opening — presenter reveals the product with excitement, picks it up, "
                "examines the packaging/design while introducing the product by name.\n"
                "- Segment 2 (8s): Middle — close-up showcase of product features and details, presenter "
                "demonstrates how to use it, touches textures, shows different angles.\n"
                "- Segment 3 (8s): Closing — presenter gives final review verdict, shows satisfaction, "
                "recommends with enthusiasm, smiles warmly and gives thumbs up.\n"
                "CONTINUITY: Each segment must start from the EXACT pose/position where the previous one ended."
            )

        system_prompt = (
            f"You are an expert prompt engineer for Google Veo 3 (image-to-video AI).\n"
            f"Write EXACTLY {n_segments} video prompts for a Shopee product review.\n\n"
            f"═══ PRODUCT INFO ═══\n"
            f"Product Name: \"{product_name}\"\n"
            f"(This product name is from Shopee. Use it to infer what the product looks like and how to review it.)\n\n"
            f"═══ VIDEO SETTINGS ═══\n"
            f"Total Duration: {duration_sec} seconds ({n_segments} segments × 8 seconds each)\n"
            f"Background/Scene: {scene_en}\n"
            f"Presenter Language: {lang_name}\n"
            f"Review Style: {style_desc}\n\n"
            f"═══ {flow_desc} ═══\n\n"
            f"═══ 6-SECTION PROMPT STRUCTURE & PROMPT LOCKS ═══\n"
            f"Each output prompt must strictly incorporate these 6 sections and prompt locks:\n"
            f"1. SECTION 1 (GENERAL RULES & LOCKS):\n"
            f"   - FRAMING LOCK: Full-frame vertical 9:16 portrait video. Reference image fills frame edge-to-edge with NO letterboxing, NO pillarboxing, NO black bars, NO white borders, NO storyboard/collage layout.\n"
            f"   - PRODUCT CONSISTENCY LOCK: The product shown in frame 1 must be the EXACT SAME product in every subsequent frame. Color, shape, size, material texture, and logos must NOT change, swap, or transform at any point (especially final 1-2s).\n"
            f"   - HAND & ANATOMY LOCK: The presenter has exactly TWO normal human hands with 5 fingers each. DO NOT generate extra hands, extra arms, extra fingers, or limb deformations.\n"
            f"   - ITEM PERSISTENCE: Any object held or worn must remain naturally present throughout.\n"
            f"2. SECTION 2 (PRODUCT TO ADVERTISE): \"{product_name}\" is the HERO. Prominently featured and in sharp focus.\n"
        )
        # Malaysia: 100% Mẫu Nam (Male Model) an toàn tuyệt đối
        if lang_code == "my":
            system_prompt += (
                f"3. SECTION 3 (PRESENTER & OUTFIT LOCK): Define ONE fixed Malay MALE presenter (~25-30yo, "
                f"modest clothing: clean long-sleeve button-down or polo shirt, dark trousers, neat well-groomed hair, "
                f"friendly professional appearance) and REPEAT THAT EXACT MALE CHARACTER AND "
                f"OUTFIT DESCRIPTION VERBATIM in all {n_segments} prompts. (CRITICAL: MUST be a MALE presenter, NO female model).\n"
            )
        else:
            system_prompt += (
                f"3. SECTION 3 (PRESENTER & OUTFIT LOCK): Define ONE fixed presenter anchor (~22-26yo Asian woman, "
                f"exact face, exact hairstyle, exact clothing outfit style and color) and REPEAT THAT EXACT "
                f"CHARACTER AND OUTFIT DESCRIPTION VERBATIM in all {n_segments} prompts.\n"
            )
        system_prompt += (
            f"4. SECTION 4 (ACTION & TIMELINE CONTINUITY):\n"
            f"   - Follow strict timeline progression (0-1s anchor/intro, 1-3s speaking/handling, 3-7s demonstration/gestures, 7-8s CRITICAL RETURN TO REFERENCE & FREEZE to static handoff pose).\n"
            f"   - Segment 1 ends with a distinct static pose; Segment 2 starts EXACTLY from that pose. Segment 2 ends with a distinct pose; Segment 3 starts EXACTLY from that pose.\n"
            f"5. SECTION 5 (CAMERA & TECHNICAL SPECS): Smartphone-style photorealism, eye-level angle, 35mm/50mm lens feel, natural soft lighting, clean white balance, optical depth of field.\n"
            f"6. SECTION 6 (DIALOGUE SCRIPT): The presenter speaks naturally in {lang_name} about \"{product_name}\" (authentic UGC tone, ~15-20 words, no exaggerated claims, ending with soft CTA).\n\n"
            f"═══ OUTPUT FORMAT ═══\n"
            f"Output EXACTLY {n_segments} lines. One prompt per line.\n"
            f"No numbering (1. 2. 3.), no bullet points, no markdown, no explanations.\n"
            f"Just {n_segments} raw prompt lines.\n"
        )

        # Định nghĩa hàm gọi Gemini helper xoay vòng (Round-Robin so le qua tất cả API keys)
        def _run_gemini(keys):
            if not keys: return None
            with getattr(self, "_ai_key_lock", threading.Lock()):
                start_idx = getattr(self, "_gemini_key_rr_idx", 0) % len(keys)
                self._gemini_key_rr_idx = getattr(self, "_gemini_key_rr_idx", 0) + 1
            # Xếp danh sách key bắt đầu từ start_idx rồi xoay vòng đều cho các luồng
            keys_ordered = list(keys[start_idx:]) + list(keys[:start_idx])
            
            # Thứ tự model ưu tiên: gemini-flash-lite-latest (quota dồi dào nhất) → gemini-3.5-flash-lite → gemini-3.1-flash-lite → gemini-3-flash-preview → gemini-3.5-flash → gemini-3.7-flash
            _MODELS = ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.7-flash"]
            for key in keys_ordered:
                k_tag = f"...{key[-6:]}" if len(key) >= 6 else key
                for model_name in _MODELS:
                    try:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
                        payload = json.dumps({
                            "contents": [{"parts": [{"text": system_prompt}]}],
                            "generationConfig": {"temperature": 0.9}
                        }).encode("utf-8")
                        req = urllib.request.Request(url, data=payload,
                                                     headers={"Content-Type": "application/json"})
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                        text = ""
                        for part in (data.get("candidates", [{}])[0].get("content", {}).get("parts", [])):
                            text += part.get("text", "")
                        prompts = [p.strip() for p in text.strip().split("\n") if p.strip() and len(p.strip()) > 20]
                        if len(prompts) >= n_segments:
                            self._sv_log_msg(f"  ✅ Gemini OK ({model_name} | key {k_tag})")
                            return prompts[:n_segments]
                    except urllib.error.HTTPError as he:
                        if he.code == 429:
                            self._sv_log_msg(f"  ⚠ {model_name} key {k_tag} quota 429 → chuyển key/model tiếp")
                            continue  # thử model tiếp trong _MODELS
                        self._sv_log_msg(f"  ⚠ Gemini {model_name} key {k_tag} HTTP {he.code}")
                        break  # lỗi khác → thử key khác
                    except Exception as e:
                        self._sv_log_msg(f"  ⚠ Gemini key {k_tag} lỗi: {str(e)[:50]}")
                        break
            return None

        # Định nghĩa hàm gọi Groq helper (Cố định model llama-3.1-8b-instant, xoay vòng so le API keys)
        def _run_groq(keys):
            if not keys: return None
            with getattr(self, "_ai_key_lock", threading.Lock()):
                start_idx = getattr(self, "_groq_key_rr_idx", 0) % len(keys)
                self._groq_key_rr_idx = getattr(self, "_groq_key_rr_idx", 0) + 1
            keys_ordered = list(keys[start_idx:]) + list(keys[:start_idx])
            groq_model = "llama-3.1-8b-instant"
            for key in keys_ordered:
                k_tag = f"...{key[-6:]}" if len(key) >= 6 else key
                try:
                    url = "https://api.groq.com/openai/v1/chat/completions"
                    payload = json.dumps({
                        "model": groq_model,
                        "messages": [
                            {"role": "system", "content": "You generate Google Veo 3 video prompts for Shopee product reviews."},
                            {"role": "user", "content": system_prompt}
                        ],
                        "temperature": 0.9,
                        "max_tokens": 2000
                    }).encode("utf-8")
                    req = urllib.request.Request(url, data=payload, headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {key}",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    })
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    prompts = [p.strip() for p in text.strip().split("\n") if p.strip() and len(p.strip()) > 20]
                    if len(prompts) >= n_segments:
                        self._sv_log_msg(f"  ✅ Groq OK ({groq_model} | key {k_tag})")
                        return prompts[:n_segments]
                except Exception as e:
                    err_str = str(e).lower()
                    if any(tok in err_str for tok in ("401", "403", "restricted", "blocked", "invalid", "forbidden")):
                        self._sv_log_msg(f"  ⚠ Groq key {k_tag} bị khóa/lỗi ({e}) → Chuyển key tiếp theo.")
                        continue
                    continue
            return None

        # Thực hiện gọi và tự động fallback
        if mode == "gemini":
            if gemini_keys:
                res = _run_gemini(gemini_keys)
                if res: return res
            if groq_keys:
                self._sv_log_msg("  🔄 Gemini thất bại, tự động chuyển sang Groq...")
                res = _run_groq(groq_keys)
                if res: return res
        elif mode == "groq":
            if groq_keys:
                res = _run_groq(groq_keys)
                if res: return res
            if gemini_keys:
                self._sv_log_msg("  🔄 Groq thất bại, tự động chuyển sang Gemini...")
                res = _run_gemini(gemini_keys)
                if res: return res
        return None

    def _sv_init_shopapi_client(self):
        """Khởi tạo ShopAPI client từ API Key đã nhập."""
        import sys
        sdk_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_sdk")
        if not os.path.isdir(sdk_dir):
            raise ImportError(f"Không tìm thấy thư mục SDK '{sdk_dir}'.\nHãy copy cả thư mục '_sdk' sang máy này.")
        if sdk_dir not in sys.path:
            sys.path.insert(0, sdk_dir)
        try:
            from shopapi import ShopAPI
        except ImportError as e:
            if "httpx" in str(e).lower():
                raise ImportError("Thiếu thư viện 'httpx' để chạy ShopAPI.\nHãy chạy 'SETUP.bat' hoặc lệnh: pip install httpx")
            raise ImportError(f"Lỗi tải module ShopAPI: {e}\nHãy kiểm tra thư mục '_sdk/shopapi' hoặc chạy SETUP.bat.")
        api_key = self._sv_shopapi_key.get().strip()
        if not api_key:
            raise ValueError("Chưa nhập ShopAPI API Key.\nVui lòng nhập key ở ô 🔑 ShopAPI Key.")
        return ShopAPI(api_key=api_key)

    def _sv_start_shopapi(self, shopapi_client):
        """Bắt đầu tạo video qua ShopAPI — tuân thủ 100% hợp đồng API ShopAPI."""
        out_dir = self._sv_outdir.get().strip()
        products = list(self._sv_claimed_products)
        scene_choice = self._sv_scene.get()
        naming_mode = self._sv_naming.get()
        client_id = self._sv_client_entry.get().strip()
        ai_mode = self._sv_ai_prompt.get()
        review_style = self._sv_review_style.get()
        del_img = self._sv_del_img.get()

        # Quy tắc 1: Luôn gửi engine="auto", chọn thời lượng theo dropdown (8s hoặc 10s)
        engine_raw = self._sv_shopapi_engine.get()
        shopapi_duration = 10 if "10s" in engine_raw or "seedance" in engine_raw.lower() else 8

        # Đọc duration_sec từ dropdown Độ dài (8s, 16s, 24s) — dùng cho logic multi-segment
        duration_sec = SV.parse_duration(self._sv_duration.get()) if SV else 16
        n_segments_needed = len(SV.DURATION_MAP.get(duration_sec, [0])) if SV else 1

        # Aspect ratio: chuyển từ format Local sang format ShopAPI
        aspect_local = self._sv_aspect.get()
        if "9:16" in aspect_local:
            shopapi_aspect = "9:16"
        elif "16:9" in aspect_local:
            shopapi_aspect = "16:9"
        else:
            shopapi_aspect = "9:16"

        lang_val = self._sv_lang.get()
        lang_code = "vi" if "Việt" in lang_val else ("id" if "Indonesia" in lang_val else ("my" if "Malaysia" in lang_val else ("ph" if "Philippines" in lang_val else "en")))

        # Gắn mô tả giọng nói
        manual_voice = self.ent_voice_desc.get().strip()
        E.VOICE_DESC = manual_voice if manual_voice else E.get_voice_for_lang(lang_code)

        # Load Gemini/Groq keys cho AI prompt generation (cần khi 16s/24s)
        sv_gemini_keys = [k.strip() for k in self.txt_gemini.get("1.0", "end").splitlines() if k.strip()]
        sv_groq_key = [k.strip() for k in self.txt_groq.get("1.0", "end").splitlines() if k.strip()] if hasattr(self, 'txt_groq') else []

        # Lưu settings
        self.settings["sv_source"] = self._sv_source.get()
        self.settings["sv_shopapi_key"] = self._sv_shopapi_key.get().strip()
        self.settings["sv_shopapi_engine"] = engine_raw
        self.settings["sv_naming"] = naming_mode
        self.settings["sv_review_style"] = review_style
        self.settings["sv_ai_prompt"] = ai_mode

        # UI states
        self._sv_running = True
        self._sv_stop_flag = False
        self._sv_btn_start.configure(state="disabled")
        self._sv_btn_stop.configure(state="normal")
        self._sv_btn_claim.configure(state="disabled")
        self._sv_status_lbl.configure(text="⏳ Đang tạo video (ShopAPI)...")
        self._sv_last_video_time = time.time()

        def work():
            total = len(products)
            temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_render")
            os.makedirs(temp_dir, exist_ok=True)
            os.makedirs(out_dir, exist_ok=True)

            seg_info = f"{n_segments_needed} segment × 8s" if n_segments_needed > 1 else f"{shopapi_duration}s"
            self._sv_log_msg(f"🌐 Chế độ ShopAPI — Engine: auto | Video: {duration_sec}s ({seg_info}) | Tỉ lệ: {shopapi_aspect}")

            # Quy tắc 7: Đọc sức chứa từ /v1/capacity hoặc /v1/me, không gõ cứng
            def _get_dynamic_capacity():
                try:
                    cap_data = shopapi_client.request("GET", "/v1/capacity")
                    if isinstance(cap_data, dict):
                        v_cap = cap_data.get("video")
                        if isinstance(v_cap, dict):
                            avail = v_cap.get("available") or (v_cap.get("capacity", 0) - v_cap.get("running", 0))
                            if avail and avail > 0:
                                return max(1, int(avail))
                        elif isinstance(v_cap, (int, float)) and v_cap > 0:
                            return max(1, int(v_cap))
                except Exception:
                    pass

                try:
                    me = shopapi_client.request("GET", "/v1/me")
                    limits = me.get("limits", {})
                    detail = (limits.get("concurrent_jobs_detail") or {}).get("video") or {}
                    capacity = int(detail.get("capacity") or 0)
                    running = int(detail.get("running") or 0)
                    if capacity > 0:
                        return max(1, capacity - running)
                    concur = int((limits.get("concurrent_jobs") or {}).get("video") or 4)
                    return max(1, concur)
                except Exception:
                    return 4

            dyn_cap = _get_dynamic_capacity()
            n_workers = max(1, min(dyn_cap, total))
            self._sv_log_msg(f"🏭 Sức chứa ShopAPI khả dụng: {dyn_cap} → Cấp phát {n_workers} luồng xử lý")
            self._sv_log_msg(f"📋 {total} SP — bắt đầu tạo video qua ShopAPI...")

            done_count = [0]
            self._sv_video_done_count = 0
            self.after(0, lambda: self._sv_video_done_lbl.configure(text=""))
            error_count = [0]
            results_lock = threading.Lock()
            jobq = queue.Queue()
            for idx, prod in enumerate(products):
                prod["_idx"] = idx
                prod["_cycles"] = 0
                jobq.put(prod)

            self._sv_done_timestamps = collections.deque()
            self._sv_pool_states = None

            def submit_video_with_retry(prompt, image_url, idempotency_key):
                """Quy tắc 1, 2, 3: engine='auto', gửi idempotency_key cũ khi retry, xử lý 503/429 bằng Retry-After."""
                max_retries = 8
                for attempt in range(max_retries):
                    if self._sv_stop_flag:
                        return "stopped", None
                    try:
                        job = shopapi_client.videos.create(
                            prompt=prompt,
                            engine="auto",  # Quy tắc 1: Luôn gửi engine="auto"
                            duration=shopapi_duration,
                            aspect_ratio=shopapi_aspect,
                            image_url=image_url,
                            idempotency_key=idempotency_key,  # Quy tắc 2: Idempotency-Key
                        )
                        return "ok", job
                    except Exception as ex:
                        err_str = str(ex)
                        # Kiểm tra hết số dư
                        if "402" in err_str or "insufficient" in err_str.lower():
                            self._sv_log_msg(f"  💸 Hết số dư ShopAPI! Vui lòng nạp thêm tại shopapi.vn")
                            return "insufficient_balance", err_str

                        # Quy tắc 3: Xử lý 503 và 429 bằng Retry-After
                        status_code = getattr(ex, "status", None) or getattr(ex, "status_code", None)
                        retry_after = getattr(ex, "retry_after", None)
                        if retry_after is None and hasattr(ex, "response"):
                            retry_hdr = getattr(ex.response, "headers", {}).get("Retry-After")
                            if retry_hdr:
                                try: retry_after = float(retry_hdr)
                                except: pass

                        is_server_busy = (
                            status_code in (429, 502, 503, 504)
                            or "503" in err_str or "429" in err_str
                            or "engine_unavailable" in err_str
                            or "rate_limit" in err_str.lower()
                            or "sự cố" in err_str.lower()
                            or "bận" in err_str.lower()
                        )
                        if is_server_busy and attempt < max_retries - 1:
                            wait_s = max(5.0, min(float(retry_after or (10.0 * (attempt + 1))), 60.0))
                            self._sv_log_msg(f"  ⏳ Máy chủ bận/503/429 ({status_code or 'busy'}) → Chờ {int(wait_s)}s theo Retry-After rồi gửi lại...")
                            t0 = time.monotonic()
                            while time.monotonic() - t0 < wait_s:
                                if self._sv_stop_flag:
                                    return "stopped", None
                                time.sleep(1)
                            continue

                        # Lỗi khác hoặc hết lượt retry
                        self._sv_log_msg(f"  ❌ ShopAPI lỗi submit: {err_str[:80]}")
                        return "error", err_str
                return "error", "Hết số lần thử gửi job"

            def poll_job_until_done(job_id):
                """Polling ShopAPI job. Poll nhanh (5s) → tăng nhẹ → tối đa 15s, timeout 5 phút."""
                poll_interval = 5.0
                max_timeout = 300.0   # 5 phút
                start_t = time.monotonic()

                while True:
                    if self._sv_stop_flag:
                        return "retry_soft", None

                    # Ngủ poll_interval (chia nhỏ từng 1s để dừng ngay khi người dùng bấm Stop)
                    t_sleep_start = time.monotonic()
                    while time.monotonic() - t_sleep_start < poll_interval:
                        if self._sv_stop_flag:
                            return "retry_soft", None
                        time.sleep(1)

                    if time.monotonic() - start_t > max_timeout:
                        self._sv_log_msg(f"  ⏰ Timeout 5 phút cho job {job_id[:16]}... bỏ qua")
                        return "retry_temporary", "Timeout 300s"

                    try:
                        result = shopapi_client.jobs.retrieve(job_id)
                    except Exception as ex:
                        self._sv_log_msg(f"  ⚠ Lỗi mạng khi kiểm tra job ({ex}), sẽ thử lại...")
                        poll_interval = min(15.0, poll_interval + 2)
                        continue

                    status = result.get("status", "")

                    if status in ("succeeded", "done"):
                        return "succeeded", result
                    elif status in ("failed", "cancelled", "rejected"):
                        err_info = result.get("error") or {}
                        if not isinstance(err_info, dict):
                            err_info = {"message": str(err_info)}
                        is_retryable = bool(err_info.get("retryable", False))
                        err_msg = err_info.get("message", "Job không thành công")
                        refunded = result.get("refunded")
                        refund_str = f" (đã hoàn {refunded} µVND)" if refunded else ""

                        if is_retryable:
                            self._sv_log_msg(f"  🔄 Máy chủ lỗi tạm thời [retryable=True]{refund_str}: {err_msg[:60]} → Tạo lại job mới sau")
                            return "retry_temporary", err_msg
                        else:
                            self._sv_log_msg(f"  ❌ Lỗi dữ liệu/chính sách [retryable=False]: {err_msg[:80]}")
                            return "fail_permanent", err_msg
                    else:
                        # pending/processing — tăng nhẹ interval, tối đa 15s
                        poll_interval = min(15.0, poll_interval + 2)

            def process_one_shopapi(prod):
                idx = prod["_idx"]
                if self._sv_stop_flag:
                    return "retry_soft"

                item_id = prod.get("item_id", "")
                product_name = prod.get("name", f"Product_{item_id}")
                image_url = prod.get("image_url", "")

                self._sv_update_line_status(idx, "running")
                self._sv_log_msg(f"\n{'='*50}")
                self._sv_log_msg(f"📦 [{idx+1}/{total}] {product_name[:50]} [ShopAPI]")

                # --- Tải ảnh SP từ Shopee CDN ---
                img_path = os.path.join(temp_dir, f"{item_id}.jpg")
                if not os.path.isfile(img_path):
                    if not image_url:
                        self._sv_log_msg(f"  ⚠ SP {item_id}: không có image_url → bỏ qua")
                        prod["_status"] = "noretry"
                        try: self._sv_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "failed", "tool": "thinaptm"})
                        except: pass
                        self._sv_update_line_status(idx, "error")
                        return ("fail", "Không có image_url")
                    self._sv_log_msg(f"  📥 Tải ảnh: {image_url[:60]}...")
                    if not self._sv_download_image(image_url, img_path):
                        prod["_status"] = "noretry"
                        try: self._sv_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "failed", "tool": "thinaptm"})
                        except: pass
                        self._sv_update_line_status(idx, "error")
                        return ("fail", "Tải ảnh thất bại")
                    self._sv_log_msg(f"  ✅ Ảnh đã tải: {os.path.basename(img_path)}")
                else:
                    self._sv_log_msg(f"  ⚡ Dùng ảnh đã tải: {os.path.basename(img_path)}")

                # --- Sinh prompt video (dùng chung logic với Local) ---
                scene_name, scene_en = SV.pick_scene(scene_choice, lang=lang_code)

                if n_segments_needed == 1:
                    # === CHẾ ĐỘ 8s: TVC prompt cố định ===
                    _tvc_lang_map = {
                        "en": {"nationality": "American", "language": "English"},
                        "vi": {"nationality": "Việt Nam", "language": "tiếng Việt"},
                        "id": {"nationality": "Indonesian", "language": "tiếng Indonesia"},
                        "my": {"nationality": "Malaysian", "language": "tiếng Malaysia (Bahasa Melayu)"},
                        "ph": {"nationality": "Filipino", "language": "Filipino"},
                    }
                    _tvc = _tvc_lang_map.get(lang_code, _tvc_lang_map["en"])
                    short_name = product_name[:80].strip()
                    # Malaysia: 100% Mẫu Nam (Male Model) an toàn tuyệt đối
                    if lang_code == "my":
                        tvc_prompt = (
                            f'Create a product advertisement video (TVC) reviewing the product "{short_name}". '
                            f'A handsome Malay male model, modest clothing (clean long-sleeve shirt, dark trousers), about 25 years old, '
                            f'holds the product and introduces its key benefits. '
                            f'He states the benefits right away without any introduction. '
                            f'He speaks {_tvc["language"]}; no text is displayed in the video. '
                            f'The product is accurately sized. '
                            f'The product price is not mentioned in the video.'
                        )
                    else:
                        tvc_prompt = (
                            f'Create a product advertisement video (TVC) reviewing the product "{short_name}". '
                            f'A beautiful {_tvc["nationality"]} woman, about 20 years old, holds the product and introduces its key benefits. '
                            f'She states the benefits right away without any introduction. '
                            f'She speaks {_tvc["language"]}; no text is displayed in the video. '
                            f'The product is accurately sized. '
                            f'Her outfit is modest and appropriate, not revealing or offensive. '
                            f'The product price is not mentioned in the video.'
                        )
                    prompts = [tvc_prompt]
                    self._sv_log_msg(f"  📺 TVC 8s: 1 prompt (Mẫu Nam)")
                else:
                    # === CHẾ ĐỘ 16s/24s: AI hoặc Template sinh nhiều prompt ===
                    prompts = None
                    if ai_mode == "Gemini":
                        prompts = self._sv_ai_gen_prompts(
                            product_name, scene_en, n_segments_needed,
                            duration_sec, lang_code, review_style,
                            mode="gemini", gemini_keys=sv_gemini_keys, groq_keys=sv_groq_key
                        )
                    elif ai_mode == "Groq":
                        prompts = self._sv_ai_gen_prompts(
                            product_name, scene_en, n_segments_needed,
                            duration_sec, lang_code, review_style,
                            mode="groq", gemini_keys=sv_gemini_keys, groq_keys=sv_groq_key
                        )

                    if prompts and len(prompts) >= n_segments_needed:
                        prompts = prompts[:n_segments_needed]
                        self._sv_log_msg(f"  🤖 AI sinh {len(prompts)} prompt ({ai_mode}, cảnh: {scene_name})")
                    else:
                        # Fallback về Prompt A + B nếu AI thất bại
                        prompts = SV.build_video_prompts_fallback(product_name, scene_en, duration_sec, lang=lang_code, review_style=review_style)
                        if ai_mode not in ("Prompt A + B", "Template (mặc định)"):
                            self._sv_log_msg(f"  ⚠ AI thất bại → dùng Prompt A + B fallback")
                        else:
                            self._sv_log_msg(f"  📝 Prompt A + B sinh {len(prompts)} prompt (cảnh: {scene_name})")
                n_segments = len(prompts)

                # --- Xác định image_url cho ShopAPI ---
                if image_url and image_url.lower().startswith("https://") and len(image_url) <= 2000 and not any(loc in image_url.lower() for loc in ("://localhost", "://127.", "://0.0.0.0", "://192.168.")):
                    shopapi_image_url = image_url
                    self._sv_log_msg(f"  🔗 Dùng link ảnh gốc: {shopapi_image_url[:60]}...")
                else:
                    self._sv_log_msg(f"  📤 Upload ảnh lên ShopAPI...")
                    try:
                        shopapi_image_url = shopapi_client.uploads.upload_file(img_path)
                        if not shopapi_image_url:
                            self._sv_log_msg(f"  ❌ Upload thành công nhưng không nhận được URL ảnh")
                            return "retry_soft"
                        self._sv_log_msg(f"  ✅ Upload OK: {str(shopapi_image_url)[:60]}...")
                    except Exception as ex:
                        self._sv_log_msg(f"  ❌ Upload lỗi: {ex}")
                        return "retry_soft"

                # --- Tạo video từng segment ---
                clip_paths = []
                for seg_idx, prompt in enumerate(prompts):
                    if self._sv_stop_flag:
                        return "retry_soft"
                    clip_path = os.path.join(temp_dir, f"sv_{item_id}_seg{seg_idx}.mp4")
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 100 * 1024:
                        self._sv_log_msg(f"  ⚡ Segment {seg_idx+1}: Dùng lại ({os.path.getsize(clip_path)//1024}KB)")
                        clip_paths.append(clip_path)
                        continue

                    # Quy tắc 2: Idempotency-Key
                    key_field = f"_idem_{seg_idx}"
                    if not prod.get(key_field):
                        prod[key_field] = str(uuid.uuid4())
                    idempotency_key = prod[key_field]

                    self._sv_log_msg(f"  🎬 Tạo video segment {seg_idx+1}/{n_segments} qua ShopAPI (auto | 8s)...")
                    # ShopAPI giới hạn prompt tối đa 5000 ký tự
                    # Rút gọn SECTION 1 (Negative Constraints) từ ~2500 → ~300 ký tự, giữ nguyên ý
                    api_prompt = prompt
                    if len(api_prompt) > 4900:
                        import re
                        CONDENSED_SEC1 = (
                            "=== SECTION 1: RULES ===\n"
                            "- Full-frame 9:16 vertical video, edge-to-edge, NO borders/bars/margins/letterbox.\n"
                            "- Photorealistic live-action only. NO cartoon/anime/illustration/CGI.\n"
                            "- NO text/subtitles/watermarks/UI overlays on screen.\n"
                            "- Product must match reference image exactly (shape, color, size, labels).\n"
                            "- Realistic product size proportional to human body. NO oversized items.\n"
                            "- Presenter has exactly 2 normal hands, 5 fingers each. NO extra limbs.\n"
                            "- No anatomical anomalies, no extra arms, no third hand, no weird deformations.\n"
                            "- Neutral color grading, clean white balance, no morphing or identity drift.\n"
                        )
                        if lang_code == "my":
                            CONDENSED_SEC1 += "- MALAYSIA MARKET: MUST use a Malay male presenter with modest clothing (clean long-sleeve shirt, dark trousers, neat appearance). NO female models.\n"
                        CONDENSED_SEC1 += "\n"
                        # Thay thế SECTION 1 gốc bằng phiên bản rút gọn
                        api_prompt = re.sub(
                            r'=== SECTION 1:.*?=== SECTION 2:',
                            CONDENSED_SEC1 + '=== SECTION 2:',
                            api_prompt, count=1, flags=re.DOTALL
                        )
                        # Bỏ [CONTENT FORMAT...] prefix nếu vẫn dài
                        if len(api_prompt) > 4900:
                            api_prompt = re.sub(r'^\[CONTENT FORMAT[^\]]*\]\s*', '', api_prompt)
                        # Bỏ [LAYOUT CONSTRAINT...] nếu vẫn dài
                        if len(api_prompt) > 4900:
                            api_prompt = re.sub(r'\[LAYOUT CONSTRAINT[^\]]*\]\s*', '', api_prompt)
                        # Cuối cùng mới cắt cứng nếu vẫn vượt
                        if len(api_prompt) > 4900:
                            api_prompt = api_prompt[:4900]
                        self._sv_log_msg(f"    ✂ Prompt rút gọn: {len(prompt)} → {len(api_prompt)} ký tự")
                    submit_res, job_or_err = submit_video_with_retry(api_prompt, shopapi_image_url, idempotency_key)

                    if submit_res == "stopped":
                        return "retry_soft"
                    elif submit_res == "insufficient_balance":
                        prod["_status"] = "noretry"
                        self._sv_update_line_status(idx, "error")
                        return ("fail", "Hết số dư ShopAPI")
                    elif submit_res != "ok":
                        return "retry_soft"

                    job_id = job_or_err.get("id", "")
                    self._sv_log_msg(f"  ⏳ Job {job_id[:16]}... đang chờ kết quả (nhịp 30s..60s)...")

                    # Quy tắc 4, 6: Polling
                    poll_res, poll_data = poll_job_until_done(job_id)

                    if poll_res == "retry_temporary":
                        # Lỗi máy chủ (retryable=True), xóa idempotency_key để lần tới sinh key MỚI
                        prod[key_field] = None
                        return "retry_soft"
                    elif poll_res == "fail_permanent":
                        # Lỗi dữ liệu/cs (retryable=False), dừng job này
                        prod["_status"] = "noretry"
                        status_to_send = "vi_pham_cs" if "vi phạm" in str(poll_data).lower() or "cs" in str(poll_data).lower() else "failed"
                        try:
                            self._sv_api_call("POST", "/api/thinaptm/complete-job", {
                                "itemId": item_id, "status": status_to_send, "tool": "thinaptm"
                            })
                        except: pass
                        self._sv_update_line_status(idx, "error")
                        return ("fail", str(poll_data))
                    elif poll_res != "succeeded":
                        return "retry_soft"

                    # Trích xuất video URL từ kết quả — hỗ trợ nhiều cấu trúc response
                    result = poll_data
                    outputs = result.get("outputs") or []
                    if not outputs:
                        single = result.get("output")
                        if single and hasattr(single, 'get') and single.get("url"):
                            outputs = [single]
                    # Fallback: thử các field phổ biến khác
                    if not outputs:
                        for field in ("result", "video", "data"):
                            val = result.get(field)
                            if val and hasattr(val, 'get') and val.get("url"):
                                outputs = [val]; break
                            elif isinstance(val, (list, tuple)) and val:
                                outputs = list(val); break
                    if not outputs:
                        # Debug: log cấu trúc dữ liệu trả về để tìm nguyên nhân
                        rd = result.to_dict() if hasattr(result, 'to_dict') else result
                        keys_info = list(rd.keys()) if isinstance(rd, dict) else type(rd).__name__
                        self._sv_log_msg(f"  ⚠ DEBUG poll_data keys: {keys_info}")
                        self._sv_log_msg(f"  ⚠ DEBUG poll_data: {str(rd)[:500]}")
                        # Tìm URL trực tiếp trong bất kỳ field nào
                        video_url = None
                        if isinstance(rd, dict):
                            for k, v in rd.items():
                                if isinstance(v, str) and ("http" in v) and (".mp4" in v or "video" in v or "download" in v):
                                    video_url = v
                                    self._sv_log_msg(f"  🔍 Tìm thấy URL trong field '{k}': {v[:80]}")
                                    break
                        if video_url:
                            outputs = [{"url": video_url}]
                        else:
                            self._sv_log_msg(f"  ❌ Job xong nhưng không có output")
                            return "retry_soft"
                    video_url = outputs[0].get("url", "") if hasattr(outputs[0], 'get') else str(outputs[0])
                    if not video_url:
                        self._sv_log_msg(f"  ❌ Job xong nhưng không có URL video")
                        return "retry_soft"

                    # Tải video
                    import urllib.request as urlreq
                    self._sv_log_msg(f"  📥 Tải video segment {seg_idx+1}...")
                    try:
                        urlreq.urlretrieve(video_url, clip_path)
                    except Exception as d_ex:
                        self._sv_log_msg(f"  ❌ Tải video lỗi ({d_ex})")
                        return "retry_soft"

                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 10 * 1024:
                        clip_paths.append(clip_path)
                        self._sv_log_msg(f"  ✅ Segment {seg_idx+1} OK ({os.path.getsize(clip_path)//1024}KB)")
                    else:
                        self._sv_log_msg(f"  ❌ Segment {seg_idx+1}: File quá nhỏ hoặc rỗng")
                        return "retry_soft"

                if not clip_paths:
                    return "retry_soft"

                # --- Ghép video (nếu nhiều segment) ---
                if len(clip_paths) > 1:
                    self._sv_log_msg(f"  🔗 Ghép {len(clip_paths)} segments...")
                    concat_path = os.path.join(temp_dir, f"sv_{item_id}_concat.mp4")
                    try:
                        SV.concat_videos(clip_paths, concat_path, log=lambda m: self._sv_log_msg(f"    {m}"))
                    except Exception as ex:
                        return ("fail", f"Ghép video lỗi: {ex}")
                else:
                    concat_path = clip_paths[0]

                # --- Đặt tên file output ---
                if naming_mode == "Theo Item ID":
                    out_name = f"{item_id}.mp4"
                elif naming_mode == "15 ký tự đầu prompt":
                    out_name = clean_filename(prompts[0][:15]) + ".mp4"
                else:
                    out_name = f"{idx+1:04d}.mp4"

                out_path = get_unique_out_path(out_dir, out_name, set())
                try:
                    import shutil
                    shutil.move(concat_path, out_path)
                    self._sv_log_msg(f"  ✅ Video: {os.path.basename(out_path)}")
                except Exception as ex:
                    return ("fail", f"Di chuyển video lỗi: {ex}")

                # --- Báo hoàn thành lên Server ---
                try:
                    self._sv_api_call("POST", "/api/thinaptm/complete-job", {
                        "itemId": item_id, "videoPath": out_path, "status": "completed", "tool": "thinaptm"
                    })
                except Exception as e:
                    self._sv_log_msg(f"  ⚠ Báo server lỗi: {e}")

                # --- Dọn file tạm ---
                try:
                    if del_img and img_path and os.path.exists(img_path):
                        try: os.remove(img_path)
                        except: pass
                    for cp in clip_paths:
                        if cp and os.path.exists(cp):
                            try: os.remove(cp)
                            except: pass
                    import glob
                    for f_tmp in glob.glob(os.path.join(temp_dir, f"sv_{item_id}_*")):
                        try: os.remove(f_tmp)
                        except: pass
                except Exception:
                    pass

                self._sv_last_video_time = time.time()
                prod["_status"] = "success"
                self._sv_update_line_status(idx, "success")
                with results_lock:
                    done_count[0] += 1
                    self._sv_video_done_count = done_count[0]
                    self.after(0, lambda c=done_count[0]: self._sv_video_done_lbl.configure(text=f"✅ {c} video"))
                    prog = (done_count[0] + error_count[0]) / total
                    self.after(0, lambda p=prog: self._sv_progress.set(p))
                    if hasattr(self, "_sv_done_timestamps"):
                        self._sv_done_timestamps.append(time.time())
                return ("success", out_path)

            # --- Worker loop ---
            def shopapi_worker():
                while not self._sv_stop_flag:
                    try:
                        prod = jobq.get(timeout=2)
                    except queue.Empty:
                        break
                    if prod.get("_status") in ("success", "noretry"):
                        continue
                    result = process_one_shopapi(prod)
                    if result == "retry_soft":
                        prod["_cycles"] += 1
                        if prod["_cycles"] < 3:
                            time.sleep(5)  # chờ 5s trước khi thử lại
                            jobq.put(prod)
                        else:
                            prod["_status"] = "noretry"
                            self._sv_update_line_status(prod["_idx"], "error")
                            with results_lock:
                                error_count[0] += 1
                                prog = (done_count[0] + error_count[0]) / total
                                self.after(0, lambda p=prog: self._sv_progress.set(p))
                            try: self._sv_api_call("POST", "/api/thinaptm/complete-job", {"itemId": prod.get("item_id"), "status": "failed", "tool": "thinaptm"})
                            except: pass
                    elif isinstance(result, tuple) and result[0] == "fail":
                        prod["_status"] = "noretry"
                        self._sv_update_line_status(prod["_idx"], "error")
                        with results_lock:
                            error_count[0] += 1
                            prog = (done_count[0] + error_count[0]) / total
                            self.after(0, lambda p=prog: self._sv_progress.set(p))
                        status_to_send = "vi_pham_cs" if len(result) > 1 and ("vi phạm" in result[1].lower() or "cs" in result[1].lower()) else "failed"
                        try:
                            self._sv_api_call("POST", "/api/thinaptm/complete-job", {
                                "itemId": prod.get("item_id"), "status": status_to_send, "tool": "thinaptm"
                            })
                        except: pass

            # Spawn workers
            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                futures = [executor.submit(shopapi_worker) for _ in range(n_workers)]
                for fut in futures:
                    fut.result()

            # --- Giải phóng SP chưa làm ---
            remaining = [p for p in products if p.get("_status") not in ("success", "noretry")]
            if remaining and self._sv_stop_flag:
                self._sv_log_msg(f"🔄 Trả {len(remaining)} SP chưa làm về Server...")
                try:
                    self._sv_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                    self._sv_log_msg(f"✅ Đã trả SP về pending.")
                except Exception as e:
                    self._sv_log_msg(f"⚠ Lỗi trả SP: {e}")

            self._sv_log_msg(f"\n{'='*50}")
            self._sv_log_msg(f"🏁 HOÀN TẤT (ShopAPI): ✅ {done_count[0]}/{total} thành công, ❌ {error_count[0]} lỗi")
            self.after(0, lambda: self._sv_status_lbl.configure(text=f"✅ {done_count[0]}/{total} xong (ShopAPI)"))
            self._sv_finish()
            self._sv_ping_server()

        threading.Thread(target=work, daemon=True).start()

    def _sv_start(self):
        """Bắt đầu tạo video từ danh sách SP đã nhận."""
        if SV is None:
            messagebox.showerror("Lỗi", "Module shopeevideo.py không tải được."); return
        if not self._sv_claimed_products:
            messagebox.showwarning("Thiếu SP", "Hãy bấm 📥 Nhận Lô Sản Phẩm trước."); return
        out_dir = self._sv_outdir.get().strip()
        if not out_dir:
            messagebox.showwarning("Thiếu", "Hãy chọn thư mục lưu video."); return

        is_shopapi_mode = "Server" in self._sv_source.get()

        if is_shopapi_mode:
            # === CHẾ ĐỘ SHOPAPI: Không cần tài khoản Google ===
            try:
                _shopapi_client = self._sv_init_shopapi_client()
            except Exception as e:
                messagebox.showerror("Lỗi ShopAPI", str(e)); return
            self._sv_start_shopapi(_shopapi_client)
            return

        # === CHẾ ĐỘ LOCAL: Cần tài khoản Google (hành vi cũ) ===
        enabled_accs = [a for a in self.accounts if a.get("enabled", True) and a.get("role") != "donor"]
        if not enabled_accs:
            messagebox.showerror("Lỗi", "Không có tài khoản nào được chọn.\nHãy tích chọn ở tab Tài khoản."); return

        self._sv_running = True
        self._sv_stop_flag = False
        self._sv_btn_start.configure(state="disabled")
        self._sv_btn_stop.configure(state="normal")
        self._sv_btn_claim.configure(state="disabled")
        self._sv_status_lbl.configure(text="⏳ Đang tạo video...")
        self._sv_last_video_time = time.time()

        products = list(self._sv_claimed_products)
        aspect_key = E.VID_ASPECTS.get(self._sv_aspect.get(), "VIDEO_ASPECT_RATIO_PORTRAIT")
        img_aspect = E.IMG_ASPECTS.get(self._sv_aspect.get(), "IMAGE_ASPECT_RATIO_PORTRAIT")
        scene_choice = self._sv_scene.get()
        duration_sec = SV.parse_duration(self._sv_duration.get())
        lang_val = self._sv_lang.get()
        lang_code = "vi" if "Việt" in lang_val else ("id" if "Indonesia" in lang_val else ("my" if "Malaysia" in lang_val else ("ph" if "Philippines" in lang_val else "en")))
        sv_model_key = E.VID_MODELS.get(self._sv_model.get(), "veo_3_1_t2v_lite_low_priority")
        remove_wm = self._sv_remove_wm.get()
        del_img = self._sv_del_img.get()
        ghep_anh = self._sv_ghep_anh.get()
        sv_use_laundering = self._sv_use_laundering.get()
        naming_mode = self._sv_naming.get()
        review_style = self._sv_review_style.get()
        client_id = self._sv_client_entry.get().strip()
        ai_mode = self._sv_ai_prompt.get()  # "Gemini" | "Groq" | "Template (mặc định)" | "📺 TVC Template"

        # Workers per account = upload_threads + 1 (1 luồng dư đang chờ poll/render trong khi các luồng khác upload)
        _sv_cached_wpa = None  # sẽ set riêng cho từng TK bên dưới
        _sv_cached_submit_max = 7.0

        self.settings["sv_remove_wm"] = remove_wm
        self.settings["sv_del_img"] = del_img
        self.settings["sv_ghep_anh"] = ghep_anh
        self.settings["sv_use_laundering"] = sv_use_laundering
        self.settings["sv_naming"] = naming_mode
        self.settings["sv_review_style"] = review_style
        self.settings["sv_ai_prompt"] = ai_mode
        self.settings["sv_submit_max"] = _sv_cached_submit_max

        # Lấy keys từ tab Tài khoản (dùng chung)
        sv_gemini_keys = [k.strip() for k in self.txt_gemini.get("1.0", "end").splitlines() if k.strip()]
        sv_groq_key = [k.strip() for k in self.txt_groq_keys.get("1.0", "end").splitlines() if k.strip()]

        # Cache proxy trên main thread trước khi vào worker thread
        try:
            _cached_px_lines = [l.strip() for l in self.txt_proxy.get("1.0", "end").splitlines() if l.strip()]
        except Exception:
            _cached_px_lines = []
        # Gắn mô tả giọng nói cố định vào engine (ưu tiên nhập tay, nếu trống → dùng preset theo ngôn ngữ)
        manual_voice = self.ent_voice_desc.get().strip()
        E.VOICE_DESC = manual_voice if manual_voice else E.get_voice_for_lang(lang_code)

        def work():
            accs = [a for a in self.accounts if a.get("enabled", True) and a.get("cookie") and a.get("role") != "donor"]
            if not accs:
                self._sv_log_msg("❌ Chưa chọn tài khoản nào (Vui lòng bật 'Dùng' trong tab Tài khoản).")
                self.after(0, lambda: self._sv_btn_start.configure(state="normal"))
                self.after(0, lambda: self._sv_btn_stop.configure(state="disabled"))
                self.after(0, lambda: self._sv_btn_claim.configure(state="normal"))
                self._sv_running = False
                return
            import base64 as b64mod
            total = len(products)
            # Dùng thư mục tạm cục bộ để render (tránh lag/treo khi ghi vào Google Drive ảo)
            temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_render")
            os.makedirs(temp_dir, exist_ok=True)
            os.makedirs(out_dir, exist_ok=True)

            self._start_recaptcha_farm()

            # Proxy (đã cache từ main thread)
            # Cloudflare WARP (1.1.1.1) — ưu tiên cao nhất, dùng riêng WARP
            if self._warp_enabled.get():
                warp_port = int(self._warp_port.get().strip() or 40000)
                warp_str = f"socks5://127.0.0.1:{warp_port}"
                n_accs = len(accs) + len([a for a in self.accounts if a.get("role") == "donor"])
                warp_lines = [f"{warp_str}#{i}" for i in range(n_accs)]
                self.proxy_pool.load(warp_lines)
                self._sv_log_msg(f"🌐 WARP 1.1.1.1 → tất cả {n_accs} TK dùng socks5://127.0.0.1:{warp_port}")
            elif self._auto_homeproxy.get() and self._homeproxy_token.get().strip():
                self._fetch_homeproxy()
            else:
                try:
                    if _cached_px_lines: self.proxy_pool.load(_cached_px_lines)
                except Exception: pass
            # 1. Khởi tạo Donor pool
            self._donor_states = []
            if sv_use_laundering:
                donor_accs = [a for a in self.accounts if a.get("role") == "donor" and a.get("cookie")]
                for da in donor_accs:
                    ds = AccountState(da, submit_max=_sv_cached_submit_max)
                    if self.proxy_pool.has_proxies():
                        self.proxy_pool.assign(ds.email)
                    ds.proxy = self.proxy_pool.get_dict(ds.email)
                    self._donor_states.append(ds)
                if self._donor_states:
                    self._sv_log_msg(f"🛡️ {len(self._donor_states)} donor bypass 429 sẵn sàng")

            # 2. Nạp trực tiếp tất cả tài khoản chính (Không check trước để tránh delay/treo)
            self._sv_log_msg(f"🔑 Chuẩn bị {len(accs)} tài khoản chính...")
            states = []
            for a in accs:
                st = AccountState(a, submit_max=_sv_cached_submit_max)
                # Workers = upload_threads + 1 (1 luồng dư poll/render trong khi upload tiếp)
                st.max_busy = getattr(st, "upload_threads", 2) + 1
                if self.proxy_pool.has_proxies():
                    px = self.proxy_pool.assign(st.email)
                    if px: st.proxy = self.proxy_pool.get_dict(st.email)
                states.append(st)
                px_info = st.proxy.get('https', 'Không proxy') if st.proxy else 'Không proxy'
                self._sv_log_msg(f"  ✅ {st.email[:20]} sẵn sàng | Upload: {st.upload_threads} | Workers: {st.max_busy} | Proxy: {px_info}")
            if not states:
                self._sv_log_msg("❌ Không tài khoản dùng được.")
                self._sv_finish()
                return

            self._sv_done_timestamps = collections.deque()
            self._sv_pool_states = states
            self.after(0, self._sv_update_pool)

            total_workers = sum(st.max_busy for st in states)
            self._sv_log_msg(f"🚀 {len(states)} TK — tổng {total_workers} luồng (upload+1 mỗi TK). Bắt đầu {total} SP.")

            # Shared Job Queue: 1 Hàng Đợi Chung cho tất cả TK (Mô hình veo3top tối ưu bứt tốc)
            jobq = queue.Queue()
            for idx, prod in enumerate(products):
                prod["_idx"] = idx
                prod["_cycles"] = 0
                jobq.put(prod)
            self._sv_log_msg(f"  📋 Hàng đợi chung: {jobq.qsize()} SP — tất cả {len(states)} TK tự động nạp chung")
            done_flag = [False]
            progress_count = [0]
            results_lock = threading.Lock()
            success_count = [0]
            self._sv_video_done_count = 0
            self.after(0, lambda: self._sv_video_done_lbl.configure(text=""))
            error_count = [0]
            n_upload_threads = max(4, sum(getattr(s, "upload_threads", 4) for s in states))
            upload_sem = threading.Semaphore(n_upload_threads)
            self._sv_log_msg(f"📤 Khởi tạo pool upload ({len(states)} TK — cài đặt luồng upload riêng biệt từng TK trong bảng Pool)")
            # Tự động tối ưu số luồng ghép video (FFmpeg) đồng thời dựa trên số nhân CPU của máy khách (14 luồng cho 56 nhân)
            merge_sem = threading.Semaphore(max(4, os.cpu_count() // 4))

            # 2h inactivity timeout checker
            def _inactivity_checker():
                while not done_flag[0] and not self._sv_stop_flag:
                    time.sleep(60)
                    if time.time() - self._sv_last_video_time > 7200:  # 2 giờ
                        self._sv_log_msg("⏰ 2 GIỜ không có video mới — tự động giải phóng SP kẹt...")
                        try:
                            remaining = [p for p in products if p.get("_status") not in ("success", "noretry")]
                            if remaining:
                                self._sv_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                                self._sv_log_msg(f"🔄 Đã trả {len(remaining)} SP chưa làm về pending.")
                        except Exception as e:
                            self._sv_log_msg(f"⚠ Lỗi auto-release: {e}")
                        self._sv_stop_flag = True
                        break
            threading.Thread(target=_inactivity_checker, daemon=True).start()

            # Stuck worker detector: phát hiện worker kẹt > 10 phút
            def _stuck_detector():
                worker_last_activity = {}  # email -> last_wins+fails
                while not done_flag[0] and not self._sv_stop_flag:
                    time.sleep(300)  # kiểm tra mỗi 5 phút
                    if done_flag[0] or self._sv_stop_flag:
                        break
                    for st in states:
                        total = st.wins + st.fails
                        prev = worker_last_activity.get(st.email, -1)
                        if prev == -1:
                            worker_last_activity[st.email] = total
                            continue
                        if total == prev and st.busy > 0 and not st.is_circuit_broken() and st.rest_remaining() <= 0:
                            # TK có busy > 0 nhưng không tạo thêm video nào trong 5 phút
                            self._sv_log_msg(f"  ⚠️ [Stuck?] {st.email[:16]}: busy={st.busy} nhưng 5 phút không có output → có thể kẹt")
                        worker_last_activity[st.email] = total
            threading.Thread(target=_stuck_detector, daemon=True).start()

            # --- Lớp 4: Proactive Cookie Refresh (Làm mới cookie chủ động mỗi 20 phút) ---
            def _proactive_cookie_refresher():
                while not done_flag[0] and not self._sv_stop_flag:
                    time.sleep(BEARER_TTL)  # 1200s = 20 phút
                    if done_flag[0] or self._sv_stop_flag:
                        break
                    self._sv_log_msg("🔄 [Proactive Refresh] Bắt đầu làm mới cookie tất cả tài khoản...")
                    for st in states:
                        if done_flag[0] or self._sv_stop_flag:
                            break
                        try:
                            if st.ensure_auth(force=True):
                                st.reset_circuit_breaker()
                                self._sv_log_msg(f"  🔄 {st.email[:16]}: Cookie OK ✅")
                            else:
                                self._sv_log_msg(f"  ⚠️ {st.email[:16]}: Cookie hết hạn → kích hoạt Instant HC")
                                self._trigger_instant_health_check(st.email)
                        except Exception as ex:
                            self._sv_log_msg(f"  ⚠️ {st.email[:16]}: Lỗi refresh: {ex}")
                        time.sleep(5)  # Xoay vòng mỗi TK cách nhau 5 giây
                    self._sv_log_msg("🔄 [Proactive Refresh] Hoàn tất.")
            threading.Thread(target=_proactive_cookie_refresher, daemon=True).start()

            def process_one(st, prod):
                idx = prod["_idx"]
                if self._sv_stop_flag:
                    return "retry_soft"

                if not st.ensure_auth():
                    # ensure_auth() đã tăng auth_fail_streak bên trong
                    if st.is_circuit_broken():
                        self._sv_log_msg(f"  🔌 Circuit Breaker: {st.email[:16]} ngắt mạch sau {st.auth_fail_streak} lỗi auth liên tiếp")
                        self._trigger_instant_health_check(st.email)
                    st.rest(AUTH_REST, "auth")
                    return "retry_soft"
                # ensure_auth() đã reset auth_fail_streak = 0 khi thành công
                bearer, project, cookie = st.bearer, st.project, st.cookie

                item_id = prod.get("item_id", "")
                product_name = prod.get("name", f"Product_{item_id}")
                image_url = prod.get("image_url", "")

                self._sv_update_line_status(idx, "running")
                self._sv_log_msg(f"\n{'='*50}")
                self._sv_log_msg(f"📦 [{idx+1}/{total}] {product_name[:50]} [{st.email[:16]}]")

                # --- Tải ảnh SP từ Shopee CDN ---
                img_ext = ".jpg"
                img_path = os.path.join(temp_dir, f"{item_id}{img_ext}")
                if not os.path.isfile(img_path):
                    if not image_url:
                        self._sv_log_msg(f"  ⚠ SP {item_id}: không có image_url → bỏ qua")
                        prod["_status"] = "noretry"
                        try: self._sv_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "failed", "tool": "thinaptm"})
                        except: pass
                        self._sv_update_line_status(idx, "error")
                        return ("fail", "Không có image_url")
                    self._sv_log_msg(f"  📥 Tải ảnh: {image_url[:60]}...")
                    if not self._sv_download_image(image_url, img_path):
                        prod["_status"] = "noretry"
                        try: self._sv_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "failed", "tool": "thinaptm"})
                        except: pass
                        self._sv_update_line_status(idx, "error")
                        return ("fail", "Tải ảnh thất bại")
                    self._sv_log_msg(f"  ✅ Ảnh đã tải: {os.path.basename(img_path)}")
                else:
                    self._sv_log_msg(f"  ⚡ Dùng ảnh đã tải: {os.path.basename(img_path)}")

                composite_path = img_path  # dùng ảnh SP làm reference trực tiếp

                # --- Sinh prompt video ---
                scene_name, scene_en = SV.pick_scene(scene_choice, lang=lang_code)
                prod["_use_fallback_prompts"] = True  # luôn dùng fallback prompts (không có ảnh người mẫu)

                # === CHẾ ĐỘ 8s: Prompt TVC cố định (1 segment duy nhất) ===
                if duration_sec == 8:
                    _tvc_lang_map = {
                        "en": {"nationality": "American", "language": "English"},
                        "vi": {"nationality": "Việt Nam", "language": "tiếng Việt"},
                        "id": {"nationality": "Indonesian", "language": "tiếng Indonesia"},
                        "my": {"nationality": "Malaysian", "language": "tiếng Malaysia (Bahasa Melayu)"},
                        "ph": {"nationality": "Filipino", "language": "Filipino"},
                    }
                    _tvc = _tvc_lang_map.get(lang_code, _tvc_lang_map["en"])
                    # Rút gọn tên SP (tối đa 80 ký tự)
                    short_name = product_name[:80].strip()
                    # Malaysia: 100% Mẫu Nam (Male Model) an toàn tuyệt đối
                    if lang_code == "my":
                        tvc_prompt = (
                            f'Create a product advertisement video (TVC) reviewing the product "{short_name}". '
                            f'A handsome Malay male model, modest clothing (clean long-sleeve shirt, dark trousers), about 25 years old, '
                            f'holds the product and introduces its key benefits. '
                            f'He states the benefits right away without any introduction. '
                            f'He speaks {_tvc["language"]}; no text is displayed in the video. '
                            f'The product is accurately sized. '
                            f'The product price is not mentioned in the video.'
                        )
                    else:
                        tvc_prompt = (
                            f'Create a product advertisement video (TVC) reviewing the product "{short_name}". '
                            f'A beautiful {_tvc["nationality"]} woman, about 20 years old, holds the product and introduces its key benefits. '
                            f'She states the benefits right away without any introduction. '
                            f'She speaks {_tvc["language"]}; no text is displayed in the video. '
                            f'The product is accurately sized. '
                            f'Her outfit is modest and appropriate, not revealing or offensive. '
                            f'The product price is not mentioned in the video.'
                        )
                    prompts = [tvc_prompt]
                    self._sv_log_msg(f"  📺 TVC 8s: 1 prompt cố định (Mẫu Nam - SP: {short_name[:40]}...)")
                    n_segments = 1
                else:
                    # === CHẾ ĐỘ 16s/24s: AI hoặc Template ===
                    n_segments_needed = len(SV.DURATION_MAP.get(duration_sec, [0, 1]))

                    prompts = None
                    if ai_mode == "Gemini":
                        prompts = self._sv_ai_gen_prompts(
                            product_name, scene_en, n_segments_needed,
                            duration_sec, lang_code, review_style,
                            mode="gemini", gemini_keys=sv_gemini_keys, groq_keys=sv_groq_key
                        )
                    elif ai_mode == "Groq":
                        prompts = self._sv_ai_gen_prompts(
                            product_name, scene_en, n_segments_needed,
                            duration_sec, lang_code, review_style,
                            mode="groq", gemini_keys=sv_gemini_keys, groq_keys=sv_groq_key
                        )

                    if prompts and len(prompts) >= n_segments_needed:
                        prompts = prompts[:n_segments_needed]
                        self._sv_log_msg(f"  🤖 AI sinh {len(prompts)} prompt ({ai_mode}, cảnh: {scene_name})")
                    else:
                        # Fallback về Prompt A + B nếu AI thất bại hoặc chọn Prompt A + B
                        prompts = SV.build_video_prompts_fallback(product_name, scene_en, duration_sec, lang=lang_code, review_style=review_style)
                        if ai_mode not in ("Prompt A + B", "Template (mặc định)"):
                            self._sv_log_msg(f"  ⚠ AI thất bại → dùng Prompt A + B fallback")
                        else:
                            self._sv_log_msg(f"  📝 Prompt A + B sinh {len(prompts)} prompt (cảnh: {scene_name})")
                    n_segments = len(prompts)

                # --- Upload ảnh SP với Semaphore riêng của từng tài khoản ---
                if not st.acquire_upload(lambda: self._sv_stop_flag):
                    return "retry_soft"
                try:
                    st.wait_upload_spacing(4.0)  # Giãn cách 4s giữa các lần upload của CÙNG 1 tài khoản (Rule #2)
                    with upload_sem:
                        if self._sv_stop_flag: return "retry_soft"
                        self._sv_log_msg(f"  📤 [{st.email[:12]}] Upload ảnh SP (luồng {st.upload_inflight}/{st.upload_threads})...")
                        try:
                            mid = E.upload_image(bearer, project, composite_path, proxy=st.proxy)
                        except Exception as ex:
                            self._sv_log_msg(f"  ❌ Upload lỗi: {ex}")
                            return "retry_soft"
                        if mid == "proxy_dead":

                            self._sv_handle_proxy_dead(st)
                            return "retry_soft"
                        if mid == "throttle":
                            # Upload bị 429 → xoay proxy + retry ngay với proxy mới
                            rotated = False
                            if self.proxy_pool and self.proxy_pool.has_proxies():
                                new_px, old_px = self.proxy_pool.rotate(st.email)
                                if new_px:
                                    st.proxy = self.proxy_pool.get_dict(st.email)
                                    self._sv_log_msg(f"  🔄 {st.email[:16]}: upload 429 → đổi proxy → retry ngay...")
                                    rotated = True
                                    # Retry ngay với proxy mới (không nghỉ)
                                    time.sleep(2)  # chờ 2s nhẹ rồi retry
                                    try:
                                        mid = E.upload_image(bearer, project, composite_path, proxy=st.proxy)
                                    except Exception:
                                        mid = None
                                    if mid and mid not in ("throttle", "forbidden", "unusual", "proxy_dead", "unauthorized"):
                                        st.on_upload_ok()
                                        self._sv_log_msg(f"  ✅ Retry proxy mới thành công! Media ID: {mid[:20]}...")
                                    else:
                                        self._sv_log_msg(f"  ⚠ Proxy mới cũng 429 → lỗi do tài khoản, nghỉ ngắn")
                                else:
                                    self._sv_log_msg(f"  ⏳ {st.email[:16]}: upload 429 — hết proxy trống")
                            # Nếu retry proxy mới thất bại hoặc không có proxy → thử donor
                            if not mid or mid in ("throttle", "forbidden", "unusual"):
                                bypassed_mid = None
                                if self._donor_states and sv_use_laundering:
                                    donors_copy = list(self._donor_states)
                                    random.shuffle(donors_copy)
                                    for donor_st in donors_copy:
                                        if donor_st.ensure_auth():
                                            self._sv_log_msg(f"  {st.email[:16]}: 429 image → bypass qua donor {donor_st.email[:16]}...")
                                            try:
                                                bypassed_mid = E.upload_image_via_donor(
                                                    donor_st.bearer, donor_st.project,
                                                    bearer, project,
                                                    composite_path,
                                                    proxy=donor_st.proxy,
                                                    main_proxy=st.proxy
                                                )
                                            except Exception as ex:
                                                self._sv_log_msg(f"    ⚠ Lỗi donor {donor_st.email[:16]}: {ex}")
                                                bypassed_mid = None
                                                continue
                                            if bypassed_mid == "quota_hard":
                                                donor_st.img_quota_exhausted = True
                                                bypassed_mid = None
                                                continue
                                            if bypassed_mid and bypassed_mid not in ("throttle", "forbidden", "unusual", "quota_hard"):
                                                self._sv_log_msg(f"    ✅ Bypass image thành công! [{donor_st.email[:16]}]")
                                                mid = bypassed_mid
                                                break
                            if not mid or mid in ("throttle", "forbidden", "unusual"):
                                rest_s = st.on_upload_throttle()
                                self._sv_log_msg(f"  😴 {st.email[:16]}: nghỉ {int(rest_s)}s (lần {st.upload_throttle_streak}) do upload 429")
                                return "retry_soft"
                        if not mid or mid in ("forbidden", "unusual", "throttle", "proxy_dead", "unauthorized"):
                            if mid == "forbidden":
                                self._sv_log_msg(f"  ❌ Upload lỗi: Tài khoản bị Google cấm tải ảnh (403 Forbidden)")
                            elif mid == "proxy_dead":
                                self._sv_log_msg(f"  ❌ Upload lỗi: Proxy mất kết nối (Proxy Dead)")
                            elif mid == "throttle":
                                self._sv_log_msg(f"  ⏳ Upload bị 429 Throttle (Google quá tải → chuyển làm mát)")
                            elif mid == "unauthorized":
                                self._sv_log_msg(f"  🔑 Upload lỗi: Cookie/Bearer hết hạn (401)")
                            else:
                                self._sv_log_msg(f"  ❌ Upload trả về rỗng (Google từ chối hoặc không cấp Media ID)")
                            return "retry_soft"
                        st.proxy_fail_streak = 0  # Upload OK → reset proxy streak
                        self._sv_log_msg(f"  ✅ Media ID: {mid[:20]}...")
                finally:
                    st.release_upload()

                # --- Tạo video từng segment (Tự động dùng lại segment đã hoàn thành trong temp) ---
                clip_paths = []
                for seg_idx, prompt in enumerate(prompts):
                    if self._sv_stop_flag: return "retry_soft"
                    clip_path = os.path.join(temp_dir, f"sv_{item_id}_seg{seg_idx}.mp4")
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 100 * 1024:
                        self._sv_log_msg(f"  ⚡ Segment {seg_idx+1}/{n_segments}: Đã hoàn thành sẵn ({os.path.getsize(clip_path)//1024}KB) → Dùng lại, không tạo lại!")
                        clip_paths.append(clip_path)
                        continue

                    self._sv_log_msg(f"  🎬 Segment {seg_idx+1}/{n_segments}...")

                    # AIMD gating & Lock per-account: chờ slot submit và giữ khóa độc quyền giãn cách 4-6s (Rule #2)
                    if not st.acquire_submit(lambda: self._sv_stop_flag):
                        return "retry_soft"
                    try:
                        with st.submit_guard(4.0, 6.0):
                            vid_seed = random.randint(1, 999999)
                            v_status, ops = E.submit_video(
                                bearer, project, prompt, seed=vid_seed, aspect=aspect_key,
                                model=sv_model_key, ref_media_id=mid, proxy=st.proxy
                            )
                    finally:
                        st.release_submit()

                    if v_status != "ok" or not ops:
                        err_str = str(v_status)
                        self._sv_log_msg(f"  ❌ Submit lỗi: {err_str[:60]}")
                        if v_status == "proxy_dead":
                            self._sv_handle_proxy_dead(st)
                            return "retry_soft"
                        if v_status == "throttle":
                            st.on_throttle()
                            if self.proxy_pool and self.proxy_pool.has_proxies():
                                new_px, old_px = self.proxy_pool.rotate(st.email)
                                if new_px:
                                    st.proxy = self.proxy_pool.get_dict(st.email)
                                    if st.rest_remaining() > 15:
                                        st.rest(15, "submit_throttle")
                                    self._sv_log_msg(f"    🔄 {st.email[:16]}: Submit 429 → Tự động xoay Proxy mới ({st.rest_remaining():.0f}s làm mát)...")
                            if st.rest_remaining() > 0:
                                if st.should_log_throttle():
                                    self._sv_log_msg(f"    ⏳ {st.email[:16]}: 429 — nghỉ {st.rest_remaining():.0f}s")
                                return "retry_soft"
                        if v_status == "quota_hard":
                            st.rest(QUOTA_HARD_REST, "quota")
                            self._sv_log_msg(f"    ⛔ {st.email[:16]} HẾT QUOTA → cách ly")
                            return "retry_soft"
                        if v_status == "auth":
                            st.auth_fail_streak += 1
                            if st.auth_fail_streak >= 2 and not st.is_circuit_broken():
                                st.trip_circuit_breaker()
                            if st.is_circuit_broken():
                                self._sv_log_msg(f"  🔌 Circuit Breaker: {st.email[:16]} ngắt mạch sau {st.auth_fail_streak} lỗi auth liên tiếp")
                                self._trigger_instant_health_check(st.email)
                            st.rest(AUTH_REST, "auth")
                            return "retry_soft"
                        if v_status == "vi phạm cs" or "PROMINENT_PEOPLE" in err_str or "AUDIO_FILTERED" in err_str:
                            prod["_status"] = "noretry"
                            try: self._sv_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "vi_pham_cs", "tool": "thinaptm"})
                            except: pass
                            self._sv_update_line_status(idx, "error")
                            return ("fail", "vi phạm cs")
                        return "retry_soft"

                    # AIMD success
                    st.on_submit_ok()
                    st.proxy_fail_streak = 0  # Submit OK → reset proxy streak

                    self._sv_log_msg(f"  ⏳ Polling segment {seg_idx+1}...")
                    kind, poll_result, _ = E.poll_video(bearer, ops, cookie=cookie, max_attempts=POLL_MAX, interval=8, proxy=st.proxy)
                    if kind != "done":
                        self._sv_log_msg(f"  ❌ Segment {seg_idx+1} render thất bại: {kind} — {poll_result}")
                        if kind == "proxy_dead":
                            self._sv_handle_proxy_dead(st)
                            return "retry_soft"
                        if kind == "failed" and E.is_policy_reason(poll_result, include_audio=True):
                            self._sv_log_msg(f"  ⚠️ Vi phạm chính sách ({poll_result}) → báo server, bỏ SP này")
                            prod["_status"] = "noretry"
                            try:
                                self._sv_api_call("POST", "/api/thinaptm/complete-job", {
                                    "itemId": item_id, "status": "vi_pham_cs", "tool": "thinaptm"
                                })
                            except Exception as ex:
                                self._sv_log_msg(f"  ⚠️ Lỗi báo vi_pham_cs lên server: {ex}")
                            self._sv_update_line_status(idx, "error")
                            return ("fail", "vi phạm cs")
                        return "retry_soft"

                    # Tải clip
                    clip_path = os.path.join(temp_dir, f"sv_{item_id}_seg{seg_idx}.mp4")
                    sz = E.download_video(poll_result, cookie, clip_path, proxy=st.proxy)
                    if sz == E.DL_PROXY_DEAD:
                        self._sv_handle_proxy_dead(st)
                        return "retry_soft"
                    if sz == E.DL_NET_FAIL:
                        self._sv_log_msg(f"  🌐 Lỗi mạng khi tải clip → trả SP về hàng đợi")
                        return "retry_soft"
                    if sz > 0 and os.path.exists(clip_path):
                        clip_paths.append(clip_path)
                        self._sv_log_msg(f"  ✅ Segment {seg_idx+1} OK ({sz//1024}KB)")
                    else:
                        self._sv_log_msg(f"  ❌ Segment {seg_idx+1}: Download thất bại (mã {sz})")
                        return "retry_soft"

                # --- Ghép video ---
                if len(clip_paths) > 1:
                    self._sv_log_msg(f"  🔗 Ghép {len(clip_paths)} segments...")
                    concat_path = os.path.join(temp_dir, f"sv_{item_id}_concat.mp4")
                    try:
                        SV.concat_videos(clip_paths, concat_path, log=lambda m: self._sv_log_msg(f"    {m}"))
                    except Exception as ex:
                        return ("fail", f"Ghép video lỗi: {ex}")
                else:
                    concat_path = clip_paths[0]

                # --- Xóa logo VEO ---
                if remove_wm:
                    self._sv_log_msg(f"  🧹 Xóa logo VEO...")
                    try:
                        SV.remove_veo_watermark(concat_path, log=lambda m: self._sv_log_msg(f"    {m}"))
                    except Exception:
                        pass

                # --- Ghép ảnh khi hoàn thành (chỉ áp dụng cho video 8s) ---
                ghep_anh_loi = False
                if ghep_anh and duration_sec == 8:
                    self._sv_log_msg("  ⏳ Đang chờ lượt ghép ảnh outro...")
                    with merge_sem:
                        self._sv_log_msg("  🎞 Bắt đầu ghép ảnh outro tạo video 12s...")
                        merged_path = os.path.join(temp_dir, f"sv_{item_id}_merged12s.mp4")
                        ok, err = self._run_ghep_anh_12s(concat_path, composite_path, merged_path)
                        if ok and os.path.exists(merged_path):
                            concat_path = merged_path
                            self._sv_log_msg("    ✅ Ghép ảnh outro 12s thành công!")
                        else:
                            self._sv_log_msg(f"    ⚠ Ghép ảnh lỗi: {err}. Giữ lại video gốc 8s và chuyển vào folder 'video8sloi' để tránh lãng phí credit.")
                            ghep_anh_loi = True

                # --- Đặt tên file output ---
                if naming_mode == "Theo Item ID":
                    out_name = f"{item_id}.mp4"
                elif naming_mode == "15 ký tự đầu prompt":
                    out_name = clean_filename(prompts[0][:15]) + ".mp4"
                else:
                    out_name = f"{idx+1:04d}.mp4"

                target_dir = os.path.join(out_dir, "video8sloi") if ghep_anh_loi else out_dir
                os.makedirs(target_dir, exist_ok=True)
                out_path = get_unique_out_path(target_dir, out_name, set())
                try:
                    import shutil
                    shutil.move(concat_path, out_path)
                    self._sv_log_msg(f"  ✅ Video: {os.path.basename(out_path)}")
                except Exception as ex:
                    return ("fail", f"Di chuyển video lỗi: {ex}")

                # --- Báo hoàn thành lên Server ---
                try:
                    self._sv_api_call("POST", "/api/thinaptm/complete-job", {
                        "itemId": item_id, "videoPath": out_path, "status": "completed", "tool": "thinaptm"
                    })
                except Exception as e:
                    self._sv_log_msg(f"  ⚠ Báo server lỗi: {e}")

                # --- Dọn dẹp triệt để file tạm (Auto-cleanup) ---
                try:
                    if composite_path and os.path.exists(composite_path):
                        try: os.remove(composite_path)
                        except: pass
                    if del_img and img_path and os.path.exists(img_path):
                        try: os.remove(img_path)
                        except: pass
                    for cp in clip_paths:
                        if cp and os.path.exists(cp):
                            try: os.remove(cp)
                            except: pass
                    import glob
                    for f in glob.glob(os.path.join(temp_dir, f"sv_{item_id}_*")):
                        try: os.remove(f)
                        except: pass
                except Exception:
                    pass

                # Update trạng thái
                self._sv_last_video_time = time.time()
                st.wins += 1
                prod["_status"] = "success"
                self._sv_update_line_status(idx, "success")
                with results_lock:
                    success_count[0] += 1
                    self._sv_video_done_count = success_count[0]
                    self.after(0, lambda c=success_count[0]: self._sv_video_done_lbl.configure(text=f"✅ {c} video"))
                    progress_count[0] += 1
                    self.after(0, lambda: self._sv_progress.set(progress_count[0] / total))
                    if hasattr(self, "_sv_done_timestamps"):
                        self._sv_done_timestamps.append(time.time())
                return ("success", out_path)

            # --- Worker thread ---
            def worker(st, jobq, initial_delay=0.0):
                if initial_delay > 0:
                    time.sleep(initial_delay + random.uniform(0.1, 0.4))
                while not done_flag[0] and not self._sv_stop_flag:
                    if not st.acc.get("enabled", True):
                        time.sleep(1); continue
                    w = st.rest_remaining()
                    if w > 0:
                        time.sleep(min(w, 2))
                        continue
                    # BẮT BUỘC: Kiểm tra auth hợp lệ trước khi nhận job, tránh việc TK chết cookie nuốt và làm trôi hàng đợi SP
                    if not st.ensure_auth():
                        time.sleep(2)
                        continue
                    with st.blk:
                        if st.busy >= st.get_current_max_busy():
                            time.sleep(0.5)
                            continue
                    try:
                        prod = jobq.get(timeout=2)
                    except queue.Empty:
                        break
                    if prod.get("_status") in ("success", "noretry"):
                        continue
                    st.busy_inc()
                    try:
                        result = process_one(st, prod)
                    finally:
                        st.busy_dec()
                    if result == "retry_soft":
                        prod["_cycles"] += 1
                        if prod["_cycles"] < 3:
                            jobq.put(prod)
                        else:
                            # --- Lớp 2: Trả lại job nếu lỗi do auth/cookie ---
                            is_auth_failure = st.is_circuit_broken() or st.rest_reason in ("auth", "circuit_breaker")
                            if is_auth_failure:
                                # Trả SP về pending trên Server thay vì đánh dấu failed
                                try:
                                    self._sv_api_call("POST", "/api/thinaptm/release-single-job", {"itemId": prod.get("item_id")})
                                    self._sv_log_msg(f"  🔄 Trả SP {prod.get('item_id')} về pending (TK đang chết cookie)")
                                except:
                                    pass
                                # Đưa lại vào queue nội bộ để thử lại sau khi TK hồi sinh
                                prod["_cycles"] = 0
                                jobq.put(prod)
                            else:
                                # Lỗi thật sự do sản phẩm → đánh dấu failed
                                prod["_status"] = "noretry"
                                self._sv_update_line_status(prod["_idx"], "error")
                                st.fails += 1
                                with results_lock:
                                    error_count[0] += 1
                                    progress_count[0] += 1
                                    self.after(0, lambda: self._sv_progress.set(progress_count[0] / total))
                                try: self._sv_api_call("POST", "/api/thinaptm/complete-job", {"itemId": prod.get("item_id"), "status": "failed", "tool": "thinaptm"})
                                except: pass
                    elif isinstance(result, tuple) and result[0] == "fail":
                        prod["_status"] = "noretry"
                        self._sv_update_line_status(prod["_idx"], "error")
                        st.fails += 1
                        with results_lock:
                            error_count[0] += 1
                            progress_count[0] += 1
                            self.after(0, lambda: self._sv_progress.set(progress_count[0] / total))
                        status_to_send = "vi_pham_cs" if len(result) > 1 and result[1] == "vi phạm cs" else "failed"
                        try:
                            self._sv_api_call("POST", "/api/thinaptm/complete-job", {
                                "itemId": prod.get("item_id"),
                                "status": status_to_send,
                                "tool": "thinaptm"
                            })
                        except:
                            pass

            # Spawn workers — Khởi động mềm & So le 0.8s giữa các TK để chống Thundering Herd (429 spam)
            total_workers = sum(st.max_busy for st in states)
            with ThreadPoolExecutor(max_workers=total_workers) as executor:
                futures = []
                for acc_idx, st in enumerate(states):
                    stagger_delay = acc_idx * 0.8
                    for _ in range(st.max_busy):
                        futures.append(executor.submit(worker, st, jobq, stagger_delay))
                for fut in futures:
                    fut.result()

            done_flag[0] = True

            # --- Giải phóng SP chưa làm ---
            remaining = [p for p in products if p.get("_status") not in ("success", "noretry")]
            if remaining and self._sv_stop_flag:
                self._sv_log_msg(f"🔄 Trả {len(remaining)} SP chưa làm về Server...")
                try:
                    self._sv_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                    self._sv_log_msg(f"✅ Đã trả SP về pending.")
                except Exception as e:
                    self._sv_log_msg(f"⚠ Lỗi trả SP: {e}")

            elapsed = time.time() - self._sv_last_video_time if self._sv_last_video_time else 0
            self._sv_log_msg(f"\n{'='*50}")
            self._sv_log_msg(f"🏁 HOÀN TẤT: ✅ {success_count[0]}/{total} thành công, ❌ {error_count[0]} lỗi")
            self.after(0, lambda: self._sv_status_lbl.configure(text=f"✅ {success_count[0]}/{total} xong"))
            self._sv_finish()
            # Refresh stats
            self._sv_ping_server()

        threading.Thread(target=work, daemon=True).start()

    def _sv_stop(self):
        """Dừng tạo video + tự động trả SP chưa làm về server."""
        self._sv_stop_flag = True
        self._sv_btn_stop.configure(state="disabled")
        self._sv_status_lbl.configure(text="⏹ Đang dừng...")
        self._sv_log_msg("⏹ Đã gửi lệnh dừng, chờ hoàn tất bước hiện tại...")

    def _trigger_instant_health_check(self, target_email=""):
        """Lớp 3: Kích hoạt Health Check khẩn cấp tức thì (Instant Health Check) khi phát hiện lỗi auth/cookie hết hạn."""
        if getattr(self, "_health_checking", False):
            self._sv_sync_cookies()
            return
        self._sv_log_msg(f"⚡ [Instant HC] Kích hoạt Health Check khẩn cấp{f' cho {target_email[:16]}' if target_email else ''}...")
        def _hc_bg():
            try:
                self._do_health_check()
            except Exception as ex:
                self._sv_log_msg(f"  ⚠️ [Instant HC] Lỗi: {ex}")
            finally:
                self._sv_sync_cookies()
        threading.Thread(target=_hc_bg, daemon=True).start()

    def _sv_sync_cookies(self):
        """Đồng bộ cookie mới từ self.accounts vào các AccountState của Server tab sau Health Check."""
        if not hasattr(self, '_sv_pool_states') or not self._sv_pool_states:
            return
        for st in self._sv_pool_states:
            for acc in self.accounts:
                acc_email = acc.get("email") or acc.get("id") or ""
                if acc_email == st.email:
                    new_cookie = acc.get("cookie", "")
                    if new_cookie and new_cookie != st.cookie:
                        st.cookie = new_cookie
                        st.reset_circuit_breaker()
                        st.clear_rest()
                        if st.ensure_auth(force=True):
                            self._sv_log_msg(f"  ✅ [Sync] {st.email[:16]}: Cookie đã được làm mới → sẵn sàng!")
                        else:
                            self._sv_log_msg(f"  ⚠️ [Sync] {st.email[:16]}: Cookie mới nhưng vẫn không auth được")
                    elif acc.get("status") == "ok" and st.is_circuit_broken():
                        st.reset_circuit_breaker()
                        st.clear_rest()
                        st.ensure_auth(force=True)
                    break

    def _sv_handle_proxy_dead(self, st):
        """Xử lý proxy chết giữa chừng: đánh dấu dead, gán proxy mới hoặc fallback không proxy."""
        st.proxy_fail_streak += 1
        if st.proxy_fail_streak < 2:
            return  # Chờ thêm 1 lần nữa để chắc chắn proxy thật sự chết
        old_px = self.proxy_pool.get_str(st.email) or "?"
        new_px = self.proxy_pool.mark_dead(st.email)
        if new_px:
            st.proxy = self.proxy_pool.get_dict(st.email)
            st.proxy_fail_streak = 0
            self._sv_log_msg(f"  🔄 Proxy chết ({old_px[:30]}) → đổi sang: {new_px[:30]}...")
        else:
            # Hết proxy trong pool → fallback qua Cloudflare WARP (1.1.1.1)
            warp_proxy = {"http": "socks5://127.0.0.1:40000", "https": "socks5://127.0.0.1:40000"}
            st.proxy = warp_proxy
            st.proxy_fail_streak = 0
            self._sv_log_msg(f"  🌐 Proxy chết ({old_px[:30]}) — hết proxy! Fallback qua WARP (socks5://127.0.0.1:40000)")

    # ============ TAB SHOPAPI (RIÊNG BIỆT) ============
    def _build_shopapi_tab(self):
        """Tab ShopAPI riêng — chạy độc lập song song với tab Server Local."""
        f = ctk.CTkFrame(self.content, fg_color=BG); self.frames["shopapi_tab"] = f

        # --- Header ---
        hdr = ctk.CTkFrame(f, fg_color="transparent"); hdr.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkLabel(hdr, text="⚡ ShopAPI — Tạo Video Nhanh", font=("", 18, "bold"), text_color=T1).pack(side="left")
        self._sa_status_lbl = ctk.CTkLabel(hdr, text="Chưa kết nối", font=("", 12), text_color=T2)
        self._sa_status_lbl.pack(side="right")

        # --- Kết nối Server (dùng chung settings) ---
        conn_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); conn_card.pack(fill="x", padx=12, pady=4)
        conn_row = ctk.CTkFrame(conn_card, fg_color="transparent"); conn_row.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(conn_row, text="Server URL:", font=("", 12)).pack(side="left")
        self._sa_url = ctk.CTkEntry(conn_row, width=260, font=("", 11))
        self._sa_url.pack(side="left", padx=4)
        self._sa_url.insert(0, self.settings.get("sv_server_url", "http://100.79.170.67:3000"))
        ctk.CTkLabel(conn_row, text="API Key:", font=("", 12)).pack(side="left", padx=(12, 0))
        self._sa_apikey = ctk.CTkEntry(conn_row, width=180, font=("", 11))
        self._sa_apikey.pack(side="left", padx=4)
        self._sa_apikey.insert(0, self.settings.get("sv_api_key", ""))
        ctk.CTkLabel(conn_row, text="Client ID:", font=("", 12)).pack(side="left", padx=(12, 0))
        self._sa_client_entry = ctk.CTkEntry(conn_row, width=160, font=("", 11))
        self._sa_client_entry.pack(side="left", padx=4)
        self._sa_client_entry.insert(0, self.settings.get("sv_client_id", "") + "_shopapi")
        # Cache for worker threads
        self._sa_cached_url = self._sa_url.get().strip()
        self._sa_cached_apikey = self._sa_apikey.get().strip()

        # --- ShopAPI Config ---
        api_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); api_card.pack(fill="x", padx=12, pady=4)
        api_row = ctk.CTkFrame(api_card, fg_color="transparent"); api_row.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(api_row, text="🔑 ShopAPI Key:", font=("", 12)).pack(side="left")
        self._sa_shopapi_key = ctk.CTkEntry(api_row, width=380, font=("", 11), show="*")
        self._sa_shopapi_key.pack(side="left", padx=4)
        self._sa_shopapi_key.insert(0, self.settings.get("sa_shopapi_key", self.settings.get("sv_shopapi_key", "")))
        ctk.CTkLabel(api_row, text="Thời lượng:", font=("", 12)).pack(side="left", padx=(12, 0))
        self._sa_shopapi_engine = ctk.CTkOptionMenu(api_row, values=["8s (Veo3 / 500đ)", "10s (Seedance / 1.000đ)"], width=190)
        self._sa_shopapi_engine.pack(side="left", padx=4)
        self._sa_shopapi_engine.set(self.settings.get("sa_shopapi_engine", self.settings.get("sv_shopapi_engine", "8s (Veo3 / 500đ)")))
        ctk.CTkLabel(api_row, text="Luồng:", font=("", 12)).pack(side="left", padx=(12, 0))
        self._sa_threads = ctk.CTkEntry(api_row, width=50, font=("", 11))
        self._sa_threads.pack(side="left", padx=4)
        self._sa_threads.insert(0, self.settings.get("sa_threads", "16"))

        # --- Cài đặt Video ---
        cfg = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); cfg.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(cfg, text="⚙ Cài đặt Video", font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(6, 2))
        row1 = ctk.CTkFrame(cfg, fg_color="transparent"); row1.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(row1, text="Tỉ lệ:", font=("", 12)).pack(side="left")
        self._sa_aspect = ctk.CTkOptionMenu(row1, values=["Dọc 9:16 (TikTok)", "Ngang 16:9"], width=160)
        self._sa_aspect.pack(side="left", padx=(4, 12))
        self._sa_aspect.set(self.settings.get("sa_aspect", "Dọc 9:16 (TikTok)"))
        ctk.CTkLabel(row1, text="Khung cảnh:", font=("", 12)).pack(side="left")
        scene_opts = SV.SCENE_OPTIONS if SV and hasattr(SV, 'SCENE_OPTIONS') else ["🎲 Random"]
        self._sa_scene = ctk.CTkOptionMenu(row1, values=scene_opts, width=180)
        self._sa_scene.pack(side="left", padx=(4, 12))
        self._sa_scene.set(self.settings.get("sa_scene", "🎲 Random"))
        ctk.CTkLabel(row1, text="Độ dài:", font=("", 12)).pack(side="left")
        dur_opts = ["8s", "16s", "24s"] if SV else ["16s"]
        self._sa_duration = ctk.CTkOptionMenu(row1, values=dur_opts, width=80)
        self._sa_duration.pack(side="left", padx=(4, 12))
        self._sa_duration.set(self.settings.get("sa_duration", "16s"))
        ctk.CTkLabel(row1, text="Ngôn ngữ:", font=("", 12)).pack(side="left")
        lang_opts = SV.LANG_OPTIONS if SV and hasattr(SV, 'LANG_OPTIONS') else ["Tiếng Philippines"]
        self._sa_lang = ctk.CTkOptionMenu(row1, values=lang_opts, width=160)
        self._sa_lang.pack(side="left", padx=4)
        self._sa_lang.set(self.settings.get("sa_lang", "Tiếng Philippines"))

        row2 = ctk.CTkFrame(cfg, fg_color="transparent"); row2.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(row2, text="Kiểu Review:", font=("", 12)).pack(side="left")
        style_opts = ["🎲 Random", "Review kho hàng", "Ngồi Review", "POV (Góc nhìn thứ nhất)", "UGC Authentic", "Unboxing", "Demo Công Dụng", "Review tự nhiên", "So Sánh/Đánh Giá"]
        self._sa_review_style = ctk.CTkOptionMenu(row2, values=style_opts, width=180)
        self._sa_review_style.pack(side="left", padx=(4, 12))
        self._sa_review_style.set(self.settings.get("sa_review_style", "🎲 Random"))
        ctk.CTkLabel(row2, text="AI Prompt:", font=("", 12)).pack(side="left")
        ai_opts = ["Template (mặc định)", "Prompt A + B", "Gemini", "Groq"]
        self._sa_ai_prompt = ctk.CTkOptionMenu(row2, values=ai_opts, width=180)
        self._sa_ai_prompt.pack(side="left", padx=(4, 12))
        self._sa_ai_prompt.set(self.settings.get("sa_ai_prompt", "Prompt A + B"))
        self._sa_del_img = ctk.BooleanVar(value=self.settings.get("sa_del_img", True))
        ctk.CTkCheckBox(row2, text="Xóa ảnh khi tạo xong", variable=self._sa_del_img, font=("", 11)).pack(side="left", padx=(12, 0))

        row3 = ctk.CTkFrame(cfg, fg_color="transparent"); row3.pack(fill="x", padx=12, pady=(2, 6))
        ctk.CTkLabel(row3, text="Đặt tên video:", font=("", 12)).pack(side="left")
        self._sa_naming = ctk.CTkOptionMenu(row3, values=["Theo Item ID", "15 ký tự đầu prompt", "Số thứ tự (001...)"], width=190)
        self._sa_naming.pack(side="left", padx=(4, 12))
        self._sa_naming.set(self.settings.get("sa_naming", "Theo Item ID"))
        ctk.CTkLabel(row3, text="Lưu Video:", font=("", 12)).pack(side="left")
        self._sa_outdir = ctk.CTkEntry(row3, width=400, font=("", 11))
        self._sa_outdir.pack(side="left", padx=4)
        self._sa_outdir.insert(0, self.settings.get("sa_out_dir", self.settings.get("sv_out_dir", "")))
        ctk.CTkButton(row3, text="Chọn", width=50, command=lambda: self._sa_pick_dir()).pack(side="left", padx=4)

        # --- Nhận Lô SP ---
        claim_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10); claim_card.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(claim_card, text="📦 Nhận Lô Sản Phẩm từ Database", font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(6, 2))
        claim_row = ctk.CTkFrame(claim_card, fg_color="transparent"); claim_row.pack(fill="x", padx=12, pady=(2, 6))
        ctk.CTkLabel(claim_row, text="Số lượng:", font=("", 12)).pack(side="left")
        self._sa_claim_limit = ctk.CTkEntry(claim_row, width=60, font=("", 11))
        self._sa_claim_limit.pack(side="left", padx=4)
        self._sa_claim_limit.insert(0, self.settings.get("sa_claim_limit", "20"))
        ctk.CTkLabel(claim_row, text="Ưu tiên:", font=("", 12)).pack(side="left", padx=(8, 0))
        self._sa_sort_by = ctk.CTkOptionMenu(claim_row, values=["Số bán cao nhất", "Hoa hồng cao nhất"], width=160)
        self._sa_sort_by.pack(side="left", padx=4)
        self._sa_sort_by.set(self.settings.get("sa_sort_by", "Số bán cao nhất"))
        ctk.CTkLabel(claim_row, text="Thị trường:", font=("", 12)).pack(side="left", padx=(8, 0))
        self._sa_market = ctk.CTkOptionMenu(claim_row, values=["PH", "VN", "ID", "TH", "MY", "SG", "TW"], width=70)
        self._sa_market.pack(side="left", padx=4)
        self._sa_market.set(self.settings.get("sa_market", "PH"))
        ctk.CTkLabel(claim_row, text="ItemID từ:", font=("", 12)).pack(side="left", padx=(8, 0))
        self._sa_min_item_id = ctk.CTkEntry(claim_row, width=110, font=("", 11))
        self._sa_min_item_id.pack(side="left", padx=4)
        self._sa_min_item_id.insert(0, self.settings.get("sa_min_item_id", "40000000000"))
        ctk.CTkLabel(claim_row, text="Hoa hồng từ:", font=("", 12)).pack(side="left", padx=(8, 0))
        self._sa_min_commission = ctk.CTkEntry(claim_row, width=50, font=("", 11))
        self._sa_min_commission.pack(side="left", padx=4)
        self._sa_min_commission.insert(0, self.settings.get("sa_min_commission", "1"))
        self._sa_btn_claim = ctk.CTkButton(claim_row, text="📥 Nhận SP", width=100, fg_color=AC, command=self._sa_claim_jobs)
        self._sa_btn_claim.pack(side="left", padx=(12, 4))
        self._sa_btn_release = ctk.CTkButton(claim_row, text="🔄 Giải phóng SP kẹt", width=150,
                                              fg_color="#E53935", hover_color="#C62828", command=self._sa_release_jobs)
        self._sa_btn_release.pack(side="left", padx=4)
        self._sa_btn_clear_violation = ctk.CTkButton(claim_row, text="🗑 Xóa Vi Phạm CS", width=150,
                                                      fg_color="#E57373", hover_color="#C62828", command=self._sa_clear_violations)
        self._sa_btn_clear_violation.pack(side="left", padx=4)

        # --- Bottom: Progress + Buttons ---
        bottom = ctk.CTkFrame(f, fg_color="transparent"); bottom.pack(side="bottom", fill="x", padx=12, pady=(4, 0))
        self._sa_progress = ctk.CTkProgressBar(bottom, width=400); self._sa_progress.pack(fill="x", pady=(0, 4)); self._sa_progress.set(0)
        btn_row = ctk.CTkFrame(bottom, fg_color="transparent"); btn_row.pack(fill="x")
        self._sa_btn_start = ctk.CTkButton(btn_row, text="▶ Bắt đầu tạo video", height=42, font=("", 15, "bold"),
                                            fg_color=AC, hover_color="#1565C0", command=self._sa_start)
        self._sa_btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._sa_btn_stop = ctk.CTkButton(btn_row, text="⏹ Dừng", height=42, width=80,
                                           fg_color="#E57373", hover_color="#C62828", state="disabled",
                                           command=self._sa_stop)
        self._sa_btn_stop.pack(side="left", padx=4)
        self._sa_btn_open = ctk.CTkButton(btn_row, text="📂 Mở thư mục", height=42, width=110,
                                           fg_color="#78909C", hover_color="#546E7A",
                                           command=lambda: os.startfile(self._sa_outdir.get().strip()) if self._sa_outdir.get().strip() else None)
        self._sa_btn_open.pack(side="left", padx=(4, 0))

        # --- Middle: Product List + Log ---
        middle = ctk.CTkFrame(f, fg_color="transparent"); middle.pack(fill="both", expand=True, padx=12, pady=(4, 0))

        # Left: Product list
        list_card = ctk.CTkFrame(middle, fg_color=CARD, corner_radius=10)
        list_card.pack(side="left", fill="both", expand=True, padx=(0, 4))
        list_hdr = ctk.CTkFrame(list_card, fg_color="transparent"); list_hdr.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(list_hdr, text="📋 Danh sách SP", font=("", 12, "bold"), text_color=T1).pack(side="left")
        self._sa_list_count = ctk.CTkLabel(list_hdr, text="0 SP", font=("", 11), text_color=T2)
        self._sa_list_count.pack(side="right")
        self._sa_video_done_lbl = ctk.CTkLabel(list_hdr, text="", font=("", 11, "bold"), text_color="#1B7D2C")
        self._sa_video_done_lbl.pack(side="right", padx=(0, 12))
        self._sa_products_text = ctk.CTkTextbox(list_card, font=("Consolas", 10))
        self._sa_products_text.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._sa_products_text.tag_config("sa_success", foreground="#1B7D2C")
        self._sa_products_text.tag_config("sa_error", foreground="#D32F2F")
        self._sa_products_text.tag_config("sa_running", foreground="#E65100")

        # Right: Log
        log_card = ctk.CTkFrame(middle, fg_color=CARD, corner_radius=10)
        log_card.pack(side="left", fill="both", expand=True, padx=(4, 0))
        log_hdr = ctk.CTkFrame(log_card, fg_color="transparent"); log_hdr.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(log_hdr, text="📝 Log", font=("", 12, "bold"), text_color=T1).pack(side="left")
        self._sa_log = ctk.CTkTextbox(log_card, font=("Consolas", 10), state="disabled")
        self._sa_log.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # --- State ---
        self._sa_claimed_products = []
        self._sa_running = False
        self._sa_stop_flag = False
        self._sa_video_done_count = 0

    def _sa_pick_dir(self):
        d = filedialog.askdirectory()
        if d:
            self._sa_outdir.delete(0, "end")
            self._sa_outdir.insert(0, d)

    def _sa_api_call(self, method, path, data=None):
        """Gọi API Server PostgreSQL cho tab ShopAPI."""
        url = self._sa_cached_url.rstrip("/") + path
        api_key = self._sa_cached_apikey
        headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
        if method == "GET":
            req = urllib.request.Request(url, headers=headers)
        else:
            body = json.dumps(data or {}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _sa_log_msg(self, msg):
        if not hasattr(self, '_sa_log_buffer'):
            self._sa_log_buffer = []
            self._sa_log_flush_scheduled = False
        self._sa_log_buffer.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if not self._sa_log_flush_scheduled:
            self._sa_log_flush_scheduled = True
            self.after(500, self._sa_flush_log)

    def _sa_flush_log(self):
        self._sa_log_flush_scheduled = False
        if not hasattr(self, '_sa_log_buffer') or not self._sa_log_buffer:
            return
        batch = self._sa_log_buffer[:]
        self._sa_log_buffer.clear()
        try:
            self._sa_log.configure(state="normal")
            self._sa_log.insert("end", "\n".join(batch) + "\n")
            line_count = int(self._sa_log.index("end-1c").split(".")[0])
            if line_count > 1000:
                self._sa_log.delete("1.0", f"{line_count - 800}.0")
            self._sa_log.see("end")
            self._sa_log.configure(state="disabled")
        except Exception:
            pass

    def _sa_download_image(self, image_url, save_path):
        try:
            req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                with open(save_path, "wb") as wf:
                    wf.write(resp.read())
            return True
        except Exception as e:
            self._sa_log_msg(f"⚠ Tải ảnh lỗi: {e}")
            return False

    def _sa_update_line_status(self, line_idx, status):
        prefix_map = {"success": "✅ ", "error": "❌ ", "running": "⏳ "}
        tag_map = {"success": "sa_success", "error": "sa_error", "running": "sa_running"}
        pfx = prefix_map.get(status, "")
        tag = tag_map.get(status)
        def _do():
            try:
                tk_line = line_idx + 1
                content = self._sa_products_text.get(f"{tk_line}.0", f"{tk_line}.end")
                for p in ("✅ ", "❌ ", "⏳ "):
                    if content.startswith(p):
                        content = content[len(p):]; break
                self._sa_products_text.delete(f"{tk_line}.0", f"{tk_line}.end")
                self._sa_products_text.insert(f"{tk_line}.0", pfx + content)
                for t in ("sa_success", "sa_error", "sa_running"):
                    self._sa_products_text.tag_remove(t, f"{tk_line}.0", f"{tk_line}.end")
                if tag:
                    self._sa_products_text.tag_add(tag, f"{tk_line}.0", f"{tk_line}.end")
            except Exception:
                pass
        self.after(0, _do)

    def _sa_claim_jobs(self):
        """Nhận lô SP cho tab ShopAPI."""
        import re as _re
        # Cache URL/API key
        self._sa_cached_url = self._sa_url.get().strip()
        if self._sa_cached_url and not (self._sa_cached_url.startswith("http://") or self._sa_cached_url.startswith("https://")):
            self._sa_cached_url = "http://" + self._sa_cached_url
        self._sa_cached_apikey = self._sa_apikey.get().strip()

        limit = int(self._sa_claim_limit.get().strip() or "20")
        sort_map = {"Số bán cao nhất": "sold", "Hoa hồng cao nhất": "commission"}
        sort_by = sort_map.get(self._sa_sort_by.get(), "sold")
        market = self._sa_market.get()
        client_id = self._sa_client_entry.get().strip()
        min_item_id_str = self._sa_min_item_id.get().strip()
        min_comm_str = self._sa_min_commission.get().strip()
        try: min_item_id = int(_re.sub(r'\D', '', min_item_id_str) or "40000000000")
        except: min_item_id = 40000000000
        try: min_commission = float(min_comm_str.replace("%", "").strip() or "1.0")
        except: min_commission = 1.0

        self._sa_btn_claim.configure(state="disabled", text="⏳...")
        self._sa_log_msg(f"📥 Đang xin {limit} SP từ Server (market={market})...")

        def _do():
            try:
                result = self._sa_api_call("POST", "/api/thinaptm/claim-jobs", {
                    "market": market, "clientId": client_id, "limit": limit, "sortBy": sort_by,
                    "min_item_id": min_item_id, "min_commission": min_commission,
                    "minItemId": min_item_id, "minCommission": min_commission
                })
                raw = result.get("products", [])
                products = []
                for p in raw:
                    try: iid = int(_re.sub(r'\D', '', str(p.get("item_id", 0))))
                    except: iid = 0
                    try:
                        rc = float(p.get("commission_rate", 0) or 0)
                        comm = rc * 100.0 if 0 < rc <= 1.0 else rc
                        p["commission_rate"] = comm
                    except: comm = 0.0
                    if (min_item_id > 0 and iid < min_item_id) or comm < min_commission:
                        continue
                    products.append(p)
                self._sa_claimed_products = products
                count = len(products)
                def _ui():
                    self._sa_products_text.configure(state="normal")
                    self._sa_products_text.delete("1.0", "end")
                    sym = "₫" if market == "VN" else ("Rp" if market == "ID" else "₱")
                    for i, p in enumerate(products):
                        name = (p.get('name', '') or '')[:55]
                        iid = p.get('item_id', '?')
                        try: pv = float(p.get('price', 0) or 0)
                        except: pv = 0.0
                        sold = p.get('sold', 0)
                        comm = float(p.get('commission_rate', 0) or 0)
                        self._sa_products_text.insert("end", f"⏳ [{i+1}] {iid} | {name} | {sym}{pv:,.0f} | Sold:{sold} | Comm:{comm:.1f}%\n")
                    self._sa_list_count.configure(text=f"{count} SP")
                    self._sa_btn_claim.configure(state="normal", text="📥 Nhận SP")
                self.after(0, _ui)
                self._sa_log_msg(f"✅ Đã nhận {count} SP! Bấm ▶ để tạo video.")
            except Exception as e:
                self._sa_log_msg(f"❌ Lỗi nhận SP: {e}")
                self.after(0, lambda: self._sa_btn_claim.configure(state="normal", text="📥 Nhận SP"))
        threading.Thread(target=_do, daemon=True).start()

    def _sa_release_jobs(self):
        """Giải phóng SP kẹt (processing) cho tab ShopAPI và làm sạch danh sách SP."""
        client_id = self._sa_client_entry.get().strip()
        if not client_id:
            messagebox.showwarning("Thiếu", "Chưa có Client ID."); return
        self._sa_cached_url = self._sa_url.get().strip()
        if self._sa_cached_url and not (self._sa_cached_url.startswith("http://") or self._sa_cached_url.startswith("https://")):
            self._sa_cached_url = "http://" + self._sa_cached_url
        self._sa_cached_apikey = self._sa_apikey.get().strip()
        self._sa_log_msg(f"🔄 Đang giải phóng SP kẹt của client '{client_id}'...")

        def _do():
            try:
                # 1. Giải phóng SP của client này
                r1 = self._sa_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                released1 = r1.get("released", 0) if isinstance(r1, dict) else 0
                # 2. Giải phóng SP kẹt > 2h của tất cả client
                try:
                    r2 = self._sa_api_call("POST", "/api/thinaptm/auto-release-stuck", {"hours": 2})
                    released2 = r2.get("released", 0) if isinstance(r2, dict) else 0
                except Exception:
                    released2 = 0
                total_released = released1 + released2
                self._sa_log_msg(f"✅ Đã giải phóng {total_released} SP kẹt (Client: {released1}, Kẹt >2h: {released2})")

                # Xóa danh sách SP cục bộ và xóa sạch giao diện textbox
                self._sa_claimed_products = []
                self._sa_video_done_count = 0

                def _clear_ui():
                    self._sa_products_text.configure(state="normal")
                    self._sa_products_text.delete("1.0", "end")
                    self._sa_list_count.configure(text="0 SP")
                    self._sa_video_done_lbl.configure(text="")
                    self._sa_progress.set(0)
                    self._sa_btn_claim.configure(state="normal", text="📥 Nhận SP")
                self.after(0, _clear_ui)
            except Exception as e:
                self._sa_log_msg(f"❌ Lỗi giải phóng: {e}")
        threading.Thread(target=_do, daemon=True).start()

    def _sa_clear_violations(self):
        """Xóa các SP vi phạm chính sách khỏi danh sách."""
        before = len(self._sa_claimed_products)
        self._sa_claimed_products = [p for p in self._sa_claimed_products if p.get("_status") != "vi phạm cs"]
        after = len(self._sa_claimed_products)
        removed = before - after
        if removed > 0:
            self._sa_log_msg(f"🗑 Đã xóa {removed} SP vi phạm CS.")
            # Redraw
            self._sa_products_text.configure(state="normal")
            self._sa_products_text.delete("1.0", "end")
            market = self._sa_market.get()
            sym = "₫" if market == "VN" else ("Rp" if market == "ID" else "₱")
            for i, p in enumerate(self._sa_claimed_products):
                name = (p.get('name', '') or '')[:55]
                iid = p.get('item_id', '?')
                st = p.get("_status", "")
                pfx = "✅ " if st == "success" else ("❌ " if st in ("noretry", "error") else "⏳ ")
                try: pv = float(p.get('price', 0) or 0)
                except: pv = 0.0
                sold = p.get('sold', 0)
                comm = float(p.get('commission_rate', 0) or 0)
                self._sa_products_text.insert("end", f"{pfx}[{i+1}] {iid} | {name} | {sym}{pv:,.0f} | Sold:{sold} | Comm:{comm:.1f}%\n")
            self._sa_list_count.configure(text=f"{after} SP")
        else:
            self._sa_log_msg("ℹ Không có SP vi phạm CS nào để xóa.")

    def _sa_stop(self):
        self._sa_stop_flag = True
        self._sa_log_msg("⏹ Đang dừng...")

    def _sa_finish(self):
        self._sa_running = False
        self.after(0, lambda: self._sa_btn_start.configure(state="normal"))
        self.after(0, lambda: self._sa_btn_stop.configure(state="disabled"))
        self.after(0, lambda: self._sa_btn_claim.configure(state="normal", text="📥 Nhận SP"))

    def _sa_start(self):
        """Bắt đầu tạo video qua ShopAPI (tab riêng)."""
        if SV is None:
            messagebox.showerror("Lỗi", "Module shopeevideo.py không tải được."); return
        if not self._sa_claimed_products:
            messagebox.showwarning("Thiếu SP", "Hãy bấm 📥 Nhận SP trước."); return
        out_dir = self._sa_outdir.get().strip()
        if not out_dir:
            messagebox.showwarning("Thiếu", "Hãy chọn thư mục lưu video."); return
        # Init ShopAPI client
        try:
            import sys
            sdk_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_sdk")
            if sdk_dir not in sys.path:
                sys.path.insert(0, sdk_dir)
            from shopapi import ShopAPI
            api_key = self._sa_shopapi_key.get().strip()
            if not api_key:
                messagebox.showerror("Lỗi", "Chưa nhập ShopAPI API Key."); return
            shopapi_client = ShopAPI(api_key=api_key)
        except Exception as e:
            messagebox.showerror("Lỗi ShopAPI", str(e)); return
        # Cache connection
        self._sa_cached_url = self._sa_url.get().strip()
        if self._sa_cached_url and not (self._sa_cached_url.startswith("http://") or self._sa_cached_url.startswith("https://")):
            self._sa_cached_url = "http://" + self._sa_cached_url
        self._sa_cached_apikey = self._sa_apikey.get().strip()
        self._sa_start_shopapi(shopapi_client)

    def _sa_start_shopapi(self, shopapi_client):
        """Worker chính cho tab ShopAPI riêng — clone từ _sv_start_shopapi, trỏ widget _sa_*."""
        out_dir = self._sa_outdir.get().strip()
        products = list(self._sa_claimed_products)
        scene_choice = self._sa_scene.get()
        naming_mode = self._sa_naming.get()
        client_id = self._sa_client_entry.get().strip()
        ai_mode = self._sa_ai_prompt.get()
        review_style = self._sa_review_style.get()
        del_img = self._sa_del_img.get()

        engine_raw = self._sa_shopapi_engine.get()
        shopapi_duration = 10 if "10s" in engine_raw or "seedance" in engine_raw.lower() else 8
        duration_sec = SV.parse_duration(self._sa_duration.get()) if SV else 16
        n_segments_needed = len(SV.DURATION_MAP.get(duration_sec, [0])) if SV else 1

        aspect_local = self._sa_aspect.get()
        shopapi_aspect = "16:9" if "16:9" in aspect_local else "9:16"

        lang_val = self._sa_lang.get()
        lang_code = "vi" if "Việt" in lang_val else ("id" if "Indonesia" in lang_val else ("my" if "Malaysia" in lang_val else ("ph" if "Philippines" in lang_val else "en")))

        manual_voice = self.ent_voice_desc.get().strip() if hasattr(self, 'ent_voice_desc') else ""
        E.VOICE_DESC = manual_voice if manual_voice else E.get_voice_for_lang(lang_code)

        sv_gemini_keys = [k.strip() for k in self.txt_gemini.get("1.0", "end").splitlines() if k.strip()] if hasattr(self, 'txt_gemini') else []
        sv_groq_key = [k.strip() for k in self.txt_groq.get("1.0", "end").splitlines() if k.strip()] if hasattr(self, 'txt_groq') else []

        # UI states
        self._sa_running = True
        self._sa_stop_flag = False
        self._sa_btn_start.configure(state="disabled")
        self._sa_btn_stop.configure(state="normal")
        self._sa_btn_claim.configure(state="disabled")
        self._sa_status_lbl.configure(text="⏳ Đang tạo video...")

        def work():
            total = len(products)
            temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_render")
            os.makedirs(temp_dir, exist_ok=True)
            os.makedirs(out_dir, exist_ok=True)

            seg_info = f"{n_segments_needed} segment × 8s" if n_segments_needed > 1 else f"{shopapi_duration}s"
            self._sa_log_msg(f"🌐 ShopAPI — Engine: auto | Video: {duration_sec}s ({seg_info}) | Tỉ lệ: {shopapi_aspect}")

            # Capacity
            def _get_cap():
                try:
                    cap = shopapi_client.request("GET", "/v1/capacity")
                    if isinstance(cap, dict):
                        vc = cap.get("video")
                        if isinstance(vc, dict):
                            a = vc.get("available") or (vc.get("capacity", 0) - vc.get("running", 0))
                            if a and a > 0: return max(1, int(a))
                except: pass
                try:
                    me = shopapi_client.request("GET", "/v1/me")
                    lim = me.get("limits", {})
                    d = (lim.get("concurrent_jobs_detail") or {}).get("video") or {}
                    c = int(d.get("capacity") or 0); r = int(d.get("running") or 0)
                    if c > 0: return max(1, c - r)
                    return max(1, int((lim.get("concurrent_jobs") or {}).get("video") or 4))
                except: return 4

            dyn_cap = _get_cap()
            try:
                user_threads = int(self._sa_threads.get().strip() or "16")
            except:
                user_threads = 16
            n_workers = max(1, min(user_threads, dyn_cap, total))
            self._sa_log_msg(f"🏭 Sức chứa API: {dyn_cap} | Cài đặt: {user_threads} → {n_workers} luồng")
            self._sa_log_msg(f"📋 {total} SP — bắt đầu tạo video...")

            done_count = [0]
            self._sa_video_done_count = 0
            self.after(0, lambda: self._sa_video_done_lbl.configure(text=""))
            error_count = [0]
            results_lock = threading.Lock()
            jobq = queue.Queue()
            for idx, prod in enumerate(products):
                prod["_idx"] = idx; prod["_cycles"] = 0
                jobq.put(prod)

            def submit_video_with_retry(prompt, image_url, idempotency_key):
                for attempt in range(8):
                    if self._sa_stop_flag: return "stopped", None
                    try:
                        job = shopapi_client.videos.create(
                            prompt=prompt, engine="auto", duration=shopapi_duration,
                            aspect_ratio=shopapi_aspect, image_url=image_url,
                            idempotency_key=idempotency_key,
                        )
                        return "ok", job
                    except Exception as ex:
                        ex_str = str(ex).lower()
                        if "insufficient" in ex_str or "balance" in ex_str:
                            self._sa_log_msg(f"  💰 Hết số dư ShopAPI!")
                            return "insufficient_balance", str(ex)
                        if "429" in ex_str or "rate" in ex_str or "503" in ex_str:
                            wait = min(30 * (attempt + 1), 120)
                            self._sa_log_msg(f"  ⏳ Rate limit → chờ {wait}s (lần {attempt+1})")
                            time.sleep(wait); continue
                        if attempt < 7:
                            time.sleep(5); continue
                        self._sa_log_msg(f"  ❌ Submit thất bại sau 8 lần: {ex}")
                        return "error", str(ex)
                return "error", "Max retries"

            def poll_job_until_done(job_id):
                poll_interval = 6.0
                max_timeout = 300  # 5 phút tối đa
                start = time.time()
                while time.time() - start < max_timeout:
                    if self._sa_stop_flag: return "stopped", None
                    # Thêm random jitter 0.5s - 2.5s để phân tán request, tránh 50 luồng dồn vào cùng 1 mini-giây
                    import random as _rnd_poll
                    time.sleep(poll_interval + _rnd_poll.uniform(0.5, 2.5))
                    try:
                        data = shopapi_client.jobs.retrieve(job_id)
                        status = (data.get("status") or "").lower()
                    except Exception as e:
                        poll_interval = min(15, poll_interval + 2); continue
                    if status == "succeeded":
                        return "succeeded", data
                    elif status in ("failed", "cancelled"):
                        err_msg = ""
                        err_obj = data.get("error")
                        if err_obj and hasattr(err_obj, 'get'):
                            err_msg = err_obj.get("message", str(err_obj))
                        elif err_obj:
                            err_msg = str(err_obj)
                        is_retryable = False
                        if err_obj and hasattr(err_obj, 'get'):
                            is_retryable = bool(err_obj.get("retryable"))
                        refunded = 0
                        ref = data.get("refund")
                        if ref and hasattr(ref, 'get'):
                            refunded = ref.get("amount", 0)
                        refund_str = f" (đã hoàn {refunded} µVND)" if refunded else ""
                        if is_retryable:
                            self._sa_log_msg(f"  🔄 Lỗi tạm [retryable]{refund_str}: {err_msg[:60]}")
                            return "retry_temporary", err_msg
                        else:
                            self._sa_log_msg(f"  ❌ Lỗi [retryable=False]: {err_msg[:80]}")
                            return "fail_permanent", err_msg
                    else:
                        # pending/processing — tăng nhẹ interval, tối đa 15s
                        poll_interval = min(15.0, poll_interval + 1.5)
                # Timeout
                elapsed = int(time.time() - start)
                self._sa_log_msg(f"  ⏰ Timeout {elapsed}s cho job {job_id[:16]}... bỏ qua")
                return "retry_temporary", f"Timeout {elapsed}s"

            def process_one(prod):
                idx = prod["_idx"]
                if self._sa_stop_flag: return "retry_soft"
                item_id = prod.get("item_id", "")
                product_name = prod.get("name", f"Product_{item_id}")
                image_url = prod.get("image_url", "")

                self._sa_update_line_status(idx, "running")
                self._sa_log_msg(f"\n{'='*50}")
                self._sa_log_msg(f"📦 [{idx+1}/{total}] {product_name[:50]}")

                # Download image
                img_path = os.path.join(temp_dir, f"{item_id}.jpg")
                if not os.path.isfile(img_path):
                    if not image_url:
                        self._sa_log_msg(f"  ⚠ Không có image_url")
                        prod["_status"] = "noretry"
                        try: self._sa_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "failed", "tool": "thinaptm"})
                        except: pass
                        self._sa_update_line_status(idx, "error")
                        return ("fail", "No image_url")
                    self._sa_log_msg(f"  📥 Tải ảnh: {image_url[:60]}...")
                    if not self._sa_download_image(image_url, img_path):
                        prod["_status"] = "noretry"
                        try: self._sa_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "failed", "tool": "thinaptm"})
                        except: pass
                        self._sa_update_line_status(idx, "error")
                        return ("fail", "Download failed")
                    self._sa_log_msg(f"  ✅ Ảnh: {os.path.basename(img_path)}")

                # Generate prompts (same logic as _sv)
                scene_name, scene_en = SV.pick_scene(scene_choice, lang=lang_code)
                if n_segments_needed == 1:
                    _tvc_lang_map = {"en": {"nationality": "American", "language": "English"}, "vi": {"nationality": "Việt Nam", "language": "tiếng Việt"}, "id": {"nationality": "Indonesian", "language": "tiếng Indonesia"}, "my": {"nationality": "Malaysian", "language": "tiếng Malaysia"}, "ph": {"nationality": "Filipino", "language": "Filipino"}}
                    _tvc = _tvc_lang_map.get(lang_code, _tvc_lang_map["en"])
                    short_name = product_name[:80].strip()
                    # Malaysia: 100% Mẫu Nam (Male Model) an toàn tuyệt đối
                    if lang_code == "my":
                        prompts = [f'Create a product advertisement video (TVC) reviewing the product "{short_name}". A handsome Malay male model, modest clothing (clean long-sleeve shirt, dark trousers), about 25 years old, holds the product and introduces its key benefits. He states the benefits right away without any introduction. He speaks {_tvc["language"]}; no text is displayed in the video. The product is accurately sized. The product price is not mentioned in the video.']
                    else:
                        prompts = [f'Create a product advertisement video (TVC) reviewing the product "{short_name}". A beautiful {_tvc["nationality"]} woman, about 20 years old, holds the product and introduces its key benefits. She states the benefits right away without any introduction. She speaks {_tvc["language"]}; no text is displayed in the video. The product is accurately sized. Her outfit is modest and appropriate, not revealing or offensive. The product price is not mentioned in the video.']
                    self._sa_log_msg(f"  📺 TVC 8s: 1 prompt (Mẫu Nam)")
                else:
                    prompts = None
                    if ai_mode == "Gemini":
                        prompts = self._sv_ai_gen_prompts(product_name, scene_en, n_segments_needed, duration_sec, lang_code, review_style, mode="gemini", gemini_keys=sv_gemini_keys, groq_keys=sv_groq_key)
                    elif ai_mode == "Groq":
                        prompts = self._sv_ai_gen_prompts(product_name, scene_en, n_segments_needed, duration_sec, lang_code, review_style, mode="groq", gemini_keys=sv_gemini_keys, groq_keys=sv_groq_key)
                    if prompts and len(prompts) >= n_segments_needed:
                        prompts = prompts[:n_segments_needed]
                        self._sa_log_msg(f"  🤖 AI sinh {len(prompts)} prompt ({ai_mode})")
                    else:
                        prompts = SV.build_video_prompts_fallback(product_name, scene_en, duration_sec, lang=lang_code, review_style=review_style)
                        self._sa_log_msg(f"  📝 Prompt A + B sinh {len(prompts)} prompt")
                n_segments = len(prompts)

                # Image URL for ShopAPI
                if image_url and image_url.lower().startswith("https://") and len(image_url) <= 2000:
                    shopapi_image_url = image_url
                    self._sa_log_msg(f"  🔗 Dùng link ảnh gốc: {shopapi_image_url[:60]}...")
                else:
                    self._sa_log_msg(f"  📤 Upload ảnh...")
                    try:
                        shopapi_image_url = shopapi_client.uploads.upload_file(img_path)
                        if not shopapi_image_url:
                            return "retry_soft"
                        self._sa_log_msg(f"  ✅ Upload OK: {str(shopapi_image_url)[:60]}")
                    except Exception as ex:
                        self._sa_log_msg(f"  ❌ Upload lỗi: {ex}")
                        return "retry_soft"

                # Create segments
                clip_paths = []
                for seg_idx, prompt in enumerate(prompts):
                    if self._sa_stop_flag: return "retry_soft"
                    clip_path = os.path.join(temp_dir, f"sa_{item_id}_seg{seg_idx}.mp4")
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 100 * 1024:
                        self._sa_log_msg(f"  ⚡ Seg {seg_idx+1}: Dùng lại ({os.path.getsize(clip_path)//1024}KB)")
                        clip_paths.append(clip_path); continue

                    key_field = f"_idem_{seg_idx}"
                    if not prod.get(key_field): prod[key_field] = str(uuid.uuid4())

                    self._sa_log_msg(f"  🎬 Segment {seg_idx+1}/{n_segments} (8s)...")
                    # Condense prompt for ShopAPI 5000 char limit
                    import re
                    api_prompt = prompt
                    if len(api_prompt) > 4900:
                        condensed_extra = ""
                        if lang_code == "my":
                            condensed_extra = "- MALAYSIA MARKET: MUST use a Malay male presenter with modest clothing (clean long-sleeve shirt, dark trousers, neat appearance). NO female models.\n"
                        CONDENSED = "=== SECTION 1: RULES ===\n- Full-frame 9:16 vertical video, edge-to-edge, NO borders/bars/margins.\n- Photorealistic live-action only. NO cartoon/anime/CGI.\n- NO text/subtitles/watermarks on screen.\n- Product must match reference image exactly.\n- Realistic product size. NO oversized items.\n- Presenter has exactly 2 hands, 5 fingers each. NO extra limbs.\n- No anatomical anomalies, no extra arms, no third hand, no weird deformations.\n- Neutral color grading, no morphing or identity drift.\n" + condensed_extra + "\n"
                        api_prompt = re.sub(r'=== SECTION 1:.*?=== SECTION 2:', CONDENSED + '=== SECTION 2:', api_prompt, count=1, flags=re.DOTALL)
                        if len(api_prompt) > 4900:
                            api_prompt = re.sub(r'^\[CONTENT FORMAT[^\]]*\]\s*', '', api_prompt)
                        if len(api_prompt) > 4900:
                            api_prompt = api_prompt[:4900]
                        self._sa_log_msg(f"    ✂ Prompt: {len(prompt)} → {len(api_prompt)} ký tự")

                    submit_res, job_or_err = submit_video_with_retry(api_prompt, shopapi_image_url, prod[key_field])
                    if submit_res == "stopped": return "retry_soft"
                    elif submit_res == "insufficient_balance":
                        prod["_status"] = "noretry"
                        self._sa_update_line_status(idx, "error")
                        return ("fail", "Hết số dư")
                    elif submit_res != "ok": return "retry_soft"

                    job_id = job_or_err.get("id", "")
                    self._sa_log_msg(f"  ⏳ Job {job_id[:16]}... polling...")
                    poll_res, poll_data = poll_job_until_done(job_id)

                    if poll_res == "retry_temporary":
                        prod[key_field] = None; return "retry_soft"
                    elif poll_res == "fail_permanent":
                        prod["_status"] = "noretry"
                        try: self._sa_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "failed", "tool": "thinaptm"})
                        except: pass
                        self._sa_update_line_status(idx, "error")
                        return ("fail", str(poll_data))
                    elif poll_res != "succeeded": return "retry_soft"

                    # Extract video URL
                    result = poll_data
                    outputs = result.get("outputs") or []
                    if not outputs:
                        single = result.get("output")
                        if single and hasattr(single, 'get') and single.get("url"): outputs = [single]
                    if not outputs:
                        for field in ("result", "video", "data"):
                            val = result.get(field)
                            if val and hasattr(val, 'get') and val.get("url"): outputs = [val]; break
                            elif isinstance(val, (list, tuple)) and val: outputs = list(val); break
                    if not outputs:
                        rd = result.to_dict() if hasattr(result, 'to_dict') else result
                        if isinstance(rd, dict):
                            for k, v in rd.items():
                                if isinstance(v, str) and "http" in v and ("video" in v or ".mp4" in v):
                                    outputs = [{"url": v}]; break
                    if not outputs:
                        self._sa_log_msg(f"  ❌ Job xong nhưng không có output")
                        return "retry_soft"

                    video_url = outputs[0].get("url", "") if hasattr(outputs[0], 'get') else str(outputs[0])
                    if not video_url: return "retry_soft"

                    # Download
                    import urllib.request as urlreq
                    self._sa_log_msg(f"  📥 Tải video segment {seg_idx+1}...")
                    try: urlreq.urlretrieve(video_url, clip_path)
                    except Exception as de:
                        self._sa_log_msg(f"  ❌ Tải lỗi: {de}"); return "retry_soft"
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 10 * 1024:
                        clip_paths.append(clip_path)
                        self._sa_log_msg(f"  ✅ Seg {seg_idx+1} OK ({os.path.getsize(clip_path)//1024}KB)")
                    else:
                        self._sa_log_msg(f"  ❌ Seg {seg_idx+1}: File rỗng"); return "retry_soft"

                if not clip_paths: return "retry_soft"

                # Concat
                if len(clip_paths) > 1:
                    self._sa_log_msg(f"  🔗 Ghép {len(clip_paths)} segments...")
                    concat_path = os.path.join(temp_dir, f"sa_{item_id}_concat.mp4")
                    try: SV.concat_videos(clip_paths, concat_path, log=lambda m: self._sa_log_msg(f"    {m}"))
                    except Exception as ex: return ("fail", f"Ghép lỗi: {ex}")
                else:
                    concat_path = clip_paths[0]

                # Naming
                if naming_mode == "Theo Item ID": out_name = f"{item_id}.mp4"
                elif naming_mode == "15 ký tự đầu prompt": out_name = SV.clean_filename(prompts[0][:15]) + ".mp4" if hasattr(SV, 'clean_filename') else f"{item_id}.mp4"
                else: out_name = f"{idx+1:04d}.mp4"

                # Use get_unique_out_path helper from the existing codebase
                # Simple unique path logic
                out_path = os.path.join(out_dir, out_name)
                counter = 2
                while os.path.exists(out_path):
                    base, ext = os.path.splitext(out_name)
                    out_path = os.path.join(out_dir, f"{base}_{counter}{ext}")
                    counter += 1

                import shutil
                try:
                    shutil.move(concat_path, out_path)
                    self._sa_log_msg(f"  ✅ Video: {os.path.basename(out_path)}")
                except Exception as ex:
                    return ("fail", f"Move lỗi: {ex}")

                # Report to server
                try:
                    self._sa_api_call("POST", "/api/thinaptm/complete-job", {
                        "itemId": item_id, "status": "completed", "tool": "thinaptm",
                        "videoFile": os.path.basename(out_path)
                    })
                except: pass

                # Delete image
                if del_img:
                    try: os.remove(img_path)
                    except: pass

                prod["_status"] = "success"
                self._sa_update_line_status(idx, "success")
                with results_lock:
                    done_count[0] += 1
                    self._sa_video_done_count = done_count[0]
                    self.after(0, lambda c=done_count[0]: self._sa_video_done_lbl.configure(text=f"✅ {c} video"))
                    prog = (done_count[0] + error_count[0]) / total
                    self.after(0, lambda p=prog: self._sa_progress.set(p))
                return ("success", out_path)

            # Worker loop
            def sa_worker(worker_id=0):
                # Giãn cách khởi động 0.06s/luồng để 50 luồng không gửi request cùng 1 micro-giây
                time.sleep(worker_id * 0.06)
                while not self._sa_stop_flag:
                    try: prod = jobq.get(timeout=2)
                    except queue.Empty: break
                    if prod.get("_status") in ("success", "noretry"): continue
                    result = process_one(prod)
                    if result == "retry_soft":
                        prod["_cycles"] += 1
                        if prod["_cycles"] < 3:
                            time.sleep(5); jobq.put(prod)
                        else:
                            prod["_status"] = "noretry"
                            self._sa_update_line_status(prod["_idx"], "error")
                            with results_lock:
                                error_count[0] += 1
                                self.after(0, lambda p=(done_count[0]+error_count[0])/total: self._sa_progress.set(p))
                            try: self._sa_api_call("POST", "/api/thinaptm/complete-job", {"itemId": prod.get("item_id"), "status": "failed", "tool": "thinaptm"})
                            except: pass
                    elif isinstance(result, tuple) and result[0] == "fail":
                        prod["_status"] = "noretry"
                        self._sa_update_line_status(prod["_idx"], "error")
                        with results_lock:
                            error_count[0] += 1
                            self.after(0, lambda p=(done_count[0]+error_count[0])/total: self._sa_progress.set(p))
                        try: self._sa_api_call("POST", "/api/thinaptm/complete-job", {"itemId": prod.get("item_id"), "status": "failed", "tool": "thinaptm"})
                        except: pass

            with ThreadPoolExecutor(max_workers=n_workers) as executor:
                futures = [executor.submit(sa_worker, wid) for wid in range(n_workers)]
                for fut in futures: fut.result()

            # Release remaining
            remaining = [p for p in products if p.get("_status") not in ("success", "noretry")]
            if remaining and self._sa_stop_flag:
                self._sa_log_msg(f"🔄 Trả {len(remaining)} SP...")
                try: self._sa_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                except: pass

            self._sa_log_msg(f"\n{'='*50}")
            self._sa_log_msg(f"🏁 HOÀN TẤT: ✅ {done_count[0]}/{total} thành công, ❌ {error_count[0]} lỗi")
            self.after(0, lambda: self._sa_status_lbl.configure(text=f"✅ {done_count[0]}/{total} xong"))
            self._sa_finish()

        threading.Thread(target=work, daemon=True).start()

    def _sv_finish(self):

        """Phục hồi trạng thái UI sau khi hoàn tất/dừng."""
        self._sv_running = False
        self.after(0, lambda: self._sv_btn_start.configure(state="normal"))
        self.after(0, lambda: self._sv_btn_stop.configure(state="disabled"))
        self.after(0, lambda: self._sv_btn_claim.configure(state="normal", text="📥 Nhận Lô Sản Phẩm"))

    def _on_closing(self):
        # Hủy health check timer
        if self._health_check_timer:
            try: self.after_cancel(self._health_check_timer)
            except Exception: pass
            self._health_check_timer = None
        try:
            # Lấy prompt của chế độ i2v (từ giao diện hoặc từ bộ nhớ)
            raw_prompts = [l.strip() for l in self.txt_prompts.get("1.0", "end").splitlines() if l.strip() and not l.startswith("(Đã nạp")]
            if raw_prompts:
                custom_prompts = raw_prompts
            else:
                custom_prompts = self.loaded_prompts

            s = {
                "gen_mode": self.gen_mode.get(),
                "ref_dir": self.ent_ref.get(),
                "aspect": self.opt_aspect.get(),
                "gen_upload_threads_per_acc": self.opt_upload_threads_per_acc.get(),
                "naming": self.opt_naming.get(),
                "out_dir": self.ent_out.get(),
                "gemini_keys": [l.strip() for l in self.txt_gemini.get("1.0", "end").splitlines() if l.strip()],
                "image_paths": self.image_paths,
                "custom_prompts": custom_prompts,
                "t2v_prompts": self.txt_prompts.get("1.0", "end-1c") if self.gen_mode.get() == "t2v" else "",
                "jobs": self.jobs,
                # AI viết prompt settings
                "ai_topic": self.ent_ai_topic.get("1.0", "end-1c").strip(),
                "ai_char_style": self.opt_ai_style.get(),
                "ai_num_scenes": self.opt_ai_scenes.get(),
                "health_check_enabled": self._health_check_enabled,
                "health_check_interval": self._health_check_interval,
                "use_laundering": self.use_laundering.get(),
                "disable_proxy": self.disable_proxy.get(),
                "auto_homeproxy": self._auto_homeproxy.get(),
                "homeproxy_token": self._homeproxy_token.get().strip(),
                "warp_enabled": self._warp_enabled.get(),
                "warp_port": int(self._warp_port.get().strip() or 40000),
                "auto_concat": self.auto_concat.get(),
                "remove_veo_wm": self.remove_veo_wm.get(),
                # Giọng nói cố định
                "voice_desc": self.ent_voice_desc.get().strip(),
                # Tạo + Tốc độ settings
                "workers_per_account": 5,
                "submit_max": 5,
                # Telegram settings
                "tg_token": self.ent_tg_token.get().strip(),
                "tg_chatid": self.ent_tg_chatid.get().strip(),
                "tg_enabled": self.tg_enabled.get(),
                # Shopee settings
                "shopee_aspect": self._sp_aspect.get(),
                "shopee_scene": self._sp_scene.get(),
                "shopee_duration": self._sp_duration.get(),
                "shopee_model_dir": self._sp_model_dir.get(),
                "shopee_out_dir": self._sp_outdir.get(),
                "shopee_products": self._sp_products.get("1.0", "end-1c"),
                "shopee_img_folder": self._sp_img_folder,
    
                "shopee_lang": self._sp_lang.get(),
                "shopee_remove_wm": self._sp_remove_wm.get(),
                "shopee_use_laundering": self._sp_use_laundering.get(),
                "shopee_ai_prompt": self._sp_ai_prompt.get(),
                "shopee_del_img": self._sp_del_img.get(),
                "shopee_ghep_anh": self._sp_ghep_anh.get(),
                # Proxy pool
                "proxy_list": [l.strip() for l in self.txt_proxy.get("1.0", "end").splitlines() if l.strip()],
                "groq_api_key": "\n".join(k.strip() for k in self.txt_groq_keys.get("1.0", "end").splitlines() if k.strip()),
                # reCAPTCHA mode
                "recaptcha_mode": self._recaptcha_mode.get(),
                "recaptcha_workers": int(self._rc_workers.get().strip() or "3"),
            }
            # Server Video tab settings (safe — chỉ lưu nếu tab đã load OK)
            if hasattr(self, '_sv_url'):
                s.update({
                    "sv_server_url": self._sv_url.get().strip(),
                    "sv_api_key": self._sv_apikey.get().strip(),
                    "sv_client_id": self._sv_client_entry.get().strip(),
                    "sv_aspect": self._sv_aspect.get(),
                    "sv_scene": self._sv_scene.get(),
                    "sv_duration": self._sv_duration.get(),
                    "sv_lang": self._sv_lang.get(),
                    "sv_model": self._sv_model.get(),
                    "sv_review_style": self._sv_review_style.get(),
                    "sv_remove_wm": self._sv_remove_wm.get(),
                    "sv_del_img": self._sv_del_img.get(),
                    "sv_ghep_anh": self._sv_ghep_anh.get(),
                    "sv_use_laundering": self._sv_use_laundering.get(),
                    "sv_ai_prompt": self._sv_ai_prompt.get(),
                    "sv_workers_per_account": 5,
                    "sv_submit_max": 5,
                    "sv_naming": self._sv_naming.get(),
                    "sv_out_dir": self._sv_outdir.get().strip(),
                    "sv_claim_limit": self._sv_claim_limit.get().strip(),
                    "sv_sort_by": self._sv_sort_by.get(),
                    "sv_market": self._sv_market.get(),
                    "sv_min_item_id": self._sv_min_item_id.get().strip(),
                    "sv_min_commission": self._sv_min_commission.get().strip(),
                })
                # ShopAPI settings (nguồn tạo video)
                if hasattr(self, '_sv_source'):
                    s["sv_source"] = self._sv_source.get()
                if hasattr(self, '_sv_shopapi_key'):
                    s["sv_shopapi_key"] = self._sv_shopapi_key.get().strip()
                # ShopAPI tab riêng
                if hasattr(self, '_sa_shopapi_key'):
                    s.update({
                        "sa_shopapi_key": self._sa_shopapi_key.get().strip(),
                        "sa_shopapi_engine": self._sa_shopapi_engine.get(),
                        "sa_threads": self._sa_threads.get().strip(),
                        "sa_aspect": self._sa_aspect.get(),
                        "sa_scene": self._sa_scene.get(),
                        "sa_duration": self._sa_duration.get(),
                        "sa_lang": self._sa_lang.get(),
                        "sa_review_style": self._sa_review_style.get(),
                        "sa_ai_prompt": self._sa_ai_prompt.get(),
                        "sa_del_img": self._sa_del_img.get(),
                        "sa_naming": self._sa_naming.get(),
                        "sa_out_dir": self._sa_outdir.get().strip(),
                        "sa_claim_limit": self._sa_claim_limit.get().strip(),
                        "sa_sort_by": self._sa_sort_by.get(),
                        "sa_market": self._sa_market.get(),
                        "sa_min_item_id": self._sa_min_item_id.get().strip(),
                        "sa_min_commission": self._sa_min_commission.get().strip(),
                    })
                if hasattr(self, '_sv_shopapi_engine'):
                    s["sv_shopapi_engine"] = self._sv_shopapi_engine.get()
            save_settings(s)
        except Exception as e:
            self._log(f"Lỗi lưu cài đặt: {e}")
        # Dừng Token Farm nếu đang chạy
        self._stop_recaptcha_farm()
        # Dọn dẹp tiến trình Chrome/Chromedriver/DrissionPage rác đồng bộ
        self._clean_orphaned_chrome(sync=True)
        self._clean_temp_render()
        self.destroy()

    def _clean_temp_render(self):
        """Xóa sạch các file tạm trong thư mục temp_render để giải phóng bộ nhớ khi tắt app."""
        temp_dir = os.path.join(HERE, "temp_render")
        if os.path.exists(temp_dir):
            import shutil
            for filename in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception:
                    pass

    def _clean_orphaned_chrome(self, sync=False):
        """Quét và tắt ngầm các tiến trình Chrome/Chromedriver tự động hóa bị kẹt của Thìn Aptm.
        Tuyệt đối KHÔNG đụng tới Chrome cá nhân của người dùng hay GemLogin app!"""
        def _do_sweep():
            import psutil, os
            current_pid = os.getpid()
            try:
                all_procs = []
                for p in psutil.process_iter(['pid', 'name', 'ppid', 'cmdline']):
                    try: all_procs.append(p.info)
                    except: pass
                pids_active = {p['pid'] for p in all_procs}
                for p in all_procs:
                    if p['pid'] == current_pid:
                        continue
                    name = (p['name'] or '').lower()
                    pid = p['pid']
                    ppid = p['ppid']
                    cmd = " ".join(p['cmdline']).lower() if p['cmdline'] else ""
                    
                    # 1. Chromedriver kẹt (không còn parent python)
                    if name == 'chromedriver.exe':
                        if ppid not in pids_active:
                            try: psutil.Process(pid).kill()
                            except: pass
                    # 2. CHỈ diệt Chrome / Iron tự động hóa do DrissionPage / ThinAptm mở ra (có chứa 'drissionpage', '_profiles' + 'remote-debugging-port')
                    # KHÔNG BAO GIỜ diệt Chrome bình thường của người dùng!
                    elif name in ('chrome.exe', 'iron.exe'):
                        if 'gemlogin' in cmd:
                            continue
                        try:
                            exe_path = psutil.Process(pid).exe().lower()
                            if 'gemlogin' in exe_path:
                                continue
                        except Exception:
                            pass
                        
                        # Bắt buộc CHỈ diệt nếu command line chứa thông số nhận diện tự động hóa riêng của app
                        is_automated_thinaptm = ('drissionpage' in cmd) or ('_profiles' in cmd) or ('remote-debugging-port' in cmd)
                        if is_automated_thinaptm or name == 'iron.exe':
                            if ppid not in pids_active or ppid == current_pid:
                                try: psutil.Process(pid).kill()
                                except: pass
            except Exception:
                pass

        if sync:
            _do_sweep()
        else:
            import threading
            threading.Thread(target=_do_sweep, daemon=True).start()

    def _clean_orphaned_chrome_manually(self):
        """Dọn dẹp thủ công khi người dùng click button, có hiển thị thông báo kết quả (Không tắt GemLogin)."""
        def _do_sweep():
            import psutil
            try:
                all_procs = []
                for p in psutil.process_iter(['pid', 'name', 'ppid', 'memory_info', 'cmdline']):
                    try: all_procs.append(p.info)
                    except: pass
                pids_active = {p['pid'] for p in all_procs}
                killed_count = 0
                freed_ram = 0
                for p in all_procs:
                    name = (p['name'] or '').lower()
                    pid = p['pid']
                    ppid = p['ppid']
                    cmd = " ".join(p['cmdline']).lower() if p['cmdline'] else ""
                    # 1. Chromedriver kẹt
                    if name == 'chromedriver.exe':
                        if ppid not in pids_active:
                            try:
                                mem = p['memory_info'].rss if p['memory_info'] else 0
                                psutil.Process(pid).kill()
                                killed_count += 1
                                freed_ram += mem
                            except: pass
                    # 2. Chrome / Iron tự động hóa (Tuyệt đối KHÔNG đụng tới GemLogin)
                    elif name in ('chrome.exe', 'iron.exe'):
                        if 'gemlogin' in cmd:
                            continue
                        try:
                            exe_path = psutil.Process(pid).exe().lower()
                            if 'gemlogin' in exe_path:
                                continue
                        except Exception:
                            pass
                        is_helper = '--type=' in cmd
                        is_automated = '--headless' in cmd or '--remote-debugging-port' in cmd or 'automation' in cmd or '_profiles' in cmd or name == 'iron.exe'
                        parent_dead = ppid not in pids_active
                        parent_proc = [x for x in all_procs if x['pid'] == ppid]
                        parent_name = parent_proc[0]['name'].lower() if parent_proc else ''
                        
                        if is_automated or is_helper:
                            if parent_dead or parent_name not in ['python.exe', 'pythonw.exe']:
                                try:
                                    mem = p['memory_info'].rss if p['memory_info'] else 0
                                    psutil.Process(pid).kill()
                                    killed_count += 1
                                    freed_ram += mem
                                except: pass
                
                msg = f"Đã quét dọn xong!\n- Đóng thành công: {killed_count} tiến trình Chrome/Driver rác.\n- Giải phóng: {freed_ram / (1024*1024):.1f} MB RAM."
                self.after(0, lambda: messagebox.showinfo("Dọn Dẹp", msg))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Lỗi", f"Lỗi dọn dẹp: {e}"))
        import threading
        threading.Thread(target=_do_sweep, daemon=True).start()

    def _start_update_checker(self):
        """Khởi chạy thread kiểm tra bản cập nhật từ GitHub."""
        try:
            self.btn_do_update.configure(text="⏳ Đang kiểm tra...", state="disabled")
        except Exception:
            pass

        def _check():
            try:
                import urllib.request, re
                import update as updater
                repo_url = "https://raw.githubusercontent.com/thincole/thinaptm/main/"
                has_update = False
                changed_files = []
                remote_ver = None
                check_files = getattr(updater, "FILES", ["thin_aptm.py", "engine.py", "login.py", "auto_voice_sub.py", "ghep_video.py", "prompt_templates.py", "recaptcha_farm.py", "update.py"])
                for f in check_files:
                    try:
                        req = urllib.request.Request(
                            repo_url + f + f"?t={os.urandom(4).hex()}",
                            headers={"Cache-Control": "no-cache", "User-Agent": "thinaptm-app-checker"}
                        )
                        remote_data = urllib.request.urlopen(req, timeout=5).read()
                        if not remote_data or len(remote_data) < 30:
                            continue
                        if f == "thin_aptm.py":
                            m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', remote_data.decode("utf-8", errors="ignore"))
                            if m: remote_ver = m.group(1)
                        local_path = os.path.join(HERE, f)
                        local_data = open(local_path, "rb").read() if os.path.exists(local_path) else b""
                        if remote_data != local_data:
                            has_update = True
                            changed_files.append(f)
                    except Exception:
                        pass
                if has_update:
                    display_ver = remote_ver if remote_ver else "Bản mới"
                    self._log(f"🔔 CẢNH BÁO CẬP NHẬT: Có bản mới ({display_ver}) trên GitHub ({len(changed_files)} file thay đổi)!")
                    self.after(0, lambda: self._show_update_badge(changed_files, display_ver))
                else:
                    self.after(0, self._show_up_to_date_badge)
            except Exception as e:
                print(f"Lỗi kiểm tra update: {e}")
                self.after(0, self._show_up_to_date_badge)
        
        threading.Thread(target=_check, daemon=True).start()

    def _show_update_badge(self, changed_files, remote_ver="Bản mới"):
        """Chuyển thẻ sang trạng thái màu cam khi có bản cập nhật mới trên GitHub."""
        try:
            self.update_card.configure(fg_color="#FFF3E0", border_color="#FFB74D")
            self.lbl_update_title.configure(text="🔔 CÓ BẢN CẬP NHẬT MỚI!", text_color="#E65100")
            self.lbl_update_sub.configure(text=f"Phiên bản mới: {remote_ver}\n({len(changed_files)} file thay đổi)", text_color="#F57C00")
            self.btn_do_update.configure(
                text="⚡ Cập nhật ngay",
                fg_color="#FF9800",
                hover_color="#F57C00",
                state="normal",
                command=self._apply_app_update
            )
        except Exception:
            pass

    def _show_up_to_date_badge(self):
        """Giữ thẻ ở trạng thái màu xanh nhẹ thông báo đã ở bản mới nhất."""
        try:
            self.update_card.configure(fg_color="#E8F5E9", border_color="#81C784")
            self.lbl_update_title.configure(text="✅ ĐÃ Ở BẢN MỚI NHẤT", text_color="#2E7D32")
            self.lbl_update_sub.configure(text=f"Phiên bản: {APP_VERSION}", text_color="#388E3C")
            self.btn_do_update.configure(
                text="🔄 Kiểm tra lại",
                fg_color="#4CAF50",
                hover_color="#388E3C",
                state="normal",
                command=self._start_update_checker
            )
        except Exception:
            pass

    def _apply_app_update(self, changed_files=None):
        """Tải và ghi đè bản cập nhật mới nhất từ GitHub."""
        try:
            self.btn_do_update.configure(text="⏳ Đang tải...", state="disabled")
        except Exception:
            pass

        def _do_download():
            try:
                import urllib.request
                import update as updater
                repo_url = "https://raw.githubusercontent.com/thincole/thinaptm/main/"
                files_to_update = getattr(updater, "FILES", ["thin_aptm.py", "engine.py", "login.py", "auto_voice_sub.py", "ghep_video.py", "prompt_templates.py", "recaptcha_farm.py", "update.py"])
                updated_count = 0
                for f in files_to_update:
                    try:
                        req = urllib.request.Request(
                            repo_url + f + f"?t={os.urandom(4).hex()}",
                            headers={"Cache-Control": "no-cache", "User-Agent": "thinaptm-app-updater"}
                        )
                        data = urllib.request.urlopen(req, timeout=12).read()
                        if data and len(data) >= 1:
                            local_path = os.path.join(HERE, f.replace("/", os.sep))
                            os.makedirs(os.path.dirname(local_path), exist_ok=True)
                            with open(local_path, "wb") as fp:
                                fp.write(data)
                            updated_count += 1
                    except Exception as ex:
                        print(f"Lỗi tải {f}: {ex}")
                
                # Cài đặt httpx nếu thiếu
                try:
                    import httpx
                except ImportError:
                    try:
                        import subprocess
                        subprocess.run([sys.executable, "-m", "pip", "install", "httpx", "-q"], timeout=30)
                    except Exception:
                        pass

                self.after(0, lambda: messagebox.showinfo("Cập Nhật Thành Công", f"🎉 Đã tải thành công {updated_count} file từ GitHub!\n\nVui lòng đóng phần mềm và mở lại (chạy CHAY.bat) để áp dụng bản mới nhất."))
                self.after(0, self._show_up_to_date_badge)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Lỗi Cập Nhật", f"Không thể tải bản cập nhật: {e}"))

        threading.Thread(target=_do_download, daemon=True).start()
        
    def _schedule_periodic_cleanup(self):
        """Lên lịch tự động quét dọn mỗi 30 phút trong thread nền: Chrome rác + temp files cũ + RAM."""
        def _bg_cleanup():
            try:
                self._clean_orphaned_chrome(sync=True)
                self._clean_old_temp_files()
                self._memory_watchdog()
            except Exception:
                pass
        threading.Thread(target=_bg_cleanup, daemon=True).start()
        self.after(1800000, self._schedule_periodic_cleanup)

    def _clean_old_temp_files(self):
        """Xóa file temp > 1 giờ tuổi trong temp_render và _temp_shopee để tránh đầy ổ cứng khi chạy 24/7."""
        import glob
        now = time.time()
        max_age = 3600  # 1 giờ
        cleaned = 0
        for temp_dir in [
            os.path.join(HERE, "temp_render"),
            # Tìm tất cả _temp_shopee trong các thư mục output
            *glob.glob(os.path.join(HERE, "**", "_temp_shopee"), recursive=True),
        ]:
            if not os.path.isdir(temp_dir):
                continue
            try:
                for f in os.listdir(temp_dir):
                    fp = os.path.join(temp_dir, f)
                    try:
                        if os.path.isfile(fp) and (now - os.path.getmtime(fp)) > max_age:
                            os.remove(fp)
                            cleaned += 1
                    except Exception:
                        pass
            except Exception:
                pass
        if cleaned > 0:
            try:
                self._sv_log_msg(f"🧹 [Auto Cleanup] Đã dọn {cleaned} file temp > 1h tuổi")
            except Exception:
                pass

    def _memory_watchdog(self):
        """Kiểm tra RAM. Nếu > 2GB → force garbage collection + log cảnh báo."""
        import gc
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            mem_mb = proc.memory_info().rss / (1024 * 1024)
            if mem_mb > 2048:
                gc.collect()
                mem_after = proc.memory_info().rss / (1024 * 1024)
                try:
                    self._sv_log_msg(f"⚠️ [Memory] RAM {int(mem_mb)}MB > 2GB → GC forced → {int(mem_after)}MB")
                except Exception:
                    pass
            elif mem_mb > 1024:
                gc.collect()  # GC nhẹ khi > 1GB
        except ImportError:
            gc.collect()  # psutil không có → chỉ GC mỗi 30 phút
        except Exception:
            pass


if __name__ == "__main__":
    # ── Single Instance Guard: chống mở nhiều cửa sổ gây đơ ──
    import socket as _sock
    _LOCK_PORT = 48923  # port nội bộ dùng để kiểm tra instance duy nhất
    _lock_sock = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    try:
        _lock_sock.bind(("127.0.0.1", _LOCK_PORT))
    except OSError:
        # Đã có 1 instance đang chạy → hiện thông báo và thoát
        import tkinter.messagebox as _mb
        import tkinter as _tk
        _r = _tk.Tk(); _r.withdraw()
        _mb.showwarning("Thìn Aptm", "Phần mềm đã đang chạy!\nKhông thể mở thêm cửa sổ thứ 2.")
        _r.destroy()
        raise SystemExit(0)
    App().mainloop()
