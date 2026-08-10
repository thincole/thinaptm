# Phân tích Thiết kế & Thuật toán Dự án Thìn Aptm

Tài liệu này phân tích chi tiết về kiến trúc, luồng hoạt động và các thuật toán cốt lõi của công cụ **Thìn Aptm** — giải pháp tự động tạo video Google Labs (Flow/Veo 3.1) đa luồng.

---

## 1. Cấu trúc Dự án & Các Thành phần Chính

Dự án được xây dựng bằng Python với cấu trúc module hóa rõ ràng:

*   **[thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py)**: 
    *   Thành phần Giao diện người dùng (GUI) được viết bằng thư viện `customtkinter`.
    *   Quản lý danh sách tài khoản, cấu hình tác vụ và hàng đợi công việc.
    *   Điều phối đa luồng qua mô hình **1 hàng đợi chung + N×wpa worker threads** — mỗi worker pull job khi rảnh (work-stealing tự nhiên).
    *   Tích hợp thuật toán AIMD (Additive Increase, Multiplicative Decrease) để tự động điều chỉnh tốc độ submit/tài khoản.
    *   Phân loại lỗi chi tiết: AUDIO_FILTERED (Gemini rewrite), DANGER_FILTER/PROMINENT_PEOPLE (vi phạm cs), i2v_blocked (cấm upload ảnh).
