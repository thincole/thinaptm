# Quy tắc phát triển dự án Thìn Aptm

Tài liệu này chứa các quy tắc thiết kế, hành vi và tính năng tùy chỉnh cốt lõi của phần mềm Thìn Aptm. BẤT KỲ hoạt động cập nhật hoặc sửa chữa code nào sau này đều phải tuân thủ nghiêm ngặt các quy tắc dưới đây.

---

## 1. Cơ chế đặt tên Video tùy chọn
- Giao diện phải duy trì menu chọn đặt tên bao gồm 3 chế độ:
  1. **Đặt tên theo ảnh:** Sử dụng tên file ảnh gốc (khử ký tự đặc biệt).
  2. **13 ký tự đầu prompt:** Trích 13 ký tự đầu của prompt làm tên file.
  3. **Số thứ tự (001...):** Tự động đánh số tăng dần.
- Luôn sử dụng hàm kiểm tra trùng lặp để sinh tên duy nhất dạng `tenvideo_2.mp4` nếu bị trùng tên file trong thư mục đầu ra.

## 2. Hệ thống kiểm soát luồng & Rate limit (Chống lỗi 429)
- **Đồng bộ hóa tài khoản (`Lock` per account):** Khi chạy đa luồng, mỗi tài khoản hoạt động phải giữ 1 khóa riêng biệt. Không cho phép gửi yêu cầu song song cùng lúc trên 1 tài khoản để tránh lỗi trùng phiên.
- **Giãn cách gửi (4 giây):** Luồng phải giữ khóa thêm 4 giây sau khi gửi request thành công trước khi nhả khóa cho luồng khác.
- **Tự động chờ phạt (30s - 150s):** Nếu gặp lỗi HTTP 429 (`Resource has been exhausted / PUBLIC_ERROR_USER_REQUESTS_THROTTLED`), luồng phải tự động nghỉ từ 30s đến tối đa 150s (với số giây tăng dần theo số lần dính lỗi liên tiếp) rồi tự động thử lại, tránh ghi nhận lỗi ngay lập tức.
- **Tôn trọng luồng cấu hình:** Không tự động hạ hoặc giới hạn số luồng của người dùng cấu hình trên giao diện.

## 3. Quản lý lỗi chính sách ("vi phạm cs")
- **Nhận diện lỗi chính sách của Google:**
  - `PUBLIC_ERROR_PROMINENT_PEOPLE_FILTER_FAILED` (Lọc người nổi tiếng)
  - `PUBLIC_ERROR_AUDIO_FILTERED` (Lọc âm thanh)
- **Xử lý trạng thái:** Khi gặp các lỗi này, chuyển trạng thái job thành `"vi phạm cs"`, hiển thị với icon cảnh báo màu vàng `⚠️ vi phạm cs`. Các lỗi này vẫn được tính gộp vào tổng số lỗi trong phần thống kê.
- **Nút xóa chuyên dụng:** Giao diện bắt buộc phải có nút `"🗑 Xóa Vi Phạm CS"` (màu đỏ nhạt `#E57373`) để xóa toàn bộ các job có trạng thái `"vi phạm cs"` ra khỏi hàng đợi.

## 4. Tải nặng & Hiển thị Hàng Đợi (Không giới hạn dòng)
- Hiển thị toàn bộ các job trong hàng đợi chi tiết (không giới hạn 300 dòng).
- Để tránh treo UI:
  - Các thẻ đếm thống kê và progress bar cập nhật mỗi 1 giây.
  - Hộp Textbox danh sách chi tiết chỉ vẽ lại mỗi 5 giây 1 lần khi phần mềm đang chạy (`running = True`), và vẽ lập tức khi bắt đầu/dừng/xóa/retry (`force = True`).

## 5. Lưu phiên làm việc
- Lưu toàn bộ cài đặt giao diện (chế độ, thư mục, tỉ lệ, luồng, chế độ đặt tên) kèm danh sách hàng đợi hiện tại (`jobs`) vào `settings.json` khi đóng phần mềm và tự động khôi phục lại khi khởi động.

