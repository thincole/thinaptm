"""Lịch hỏi lại thích nghi khi chờ job — SDK_SPEC §6.

Tách riêng khỏi `_client.py` để `resources/jobs.py` dùng được mà không tạo vòng
lặp import.
"""

from __future__ import annotations

import random
from typing import Iterator, Optional

__all__ = ["poll_delays", "DEFAULT_WAIT_TIMEOUT", "MAX_POLL_INTERVAL", "NHIP_THEO_LOAI"]

#: Mặc định chờ tối đa 600 giây — SDK_SPEC §6.
DEFAULT_WAIT_TIMEOUT = 600.0

#: ═══════════════════════════════════════════════════════════════════════════
#:  5 → 30 GIÂY NGÀY 16/08/2026: HỎI DÀY KHÔNG LÀM JOB XONG SỚM HƠN
#: ═══════════════════════════════════════════════════════════════════════════
#:
#: Trần cũ là 5 giây, và nó áp cho MỌI loại job. Nhưng thời gian thật của một
#: job không có loại nào gần 5 giây:
#:
#:     ảnh    ~30 giây   (nhanh nhất, đo trên nhà máy thật)
#:     video  ~2 phút
#:     giọng nói  vài chục giây tới vài phút, theo độ dài văn bản
#:
#: Hỏi mỗi 5 giây một việc mất 30 giây là **hỏi sáu lần để nhận một câu trả
#: lời**, năm lần trong đó chắc chắn là "chưa xong". Với video là hai mươi bốn
#: lần hỏi cho một câu trả lời.
#:
#: ═══ CÁI GIÁ, ĐO TRÊN MÁY CHỦ THẬT ═══
#:
#:     GET /v1/jobs  3.146 lần / 5 phút = 10 request/giây từ MỘT khách
#:     → ~2,6 trên 4 lõi CPU của VPS
#:     → load average 10, và POST .../complete hỏng 79% vì giao dịch hết giờ
#:
#: Tức nhịp hỏi dày không chỉ tốn băng thông — nó cướp CPU của chính khâu kết
#: sổ tiền cho những job mà nó đang chờ.
#:
#: ═══ VÌ SAO ĐÚNG 30 GIÂY ═══
#:
#: Chủ dự án chốt con số này, và lý lẽ rất gọn: *"nhanh nhất 1 job cũng là 30
#: giây"*. Job nhanh nhất của cả ba nhà máy đều ≥30 giây, nên mọi lần hỏi cách
#: nhau dưới 30 giây là **chắc chắn** rơi vào lúc job chưa thể xong — không
#: phải "có khả năng lãng phí" mà là lãng phí có thể chứng minh trước.
#:
#: Chậm nhất là biết kết quả muộn hơn 30 giây so với lúc job thật sự xong.
#: Đổi lại tải hỏi giảm 6 lần. Ai cần biết
#: NGAY thì đã có hai đường tốt hơn hẳn và không tốn một lời hỏi nào: webhook,
#: hoặc SSE (`client.jobs.stream`).
MAX_POLL_INTERVAL = 30.0

#: Lần hỏi ĐẦU TIÊN nên rơi vào khoảng job sắp xong, không phải ngay sau khi gửi.
#:
#: Máy chủ trả `estimated_seconds` ngay trong phản hồi 202 — nó biết hàng chờ
#: đang dài bao nhiêu và mỗi job loại đó gần đây mất bao lâu. Bản cũ nhân với
#: 0,5 rồi **kẹp ở 5 giây**, nên với job 30 giây nó vẫn hỏi ở giây thứ 5 và ba
#: mươi giây ước tính kia thành vô nghĩa.
#:
#: 0,8: đợi gần hết quãng dự tính rồi mới hỏi lần đầu. Hụt một chút thì lần hỏi
#: kế tiếp cách đó vài giây, nên không mất mát gì; mà nếu ước tính đúng thì
#: thường chỉ tốn ĐÚNG MỘT lời hỏi cho cả job.
HE_SO_CHO_LAN_DAU = 0.8

#: Nhưng không bao giờ đợi lần đầu quá ngần này (giây) — ước tính có thể sai
#: rất xa khi hàng chờ dài, và khách không nên mù suốt năm phút.
CHO_LAN_DAU_TOI_DA = 60.0

