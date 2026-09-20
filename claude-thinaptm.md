# ThinAPTM — Ghi chú kỹ thuật (Claude)

Tài liệu tổng hợp các thuật toán, cơ chế, quy trình vận hành và bài học quan trọng đã xây dựng/sửa cho ThinAPTM (chủ yếu trong `thin_aptm.py`). Cập nhật lần cuối: 2026-09-21.

## 1. Kiến trúc chế độ Extension

```
Chrome extension (flow.google.com, đã đăng nhập thật)
   ↕ WebSocket (127.0.0.1:9333)
flow_bridge.py
   ↕
engine_ext.py (batchexecute RPC: submit_video_ext, poll_video_ext, upload_image_ext...)
   ↕
thin_aptm.py — worker()/process_one() (vòng lặp xử lý job)
```

- Mỗi tài khoản = 1 Chrome profile riêng (`_profiles/<email>/`) + 1 proxy cố định (`accounts.json[i]["proxy"]`), mở qua `recaptcha_farm.ExtensionBrowserPool.start_account()`.
- `--proxy-bypass-list 127.0.0.1;localhost;<local>` bắt buộc — nếu thiếu, traffic tới bridge nội bộ bị route qua proxy ngoài, extension không bao giờ kết nối được.
- Panel "ThinAPTM Flow Bridge" giờ **tự hiện** sau khi mở trình duyệt: `chrome.commands` (`Alt+Shift+P`) + `chrome.sidePanel.open()` trong `background.js`, kích hoạt bằng CDP `Input.dispatchKeyEvent` (`page.actions.key_down(...)`) trong `recaptcha_farm.py` — vì `sidePanel.open()` chỉ chạy được trong 1 "user gesture" thật, JS tự gọi bị Chrome chặn.

## 2. Các hằng số điều khiển chính (`thin_aptm.py`, ~dòng 220-270)

| Hằng số | Giá trị | Ý nghĩa |
|---|---|---|
| `RATE_START` | 10 | Tốc độ submit khởi đầu (video/10 phút) |
| `RATE_FLOOR` | 10 | Sàn không cho tụt xuống thấp hơn (bằng RATE_START) |
| `RATE_CUT` | 0.75 | Mỗi lần bị gắn cờ: tốc độ ×0.75 (phạt nhẹ, trước là 0.6) |
| `RATE_UP_EVERY` | 900s (15p) | Chạy êm bấy nhiêu giây thì +1 rate_limit |
| `RATE_HARD_MAX` | 30 | Trần tuyệt đối |
| `RATE_CEIL_SAFETY` | 0.8 | Trần học được = 80% tốc độ lúc bị gắn cờ |
| `CEIL_RELAX_EVERY` | 6h | Êm 6h thì nới trần học được +1 |
| `UNUSUAL_LADDER` | `[600]` | Bị gắn cờ UNUSUAL_ACTIVITY → luôn nghỉ cố định 10 phút (KHÔNG leo thang — đã thử leo thang, không hiệu quả hơn) |
| `UNUSUAL_RESET` | 2h | Êm 2h thì bộ đếm số lần gắn cờ về 0 |
| `IP_BURN_THRESHOLD` | 5 | Gắn cờ ≥5 lần/2h → nghi IP cháy → tự xoay proxy (trước là 3, tăng để giảm số lần phải xoay/đăng nhập lại) |
| `IP_ROTATE_COOLDOWN` | 300s | Tối thiểu giữa 2 lần thử xoay IP cho cùng 1 TK |
| `FLAGGED_PROXY_TTL` | 6h | **Mới** — proxy bị đánh dấu cháy tự hết hạn sau 6h, không còn vĩnh viễn |
| `EXT_POLL_MAX` / `EXT_POLL_RPC_TIMEOUT` | 24 / 20s | Giới hạn poll video Extension mode (~3 phút worst-case, trước ~90 phút) |
| `BREAK_RUN` / `BREAK_LEN` | 50-70p / 5-10p | Nghỉ ngắn định kỳ (bình thường, không phải lỗi — thấy "☕ đã chạy Np → nghỉ ngắn Mp" trong log) |

