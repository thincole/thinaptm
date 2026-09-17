# Fix & Tối ưu: Cookie recovery + hiệu năng tổng thể

**Ngày sửa:** 2026-09-15
**File bị sửa:** `thin_aptm.py` (phần 1), sau đó thêm `engine.py`, `thin_aptm.py`, `recaptcha_farm.py`, `auto_voice_sub.py` (phần 2 — tối ưu hiệu năng)
**Triệu chứng ban đầu (Phần 1):** Khi cookie tài khoản Google chết giữa lúc đang chạy tạo video, Health Check / auto re-login báo đã lấy được cookie mới, nhưng các job đang chạy/tiếp theo vẫn fail như thể cookie chưa được refresh.

> File này có 2 phần: **Phần 1** (mục 1-4 bên dưới) là fix bug cookie recovery gốc. **Phần 2** (mục 5) là đợt tối ưu hiệu năng/dọn code trùng lặp toàn bộ codebase thực hiện ngay sau đó, dựa trên audit đọc lại toàn bộ ~10.300 dòng `thin_aptm.py` + các module phụ.

---

## 1. Nguyên nhân gốc

Mỗi tài khoản đang chạy được đại diện bởi 1 object `AccountState` (`thin_aptm.py:390`). `AccountState.cookie` là **bản snapshot lấy 1 lần lúc khởi tạo pool** (dòng 395), không tự động đọc lại từ `self.accounts` / `accounts.json`.

Khi Health Check (`_do_health_check`, dòng 1676) hoặc auto re-login (Chrome profile / password) lấy được cookie mới, nó chỉ ghi vào `self.accounts[i]["cookie"]` và `accounts.json` — **không** ghi vào `AccountState.cookie` mà worker thread đang dùng để gọi API.

Hàm đồng bộ cookie-mới-vào-AccountState-đang-chạy (`_sv_sync_cookies`, dòng 8933) **trước đây chỉ quét `self._sv_pool_states`** → chỉ có tác dụng cho tab **Server 24/7**. Hai tab **Tạo Video** (`self._pool_states`) và **Sản phẩm** (`self._sp_pool_states`) hoàn toàn không được đồng bộ → đây là nguyên nhân chính gây ra triệu chứng.

Ngoài ra, ngay trong tab Server 24/7 (nơi có cơ chế đồng bộ), vẫn có 4 lỗi phụ khiến tài khoản có thể bị khóa nhầm/khóa lâu dù cookie đã sống lại (chi tiết bên dưới).

---

## 2. Danh sách thay đổi

### Fix 1+2 — Tổng quát hóa `_sv_sync_cookies()` (dòng ~8933)
**Vấn đề:** Chỉ đồng bộ cookie cho pool của tab Server 24/7; và chỉ reset trạng thái khi cookie **string thay đổi**, bỏ qua trường hợp Health Check xác nhận lại đúng cookie cũ vẫn còn sống (lỗi thoáng qua, không phải chết thật) → tài khoản bị "bench" vĩnh viễn.

**Sửa:**
- Quét cả 3 pool: `self._pool_states` (Tạo Video), `self._sp_pool_states` (Sản phẩm), `self._sv_pool_states` (Server 24/7).
- Thêm nhánh `revived_same_cookie`: nếu `acc.get("status") == "ok"` (Health Check vừa xác nhận sống) và tài khoản đang `is_circuit_broken()`/rest do auth, dù cookie string không đổi vẫn `reset_circuit_breaker()` + `clear_rest()` + `ensure_auth(force=True)`.
- Đổi log từ `_sv_log_msg` (chỉ hiện ở tab Server 24/7) sang `_log` (log chung) vì giờ áp dụng cho cả 3 tab.

Hàm này được gọi tự động, vô điều kiện trong `finally` của `_do_health_check()` (dòng 1836) — tức chạy sau MỌI lần Health Check (timer định kỳ / nút bấm thủ công / Instant HC) — nên chỉ cần mở rộng vùng quét là tự vá lỗi gốc cho cả 3 tab.

### Fix 3 — Ngưỡng trip circuit breaker khi lỗi auth lúc đang chạy (dòng ~8469 và ~8568)
**Vấn đề:** Tại 2 điểm phát hiện lỗi auth khi upload ảnh (401) và khi submit video, circuit breaker bị trip **ngay từ lỗi đầu tiên**, trái với quy tắc "2 lỗi liên tiếp" đã cài đúng trong `ensure_auth()` (dòng 714). Sau đó rest 60s của `trip_circuit_breaker()` còn bị ghi đè thành rest 1800s (`AUTH_REST`) ngay lập tức — vô ích vì cổng chặn dispatch job chỉ cần `is_circuit_broken()==True` là đủ.

