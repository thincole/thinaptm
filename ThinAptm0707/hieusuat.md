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