## 3. Cơ chế điều tốc (AIMD) — `AccountState`

- `acquire_rate_slot()`: giãn đều + jitter ±30% quanh chu kỳ `600/rate_limit`, cộng ràng buộc cửa sổ trượt cứng (không quá `rate_limit` submit/600s).
- `on_rate_unusual()`: khi bị gắn cờ UNUSUAL_ACTIVITY — học trần (`rate_ceiling = observed × 0.8`), cắt tốc độ (`×RATE_CUT`, không dưới `RATE_FLOOR`), hạ về 1 luồng upload, trả về thời gian nghỉ theo `UNUSUAL_LADDER`.
- `on_video_ok()`: chạy êm đủ `RATE_UP_EVERY` giây thì +1 `rate_limit` (không vượt trần học được); êm đủ `CEIL_RELAX_EVERY` thì trần +1.
- `on_upload_throttle()`: **Bug đã sửa** — trước đây 4 nơi trong code (Extension mode, cả 2 tab Tạo hàng loạt + Shopee) dùng `st.rest(60, "throttle")` cố định, không tăng dần, có thể lặp vô hạn đúng 60s không thoát. Giờ TẤT CẢ đều gọi `on_upload_throttle()`: bậc thang `15→22→34→51→76→90s` (`15 × 1.5^(streak-1)`, max 90s), tự hạ về 1 luồng sau 2 lần liên tiếp.
- Circuit breaker (`trip_circuit_breaker()`/`reset_circuit_breaker()`): **Bug đã sửa** — reset tự động mỗi khi `ensure_auth_ext()`/`ensure_auth()` xác nhận thành công (trước đây không có gì reset khi rest 60s hết hạn tự nhiên, gây vòng lặp 316 sự kiện/giây kẹt cứng).

## 4. Tự phát hiện IP cháy → xoay proxy (`_sv_try_rotate_burned_ip`)

Kích hoạt khi `unusual_count >= IP_BURN_THRESHOLD` (5 lần/2h).

**Quan trọng — đã đổi hành vi (2026-09-20)**: KHÔNG còn đăng nhập lại bằng password+2FA nữa. Chỉ:
1. `RF.get_extension_pool().stop_account(email)` — đóng trình duyệt cũ.
2. `proxy_pool.rotate(email, cooldown=3600)` — chọn proxy khác, cách ly proxy cũ 1h.
3. `proxy_pool.mark_flagged(old_proxy)` + lưu `settings.json["flagged_proxies"]`.
4. Cập nhật `acc["proxy"]` — **KHÔNG đụng `acc["cookie"]`/`acc["status"]`, KHÔNG xoá profile Chrome**.
5. Reset rate_gov (`RATE_START`, unusual_count=0).
6. Để cơ chế tự-mở-lại-trình-duyệt (đã có) mở Chrome với **cùng profile, proxy mới** — Extension mode tự nhận diện "phiên Chrome thật đã có sẵn" và dùng luôn.

**Lý do đổi**: dữ liệu 1 đêm chạy cho thấy tài khoản phải đăng nhập lại (password+2FA) càng nhiều lần trong ngày càng bị gắn cờ dồn dập hơn — mỗi lần đăng nhập lại là 1 tín hiệu "thiết bị/vị trí lạ" tự cộng dồn nghi ngờ cho CHÍNH TÀI KHOẢN, không chỉ IP. Sau khi đổi: số lần xoay IP giảm hẳn (từ ~2-3 lần/tài khoản/3.5h xuống 1-2 lần), không cần đăng nhập lại nữa trong đa số trường hợp.

**Rủi ro đã biết**: bản cũ xoá profile + đăng nhập lại từng được chọn để né lỗi CookieMismatch — bỏ bước đó CÓ THỂ gặp lại lỗi này (chưa thấy tái diễn tính tới thời điểm ghi chú, cần tiếp tục theo dõi).

