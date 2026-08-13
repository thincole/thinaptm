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