**Sửa:** Chỉ `trip_circuit_breaker()` + trigger Instant Health Check khi `auth_fail_streak >= 2`. Nếu mới lỗi lần đầu (streak == 1), chỉ `rest(AUTH_REST, "auth")` như cũ, không trip breaker.

### Fix 4 — `_proactive_cookie_refresher` thiếu `clear_rest()` (dòng ~8253)
**Vấn đề:** Khi refresh cookie định kỳ (mỗi 20 phút) thành công, chỉ gọi `reset_circuit_breaker()` mà quên `clear_rest()` → tài khoản vẫn bị `rest_remaining() > 0` (tới ~30 phút) dù log đã báo "Cookie OK ✅".

**Sửa:** Thêm `st.clear_rest()` ngay cạnh `st.reset_circuit_breaker()`.

### Fix 5 — Vòng lặp chờ 5 phút trong `process_one` (dòng ~8282)
**Vấn đề:** Vòng lặp tự chờ cookie refresh gọi `st.ensure_auth()` mỗi 10s trên **cùng 1 cookie đã biết chết**, kể cả khi cookie chưa hề đổi. Mỗi lần gọi thất bại lại tăng `auth_fail_streak`, có thể tự vượt ngưỡng 5 lỗi trong 1 sự cố duy nhất và tự đánh dấu tài khoản lỗi vĩnh viễn (`#Auth failed...`, dòng 713). Tài khoản dính prefix `#` sau đó bị `_proactive_cookie_refresher` bỏ qua vĩnh viễn (dòng 8251-8252).

**Sửa:** Bỏ nhánh gọi lại `ensure_auth()` khi cookie chưa đổi; chỉ kiểm tra `st.cookie != old_cookie` (dấu hiệu nền đã refresh) và chỉ gọi `ensure_auth()` một lần khi phát hiện cookie thực sự thay đổi.

---

## 3. Chưa sửa lần này (lưu ý nếu cần làm sau)

- **`_health_checking` là bool thường, không atomic** giữa các thread trigger (timer / nút bấm / Instant HC) — có thể đua nhau chạy `_do_health_check()` song song, gây xung đột khi cùng mở Chrome profile 1 tài khoản. Cách vá: đổi sang `threading.Lock` với `acquire(blocking=False)`. **[Vẫn CHƯA sửa ở Phần 2.]**
- **`E.bearer_from_cookie(a["cookie"])`** trong `check_one()` của Health Check (dòng ~1697) không truyền `proxy=`, khác với mọi lệnh gọi thật khác trong app → có thể cho kết quả sai với tài khoản có proxy riêng. Cần điều tra cách `proxy` được `ProxyPool` gán runtime vào `AccountState.proxy` (hiện không đọc thẳng từ `acc` dict) trước khi vá. **[Vẫn CHƯA sửa ở Phần 2.]**
- **Code chết chưa xóa:** `auto_recover_cookie()` (dòng 632) và `_ensure_checked_accs_alive()` (dòng 3223) — không có nơi nào gọi tới, an toàn để xóa nhưng không bắt buộc. **[Vẫn CHƯA xóa ở Phần 2 — vẫn còn trong code.]**

---

## 4. Cách kiểm thử thủ công

Không có test tự động (app GUI + phụ thuộc mạng/Chrome thật).

1. `python -m py_compile thin_aptm.py` — đảm bảo không lỗi cú pháp.
2. Sửa tay 1 ký tự cookie của 1 tài khoản trong `accounts.json` để giả lập chết, chạy hàng đợi ở tab **Tạo Video**, bấm "Chạy Health Check ngay" → log phải hiện "Cookie đã được làm mới → sẵn sàng!" và job tiếp tục chạy được (trước đây tab này không hề nhận cookie mới).
3. Lặp lại tương tự ở tab **Sản phẩm** và **Server 24/7** để xác nhận cả 3 pool đều nhận cookie mới.
4. Ở tab Server 24/7: giả lập 1 lỗi auth đơn lẻ khi đang submit — xác nhận circuit breaker **không** trip ở lần đầu, chỉ nghỉ bình thường; lỗi lần 2 liên tiếp mới trip + trigger Instant Health Check.

---
---

# PHẦN 2 — Đợt tối ưu hiệu năng toàn codebase