## 6. Quy định bảo vệ phân mục "Tài khoản"
- BẤT KỲ hoạt động chỉnh sửa, nâng cấp, sửa lỗi nào liên quan đến code thuộc phân mục "Tài khoản" (Accounts) trên giao diện hoặc logic ngầm đều **bắt buộc phải hỏi ý kiến và được sự đồng ý của người dùng** trước khi tiến hành viết code. Không tự động quyết định cấu trúc hay tính năng tài khoản.

## 7. Cơ chế tích hợp Auto HomeProxy
- **Cấu hình**: Cung cấp checkbox `"Auto HomeProxy"` (lưu vào biến `auto_homeproxy`) và ô nhập `"Token"` (lưu vào biến `homeproxy_token`).
- **Làm sạch Token**: Tự động lọc bỏ tiền tố `"Bearer "` nếu người dùng dán nhầm.
- **Xác thực**: Gửi yêu cầu HTTP đi kèm hai header: `Authorization: Bearer <token>` và `x-merchant-id: <merchant_id>`.
- **Tìm Merchant ID**: Tự động gọi API `/orders?page=1&limit=1` để lấy `merchant_id` của tài khoản và truyền vào header khi cần.
- **Endpoint lấy Proxy**: 
  - *Chính*: `GET https://app.homeproxy.vn/api/v2/users/proxies?page=1&limit=500` (hoặc domain `api.homeproxy.vn/api/v1`).
  - *Giải mã mật khẩu*: Giải mã base64 của trường `password` trong dữ liệu trả về trước khi nạp vào Proxy Pool.
  - *Lọc hạn dùng*: Chỉ nạp proxy có `status = Completed` và `expiredAt` chưa hết hạn.
  - *Cảnh báo*: Nếu bị lỗi (như 401, 0 proxy), phải hiển thị hộp thoại cảnh báo Popup (`messagebox.showwarning`) cho người dùng.
- **Auto-load**: Tự động gọi API tải proxy mới nhất khi khởi động ứng dụng và trước khi chạy phiên làm việc (cả tab thường và tab tạo từ Server).

## 8. Dọn dẹp bộ nhớ đệm khi tắt ứng dụng
- Khi người dùng tắt phần mềm (hàm destroy/exit), bắt buộc phải thực hiện xóa sạch toàn bộ các file ảnh và video tạm thời bên trong thư mục `temp_render` để giải phóng không gian đĩa cho hệ thống của người dùng.

## 9. Hệ thống Bảo vệ 4 Lớp cho Chế độ Cắm 24/7

Hệ thống này được thiết kế để giảm tỷ lệ sản phẩm bị đánh dấu `failed` do cookie tài khoản Google hết hạn giữa chừng từ **~45%** xuống **≈ 0%** khi treo máy liên tục 24/7.

### 9.1 Lớp 1: Circuit Breaker (Ngắt mạch tài khoản tức thì)
- **Thuộc tính**: `AccountState` phải có `auth_fail_streak` (int) và `_circuit_broken` (bool).
- **Cơ chế**: Khi 1 tài khoản dính **2 lỗi auth liên tiếp** (`ensure_auth()` fail hoặc `v_status == "auth"`):
  - Lập tức gọi `trip_circuit_breaker()`: đánh dấu `_circuit_broken = True`, cho tài khoản nghỉ 60 giây.
  - Kích hoạt Instant Health Check (Lớp 3) ngay lập tức.
  - Các worker không giao thêm job cho tài khoản này (vì `rest_remaining() > 0`).
- **Reset**: Khi cookie được làm mới thành công → gọi `reset_circuit_breaker()` để reset `auth_fail_streak = 0` và `_circuit_broken = False`.
- **Quan trọng**: Khi `ensure_auth()` thành công → luôn reset `auth_fail_streak = 0`.

### 9.2 Lớp 2: Trả lại Job thay vì đánh dấu `failed`
- **Cơ chế**: Trong worker loop, khi `result == "retry_soft"` và `prod["_cycles"] >= 3`:
  - Kiểm tra `is_auth_failure = st.is_circuit_broken() or st.rest_reason in ("auth", "circuit_breaker")`.
  - **Nếu lỗi do auth/cookie** (`is_auth_failure = True`):
    - Gọi API `POST /api/thinaptm/release-single-job` với `{"itemId": item_id}` để trả SP về trạng thái `pending` trên Database.
    - Reset `prod["_cycles"] = 0` và đưa lại vào queue nội bộ để thử lại sau khi tài khoản hồi sinh.
    - Log: `"🔄 Trả SP {item_id} về pending (TK đang chết cookie)"`.
  - **Nếu lỗi thật sự do sản phẩm** (`is_auth_failure = False`):
    - Đánh dấu `"failed"` trên Server như bình thường.