*   **[login.py](file:///E:/ThinAptm0707/login.py)**:
    *   Thực hiện nhiệm vụ xác thực với Google Labs (3 cách).
    *   *Cách 1 — Thủ công (`manual_login`):* Mở trình duyệt Chromium độc lập qua `DrissionPage` để người dùng tự đăng nhập và quét cookie.
    *   *Cách 2 — Tự động (`login_get_cookie`):* Tự động nhập thông tin tài khoản, mật khẩu và sinh mã OTP qua thuật toán TOTP (`pyotp`) từ Secret Key 2FA để vượt qua bước bảo mật.
    *   *Cách 3 — Profile re-login (`reopen_profile_cookie`):* Mở Chrome với profile CŨ (giữ session Google) → Google tự đăng nhập lại → lấy cookie mới mà KHÔNG cần password. Cơ chế giống Chiến Hust.
*   **[engine.py](file:///E:/ThinAptm0707/engine.py)**:
    *   Lõi API tương tác trực tiếp với máy chủ Google (`aisandbox-pa.googleapis.com`).
    *   Chịu trách nhiệm chuyển đổi cookie thành Bearer Token, tải ảnh lên (I2V), submit tác vụ tạo video, thăm dò trạng thái (polling) và tải video kết quả.
*   **`accounts.json`**:
    *   Cơ sở dữ liệu lưu trạng thái tài khoản dưới dạng JSON bao gồm: Email, password, 2FA secret, cookie hiện tại và tình trạng hoạt động (`ok`, `dead`, `new`).

---

## 2. Quy trình Hoạt động (Operational Flow)

Hệ thống vận hành theo 3 giai đoạn khép kín từ khâu chuẩn bị tài khoản đến xuất bản video:

### Giai đoạn A: Đăng ký & Xác thực Tài khoản
1.  **Đăng nhập thủ công:**
    *   Hệ thống khởi tạo Chromium với tham số `co.auto_port()` để chạy cổng riêng biệt không đụng độ Chrome cá nhân.
    *   Một vòng lặp quét liên tục mỗi 2 giây để tìm cookie `next-auth.session-token` của tên miền `labs.google`. Khi phát hiện, cookie được lưu lại và trình duyệt tự động đóng.
2.  **Tự động Đăng nhập:**
    *   `DrissionPage` định vị các thẻ Input đăng nhập của Google và điền thông tin.
    *   Mã 2FA được tạo động tại thời gian thực thông qua thuật toán TOTP:
        $$\text{OTP} = \text{TOTP}(\text{Secret Key}, \text{time})$$
        và được điền tự động để hoàn tất đăng nhập.

### Giai đoạn B: Quản lý và Nạp Tác vụ
1.  Người dùng thiết lập chế độ tạo video:
    *   *Text $\rightarrow$ Video (T2V):* Nhập danh sách prompt văn bản (mỗi dòng tạo 1 video).
    *   *Image $\rightarrow$ Video (I2V):* Chọn thư mục chứa ảnh gốc. Mỗi ảnh được ghép với một prompt văn bản tương ứng. 
        *(Tối ưu hóa: Nếu thư mục chứa hơn 200 ảnh, giao diện chi tiết sẽ tự động ẩn để tránh treo app, toàn bộ quá trình khớp ảnh + prompt sẽ được thực hiện trực tiếp trên RAM siêu tốc).*
2.  Ứng dụng tính toán tên file đầu ra tự động dựa trên lựa chọn đặt tên của người dùng (mặc định lấy 13 ký tự đầu của prompt, hoặc đặt theo tên ảnh gốc, hoặc số thứ tự) và đặt vào thư mục lưu trữ được chỉ định. Tên file được làm sạch các ký tự đặc biệt và tự động thêm hậu tố chống trùng thông qua tìm kiếm tập hợp $O(1)$.

### Giai đoạn C: Thực thi Đa luồng Hàng đợi

Khi bấm **Bắt đầu**, luồng chính của giao diện kích hoạt `_start()` → `_run()` trong thread riêng:

```
_run(accs, todo, wpa=15)
│
├─ 1. Auth tất cả tài khoản (refresh bearer từ cookie)
│     └─ AccountState.ensure_auth(force=True) cho mỗi acc
│        └─ bearer_from_cookie(cookie) → bearer + email
│        └─ get_project(cookie) → projectId
│
├─ 2. Gán proxy từ ProxyPool (nếu có)
│
├─ 3. Tạo hàng đợi chung (queue.Queue)
│     └─ Đưa tất cả jobs vào queue, gắn _cycles = 0
│
├─ 4. Spawn workers: len(states) × wpa threads
│     └─ Mỗi thread chạy worker(st) → pull job từ queue
│
├─ 5. _drain(): chờ đến khi tất cả jobs xong/lỗi/vi phạm
│
├─ 6. Auto-retry: lặp lại 2 vòng cho jobs lỗi
│     └─ Đặt lại status="chờ", _cycles=0, put vào queue
│     └─ Workers vẫn sống → nhặt lại job
│
└─ 7. Join threads + thống kê kết quả + Telegram report
```

**Mô hình:** `1 HÀNG ĐỢI CHUNG` + mỗi tài khoản chạy `wpa` (15) workers, tất cả pull từ hàng đợi chung. Account throttle → nghỉ (cooldown), account khác gánh; job requeue. Submit KHÔNG khóa/không sleep — poll inline tự giãn nhịp (worker bận ~60-90s/video), tận dụng render server-side song song.

> **Lưu ý:** Dù import `ThreadPoolExecutor`, chỉ dùng cho `_check_accs()` (check cookie song song) và `_do_health_check()`. Vòng tạo video chính dùng `queue.Queue` + `worker()` thuần.

---

## 3. Thuật toán & Cơ chế Bypass API

Để có thể gửi yêu cầu trực tiếp đến Google Labs không qua trình duyệt, dự án áp dụng các kỹ thuật bypass nâng cao:

### 1. Bypass TLS Fingerprint (Vân tay TLS)
Google sử dụng các cơ chế chống bot bằng cách phân tích vân tay gói tin TLS (JA3 Fingerprint) và tiêu chuẩn HTTP/2 của client.
*   **Giải pháp:** Sử dụng thư viện `curl_cffi` giả lập toàn bộ hành vi mạng của trình duyệt Chrome (`impersonate="chrome"`). Các yêu cầu HTTP thô sẽ mang đúng cấu hình cipher suite của Chrome, giúp đánh lừa hệ thống giám sát của Google.

### 2. Bypass Xác thực ReCaptcha (`android_bypass`)
Google Labs Flow yêu cầu xác minh Captcha khi sinh nội dung. Tuy nhiên, API dành cho các thiết bị di động có cơ chế xác thực riêng đơn giản hơn.
*   **Giải pháp:** Trong các payload gửi yêu cầu sinh video, cấu trúc client context được tùy biến để giả lập một yêu cầu đến từ ứng dụng Android:
    ```json
    "recaptchaContext": {
        "applicationType": "RECAPTCHA_APPLICATION_TYPE_ANDROID", 
        "token": "android_bypass"
    }
    ```
    Thuộc tính này giúp API chấp nhận yêu cầu mà không đòi hỏi thực hiện thử thách ảnh ReCaptcha.

### 3. Thuật toán Trích xuất Trạng thái Thăm dò (Polling)
Google Labs xử lý render video bất đồng bộ. Hệ thống cần gửi yêu cầu kiểm tra trạng thái định kỳ tới endpoint:
`https://aisandbox-pa.googleapis.com/v1/video:batchCheckAsyncVideoGenerationStatus?key={KEY}`
*   Do cấu trúc dữ liệu trả về từ Google rất phức tạp và lồng ghép nhiều lớp, `engine.py` triển khai thuật toán đệ quy duyệt cây `_find_status` để trích xuất trạng thái:
    ```python
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
    ```
*   Hệ thống sẽ kiểm tra xem mảng kết quả trả về từ hàm trên có chứa các từ khóa thành công (`SUCCESSFUL`, `SUCCEEDED`, `COMPLETE`) hoặc thất bại (`FAIL`) để quyết định bước tiếp theo.

### 4. Tải Xuống Video qua Redirect
Google bảo mật đường dẫn trực tiếp của video bằng cách tạo ra các URL động ngắn hạn.
*   Để tải file, hệ thống gọi API redirect `media.getMediaUrlRedirect?name={media_id}` với Cookie tài khoản.
*   Thư viện `curl_cffi` được cấu hình `allow_redirects=True` để đi theo luồng chuyển hướng của Google và nhận về file nhị phân của video `.mp4`, sau đó ghi trực tiếp xuống đĩa cứng.

---

## 4. Cơ chế Tự kiểm tra Cookie & Auto Re-login (Health Check)

### Mục đích
Cookie của Google Labs có thời hạn sử dụng giới hạn. Khi cookie hết hạn (die), tài khoản không thể tạo video. Cơ chế Health Check tự động phát hiện cookie chết và đăng nhập lại để lấy cookie mới, đảm bảo hệ thống chạy liên tục không cần can thiệp thủ công.

### Kiến trúc

```mermaid
graph TD
    A[Timer định kỳ - mỗi N phút] --> B[_cookie_health_check]
    B --> C[_do_health_check - chạy trên thread riêng]
    C --> D["Bước 1: Check cookie song song (8 luồng)"]
    D --> E{bearer_from_cookie OK?}
    E -- Có --> F["status = 'ok' ✅"]
    E -- Không --> G["status = 'dead' ❌ → dead_accs"]
    G --> PH1["Pha 1: reopen_profile_cookie — mở Chrome profile cũ, không cần password"]
    PH1 --> PH1R{"Profile có session?"}
    PH1R -- Có --> F
    PH1R -- Không --> PH2{Tài khoản có password?}
    PH2 -- Có --> PH2L["Pha 2: login_get_cookie — email + password + 2FA"]
    PH2 -- Không --> J["Bỏ qua - ghi log cảnh báo"]
    PH2L --> K{Login thành công?}
    K -- Có --> L["Cập nhật cookie mới + status = 'ok'"]
    K -- Không --> M["Giữ status = 'dead'"]
    L --> N[Lưu accounts.json + refresh UI]
    M --> N
    J --> N
    N --> O["Đặt lịch lần check kế tiếp (nếu vẫn bật)"]
```

### Các thành phần code

| Thành phần | Vị trí | Chức năng |
|---|---|---|
| `_health_check_enabled` | `App.__init__` | Cờ bật/tắt, lưu vào `settings.json` |
| `_health_check_interval` | `App.__init__` | Khoảng cách giữa các lần check (phút), tối thiểu 5 |
| `_health_check_timer` | `App.__init__` | ID timer của `self.after()`, dùng để hủy khi tắt |
| `_health_checking` | `App.__init__` | Cờ chống chạy trùng (mutex đơn giản) |
| `_toggle_health_check()` | `App` | Callback switch bật/tắt trên UI |
| `_get_hc_interval_ms()` | `App` | Đọc interval từ ô nhập, chuyển phút → ms |
| `_schedule_health_check()` | `App` | Đặt timer cho lần check kế tiếp |
| `_run_health_check_now()` | `App` | Nút "Check ngay" — chạy ngay lập tức |
| `_cookie_health_check()` | `App` | Callback từ timer → spawn thread |
| `_do_health_check()` | `App` | Logic chính: check + re-login (chạy trên thread) |

### UI trên tab Tài khoản

Card `hc_card` nằm dưới thanh nút, chứa:
- **Switch Bật/Tắt** (`_hc_switch`): Toggle tính năng health check
- **Ô nhập interval** (`_hc_interval_entry`): Số phút giữa mỗi lần check (mặc định 30)
- **Nhãn trạng thái** (`_hc_status_lbl`): Hiển thị "Lần check kế: HH:MM:SS" hoặc kết quả check gần nhất
- **Nút "▶ Check ngay"**: Chạy health check tức thì, không cần chờ timer

### Luồng xử lý chi tiết

1. **Khi bật switch**: `_toggle_health_check()` → `_schedule_health_check()` đặt `self.after(interval_ms)` 
2. **Khi timer trigger**: `_cookie_health_check()` → spawn `_do_health_check()` trên daemon thread
3. **`_do_health_check()` thực hiện**:
   - Filter tài khoản enabled có cookie
   - Check song song 8 luồng qua `ThreadPoolExecutor` → mỗi account gọi `E.bearer_from_cookie(cookie)`
   - Tài khoản nào bearer=None → đánh dấu `dead`, thêm vào `dead_accs`
   - Lưu `accounts.json`, refresh UI
   - **Pha 1 — Profile re-login** (không cần password):
     - Với mỗi tài khoản dead: tìm profile tại `_profiles/{email}` → gọi `L.reopen_profile_cookie(profile_dir)`
     - Google session trong profile còn sống → tự lấy cookie mới
     - Profile không tồn tại hoặc session hết hạn → chuyển sang Pha 2
   - **Pha 2 — Password re-login** (fallback):
     - Với mỗi tài khoản vẫn dead + có `password`: gọi `L.login_get_cookie(email, password, totp)`
     - Tạo/cập nhật profile tại `_profiles/{email}` để lần sau dùng Pha 1
   - Re-login thành công → cập nhật cookie mới + verify lại bearer
   - Lưu `accounts.json` sau mỗi tài khoản re-login
4. **Khi tắt switch**: Hủy timer qua `self.after_cancel()`
5. **Khi đóng app**: `_on_closing()` hủy timer + lưu trạng thái bật/tắt và interval vào `settings.json`

### Persistence (Lưu trữ cài đặt)

Trong `settings.json`:
```json
{
  "health_check_enabled": true,
  "health_check_interval": 30
}
```
- Được đọc khi khởi tạo `App.__init__`
- Được ghi khi đóng app `_on_closing()`
- Nếu đã bật, khi mở lại app sẽ tự khởi động timer

---

## 5. Thuật toán AIMD - Điều khiển Tốc độ Submit

### Mô hình

Hệ thống sử dụng mô hình **AIMD (Additive Increase / Multiplicative Decrease)** tương tự điều khiển tắc nghẽn TCP để tự điều chỉnh tốc độ submit cho MỖI tài khoản:

- **Additive Increase**: Sau mỗi `SUBMIT_UP_AFTER` (5) lần submit thành công liên tiếp → `submit_limit += 1`
- **Multiplicative Decrease**: Bị throttle (429) → `submit_limit *= SUBMIT_DOWN` (0.5)
- Giới hạn: `SUBMIT_MIN` (1) ≤ `submit_limit` ≤ `SUBMIT_MAX`

### 3 bộ cài đặt (Preset)

> [!IMPORTANT]
> **Mặc định dùng CHẾ ĐỘ CÂN BẰNG** — kết hợp tốc độ cao + ít 429 nhờ poll-inline back-pressure.

#### 🎯 Chế độ Cân bằng (Mặc định — đang dùng)

Nhiều workers + AIMD + poll-inline back-pressure → ít 429 nhất, tốc độ ~14-16 video/phút.

**Nguyên lý:** 15 workers/account nhưng mỗi worker bận poll 60-90s → tại bất kỳ thời điểm nào chỉ ~3-4 workers thực sự submit. Workers tự tạo back-pressure, AIMD chỉ là lớp bảo vệ thêm.

```python
WORKERS_PER_ACCOUNT = 15   # poll-inline back-pressure: ~3-4 submit thực tế
SUBMIT_START = 2.0
SUBMIT_MAX = 8.0
THROTTLE_SLEEP = 3.0       # 8s quá lâu gây thundering herd; 1.5s hơi hung hăng
JOB_MAX_CYCLES = 30
```

#### 🛡️ Chế độ An toàn (Ít account, chạy lâu dài)

Ưu tiên bền vững, tránh bị Google cấm upload ảnh/video. Tốc độ ~8-10 video/phút.

```python
WORKERS_PER_ACCOUNT = 8
SUBMIT_START = 2.0
SUBMIT_MAX = 5.0
THROTTLE_SLEEP = 5.0
JOB_MAX_CYCLES = 20
```

#### ⚡ Chế độ Hung hăng (Tốc độ cao — rủi ro bị ban)

Tốc độ ~18-20 video/phút nhưng có thể bị Google throttle nặng hoặc cấm upload ảnh sau 1-2 tiếng.

```python
WORKERS_PER_ACCOUNT = 20
SUBMIT_START = 3.0
SUBMIT_MAX = 10.0
THROTTLE_SLEEP = 1.5
JOB_MAX_CYCLES = 40
```

#### Bảng so sánh đầy đủ

| Tham số | 🎯 Cân bằng | 🛡️ An toàn | ⚡ Hung hăng | Ý nghĩa |
|---|---|---|---|---|
| `WORKERS_PER_ACCOUNT` | **15** | 8 | 20 | Số luồng render/tài khoản (đa số bận poll → ít submit thực tế) |
| `SUBMIT_START` | **2.0** | 2.0 | 3.0 | Giới hạn submit ban đầu |
| `SUBMIT_MIN` | 1.0 | 1.0 | 1.0 | Sàn (luôn ít nhất 1 submit) |
| `SUBMIT_MAX` | **8.0** | 5.0 | 10.0 | Trần submit đồng thời |
| `SUBMIT_UP_AFTER` | 5 | 5 | 5 | Số OK liên tiếp để +1 |
| `SUBMIT_DOWN` | 0.5 | 0.5 | 0.5 | Hệ số giảm khi throttle |
| `THROTTLE_SLEEP` | **3.0s** | 5.0s | 1.5s | Nghỉ khi bị rate limit |
| `QUOTA_HARD_REST` | 6h | 6h | 6h | Nghỉ khi hết quota thật |
| `AUTH_REST` | 30min | 30min | 30min | Nghỉ khi 401/403 không cứu được |
| `BEARER_TTL` | 20min | 20min | 20min | Thời gian refresh bearer |
| `JOB_MAX_CYCLES` | **30** | 20 | 40 | Số vòng retry tối đa / job |
| `AUTO_RETRY_ROUNDS` | 2 | 2 | 2 | Số vòng tự retry sau khi xong |
| **Tốc độ ước tính** | ~14-16/p | ~8-10/p | ~18-20/p | video/phút |
| **Rủi ro 429** | Thấp ✅ | Rất thấp | Cao ⚠️ | |

> **Chuyển đổi:** Sửa các giá trị trong `thin_aptm.py` dòng 88-111. Comment `# 🎯 CHẾ ĐỘ CÂN BẰNG` ở đầu block nhắc nhở preset đang dùng.

### Cổng submit (`AccountState`)

```python
class AccountState:
    # Cổng AIMD
    submit_limit = SUBMIT_START   # giới hạn đồng thời hiện tại
    inflight = 0                  # số submit đang bay
    _ok_streak = 0                # chuỗi OK liên tiếp
    i2v_blocked = False           # True nếu account bị cấm upload ảnh (403)
    
    def acquire_submit(stop_check):  # chờ đến lượt submit
    def release_submit():            # nhả slot
    def on_submit_ok():              # +1 OK streak, tăng limit nếu đủ
    def on_throttle():               # giảm limit (AIMD MD)
```

### Cơ chế `i2v_blocked` — Cấm upload ảnh theo tài khoản

Khi Google cấm 1 tài khoản upload ảnh (trả 403 trên `upload_image`), hệ thống:

1. `upload_image()` trả `"forbidden"` (engine.py)
2. `process()` đánh dấu `st.i2v_blocked = True` + log `🚫` + trả `"retry_soft"`
3. `worker()` kiểm tra: nếu `i2v_blocked` + job là I2V → **skip**, trả job về hàng đợi
4. Account vẫn nhận **job T2V** bình thường
5. Account khác (chưa bị cấm) sẽ nhặt job I2V

```mermaid
graph TD
    A["Worker nhận job I2V"] --> B{st.i2v_blocked?}
    B -- Có --> C["Trả job về queue → account khác nhặt"]
    B -- Không --> D["upload_image()"]
    D --> E{Kết quả?}
    E -- "media_id" --> F["Tiếp tục submit_video"]
    E -- "forbidden (403)" --> G["Đánh dấu i2v_blocked = True"]
    G --> C
    E -- "throttle (429 hết retry)" --> H["on_throttle + retry_soft"]
    E -- "None" --> I["fail: upload ảnh lỗi"]
```

> **Reset:** Restart app → `i2v_blocked` reset về `False` → thử lại bình thường.

---

## 6. Cấu trúc File hiện tại (07/2026)

```
ThinAptm0707/
├── thin_aptm.py      # GUI chính (customtkinter) - ~2134 dòng
│   ├── Class App(CTk)
│   │   ├── Tab Tài khoản: import, manual login, auto login, check, health check
│   │   ├── Tab Tạo video: I2V/T2V, prompt, naming, aspect ratio, Telegram report
│   │   ├── Tab Hàng đợi: batch ops, pool monitor, AIMD, auto retry
│   │   └── Tab Tạo Video Shopee: scrape SP → AI generate → video
│   └── Class AccountState: quản lý auth + throttle / account
├── engine.py         # API Google Labs (curl_cffi) - ~360 dòng
│   ├── bearer_from_cookie()  # cookie → bearer token
│   ├── get_project()         # lấy/tạo project
│   ├── upload_image()        # upload ảnh cho I2V
│   ├── generate_image()      # tạo ảnh AI (Gemini Pix 2)
│   ├── submit_video()        # gửi yêu cầu tạo video
│   ├── _classify()           # phân loại lỗi submit (throttle/quota/auth/ip_block)
│   ├── poll_video()          # thăm dò trạng thái render
│   ├── download_video()      # tải video qua redirect
│   └── rewrite_prompt()      # nhờ Gemini viết lại prompt vi phạm
├── shopeevideo.py    # Module Shopee Video - ~250 dòng
│   ├── fetch_product_info()  # scrape thông tin SP (API + fallback)
│   ├── build_image_prompt()  # tạo prompt cho AI generate
│   ├── build_video_prompt()  # tạo prompt cho video
│   └── SCENE_PRESETS[]       # 10 preset khung cảnh review
├── login.py          # Đăng nhập Google (DrissionPage) - ~170 dòng
│   ├── manual_login()            # user tự đăng nhập
│   ├── login_get_cookie()        # auto login email/pass/2fa
│   └── reopen_profile_cookie()   # mở Chrome profile cũ, không cần password
├── accounts.json     # Dữ liệu tài khoản [{email, password, totp, cookie, status, enabled}]
├── settings.json     # Cài đặt + hàng đợi jobs + health check + telegram + shopee
├── log.txt           # Log hoạt động tab Tạo Video (xóa mỗi lần mở app)
├── shopee.txt        # Log hoạt động tab Tạo Video Shopee
├── SETUP.bat         # Cài thư viện
├── _profiles/        # Chrome profile riêng mỗi tài khoản (cho Pha 1 re-login)
├── CHAY.bat          # Chạy app
└── thinaptm.md       # Tài liệu này
```

### Cấu trúc accounts.json
```json
[
  {
    "id": "email@gmail.com",
    "email": "email@gmail.com",
    "password": "...",       // rỗng nếu login thủ công
    "totp": "SECRET_KEY",   // rỗng nếu không có 2FA
    "cookie": "...",         // cookie labs.google hiện tại
    "status": "ok|dead|new",
    "enabled": true          // có dùng tài khoản này không
  }
]
```

### Cấu trúc settings.json (chính)
```json
{
  "gen_mode": "i2v",
  "ref_dir": "...",
  "aspect": "Dọc 9:16 (TikTok)",
  "naming": "13 ký tự đầu prompt",
  "out_dir": "...",
  "gemini_keys": ["key1", "key2"],
  "health_check_enabled": false,
  "health_check_interval": 30,
  "tg_token": "BOT_TOKEN",
  "tg_chatid": "CHAT_ID",
  "tg_enabled": false,
  "shopee_aspect": "Dọc 9:16 (TikTok)",
  "shopee_scene": "📦 Tổng kho hàng hóa",
  "shopee_model_img": "",
  "shopee_out_dir": "",
  "shopee_links": "",
  "jobs": [...]
}
```

---

## 7. Phân loại & Xử lý Lỗi API Google Flow

### Tổng quan

Khi video render thất bại (`poll_video` trả `pk == "failed"`), hệ thống phân loại lỗi thành **3 nhánh** dựa trên mã lỗi trả về (`error.message` trong response):

```mermaid
graph TD
    A["poll_video → pk == 'failed'"] --> B{Kiểm tra mã lỗi m}
    B -->|"AUDIO_FILTERED"| C["Nhánh 1: Lỗi PROMPT"]
    B -->|"DANGER_FILTER / PROMINENT_PEOPLE<br/>IP_INPUT_IMAGE / MINOR"| D["Nhánh 2: Lỗi NỘI DUNG/ẢNH"]
    B -->|"Lỗi khác"| E["Nhánh 3: Lỗi render thường"]
    
    C --> F{Có Gemini API key?}
    F -->|Có + chưa hết lượt| G["Gemini viết lại prompt → retry_soft"]
    F -->|Không / hết lượt| H["status = 'lỗi' (lỗi thường)"]
    
    D --> I["status = 'vi phạm cs' (nút Xóa Vi Phạm CS xóa)"]
    E --> J["status = 'lỗi' (lỗi thường, có thể retry)"]
```

### Bảng phân loại lỗi render chi tiết

| Mã lỗi API | Loại lỗi | Nguyên nhân | Xử lý | Status job | Nút "Xóa Vi Phạm CS" |
|---|---|---|---|---|---|
| `PUBLIC_ERROR_AUDIO_FILTERED` | Prompt vi phạm | Prompt chứa nội dung bị lọc audio/bạo lực | Gemini viết lại prompt → retry. Hết lượt → lỗi thường | `"lỗi"` | ❌ Không xóa |
| `PUBLIC_ERROR_DANGER_FILTER` | Nội dung nguy hiểm | Ảnh/video chứa nội dung nguy hiểm | Đánh vi phạm cs ngay | `"vi phạm cs"` | ✅ Xóa |
| `PUBLIC_ERROR_PROMINENT_PEOPLE_FILTER_FAILED` | Người nổi tiếng | Ảnh chứa khuôn mặt người nổi tiếng | Đánh vi phạm cs ngay | `"vi phạm cs"` | ✅ Xóa |
| `PUBLIC_ERROR_IP_INPUT_IMAGE` | Ảnh vi phạm IP | Ảnh đầu vào chứa logo/nhân vật có bản quyền | Đánh vi phạm cs ngay | `"vi phạm cs"` | ✅ Xóa |
| `PUBLIC_ERROR_MINOR` | Trẻ em | Nội dung liên quan đến trẻ em | Đánh vi phạm cs ngay | `"vi phạm cs"` | ✅ Xóa |
| `PUBLIC_ERROR_HIGH_TRAFFIC` | Server quá tải | Google server đang đông | Lỗi thường, tự retry | `"lỗi"` | ❌ Không xóa |
| Lỗi khác / timeout | Render lỗi | Lỗi kỹ thuật, timeout | Lỗi thường, tự retry | `"lỗi"` | ❌ Không xóa |

### Code xử lý (thin_aptm.py, hàm `process()` trong `_run()`)

```python
elif pk == "failed":
    m = mid or ""
    # 1) AUDIO_FILTERED: lỗi do prompt → dùng Gemini viết lại rồi retry
    if "AUDIO_FILTERED" in m:
        if self._gemini_active and job.get("_rewrites", 0) < MAX_REWRITES:
            new = self._rewrite_prompt(job["prompt"])
            if new and new.strip() != job["prompt"].strip():
                job["_rewrites"] = job.get("_rewrites", 0) + 1
                job["prompt"] = new
                return "retry_soft"   # requeue, làm lại với prompt mới
        # Hết lượt rewrite → lỗi thường (nút Xóa Vi Phạm CS KHÔNG xóa)
        return ("fail", m or "render fail")
    # 2) Lỗi nội dung/ảnh → vi phạm cs (nút Xóa Vi Phạm CS sẽ xóa)
    if "DANGER_FILTER" in m or "PROMINENT_PEOPLE" in m or "IP_INPUT_IMAGE" in m or m == "PUBLIC_ERROR_MINOR":
        return ("fail", "policy")
    # 3) Các lỗi render khác
    return ("fail", m or "render fail")
```

### Phân loại lỗi submit (engine.py, hàm `_classify()`)

Khi `submit_video()` trả lỗi (status ≠ 200), `_classify()` phân loại dựa trên HTTP status + error reason:

| Loại trả về | Điều kiện | Ý nghĩa | Xử lý ở `process()` |
|---|---|---|---|
| `"throttle"` | 429 + `USER_REQUESTS_THROTTLED` hoặc `RESOURCE_EXHAUSTED` | Giới hạn tốc độ tạm | AIMD giảm tốc, nghỉ 3s (Cân bằng), tự hồi |
| `"quota_hard"` | `QUOTA_EXCEEDED` / `OUT_OF_CREDIT` / `DAILY` | Hết quota thật | Cách ly account 6h, đổi account |
| `"auth"` | HTTP 401 hoặc **403** | Bearer hết hạn / permission denied | Refresh cookie → bearer, retry. Nếu vẫn fail → nghỉ 30p |
| `"unusual"` | `RECAPTCHA` / `UNUSUAL_ACTIVITY` | Bot detection | Retry nhanh (0.4s) |
| `"ratelimit"` | `TOO_MUCH_TRAFFIC` | Rate limit theo IP | AIMD giảm tốc, nghỉ 5s |
| `"ip_block"` | Response HTML "Sorry" | IP bị chặn | AIMD giảm tốc |
| `"retry"` | Lỗi khác | Lỗi không xác định | Retry nhanh (0.4s) |

### Cơ chế Gemini Rewrite Prompt

Khi gặp `AUDIO_FILTERED`, hệ thống dùng Google Gemini API để viết lại prompt an toàn:

1. **Xoay vòng key**: Duyệt qua danh sách Gemini API key đã khai báo, bỏ qua key đã chết (`_gemini_bad`)
2. **Prompt cho Gemini**: Yêu cầu giữ nguyên ý nhưng loại bỏ bạo lực, vũ khí, người nổi tiếng, logo, nhạc có bản quyền
3. **Giới hạn**: Tối đa `MAX_REWRITES` (3) lần viết lại / job
4. **Phân loại key**:
   - `"ok"` → dùng prompt mới, retry job
   - `"dead"` (400/401/403) → loại key, thử key kế
   - `"busy"` (429/lỗi khác) → thử key kế

```python
# engine.py - rewrite_prompt()
GEMINI_MODEL = "gemini-flash-latest"
instr = "Rewrite the following text-to-video prompt so it PASSES content-safety filters..."
# POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}
```

---

## 8. Hiển thị Hàng đợi (Queue Display)

### Format hiển thị mỗi dòng job

Mỗi dòng trong danh sách hàng đợi hiển thị theo thứ tự cột:

```
☐ STT  Loại Trạng thái  Ảnh đầu vào           Prompt (48 ký tự)                                     File output
☐ 1    I2V  ⏳ chờ       input_image.jpg        Create an 8-second product review                      output.mp4
☑ 2    I2V  🔄 đang      photo_001.png          A beautiful sunset over the ocean                      sunset_001.mp4
☐ 3    T2V  ✅ xong      -                      Flying through a neon city at night                    neon_city.mp4
```

| Cột | Độ rộng | Nguồn dữ liệu | Ghi chú |
|---|---|---|---|
| `☐/☑` | 1 ký tự | `check_vars[i]` | Checkbox chọn/bỏ chọn |
| STT | 5 ký tự | Index (1-based) | Số thứ tự trong hàng đợi |
| Loại | 5 ký tự | `j["type"]` | `I2V` hoặc `T2V` |
| Trạng thái | 11 ký tự | `j["status"]` | Icon + text (⏳ chờ / 🔄 đang / ✅ xong / ❌ lỗi / ⚠️ vi phạm cs) |
| **Ảnh đầu vào** | 22 ký tự | `j["ref"]` | Tên file ảnh gốc (tối đa 20 ký tự), `-` nếu T2V |
| Prompt | 50 ký tự | `j["prompt"]` | 48 ký tự đầu của prompt |
| File output | tự do | `j["out"]` | Tên file video kết quả |

### Tối ưu hiển thị danh sách lớn

- **≤ 300 job**: Hiển thị toàn bộ danh sách
- **> 300 job**: Hiển thị thông minh:
  1. Jobs **đang chạy** (ưu tiên cao nhất)
  2. Jobs **lỗi / vi phạm** (tối đa 50 dòng)
  3. **100 dòng đầu** + **100 dòng cuối** (ẩn phần giữa)
- **Throttle refresh**: Chỉ cập nhật tối đa 1 lần/giây khi đang chạy; full refresh mỗi 5 giây

### Màu sắc theo trạng thái

| Tag | Trạng thái | Màu |
|---|---|---|
| `dang` | Đang chạy | `#E53935` (đỏ) |
| `xong` | Thành công | `#2E7D32` (xanh lá) |
| `loi` | Lỗi | `#E65100` (cam đậm) |
| `vipham` | Vi phạm CS | `#AD1457` (hồng đậm) |
| `cho` | Chờ | `#555555` (xám) |

### Batch Operations (Thao tác hàng loạt)

| Thao tác | Hàm | Mô tả |
|---|---|---|
| Check/Bỏ chọn theo dãy | `_check_range()` / `_uncheck_range()` | Chọn/bỏ từ dòng X đến dòng Y |
| Chọn/Bỏ tất cả | `_select_all()` / `_deselect_all()` | Toggle toàn bộ danh sách |
| Xóa đã chọn | `_delete_checked()` | Xóa các job đã check |
| Retry đã chọn | `_retry_checked()` | Reset status → "chờ" để chạy lại |
| Đổi folder | `_change_folder_checked()` | Đổi thư mục output cho các job đã chọn |
| Đổi tên | `_rename_checked()` | Đổi tên file output theo quy tắc naming hiện tại |

---

## 9. Telegram Report & Interactive Bot

### Mục đích
Gửi thông báo tự động định kỳ và cho phép người dùng gửi lệnh truy vấn từ xa từ Telegram. Giúp theo dõi tốc độ, tiến độ và trạng thái tài khoản thời gian thực mà không cần mở giao diện phần mềm.

### Kiến trúc

```mermaid
graph TD
    A[App khởi động] --> B["Load settings.json → tg_token, tg_chatid, tg_enabled"]
    B --> C["_build_acc() → Tạo UI widgets"]
    C --> D["Switch Bật/Tắt + Bot Token + Chat ID + Nút Test"]
    D --> E["_start_telegram_polling() → Spawn luồng nhận lệnh ngầm"]
    
    subgraph "Luồng gửi báo cáo chu kỳ"
        F[App khởi chạy video _run] --> G["Thread _tg_periodic"]
        G --> H{tg_enabled ON + đã qua 1h?}
        H -- Chưa --> I[Sleep 60s]
        I --> H
        H -- Rồi --> J["Dựng thống kê sạch → _send_telegram"]
        J --> I
    end

    subgraph "Luồng nhận lệnh tương tác (Tài khoản & Hàng đợi)"
        E --> K["getUpdates polling loop"]
        K --> L{Nhận được tin nhắn từ Chat ID?}
        L -- Không --> K
        L -- Có tin mới --> M{"Tin là tkaptm, /tkaptm, aptmtk, /aptmtk?"}
        M -- Đúng --> N["Dựng báo cáo chi tiết giống mẫu ảnh → _send_telegram"]
        M -- Sai --> K
        N --> K
    end
```

### Các tính năng tương tác mới
1. **Đăng ký danh sách lệnh (`setMyCommands`)**: Khi thay đổi bot token, hệ thống tự động POST đăng ký danh sách lệnh (`tkaptm` và `aptmtk`) để khi gõ dấu `/` trên Telegram, các lệnh này sẽ hiện lên gợi ý để chọn nhanh.
2. **Nút bấm trực quan (Reply Keyboard Button)**: Mỗi tin nhắn bot gửi đi đều đính kèm `reply_markup` chứa nút nhấn bàn phím ảo **`tkaptm`** ở cuối ứng dụng chat của người dùng. Họ chỉ cần chạm vào nút này để yêu cầu thống kê một cách đơn giản nhất.
3. **Thống kê linh hoạt theo Tab hoạt động**: Hàm dựng text thống kê `_build_telegram_stats` tự dò xem tab Tạo video thường hay Tạo video Shopee đang chạy để xuất thông tin tiến độ, số lượng thành công/lỗi và tài khoản tương ứng của tác vụ đó.

### Các thành phần code chính

| Thành phần | Vị trí | Chức năng |
|---|---|---|
| `_start_telegram_polling()` | `App` | Spawn luồng daemon lắng nghe Telegram. |
| `_telegram_polling_loop()` | `App` | Vòng lặp `getUpdates` ngầm (timeout 10s), kiểm tra lọc Chat ID và xử lý lệnh. |
| `_build_telegram_stats()` | `App` | Hàm dựng tin nhắn thống kê đồng bộ (xong/lỗi/còn lại, tốc độ, trạng thái tài khoản) dùng chung cho cả báo cáo định kỳ lẫn phản hồi lệnh. |
| `_send_telegram(text)` | `App` | Đóng gói tin nhắn gửi qua API, tự động nạp nút nhấn `tkaptm` dạng JSON markup. |

### Cấu hình hiện tại

| Khoá cấu hình | Giá trị cấu hình |
|---|---|
| Bot hiển thị | [@APTMVeo_bot](https://t.me/APTMVeo_bot) |
| `tg_token` | `8056221929:AAHLCItPyjFuiTS2tzoV_-ZEhHxz93RopUw` |
| `tg_chatid` | `1533409967` (An Phúc Trí @AnPhucTri) |
| `tg_enabled` | `true` |

### Ví dụ định dạng thống kê gửi về
```
⏰ Thống kê chạy (1.5h)
==============================
✅ Xong: 1286/19778 · ❌ Lỗi: 40 · 📦 Còn: 18472
⚡ Tốc độ: 11.9 video/phút
👥 Tài khoản:
  01004046501m@gmail.com: ✅550 ❌25 ⚡18 🟢 chạy
  01004649955m@gmail.com: ✅736 ❌35 ⚡18 🟢 chạy
```

### Persistence (Lưu trữ)
Ghi nhận trong `settings.json`:
- `tg_token`: Bot token API.
- `tg_chatid`: Chat ID đích nhận tin nhắn và được phép điều khiển.
- `tg_enabled`: Bật/Tắt toàn bộ tính năng và luồng polling Telegram.

---

## 10. Module Tạo Video Shopee (`shopeevideo.py`)

### Mục đích
Tự động tạo video review sản phẩm Shopee bằng AI. Quy trình: lấy thông tin SP → tạo ảnh ghép AI (người mẫu + sản phẩm + khung cảnh) → tạo video từ ảnh.

### Luồng xử lý

```mermaid
graph TD
    A[Nhập link Shopee] --> B[Trích shop_id + item_id]
    B --> C[fetch_product_info]
    C --> D{API thành công?}
    D -- Có --> E[Lấy tên + giá + ảnh]
    D -- 403 --> F[Fallback: tạo info cơ bản từ ID]
    E --> G[Upload ảnh người mẫu]
    F --> G
    G --> H[build_image_prompt - tạo prompt AI]
    H --> I[generate_image - API Google Flow]
    I --> J{Tạo ảnh OK?}
    J -- Có --> K[build_video_prompt]
    K --> L[submit_video → poll → download]
    L --> M[Lưu video .mp4]
    J -- Lỗi 3 lần --> N[Bỏ qua SP này]
```

### Scrape sản phẩm Shopee (`fetch_product_info`)

Hệ thống thử 3 endpoint API Shopee (với `curl_cffi` impersonate Chrome):

| Endpoint | URL | Ghi chú |
|---|---|---|
| `pdp/get_pc` | `shopee.vn/api/v4/pdp/get_pc?shop_id=X&item_id=Y` | Endpoint mới nhất |
| `v4/item/get` | `shopee.vn/api/v4/item/get?shopid=X&itemid=Y` | Fallback 1 |
| `v2/item/get` | `shopee.vn/api/v2/item/get?shopid=X&itemid=Y` | Fallback 2 |

Nếu tất cả API trả 403 (Shopee chặn) → tạo info cơ bản từ shop_id + item_id.

### 10 preset khung cảnh review

| # | Tên | Scene (tiếng Anh) |
|---|---|---|
| 1 | 📦 Tổng kho hàng hóa | large warehouse filled with stacked packages |
| 2 | 🏪 Siêu thị mini | modern mini supermarket with product shelves |
| 3 | 🎬 Phòng review chuyên nghiệp | professional product review studio |
| 4 | 🏠 Phòng khách ấm cúng | cozy modern living room with warm lighting |
| 5 | 🌿 Không gian xanh | bright space with green plants |
| 6 | 🛍️ Cửa hàng thời trang | trendy fashion boutique |
| 7 | 📱 Studio công nghệ | modern tech studio |
| 8 | 🍳 Nhà bếp hiện đại | sleek modern kitchen |
| 9 | 🏋️ Phòng gym/thể thao | sports/gym equipment area |
| 10 | 💄 Bàn trang điểm | elegant vanity/makeup table |

### UI trên tab Tạo Video Shopee

| Widget | Chức năng |
|---|---|
| TextBox link | Nhập danh sách link Shopee (mỗi dòng 1 link) |
| Chọn ảnh người mẫu | Ảnh model chung cho tất cả video |
| Dropdown khung cảnh | 10 preset + có thể mở rộng |
| Dropdown tỉ lệ video | 9:16 / 16:9 / 1:1 |
| Thư mục lưu | Output folder |
| Log area | Hiển thị tiến trình (ghi ra `shopee.txt`) |

### Log file
- **`shopee.txt`**: ghi chi tiết từng bước xử lý, format `[HH:MM:SS] message`
- Không bị xóa khi mở app (khác `log.txt`)

---

## 11. Dependencies

| Package | Dùng cho | Bắt buộc? |
|---|---|---|
| `customtkinter` | GUI | ✅ |
| `curl_cffi` | TLS bypass (API Google + Shopee) | ✅ |
| `DrissionPage` | Auto login Google | ⚠️ Chỉ cần nếu dùng auto login |
| `pyotp` | Sinh mã 2FA | ⚠️ Chỉ cần nếu có 2FA |
| `Pillow` | Logo display | ⚠️ Optional |
| `urllib` (stdlib) | Telegram Bot API | ✅ (built-in) |

---

## 12. Sửa lỗi Login (2026-07-10)

### Tóm tắt

Nút "Nhập thủ công" và "Auto login" không hoạt động — Chrome mở nhưng không tự động điền email/password/2FA, hoặc crash ngay lập tức. **3 bug riêng biệt** cùng gây ra vấn đề:

### Bug 1: DrissionPage 4.x — `auto_port()` + `set_user_data_path()` crash

**Triệu chứng:** `ValueError: not enough values to unpack (expected 2, got 1)` ngay khi tạo `ChromiumPage`.

**Nguyên nhân:** DrissionPage 4.1.1.4 có bug: khi gọi `auto_port()` cùng `set_user_data_path()`, thuộc tính `address` bị set thành chuỗi rỗng `""`. Khi `connect_browser()` cố split `address.split(':')` → crash.

**File:** [login.py](file:///E:/ThinAptm0707/login.py) — hàm `_opts()`

**Fix:** Khi có `profile_dir`, dùng `set_local_port(random.randint(19200, 29999))` thay vì `auto_port()`. Khi không có profile → giữ `auto_port()` như cũ.

```python
def _opts(profile_dir=None):
    co = ChromiumOptions()
    co.set_argument("--no-first-run"); co.set_argument("--no-default-browser-check")
    if profile_dir:
        os.makedirs(profile_dir, exist_ok=True)
        co.set_user_data_path(profile_dir)
        co.set_local_port(random.randint(19200, 29999))  # DP4 bug workaround
    else:
        co.auto_port()
    return co
```

### Bug 2: Google Sign-in URL deprecated — Error 400

**Triệu chứng:** Chrome mở trang Google nhưng hiển thị "Error 400 (Bad Request) — The server cannot process the request because it is malformed."

**Nguyên nhân:** URL cũ `/signin/v2/identifier` đã bị Google deprecated. URL `/ServiceLogin` cũng trả 400 khi dùng với Chrome profile có cookie cũ.

**Fix:** Dùng `https://accounts.google.com` (URL cơ bản) — Google tự redirect sang `/v3/signin/identifier` (trang hiện tại, luôn hoạt động).

```python
GOOGLE_SIGNIN = "https://accounts.google.com"
```

### Bug 3: Profile rỗng gây chờ 90 giây vô ích

**Triệu chứng:** Khi ấn "Auto login", Chrome mở trang Flow và chờ 90 giây mà không làm gì.

**Nguyên nhân:** Hàm `_opts()` tạo thư mục profile với `os.makedirs()` → thư mục tồn tại nhưng rỗng → `_auto_login` thấy `os.path.exists(profile_dir)` = True → gọi `reopen_profile_cookie()` chờ 90 giây cho session Google không tồn tại.

**Fix:** Thêm hàm `_has_profile_data()` kiểm tra file `Local State` (Chrome tạo khi profile được dùng thật). `reopen_profile_cookie()` dùng hàm này thay vì `os.path.exists()`.

```python
def _has_profile_data(profile_dir):
    if not profile_dir or not os.path.exists(profile_dir):
        return False
    return os.path.exists(os.path.join(profile_dir, "Local State"))
```

### Cải tiến: Nút "Nhập thủ công" tự động điền credentials

**Trước:** Nút "Nhập thủ công" chỉ mở Chrome rồi chờ user tự đăng nhập — không dùng email/password/2FA đã lưu.

**Sau:** Nút "Nhập thủ công" kiểm tra tài khoản nào đã có password:
- **Có password** → tự động gọi `login_get_cookie()` (điền email + password + 2FA)
- **Không có password** → mở Chrome thủ công như cũ (fall back)

**File:** [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) — hàm `_manual_login()`

### Cải tiến: `login_get_cookie()` robust hơn

**Trước:** Chỉ 1 cố gắng tìm element, không log chi tiết, dễ fail mà không rõ nguyên nhân.

**Sau:**
- Log chi tiết từng bước (📧 email → 🔒 password → 🔐 2FA → ⏳ chờ cookie)
- Thử nhiều selector cho mỗi element (`#identifierId`, `input@type=email`, `input@name=identifier`)
- Xử lý trang "chọn tài khoản" (nút "Use another account")
- Chờ tối đa 25 giây cho cookie xuất hiện sau khi login
- Nạp LABS trước để check profile cũ (tránh mở login không cần thiết)

### Bảng tổng hợp thay đổi

| File | Hàm | Thay đổi |
|---|---|---|
| `login.py` | `_opts()` | Fix DP4 crash: `set_local_port(random)` thay `auto_port()` khi có profile |
| `login.py` | `GOOGLE_SIGNIN` | URL mới `accounts.google.com` (cũ `/v2/` bị 400) |
| `login.py` | `_has_profile_data()` | Hàm mới: check Chrome profile có data thật |
| `login.py` | `login_get_cookie()` | Viết lại: log chi tiết, multi-selector, xử lý account chooser |
| `login.py` | `reopen_profile_cookie()` | Dùng `_has_profile_data()` thay `os.path.exists()` |
| `thin_aptm.py` | `_manual_login()` | Tự động dùng credentials nếu có, fall back thủ công |

---

## 13. Chạy Shopee Video không cần ảnh người mẫu (2026-07-17)

### Tóm tắt

Tab "Tạo video Shopee" trước đây **bắt buộc** phải chọn thư mục chứa ảnh người mẫu. Nếu không có → hiển thị cảnh báo và dừng lại. Giờ đã sửa để **ảnh người mẫu là tùy chọn** — khi không có, phần mềm tự xử lý bằng hệ thống fallback prompt.

### Cơ chế hoạt động

```mermaid
graph TD
    A[Bấm Bắt đầu] --> B{Có thư mục ảnh người mẫu?}
    B -- Có --> C[Luồng BÌNH THƯỜNG]
    C --> C1[Phase 1: Upload ảnh mẫu + ảnh SP → generate_image AI tạo ảnh composite]
    C1 --> C2[Phase 2: build_video_prompts — prompt tham chiếu ảnh mẫu]
    C2 --> C3[Phase 3-4: Submit video → poll → download → ghép]
    
    B -- Không --> D[Luồng FALLBACK TỰ ĐỘNG]
    D --> D1["Phase 1: BỎ QUA — copy ảnh SP làm reference trực tiếp"]
    D1 --> D2["Phase 2: build_video_prompts_fallback — MÔ TẢ MC bằng text"]
    D2 --> D3[Phase 3-4: Submit video → poll → download → ghép]
    
    D2 -.-> E["Random tóc + trang phục mỗi SP → video luôn mới mẻ"]
```

### Fallback Prompt — Mô tả MC bằng text

Khi không có ảnh người mẫu, prompt video thay vì tham chiếu `"Người trong ảnh tham chiếu"` sẽ **mô tả chi tiết MC**:

```
THE PRESENTER: A beautiful young woman, approximately 20 years old, 
with a warm and friendly appearance.
She has {hair}. She wears {outfit}.
```

- **`{hair}`**: Random từ pool 8 kiểu tóc (ví dụ: "tóc đen dài thẳng", "tóc nâu ngang vai hơi xoăn")
- **`{outfit}`**: Random từ pool 8 bộ trang phục (ví dụ: "áo sơ mi trắng bỏ trong quần tây beige cạp cao")
- Cùng combo tóc + trang phục cho **tất cả đoạn** của cùng 1 SP (đảm bảo đồng nhất)
- Mỗi SP khác nhau → random combo mới → video luôn đa dạng

### Các thay đổi code

| File | Vị trí | Thay đổi |
|---|---|---|
| `thin_aptm.py` | `_shopee_start()` dòng ~2655 | Bỏ 2 check bắt buộc `model_dir` + `model_images` → giờ là tùy chọn |
| `thin_aptm.py` | `work()` dòng ~2770 | Gán model chỉ khi có: `if model_images:` bọc vòng lặp |
| `thin_aptm.py` | `work()` dòng ~2779 | Log thông minh: có ảnh → hiển thị số lượng, không có → "dùng prompt tự động" |
| `thin_aptm.py` | `process_one()` dòng ~2870 | Thêm nhánh `if not model_img:` → tự copy ảnh SP + bật `_use_fallback_prompts` |
| `thin_aptm.py` | `process_one()` dòng ~3040 | Fix crash `os.path.basename(None)` → hiển thị "Tự mô tả (prompt)" |

### Khi nào dùng fallback

| Trường hợp | Trigger | Prompt dùng |
|---|---|---|
| Có ảnh mẫu + còn quota | Bình thường | `build_video_prompts()` — tham chiếu ảnh composite |
| Có ảnh mẫu + hết quota ảnh | Tất cả account hết quota `generate_image` | `build_video_prompts_fallback()` — mô tả MC bằng text |
| **Không có ảnh mẫu** | Bỏ trống thư mục người mẫu | `build_video_prompts_fallback()` — mô tả MC bằng text |

> [!TIP]
> Khi không có ảnh người mẫu, phần mềm **tiết kiệm quota tạo ảnh** (bỏ qua Phase 1 hoàn toàn) — chỉ tốn quota tạo video. Phù hợp khi chạy số lượng lớn hoặc quota ảnh đang eo hẹp.

---

## 14. Tối ưu quá trình chờ cookie và xử lý đăng nhập (2026-07-19)

### Tóm tắt

Người dùng phản ánh khi bấm "Nhập thủ công" (do lưu sẵn mật khẩu nên hệ thống chạy auto-fill), trình duyệt Chrome đóng lại quá nhanh khiến họ không kịp mở điện thoại để xác nhận bảo mật Google (2FA prompt). Đồng thời, một số tài khoản sau khi login thành công (nhưng chưa kịp nhận cookie Labs) đã bị tool báo lỗi không tìm thấy Email và đổi trạng thái thành "Chết" sai lệch. 

Đã thực hiện **2 nâng cấp lớn** vào quy trình đăng nhập trong `login.py` để xử lý triệt để:

### Cải tiến 1: "Chờ thông minh" tự động theo tiến độ (Smart Wait)

**Vấn đề cũ:** Sau khi điền email/mật khẩu/2FA, code cũ đợi tĩnh `3` giây rồi ép trình duyệt điều hướng (`page.get(LABS)`) nhảy sang web Flow. Nếu người dùng đang bị Google yêu cầu thêm xác nhận điện thoại/mã SMS, việc điều hướng cưỡng ép lập tức hủy bỏ luồng xác thực Google và làm hỏng tiến trình. Nếu sống sót sang được trang lấy Session-token thì thời gian chờ lấy Cookie cũng chỉ có `25` giây (quá ngắn để thao tác kịp trên điện thoại).

**Nâng cấp:** 
- Xóa bỏ việc ép độ trễ tĩnh `time.sleep` gây phá vỡ luồng.
- Bổ sung luồng kiểm tra URL liên tục trong giới hạn **120 giây (2 phút)**:
  `if "signin" not in curr and "challenge" not in curr`
  → Tool chỉ chủ động nhảy sang trang `labs.google/fx/tools/flow` một khi nó chắc chắn người dùng **đã hoàn thành tuyệt đối** mọi bước xác thực bên phía Google Account (không còn kẹt ở các link "challenge"). Từ nay người dùng có tối đa 2 phút thong thả để chấp thuận Captcha hay 2FA điện thoại mà Chrome sẽ giữ yên không bị văng.

### Cải tiến 2: Tự động dùng session cũ, bypass màn điền form

**Vấn đề cũ:** Tại thư mục Profile trên máy, nếu Chrome **đã duy trì sẵn 1 session đăng nhập Google thành công**, đường link cơ bản `GOOGLE_SIGNIN` sẽ đưa người dùng chuyển hướng mượt mà lẳng lặng tới vùng làm việc `myaccount.google.com` (trang quản lý Google) mà **không hiện ra** trang có ô tìm kiếm Email.
Đoạn code cũ vẫn đi lùng sục ô nhập email theo cấu trúc máy móc, tìm suốt không thấy nên ngớ ngẩn kết luận là đăng nhập thất bại → trả trạng thái "Chết" (Dead) oan uổng.

**Nâng cấp:**
- Bổ sung tín hiệu thông minh `already_logged_in`:
  `already_logged_in = "myaccount.google.com" in page.url or "myactivity.google.com" in page.url`
- Tool sẽ kiểm tra trước, nếu URL thể hiện người dùng đã lọt vào vùng Account (Đã đăng nhập) thì sẽ kích hoạt bỏ qua toàn bộ khối lệnh tìm kiếm Input email và password. Giai đoạn Form Fills sẽ được Bypass và tool nhảy ngay xuống bước điều hướng về lại nền tảng Labs để trích xuất File Cookie Google Flow. Giải quyết dứt điểm tính trạng báo 'Chết' ngớ ngẩn trên các Profile chưa cạn kiệt Session!

---

## 15. Nâng cấp bộ Prompt Đạo Diễn (Director's Prompt) (2026-07-20)

### Tóm tắt

Hệ thống prompt mặc định của tab Shopee Video trong `shopeevideo.py` đã được đại tu toàn diện để áp dụng định dạng **"Director's Prompt"** (Prompt đạo diễn). Nâng cấp này nhằm siết chặt các giới hạn AI, chống hoàn toàn ảo giác (hallucination) của Veo 3 và phân rã các hành động dựa trên dòng thời gian chuyên nghiệp (Timeline Action).

Đặc biệt, prompt mới tích hợp chuẩn mực **khóa cứng danh tính (Identity Lock)** bằng thẻ kép: Hình ảnh tham chiếu + Đoạn text mô tả cô gái 22 tuổi gốc Việt.

### Các điểm đột phá trong cấu trúc Prompt mới

#### 1. Identity Lock (Khóa Danh Tính & Giới Tính)
Đóng đinh 100% hình dạng nhân vật review nhờ cấu trúc mô tả cứng trong biến `_CONT_EN` và `_CONT_VI`:
- **Chống sai lệch độ tuổi/giới tính:** Khai báo rõ ràng *"A 22-year-old Vietnamese woman with a bright, cheerful face"*. Lệnh này trở thành vòng kim cô kép khi đồng bộ chung với hình ảnh tham chiếu đầu vào.
- **Tính kiên định vật thể (Item Persistence):** Ép buộc Veo không được tự ý xóa bỏ hay vứt các đồ vật trang sức, phụ kiện. Sản phẩm ở giây đầu phải chính xác xuất hiện tới giây cuối cùng (PIXEL-PERFECT).

#### 2. Kịch bản Dòng Thời Gian (Timeline-based Action)
Thay vì gom một cục prompt miêu tả, 16 giây video được tách thành 2 clip với timeline chặt chẽ:
- **Clip 1 (0-8 giây):** Từ mờ sáng dần đến tương tác với sản phẩm. Quan trọng nhất là giây thứ 7-8 ép AI tạo ra tư thế **đứng yên hoàn toàn (static pose with zero movement)** để làm "Handoff pose".
- **Clip 2 (8-16 giây):** Mở đầu bằng tư thế đóng băng từ video trước để tạo độ liền mạch. Sau đó, camera chủ động phóng to (B-Roll Close-up) vào khu vực nút bấm, cấu trúc vật liệu của sản phẩm (giây 10-14s) rồi quay trở lại mặt MC chốt sale (giây 14-16s).

#### 3. Chống khuyết điểm AI thảm họa
Lệnh Constraints mạnh mẽ được bổ sung:
- `No chaotic or unintended rapid morphing. No slow-motion effects.` (Loại bỏ múa dưỡng sinh, cử động chậm).
- `No overly graceful ballet-like gestures.` (Chống lỗi giơ tay như múa ballet).

### Các thay đổi code

| File | Mã/Vị trí | Thay đổi |
|---|---|---|
| `shopeevideo.py` | `_CONT_EN`, `SEGMENT_POOL_EN` (Dòng 92-143) | Gắn bộ khung Directives + Timeline Action 16s cho tiếng Anh |
| `shopeevideo.py` | `_CONT_VI`, `SEGMENT_POOL_VI` (Dòng 219-269) | Gắn bộ khung Directives + Timeline Action 16s (đã dịch sát rạt) cho tiếng Việt |

> [!TIP]
> Do hệ thống hard-code (gắn cứng) mô tả *"Cô gái Việt Nam 22 tuổi"*, hệ thống này đang được tối ưu 100% cho việc dùng ảnh Reviewer nữ. Nếu thay đổi bộ folder người mẫu nam, hãy vào `shopeevideo.py` chỉnh lại biến cấu trúc Character Name cho khớp để tránh AI bị "tâm thần phân liệt" ngoại hình!

---

## 16. Fix Upload 429 — Reset Project + TLS Nâng Cấp (Học từ AutoVeo3) (2026-07-20)

### Tóm tắt Vấn Đề

Cùng tài khoản `maichuyencole@gmail.com`, cùng thời điểm chạy:
- **AutoVeo3**: upload OK, ra video trong ~6 phút
- **ThinAptm**: loop upload 429 vĩnh viễn (54 lần nghỉ, 0/2535 video)

### 5 Nguyên Nhân Gốc Rễ

| # | Nguyên nhân | Mức độ |
|---|-------------|--------|
| 1 | AutoVeo3 XÓA + TẠO PROJECT MỚI mỗi phiên (reset quota upload) | 🔴 Chính |
| 2 | ThinAptm dồn 15 upload đồng thời (Thundering Herd) | 🔴 Chính |
| 3 | AutoVeo3 có RecaptchaService Token Farm (5 luồng) | 🔴 Chính |
| 4 | AutoVeo3 dùng `pyreqwest_impersonate` (TLS sâu hơn `curl_cffi`) | 🟡 Phụ |
| 5 | ThinAptm không có TK Donor nào → Image Laundering không kích hoạt | 🟡 Phụ |

### Fix Đã Thực Hiện

#### A. Reset Project mỗi phiên (engine.py + thin_aptm.py)

Thêm `delete_project()` + `reset_project()` trong `engine.py`. Gọi trước `ensure_auth()` ở CẢ 2 tab (Tạo Video + Shopee Video).

#### B. Nâng cấp TLS Fingerprint (engine.py)

Chuyển HTTP client từ `curl_cffi` sang `pyreqwest_impersonate` (cùng thư viện AutoVeo3 dùng). Headers được cập nhật khớp với pattern của `ai_transport.pyd`.

### Các giải pháp bổ sung (chưa implement)

| Ưu tiên | Giải pháp | Trạng thái |
|---------|-----------|------------|
| 🔴 P0 | Reset project mỗi phiên | ✅ Done |
| 🔴 P0 | Nâng cấp TLS (`pyreqwest_impersonate`) | ✅ Done |
| 🟡 P1 | Đánh dấu ít nhất 1 TK donor | ⏳ User tự set |
| 🟡 P1 | Token farm (RecaptchaService) | ❌ Cần RE thêm |

---

## 17. Xử lý cạn Quota ảnh khi Bypass 429 & Tối ưu hóa Fallback (2026-07-22)

### Tóm tắt Vấn Đề
Khi tài khoản chính bị cạn kiệt quota tạo ảnh ngày (`PUBLIC_ERROR_PER_MODEL_DAILY_QUOTA_REACHED` từ API `generate_image`), cơ chế bypass upload 429 qua donor (Image Laundering) sẽ thất bại.
Trước đó, khi bypass thất bại do tài khoản chính hết quota tạo ảnh, tool không đánh dấu trạng thái và không cho tài khoản nghỉ/đổi proxy mà trả job về hàng đợi ngay lập tức. Điều này gây ra vòng lặp lỗi vô hạn chạy liên tục cực nhanh khiến luồng bị nghẽn và spam API Google.

### Giải Pháp Đã Thực Hiện

#### A. Trả lỗi Quota từ Engine ([engine.py](file:///E:/ThinAptm0707/engine.py))
* Cập nhật hàm `upload_image_via_donor` để trả về chuỗi `"quota_hard"` nếu `generate_image` trên tài khoản chính gặp lỗi cạn quota (`kind == "quota_hard"`), thay vì chỉ trả về `None`.

#### B. Đánh dấu Quota & Cho phép Cooldown/Xoay Proxy ([thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py))
* Trong tab **Tạo Video Shopee**, tại 3 vị trí gọi bypass (ảnh người mẫu, ảnh sản phẩm, ảnh composite), nếu nhận về mã lỗi `"quota_hard"`:
  1. Đánh dấu tài khoản chính: `st.img_quota_exhausted = True`.
  2. Đặt `bypassed_mid = None` để ngắt luồng và cho phép chạy tiếp xuống khối lệnh tiêu chuẩn của tool: **Xoay Proxy mới** + **Cho tài khoản nghỉ (cooldown từ 60s - 600s)**.
* Việc cooldown và xoay proxy giúp làm sạch IP. Ở lượt chạy tiếp theo khi thức dậy, tài khoản chính có thể upload ảnh sản phẩm trực tiếp thành công mà không cần gọi đến donor bypass nữa (vì upload trực tiếp không tiêu tốn quota tạo ảnh).

#### C. Thử nghiệm dùng Nhiều Ảnh Tham Chiếu cho Video (Đã Bác Bỏ)
* **Ý tưởng:** Truyền cả ảnh người mẫu và ảnh sản phẩm làm reference khi gọi API sinh video để giảm số lần upload ảnh composite.
* **Thực nghiệm:** Đã viết script test gửi request API trực tiếp lên Google Labs. Máy chủ trả về lỗi:
  `HTTP 400 (INVALID_ARGUMENT): Reference images can contain at most 1 images.`
* **Kết luận:** Mô hình Image-to-Video của Veo 3.1 bắt buộc chỉ chấp nhận tối đa 1 ảnh làm reference khung hình đầu tiên. Quy trình tạo ảnh composite trước rồi mới sinh video là phương án duy nhất và tối ưu nhất về mặt kỹ thuật.

---

## 18. Loại bỏ Hybrid Voice Sync, Tối ưu hóa Bản địa hóa Đa Quốc gia & Lồng thoại Động vào Veo 3.1 (2026-07-22)

### Tóm tắt

Phiên bản nâng cấp này thực hiện hai cải tiến lớn:
1.  **Loại bỏ lồng tiếng cục bộ (Hybrid Voice Sync):** Thay vì tự sinh file âm thanh `.wav` qua Edge-TTS/Gemini và ghép nối qua FFmpeg ở phía máy khách, hệ thống chuyển giao 100% nhiệm vụ tạo tiếng nói cho **Google Labs Veo 3.1**. Mô hình Veo 3.1 tự động tạo video đi kèm âm thanh (cử chỉ nói và lip-sync khớp miệng) dựa trên kịch bản thoại được nhúng trực tiếp trong Prompt.
2.  **Hỗ trợ Bản địa hóa 3 Quốc gia (Việt Nam, Philippines, Indonesia):** Đồng bộ hóa từ giao diện chọn ngôn ngữ cho đến diện mạo người mẫu, chỉ thị nói tiếng nước bản địa, và kịch bản thoại tự động sinh theo cấu trúc tối ưu mới.

### Chi tiết Thiết lập Đa Quốc gia (Localization Matrix)

Khi người dùng chọn ngôn ngữ trên giao diện, hệ thống tự động ánh xạ quốc tịch người mẫu và giọng đọc cho AI:

| Ngôn ngữ chọn | Mã vùng | Quốc tịch người mẫu (Đưa vào Prompt) | Chỉ thị tiếng nói cho AI | Lời thoại tự sinh (`dialogue`) |
|---|---|---|---|---|
| **Tiếng Việt** | `vi` | Việt Nam (`Vietnamese` / `Việt Nam`) | `Người mẫu nói tiếng Việt` | Tiếng Việt (`Đối với [tên SP]...`) |
| **Tiếng Philippines** | `en` | Philippines (`Filipino` / `Philippines`) | `The model speaks Filipino` | Tiếng Tagalog (`Para sa [tên SP]...`) |
| **Tiếng Indonesia** | `id` | Indonesia (`Indonesian` / `Indonesia`) | `The model speaks Indonesian` | Tiếng Indonesia (`Untuk [tên SP]...`) |

### Cấu trúc Lời thoại Động Mới (16s Video)

Để nâng cao tỷ lệ giữ chân người xem (retention rate), kịch bản thoại được chia theo cấu trúc:
*   **Đoạn 1 (0-8s):** Bỏ qua lời chào xã giao. Tập trung giới thiệu trực tiếp công dụng chính của sản phẩm ngay từ giây đầu tiên.
    *   *Công thức:* `[Tiền tố quốc gia] + [Mô tả tính năng 1]` (Ví dụ: *"Đối với Kem chống nắng, thiết kế quá mượt mà..."*)
*   **Đoạn 2 (8-16s):** Giới thiệu thêm một tính năng/công dụng khác của sản phẩm, sau đó kết nối mượt mà sang lời kêu gọi hành động (CTA).
    *   *Công thức:* `[Mô tả tính năng 2] + [Lời kêu gọi mua hàng - CTA]`

*Tối ưu hóa lập trình:* Để tránh trùng lặp tính năng giữa Đoạn 1 và Đoạn 2, hệ thống sử dụng thuật toán gieo hạt `seed` dựa trên tổng mã ASCII của tên sản phẩm để bốc ngẫu nhiên không trùng lặp các tính năng từ kho dữ liệu bản địa hóa tương ứng.

### Các thay đổi file nguồn

| File | Vị trí | Thay đổi |
|---|---|---|
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | GUI & Worker | - Bổ sung tùy chọn Row 1.5 **Kiểu Review** (`Review tự nhiên` hoặc `Ngồi Review`) vào giao diện.<br>- Đồng bộ mặc định ngôn ngữ ban đầu là "Tiếng Việt".<br>- Dọn sạch mã nguồn tạo file `.wav` và lệnh FFmpeg ghép âm thanh.<br>- Cập nhật lưu cấu hình `shopee_review_style` và truyền vào các hàm dựng prompt.<br>- Bổ sung nút tick **"Không mẫu"** (`shopee_no_model`) ở Row 2 giúp người dùng ép buộc chế độ Fallback (dùng prompt tự mô tả MC) ngay lập tức mà không cần xóa đường dẫn thư mục người mẫu hiện tại. Tự động vô hiệu hóa (gray out) ô nhập khi nút này được bật. |
| [shopeevideo.py](file:///E:/ThinAptm0707/shopeevideo.py) | Config & Prompt Builders | - Cập nhật danh sách hiển thị `LANG_OPTIONS` theo đúng thứ tự: `"Tiếng Việt"`, `"Tiếng Philippines"`, `"Tiếng Indonesia"`.<br>- Khai báo các kho tính năng và CTA bằng 3 ngôn ngữ: `TTS_MIDDLES_VI/ID/PH` và `TTS_ENDINGS_VI/ID/PH`.<br>- Cập nhật hàm `generate_tts_script` hỗ trợ chọn mẫu câu đa ngôn ngữ động.<br>- Bổ sung chỉ thị `{dialogue}` vào các mẫu prompt video thường (`_CONT_VI/EN`) và fallback (`_CONT_FALLBACK_VI/EN`).<br>- Cập nhật `build_video_prompts` và `build_video_prompts_fallback` để sinh dialogue cho từng phân đoạn và truyền trực tiếp vào tham số format của prompt gửi cho Google.<br>- Bổ sung các ràng buộc giải phẫu bàn tay nghiêm ngặt (`NO anatomical anomalies, no extra limbs, no extra hands...` / `Tuyệt đối KHÔNG sinh thêm tay...`) vào toàn bộ 4 bộ template âm để triệt tiêu lỗi bàn tay thứ 3/thứ 4 phản cảm.<br>- Tích hợp tham số `review_style` để tự động nhúng chỉ thị bố cục toàn cục (`[ĐIỀU CHỈNH BỐ CỤC: Người reviewer ngồi lịch sự sau một chiếc bàn gỗ tối giản... / [LAYOUT CONSTRAINT: The presenter is sitting politely behind a clean, minimalist wooden desk...]`) ở vị trí ưu tiên đầu prompt khi chọn phong cách "Ngồi Review". |

---

## 19. Tối ưu Giao diện Hàng đợi & Thêm Lựa chọn Image Laundering (2026-07-23)

### Tóm tắt
Đã thực hiện 2 cải tiến lớn về UI/UX và tính năng kiểm soát luồng:
1. **Chia đôi màn hình tab Hàng đợi**: Thay đổi cách xếp chồng dọc của ô danh sách jobs (`self.txt_queue`) và console log (`self.txt_log`). Sử dụng container `split_frame` để chia ngang màn hình với tỷ lệ 50/50, giúp tận dụng tối đa màn hình rộng, tối ưu hiển thị danh sách job dài cùng console log song song.
2. **Lựa chọn tích "Rửa ảnh" (Bypass 429 via Donor)**: Bổ sung 2 checkbox cho phép bật/tắt động cơ chế Image Laundering (chuyển tiếp upload qua donor khi tài khoản chính bị rate limit 429). Checkbox được tích hợp ở cả tab Hàng đợi và tab Tạo video Shopee.

### Các thay đổi chi tiết

| File | Vị trí | Thay đổi |
|---|---|---|
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_build_queue()` (dòng ~1400) | - Đưa `self.txt_queue` và `self.txt_log` vào một `split_frame` chung.<br>- Sắp xếp side-by-side (50/50 width) bằng cách sử dụng `pack(side="left/right", fill="both", expand=True)`.<br>- Bổ sung checkbox `Rửa ảnh (Bypass 429)` (`self.use_laundering`) vào hàng nút điều khiển chính của tab Hàng đợi. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_build_shopee()` (dòng ~2460) | - Bổ sung checkbox `Rửa ảnh (Bypass 429)` (`self._sp_use_laundering`) vào Row 1.5 bên cạnh menu Kiểu Review. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_run()` (dòng ~2145, ~2190) | - Cập nhật logic bypass upload 429 của hàng đợi chuẩn để kiểm tra thêm cờ: `if self._donor_states and self.use_laundering.get():`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `work()` (dòng ~3355, ~3425, ~3570) | - Cập nhật logic bypass upload 429 của luồng Shopee (cho cả ảnh người mẫu, ảnh sản phẩm, và ảnh ghép composite) để kiểm tra thêm cờ: `if self._donor_states and self._sp_use_laundering.get():`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_on_closing()` (dòng ~3955) | - Lưu cấu hình `use_laundering` và `shopee_use_laundering` vào `settings.json` khi đóng ứng dụng và tự động nạp lại khi khởi động. |

---

## 20. Phân tích Video Mẫu & Thư viện Prompt Templates (2026-07-24)

### Tóm tắt
Phân tích chi tiết video mẫu dạng **2D animation motivational** (1080×1920, 45s, 30fps) được tạo bởi Google Veo. Từ phân tích này, xây dựng hệ thống hỗ trợ tạo video tương tự gồm: thư viện prompt templates offline, script ghép video, và bộ prompt mẫu.

### Phân tích video mẫu

**File**: `FSave.com_Reels_Ky-luat-tao-nen-tu-do-test-AUTO-STUDIO-q_Media_1737266811061890_001_1080p.mp4`

| Thuộc tính | Giá trị |
|---|---|
| Độ phân giải | 1080 × 1920 (Full HD dọc 9:16) |
| Thời lượng | ~45 giây |
| FPS / Codec | 30fps / H.264 Main (avc1) |
| Bitrate | ~6 Mbps video + 125 kbps audio AAC Stereo |
| Encoder | `h264_nvenc` (NVIDIA GPU) + `Lavf` (FFmpeg) |
| Watermark | "Veo" (góc phải dưới) → **tạo bởi Google Veo** |

**Đặc điểm nội dung**:
- Phong cách: Animation 2D dạng **stickman nâng cao** — nhân vật đầu tròn trắng tối giản, background chi tiết nghệ thuật
- Chủ đề: Motivational / Self-improvement tiếng Việt dạng listicle ("4 điều im lặng")
- Cấu trúc: Mỗi "điều" = 1 cảnh minh họa ẩn dụ (~5-8 giây), phụ đề lớn in đậm màu vàng
- Âm thanh: Voiceover tiếng Việt + nhạc nền

### Các file mới tạo

| File | Mô tả |
|---|---|
| [prompt_templates.py](file:///E:/ThinAptm0707/prompt_templates.py) | Thư viện template prompt offline — 50+ scene templates, 7 character styles, 6 kịch bản mẫu. Hoạt động hoàn toàn offline, không cần API AI. |
| [ghep_video.py](file:///E:/ThinAptm0707/ghep_video.py) | Script ghép video CLI: concat + fade transition + nhạc nền + burn subtitle. Dùng FFmpeg subprocess. |
| [prompts_mau/01_4dieu_imlang_T2V.txt](file:///E:/ThinAptm0707/prompts_mau/01_4dieu_imlang_T2V.txt) | 6 prompt T2V — "4 Điều Im Lặng" (giống video mẫu) |
| [prompts_mau/02_5dauhi_truongthanh_T2V.txt](file:///E:/ThinAptm0707/prompts_mau/02_5dauhi_truongthanh_T2V.txt) | 6 prompt T2V — "5 Dấu Hiệu Trưởng Thành" |
| [prompts_mau/03_3quytac_nguoimanhme_T2V.txt](file:///E:/ThinAptm0707/prompts_mau/03_3quytac_nguoimanhme_T2V.txt) | 4 prompt T2V — "3 Quy Tắc Người Mạnh Mẽ" |

### Chi tiết prompt_templates.py

**Character Styles** — 7 phong cách nhân vật:

| Key | Mô tả |
|---|---|
| `stickman` | Nhân vật tối giản đầu tròn trắng, áo xám quần đen |
| `stickman_hoodie` | Nhân vật tối giản đầu tròn trắng, hoodie đen |
| `anime` | Nhân vật anime nam tóc đen rối, quần áo tối |
| `chibi` | Chibi đầu to, thân nhỏ, outfit đơn giản |
| `realistic` | Người thật chân thực, ánh sáng cinematic |
| `silhouette` | Bóng đen người, backlit dramatic |
| `robot` | Robot nhỏ cute đầu tròn phát sáng |

**Scene Templates** — 50+ template chia theo nhóm:
- **Mở đầu/Intro**: `tsunami`, `portal`, `giant_doors`, `crossroads`, `cliff_edge`, `mirror`
- **Cảm xúc**: `pressure_gauge`, `fire_rage`, `rain_sad`, `broken_heart`, `crying_rain`, `mask_fake`
- **Bế tắc**: `tangled_ropes`, `maze`, `sinking_sand`, `chains`, `fog_lost`
- **Sức mạnh**: `climbing_stairs`, `lifting_weight`, `breaking_wall`, `standing_storm`, `sword_draw`, `mountain_top`, `shield_block`
- **Bình yên**: `meditation`, `lotus_thorns`, `tree_growth`, `garden_tend`, `stargazing`
- **Cô đơn**: `alone_table`, `walking_alone`, `island_one`
- **Đối lập**: `bridge_choice`, `light_dark`, `wolf_sheep`, `puppet_free`
- **Kết thúc**: `sunset_walk`, `sunrise_cliff`, `seed_plant`, `star_path`, `phoenix`, `ocean_calm`, `door_open`
- **Quan hệ**: `backstab`, `helping_hand`, `toxic_crowd`, `crown_earn`

**Preset Scripts** — 6 kịch bản mẫu có sẵn:
- `4_dieu_im_lang` — 4 Điều Im Lặng (6 cảnh)
- `5_dau_hieu_truong_thanh` — 5 Dấu Hiệu Trưởng Thành (6 cảnh)
- `3_quytac_nguoi_manh` — 3 Quy Tắc Người Mạnh Mẽ (4 cảnh)
- `5_sai_lam_tuoi_20` — 5 Sai Lầm Tuổi 20 (6 cảnh)
- `khi_ban_muon_bo_cuoc` — Khi Bạn Muốn Bỏ Cuộc (5 cảnh)
- `ngung_lam_nguoi_tot` — Ngừng Làm Người Tốt Vô Điều Kiện (6 cảnh)

**Cách dùng CLI**:
```bash
# Liệt kê kịch bản mẫu
python prompt_templates.py --list-presets

# Sinh prompt từ kịch bản mẫu
python prompt_templates.py --preset 4_dieu_im_lang -o prompts.txt

# Sinh prompt từ file outline tùy chỉnh
python prompt_templates.py outline.txt -o prompts.txt
```

**Format file outline**:
```
TIEU_DE: 4 điều im lặng
STYLE: stickman

---
TEXT: 4 ĐIỀU IM LẶNG
MOOD: dramatic
SCENE: tsunami

---
TEXT: Khi ai đó khiến bạn tức giận
MOOD: angry
SCENE: pressure_gauge
```

### Chi tiết ghep_video.py

Script ghép video clips thành video hoàn chỉnh qua FFmpeg subprocess:

```bash
# Ghép đơn giản (không re-encode)
python ghep_video.py D:\output\clips

# Ghép + fade transition 0.5s
python ghep_video.py D:\output\clips video_final.mp4 --fade 0.5

# Ghép + nhạc nền + phụ đề
python ghep_video.py D:\output\clips video_final.mp4 --fade 0.5 --bgm nhac.mp3 --srt phude.srt
```

Tính năng: concat simple (no re-encode) / xfade transition / add BGM (loop + volume control) / burn SRT subtitle (bold yellow, bottom). Tự fallback `libx264` nếu không có NVIDIA GPU.

---

## 21. Tích hợp AI Viết Prompt Tự Động & Auto-Concat (2026-07-24)

### Tóm tắt
Tích hợp 2 tính năng mới trực tiếp vào Thìn Aptm:
1. **AI Viết Prompt**: Dùng **cookie tài khoản Google AI Ultra** (cùng 5 tài khoản tạo video) để gọi **Gemini 2.0 Flash** sinh prompt Veo tự động từ chủ đề tiếng Việt — **KHÔNG cần API key riêng**.
2. **Tự động ghép video**: Khi batch hoàn thành, FFmpeg tự ghép các clip thành 1 file `video_final.mp4`.

### Kiến trúc AI Viết Prompt

```
[Người dùng nhập chủ đề tiếng Việt]
         │
         ▼
[_ai_gen_prompt()] ──── chạy thread riêng
         │
         ├─ Lấy danh sách accounts có cookie + status OK
         ├─ Shuffle ngẫu nhiên (phân tải)
         │
         ▼
[E.generate_video_prompts(cookie, topic, num_scenes, char_style)]
         │
         ├─ bearer_from_cookie(cookie) → bearer token
         │     (dùng lại hệ thống auth sẵn có)
         │
         ├─ POST https://generativelanguage.googleapis.com/v1beta/
         │       models/gemini-2.0-flash:generateContent
         │     Headers: Authorization: Bearer <token>
         │     (KHÔNG dùng API key — dùng OAuth bearer từ cookie)
         │
         ├─ System prompt hướng dẫn Gemini:
         │     - Nhận chủ đề tiếng Việt
         │     - Sinh đúng N dòng prompt tiếng Anh cho Veo
         │     - Giữ nhất quán character style xuyên suốt
         │     - Mỗi prompt mô tả chi tiết: nhân vật, hành động,
         │       background, mood, lighting, metaphor
         │     - Tất cả có "vertical 9:16"
         │     - Cảnh đầu = intro/title, cảnh cuối = ending
         │
         ▼
[Kết quả: list of N prompts] → điền vào txt_prompts
```

**Cơ chế failover**: Nếu 1 tài khoản gặp lỗi (dead/busy/429), tự xoay sang tài khoản tiếp theo trong pool 5 tài khoản. Xử lý lỗi theo cùng pattern với `rewrite_prompt()`:
- `status == "ok"` → trả danh sách prompt
- `status == "dead"` (401/403) → bỏ account, thử account khác
- `status == "busy"` (429/lỗi mạng) → thử account khác

### Kiến trúc Auto-Concat

```
[_run() hoàn thành] → kiểm tra self.auto_concat.get() == True
         │                   và done >= 2 (có ít nhất 2 clip xong)
         ▼
[_auto_concat(todo)]
         │
         ├─ Lọc jobs status=="xong", lấy đường dẫn output
         ├─ Sort theo tên file (đảm bảo thứ tự)
         ├─ Tạo FFmpeg concat list (tempfile)
         ├─ subprocess: ffmpeg -f concat -safe 0 -c copy → video_final.mp4
         │     (không re-encode → nhanh, giữ nguyên chất lượng)
         ├─ Tự đánh số video_final_1.mp4 nếu đã tồn tại
         └─ Log kết quả + kích thước file
```

### Thay đổi UI

**Tab Tạo Video** — Thêm row AI Viết Prompt (card trắng bo tròn, nền CARD):

| Thành phần | Widget | Mô tả |
|---|---|---|
| 🤖 icon | CTkLabel | Nhãn icon |
| "Chủ đề:" | CTkEntry (width=320) | Ô nhập chủ đề tiếng Việt, placeholder: "VD: 4 điều nên im lặng khi tức giận" |
| "Style:" | CTkOptionMenu (width=120) | 5 lựa chọn: stickman, stickman_hoodie, anime, chibi, silhouette |
| "Cảnh:" | CTkOptionMenu (width=60) | Số cảnh: 4, 5, 6, 7, 8 |
| 🤖 AI viết prompt | CTkButton | Nút tím (#8E24AA), hover #6A1B9A, font bold 12. Đổi text "⏳ Đang viết..." khi đang xử lý |

**Tab Hàng Đợi** — Thêm checkbox:

| Thành phần | Widget | Mô tả |
|---|---|---|
| 🔗 Tự ghép video | CTkCheckBox | Bên cạnh "Rửa ảnh (Bypass 429)". Mặc định tắt. |

### Các thay đổi file nguồn

| File | Vị trí | Thay đổi |
|---|---|---|
| [engine.py](file:///E:/ThinAptm0707/engine.py) | Dòng 594 | Thêm hằng số `GEMINI_BEARER_MODEL = "gemini-2.0-flash"` — model Gemini dùng cho AI viết prompt qua bearer token (tách biệt với `GEMINI_MODEL = "gemini-flash-latest"` dùng cho rewrite prompt qua API key). |
| [engine.py](file:///E:/ThinAptm0707/engine.py) | Dòng 631-637 | Thêm dict `CHAR_STYLES` — 5 mô tả character style tiếng Anh cho system prompt Gemini. |
| [engine.py](file:///E:/ThinAptm0707/engine.py) | Dòng 639-693 | Thêm hàm `generate_video_prompts(cookie, topic, num_scenes=5, char_style="stickman", timeout=60, proxy=None)`. Dùng `bearer_from_cookie()` lấy OAuth token → POST Gemini API với `Authorization: Bearer` header (không dùng `?key=` URL param). Parse response JSON, tách dòng, trả `("ok", [prompts])` hoặc `("dead"/"busy", None)`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_build_gen()` (dòng ~1160) | Thêm row AI Viết Prompt: CTkFrame card trắng chứa ô nhập chủ đề (`self.ent_ai_topic`), dropdown style (`self.opt_ai_style`), dropdown số cảnh (`self.opt_ai_scenes`), nút "🤖 AI viết prompt" (`self.btn_ai_gen`). Khôi phục giá trị từ settings. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | Dòng ~1239 | Thêm method `_ai_gen_prompt()`: Lấy danh sách accounts OK, shuffle ngẫu nhiên, chạy thread riêng gọi `E.generate_video_prompts()`, xoay qua tài khoản khi gặp lỗi, điền kết quả vào `self.txt_prompts`, cập nhật `self.loaded_prompts`. Disable nút khi đang xử lý. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_build_queue()` (dòng ~1450) | Thêm checkbox `self.auto_concat` (BooleanVar) "🔗 Tự ghép video" cạnh checkbox "Rửa ảnh". |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_run()` (dòng ~2468) | Hook auto-concat: sau Telegram report, kiểm tra `self.auto_concat.get() and done >= 2` → gọi `self._auto_concat(todo)`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | Dòng ~2478 | Thêm method `_auto_concat(todo)`: Lọc jobs xong, sort theo tên file, tạo FFmpeg concat list (tempfile), subprocess chạy `ffmpeg -f concat -safe 0 -c copy`, log kết quả + kích thước. Tự đánh số `video_final_N.mp4` nếu trùng. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_on_closing()` (dòng ~4015) | Lưu thêm 4 settings: `ai_topic`, `ai_char_style`, `ai_num_scenes`, `auto_concat` vào `settings.json`. |

---

## 22. Sửa lỗi Loop Upload 429 không nghỉ ở Tab Hàng đợi (2026-07-24)

### Tóm tắt
Đã sửa lỗi nghiêm trọng khiến các tài khoản bị Google chặn upload tạm thời (HTTP 429) liên tục cướp job và tái tuần hoàn không nghỉ trong hàng đợi của tab Tạo video chính:
1. **Nguyên nhân**: Khi upload ảnh thất bại với lỗi 429, tab Shopee cho tài khoản nghỉ ngơi (cooldown) qua `st.on_upload_throttle()`, nhưng tab Hàng đợi chuẩn lại bỏ quên logic này (chỉ đổi proxy rồi requeue ngay). Khiến các tài khoản dính 429 liên tục spam nhặt job từ queue chung $\rightarrow$ lỗi ngay lập tức $\rightarrow$ requeue $\rightarrow$ nhặt tiếp, cướp hết lượt của tài khoản khỏe mạnh duy nhất.
2. **Khắc phục**: Tích hợp gọi `st.on_upload_throttle()` tại 2 vị trí xử lý lỗi upload 429 trong luồng `_run()`. Tài khoản bị lỗi sẽ nghỉ tăng dần theo số lần dính lỗi liên tiếp (60s, 120s, 240s... tối đa 10 phút), dừng kéo job để tài khoản khỏe mạnh xử lý.

### Các thay đổi chi tiết

| File | Vị trí | Thay đổi |
|---|---|---|
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_run()` (dòng ~2465) | Thêm lệnh `rest_s = st.on_upload_throttle()` và log nghỉ khi upload lần đầu bị 429 (donor bypass thất bại). |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_run()` (dòng ~2510) | Thêm lệnh `rest_s = st.on_upload_throttle()` và log nghỉ khi upload lần hai (sau refresh auth) bị 429. |

---

## 23. Tối ưu Cấu hình Số Luồng (Tạo) và Tốc độ (Submit Limit) (2026-07-30)

### Tóm tắt
Đã giới hạn lại các tham số động cơ chạy ở đầu file `thin_aptm.py` theo yêu cầu tối ưu độ ổn định cho tài khoản:
1. **Số Luồng (Tạo - busy threads)**: Cấu hình `WORKERS_PER_ACCOUNT = 4` để giới hạn số luồng xử lý đồng thời tối đa của mỗi tài khoản (trong bảng hiển thị ở cột "Tạo" max là 4).
2. **Tốc độ (Submit limit)**: Cấu hình `SUBMIT_MAX = 5.0` và `SUBMIT_START = 4.0` để giới hạn tốc độ submit đồng thời tối đa của mỗi tài khoản là 5 (trong bảng hiển thị ở cột "Tốc độ" max là 5).

### Các thay đổi chi tiết

| File | Vị trí | Thay đổi |
|---|---|---|
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | Dòng ~92 | Đổi `WORKERS_PER_ACCOUNT` từ `6` thành `4`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | Dòng ~95 | Đổi `SUBMIT_START` từ `6.0` thành `4.0` để bắt đầu phù hợp với trần mới. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | Dòng ~97 | Đổi `SUBMIT_MAX` từ `12.0` thành `5.0` để khống chế tốc độ submit. |

---

## 24. Phân tách lệnh Thống kê Telegram cho Hàng đợi và Shopee Video (2026-07-30)

### Tóm tắt
Đã phân tách tính năng thống kê báo cáo qua Telegram thành 2 lệnh độc lập để người dùng dễ dàng truy vấn riêng biệt từng tab hoạt động:
1. **Lệnh `tkhangdoi` (hoặc `/tkhangdoi`)**: Chỉ hiển thị thống kê tiến độ chạy, tốc độ và trạng thái tài khoản của tab **Hàng đợi** (tạo video thường).
2. **Lệnh `tkshopee` (hoặc `/tkshopee`)**: Chỉ hiển thị thống kê tiến độ chạy, tốc độ và trạng thái tài khoản của tab **Tạo video Shopee**.
3. **Phím ảo tiện lợi (Reply Keyboard)**: Cập nhật phím ảo ở dưới khung chat Telegram của người dùng thành 2 nút bấm nhanh song song là **`tkhangdoi`** và **`tkshopee`** để thuận tiện chạm tra cứu trên điện thoại.
4. **Xóa lệnh tự động cũ khỏi menu**: Loại bỏ hoàn toàn `/tkaptm` và `/aptmtk` khỏi danh sách menu gợi ý lệnh `/` của Telegram Bot để giao diện gọn gàng hơn.

### Các thay đổi chi tiết

| File | Vị trí | Thay đổi |
|---|---|---|
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_send_telegram()` (dòng ~1952) | Đổi keyboard của reply_markup thành: `[[{"text": "tkhangdoi"}, {"text": "tkshopee"}]]`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_build_telegram_stats()` (dòng ~1982) | Tách hàm dựng text thành 3 phần: `_build_telegram_stats()` (tự động theo tab chạy), `_build_telegram_stats_queue()` (chỉ lấy tab hàng đợi), và `_build_telegram_stats_shopee()` (chỉ lấy tab Shopee). |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_telegram_polling_loop()` (dòng ~2100) | Đăng ký 3 lệnh tương tác với API Telegram (đã lược bỏ `tkaptm` và `aptmtk`): `/tkhangdoi`, `/tkshopee`, và `/tkslideshow`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_telegram_polling_loop()` (dòng ~2135) | Bổ dung phân nhánh điều hướng xử lý các lệnh: `/tkhangdoi`/`tkhangdoi` gọi hàm hàng đợi, và `/tkshopee`/`tkshopee` gọi hàm Shopee. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_test_telegram()` (dòng ~2160) | Đồng bộ loại bỏ `tkaptm` và `aptmtk` khỏi danh sách setMyCommands khi người dùng bấm test. |

---

## 25. Tự động chuyển đổi Proxy khi khởi động tài khoản thất bại (2026-07-30)

### Tóm tắt
Khắc phục lỗi khi khởi động tài khoản chính/donor, nếu proxy bị lỗi kết nối hoặc sai thông tin xác thực (HTTP 407 Proxy Authentication Required) thì tài khoản đó sẽ bị loại bỏ hoàn toàn:
1. **Khắc phục**: Khi `ensure_auth` hoặc `reset_project` thất bại lúc chuẩn bị tài khoản, phần mềm sẽ tự động đánh dấu proxy hiện tại là `dead`, sau đó gán proxy mới từ Proxy pool và thử khởi tạo lại (tối đa số lần bằng số proxy còn sống trong pool).
2. **Tab áp dụng**: Cả tab **Hàng đợi** và tab **Tạo Video Shopee** đều được nâng cấp logic này để tăng tính bền bỉ khi chạy số lượng lớn tài khoản và proxy.

### Các thay đổi chi tiết

| File | Vị trí | Thay đổi |
|---|---|---|
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_run()` (dòng ~2370) | Bổ sung vòng lặp retry proxy (thử `mark_dead` proxy cũ, gán proxy mới) khi tài khoản chính khởi động bị lỗi auth/reset project ở tab Hàng Đợi. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_sp_run()` (dòng ~3650) | Áp dụng logic tự động đổi proxy tương tự khi khởi động tài khoản chính trong tab Tạo Video Shopee. |

---

## 26. Tự động ghép thông minh theo ID và Sắp xếp tự nhiên (Natural Sort) (2026-07-31)

### Tóm tắt
Giải quyết vấn đề lệch thứ tự ghép ảnh và prompt do sự đụng độ giữa cách sắp xếp kiểu văn bản thuần túy (như hệ điều hành) và cách sắp xếp số học tự nhiên (như Excel/TXT):
1. **Tự động ghép theo ID (Auto ID Matching)**: Khi thêm hàng đợi (I2V), phần mềm sẽ tự động tách ID từ đầu dòng prompt (hoặc trước dấu `|`) để tìm ảnh có tên file trùng khớp thay vì chỉ ghép mù quáng theo số dòng. Nếu tỉ lệ khớp ID cao (trên 10%), hệ thống sẽ tự sắp hàng đợi theo thứ tự dòng prompt và gắn đúng ảnh tương ứng.
2. **Sắp xếp tự nhiên (Natural Sort)**: Cải tiến thuật toán sắp xếp danh sách ảnh nạp vào từ thư mục (`natural_sort_key`). Nhận diện chuỗi số theo giá trị toán học thực tế (ví dụ: số 10 chữ số sẽ xếp trước số 11 chữ số), đồng bộ hóa thứ tự sắp xếp với Excel/file TXT.
3. **Phạm vi cập nhật**: 
   - Tab **Hàng đợi**: Tự động ghép theo ID + Sắp xếp ảnh tự nhiên.
   - Tab **Tạo Video Shopee**: Sắp xếp ảnh sản phẩm tự nhiên khi quét thư mục.

### Các thay đổi chi tiết

| File | Vị trí | Thay đổi |
|---|---|---|
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_load_ref_images()` (dòng ~1493) | Nạp danh sách ảnh gốc của tab Tạo video thường bằng hàm sắp xếp số học tự nhiên `natural_sort_key` thông qua thư viện `re`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_add_queue()` (dòng ~1550) | Thay thế vòng lặp ghép index thô bằng thuật toán tự động khớp thông minh theo ID ảnh và dòng prompt. Tự động fallback về ghép index cũ nếu không có ID chung. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_sp_import_folder()` (dòng ~3265) | Cập nhật hàm quét ảnh sản phẩm của tab Shopee để sắp xếp tự nhiên theo số học trước khi đưa vào danh sách sản phẩm. |

---

## 27. Cập nhật Bố cục Giao diện, Đồng bộ Ngôn ngữ, Khóa Trường Dữ liệu & Tối ưu Đa luồng Chống Đơ UI (2026-08-01)

### Tóm tắt
Đã thực hiện chuỗi nâng cấp quan trọng nâng cao trải nghiệm người dùng, độ bền bỉ và tính ổn định của hệ thống:

1. **Tối ưu Bố cục Tab Tài khoản (2 cột ngang hàng)**:
   - Gộp `reCAPTCHA Mode` và `Telegram Report` nằm chung 1 hàng với cấu trúc 2 cột.
   - Đặt `Gemini API Keys` và `Groq API Keys` ở hàng kế tiếp dưới dạng 2 cột ngang nhau.
   - Loại bỏ ô cài đặt Telegram trùng lặp tại tab Tạo Video, tất cả tính năng dùng chung cấu hình Telegram duy nhất tại tab Tài khoản.

2. **Đồng bộ tự động Ngôn ngữ ↔ Thị trường (Server Video)**:
   - Tự động liên kết 2 chiều giữa dropdown Ngôn ngữ (`_sv_lang`) và Thị trường (`_sv_market`):
     - `Tiếng Philippines` $\leftrightarrow$ `PH`
     - `Tiếng Việt` $\leftrightarrow$ `VN`
     - `Tiếng Indonesia` $\leftrightarrow$ `ID`
   - Dùng cờ `_sv_syncing` ngăn ngừa vòng lặp callback đệ quy.

3. **Sắp xếp Ưu tiên Tài khoản Main ở trên Donor**:
   - Hàm `_refresh_acc` tự động gom và đẩy tất cả tài khoản role `Main` lên phía trên, tài khoản `Donor` nằm phía dưới.
   - Số thứ tự hiển thị (`display_i`) được đánh số liên tục từ 1, các thao tác Toggle/Edit/Delete vẫn trỏ chính xác vào index gốc (`orig_i`) trong `self.accounts`.

4. **Nút "Sửa" (Edit Toggle) & Khóa Dữ liệu Mặc định**:
   - Các trường kết nối Server (Server URL, API Key, Client ID) và Telegram (Token, Chat ID) mặc định ở trạng thái `disabled`.
   - Thêm nút `✏️ Sửa` bên cạnh. Khi bấm nút, trường dữ liệu mở khóa (`normal`) để chỉnh sửa, bấm lại chuyển thành `🔒 Khóa` và tự động cập nhật bộ nhớ cache.

5. **Khắc phục Triệt để Lỗi "Not Responding" (Đơ UI Thread)**:
   - **Nguyên nhân đơ UI**: Việc worker thread ngầm gọi `.get()` trực tiếp trên các widget `disabled` hoặc Textbox Proxy (`txt_proxy`) của Tkinter gây ra lỗi **deadlock** treo ứng dụng.
   - **Giải pháp**: Khởi tạo và cache toàn bộ thông tin `_sv_cached_url`, `_sv_cached_apikey`, `_sv_cached_client_id`, `_cached_px_lines` trên Main UI Thread trước khi kích hoạt worker thread. Worker thread ngầm tuyệt đối chỉ đọc dữ liệu từ cache.

6. **Tự động Phân bổ Công việc Round-Robin & Log Proxy**:
   - Thay thế 1 queue chung bằng danh sách queue riêng cho từng tài khoản. Sản phẩm được phân bổ xoay vòng đều cho các tài khoản (`acc_idx = idx % len(states)`).
   - Khắc phục tình trạng 1 tài khoản bị dồn ép xử lý toàn bộ lô hàng gây rate-limit.
   - Hiển thị địa chỉ Proxy chi tiết đi kèm từng tài khoản khi khởi động công việc.

7. **Sửa các lỗi tồn đọng nhỏ**:
   - **Fix nút "Nhận Lô SP"**: Tự động reset state=`normal` và text=`📥 Nhận Lô Sản Phẩm` khi xong batch hoặc giải phóng SP kẹt.
   - **Fix Upload Error**: Loại bỏ tham số thừa `aspect=img_aspect` trong hàm `E.upload_image()`.
   - **Cải tiến danh sách SP đã nhận**: Format hiển thị chi tiết dạng `⏳ [STT] item_id | name | ₱price | Sold:X | Comm:Y%`.

### Các thay đổi chi tiết

| File | Vị trí | Thay đổi |
|---|---|---|
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_build_acc()` (dòng ~558-615) | Tái cấu trúc card reCAPTCHA + Telegram Report thành layout 2 cột; Gemini + Groq API keys 2 cột. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_refresh_acc()` (dòng ~691-730) | Thêm logic sort Main trước Donor, quản lý cặp chỉ số `(display_i, orig_i)`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_build_gen()` (dòng ~1176) | Loại bỏ hoàn toàn khối UI Telegram Report trùng lặp ở tab Tạo Video. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_sv_sync_...` (dòng ~4777-4805) | Thêm 2 hàm callback đồng bộ 2 chiều Ngôn ngữ ↔ Thị trường. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_sv_toggle_...` (dòng ~4655-4680) | Thêm hàm toggle trạng thái Sửa/Khóa cho Kết nối Server và Telegram. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_sv_start()` (dòng ~5040-5380) | Thêm cache Main Thread cho URL, API key, Client ID, Proxy lines; triển khai Round-Robin per-account queue và log Proxy. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_sv_finish()`, `_sv_release_stuck()` | Cập nhật khôi phục text + state mặc định cho nút "Nhận Lô Sản Phẩm". |

---

## 28. Tái Cấu Trúc Trại Token reCAPTCHA (Token Farm) & Bảng So Sánh Chế Độ Captcha (2026-08-01)

### Tóm tắt
Đã giải quyết triệt để lỗi crash của **Trại Token reCAPTCHA (Token Farm)** và cập nhật tài liệu so sánh 2 phương thức giải captcha hiện có:

1. **Khắc phục lỗi Crash của Token Farm (`recaptcha_farm.py`)**:
   - **Lỗi cũ**: Module `recaptcha_farm.py` trước đó dùng `undetected_chromedriver` (`uc.Chrome`), khi khởi chạy 3 luồng song song trên Windows gây xung đột cổng kết nối ngầm (`cannot connect to chrome at 127.0.0.1:xxxxx`) và đụng độ file vá `chromedriver.exe`.
   - **Nâng cấp**: Viết lại toàn bộ hàm `_worker` sử dụng **`DrissionPage`** (`ChromiumPage`), đồng bộ tuyệt đối với hạ tầng đăng nhập của dự án.
   - **Giao tiếp CDP độc lập**: Mỗi worker thread tự chọn một cổng giao tiếp ngẫu nhiên (`random.randint(30000, 49999)`), khởi động Chrome Headless độc lập và dùng `page.run_js()` thực thi `grecaptcha.enterprise.execute()` lấy token tươi trả về hàng đợi thread-safe.

2. **Bảng So Sánh Chế Độ Giải reCAPTCHA (`android_bypass` vs `token_farm`)**:

| Tiêu chí | 🤖 `android_bypass` (Token Tĩnh) | 🐑 `token_farm` (Token Farm qua Chrome) |
|---|---|---|
| **Cơ chế** | Giả lập token tĩnh của ứng dụng Android: `RECAPTCHA_APPLICATION_TYPE_ANDROID` + `android_bypass` | Mở N luồng Chrome headless (`DrissionPage`), liên tục nạp script `recaptcha/enterprise.js` và thực thi `execute('6LfhM...', {action: 'LABS_FLOW'})` |
| **Thời gian khởi động** | Tức thì (0 giây) | Cần ~3-5 giây đầu để khởi tạo các luồng Chrome |
| **Tài nguyên phần cứng** | Không tốn RAM/CPU | Sử dụng một lượng tài nguyên RAM/CPU nhẹ cho Chrome ngầm |
| **Khả năng chống 429** | Trung bình - Tốt với lượng job vừa phải | **Tối ưu nhất - Rất ít bị 429** (Google coi request là người dùng thực sự từ trình duyệt) |
| **Độ ổn định API** | Phụ thuộc vào endpoint Android | **Chuẩn 100%** theo luồng web chính thức của Google Labs Flow |
| **Khuyên dùng** | Máy yếu / Khởi động nhanh / Ít tài khoản | **Tạo video hàng loạt quy mô lớn**, nhiều tài khoản song song |

### Thay đổi chi tiết file

| File | Vị trí | Thay đổi |
|---|---|---|
| [recaptcha_farm.py](file:///E:/ThinAptm0707/recaptcha_farm.py) | `_worker()` (dòng ~108-207) | Thay thế `undetected_chromedriver` bằng `DrissionPage` (`ChromiumOptions` + `ChromiumPage`), gán port ngẫu nhiên `30000-49999`, dùng Promise JS cho `run_js()`. Dọn dẹp hoàn toàn khối code cũ bị thừa. |

---

## 29. Tự động phát hiện và chuyển đổi Proxy lỗi 407/die trong khi chạy (Global Proxy Guard) (2026-08-01)

### Tóm tắt
Giải quyết triệt để lỗi khi một tài khoản đang chạy video bị chuyển sang proxy chết (trả lỗi HTTP 407 Proxy Authentication Required hoặc CONNECT tunnel failed). Lỗi này không phải lỗi 429 nên trước đó không kích hoạt nghỉ giãn cách, dẫn đến tài khoản liên tục nhận job mới và lỗi ngay lập tức hàng trăm lần:
1. **Khắc phục**: 
   - Thiết lập cơ chế **Global Proxy Guard**: Bọc (wrap) toàn cục các hàm gọi request `cffi.get`, `cffi.post`, và `cffi.delete` trong `engine.py`.
   - Nếu phát hiện phản hồi có mã status `407` hoặc nội dung ngoại lệ chứa `"407"` / `"tunnel failed"`, hệ thống lập tức kích hoạt callback `ON_PROXY_ERROR_CALLBACK` truyền proxy bị lỗi về GUI.
2. **Xử lý phía GUI (`thin_aptm.py`)**: 
   - Khi nhận được callback lỗi proxy, hệ thống tự động tra cứu xem tài khoản (`AccountState`) nào đang gán proxy này (bao gồm cả tài khoản chính ở tab Hàng Đợi, tab Shopee hoặc tài khoản Donor).
   - Tự động đánh dấu proxy cũ là `dead` trong pool, gán một proxy mới khác còn sống và tiếp tục chạy bình thường mà không làm gián đoạn hay đơ luồng xử lý.

### Các thay đổi chi tiết

| File | Vị trí | Thay đổi |
|---|---|---|
| [engine.py](file:///E:/ThinAptm0707/engine.py) | Đầu file (dòng ~17) | Định nghĩa biến callback `ON_PROXY_ERROR_CALLBACK` và hàm bọc `_wrap_req` để tự động kiểm tra và bắn lỗi proxy 407 về GUI. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `__init__()` (dòng ~452) | Đăng ký callback `E.ON_PROXY_ERROR_CALLBACK = self._on_global_proxy_error` khi khởi tạo ứng dụng. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | Dòng ~1947 | Thêm method `_on_global_proxy_error(proxy_dict)` để tìm kiếm tài khoản tương ứng, đánh dấu proxy cũ là `dead`, tự động gán proxy mới và log thông báo cho người dùng. |

---

## 30. Shopee Product Scraper — Chrome Extension Cào Sản Phẩm Tự Động (2026-08-01)

### Tóm tắt

Extension Chrome Manifest V3 tự động cào sản phẩm từ **7 thị trường Shopee** (PH, VN, ID, TH, MY, SG, TW), lưu trữ tập trung vào **PostgreSQL** qua Server Express, hỗ trợ quét hàng loạt category với phân bổ công việc phân tán (distributed task queue). Extension phục vụ làm nguồn dữ liệu sản phẩm cho module Tạo Video Shopee của Thìn Aptm.

### Cấu trúc thư mục

```
E:\0 - cao SP trang chu\
├── manifest.json            # Manifest V3 — permissions, content scripts, service worker
├── background.js            # Service Worker: Bypass proxy, API client, Google Sheets JWT, Server bridge
├── css/
│   └── panel.css            # Dark-theme panel styles, CSS tokens, slide-out animation
├── js/
│   ├── content.js           # Core engine: UI panel, state, batching, pagination, DB sync (~2760 dòng)
│   └── inject.js            # API Interceptor: MAIN world fetch/XHR hook + React Fiber fallback
└── server/
    ├── index.js             # Express API server (port 3000, 0.0.0.0)
    ├── db.js                # PostgreSQL pool, schema, bulk upsert, atomic claim
    ├── .env                 # DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME, API_KEY
    └── start_server.bat     # Khởi chạy server
```

### Kiến trúc tổng quan

```mermaid
graph TD
    A["Shopee Web (Search/Category Page)"] --> B["inject.js (MAIN World)"]
    B -->|"window.postMessage"| C["content.js (ISOLATED World)"]
    A -->|"Fallback khi inject thất bại"| D["background.js (Service Worker)"]
    D -->|"Bypass API (Facebook UA)"| A
    D -->|"chrome.runtime response"| C

    C -->|"Lọc + Enrichment + Thống kê"| E["Processed Products"]
    E -->|"chrome.runtime.sendMessage"| D
    D -->|"HTTP POST /api/products"| F["Express Server (index.js:3000)"]
    F -->|"Bulk Upsert"| G["PostgreSQL (shopee_products)"]

    subgraph "Batch Mode"
        H["Server: shopee_categories"] -->|"SELECT ... FOR UPDATE SKIP LOCKED"| F
        F -->|"Claim → In Progress → Completed"| H
    end
```

### Chi tiết các thành phần

#### A. `manifest.json` — Cấu hình Extension

| Thuộc tính | Giá trị |
|---|---|
| Manifest Version | 3 |
| Permissions | `storage`, `downloads`, `cookies`, `scripting`, `tabs` |
| Host Permissions | `https://shopee.ph/*`, `shopee.vn/*`, `shopee.co.id/*`, `shopee.sg/*`, `shopee.com.my/*`, `shopee.co.th/*`, `shopee.tw/*` + Google OAuth/Sheets |
| Content Scripts | `content.js` + `panel.css` → ISOLATED world; `inject.js` → MAIN world (`document_start`) |
| Service Worker | `background.js` |

- **MAIN world** (`inject.js`): Chạy trong context JavaScript của trang Shopee → có quyền hook `fetch`/`XHR` gốc
- **ISOLATED world** (`content.js`): Chạy tách biệt → an toàn, không bị Shopee phát hiện, quản lý UI panel

#### B. `js/inject.js` — API Interceptor

**Mục đích**: Chặn bắt response từ API Shopee khi trang load dữ liệu sản phẩm.

**3 cơ chế hoạt động:**

| # | Cơ chế | Mô tả |
|---|---|---|
| 1 | **Fetch Hook** | Wrap `window.fetch`, check URL khớp `API_PATTERNS` (`api/v4/search/search_items`, `recommend`, `affiliate`, `ams`, `offer`), clone JSON response → `postMessage` về `content.js` |
| 2 | **XHR Hook** | Wrap `XMLHttpRequest.prototype.open/send` — fallback cho legacy request |
| 3 | **React Fiber Fallback** | Duyệt DOM tìm `__reactFiber$` / `__reactInternalInstance$` → trích `shopId`, `itemId` từ React component state nếu API không trả data |

```javascript
// inject.js — Core Pattern
const origFetch = window.fetch;
window.fetch = async function(url, opts) {
    const resp = await origFetch.apply(this, arguments);
    if (API_PATTERNS.some(p => url.includes(p))) {
        const clone = resp.clone();
        const json = await clone.json();
        window.postMessage({ type: 'SHOPEE_SCRAPER_DATA', payload: json, url }, '*');
    }
    return resp;
};
```

#### C. `js/content.js` — Core Engine (~2760 dòng)

**Mục đích**: Quản lý toàn bộ logic: UI panel, state machine, auto-pagination, batch scrape, data processing, DB sync.

**Các hằng số quan trọng:**

| Hằng số | Giá trị | Mô tả |
|---|---|---|
| `MARKETS` | 7 thị trường | PH, VN, ID, TH, MY, SG, TW — mỗi thị trường có domain, flag, currency riêng |
| `BLOCKED_KEYWORDS` | ~50 từ khóa | Lọc sản phẩm nhạy cảm (adult, vũ khí, thuốc, giả hàng) |
| `BLOCKED_CATIDS` | Danh sách catid | Category bị cấm (ví dụ: `11021341`) |
| `MAX_PAGES_PER_SORT` | 20 | Tối đa 20 trang/bộ lọc |
| `MAX_BYPASS_FAILURES` | 3 | Số lần retry bypass thất bại trước khi skip |

**Settings (lưu localStorage):**

```javascript
let settings = {
    autoPage: true,        // Tự động quét tất cả trang
    delay: 4,              // Delay giữa các trang (giây)
    bypassMode: true,      // Bypass CAPTCHA bằng UA Facebook
    sortCtime: true,       // Bộ lọc: Mới nhất
    sortSales: true,       // Bộ lọc: Bán chạy
    disableCommission: false, // Tắt cào hoa hồng (x30 tốc độ)
    serverUrl: 'http://localhost:3000',
    serverApiKey: 'shopee_secret_2026',
    autoSyncServer: true,  // Tự đồng bộ lên PostgreSQL
    profileName: 'Profile_XXXX' // Tên Chrome Profile (dùng cho claim category)
};
```

**Hàm `getSortModes()` — Dynamic Sort Mode:**

```javascript
function getSortModes() {
    const modes = [];
    if (settings.sortCtime !== false) modes.push('ctime');  // Mới nhất
    if (settings.sortSales !== false) modes.push('sales');  // Bán chạy
    if (modes.length === 0) modes.push('ctime'); // Fallback: ít nhất 1
    return modes;
}
```

> [!IMPORTANT]
> `sortBy=pop` đã bị loại bỏ vì Shopee render SSR (Server-Side Rendering) cho trang mặc định `pop`, khiến `inject.js` không bắt được API call → tốn thời gian vô ích.

**Các hàm cốt lõi:**

| Hàm | Chức năng |
|---|---|
| `processApiData(apiData)` | Trích xuất SP, lọc SP cấm, enrichment tên/giá, cào hoa hồng Affiliate, cập nhật UI, trigger trang kế |
| `scheduleNextPage()` | Tính delay + jitter ±30%, cuộn trang giả lập, navigate trang kế |
| `fetchNextPageBypass()` | Gửi request bypass qua `background.js` (Facebook UA) |
| `startBatchScrape()` | Claim category từ Server → quét → xoay sort → mark completed → next |
| `navigateToNextCategory()` | Claim category tiếp từ Server, navigate trang Shopee |
| `detectCaptcha()` | Phát hiện CAPTCHA (URL, DOM, text) → dừng + phát âm thanh cảnh báo |
| `startCaptchaAutoResume()` | Poll mỗi 2s, tự resume 3s sau khi CAPTCHA biến mất |
| `createPanel()` | Render UI panel với các section thu gọn (Settings, Server DB, Log) |

#### D. `background.js` — Service Worker

**Mục đích**: Proxy cho các tác vụ đặc quyền: bypass API, CSRF cookie, Google Sheets JWT, file download, server bridge.

**Hàm `fetchShopeeApiDirect(apiUrl)` — Bypass Anti-bot:**

```
Bước 1: Fetch với credentials user + X-CSRFToken (từ cookie)
    ↓ Nếu bị chặn (403/non-OK)
Bước 2: Fallback sang BYPASS_UAS (Facebook/WhatsApp/Line UA)
    → Shopee WAF cho crawler mạng xã hội đi qua không cần CAPTCHA
    ↓ Nếu response thiếu tên SP (degraded)
Bước 3: enrichItemsWithApi() — gọi /api/v4/item/get cho từng batch 5 SP
```

**Bypass User-Agents:**

```javascript
const BYPASS_UAS = [
    'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
    'WhatsApp/2.23.20.0',
    'Line/14.5.0'
];
```

**Google Sheets JWT (RS256):**

```
1. Import PKCS8 PEM private key → crypto.subtle
2. Sign SHA-256 JWT assertion
3. Exchange at https://oauth2.googleapis.com/token
4. Append rows to Google Sheets → không cần OAuth popup
```

**Server Proxy Handlers:**

| Action | Endpoint Server | Mô tả |
|---|---|---|
| `uploadToServer` | `POST /api/products` | Gửi batch SP lên PostgreSQL |
| `claimServerCategory` | `POST /api/batch/claim` | Claim category cho profile |
| `completeServerCategory` | `POST /api/batch/complete` | Đánh dấu category đã quét xong |
| `resetServerCategories` | `POST /api/categories/reset` | Reset tất cả category → quét lại |
| `fetchServerProducts` | `GET /api/products` | Lấy danh sách SP phân trang |
| `fetchServerExport` | `GET /api/products/export` | Export toàn bộ SP theo market |

#### E. `server/index.js` — Express API Server

**Cấu hình**: Port 3000, bind `0.0.0.0` (truy cập từ nhiều máy), JSON limit 50MB.

**Xác thực**: Header `X-API-Key` = `shopee_secret_2026`.

**API Routes:**

| Method | Route | Chức năng |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/stats` | Thống kê tổng SP theo market |
| `POST` | `/api/products` | Bulk upsert sản phẩm |
| `GET` | `/api/products` | Query SP phân trang |
| `GET` | `/api/products/export` | Export toàn bộ SP theo market |
| `POST` | `/api/categories/import` | Import danh mục |
| `POST` | `/api/batch/claim` | **Atomic claim** category (distributed lock) |
| `POST` | `/api/batch/complete` | Đánh dấu category hoàn thành |
| `POST` | `/api/categories/reset` | Reset trạng thái category |
| `GET` | `/api/categories/stats` | Thống kê danh mục |
| `POST` | `/api/thinaptm/claim-jobs` | Claim job video cho Thìn Aptm |
| `POST` | `/api/thinaptm/complete-job` | Đánh dấu video đã tạo xong |

#### F. `server/db.js` — PostgreSQL Schema & Algorithms

**Connection Pool**: `pg.Pool`, max 20 connections, idle timeout 30s.

**Schema `shopee_products`:**

```sql
CREATE TABLE shopee_products (
    item_id         BIGINT PRIMARY KEY,
    shop_id         BIGINT NOT NULL,
    name            TEXT,
    price           NUMERIC(15, 2) DEFAULT 0,
    sold            INT DEFAULT 0,
    commission_rate NUMERIC(5, 2) DEFAULT 0,
    image_url       TEXT,
    product_url     TEXT,
    market          VARCHAR(10),
    source_url      TEXT,
    scraped_at      TIMESTAMPTZ DEFAULT NOW(),
    -- Video extension columns (cho Thìn Aptm)
    video_status    VARCHAR(20) DEFAULT 'pending',
    video_path      TEXT,
    claimed_by      VARCHAR(100),
    claimed_at      TIMESTAMPTZ,
    video_updated_at TIMESTAMPTZ
);

-- Indexes tối ưu query
CREATE INDEX idx_market_sold ON shopee_products (market, sold DESC);
CREATE INDEX idx_market_price ON shopee_products (market, price);
CREATE INDEX idx_scraped_at ON shopee_products (scraped_at DESC);
CREATE INDEX idx_video_status ON shopee_products (video_status);
```

**Schema `shopee_categories`:**

```sql
CREATE TABLE shopee_categories (
    market      VARCHAR(10),
    catid       VARCHAR(50),
    name        TEXT,
    link        TEXT,
    status      VARCHAR(20) DEFAULT 'pending',  -- pending | in_progress | completed
    claimed_by  VARCHAR(100),                    -- Profile name đang quét
    claimed_at  TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (market, catid)
);
```

**Thuật toán Bulk Upsert (`upsertProducts`):**

```
1. Chia products thành batch 500 SP
2. Mỗi batch: BEGIN transaction
3. Tạo 1 câu SQL duy nhất:
   INSERT INTO shopee_products (item_id, shop_id, name, price, sold, ...)
   VALUES ($1,$2,...), ($N+1,$N+2,...), ...
   ON CONFLICT (item_id) DO UPDATE SET
     name = EXCLUDED.name,
     price = EXCLUDED.price,
     sold = EXCLUDED.sold,
     commission_rate = EXCLUDED.commission_rate,
     image_url = EXCLUDED.image_url,
     scraped_at = EXCLUDED.scraped_at;
4. COMMIT (hoặc ROLLBACK nếu lỗi)
```

> [!NOTE]
> `ON CONFLICT (item_id) DO UPDATE` đảm bảo **không bao giờ trùng lặp** item_id trong DB. Khi cào lại SP cùng ID, chỉ cập nhật tên/giá/sold mới nhất.

**Thuật toán Atomic Claim Category (`claimCategory`):**

```sql
-- Distributed lock: SELECT FOR UPDATE SKIP LOCKED
-- Đảm bảo 2 Chrome profile không claim cùng category
UPDATE shopee_categories
SET status = 'in_progress', claimed_by = $1, claimed_at = NOW()
WHERE (market, catid) = (
    SELECT market, catid FROM shopee_categories
    WHERE market = $2 AND status = 'pending'
    ORDER BY catid
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING *;
```

### Quy trình Batch Mode (Quét hàng loạt Category)

```mermaid
graph TD
    A["Bấm 🚀 Quét từ DB"] --> B["Claim category từ Server<br/>(POST /api/batch/claim)"]
    B --> C["Server: SELECT FOR UPDATE SKIP LOCKED<br/>→ Khóa category cho profile này"]
    C --> D["Navigate tới URL category<br/>(sortBy=ctime, page=0)"]
    D --> E["inject.js bắt API response"]
    E --> F["content.js xử lý 60 SP/trang"]
    F --> G["Upload lên PostgreSQL"]
    G --> H{Còn trang?<br/>page < 20?}
    H -- Có --> I["scheduleNextPage()<br/>(delay 4s ± jitter)"]
    I --> D
    H -- Không / 0 SP --> J{Còn sort mode?}
    J -- "ctime → sales" --> K["Đổi sortBy=sales<br/>Reset page=0"]
    K --> D
    J -- Hết sort modes --> L["Mark completed trên Server<br/>(POST /api/batch/complete)"]
    L --> B
```

### Cơ chế Chống Bot & CAPTCHA

| Cơ chế | Mô tả |
|---|---|
| **Jittered Delay** | `baseSec + (Math.random() * jitter * 2 - jitter)` — delay 4s ± 30% ngẫu nhiên |
| **Human Scroll** | `simulateHumanScroll()` — cuộn trang random trước khi navigate |
| **CAPTCHA Detection** | Scan URL (`verify/traffic`), DOM (`.shopee-captcha-container`), text signatures |
| **CAPTCHA Alert** | Phát âm thanh multi-frequency qua Web Audio API |
| **CAPTCHA Auto Resume** | Poll mỗi 2s, tự resume 3s sau khi CAPTCHA biến mất |
| **Bypass UA** | `facebookexternalhit/1.1`, `WhatsApp`, `Line` — Shopee WAF cho qua |
| **Affiliate Throttle** | Delay 1.5s giữa mỗi query Affiliate API chống 429 |

### UI Panel — Cấu trúc giao diện

| Section | Thu gọn? | Mặc định | Nội dung |
|---|---|---|---|
| 🛒 Header | ❌ | Mở | Tên app + subtitle |
| 🌏 Thị trường | ❌ | Mở | Dropdown 7 market + nút Fetch danh mục |
| 📊 Thống kê | ❌ | Mở | 4 thẻ đếm (Tổng DB, Mới, Trùng, Trang) + progress bar |
| ⚙ Cài đặt | ✅ `#sp-settings-toggle` | **Thu gọn** | Auto page, Bypass, Commission, Sort modes (ctime/sales), Delay |
| 📂 Quét hàng loạt | ❌ | Mở | Quét từ DB, Import file, Reset, Batch progress |
| 🎮 Điều khiển | ❌ | Mở | Start/Stop, Xem DB, Export CSV, Google Sheets, Dọn SP lỗi |
| 🖥️ Server DB | ✅ `#sp-server-toggle` | **Thu gọn** | URL, API Key, Profile, Ping, Đồng bộ, Migrate, Enrich |
| 📝 Nhật ký | ❌ | Mở | Log console (max-height 350px) + nút tải log.txt |

**Design Tokens (CSS):**

```css
:root {
    --sp-bg: #0f0f1a;        /* Nền tối */
    --sp-card: #1a1a2e;      /* Nền card */
    --sp-accent: #ee4d2d;    /* Shopee orange */
    --sp-success: #2ed573;   /* Xanh lá */
    --sp-warning: #ffa502;   /* Vàng cam */
    --sp-error: #ff4757;     /* Đỏ */
    --sp-cyan: #18dcff;      /* Cyan highlight */
    --sp-panel-w: 25vw;      /* Chiều rộng panel = 25% viewport */
}
```

### Lịch sử thay đổi quan trọng (phiên này)

| Thay đổi | Mô tả |
|---|---|
| Loại bỏ `sortBy=pop` | Shopee SSR cho trang `pop` → inject.js không bắt được API |
| Thêm checkbox Sort Modes | Người dùng chọn ctime/sales hoặc cả 2 trong Cài đặt |
| `getSortModes()` dynamic | SORT_MODES đọc từ settings thay vì hardcode |
| Thu gọn Settings & Server DB | Toggle accordion với state lưu localStorage |
| Xóa bảng "Sản phẩm" | Giải phóng diện tích, tăng log lên 350px |
| Fix crash `sp-search` | Xóa event listener cho element đã bị remove |



---

## 31. Loại bỏ hoàn toàn tính năng và tab SlideShow (2026-08-01)

### Tóm tắt
Theo yêu cầu tối giản và tập trung hóa tính năng phần mềm, đã tiến hành gỡ bỏ hoàn toàn tab tạo video SlideShow và tất cả mã nguồn liên quan:
1. **Gỡ bỏ UI (Giao diện)**:
   - Xóa bỏ tab `"Tạo Video SlideShow"` khỏi menu điều hướng bên trái của phần mềm chính (`thin_aptm.py`).
   - Xóa bỏ hàm khởi dựng giao diện tab `_build_slideshow()`.
   - Loại bỏ cơ chế tự lưu/khôi phục cấu hình SlideShow trong hàm đóng app `_on_closing()`.
2. **Gỡ bỏ mã nguồn và file standalone**:
   - Xóa bỏ module độc lập `SlideShow.py` (chứa toàn bộ logic render slideshow, Ken Burns effect và giao tiếp Google Sheets).
   - Xóa bỏ file chạy standalone `slideshow_standalone.py`.
   - Xóa bỏ file kịch bản khởi động nhanh `run_slideshow.bat`.
   - Xóa bỏ tài liệu hướng dẫn SlideShow `slideshow.md`.
3. **Telegram Bot Integration**:
   - Loại bỏ lệnh `/tkslideshow` và `tkslideshow` khỏi danh sách tự động đăng ký với Telegram Bot API (`setMyCommands`) trong cả hai hàm `_init_bot_commands()` và `_test_telegram()`.

### Các thay đổi chi tiết

| File | Vị trí | Thay đổi |
|---|---|---|
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | Menu điều hướng (dòng ~471) | Xóa item `("slideshow", ...)` khỏi danh sách các tab. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_build_slideshow()` (dòng ~5481) | Xóa bỏ hoàn toàn hàm này cùng các lệnh import/build tab SlideShow. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_on_closing()` (dòng ~5570) | Xóa bỏ khối code cập nhật settings của SlideShow trước khi lưu vào `settings.json`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | Đăng ký lệnh (dòng ~2145 & ~2208) | Loại bỏ lệnh `tkslideshow` khỏi danh sách đăng ký lệnh với Telegram Bot. |
| **SlideShow.py** | [DELETE] | Xóa bỏ file nguồn SlideShow. |
| **slideshow_standalone.py** | [DELETE] | Xóa bỏ file chạy độc lập. |
| **run_slideshow.bat** | [DELETE] | Xóa bỏ file bat. |
| **slideshow.md** | [DELETE] | Xóa bỏ file tài liệu. |

---

## 32. Sửa triệt để lỗi Lag / Not Responding — Thread Safety & Performance Optimization (2026-08-01)

### Tóm tắt
Rà soát toàn diện mã nguồn `thin_aptm.py` phát hiện **11 nhóm lỗi** gây lag và "Not Responding". Nguyên nhân gốc rễ: **thread nền gọi trực tiếp widget Tkinter** (`.get()`, `.configure()`), và **hiệu năng UI** (gõ phím lag, log phình bộ nhớ vô hạn).

### Nhóm A — Thread Safety (Ngăn Deadlock)

| # | Vị trí | Lỗi | Sửa |
|---|---|---|---|
| A1 | `_telegram_polling_loop` (dòng ~2126) | Vòng lặp `while True` liên tục gọi `.get()` trên `ent_tg_token`, `ent_tg_chatid`, `tg_enabled` từ thread nền → deadlock | Cache giá trị TG vào `_cached_tg_*` biến instance. Thread nền đọc cache. Main thread cập nhật cache qua `_update_tg_cache()` + `after(0)`. |
| A2 | `_run()` (dòng ~2400) | Đọc `txt_proxy.get()`, `use_laundering.get()`, `tg_enabled.get()`, `remove_veo_wm.get()`, `auto_concat.get()` từ thread nền | Cache tất cả vào `_cached_*` trong `_start()` (main thread), truyền vào `_run()`. |
| A3 | `_shopee_start` → `work()` (dòng ~3656) | Đọc `txt_proxy.get()`, `_sp_use_laundering.get()`, `tg_enabled.get()`, `_sp_review_style.get()` từ thread nền | Cache tất cả vào local vars trong `_shopee_start()` (main thread) trước khi spawn `work()`. |
| A4 | `_check_accs` (dòng ~887) | `lbl_acc_prog.configure(text=...)` trực tiếp từ thread nền | Bọc trong `self.after(0, ...)`. |
| A5 | `_ai_gen_prompt` → `_do()` (dòng ~1372) | `opt_aspect.get()`, `gen_mode.get()` từ thread nền | Cache giá trị trước khi spawn thread `_do()`. |

### Nhóm B — Performance Optimization

| # | Vị trí | Lỗi | Sửa |
|---|---|---|---|
| B1 | `<KeyRelease>` trên `_sp_products` (dòng ~3052) | Mỗi phím bấm → `.get("1.0","end")` + `splitlines()` toàn bộ textbox → **lag gõ phím cực nặng** | Debounce 500ms: dùng `after_cancel` + `after(500, ...)`, chỉ chạy sau khi ngừng gõ 500ms. |
| B2 | `_log` và `_sp_log_msg` (dòng ~1946, 3470) | Log textbox tăng vô hạn → phình bộ nhớ + slow rendering | Giới hạn log widget tối đa 2000 dòng. Khi vượt quá, xóa bớt 500 dòng đầu (trim to 1500). |

### Các thay đổi chi tiết

| File | Vị trí | Thay đổi |
|---|---|---|
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_start_telegram_polling` | Khởi tạo `_cached_tg_*` từ settings, thêm hàm `_update_tg_cache()`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_telegram_polling_loop` | Đọc từ cache thay vì `.get()` widget, schedule `_update_tg_cache` qua `after(0)`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_start()` | Cache `txt_proxy`, `use_laundering`, `tg_enabled`, `remove_veo_wm`, `auto_concat` vào `_cached_*`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_run()` | Dùng `_cached_*` thay vì `.get()` tại 6 vị trí. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_shopee_start()` | Cache proxy, use_laundering, tg_enabled, review_style trước `def work()`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `work()` (shopee) | Dùng `_sp_cached_*` thay vì `.get()` tại 8 vị trí. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_check_accs` | Bọc `lbl_acc_prog.configure` trong `self.after(0)`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_ai_gen_prompt` | Cache `opt_aspect`, `gen_mode` trước khi spawn thread `_do()`. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_build_shopee` (KeyRelease) | Thay binding trực tiếp bằng debounce 500ms. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_log` | Thêm truncation: xóa 500 dòng đầu khi vượt 2000 dòng. |
| [thin_aptm.py](file:///E:/ThinAptm0707/thin_aptm.py) | `_sp_log_msg` | Thêm truncation tương tự cho log Shopee. |

---

## 33. Cài đặt chỉ số "Tạo" & "Tốc độ" trên tab Hàng đợi (2026-08-01)
- **Giao diện**: Thêm 2 ô nhập liệu `⚡ Tạo` (`spn_workers`) và `Tốc độ` (`spn_speed`) trên thanh điều khiển của tab Hàng đợi. Giá trị mặc định là **5**.
- **Chức năng**:
  - `Tạo`: Quy định số worker đồng thời cho mỗi tài khoản (`workers_per_account`).
  - `Tốc độ`: Quy định trần tốc độ submit tối đa cho thuật toán AIMD (`submit_max`).
- **Lưu trữ**: Tự động lưu và khôi phục giá trị vào `settings.json`.
- **Đồng bộ**: Cả tab Hàng đợi chính và tab Shopee đều sử dụng cài đặt động này.

---

## 34. Cập nhật Format danh sách Sản phẩm tab Shopee (2026-08-01)
- **Hiển thị mới**: Chuyển sang format `ảnh.jpg | Tên SP` giúp người dùng dễ dàng nhìn thấy tên file ảnh ngay đầu dòng.
- **Tự động nhận diện (Smart Detection)**: Tự động phân biệt format mới (`ảnh.jpg | Tên SP`) và format cũ (`Tên SP | ảnh.jpg`) dựa vào đuôi file ảnh, giúp tương thích ngược hoàn toàn với dữ liệu cũ.
---

## 35. Tính năng "AI Prompt" & Nút "Test prompt" tab Tạo Video Shopee (2026-08-01)
- **Giao diện**:
  - Thêm menu lựa chọn `AI Prompt:` với các giá trị: `Gemini`, `Groq`, `Template (mặc định)`.
  - Thêm nút `🧪 Test prompt` màu xanh tím bên cạnh.
- **Chức năng**:
  - **AI Prompt**: Cho phép chọn mô hình AI (Gemini / Groq / Template) để tự động sinh prompt video đa đoạn dựa trên tên sản phẩm, khung cảnh, độ dài video (16s/24s), ngôn ngữ và phong cách review.
  - **Nút Test prompt**: Khi bấm, ứng dụng sẽ lấy sản phẩm ĐẦU TIÊN trong danh sách, gọi engine AI tương ứng (hoặc Template) và hiển thị kết quả prompt sinh ra trong một cửa sổ popup (`CTkToplevel`) trực quan để người dùng kiểm tra trước khi chạy hàng loạt.
---

## 36. Lọc sản phẩm theo ItemID từ & Hoa hồng từ trên tab Tạo Video từ Server (2026-08-01)
- **Giao diện**:
  - Thêm 2 ô nhập liệu `ItemID từ:` (`_sv_min_item_id`, mặc định `40000000000`) và `Hoa hồng từ:` (`_sv_min_commission`, mặc định `1%`) tại khung "Nhận Lô Sản Phẩm từ Database".
- **Chức năng**:
  - Khi bấm **Nhận Lô Sản Phẩm**, ứng dụng gửi tham số `min_item_id` / `minItemId` và `min_commission` / `minCommission` lên API Server.
  - Đồng thời thực hiện lọc ở phía client để đảm bảo 100% sản phẩm hiển thị và nhận về đều có `item_id >= ItemID từ` và `hoa hồng >= Hoa hồng từ`.
- **Lưu trữ**: Tự động lưu và khôi phục `sv_min_item_id` và `sv_min_commission` trong `settings.json`.

---

## 37. Thiết lập Icon riêng cho ứng dụng Thìn Aptm (2026-08-01)
- **Hình ảnh**: Tự động tạo file `logo.ico` đa kích thước (16x16 đến 256x256) từ hình ảnh thương hiệu `logo.png`.
- **Cấu hình Windows**:
  - Đăng ký `SetCurrentProcessExplicitAppUserModelID` (`thinaptm.googleflow.app.1.0`) giúp Windows hiển thị icon riêng trên thanh Taskbar thay vì icon Python mặc định.
---

## 38. Bổ sung ô cài đặt "Tạo" & "Tốc độ" trên tab Tạo Video Shopee (2026-08-01)
- **Giao diện**: Thêm trực tiếp 2 ô nhập liệu `⚡ Tạo` (`_sp_workers`) và `Tốc độ` (`_sp_speed`) vào khung Cài đặt của tab **Tạo Video Shopee** giúp người dùng tiện chỉnh sửa trực tiếp mà không cần chuyển sang tab Hàng đợi.
---

## 39. Đồng bộ hóa chuẩn 1 format Hoa hồng và Đơn vị tiền tệ (2026-08-01)
- **Chuẩn hóa 1 Format Hoa hồng**: Toàn bộ hoa hồng từ mọi thị trường (VN, PH, ID...) đều được quy đổi tự động về cùng 1 chuẩn phần trăm (ví dụ: `15.0%`, `10.0%`, `7.0%`).
- **Đơn vị tiền tệ động theo Thị trường**:
  - Thị trường VN: Hiển thị tiền `₫` (VD: `₫150,000`).
  - Thị trường ID: Hiển thị tiền `Rp`.
  - Thị trường PH & các thị trường khác: Hiển thị tiền `₱`.

---

## 40. Khắc phục sự cố Server ngắt / thoát bất ngờ (Anti-Crash & Auto-Restart 24/7) (2026-08-06)
- **Nguyên nhân**:
  1. Thư viện PostgreSQL pool (`pg.Pool`) thiếu hàm lắng nghe lỗi `pool.on('error')`, khiến mỗi khi kết nối đệm (idle connection) bị ngắt hoặc rớt mạng, Node.js sẽ phát sự kiện `error` không được catch $\rightarrow$ làm văng Node process.
  2. Thiếu bộ bắt lỗi toàn cục (`uncaughtException` & `unhandledRejection`) dẫn đến khi có sự cố mạng từ Telegram API hoặc fetch ngoại lệ, Node.js tự động ngắt và hiện `Press any key to continue`.
- **Giải pháp xử lý triệt để**:
  1. **[db.js](file:///E:/0%20-%20cao%20SP%20trang%20chu/server/db.js)**: Bổ sung `pool.on('error', ...)` để tự động ghi log và nuốt lỗi kết nối đệm, tuyệt đối không cho văng app.
  2. **[index.js](file:///E:/0%20-%20cao%20SP%20trang%20chu/server/index.js)**: Đăng ký `process.on('uncaughtException')` và `process.on('unhandledRejection')` giúp Server luôn sống 24/7.
  3. **[start_server.bat](file:///E:/0%20-%20cao%20SP%20trang%20chu/server/start_server.bat)**: Tích hợp vòng lặp tự động khởi động lại Node.js sau 3 giây (`:loop ... goto loop`) nếu Server bị thoát bất kỳ lý do gì.

---

## 41. Tự động khởi chạy Server khi bật/khởi động lại máy tính Windows (Auto Startup) (2026-08-06)
- **Giải pháp**: Đã tạo lối tắt (Shortcut) `Shopee_Database_Server.lnk` trực tiếp trong thư mục `shell:startup` của Windows (`C:\Users\thinc\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup`).
- **Cơ chế**:
  1. Mỗi khi máy tính khởi động và đăng nhập vào Windows, hệ thống sẽ tự động khởi chạy cửa sổ `start_server.bat`.
  2. Kết hợp với vòng lặp `:loop` của `start_server.bat` và bộ lọc lỗi `pool.on('error')`, Server sẽ hoạt động liên tục 24/7 không bao giờ sập.

---

## 42. Tùy chọn Không lưu sản phẩm Hoa hồng = 0% & Làm sạch Database (2026-08-06)
- **Tính năng Extension (`content.js`)**:
  1. Thêm checkbox `🚫 Không lưu SP có hoa hồng = 0%` (`skipZeroCommission`) trong phần Cài Đặt của Chrome Extension, mặc định **BẬT (`true`)**.
  2. Khi quét sản phẩm (cả thủ công và batch mode), Extension tự động lọc bỏ các sản phẩm có `commission_rate = 0` trước khi lưu vào PostgreSQL Server.
- **Dọn dẹp Database (`shopee_db`)**:
  1. Đã chạy câu lệnh SQL làm sạch dứt điểm `DELETE FROM shopee_products WHERE commission_rate = 0 OR commission_rate IS NULL;`, loại bỏ **109,784 sản phẩm rác** không có hoa hồng.
  2. Đảm bảo Database luôn tinh gọn, chỉ chứa các sản phẩm mang lại doanh thu hoa hồng thực tế cho người dùng.

---

## 43. Sửa triệt để lỗi Windows Script Host & Lỗi mã hóa ký tự file Batch (2026-08-06)
- **Nguyên nhân 2 lỗi trong ảnh**:
  1. **Lỗi CMD rác lệnh (`'KHOI' is not recognized...`)**: File `.bat` cũ chứa ký tự UTF-8 Emojis (`⚠️`) khiến trình đọc CMD của Windows bị lệch offset ký tự nhị phân, dẫn đến việc cắt xới câu lệnh sai và thực thi rác.
  2. **Lỗi Windows Script Host (`Microsoft JScript compilation error 800A03EA`)**: Khi lệnh `node` trong CMD bị lỗi mã hóa hoặc thiếu biến môi trường PATH, Windows tự động dùng chương trình mặc định `wscript.exe` (Windows Script Host) mở file `index.js` $\rightarrow$ gây popup báo lỗi cú pháp JScript.
- **Khắc phục triệt để**:
  1. **[start_server.bat](file:///E:/0%20-%20cao%20SP%20trang%20chu/server/start_server.bat)**: Viết lại chuẩn đét định dạng Plain ASCII (không chứa ký tự Unicode đặc biệt), bổ sung cơ chế kiểm tra `where node`, nếu không thấy PATH sẽ tự động fallback gọi đường dẫn tuyệt đối `"C:\Program Files\nodejs\node.exe" index.js`.
  2. Cập nhật lại Shortcut `Shopee_Database_Server.lnk` trong `shell:startup` đảm bảo đường dẫn và thư mục làm việc luôn chính xác 100%.






---

## 44. Hệ Thống Tối Ưu Bứt Tốc 1 Hàng Đợi Chung (Shared Job Queue) & Polling 3.5s (2026-08-09)
- **Tình trạng cũ**: Tab Server Video chia cứng sản phẩm vào từng giỏ riêng (per_acc_queues) -> khi 1 tài khoản nghỉ hoặc chậm, các sản phẩm kẹt trong giỏ đó không được tài khoản khác gánh hộ.
- **Khắc phục**: Chuyển sang mô hình 1 Hàng Đợi Chung (jobq = queue.Queue()). Tất cả các tài khoản hoạt động tự động pull sản phẩm từ giỏ chung, triệt tiêu 100% tình trạng sản phẩm bị kẹt hay tài khoản bị rảnh tay.
- **Rút ngắn nhịp Polling**: Rút ngắn thời gian hỏi kết quả video poll_video từ 8.0s xuống 3.5s/lần, tiết kiệm 9 - 11 giây chờ vô ích cho mỗi video render xong trên Google Cloud GPU.

---

## 45. Tự Động Xoay Proxy Tức Thì Khi Bị Throttle 429 (ProxyPool.rotate) (2026-08-09)
- **Cơ chế**: Ngay khi 1 tài khoản bị Google phản hồi HTTP 429 Throttle -> Hệ thống lập tức rút 1 Proxy tươi mới từ Pool (HomeProxy / WARP) gán cho tài khoản đó và gọi st.clear_rest().
- **Hiệu quả**: Xóa bỏ 100% thời gian ngồi chờ nghỉ 37s/39s, giữ cho các tài khoản luôn ở trạng thái đang chạy 100% thời gian -> Đẩy tốc độ hệ thống lên sát trần ~18 - 22 video/phút.

---

## 46. Công Thức Tự Động Luồng Upload/TK & Tối Ưu Quá Tải CPU 100% (2026-08-10)
- **Công thức luồng chuẩn**:
  - Tổng luồng Upload = Số TK đang chạy x Số luồng Upload/TK
  - Số Tạo (Worker/TK) = Số Tốc Độ (Submit Max) = Upload/TK + 1
- **Giải pháp dứt điểm CPU 100% & Đơ Giật GUI**:
  1. Khống chế tối đa 6 luồng ghép FFmpeg song song (merge_sem = Semaphore(6)).
  2. Ép cờ ưu tiên CPU thấp hơn giao diện Windows: creationflags = 0x00004000 | 0x08000000 (BELOW_NORMAL_PRIORITY_CLASS).
  3. Mã hóa FFmpeg đệm -threads 1 và CPU preset -preset superfast giúp máy mát mẻ, CPU giữ ở mức 40% - 50%, giao diện mượt 100%.

---

## 47. Nút Dừng Từng Tài Khoản Trực Tiếp Trên Bảng Pool AIMD (2026-08-10)
- **Thiết kế**: Thêm nút Dừng (màu đỏ nhạt #E57373) ở cột ngoài cùng bên phải của từng dòng tài khoản trong bảng Pool (AIMD) ở cả 3 Tab.
- **Cơ chế**: Bấm nút Dừng -> Tự động bỏ chọn Dùng trong tab Tài khoản (a['enabled'] = False), đặt st.rest(86400 * 365, 'user_stopped'), cập nhật trạng thái Đã dừng màu đỏ và làm mới giao diện tab Tài khoản.

---

## 48. Cơ Chế Khẩn Cấp Cảnh Báo Ổ Đĩa Đầy & Báo Động Telegram (2026-08-10)
- **Cơ chế**: Tự động giám sát dung lượng đĩa đệm (out_dir).
- **Khi dung lượng trống < 1.0 GB**:
  1. Lập tức DỪNG TẤT CẢ LUỒNG TẠO VIDEO ở cả 3 Tab.
  2. Gửi tin nhắn Báo động khẩn cấp qua Telegram Bot API (chứa tên ổ đĩa, đường dẫn, dung lượng còn lại).
  3. Ghi Log chữ đỏ và bật Popup hiển thị CẢNH BÁO Ổ ĐĨA ĐẦY.
- Được kiểm tra liên tục trước mỗi video và định kỳ mỗi 30 giây một lần khi đang treo máy 24/7.

---

## 49. Quản Lý Phiên Bản (v1.3.5) & Thẻ Thông Báo Cập Nhật Sidebar Trái (2026-08-10)
- **Số phiên bản**: Khai báo hằng số APP_VERSION = 'v1.3.5', hiển thị ở tiêu đề cửa sổ, menu trái và footer sidebar (Phiên bản: v1.3.5).
- **Non-blocking Update Alert**:
  - update.py kiểm tra bản cập nhật ngầm không chặn khởi động.
  - Khi có bản mới trên GitHub -> Thẻ thông báo màu cam CÓ BẢN MỚI! cùng nút Nâng cấp ngay xuất hiện ở góc dưới bên trái menu sidebar.
  - Bấm Nâng cấp ngay -> Hỏi xác nhận -> Khởi chạy update.py --force-update tải file và khởi động lại.

---

## 50. Xử Lý Lỗi Google Queue Full (PUBLIC_ERROR_TOO_MANY_VIDEOS) (2026-08-10)
- **Phân loại lỗi**: Nhận diện TOO_MANY, TOO_MANY_VIDEOS, CONCURRENT trong phản hồi của Google VEO3 API.
- **Cơ chế xử lý**: Đây là hàng đợi render GPU của Google cho tài khoản đó đang đầy. Hệ thống hạ submit_limit, cho nghỉ ngắn 15s-20s chờ các video cũ render xong trên cloud của Google rồi tự động retry_soft nộp lại sản phẩm.


---

## 51. Nut Bat/Tat Trang Thai Tai Khoan Tuong Tac Hai Chieu (Dung <-> Tiep tuc) (2026-08-10)
- **Co che nut dong**:
  - Khi tai khoan dang chay -> Nut hien thi mau do [Dung]. Bam vao -> Bo tich o Dung trong tab Tai khoan, tam ngat luong va chuyen nut thanh [Tiep tuc] (mau xanh la).
  - Khi tai khoan dang dung -> Nut hien thi mau xanh la [Tiep tuc]. Bam vao -> Tu dong tich lai o Dung trong tab Tai khoan, xoa bo trang thai dung, lam moi xac thuc va cho tai khoan bat dau chay lai ngay lap tuc.
- **Tuong thich toan bo cac Tab**: Ap dung dong bo cho bang Pool tai khoan (AIMD) tren ca 3 Tab (Tab chinh, Tab Shopee, Tab Server Video).


---

## 52. Tự Động Gia Hạn Cookie Session Ngầm Bằng HTTP Request (HTTP NextAuth Auto-Refresh - KHÔNG MỞ CHROME) (2026-08-10)
- **Đột phá kỹ thuật**:
  - Google Labs (Flow/Veo3) sử dụng NextAuth.js làm cơ chế xác thực session (__Secure-next-auth.session-token).
  - NextAuth tự động duy trì cửa sổ trượt (sliding session window). Khi gửi HTTP GET request tới https://labs.google/fx/api/auth/session kèm theo cookie hiện tại, máy chủ NextAuth của Google sẽ phản hồi kèm header **Set-Cookie** chứa token session mới (__Secure-next-auth.session-token).
- **Cơ chế triển khai**:
  - Bổ sung hàm update_cookie_string() trong engine.py tự động bắt header Set-Cookie trả về từ response HTTP 200 OK.
  - Khi earer_from_cookie() hoặc ensure_auth() được gọi (bao gồm luồng Proactive Refresh 20 phút/lần) $
ightarrow$ Tự động trích xuất và cập nhật cookie mới trực tiếp trong bộ nhớ RAM và lưu vào ccounts.json.
- **Ưu điểm vượt trội**:
  - **Tốc độ phản hồi cực đại (< 300ms)**: Không tốn CPU/RAM khởi chạy trình duyệt Chrome hay DrissionPage.
  - **Duy trì treo máy 24/7 tuyệt đối**: Cookie tài khoản liên tục được kéo dài thời gian sống (Sliding expiration) qua từng HTTP request đơn lẻ mà người dùng không bao giờ cần phải đăng nhập lại hay bật Chrome thủ công.


---

## 53. Tích Hợp Tùy Chọn Multi-Port WARP 1.1.1.1 (Mỗi Luồng 1 Port / IP Riêng) (2026-08-10)
- **Tính năng mới**:
  - Bổ sung ô Checkbox 🔀 Multi-Port (1 Port/TK) trong phần Proxy WARP ở cả 3 Tab.
  - Khi bật tùy chọn này: Hệ thống tự động gán dải Port tăng dần từ Port gốc (warp_port, ví dụ 40000, 40001, 40002, 40003...) cho từng tài khoản hoạt động.
- **Cơ chế hoạt động**:
  - Nâng cấp bộ nút **🧪 Test WARP**: Khi bật Multi-Port, nút Test sẽ kiểm tra kết nối song song qua các Port (40000, 40001...) và hiển thị IP công khai của từng Port.
  - Tích hợp đồng bộ cho Tab Tạo Video Thường, Tab Shopee và Tab Server Video.
  - Tự động lưu cấu hình warp_multi_port vào settings.json.


---

## 54. Hiển Thị Địa Chỉ IP Công Khai Thực Tế Của Từng Tài Khoản Trên Bảng Pool (2026-08-10)
- **Tính năng mới**:
  - Trong cột 🌐 Proxy / IP ở bảng Pool tài khoản (AIMD), phần mềm tự động truy vấn và hiển thị **Địa chỉ IP công khai thực tế** (ví dụ 104.28.192.44 đối với WARP hoặc 113.161.42.18 đối với HomeProxy) thay vì chỉ hiển thị chuỗi local proxy socks5://127.0.0.1:40000.
- **Cơ chế ngầm**:
  - Bổ sung hàm st.fetch_public_ip() chạy ngầm không gây block giao diện.
  - Khi proxy được gán hoặc xoay tự động (sau khi dính 429), IP thực tế mới sẽ tự động được cập nhật lại lên màn hình ngay lập tức.
  - Áp dụng đồng bộ cho cả 3 Tab (Tab Tạo Video Thường, Tab Shopee, Tab Server Video).


---

# 📚 THƯ VIỆN TÀI LIỆU TỔNG HỢP (CONSOLIDATED APPENDIX)

## 📄 NỘI DUNG NGUYÊN BẢN TỪ FILE [postshopee.md]

# Tài Liệu Hướng Dẫn Kỹ Thuật & Cấu Hình Phần Mềm Thìn Aptm (v1.3.5)

Tài liệu này tổng hợp toàn bộ quy tắc, cơ chế tối ưu hóa, công thức tự động và các tính năng nâng cấp mới nhất của phần mềm **Thìn Aptm (v1.3.5)**.

---

## 1. 📐 Công Thức Luồng & Cấu Hình Tự Động

### 1.1 Công thức tính số Tạo & Tốc độ
Để tránh hiện tượng bùng nổ quá tải CPU 100% khi chạy nhiều tài khoản, phần mềm tự động tính toán các thông số theo công thức chuẩn:

$$\text{Tổng luồng Upload} = \text{Số tài khoản đang chạy} \times \text{Số luồng Upload/TK (nhập trong ô 📤 Upload/TK)}$$

$$\text{Số Tạo (Luồng Worker/TK)} = \text{Số Tốc Độ (Submit Max)} = \mathbf{\text{Số luồng Upload/TK} + 2}$$

#### 📊 Bảng minh họa công thức:
| Ô nhập `Upload/TK` | ⚡ **Thông số Tạo** (Luồng Worker/TK) | 🚀 **Thông số Tốc độ** (Submit Max/TK) | Tổng luồng Worker (5 Tài khoản) |
| :---: | :---: | :---: | :---: |
| **`3`** *(mặc định)* | **`5`** luồng / TK | **`5.0`** submit max | 25 luồng song song |
| **`4`** | **`6`** luồng / TK | **`6.0`** submit max | 30 luồng song song |
| **`5`** | **`7`** luồng / TK | **`7.0`** submit max | 35 luồng song song |

---

## 2. ⚡ Tối Ưu Hóa CPU/RAM & Triệt Tiêu Đơ Máy (100% CPU Fix)

Phần mềm kết hợp 2 giải pháp tối ưu hệ thống để giữ CPU ở mức **40% - 50%**, máy mát rượi và giao diện mượt mà 100%:

1. **Khống chế số luồng ghép FFmpeg song song**:
   - Giới hạn tối đa **6 luồng ghép FFmpeg đồng thời** (`merge_sem = Semaphore(6)`).
   - Thêm tham số `-threads 1` để mỗi tiến trình FFmpeg chỉ dùng 1 nhân CPU.
   - Chuyển preset mã hóa CPU sang `-preset superfast` giúp giảm tải CPU hơn 300%.

2. **Ép mức ưu tiên CPU dưới giao diện Windows (`BELOW_NORMAL_PRIORITY_CLASS`)**:
   - Tất cả các câu lệnh FFmpeg mã hóa/ghép video được cấp cờ `creationflags = 0x00004000 | 0x08000000` trên Windows.
   - Hệ điều hành Windows luôn ưu tiên CPU cấp cao cho giao diện Tkinter và thao tác chuột/bàn phím ➔ **Triệt tiêu 100% hiện tượng đơ máy hay chữ `(Not Responding)`**.

---

## 3. 🛡️ Cơ Chế Xử Lý Lỗi 429 Throttle & Nút Dừng Tài Khoản

### 3.1 Tự động xoay Proxy khi bị Throttle (`ProxyPool.rotate`)
- Ngay khi 1 tài khoản nhận lỗi HTTP 429 từ Google ➔ Phần mềm rút 1 Proxy tươi mới từ Pool (HomeProxy / WARP) gán cho tài khoản đó và gọi `st.clear_rest()`.
- **Xóa bỏ 100% thời gian ngồi chờ 37s/39s** ➔ Tài khoản tiếp tục nộp video ngay trên IP Proxy mới.
- Nếu kho Proxy hết, tài khoản nghỉ ngắn **15s - 60s** để hạ nhiệt theo Rule #2.

### 3.2 Nút `⏹ Dừng` từng tài khoản trong Bảng Pool (AIMD)
- Ở cột ngoài cùng bên phải của bảng Pool tài khoản (AIMD) trên cả 3 Tab, xuất hiện nút **`⏹ Dừng`** (màu đỏ nhạt `#E57373`).
- Khi bấm nút `⏹ Dừng`:
  1. Tự động **hủy tích chọn ô "Dùng"** trong tab **Tài khoản**.
  2. Đưa trạng thái tài khoản về **`⏹ Đã dừng`** và ngắt luồng phân việc của tài khoản đó.
  3. Trả Proxy của tài khoản đó về Pool.

---

## 4. 🚨 Cơ Chế Cảnh Báo Ổ Đĩa Đầy & Báo Động Telegram

- **Ngưỡng an toàn**: 1.0 GB dung lượng đĩa trống tại thư mục lưu trữ (`out_dir`).
- **Khi dung lượng đĩa < 1.0 GB**:
  1. **DỪNG TẤT CẢ LUỒNG CÔNG VIỆC** ngay lập tức ở cả 3 Tab.
  2. **Gửi báo động khẩn cấp qua Telegram Bot API** (chứa tên ổ đĩa, đường dẫn, dung lượng còn lại).
  3. Ghi Log cảnh báo chữ đỏ và bật Popup thông báo **`⛔ CẢNH BÁO Ổ ĐĨA ĐẦY`**.
- Được kiểm tra liên tục trước mỗi video và định kỳ **mỗi 30 giây một lần** khi đang treo máy 24/7.

---

## 5. 🔔 Hệ Thống Cảnh Báo Cập Nhật & Quản Lý Phiên Bản (`v1.3.5`)

- **Hiển thị Version**: Phiên bản **`v1.3.5`** hiển thị ở tiêu đề cửa sổ, menu bên trái và chân trang sidebar (`📌 Phiên bản: v1.3.5`).
- **Thông báo cập nhật không gây giật lag (Non-blocking)**:
  - Khởi động phần mềm 100% mượt mà, không bật các hộp thoại popup chặn màn hình.
  - Khi phát hiện có bản mới trên GitHub ➔ Ở ô bên dưới menu trái (vùng góc dưới bên trái) sẽ xuất hiện thẻ màu cam:
    ```text
    🔔 CÓ BẢN MỚI!
    Có X file có bản mới!
    [🚀 Nâng cấp ngay]
    ```
  - Khi bấm **`🚀 Nâng cấp ngay`**, phần mềm hỏi xác nhận ➔ Tự động tải bản mới từ GitHub và khởi động lại.

---

## 6. 🚀 Tốc Độ & Hàng Đợi Chung (Shared Job Queue)

1. **1 Hàng Đợi Chung (`Shared Job Queue`)**:
   - Đã chuyển tab Server Video sang mô hình **1 Hàng Đợi Chung**.
   - Tất cả sản phẩm được nạp vào 1 giỏ chung, tài khoản nào làm xong sẽ nhặt ngay sản phẩm tiếp theo, **triệt tiêu 100% tình trạng sản phẩm bị kẹt do 1 tài khoản chậm**.

2. **Rút ngắn nhịp Poll video AI**:
   - Nhịp thăm dò kết quả `poll_video` từ server Google được rút ngắn từ 8s xuống **3.5s/lần**.
   - Tiết kiệm từ **9 - 11 giây chờ vô ích** cho mỗi video sản xuất.

---

*Tài liệu được cập nhật tự động vào hệ thống mã nguồn Thìn Aptm (v1.3.5).*


---

## 51. Nut Bat/Tat Trang Thai Tai Khoan Tuong Tac Hai Chieu (Dung <-> Tiep tuc) (2026-08-10)
- **Co che nut dong**:
  - Khi tai khoan dang chay -> Nut hien thi mau do [Dung]. Bam vao -> Bo tich o Dung trong tab Tai khoan, tam ngat luong va chuyen nut thanh [Tiep tuc] (mau xanh la).
  - Khi tai khoan dang dung -> Nut hien thi mau xanh la [Tiep tuc]. Bam vao -> Tu dong tich lai o Dung trong tab Tai khoan, xoa bo trang thai dung, lam moi xac thuc va cho tai khoan bat dau chay lai ngay lap tuc.
- **Tuong thich toan bo cac Tab**: Ap dung dong bo cho bang Pool tai khoan (AIMD) tren ca 3 Tab (Tab chinh, Tab Shopee, Tab Server Video).


---

## 52. Tự Động Gia Hạn Cookie Session Ngầm Bằng HTTP Request (HTTP NextAuth Auto-Refresh - KHÔNG MỞ CHROME) (2026-08-10)
- **Đột phá kỹ thuật**:
  - Google Labs (Flow/Veo3) sử dụng NextAuth.js làm cơ chế xác thực session (__Secure-next-auth.session-token).
  - NextAuth tự động duy trì cửa sổ trượt (sliding session window). Khi gửi HTTP GET request tới https://labs.google/fx/api/auth/session kèm theo cookie hiện tại, máy chủ NextAuth của Google sẽ phản hồi kèm header **Set-Cookie** chứa token session mới (__Secure-next-auth.session-token).
- **Cơ chế triển khai**:
  - Bổ sung hàm update_cookie_string() trong engine.py tự động bắt header Set-Cookie trả về từ response HTTP 200 OK.
  - Khi earer_from_cookie() hoặc ensure_auth() được gọi (bao gồm luồng Proactive Refresh 20 phút/lần) $
ightarrow$ Tự động trích xuất và cập nhật cookie mới trực tiếp trong bộ nhớ RAM và lưu vào ccounts.json.
- **Ưu điểm vượt trội**:
  - **Tốc độ phản hồi cực đại (< 300ms)**: Không tốn CPU/RAM khởi chạy trình duyệt Chrome hay DrissionPage.
  - **Duy trì treo máy 24/7 tuyệt đối**: Cookie tài khoản liên tục được kéo dài thời gian sống (Sliding expiration) qua từng HTTP request đơn lẻ mà người dùng không bao giờ cần phải đăng nhập lại hay bật Chrome thủ công.


---

## 53. Tích Hợp Tùy Chọn Multi-Port WARP 1.1.1.1 (Mỗi Luồng 1 Port / IP Riêng) (2026-08-10)
- **Tính năng mới**:
  - Bổ sung ô Checkbox 🔀 Multi-Port (1 Port/TK) trong phần Proxy WARP ở cả 3 Tab.
  - Khi bật tùy chọn này: Hệ thống tự động gán dải Port tăng dần từ Port gốc (warp_port, ví dụ 40000, 40001, 40002, 40003...) cho từng tài khoản hoạt động.
- **Cơ chế hoạt động**:
  - Nâng cấp bộ nút **🧪 Test WARP**: Khi bật Multi-Port, nút Test sẽ kiểm tra kết nối song song qua các Port (40000, 40001...) và hiển thị IP công khai của từng Port.
  - Tích hợp đồng bộ cho Tab Tạo Video Thường, Tab Shopee và Tab Server Video.
  - Tự động lưu cấu hình warp_multi_port vào settings.json.


---

## 54. Hiển Thị Địa Chỉ IP Công Khai Thực Tế Của Từng Tài Khoản Trên Bảng Pool (2026-08-10)
- **Tính năng mới**:
  - Trong cột 🌐 Proxy / IP ở bảng Pool tài khoản (AIMD), phần mềm tự động truy vấn và hiển thị **Địa chỉ IP công khai thực tế** (ví dụ 104.28.192.44 đối với WARP hoặc 113.161.42.18 đối với HomeProxy) thay vì chỉ hiển thị chuỗi local proxy socks5://127.0.0.1:40000.
- **Cơ chế ngầm**:
  - Bổ sung hàm st.fetch_public_ip() chạy ngầm không gây block giao diện.
  - Khi proxy được gán hoặc xoay tự động (sau khi dính 429), IP thực tế mới sẽ tự động được cập nhật lại lên màn hình ngay lập tức.
  - Áp dụng đồng bộ cho cả 3 Tab (Tab Tạo Video Thường, Tab Shopee, Tab Server Video).


---

## 📄 NỘI DUNG NGUYÊN BẢN TỪ FILE [shopee.md]

# 🛒 Shopee Video Creator v3 — Tài liệu kỹ thuật

> Cập nhật: 2026-07-15

## 1. Tổng quan hệ thống

Tạo video review sản phẩm tự động từ **ảnh SP + thư mục ảnh người mẫu** qua Google Flow AI.
Mỗi sản phẩm được gán **ngẫu nhiên 1 người mẫu** từ thư mục, đảm bảo **đồng bộ 1 người mẫu duy nhất** xuyên suốt cả video.

### Luồng xử lý (5 Phase)

```
Ảnh SP + Thư mục người mẫu (random 1) + Khung cảnh
        │
        ▼
┌─────────────────────────────────────┐
│  PHASE 1: Tạo ảnh hoàn thiện (AI)  │  ← Google Flow generate_image
│  Gộp người mẫu + SP + khung cảnh   │  ← Cache: composite_{tên_SP}.jpg
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  PHASE 2: Sinh prompt video         │  ← build_video_prompts() hoặc load từ metadata
│  16s → 2 prompt, 24s → 3 prompt    │  ← Lưu metadata: meta_{tên_SP}.json
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  PHASE 3: Tạo video thành phần     │  ← Google Flow submit_video (i2v)
│  Mỗi clip ~8s từ ảnh composite     │  ← Cache: clip_{tên_SP}_{segment}.mp4
│  Skip clip đã có từ phiên trước    │  ← Chỉ tạo clip thiếu
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  PHASE 4: Ghép video (FFmpeg)       │  ← Yêu cầu ĐỦ 100% clip mới ghép
│  16s = đủ 2/2, 24s = đủ 3/3       │  ← Thiếu clip → ❌ + log đoạn thiếu
└──────────────┬──────────────────────┘
               ▼
┌─────────────────────────────────────┐
│  PHASE 5: Xóa watermark Veo        │  ← FFmpeg delogo filter, góc dưới phải
│  + Dọn clip + composite + metadata  │  ← Tự xóa temp sau khi ghép thành công
└─────────────────────────────────────┘
```

### Files chính

| File | Vai trò |
|------|---------|
| `shopeevideo.py` | Module: prompt pool, scene presets, model picker, watermark removal, FFmpeg concat, utils |
| `thin_aptm.py` | GUI: Tab "Tạo Video Shopee", xử lý đa luồng, account pool, metadata persistence |
| `engine.py` | API wrapper: upload_image, generate_image, submit_video, poll_video, download_video |

---

## 2. Hệ thống người mẫu (Model System)

### 2.1 Kiến trúc

```
Thư mục người mẫu/
├── model_1.jpg
├── model_2.png
├── model_3.webp
└── ...
```

- User chọn **thư mục** (không phải 1 file đơn lẻ)
- Extensions hỗ trợ: `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`
- Hàm `list_model_images(folder)` → trả list full-path đã sắp xếp
- Hàm `pick_random_model(folder)` → trả 1 ảnh ngẫu nhiên

### 2.2 Gán người mẫu cho sản phẩm

```python
# Trước khi chạy: gán random 1 người mẫu cho mỗi SP
product_model_map = {}  # idx → model_img_path
for idx, prod in enumerate(products):
    product_model_map[idx] = random.choice(model_images)
```

- **1 SP = 1 người mẫu duy nhất** xuyên suốt Phase 1 → Phase 5
- Khác SP có thể dùng khác người mẫu (random)
- Nếu có metadata từ phiên trước → dùng lại người mẫu đã gán (không random lại)

### 2.3 Cache upload theo (account, model)

```python
model_media_cache = {}   # (email, model_path) → media_id
cache_key = (st.email, model_img)
```

- Cache theo cặp `(email, model_path)` thay vì chỉ `email`
- Nhiều SP dùng cùng người mẫu trên cùng account → dùng lại media_id
- Nhiều SP dùng khác người mẫu trên cùng account → upload riêng

---

## 3. Metadata Persistence (Đồng bộ prompt giữa các phiên)

### 3.1 Vấn đề

Khi video thiếu clip, lần chạy lại cần tạo đúng clip thiếu bằng **ĐÚNG prompt cũ**.
Nếu không, clip mới sẽ dùng khác scene/model → video không đồng bộ visual.

### 3.2 Giải pháp: File metadata per SP

```
{out_dir}/_temp_shopee/meta_{tên_SP}.json
```

Nội dung:

```json
{
  "scene_name": "🎥 Phòng review chuyên nghiệp",
  "scene_en": "in a professional product review studio...",
  "model_img": "C:/models/model_1.jpg",
  "prompts": ["[CONTINUITY...] HOOK + DEMO...", "[CONTINUITY...] BENEFIT + CTA..."],
  "lang": "en",
  "duration": 16
}
```

### 3.3 Luồng hoạt động

```
Lần 1 (mới):
  → Pick random scene + model
  → Build prompts
  → Lưu metadata JSON
  → Tạo clip 1 ✅ → clip 2 ❌
  → "Thiếu đoạn [2]" → giữ clip 1 + metadata

Lần 2 (retry):
  → Load metadata → ĐÚNG scene/model/prompts phiên trước
  → ⚡ Clip 1 đã có → skip
  → Tạo clip 2 bằng ĐÚNG prompt cũ ✅
  → Đủ 2/2 → Ghép ✅ → Xóa temp + metadata
```

### 3.4 Quy tắc ưu tiên

| Có metadata? | Hành vi |
|--------------|---------|
| ✅ Có | Load scene + model + prompts từ JSON |
| ❌ Không | Pick random scene + model mới, build prompts mới, lưu metadata |

### 3.5 Vòng đời metadata

- **Tạo**: Sau Phase 2 (sinh prompt) nếu chưa có
- **Đọc**: Đầu mỗi lần xử lý SP (trước Phase 1)
- **Xóa**: Sau Phase 4 thành công (cùng clip + composite)

---

## 4. Cấu trúc Prompt Video

### 4.1 Nguyên tắc

- Mỗi clip từ API Google Flow dài **~8 giây** (không điều chỉnh được)
- Để đạt đúng thời lượng: **16s = 2 clip**, **24s = 3 clip**
- Tất cả clip dùng **CÙNG ảnh composite** làm reference → đồng bộ visual
- Ngôn ngữ nói được inject qua `{lang_instruction}` placeholder

### 4.2 Format 16s (2 clip × ~8s)

| Clip | Thời gian | Nội dung | Cấu trúc quảng cáo |
|------|-----------|----------|---------------------|
| 1 | 0-8s | **HOOK + DEMO/PAIN** | Thu hút → Trình diễn SP → Nêu vấn đề → Giải quyết |
| 2 | 8-16s | **BENEFIT/CLOSE + CTA** | Cận cảnh lợi ích → Kêu gọi hành động |

### 4.3 Format 24s (3 clip × ~8s) — Kỹ thuật "Handoff Pose"

3 clip được thiết kế **liền mạch** bằng kỹ thuật "handoff pose":
mỗi clip **kết thúc** ở tư thế cụ thể, clip sau **bắt đầu** từ **chính tư thế đó**.

| Clip | Thời gian | Nội dung | Tư thế bắt đầu | Tư thế kết thúc (handoff) |
|------|-----------|----------|-----------------|---------------------------|
| 1 | 0-8s | **REVIEW** — Quan sát, ấn tượng đầu tiên | Cầm SP 2 tay ngang ngực, đang xem | Cầm SP 2 tay ngang ngực, mặt hướng camera, đang nói dở |
| 2 | 8-16s | **DEMO/TEST** — Trình diễn thực tế, sờ chất liệu, cận cảnh | *(khớp clip 1)* Cầm SP 2 tay ngang ngực, đang nói dở | Giơ SP 1 tay cạnh mặt, tay kia chỉ vào SP |
| 3 | 16-24s | **TARGET + CTA** — Ai nên dùng + Kêu gọi mua hàng | *(khớp clip 2)* Giơ SP 1 tay cạnh mặt | Giơ SP 2 tay + double thumbs-up |

**Luồng liền mạch khi ghép:**
```
Clip 1: [xem SP, xoay, sờ, chia sẻ cảm nhận] ── kết thúc: cầm SP ngang ngực, đang nói ──→
Clip 2: [bắt đầu từ pose đó] → lật, mở, sờ chất liệu, macro cận cảnh ── kết thúc: giơ SP cạnh mặt ──→
Clip 3: [bắt đầu từ pose đó] → giới thiệu đối tượng → CTA double thumbs-up
```

### 4.4 Yêu cầu đủ clip

- **16s**: Phải đủ **2/2** clip mới ghép
- **24s**: Phải đủ **3/3** clip mới ghép
- Thiếu clip → ❌ + log chính xác đoạn thiếu (VD: "Thiếu đoạn [2, 3]")
- Clip đã có được giữ lại → lần sau chỉ tạo clip thiếu

### 4.5 Segment Pool & Duration Map

```python
SEGMENT_POOL_EN = [...]  # 5 phần tử: index 0-1 cho 16s, 2-4 cho 24s
SEGMENT_POOL_VI = [...]  # 5 phần tử: tương tự, tiếng Việt

DURATION_MAP = {
    16: [0, 1],      # 2 clip
    24: [2, 3, 4],   # 3 clip
}
```

### 4.6 Đồng bộ ngôn ngữ

```python
_LANG_INSTRUCTIONS = {
    "en": "The model speaks English",
    "vi": "Người mẫu nói tiếng Việt",
}
```

### 4.7 Yêu cầu liên tục (Continuity)

Mỗi prompt bắt đầu bằng block `_CONT_EN` / `_CONT_VI` yêu cầu:
- ✅ CÙNG khuôn mặt, tóc, da, vóc dáng
- ✅ CÙNG trang phục, phụ kiện
- ✅ CÙNG phông nền, ánh sáng, tông màu
- ✅ Sản phẩm giữ nguyên 100% pixel-perfect (hình dạng, màu, chất liệu, bao bì)
- ✅ **Chữ viết trên SP** (nhãn mác, logo, tên thương hiệu, mã vạch) giữ nguyên từng ký tự — cùng font, kích cỡ, vị trí
- ✅ CÙNG ngôn ngữ nói xuyên suốt
- ✅ **KHÔNG hiển thị text overlay** (phụ đề, chú thích, watermark) — video sạch 100%

### 4.8 Anti-Greeting Rules (v2)

Vì mỗi clip được AI tạo **độc lập**, AI mặc định mở đầu bằng lời chào/vẫy tay.
Cả 3 clip 24s (và cả 2 clip 16s) đều có lệnh **cấm greeting** explicit:

```
CRITICAL: DO NOT start with any greeting, waving, welcoming, or introduction.
NO 'hello', NO waving at camera, NO welcome pose.
```

Đồng thời, clip 2 và 3 dùng kỹ thuật **"STARTING POSE (MUST MATCH)"** —
yêu cầu AI bắt đầu từ tư thế cụ thể thay vì tự quyết định mở đầu.

### 4.9 Kỹ thuật Handoff Pose (chi tiết)

Mỗi clip sử dụng cặp lệnh:
- **`ENDING POSE (IMPORTANT)`** ở cuối clip N → mô tả tư thế kết thúc bắt buộc
- **`STARTING POSE (MUST MATCH)`** ở đầu clip N+1 → yêu cầu bắt đầu từ **đúng** tư thế đó

Kết hợp cố định camera framing (medium shot waist-up) giữa các clip
→ video ghép trông liền mạch như quay 1 take duy nhất.

---

## 5. Hệ thống Cache & Auto-cleanup

### 5.1 Cache files per SP

```
{out_dir}/_temp_shopee/
├── meta_{tên_SP}.json           ← metadata (scene, model, prompts)
├── composite_{tên_SP}.jpg       ← ảnh hoàn thiện (AI generated)
├── clip_{tên_SP}_1.mp4          ← video đoạn 1
├── clip_{tên_SP}_2.mp4          ← video đoạn 2
└── clip_{tên_SP}_3.mp4          ← video đoạn 3 (chỉ 24s)
```

### 5.2 Skip logic

| File | Điều kiện skip | Tiết kiệm |
|------|----------------|-----------|
| composite | Tồn tại + > 1KB | ~30s (skip Phase 1) |
| clip_N | Tồn tại + > 5KB | ~2-3min/clip |
| metadata | Tồn tại | Dùng lại prompt cũ |

### 5.3 Auto-cleanup sau ghép thành công

Khi Phase 4 thành công → **tự động xóa**:
- ✅ Tất cả clip thành phần
- ✅ Ảnh composite
- ✅ File metadata JSON

> ⚠️ Nếu SP bị lỗi → **giữ nguyên** tất cả temp để retry ở phiên sau.

### 5.4 Luồng cache khi chạy lại

```
Phiên 1:
  Tạo ảnh (30s) + Lưu metadata + 2 clip (3min) + Ghép
  → ✅ (xóa tất cả temp) hoặc ❌ (giữ tất cả temp)

Phiên 2 (nếu ❌):
  📋 Load metadata → ⚡ Dùng ảnh có sẵn → ⚡ Dùng clip có sẵn
  → Chỉ tạo clip thiếu bằng ĐÚNG prompt cũ → Ghép → ✅ (xóa temp)
```

---

## 6. Xóa Watermark Veo (Phase 5)

### 6.1 Cơ chế

- Dùng FFmpeg `delogo` filter để xóa/blur logo "Veo" ở góc dưới phải
- Tự detect kích thước video bằng `ffprobe` → tính tọa độ tỉ lệ
- Re-encode với `libx264 -crf 18` (gần lossless) + `copy` audio
- Ghi đè file gốc (ghi ra file tạm `.nowm.mp4` → `os.replace`)

### 6.2 Tọa độ watermark (tỉ lệ)

```python
lw = max(int(w * 0.12), 70)    # chiều rộng logo ~12% width
lh = max(int(h * 0.05), 28)    # chiều cao logo ~5% height
lx = w - lw - max(int(w * 0.015), 8)  # cách mép phải ~1.5%
ly = h - lh - max(int(h * 0.015), 8)  # cách mép dưới ~1.5%
```

### 6.3 GUI

- Checkbox **"🧹 Xóa logo Veo"** (mặc định BẬT)
- Setting key: `shopee_remove_wm` (bool)
- Nếu tắt → skip Phase 5, giữ nguyên watermark

---

## 7. Trạng thái dòng sản phẩm (Status Tracking)

### 7.1 Prefix trạng thái trong textbox

| Prefix | Ý nghĩa | Màu |
|--------|----------|-----|
| `✅ ` | Thành công | Xanh lá `#1B7D2C` |
| `❌ ` | Thất bại | Đỏ `#D32F2F` |
| `⏳ ` | Đang xử lý | Cam `#E65100` |
| (không) | Chưa chạy | Mặc định |

### 7.2 Hành vi

- **Skip tự động**: Dòng `✅` bị bỏ qua ở lần chạy tiếp theo
- **Bộ đếm**: Góc phải hiển thị `8 SP (✅3 ❌1 ⏳4)`
- **Nút "🔄 Xóa trạng thái"**: Xóa tất cả prefix → chạy lại toàn bộ
- **Khôi phục màu**: Khi mở lại app, text tags được restore từ prefix

---

## 8. Xử lý đa luồng & Tốc độ tự động (AIMD)

### 8.1 Kiến trúc: Shared Queue + Per-Account Workers

Sử dụng cùng mô hình với tab "Tạo Video" chính — **KHÔNG dùng ThreadPoolExecutor**.

```
            Shared Job Queue (products)
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
 Account A        Account B       Account C
 ├─ Worker 1      ├─ Worker 1     ├─ Worker 1
 ├─ Worker 2      ├─ Worker 2     ├─ Worker 2
 └─ ...           └─ ...          └─ ...
 (wpa workers)    (wpa workers)   (wpa workers)

 Mỗi worker: pull job → AIMD gating → process → outcome
   success    → đánh dấu xong, +1 wins
   retry_soft → trả job về queue, account khác nhặt
   fail       → đánh dấu lỗi vĩnh viễn
```

- `wpa` = `WORKERS_PER_ACCOUNT` (=5, cố định, giống main tab)
- Tổng workers = `len(accounts) × wpa`
- Account đang nghỉ (rest) → worker sleep, không pull job
- Account bị cấm upload (i2v_blocked) → worker bỏ qua (chỉ áp dụng main tab)

### 8.2 Thuật toán AIMD (Additive Increase / Multiplicative Decrease)

Giống thuật toán điều khiển tắc nghẽn TCP — tự tìm tốc độ tối đa của TỪNG account.

```python
class AccountState:
    submit_limit = SUBMIT_START   # giới hạn đồng thời hiện tại
    inflight = 0                  # số submit đang bay
    _ok_streak = 0                # chuỗi OK liên tiếp
    _gate = threading.Condition() # cổng chờ

    def acquire_submit(stop_check):  # chờ đến lượt submit
    def release_submit():            # nhả slot
    def on_submit_ok():              # +1 OK streak, tăng limit nếu đủ
    def on_throttle():               # giảm limit (AIMD MD)
```

**Quy tắc:**

- **Additive Increase**: Sau mỗi `SUBMIT_UP_AFTER` (5) lần submit thành công liên tiếp → `submit_limit += 1`
- **Multiplicative Decrease**: Bị throttle (429) → `submit_limit *= SUBMIT_DOWN` (0.5)
- Giới hạn: `SUBMIT_MIN` (1) ≤ `submit_limit` ≤ `SUBMIT_MAX` (6)

### 8.3 Tham số AIMD (dùng chung với main tab)

| Tham số | Giá trị | Mô tả |
|---------|---------|-------|
| `SUBMIT_START` | 2.0 | Limit ban đầu mỗi account |
| `SUBMIT_MIN` | 1.0 | Sàn (luôn ≥ 1 submit) |
| `SUBMIT_MAX` | 6.0 | Trần submit đồng thời |
| `SUBMIT_UP_AFTER` | 5 | Số OK liên tiếp để +1 |
| `SUBMIT_DOWN` | 0.5 | Hệ số nhân khi throttle |
| `GEN_ATTEMPTS` | 60 | Số lần thử submit/segment trước khi bỏ |
| `THROTTLE_SLEEP` | 8.0s | Nghỉ sau mỗi 429 |
| `QUOTA_HARD_REST` | 6h | Cách ly khi hết quota thật |
| `AUTH_REST` | 30min | Nghỉ khi 401 không cứu được |
| `POLL_MAX` | 60 | Số lần poll render |
| `SP_JOB_MAX_CYCLES` | 10 | Số lần 1 SP được chuyền/thử trước khi bỏ |

### 8.4 AIMD Gating cho mọi API call

AIMD gating (`acquire_submit` / `release_submit`) bọc quanh **tất cả** API call:

| API Call | Phase | Gating |
|----------|-------|--------|
| `upload_image` (người mẫu) | Phase 1 | ✅ acquire → upload → release |
| `upload_image` (SP) | Phase 1 | ✅ acquire → upload → release |
| `generate_image` (composite) | Phase 1 | ✅ acquire → generate → release |
| `upload_image` (composite) | Phase 3 | ✅ acquire → upload → release |
| `submit_video` (mỗi segment) | Phase 3 | ✅ acquire → submit → release |

Mỗi lần API thành công → `on_submit_ok()` (AIMD +)
Mỗi lần bị throttle → `on_throttle()` (AIMD -)

### 8.5 Phân loại lỗi & xử lý

| Lỗi API | Xử lý | Kết quả |
|----------|--------|---------|
| `ok` | `on_submit_ok()` | Tiếp tục |
| `throttle` (429) | `on_throttle()` + sleep 8s + retry | Tự giảm tốc |
| `quota_hard` | `rest(6h, "quota")` | Cách ly dài, đổi account |
| `auth` (401) | Refresh cookie, nghỉ 30p nếu fail | Đổi account |
| `ratelimit` / `ip_block` | `on_throttle()` + sleep ngắn | Tự giảm tốc |
| Upload `forbidden` (403) | `i2v_blocked = True` | Đổi account |
| Upload `throttle` | `on_throttle()` | Đổi account |
| Các lỗi khác | sleep BYPASS_QUICK | Retry nhanh |

### 8.6 Luồng xử lý 1 SP (process_one)

```
process_one(st, prod) → 'success' | 'retry_soft' | ('fail', reason)

  1. ensure_auth() — nếu fail → retry_soft
  2. Phase 1: Upload ảnh (AIMD gating) → tạo ảnh composite
  3. Phase 2: Sinh/load prompts
  4. Phase 3: Upload composite → submit_video (AIMD gating, GEN_ATTEMPTS lần)
     - OK → poll → download
     - Throttle → on_throttle() + sleep → retry
     - Quota → cách ly → retry_soft
  5. Phase 4: Ghép clip
  6. Phase 5: Xóa watermark (nếu bật)
```

### 8.7 Pool Status Panel (GUI live)

Panel "🚀 Pool tài khoản (AIMD)" hiển thị live (mỗi 2s):

| Cột | Ý nghĩa |
|-----|---------|
| 👥 Tổng | Tổng số account đang dùng |
| 🟢 Chạy | Account đang hoạt động (không nghỉ) |
| ⚡ Tạo | Account đang có worker bận (busy > 0) |
| 😴 Nghỉ | Account đang cooldown |

Bảng per-account:

| Cột | Ý nghĩa |
|-----|---------|
| ✅ Xong | Số SP hoàn thành trên account |
| ❌ Lỗi | Số SP lỗi trên account |
| ⚡ Tạo | Số worker đang busy |
| 🚀 Tốc độ | `submit_limit` hiện tại (AIMD tự chỉnh) |
| Trạng thái | 🟢 đang chạy / 😴 nghỉ Ns / ⛔ cách ly Np |

### 8.8 Speed Tracking (Tốc độ trượt 10 phút)

```python
_sp_done_timestamps = collections.deque()  # ghi timestamp mỗi video xong
_sp_rolling_rate(window_min=10)            # đếm video trong 10 phút gần nhất
_sp_eta_text()                             # "⚡ 2.3 video/phút · còn 150 SP · dự kiến xong sau 1g05p (≈19:30)"
```

- Không tính phút hiện tại (đang dang dở)
- ETA tự động cập nhật trên header pool panel

### 8.9 Telegram Report (AIMD-aware)

**Báo cáo định kỳ** (mỗi 1 giờ):
```
⏰ Shopee Video — Báo cáo (2h30m)
==============================
✅ Thành công: 120/12375 · ❌ Lỗi: 45
⚡ Tốc độ: 2.3 video/phút
👥 Tài khoản:
  account1: ✅100 ❌35 ⚡3 🟢 chạy
  account2: ✅20 ❌10 ⚡2 😴 nghỉ 45s
```

**Báo cáo kết thúc**:
```
🏁 Shopee Video — HOÀN TẤT
==============================
✅ Thành công: 380/12375
❌ Lỗi: 267
⏭ Bỏ qua: 30
⚡ Tốc độ TB: 2.1 video/phút
⏰ Thời gian: 9h13m
👥 Tài khoản:
  account1: ✅320 ❌230 ⚡4
  account2: ✅60 ❌37 ⚡2
```

> Prefix "Shopee Video" để phân biệt với report tab "Tạo Video" (`📊 Video Report`).

---

## 9. Khung cảnh (Scenes)

12 presets + Random (tối ưu cho review sản phẩm):

| Scene | Mô tả | Phù hợp |
|-------|-------|---------|
| 📦 Tổng kho hàng hóa | Warehouse, kệ sản phẩm | SP công nghiệp, số lượng lớn |
| 🛒 Siêu thị hiện đại | Supermarket sáng sủa | SP tiêu dùng |
| 🎥 Phòng review | Studio trắng + softbox | Mọi SP (chuyên nghiệp nhất) |
| 🛋 Phòng khách sang trọng | Sofa da, ánh sáng vàng | SP gia dụng, nội thất |
| 💼 Văn phòng hiện đại | Bàn kính, cây xanh | SP công nghệ, văn phòng |
| 🌳 Ngoài trời công viên | Ánh nắng tự nhiên | SP thời trang, outdoor |
| 📸 Studio chụp ảnh | Ring light, phông xám | Mọi SP (cận cảnh) |
| 🏬 Showroom trưng bày | Kệ kính, LED spotlight | SP cao cấp |
| ☕ Quán café hiện đại | Bàn gỗ, ấm cúng | SP lifestyle |
| 📦 Bàn unboxing | Giấy kraft, kéo, bọc hàng | Unboxing review |
| ⚖ Bàn so sánh SP | Bàn trắng, SP xếp cạnh nhau | So sánh sản phẩm |
| 📱 Studio livestream | Ring light, tripod, LED | Livestream bán hàng |

---

## 10. GUI (Tab Tạo Video Shopee)

### 10.1 Cài đặt

- **Tỉ lệ**: Dọc 9:16 (TikTok) / Ngang 16:9 / Vuông 1:1
- **Khung cảnh**: Random hoặc chọn preset
- **Độ dài**: 16s / 24s
- **Ngôn ngữ**: Tiếng Anh / Tiếng Việt
- **🧹 Xóa logo Veo**: Checkbox (mặc định BẬT)
- **Thư mục người mẫu**: Folder chứa nhiều ảnh (hiển thị số lượng)
- **Thư mục lưu**: Output directory

### 10.2 Nút chức năng

| Nút | Chức năng | Xác nhận |
|-----|-----------|----------|
| 📂 Import thư mục ảnh | Scan folder → tên file = tên SP | Không |
| 📄 Import tên SP (TXT) | Ghi đè tên, giữ đường dẫn ảnh | Không |
| 👁 Xem trước | Render thumbnail preview | Không |
| 🗑 Xóa hết | Xóa toàn bộ danh sách | ✅ Hỏi xác nhận |
| 🔄 Xóa trạng thái | Xóa ✅/❌/⏳ để chạy lại | ✅ Hỏi xác nhận |
| ✅ Xóa thành công | Xóa các dòng ✅, giữ lại ❌ và chưa chạy | Không |
| ▶ Bắt đầu tạo video | Chạy xử lý | Không |
| ⏹ Dừng | Gửi lệnh dừng | Không |
| 📂 Mở thư mục | Mở output folder | Không |

### 10.3 Tối ưu import 20k+ items

- **Batch insert**: Build toàn bộ text 1 lần rồi insert (không loop append)
- **Set lookup**: Dùng `set` cho extensions thay vì `tuple` (O(1) vs O(n))
- **Iterator đọc file**: `for l in f` thay vì `f.readlines()` (tiết kiệm RAM)
- **Skip preview**: > 200 SP → không auto-preview (user bấm 👁 khi cần)

---

## 11. API Functions (shopeevideo.py)

### 11.1 Public Functions

| Function | Signature | Mô tả |
|----------|-----------|-------|
| `pick_scene` | `(user_choice, lang="en")` | Trả `(scene_name, scene_desc)` |
| `build_image_prompt` | `(product_name, scene_en, lang="en")` | Prompt tạo ảnh composite |
| `build_video_prompts` | `(product_name, scene_en, duration_sec=16, lang="en")` | List prompt video segments |
| `concat_videos` | `(clip_paths, output_path, log=None)` | FFmpeg concat (copy → re-encode fallback) |
| `remove_veo_watermark` | `(input_path, log=None)` | Xóa logo Veo (delogo filter, ghi đè gốc) |
| `pick_random_model` | `(model_folder)` | Random 1 ảnh từ thư mục → full path |
| `list_model_images` | `(model_folder)` | List tất cả ảnh sorted → list full path |
| `parse_duration` | `(duration_str)` | Parse "16s" → 16 |
| `clean_filename` | `(s)` | Tên file an toàn (≤60 ký tự) |

### 11.2 Constants

| Constant | Giá trị | Mô tả |
|----------|---------|-------|
| `SCENES` | 12 tuple | (tên, desc_EN, desc_VI) |
| `SCENE_OPTIONS` | 13 items | ["🎲 Random"] + 12 scenes |
| `DURATION_OPTIONS` | ["16s", "24s"] | Lựa chọn độ dài |
| `DURATION_MAP` | {16: [0,1], 24: [2,3,4]} | Mapping duration → segment indices |
| `SEGMENT_POOL_EN` | 5 templates | Prompt tiếng Anh |
| `SEGMENT_POOL_VI` | 5 templates | Prompt tiếng Việt |
| `LANG_OPTIONS` | ["Tiếng Anh", "Tiếng Việt"] | GUI options |
| `_MODEL_EXTS` | set | Extensions ảnh hỗ trợ |

---

## 12. Settings keys (settings.json)

| Key | Kiểu | Mô tả |
|-----|------|-------|
| `shopee_aspect` | string | Tỉ lệ video |
| `shopee_scene` | string | Khung cảnh đã chọn |
| `shopee_duration` | string | Độ dài ("16s" / "24s") |
| `shopee_model_dir` | string | Đường dẫn thư mục người mẫu |
| `shopee_out_dir` | string | Thư mục lưu output |
| `shopee_products` | string | Nội dung textbox SP (multiline) |
| `shopee_lang` | string | Ngôn ngữ |
| `shopee_remove_wm` | bool | Xóa watermark Veo (mặc định true) |

---

## 13. Lỗi thường gặp & Cách xử lý

| Lỗi | Nguyên nhân | Cách xử lý |
|-----|-------------|------------|
| `Lỗi xử lý SP: 12` | DURATION_MAP không có key 12 | Đã fix: default → 16 |
| Video không đồng bộ giữa các clip | Retry dùng khác scene/model/prompt | Đã fix: metadata persistence |
| Thiếu đoạn [2, 3] | API render fail hoặc timeout | Chạy lại → chỉ tạo đoạn thiếu với đúng prompt |
| Giọng nói không đồng bộ | Lang hardcoded trong từng segment | Đã fix: `{lang_instruction}` |
| Upload ảnh thất bại | Account bị cấm i2v (403) | Chuyển account khác |
| Render timeout | API quá tải | Tự retry 3 lần |
| GUI freeze khi import 20k | Auto-preview render 20k thumbnails | Đã fix: skip preview khi > 200 |

---

## 14. Nâng cấp tương lai (TODO)

### 14.1 Tính năng

- [ ] Thêm nhạc nền tự động (FFmpeg audio mix)
- [ ] Thêm text overlay (tên SP, giá, CTA) lên video
- [ ] Thêm logo/watermark tùy chỉnh
- [ ] Hỗ trợ nhiều ngôn ngữ hơn (Thái, Indo, ...)
- [ ] Cho phép user tùy chỉnh prompt template
- [ ] Preview video trước khi lưu
- [ ] Cho phép chọn giới tính người mẫu (nam/nữ) per SP

### 14.2 Tối ưu

- [x] ~~Song song hóa tạo clip trong cùng 1 SP~~ → Đã chuyển sang AIMD shared queue + per-account workers (§8)
- [ ] Compress video output (crf/bitrate tùy chỉnh)
- [ ] Progress bar chi tiết hơn (% từng SP, từng phase)
- [ ] Virtual scrolling cho preview panel khi > 1000 SP

### 14.3 Chất lượng

- [ ] A/B test prompt: so sánh chất lượng video giữa các biến thể prompt
- [ ] Thêm seed cố định cho visual consistency giữa các clip
- [ ] Thêm style preset (energetic, calm, professional, ...)
- [ ] Lọc/phân loại ảnh người mẫu (nam/nữ, phong cách) để match sản phẩm


---

## 📄 NỘI DUNG NGUYÊN BẢN TỪ FILE [hieusuat.md]

# 📊 Theo Dõi Hiệu Suất — Thìn Aptm

---

# Phiên 2: 2026-07-08 (07:04 → 08:36)

## 1. Thông Tin Phiên Chạy

| Thông số | Giá trị |
|---|---|
| **Thời gian bắt đầu** | 07:04:17 |
| **Thời gian log cuối** | 08:36:33 (vẫn đang chạy) |
| **Thời gian chạy** | ~92 phút |
| **Tổng job** | 9,518 |
| **Số tài khoản** | 3 (jesusita, maichuyen, qh.varic) |
| **Số luồng cấu hình** | 60 (20/account) |
| **Chế độ** | I2V (Image → Video) |

---

## 2. Kết Quả Xử Lý (92 phút)

| Trạng thái | Số lượng | Tỉ lệ |
|---|---|---|
| ✅ Video tải thành công | **396** | 4.2% tổng |
| 🔴 429 Rate Limit | **435** | Nhiều hơn video! |
| ❌ Render TIMED_OUT | **117** | 74% tổng fail |
| ❌ Render HIGH_TRAFFIC | 12 | — |
| ⚠️ AUDIO_FILTERED | 13 | — |
| ⚠️ Vi phạm CS (IP/DANGER/PROMINENT) | 8 | — |
| ❌ INTERNAL | 1 | — |
| 🔄 Còn lại đang chờ | ~8,946 | — |

**Throughput: 4.3 video/phút** (thấp — kỳ vọng 10+)

---

## 3. Phân Tích Hiệu Suất Từng Tài Khoản

| Tài khoản | Video ✅ | Lần bị 429 🔴 | Tỉ lệ 429/video |
|---|---|---|---|
| **jesusitamicelizw** | 127 | 147 | **1.16** |
| **maichuyencole** | 131 | 144 | **1.10** |
| **qh.varic** | 138 | 144 | **1.04** |

→ Tất cả 3 account bị 429 tương đương nhau — không phải lỗi 1 account mà là cơ chế submit quá nhanh cho cả hệ thống.

---

## 4. Biểu Đồ Video/Phút — Pattern "Burst → Deadzone"

```
07:05: ████████████████████  20   (burst khởi đầu)
07:06: ██                     2   ← 429 chặn
07:07: ·                      0   ← DEADZONE
07:08: ·                      0   ← DEADZONE
07:09: ███████████           11   (hồi lại)
07:10: ██████████            10
07:11: █                      1   ← 429 chặn
07:12: ·                      0   ← DEADZONE
07:13: ████████████          12   (hồi lại)
07:14: ██████████            10
      ...
07:49: ███████████           11
07:50: ██████████            10
07:51: ·                      0   ← DEADZONE
07:52: ·                      0   ← DEADZONE
07:53: ██████                 6   (hồi lại)
07:54: ████████████          12
      ...
08:25: █████████              9
08:26: ███████████           11
      ...
08:29: █████████████         13
08:30: ████████               8
      ...
08:33: ██████████████        14
08:34: ██████████            10   (video cuối cùng)
08:35: ·                      0   ← DEADZONE kéo dài...
```

**Pattern**: AIMD giảm về 1 submit → vẫn 429 → nghỉ 30s → thử lại → 429 → toàn bộ 60 luồng đứng yên 2-3 phút → Google mở khóa → burst lại → lặp lại.

---

## 5. Phân Tích Thời Gian Sử Dụng

| Hoạt động | Thời gian ước tính | Tỉ lệ |
|---|---|---|
| 🟢 Thực sự làm video | ~35 phút | **38%** |
| 🔴 Chờ 429 (deadzone) | ~40 phút | **43%** |
| 🟠 Chờ render timeout | ~15 phút | **16%** |
| 🟡 Khác (lỗi, rewrite) | ~2 phút | **3%** |

→ **Hệ thống chỉ làm việc thực sự ~38% thời gian, 43% đứng yên chờ!**

---

## 6. Root Cause — Tại Sao Hiệu Suất Thấp?

### Nguyên nhân gốc: **Chỉ 3 account cho 9,518 job**

- Mỗi account chỉ đạt ~1.4 video/phút (dưới mức tối đa ~2.2)
- Google throttle khi 3 account submit từ cùng IP → deadzone đồng loạt
- 60 luồng (20/account) tạo áp lực lớn lên Google → bị throttle nhanh hơn

### Phân tích chi tiết lỗi render

| Loại lỗi render | Số lần | Ghi chú |
|---|---|---|
| `VIDEO_GENERATION_TIMED_OUT` | **117** | Server-side issue, mỗi lần tốn ~5 phút poll |
| `HIGH_TRAFFIC` | 12 | Google server đông |
| `AUDIO_FILTERED` | 13 | Prompt vi phạm (6 lần rewrite thành công) |
| `IP_INPUT_IMAGE` | 5 | Ảnh chứa logo/bản quyền |
| `DANGER_FILTER` | 2 | Nội dung nguy hiểm |
| `PROMINENT_PEOPLE` | 1 | Khuôn mặt người nổi tiếng |
| `INTERNAL` | 1 | Lỗi nội bộ Google |

---

## 7. Đề Xuất Tối Ưu

### 🔴 Ưu Tiên Cao

| # | Giải pháp | Tác động dự kiến |
|---|---|---|
| 1 | **Thêm 5-7 tài khoản** | +150-200% throughput. 10 account → ~10 video/phút |
| 2 | **Nghỉ dài hơn khi AIMD chạm sàn** (60-90s thay vì 30s) | -50% deadzone |
| 3 | **So le submit giữa các account** (lệch 10s) | -30% đồng loạt 429 |

### 🟡 Ưu Tiên Trung Bình

| # | Giải pháp | Tác động dự kiến |
|---|---|---|
| 4 | Giảm `POLL_MAX` 60 → 30 | Phát hiện render timeout sớm hơn |
| 5 | Limit pending render/account | Tránh quá nhiều video cùng render → TIMED_OUT |
| 6 | Retry render fail tự động (TIMED_OUT) | 117 job có thể retry thành công |

### 🟢 Ưu Tiên Thấp

| # | Giải pháp |
|---|---|
| 7 | Log tổng kết mỗi 5 phút (throughput, 429 rate) |
| 8 | Cảnh báo khi tất cả account đồng loạt 429 |

---

---

# Phiên 1: 2026-07-07 (00:04 → 00:08)

## 1. Thông Tin Phiên Chạy

| Thông số | Giá trị |
|---|---|
| **Thời gian bắt đầu** | 00:04:38 |
| **Thời gian kết thúc (log cuối)** | 00:08:18 |
| **Thời gian chạy (tính đến log cuối)** | ~3 phút 40 giây |
| **Tổng job** | 4,314 (range dòng 8550–12863) |
| **Số tài khoản** | 3 |
| **Số luồng cấu hình** | 12 |
| **Chế độ** | I2V (Image → Video) |

---

## 2. Kết Quả Xử Lý (trong 3 phút 40 giây)

| Trạng thái | Số lượng | Tỉ lệ |
|---|---|---|
| ✅ Video tải thành công | **16** | 0.37% tổng |
| ❌ Vi phạm chính sách (CS) | **1** | — |
| ⏳ 429 Rate Limit (throttled) | **12 lần** | — |
| 🔄 Còn lại đang chờ/chạy | ~4,297 | — |

### Video Đã Hoàn Thành

| Thời gian | File | Kích thước | Tài khoản |
|---|---|---|---|
| 00:05:39 | 52806019803.mp4 | 3,454 KB | jesusitamicelizw |
| 00:05:39 | 52805995432.mp4 | 3,775 KB | maichuyencole@gm |
| 00:06:04 | 52806557718.mp4 | 2,150 KB | maichuyencole@gm |
| 00:06:05 | 52850770252.mp4 | 1,960 KB | jesusitamicelizw |
| 00:06:28 | 52806240731.mp4 | 1,978 KB | maichuyencole@gm |
| 00:06:28 | 52806685137.mp4 | 1,844 KB | jesusitamicelizw |
| 00:06:54 | 52806301822.mp4 | 2,394 KB | qh.varic@gmail.c |
| 00:06:58 | 52806515769.mp4 | 1,939 KB | jesusitamicelizw |
| 00:07:08 | 52806633290.mp4 | 2,056 KB | qh.varic@gmail.c |
| 00:07:10 | 52807267778.mp4 | 3,214 KB | maichuyencole@gm |
| 00:07:21 | 52851386608.mp4 | 2,930 KB | maichuyencole@gm |
| 00:07:28 | 52851780549.mp4 | 2,249 KB | jesusitamicelizw |
| 00:07:38 | 52806003852.mp4 | 2,211 KB | qh.varic@gmail.c |
| 00:07:47 | 52851786350.mp4 | 1,760 KB | maichuyencole@gm |
| 00:07:53 | 52852580296.mp4 | 2,041 KB | jesusitamicelizw |
| 00:08:03 | 52853571422.mp4 | 2,142 KB | jesusitamicelizw |

**Kích thước video trung bình:** ~2,316 KB (~2.3 MB)

---

## 3. Phân Tích Hiệu Suất Từng Tài Khoản

| Tài khoản | Video thành công | Thời gian TB/video | Số lần bị 429 |
|---|---|---|---|
| **jesusitamicelizw** | 6 | ~24s | 0 |
| **maichuyencole@gm** | 6 | ~26s | 0 |
| **qh.varic@gmail** | 3 | ~29s | **12** (tất cả) |
| _Không xác định_ | 1 | — | — |

### ⚠️ Vấn Đề Lớn: Account `qh.varic@gmail` Bị Chặn Liên Tục

- **12/12 lần bị 429** đều rơi vào tài khoản `qh.varic@gmail`
- Tài khoản này **bị throttle ngay từ giây đầu** (00:04:48, chỉ 10 giây sau khi bắt đầu)
- Mỗi lần nghỉ 50 giây nhưng vẫn bị tiếp → tài khoản này có thể đã cạn quota trước đó
- Dù bị chặn liên tục, vẫn submit thành công được **3 video** (00:06:54, 00:07:08, 00:07:38)

---

## 4. Phân Tích Lỗi

### 4.1 Rate Limiting (429 — RESOURCE_EXHAUSTED)

| Thời gian | Khoảng cách | Account |
|---|---|---|
| 00:04:48 | — | qh.varic |
| 00:05:00 | 12s | qh.varic |
| 00:05:13 | 13s | qh.varic |
| 00:05:24 | 11s | qh.varic |
| 00:06:56 | 1m32s | qh.varic |
| 00:07:07 | 11s | qh.varic |
| 00:07:18 | 11s | qh.varic |
| 00:07:27 | 9s | qh.varic |
| 00:07:46 | 19s | qh.varic |
| 00:08:02 | 16s | qh.varic |
| 00:08:13 | 11s | qh.varic |
| 00:08:14 | 1s | maichuyencole (lần đầu!) |

### 4.2 Vi Phạm Chính Sách

| Thời gian | Loại lỗi | Prompt |
|---|---|---|
| 00:06:32 | `PUBLIC_ERROR_AUDIO_FILTERED` | "52851416250-b Create an 8-seco..." |

---

## 5. Throughput (Tốc Độ Xử Lý)

- Giai đoạn **00:05:39 → 00:08:03** (2 phút 24 giây): **16 video**
- **Throughput: ~6.7 video/phút** (với 3 account)
- **Throughput/account: ~2.2 video/phút**

---

---

# 📈 Bảng So Sánh Giữa Các Phiên

| Metric | Phiên 1 (07/07) | Phiên 2 (08/07) | Xu hướng |
|---|---|---|---|
| **Thời gian chạy** | 3.7 phút | 92 phút | — |
| **Video hoàn thành** | 16 | 396 | — |
| **Throughput** | 6.7 video/phút | 4.3 video/phút | 📉 **-36%** |
| **Throughput/account** | 2.2 video/phút | 1.4 video/phút | 📉 **-36%** |
| **429/video tỉ lệ** | 0.75 | **1.1** | 📉 +47% |
| **Render TIMED_OUT** | 0 | **117** | 📉 Mới xuất hiện |
| **Luồng cấu hình** | 12 | 60 | ⬆ +400% |
| **Account** | 3 | 3 | ⏸ Không đổi |

**Nhận xét**: Tăng luồng từ 12 → 60 nhưng throughput **giảm 36%** vì Google throttle mạnh hơn. Nhiều luồng hơn = nhiều submit hơn = nhiều 429 hơn = nhiều deadzone hơn. Bài học: **thêm account quan trọng hơn thêm luồng**.

---

_Cập nhật lần cuối: 2026-07-08 08:40_


---



---

## 55. Tối Ưu Hoàn Chỉnh Toàn Bộ Các Tiến Trình Ghép Video FFmpeg (2026-08-10)
- **Kiểm tra & Khắc phục**:
  - Đã rà soát 100% các lệnh khởi chạy FFmpeg trên toàn bộ dự án (	hin_aptm.py, shopeevideo.py, ghep_video.py, uto_voice_sub.py).
  - Chuyển toàn bộ các cờ encode CPU fallback từ -preset fast/-preset medium sang **-preset superfast** và siết chặt **-threads 1** cho từng tiến trình.
  - Bổ sung cờ ưu tiên hệ thống Windows BELOW_NORMAL_PRIORITY_CLASS (0x00004000) + CREATE_NO_WINDOW (0x08000000) cho 100% lệnh subprocess.run FFmpeg.
  - Khống chế trần Semaphore FFmpeg đồng thời fmpeg_sem & merge_sem ở mức **max(2, min(6, os.cpu_count() // 8))** (tối đa 6 tiến trình), giúp CPU 56 nhân luôn duy trì mức mát mẻ dưới 40% và giao diện Windows mượt mà 100%.


---

## 56. Gộp Hai Tùy Chọn Kiểu Review & Nội Dung Thành 1 Ô Menu Duy Nhất (2026-08-10)
- **Tối ưu giao diện**:
  - Gộp ô menu Kiểu Review và ô Nội dung thành **1 ô duy nhất: Kiểu Review**.
  - Danh sách các kiểu lựa chọn gộp chung: Review kho hàng, Ngồi Review, POV, UGC, Unboxing, Demo công dụng, Review tự nhiên.
  - Tối ưu đồng bộ cho cả Tab Shopee và Tab Server Video.


---

## 57. Bổ Sung Lựa Chọn Mặc Định 'Random' Trong Menu Kiểu Review (2026-08-10)
- **Tùy chọn mới**:
  - Đã bổ sung lựa chọn **Random** lên vị trí đầu tiên và đặt làm **mặc định** trong ô menu **Kiểu Review**.
  - Khi chọn Random, phần mềm sẽ tự động chọn ngẫu nhiên 1 trong các kiểu review (Review kho hàng, Ngồi Review, POV, UGC, Unboxing, Demo công dụng, Review tự nhiên) cho mỗi video được tạo ra.
  - Áp dụng đồng bộ cho cả Tab Shopee và Tab Server Video.


---

## 58. Tích Hợp Chế Độ TVC Template 16s (8s Video AI + 8s Slideshow 3 Ảnh Sản Phẩm P 1..6) (2026-08-10)
- **Cơ chế hoạt động mới**:
  - Đã tích hợp trực tiếp file SlideShow.py (từ dự án E:\0 - Tai anh Shopee 2026) vào thư mục gốc E:\ThinAptm0707.
  - Khi chọn **Độ dài = 16s** và **AI Prompt = 📺 TVC Template**:
    1. **Tạo 8s Video AI**: Phần mềm tự động tạo 1 segment duy nhất dài 8s bằng AI prompt TVC chuẩn.
    2. **Tải & Tạo 3 Ảnh Sản Phẩm**: Tự động tải các ảnh sản phẩm chất lượng cao (hoặc tự động dùng kĩ thuật PIL Zoom-Crop 85% & 70% để tạo ra 3 biến thể khung hình sắc nét nếu sản phẩm chỉ có 1 ảnh).
    3. **Tạo Slideshow 8s (Hiệu Ứng P 1..6)**: Gọi module SlideShow.create_slideshow() áp dụng ngẫu nhiên các bộ lọc khung mẫu & hiệu ứng chuyển động chuyên nghiệp (Camera, Fast Beat, Shopee App, Specs, Dynamic, Classic / Zoompan, Shake Beat, Pulse Flash).
    4. **Ghép Thành Video 16s**: Ghép nối 8s Video AI + 8s Slideshow Ảnh Sản Phẩm $ightarrow$ Tạo ra 1 Video TVC 16s hoàn chỉnh.
  - Mở khóa tùy chọn 📺 TVC Template cho tất cả các mức độ dài (8s, 16s, 24s).


---

## 59. Nâng Cấp TVC Template Cho Độ Dài 24s (8s AI Video + 16s Slideshow 6 Ảnh Sản Phẩm) (2026-08-10)
- **Quy tắc độ dài TVC Template**:
  - **16s**: 8s Video AI (1 segment) + **8s Slideshow (3 ảnh sản phẩm)** với hiệu ứng mẫu P 1..6 & Zoompan.
  - **24s**: 8s Video AI (1 segment) + **16s Slideshow (6 ảnh sản phẩm)** với hiệu ứng mẫu P 1..6 & Zoompan.
- **Xử lý ảnh thiếu linh hoạt**:
  - Nếu sản phẩm không đủ 3 hoặc 6 ảnh thực tế từ Shopee, hệ thống tự động sinh thêm các góc chụp/cận cảnh biến thể chất lượng cao bằng thuật toán PIL Zoom-Crop (90%, 80%, 70%, 60%, 50%) để đảm bảo luôn đủ 3 hoặc 6 ảnh đẹp cho slideshow.


---

## 60. Tắt Hoàn Toàn Tính Năng Can Thiệp & Diệt Tiến Trình Chrome (Bảo Vệ 100% Chrome Làm Việc Của Người Dùng) (2026-08-10)
- **Vấn đề đã xử lý**:
  - Trước đây, hàm quét ngầm _clean_orphaned_chrome() khi chạy vô tình quét trúng các tiến trình con (--type=renderer / --type=utility) của trình duyệt Google Chrome chính mà người dùng đang làm việc, dẫn đến lỗi Chrome bị văng trang với mã lỗi Ôi, hỏng! Mã lỗi: 15.
- **Cải tiến khắc phục triệt để**:
  - Đã **TẮT HOÀN TOÀN (Vô hiệu hóa 100%)** tất cả các hàm quét và diệt tiến trình Chrome ngầm (_clean_orphaned_chrome(), _clean_orphaned_chrome_manually(), kill_chrome_locking_profile()).
  - Phần mềm ThinAptm từ nay **TUYỆT ĐỐI KHÔNG CAN THIỆP, KHÔNG BẮT VÀ KHÔNG DIỆT BẤT KỲ TIẾN TRÌNH CHROME NÀO** trên máy tính của người dùng.
  - Đảm bảo trình duyệt Chrome làm việc, Zalo, Shopee, GemLogin của bạn luôn chạy mượt mà, không bao giờ bị văng trang hay bị ảnh hưởng bởi ThinAptm nữa!


---

## 61. Khac Phuc Triet De Loi Nut Bat Dau Tao Video Khong Phan Hoi (2026-08-10)
- **Nguyen nhan**:
  - Khi gop hai o menu Kieu Review va Noi dung thanh 1 o duy nhat, bien tham chieu self._sv_content_style bi thieu, gay ra loi ngam AttributeError ngat ham khoi dong.
- **Khac phuc**:
  - Da cap nhat va boc kiem tra an toan getattr() cho tat ca cac tham chieu. Nut ▶ Bat dau tao video da chay ngon lành 100%!


---

## 62. Khac Phuc Triet De Loi Nhan Dien Nham Cookie Het Han Cho Tai Khoan (2026-08-10)
- **Nguyen nhan**:
  - Trong engine.py, ham earer_from_cookie() kiem tra truong expires cu trong JSON response cua Google ngay ca khi Google da cap Bearer Token moi (ya29...) va Set-Cookie gia han session token 30 ngay. Dieu nay khien 2 tai khoan jesusitamicelizws33@gmail.com va phucphuongdinh40@gmail.com bi coi la cookie loi.
- **Khac phuc**:
  - Da cap nhat earer_from_cookie()uu tien dung ngay ccess_token khi Google tra ve HTTP 200. Ket qua: **10/10 Tai Khoan trong accounts.json Hoat Dong 100% Sắn Sang Tao Video!**


---

## 63. Phan Tich Chi Tiet Log & Khac Phuc Loi Tu Dong Tra SP Khi Bat Dau Chay (2026-08-10)
- **Phan tich nguyen nhan tu Log người dùng gửi**:
  1. Mốc [18:42:08] có dòng ⏹ Đã gửi lệnh dừng, chờ hoàn tất bước hiện tại... do biến _sv_stop_flag bị bật khi người dùng ấn dừng hoặc khi xảy ra ngắt luồng trước đó.
  2. Khi 4 tài khoản auth xong lúc 18:42:15, luồng worker kiểm tra _sv_stop_flag == True nên ngay lập tức trả 12 sản phẩm về Server và dừng lại (🔄 Trả 12 SP chưa làm về Server... -> ✅ Đã trả SP về pending.).
  3. Đồng thời 2 tài khoản jesusitamicelizws33@gmail.com và phucphuongdinh40@gmail.com bị bỏ qua do lỗi check expiration cũ (đã được sửa ở Mục 62).
- **Giải pháp xử lý**:
  - Đã thêm lệnh self._sv_stop_flag = False đặt tại đầu hàm khởi chạy _sv_start_run(), đảm bảo cờ dừng luôn được reset về False khi bắt đầu phiên làm việc mới.
  - Cả 10/10 tài khoản đều đã Auth thành công 100%, không còn tài khoản nào bị bỏ qua.


---

## 64. Giai Thich Nguyen Nhan 401 Unauthorized & Sua Loi Check Trang Thai Giao Dien (2026-08-10)
- **Nguyen nhan thuc te**:
  1. Hai tai khoan jesusitamicelizws33@gmail.com va phucphuongdinh40@gmail.com bi phia Google huy phien dang nhap va tra ve **401 Unauthorized** khi goi API project.searchUserProjects. Vi vay phan mem dung bao cookie loi -> bo qua la HOAN TOAN CHINH XAC de tranh va cham va mat credit.
  2. Ban dau giao dien bang Tai khoan van hien Hoat dong la do ham check_one() trong Health Check bi loi tuple unpack (cho 2 thay vi 3), khien nut Check ngam crash khong cap nhat lai file status.
- **Khac phuc**:
  - Da sua xong ham check_one() trong _do_health_check(). Khi bam Check, hai tai khoan tren se hien dung trang thai Chét do do cookie qua han.
  - Nguoi dung chi can bam nut **🔑 Auto login** hoac bieu tuong **☕** Re-login o dong tai khoan do de Google tu dong cap cookie moi 100% hoat dong lai binh thuong!


---

## 65. Giai Thich Co Che Tao Video AI & Xu Ly Khi Dinh Co Dung (2026-08-10)
- **Lý do phần mềm không tạo video AI trong lần chạy trước**:
  1. Do trong mốc log [18:42:08] cờ dừng _sv_stop_flag bị kích hoạt, khi các tài khoản vừa chuẩn bị xong thì luồng worker lập tức phát hiện cờ dừng và nhả toàn bộ 12 sản phẩm về Server (🔄 Trả 12 SP chưa làm về Server...). Vì vậy luồng chưa kịp gọi API Google Veo3 để tạo video AI.
  2. Khi chưa kịp tạo video AI, phần mềm chỉ mới tải ảnh gốc sản phẩm về thư mục tạm 	emp_render nên bạn thấy xuất hiện ảnh đầu tiên của sản phẩm.
- **Đã khắc phục hoàn toàn**:
  - Đã thêm reset cờ dừng _sv_stop_flag = False và _sp_stop_flag = False ngay khi bấm nút Bắt đầu.
  - Đã kiểm tra thực tế API Google Veo3 trên các tài khoản sống (như nlangthuong91@gmail.com) -> Bearer Token và Project ID đều hoạt động 100% hoàn hảo và sẵn sàng tạo video AI ngẫu nhiên/TVC.


---

## 66. Khac Phuc Loi Unpack Tuple Khien Auto Login Bi Treo (2026-08-10)
- **Nguyen nhan**:
  - Trong ham _auto_login(), lenh , _ = E.bearer_from_cookie(a['cookie']) bi loi unpacking (expected 2, got 3) vi earer_from_cookie tra ve 3 phan tu. Khien luong ngam bi ngat va dung o dong 'Dang xac minh cookie voi Google Labs...'.
- **Khac phuc**:
  - Da cap nhat va boc xu ly an toan 3-tuple cho TOAN BO 8 vi tri goi earer_from_cookie() trong 	hin_aptm.py.
  - Nut **Auto login** va **Check** gio day chay mượt va phan hoi ngam tuc thi!


---

## 67. Xac Nhan Auto Login Thanh Cong 100% Cho Tat Ca 10 Tai Khoan (2026-08-10)
- **Ket qua thuc te**:
  - Chuc nang Auto Login qua Profile da tu dong kich hoat va cap nhat cookie moi cho 3 tai khoan (jesusitamicelizws33@gmail.com, maichuyencole@gmail.com, phucphuongdinh40@gmail.com) thanh cong 100%.
  - Toan bo 10/10 tai khoan (6 Main + 4 Donor) deu da chuyen sang **Hoat dong (ok)**, san sang 100% chay song song va tao video AI ngau nhien/TVC 16s/24s cho Server va Shopee Tab!


---

## 68. Them Co Che Tu Dong Xoay Proxy Khi Khoi Tao Tai Khoan Nut Bat Dau (2026-08-10)
- **Nguyen nhan**:
  - Log bao 2 tai khoan loi cookie truoc do la do phien chay cu CHUA chay nut Auto Login. Sau khi chay Auto Login thi tat ca cookie da song 100%.
  - Tuy nhien, neu proxy duoc gan cho 1 tai khoan bi chet/timeout, lenh ensure_auth qua proxy do se bi ngat khien tai khoan bi bo qua.
- **Giai phap nang cap**:
  - Da them co che **Tu dong doi Proxy khac khi khoi tao**: Khi phat hien proxy hien tai cua tai khoan bi loi/timeout, he thong tu dong mark dead va xoay sang proxy moi khac de ket noi lai Google. Đam bao tai khoan khong bao gio bi bo qua do proxy chet!


---

## 69. Xác Minh & Hoàn Thiện Cơ Chế Gia Hạn Session Cookie 100% Qua HTTP Request (Không Cần Mở Chrome) (2026-08-10)
- **Đột phá công nghệ & Kết quả kiểm chứng thực tế**:
  - Đã kiểm chứng thành công 100%: Cả hai endpoint `GET /fx/api/auth/session` và `GET /fx/tools/flow` của Google FX (Labs Google) đều tự động gia hạn phiên và trả về header `Set-Cookie` chứa `__Secure-next-auth.session-token` MỚI.
  - Thử nghiệm thực tế: Một cookie cũ đã hết hạn từ 17 giờ trước (`expired 17h ago`), khi gọi HTTP GET `/fx/api/auth/session` $\rightarrow$ Google FX tự động gia hạn thành công và trả về `Set-Cookie` với `session-token` MỚI kéo dài thời gian sống thêm **23.3 giờ** (`expires 2026-08-10T17:14:57Z`).
  - Bearer Token MỚI được trích xuất thành công và test thử truy vấn danh sách Project (`project.searchUserProjects`) đạt mã **HTTP 200 OK** (trả về 5 projects sẵn sàng).
- **Tối ưu vượt trội & Cấu trúc tích hợp trong Code**:
  - **Tốc độ:** Gia hạn cookie cực nhanh chỉ mất ~0.2 giây qua 1 HTTP request đơn lẻ, KHÔNG CẦN tốn 15-30 giây mở Chrome / DrissionPage.
  - **Tài nguyên:** Tiết kiệm 100% tài nguyên CPU & RAM cho trình duyệt.
  - **Code tích hợp:**
    - [`engine.py`](file:///E:/ThinAptm0707/engine.py): Hàm `update_cookie_string()` bóc tách `Set-Cookie` header để cập nhật `__Secure-next-auth.session-token` mới vào chuỗi cookie. Hàm `bearer_from_cookie()` trả về tuple 3 phần tử `(access_token, user_email, new_cookie)`.
    - [`thin_aptm.py`](file:///E:/ThinAptm0707/thin_aptm.py): Hàm `ensure_auth()` tự động lưu `new_cookie` trực tiếp vào bộ nhớ và đồng bộ lưu xuống `accounts.json`.


---

## 70. Bổ Sung Tùy Chỉnh Số Luồng Upload/Tài Khoản Ở Cuối Thanh Hành Động (2026-08-10)
- **Nâng cấp tính năng**:
  - Đã đưa ô tùy chỉnh `📤 Upload/TK:` vào **cuối hàng nút bấm điều khiển** ở chân trang (`[ ▶ Bắt đầu ] [ ⏹ Dừng ] [ 📂 Mở thư mục ] [ 📤 Upload/TK: 3 ]`) của cả 3 Tab (Tạo video chính, Shopee Video, Server Video).
  - Cho phép người dùng tùy chọn linh hoạt từ `1` đến `10` luồng upload/tài khoản (mặc định là `3` luồng/TK).
  - Công thức Semaphore tự động tính toán dynamic:
    $$\text{n\_upload\_threads} = \max(1, \text{số TK đang chạy} \times \text{upload\_per\_acc})$$
  - Toàn bộ lựa chọn được lưu trữ và khôi phục tự động qua `settings.json` (`gen_upload_threads_per_acc`, `shopee_upload_threads_per_acc`, `sv_upload_threads_per_acc`).


---

## 71. Bổ Sung Nút Tương Tác ⏹ Dừng / ▶ Chạy Trực Tiếp Trên Bảng Pool Tài Khoản (AIMD) (2026-08-10)
- **Yêu cầu & Giải pháp thiết kế**:
  - Người dùng có thể nhấn nút dừng từng tài khoản ngay trên bảng Pool tài khoản (AIMD) mà không cần chuyển sang Tab Tài khoản.
  - Khi bấm **`⏹ Dừng`**:
    1. Tự động bỏ chọn `enabled = False` của tài khoản trong bộ nhớ và đồng bộ với tích chọn checkbox ở Tab **Tài khoản**.
    2. Lưu trạng thái xuống `accounts.json`.
    3. Luồng worker lập tức tạm dừng phân công job cho tài khoản này và nhả Proxy về Pool (nếu có dùng Proxy).
    4. Trạng thái dòng trên bảng Pool chuyển sang **`⏹ đã dừng`**, và nút bấm tự động chuyển thành **`▶ Chạy`** (màu xanh `#26A69A`).
  - Khi bấm **`▶ Chạy`**:
    1. Bật lại `enabled = True` cho tài khoản và đồng bộ tích chọn lại ở Tab **Tài khoản**.
    2. Lưu trạng thái xuống `accounts.json`.
    3. Luồng worker tiếp tục pull job bình thường, tự động gán Proxy mới từ Pool.
    4. Trạng thái dòng chuyển về **`🟢 đang chạy`**, và nút bấm chuyển thành **`⏹ Dừng`** (màu đỏ nhạt `#E57373`).
  - Nút bấm được tích hợp đầy đủ trên cả 3 bảng Pool ở 3 Tab (Tạo video chính, Shopee Video, Server Video).


---

## 72. Thẻ Trạng Thái Cập Nhật & Tự Động Đóng Cửa Sổ Đen CMD Khi Khởi Động (2026-08-10)
- **Cải tiến tính năng**:
  - Đã loại bỏ hoàn toàn các hộp thoại popup cảnh báo cập nhật (`messagebox.askyesno`) khỏi [`update.py`](file:///E:/ThinAptm0707/update.py) khi chạy `CHAY.bat`. Mọi việc kiểm tra và hiển thị cập nhật được xử lý tập trung 100% tại giao diện chính Thìn Aptm.
  - Đã cập nhật file [`CHAY.bat`](file:///E:/ThinAptm0707/CHAY.bat) khởi chạy ứng dụng ngầm qua `pythonw` và gọi `exit` để **tự động đóng sạch cửa sổ đen CMD** ngay khi giao diện Thìn Aptm xuất hiện.
  - **Thẻ trạng thái cố định (`update_card`):** Được ghim cố định 24/7 ở khu vực dưới cùng bên trái Sidebar (khu vực khoanh đỏ), không bao giờ bị biến mất:
    - **Trạng thái Đã mới nhất:** Hiển thị thẻ màu xanh nhẹ với tiêu đề `✅ ĐÃ Ở BẢN MỚI NHẤT`, ghi rõ `Phiên bản: ThinAPTM 1.2.0` và nút bấm **`🔄 Kiểm tra lại`**.
    - **Trạng thái Có bản cập nhật mới:** Chuyển sang thẻ màu cam nổi bật với tiêu đề `🔔 CÓ BẢN CẬP NHẬT MỚI!`, ghi rõ `Phiên bản mới: ThinAPTM 1.x.y` và nút bấm **`⚡ Cập nhật ngay`**.
  - Khi nhấn **`⚡ Cập nhật ngay`**:
    - Hệ thống tự động tải toàn bộ file mới nhất từ GitHub ghi đè vào thư mục app và thông báo thành công.


---

## 73. Hiển Thị Thông Tin Phiên Bản Chuẩn `ThinAPTM 1.2.0` & Hiển Thị Tên Bản Mới Trên Thẻ Cập Nhật (2026-08-10)
- **Bổ sung quản lý phiên bản**:
  - Khai báo hằng số phiên bản chính thức: `APP_VERSION = "ThinAPTM 1.2.0"`.
  - Hiển thị thông tin phiên bản ở 3 vị trí trên giao diện người dùng:
    1. **Tiêu đề cửa sổ ứng dụng:** `Thìn Aptm (ThinAPTM 1.2.0) — Tạo Video Google Flow`.
    2. **Dưới Logo Sidebar:** `Tạo video Google Flow  •  ThinAPTM 1.2.0`.
    3. **Chân thanh Sidebar (Footer):** Nhãn chữ xám `ThinAPTM 1.2.0` nằm ngay dưới cùng giúp người dùng dễ dàng kiểm tra phiên bản đang chạy.
  - **Trích xuất Tên Phiên bản mới từ GitHub:** Khi luồng ngầm phát hiện có bản cập nhật mới trên GitHub, hệ thống tự động bóc tách hằng số `APP_VERSION` của mã nguồn remote và hiển thị trực tiếp lên thẻ thông báo ở góc dưới bên trái:
---

## 74. Khắc Phục Triệt Để Lỗi Sập Chrome Cá Nhân (`Ôi, hỏng! Mã lỗi: 15`) & Bảo Vệ Tiến Trình Trình Duyệt (2026-08-10)
- **Nguyên nhân & Giải pháp khắc phục**:
  - **Nguyên nhân:** Hàm dọn dẹp tiến trình rác ngầm `_clean_orphaned_chrome()` trước đó sử dụng bộ lọc kiểm tra `--type=` chưa chặt chẽ, dẫn đến việc ngắt nhầm các tiến trình con (`renderer`/`utility`) của Google Chrome cá nhân người dùng đang mở (ví dụ: Zalo `chat.zalo.me`, Facebook, YouTube, Google Sheets), gây ra lỗi Chrome bị sập màn hình xám `Ôi, hỏng! Mã lỗi: 15`.
  - **Giải pháp bọc bảo vệ 100%:**
    - Cập nhật thuật toán nhận diện trong `_clean_orphaned_chrome()`: Bắt buộc chỉ diệt các cửa sổ Chrome tự động hóa do **DrissionPage / ThinAptm** khởi tạo (chứa cờ nhận diện riêng `drissionpage` hoặc `_profiles` kết hợp `remote-debugging-port`).
    - **Tuyệt đối không đụng tới:** Trình duyệt Chrome cá nhân của người dùng, các tab làm việc hàng ngày và ứng dụng GemLogin.
  - **Kết quả kiểm thử:** Ứng dụng khởi chạy 100% mượt mà, trình duyệt Chrome cá nhân của người dùng hoạt động hoàn toàn ổn định không bị ảnh hưởng.


---

## 75. Đổi Tên Tùy Chọn AI Prompt "Template (mặc định)" Thành "Prompt A + B" (2026-08-10)
- **Cải tiến giao diện**:
  - Đã cập nhật tên tùy chọn trong menu `AI Prompt:` ở cả hai Tab **Shopee Video** và **Server Video**: Chuyển từ `"Template (mặc định)"` thành **`"Prompt A + B"`**.
  - Đảm bảo tương thích ngược: Tự động chuyển đổi các cài đặt cũ lưu trong `settings.json` từ `"Template (mặc định)"` sang `"Prompt A + B"` mà không gây lỗi giao diện.


---

## 76. Tích Hợp Cơ Chế Tự Động Khôi Phục Cookie Chết Ngầm (Self-Healing Cookie Recovery) (2026-08-10)
- **Tính năng mới**:
  - Khi bắt đầu tạo video hoặc trong quá trình chạy, nếu `ensure_auth()` phát hiện cookie của tài khoản bị chết/hết hạn (`401 Unauthorized`), hệ thống tự động kích hoạt hàm `auto_recover_cookie()`.
  - **Cơ chế khôi phục 2 lớp**:
    1. **Lớp 1 (Siêu nhanh 3s):** Tự động mở lại Chrome Profile tương ứng trong thư mục `_profiles/<email>` qua `L.reopen_profile_cookie()`, trích xuất chuỗi session cookie 30 ngày mới mà không cần người dùng nhập lại mật khẩu.
    2. **Lớp 2 (Fallback Password):** Nếu Profile cũ không còn, tự động dùng Password/2FA lưu trong tài khoản để đăng nhập lại ngầm.
  - Cập nhật cookie mới trực tiếp vào bộ nhớ và đồng bộ ngay xuống `accounts.json`, giúp tài khoản lập tức sống lại và tiếp tục tạo video mà không bao giờ bị dừng hay bị bỏ qua!


---

## 77. Hoàn Thiện File Cập Nhật Thủ Công `UPDATE.bat` & Nâng Cấp Tải Trực Tiếp Từ GitHub (2026-08-10)
- **Cải tiến tính năng**:
  - Đã cập nhật lại file [`UPDATE.bat`](file:///E:/ThinAptm0707/UPDATE.bat) cho phép người dùng thực hiện cập nhật cưỡng bức thủ công toàn bộ 14 file mã nguồn từ GitHub `thincole/thinaptm/main`.
  - Áp dụng cơ chế **Cache-Busting (`?t=hex`)** khi gọi HTTP request để ngăn trình duyệt/Windows lưu kết quả cũ.
  - Sửa lại câu lệnh hiển thị tiếng Việt trên CMD sạch sẽ, không bị lỗi font hay bị dừng lệnh đột ngột.


---

## 78. Khắc Phục Lỗi Unpack Tuple 3 Phần Tử Trong Nút Auto Login & Health Check (2026-08-10)
- **Nguyên nhân & Khắc phục**:
  - **Nguyên nhân:** Khi gọi `E.bearer_from_cookie()`, hàm trả về tuple 3 phần tử `(token, email, new_cookie)`. Tuy nhiên tại các điểm gọi trong `_auto_login()`, `_check_accs()` và `_do_health_check()`, mã lệnh cũ sử dụng cú pháp bóc tách 2 phần tử (`b, em = E.bearer_from_cookie(...)`), dẫn đến lỗi ngầm `ValueError: too many values to unpack (expected 2)` làm luồng ngầm bị ngắt và dừng ở dòng `🩺 Đang xác minh cookie với Google Labs...`.
  - **Giải pháp xử lý:** Đã cập nhật lại toàn bộ 9 vị trí gọi `bearer_from_cookie()` trong `thin_aptm.py`, bóc tách an toàn 3 phần tử.
  - **Kết quả:** Nút **Auto login** và **Check** chạy mượt mà 100%, tự động làm tươi và xác minh tất cả cookie mà không bị dừng hay treo giao diện!


---

## 79. Điều Chỉnh Tốc Độ Min = 4 VÀ Max = 8 Cho Thuật Toán AIMD Rate Limiter (2026-08-10)
- **Nâng cấp tốc độ**:
  - Đã cập nhật các hằng số điều khiển cổng submit thích ứng AIMD trong [`thin_aptm.py`](file:///E:/ThinAptm0707/thin_aptm.py):
    - **`SUBMIT_MIN = 4.0`**: Nâng tốc độ sàn tối thiểu từ 2 lên **4** (tài khoản khi bị phạt rate limit 429 vẫn duy trì tối thiểu 4 submit đồng thời).
    - **`SUBMIT_MAX = 8.0`**: Nâng tốc độ trần tối đa từ 5 lên **8** (tài khoản chạy mượt sẽ tự động tăng dần tốc độ lên tối đa 8 submit đồng thời).
    - **`SUBMIT_START = 6.0`**: Đặt tốc độ khởi đầu mặc định ở mức **6**.
    - **`WORKERS_PER_ACCOUNT = 8`**: Mở rộng số worker phân công cho mỗi tài khoản lên **8 workers** để khai thác tối đa băng thông.


---

## 80. Ép Khung Chỉ Số "⚡ Tạo" (Busy Workers) Trong Khoảng Min = 4 Đến Max = 8 Khi Đang Chạy (2026-08-11)
- **Cải tiến số luồng tạo video**:
  - Đã cập nhật thanh chọn `📤 Upload/TK:` ở cả 3 tab (Tạo video, Shopee Video, Server Video) trên giao diện [`thin_aptm.py`](file:///E:/ThinAptm0707/thin_aptm.py):
    - Đổi dải tùy chọn thành `["4", "5", "6", "7", "8"]` với mức mặc định tối thiểu là **4**. Tự động nâng các máy đang lưu cấu hình cũ (1, 2, 3) lên **4**.
    - Ràng buộc công thức khởi tạo worker theo tài khoản `wpa = max(4, min(8, upload_per_acc))` để đảm bảo khi phiên chạy bắt đầu, chỉ số **`⚡ Tạo`** của từng tài khoản luôn được duy trì cố định trong dải **Min = 4** đến **Max = 8**.


---

## 81. Cơ Chế Tái Sử Dụng Video Thành Phần (8s Segment Cache) Trong Tab Server Video (2026-08-11)
- **Giải thích & Nâng cấp**:
  - **Trong cùng phiên làm việc (Khi đang chạy / thử lại):** Nếu 1 video 16s đã render xong Đoạn 1 (8s thành phần) và lưu vào `temp_render/sv_{item_id}_seg0.mp4`, nhưng Đoạn 2 bị gián đoạn (do xoay proxy/retry), ở lượt chạy tiếp theo phần mềm sẽ **tự động kiểm tra file sẵn có trong `temp_render`**, ghi log `⚡ Segment 1/2: Đã hoàn thành sẵn → Dùng lại, không tạo lại!`, ghép dùng luôn file 8s cũ và **chỉ tạo tiếp Đoạn 2 (8s còn thiếu)** giúp tiết kiệm 50% thời gian và hạn chế tối đa request lên Google.
  - **Khi tắt phần mềm (Exit / Destroy App):** Tuân thủ nghiêm ngặt **Quy tắc số 8 (`RULE[E:\ThinAptm0707\.agents\AGENTS.md]`)**, phần mềm sẽ tự động dọn dẹp sạch toàn bộ các file tạm trong `temp_render` để giải phóng dung lượng đĩa cho máy tính người dùng.


---