**Bối cảnh:** Sau khi fix xong bug cookie recovery ở Phần 1, đã cho 5 agent đọc lại **toàn bộ** codebase (`thin_aptm.py` ~10.300 dòng, `engine.py`, `login.py`, `browser_stealth.py`, `recaptcha_farm.py`, `shopeevideo.py`, `auto_voice_sub.py`, `ghep_video.py`, `watermark_remover.py`, `prompt_templates.py`, `update.py`) để liệt kê các điểm cần tối ưu. Đã thực hiện toàn bộ nhóm ưu tiên **CAO** (12 mục, chia theo file).

## 5. Danh sách đã sửa

### `engine.py`

**5.1 — Session HTTP theo từng thread (`_get_session()`)**
- Vấn đề: mọi request dùng `cffi.get()`/`cffi.post()` cấp module — mỗi lần gọi tự mở kết nối/TLS handshake mới, tốn tài nguyên với các hàm poll lặp lại liên tục (`poll_video` gọi mỗi 5-20s).
- Sửa: thêm `_get_session(proxy)` — trả về `cffi.Session()` cache theo **từng thread** (`threading.local()`) + chữ ký proxy, KHÔNG dùng 1 Session dùng chung giữa các thread (curl_cffi Session không đảm bảo an toàn khi nhiều thread gọi đồng thời trên cùng 1 object). Thay toàn bộ 22 điểm gọi `cffi.get(`/`cffi.post(` → `_get_session(proxy).get(`/`.post(`. Giữ nguyên cơ chế bắt lỗi proxy 407 (`_wrap_req`) bằng cách wrap `.get`/`.post` của từng Session mới tạo.
- Vị trí: định nghĩa ngay sau khối `cffi.get = _wrap_req(...)` ở đầu file.

**5.2 — Chặn memory leak cache toàn cục**
- Vấn đề: `_wiz_cache`, `_session_token_cache`, `_tier_cache`, `_refresh_locks` là dict không giới hạn, không bao giờ tự dọn — phình to vô hạn khi app chạy 24/7 nhiều ngày.
- Sửa: thêm `_cache_put_ts(cache, lock, key, value, max_size=500)` — evict entry có `ts` cũ nhất khi vượt 500 entry. `_refresh_locks` (không có field `ts`) dùng FIFO đơn giản (thứ tự chèn). **Không đụng `_image_cache`** — đó là cache MD5 ảnh vĩnh viễn có chủ đích (ghi ra `uploaded_image_cache.json`), giới hạn nó sẽ làm mất giá trị cache thật.

**5.3 — Tải video theo stream**
- Vấn đề: `download_video`/`download_url` gọi `.content` (tải hết vào RAM) trước khi ghi file — tốn RAM + trễ với video vài chục-trăm MB, nhiều worker song song.
- Sửa: dùng `stream=True` + `r.iter_content(chunk_size=262144)`, ghi thẳng ra file tạm `<dst>.part` theo chunk, chỉ `os.replace()` thành file thật sau khi xác thực xong magic bytes MP4 (`ftyp`/`moov`) ở chunk đầu tiên. Đã verify chữ ký API `stream`/`iter_content` khớp với `curl_cffi.requests.Session`.

### `thin_aptm.py`

**5.4 — `wait_upload_spacing` không còn giữ lock khi sleep**
- Vấn đề (`AccountState.wait_upload_spacing`): giữ `self.upload_lock` **trong lúc `time.sleep(6-8s)`** → mọi luồng upload khác của cùng tài khoản bị serialize tuần tự, làm cơ chế tăng `upload_threads` (1→4) mất tác dụng thực tế dù UI báo đúng số luồng.
- Sửa: chỉ giữ lock đủ để "đặt chỗ" mốc giờ kế tiếp (`self.last_upload_ts = time.time() + wait_s`), sleep thực hiện **ngoài** lock — các luồng khác vẫn tính đúng khoảng cách 6-8s nhưng không bị chặn lẫn nhau.

**5.5 — Debounce `save_accs()`/`_refresh_acc()` trong Health Check**
- Vấn đề (`_do_health_check`, cả 2 vòng lặp Pha 1 và Pha 2): gọi ghi file `accounts.json` + rebuild toàn bộ UI **sau mỗi tài khoản** → O(N) lần ghi đĩa/rebuild UI, tổng chi phí ~O(N²) khi N lớn.
- Sửa: thêm `_debounced_save_refresh(force=False)` — chỉ lưu/refresh tối đa mỗi 3 giây; luôn lưu ngay khi `force=True` (gọi ở cuối mỗi pha để đảm bảo không mất kết quả tài khoản cuối cùng).