## 5. Proxy Pool (`class ProxyPool`)

- `assign()`/`rotate()`: 3 tầng ưu tiên — (1) chưa ai dùng + chưa cooldown + chưa cháy, (2) bỏ qua cooldown nhưng vẫn né cháy, (3) hết cách, chấp nhận cả proxy cháy còn hơn không có.
- `assign_specific(email, proxy_str)`: gán ĐÚNG proxy đã lưu sẵn trong `accounts.json`, **bỏ qua hoàn toàn kiểm tra flagged** (chủ ý — tôn trọng lựa chọn đã lưu của tài khoản đó).
- **`_flagged` giờ là dict `{proxy: thời_điểm_cháy}`, không phải set** — tự hết hạn sau `FLAGGED_PROXY_TTL` (6h) qua `_is_flagged_locked()`. Trước đây cháy vĩnh viễn → 1 ngày chạy 2 tài khoản đã cháy hết 22/23 proxy trong pool, dồn về vài proxy cháy sẵn ping-pong qua lại, cắm cờ càng lúc càng nhanh.
- Migrate định dạng cũ: nếu `settings.json["flagged_proxies"]` là list phẳng (không có mốc giờ) → coi như đã cháy từ rất lâu, **hết hạn ngay lập tức** khi nạp (không bắt chờ thêm 6h).
- `mark_flagged()` cập nhật mốc giờ hiện tại; `get_flagged()` tự dọn entry hết hạn mỗi lần gọi.

## 6. Dò kẹt tự động (`_stuck_detector`, trong `_sv_run`)

Kiểm tra mỗi 5 phút: nếu `busy > 0` mà `wins+fails` không đổi (không có tiến triển) và không đang nghỉ/circuit-broken.
- Lần 1: chỉ log cảnh báo `⚠️ [Stuck?]`.
- **Lần 2 liên tiếp (≥10 phút đứng im)**: coi như IP/proxy cháy (vd proxy chập chờn khiến Chrome hiện hộp thoại xin user/pass proxy, không ai nhập được vì chạy tự động, đứng im vô thời hạn) → tự gọi `_sv_try_rotate_burned_ip(st)` để xoay proxy, không cần chờ đủ 5 lần gắn cờ UNUSUAL_ACTIVITY.

*Lưu ý*: cảnh báo "Stuck?" đơn lẻ (1 lần) thường là báo giả — hay trùng lúc trình duyệt vừa mất kết nối/đang tự mở lại (đồng hồ "5 phút không output" tính từ TRƯỚC lúc mất kết nối). Chỉ đáng lo khi thấy "(lần 2 liên tiếp)" hoặc dòng "🔥 ... Kẹt >= 10 phút liên tục".

## 7. Health Check (định kỳ ~30 phút)

- Pha 1: thử mở lại profile Chrome cũ (không cần password) — CHỈ áp dụng nếu tài khoản KHÔNG có password lưu sẵn.
- Pha 2: có password → login tươi 100% bằng password+TOTP.
- **Bug đã sửa**: khi Pha 1/Pha 2 thành công, giờ tự reset `st._relaunch_fail_streak = 0` cho AccountState tương ứng (tìm trong `self._sv_pool_states`). Trước đây: nếu `_sv_auto_relaunch_ext_browser` đã thất bại 3 lần liên tiếp trước đó (khoá cooldown 30 phút), Health Check đăng nhập lại thành công vẫn KHÔNG gỡ được khoá này — tài khoản có cookie sống nhưng trình duyệt vẫn đứng im tới hết 30 phút mới thử mở lại.

## 8. Danh sách bug đã tìm & sửa trong phiên làm việc dài (2026-09-19 → 09-21)