#: ═══════════════════════════════════════════════════════════════════════════
#:  NHỊP HỎI THEO LOẠI JOB — 24/08/2026, CHỦ DỰ ÁN CHỐT
#: ═══════════════════════════════════════════════════════════════════════════
#:
#: *"Ảnh nhanh nhất cũng 30 giây, video nhanh nhất cũng 1 phút"* — nên lần hỏi
#: ĐẦU không bao giờ sớm hơn mốc đó (hỏi trước là chắc chắn nhận "đang chạy"),
#: và các lần sau cũng không dày hơn một phần ba thời gian job ngắn nhất.
#:
#: Đo lô 1000 ảnh + 1000 video thật cùng ngày: lịch cũ (2s → ×1,5 → 30s) sau
#: lần hỏi đầu lại quay về 2, 3, 4,5 giây — với 900 clip đang chờ, tool đẩy
#: **55–106 lượt hỏi/giây** dù có van tổng 20/giây, vì mọi job cùng một lô
#: đồng pha: chúng cùng được tạo, cùng chờ, cùng hỏi. Van tổng chỉ ép được
#: trung bình; nhịp đồng pha vẫn thành từng cơn.
#:
#: Ba luật, mỗi loại một bộ số ``(chờ lần đầu tối thiểu, bước tối thiểu, bước
#: tối đa)``, tính bằng giây:
#:
#:   * ảnh    (30, 10, 30)   — job ~30–60 s
#:   * video  (60, 20, 60)   — job ~1–5 phút
#:   * tts    (30, 10, 30)   — vài chục giây tới vài phút theo độ dài
#:
#: và **rải pha**: mỗi khoảng nghỉ nhân với 0,8–1,2 ngẫu nhiên, để nghìn job cùng
#: lô không cùng hỏi đúng một giây. Không truyền ``kind`` thì lịch cũ giữ nguyên
#: từng chữ — SDK cũ của khách không đổi hành vi.
NHIP_THEO_LOAI = {
    "image": (30.0, 10.0, 30.0),
    "video": (60.0, 20.0, 60.0),
    "tts": (30.0, 10.0, 30.0),
}

#: Biên rải pha: ±20 %.
RAI_PHA = 0.2


def poll_delays(
    estimated_seconds: Optional[float] = None,
    poll_interval: Optional[float] = None,
    kind: Optional[str] = None,
) -> Iterator[float]:
    """Sinh ra khoảng nghỉ trước mỗi lần hỏi lại trạng thái job.

    1. Có `estimated_seconds` → ngủ `estimated * 0.8` (tối đa 60 giây) trước lần
       hỏi ĐẦU. Không có thì ngủ 2 giây.
    2. Sau đó mỗi vòng `interval = min(interval * 1.5, 30s)`, bắt đầu từ `2s`.

    Truyền `poll_interval` để cố định khoảng cách — hữu ích khi bạn tự điều khiển
    nhịp hỏi hoặc khi viết test.

    ⚠ ĐỪNG HỎI DÀY. Không job nào của nền tảng này xong dưới 30 giây (ảnh nhanh
    nhất ~30s, video ~2 phút, giọng nói theo độ dài văn bản). Mỗi lời hỏi thêm
    KHÔNG làm job xong sớm hơn một giây nào — nó chỉ lấy CPU của máy chủ, và
    máy chủ dùng đúng CPU đó để kết sổ tiền cho chính job bạn đang chờ. Đo
    16/08/2026: một khách hỏi 10 lần/giây đã đẩy 79% lượt quyết toán vào lỗi 500.

    Cần biết NGAY thì dùng webhook hoặc SSE (`jobs.stream`) — cả hai đều không
    tốn một lời hỏi nào.

    Truyền ``kind`` (``"image"``/``"video"``/``"tts"``) để lịch bám theo thời
    gian thật của loại job đó và được rải pha — xem `NHIP_THEO_LOAI`.
    """
    if poll_interval is not None:
        fixed = max(float(poll_interval), 0.0)
        while True:
            yield fixed

    # Lần đầu: đợi gần hết quãng máy chủ dự tính rồi mới hỏi. Ước tính đúng thì
    # thường chỉ tốn ĐÚNG MỘT lời hỏi cho cả job.
    first = 2.0
    if estimated_seconds is not None:
        try:
            first = min(float(estimated_seconds) * HE_SO_CHO_LAN_DAU, CHO_LAN_DAU_TOI_DA)
        except (TypeError, ValueError):
            first = 2.0

    theo_loai = NHIP_THEO_LOAI.get(str(kind or "").strip().lower())
    if theo_loai is None:
        yield max(first, 0.0)
        interval = 2.0
        while True:
            yield interval
            interval = min(interval * 1.5, MAX_POLL_INTERVAL)

    # Theo loại: không hỏi trước lúc job SỚM NHẤT có thể xong, bước sau không
    # dày hơn sàn của loại đó, và mọi khoảng nghỉ đều rải pha ±20 %.
    san_dau, buoc_min, buoc_max = theo_loai
    yield _rai(max(first, san_dau))
    interval = buoc_min
    while True:
        yield _rai(interval)
        interval = min(interval * 1.5, buoc_max)


def _rai(giay: float) -> float:
    """Rải pha một khoảng nghỉ: ±`RAI_PHA`, không bao giờ âm."""
    return max(0.0, giay * random.uniform(1.0 - RAI_PHA, 1.0 + RAI_PHA))