- **Server endpoint**: `POST /api/thinaptm/release-single-job` nhận `{ itemId }` → cập nhật `video_status = 'pending'`, xóa `claimed_by` và `claimed_at`. Chỉ release SP có `video_status = 'processing'`.

### 9.3 Lớp 3: Kích hoạt Health Check Khẩn cấp Tức thì (Instant Health Check)
- **Method**: `_trigger_instant_health_check(target_email)`:
  - Kiểm tra `self._health_checking` — nếu đang chạy thì bỏ qua (tránh chồng chéo).
  - Nếu chưa chạy → khởi động `_do_health_check()` trong thread mới.
  - Sau khi Health Check hoàn tất → gọi `_sv_sync_cookies()` để đồng bộ cookie mới.
- **Method**: `_sv_sync_cookies()`:
  - Duyệt `self._sv_pool_states`, tìm tài khoản khớp trong `self.accounts`.
  - Nếu cookie mới khác cookie cũ → cập nhật `st.cookie`, gọi `reset_circuit_breaker()`, `clear_rest()`, `ensure_auth(force=True)`.
- **Tích hợp**: Được kích hoạt tự động bởi Circuit Breaker (Lớp 1) khi trip, và bởi Proactive Refresh (Lớp 4) khi phát hiện cookie hết hạn.

### 9.4 Lớp 4: Làm mới Cookie Chủ động (Proactive Cookie Refresh)
- **Thread**: `_proactive_cookie_refresher()` chạy nền trong `_sv_start_run()`.
- **Chu kỳ**: Mỗi **20 phút** (`BEARER_TTL = 1200s`), quét tất cả tài khoản:
  - Gọi `st.ensure_auth(force=True)` cho từng tài khoản xoay vòng (mỗi TK cách nhau **5 giây** để tránh làm mới cùng lúc).
  - Nếu thành công → `reset_circuit_breaker()`, log `"🔄 {email}: Cookie OK ✅"`.
  - Nếu thất bại → kích hoạt Instant Health Check (Lớp 3).
- **Mục đích**: Cookie Google thường hết hạn sau ~60 phút. Thread này chủ động làm mới TRƯỚC KHI hết hạn → tài khoản gần như không bao giờ bị chết cookie nữa.

### 9.5 Các thông số giới hạn hiệu năng
- **Luồng Upload ảnh đồng thời (`upload_sem`)**: **4 luồng** — tối ưu cho chạy 24/7 liên tục, tránh bị Google đánh dấu IP.
- **Số nhân CPU cho 1 tiến trình FFmpeg (`-threads 2`)**: **2 nhân/tiến trình** — chống lag máy khi ghép video.
- **Luồng ghép video FFmpeg đồng thời (`merge_sem`)**: `max(2, os.cpu_count() // 8)` — tự động theo CPU (ví dụ: 7 luồng cho CPU 56 nhân).
- **Thời gian chờ Token Farm (`timeout`)**: **2 giây** — ưu tiên token tươi, fallback bypass tĩnh nếu kho trống.

### 9.6 Log nhận diện khi chạy thực tế
```
🔌 Circuit Breaker: {email} ngắt mạch sau 2 lỗi auth liên tiếp        ← Lớp 1
🔄 Trả SP {item_id} về pending (TK đang chết cookie)                   ← Lớp 2
⚡ [Instant HC] Kích hoạt Health Check khẩn cấp cho {email}...          ← Lớp 3
✅ [Sync] {email}: Cookie đã được làm mới → sẵn sàng!                   ← Lớp 3
🔄 [Proactive Refresh] Bắt đầu làm mới cookie tất cả tài khoản...      ← Lớp 4
🔄 {email}: Cookie OK ✅                                                 ← Lớp 4
```