1. **Circuit breaker kẹt vĩnh viễn** → vòng lặp 316 sự kiện/giây, log 548MB/26 phút. Sửa: reset circuit breaker mỗi lần `ensure_auth_ext()`/`ensure_auth()` xác nhận sống.
2. **Extension poll worst-case quá lỏng** (~90 phút/job) → `EXT_POLL_MAX=24`, `EXT_POLL_RPC_TIMEOUT=20` (còn ~3 phút).
3. **`_on_closing()` xoá mất `flagged_proxies`/mọi field không có ô UI** mỗi lần tắt app — do dựng `s = {...}` từ đầu không kế thừa `self.settings`. Sửa: `s = {**self.settings, ...}`.
4. **"Project not found" 404** cho tài khoản chưa biết `flow_project_id` — trước dùng UUID cố định của tài khoản khác. Sửa: điều hướng về trang chủ Flow, để content.js tự phát hiện/tạo project mới.
5. **Upload-throttle nghỉ cố định 60s không thoát được** (4 chỗ trong code) → sửa dùng chung `on_upload_throttle()` có bậc thang.
6. **Health Check không gỡ khoá 30 phút của `_sv_auto_relaunch_ext_browser`** sau khi tự phục hồi cookie → sửa reset `_relaunch_fail_streak`.
7. **Proxy cháy vĩnh viễn** → cạn cả pool sau ~21h chạy → thêm `FLAGGED_PROXY_TTL` (mục 5).
8. **Đăng nhập lại quá nhiều lần/ngày tự làm tăng nghi ngờ tài khoản** → bỏ bước đăng nhập lại khi xoay IP (mục 4).
9. **`seedvis_settings.json` chứa API key thật bị commit lên GitHub** (GCP/Gemini/Groq/seedvis keys) → thêm vào `.gitignore`, gỡ khỏi commit local chưa push (`git rm --cached` + amend), cài `git-filter-repo` (chưa chạy — lệnh viết-lại-lịch-sử + force-push bị chặn bởi Claude Code, cần người dùng tự chạy nếu muốn dọn sạch lịch sử cũ đã push).

## 9. Quy tắc vận hành an toàn (RẤT QUAN TRỌNG — đã vi phạm & phải sửa nhiều lần)

- **Sửa `accounts.json`/`settings.json` bằng cách ghi file trực tiếp CHỈ có tác dụng khi app đang TẮT HẲN.** App chỉ load các file này 1 lần lúc khởi động (`App.__init__`); sửa khi app đang chạy sống sẽ (a) không có tác dụng cho tới lần restart kế tiếp, VÀ (b) có nguy cơ bị app tự ghi đè mất (lần `save_accs()`/`save_settings()` tiếp theo của chính app dùng bản trong RAM, không biết gì về sửa đổi ngoài file).
- Quy trình đổi proxy tay an toàn: (1) `curl -x http://user:pass@host:port https://api.ipify.org` để xác nhận proxy còn sống, (2) xác nhận app đã tắt hẳn (`Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'"`), (3) sửa `accounts.json`["proxy"]/`["cookie"]="" `/`["status"]="new"` + `settings.json["flagged_proxies"]`, (4) báo người dùng mở lại app.
- Trước khi commit/push, LUÔN kiểm tra file mới/untracked có chứa secret không (`grep -iE "api_key|secret|password|token"`), đặc biệt các file `*settings.json` ngoài `accounts.json`/`settings.json` gốc (vd `AutoSeedvis/settings.json`, `seedvis_settings.json`) — `.gitignore` hiện đã chặn mọi file tên `settings.json` ở BẤT KỲ thư mục con nào (pattern không có `/` đầu áp dụng đệ quy).
- `day_code_len_github.bat`: tự tăng version + `git add .` (gom MỌI file untracked) + commit + push. Vì gom tất cả nên rất dễ lỡ tay thêm file nhạy cảm — luôn rà `git status` trước khi người dùng chạy file này nếu vừa có file mới xuất hiện.

## 10. Quy ước viết test (scratchpad — không phải trong repo)