**5.6 — Song song hoá Health Check Pha 1**
- Vấn đề: vòng lặp `L.reopen_profile_cookie(...)` (mở lại Chrome profile) chạy **tuần tự** từng tài khoản chết, mỗi lần tối đa 90s → N tài khoản chết có thể mất N×90s.
- Sửa: tách thân vòng lặp thành hàm `_try_profile_relogin(item)`, chạy qua `ThreadPoolExecutor(max_workers=4)`. Thêm lock (`still_dead_lock`, `_hc_attempted_lock`) bảo vệ các biến/dict dùng chung giữa các thread.

**5.7 — Giới hạn FFmpeg hậu kỳ chạy song song**
- Vấn đề (`_auto_concat`/`_do_build`): mỗi thư mục hoàn thành spawn 1 `threading.Thread` gọi `auto_voice_sub.build_final_video()` (nặng CPU/GPU) **không giới hạn số luồng chạy song song**.
- Sửa: thêm `self._postprocess_sem = threading.Semaphore(2)` ở `__init__`, `_do_build` phải `acquire()` semaphore này trước khi build, tối đa 2 tiến trình hậu kỳ chạy đồng thời trên toàn app.

**5.8 — `busy` check dùng `Condition` có sẵn (cải thiện nhỏ)**
- Cả 3 tab (Tạo Video / Sản phẩm / Server 24/7) đều có đoạn `with st.blk: if st.busy >= max_busy: time.sleep(0.5); continue` — busy-wait dùng Lock thường. Codebase đã có sẵn pattern `Condition.wait(0.5)` + `notify_all()` cho `acquire_submit`/`acquire_upload`. Đổi `busy_dec()` để `notify_all()` trên `self._gate`, và 3 điểm check đổi sang `with st._gate: ... st._gate.wait(0.5)` — đánh thức sớm hơn khi có slot trống thay vì luôn chờ đủ 0.5s. (Đánh giá lại: đây là cải thiện nhỏ, KHÔNG phải lỗi hiệu năng nghiêm trọng như đánh giá ban đầu, vì `time.sleep(0.5)` vốn không tốn CPU đáng kể.)

**5.9 — Trích 6 helper dùng chung, xoá ~15 khối code trùng lặp**
- `_recalc_submit_rate()` (method của `AccountState`) — thay công thức `calc_rate = max(2, min(20, upload_threads+3))` + gán `max_busy/_submit_max/submit_limit` bị lặp 4 lần trong `on_upload_throttle`/`on_upload_ok`/`on_video_ok`/`set_upload_threads`.
- `_bearer_and_email(cookie, proxy=None)` (hàm module) — thay pattern giải nén `E.bearer_from_cookie()` lặp lại 8 lần.
- `_apply_acc_email(a, em, fallback_email=None)` (hàm module) — thay logic chuẩn hoá email (ưu tiên `em` mới, fallback nếu không hợp lệ `@google`) lặp lại nhiều nơi.
- `_profile_dir(email)` (hàm module) — thay `os.path.join(HERE, "_profiles", email.replace("@","_"))` lặp lại 5 nơi.
- `_sv_build_out_name(naming_mode, item_id, idx, prompts)` (hàm module) — thay logic đặt tên file output trùng giữa `process_one_shopapi` và `process_one` (tab Server 24/7).
- `_sv_cleanup_temp(item_id, temp_dir, img_path, clip_paths, del_img, composite_path=None)` (hàm module) — thay logic dọn file tạm trùng giữa 2 hàm trên.
- **Lưu ý phạm vi:** KHÔNG merge toàn bộ `process_one` và `process_one_shopapi` (~300 dòng mỗi hàm) thành 1 — rủi ro cao, chỉ trích các đoạn con đã xác định trùng lặp cụ thể.

**5.12 — Log lỗi thay vì nuốt im lặng ở các điểm nhạy cảm**
- `load_accs()`: log lỗi ra console trước khi trả `[]` (trước đây mất trắng danh sách tài khoản mà không rõ lý do).
- `_update_pool()`: log traceback (giới hạn 1 dòng/30s tránh spam) thay vì `except Exception: pass` nuốt toàn bộ lỗi của panel pool.
- Toàn bộ ~11 điểm `try: self._sv_api_call/_sa_api_call("POST", ".../complete-job"|"release-single-job"|"release-jobs", ...) \n except: pass` (cả 3 tab sv/sp/sa) → đổi thành log lỗi kèm `item_id`/`client_id` cụ thể, để phát hiện được khi server không đồng bộ trạng thái job.

### `recaptcha_farm.py`

**5.10 — Khoá khi truy cập `page` dùng chung + gộp code inject cookie**
- Vấn đề: `get_wiz_tokens_from_browser()` gọi `page.run_js(...)` **không khoá**, trong khi `_get_or_create_session`/`submit_video_native` đều dùng `sess["lock"]` khi thao tác cùng 1 `ChromiumPage` → rủi ro race condition/crash khi 2 thread cùng dùng 1 session.
- Sửa: bọc phần thao tác `page` bằng `sess["lock"].acquire(timeout=5)` (bỏ qua candidate đó nếu không lấy được lock trong 5s, không chờ vô hạn), giải phóng trong `finally`.
- Trích `_inject_cookies(page, cookie_str, url=FLOW_URL, clear_old=False)` (hàm module, đặt trước `class RecaptchaFarm`) — thay logic "set cookie qua CDP `Network.setCookie`" bị lặp lại y hệt ở 3 nơi (`_get_or_create_session`, `_worker` khởi tạo, `_worker` reload khi cookie chết).

### `auto_voice_sub.py`

**5.11 — Song song hoá encode từng clip + cảnh báo lỗi tách audio**
- Vấn đề (`build_final_video` bước 1): vòng `for i in range(n)` chạy tuần tự 3 lệnh `subprocess` (probe duration, mute clip, setpts encode) cho từng clip — các clip độc lập nhau nhưng không chạy song song, là điểm nghẽn lớn nhất ở bước dựng hậu kỳ.
- Sửa: tách thân vòng lặp thành `_adjust_one_clip(i)`, chạy qua `ThreadPoolExecutor(max_workers=max(1, min(4, n)))`, dùng `ex.map()` để giữ đúng thứ tự `adjusted_clips`. Nếu nhiều luồng NVENC tranh chấp GPU, cơ chế fallback CPU (`libx264`) đã có sẵn tự khắc phục cho từng clip riêng lẻ.
- Khi tách audio (`cmd_silent`) thất bại và phải dùng lại clip gốc (có tiếng), thêm `log_cb(f"⚠️ ...")` cảnh báo rõ — trước đây âm thầm dùng clip có tiếng gốc mà không log gì, có thể khiến video ra bị lẫn 2 nguồn audio mà không ai biết.

## 6. Chưa sửa ở Phần 2 (không thuộc phạm vi, cân nhắc làm sau nếu cần)

- Không merge `process_one`/`process_one_shopapi` thành 1 hàm dùng chung hoàn toàn (chỉ trích các đoạn con, xem mục 5.9).
- Không đổi kiến trúc cache `engine.py` thành LRU thư viện ngoài (dùng cách giới hạn kích thước dict đơn giản để giảm rủi ro).
- Các mục ưu tiên TRUNG BÌNH/THẤP từ đợt audit (trùng lặp code nhỏ hơn, magic number rải rác, dead code khác...) chưa động tới.

## 7. Cách kiểm thử Phần 2

Không có test tự động (app GUI + phụ thuộc mạng thật/Chrome thật/GPU thật). Đã verify được trong môi trường dev:
- `python -m py_compile engine.py thin_aptm.py recaptcha_farm.py auto_voice_sub.py` — không lỗi cú pháp.
- `python -c "import thin_aptm"` / `import engine` / `import recaptcha_farm` / `import auto_voice_sub` — không lỗi runtime ở module-level.
- Test độc lập: session `curl_cffi` tái sử dụng đúng theo thread, cache eviction hoạt động đúng khi vượt 500 entry, `stream`/`iter_content` đúng chữ ký API.

**Cần tự kiểm thử thủ công (không thể test trong môi trường này):**
1. Chạy tạo video thật ở cả 3 tab — xác nhận tốc độ upload nhanh hơn (mục 5.4), không có lỗi mạng mới (do đổi session ở mục 5.1).
2. Bấm Health Check thủ công với vài tài khoản cookie chết — xem log Pha 1 chạy song song đúng (mục 5.6), UI không bị đơ do debounce (mục 5.5).
3. Dựng hậu kỳ lồng tiếng với video nhiều phân cảnh — xem GPU (NVENC) có bị tranh chấp không khi chạy song song (mục 5.11); nếu có, phải thấy log tự fallback sang CPU cho từng clip.
4. Theo dõi log dài (~30-60 phút chạy liên tục) để xác nhận không có lỗi mới phát sinh, đặc biệt các dòng log lỗi mới thêm ở mục 5.12 (nếu thấy log lỗi complete-job/release-job xuất hiện thường xuyên, nghĩa là server đang có vấn đề thật — trước đây bị nuốt im lặng nên không ai biết).