Vị trí: `C:\Users\thinc\AppData\Local\Temp\claude\e--ThinAptm0707\<session-id>\scratchpad\` (tạm thời theo phiên, KHÔNG persist qua các phiên Claude Code khác nhau — cần viết lại nếu muốn tái sử dụng).

**Luật cứng, đã vi phạm 2-3 lần và gây hỏng dữ liệu thật**: MỌI test chạm tới `App`/`AccountState`/`ProxyPool` PHẢI mock `save_accs`/`save_settings` ở cấp MODULE ngay đầu file, TRƯỚC bất kỳ import/test nào:
```python
import thin_aptm as T
_saved_accs_log = []
_saved_settings_log = []
T.save_accs = lambda accs: _saved_accs_log.append(list(accs))
T.save_settings = lambda s: _saved_settings_log.append(dict(s))
```
Không được tin tưởng logic nghiệp vụ sẽ "không bao giờ" gọi save thật — 1 nhánh lỗi bất ngờ (vd AttributeError giữa chừng) đủ để code thật chạy tới dòng `save_accs(self.accounts)` với dữ liệu test giả, ghi đè `accounts.json` thật.

Test giả lập đồng hồ (dùng cho các bộ đếm thời gian như rate governor, FLAGGED_PROXY_TTL):
```python
class FakeTime:
    def __init__(self): self.now = 1_000_000.0
    def time(self): return self.now
    def sleep(self, s): self.now += max(0.0, s)
    def __getattr__(self, name):
        import time as _t
        return getattr(_t, name)
clock = FakeTime(); T.time = clock
```

**File test hiện có (tham khảo cấu trúc, cần viết lại nếu bắt đầu phiên mới)**:
- `test_circuit_breaker_stuck.py` — 11 test, mô phỏng kịch bản circuit breaker kẹt vĩnh viễn.
- `test_rate_gov.py` — 42 test, đầy đủ bộ điều tốc AIMD (giãn cách, học trần, bậc thang nghỉ, nghỉ ngắn định kỳ, submit_guard).
- `test_ip_rotate.py` — 22 test, `_sv_try_rotate_burned_ip` (bao gồm test 7 "kịch bản bug thật": proxy vừa cháy cho TK A không được chọn lại cho TK B).
- `test_proxy_flag_ttl.py` — 7 test, TTL hết hạn của `_flagged` (mới nhất, tương ứng mục 5/8.7).
- `test_proxy_assign_specific.py` — 9 test.

Quy trình kiểm chứng trước khi báo "đã sửa xong": `python -m py_compile thin_aptm.py` → chạy lại TOÀN BỘ các file test trên (không chỉ file liên quan tới thay đổi) → `md5sum accounts.json settings.json` trước/sau để xác nhận file thật không bị đụng.

## 11. Bối cảnh vận hành (để hiểu quyết định thiết kế)

- Quy mô mục tiêu: tối đa ~10 tài khoản chạy song song (người dùng xác nhận).
- Pool proxy: 23 proxy dịch vụ thương mại dùng chung nhiều khách hàng (nhiều tiền tố subdomain khác nhau — không có quy luật ISP đáng tin cậy theo tên miền, phải test riêng từng proxy bằng curl).
- Kết luận đã kiểm chứng bằng dữ liệu thực: **tốc độ submit KHÔNG phải nguyên nhân chính gây UNUSUAL_ACTIVITY** — uy tín/lịch sử của từng IP cụ thể quan trọng hơn nhiều. Tài khoản chạy chậm (do bị phạt trước đó) vẫn bị gắn cờ y hệt tài khoản chạy nhanh trên cùng proxy tốt.
- "Media not found" khi render (log `❌ Segment N render thất bại (Extension): failed — Media not found.`) là tín hiệu vô hại đã xác nhận qua code (`flow_batch.py:441`) — operation có thể báo lỗi này mà vẫn giao clip hoàn chỉnh, code đã tự retry đúng thiết kế.
