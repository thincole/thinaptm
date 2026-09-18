"""Flow's batchexecute API — transport chuẩn bị thay REST cho chế độ Extension.

Google di chuyển Flow sang flow.google.com (9/2026) và ngừng phát Bearer ya29
mà toàn bộ engine.py (REST) đang phụ thuộc. Frontend mới ký mọi request bằng
cookie phiên + token CSRF theo từng trang (`at`), qua đúng 1 endpoint
batchexecute. Không thể replay request này từ ngoài trình duyệt — lệnh tạo
media còn kèm reCAPTCHA dùng 1 lần, gửi lại là dính PUBLIC_ERROR_UNUSUAL_ACTIVITY.

Vì vậy module này KHÔNG đụng mạng: chỉ build request envelope và đọc response.
Việc gửi request thật là của Chrome Extension (flow_bridge.py cầu nối,
extension/background.js chạy payload ngay trong tab Flow đã đăng nhập).

Định dạng batchexecute của Google:

    f.req = [[[rpcid, "<inner payload dạng chuỗi JSON>", null, "generic"]]]

response có tiền tố chống-hijack ``)]}'`` rồi tới các chunk có độ dài đứng
trước, mỗi chunk chứa envelope ``["wrb.fr", rpcid, "<payload dạng chuỗi JSON>", …]``.

Port gần như nguyên vẹn từ E:\\0 -Flowkit\\agent\\services\\flow_batch.py (dự án
độc lập, đã dùng ổn định để tạo video trực tiếp trên flow.google.com) — module
này không có phụ thuộc riêng của FlowKit nên port thẳng, chỉ đổi phần mô tả.
"""
from __future__ import annotations

import json
import random
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

BATCH_PATH = "/_/AiSandboxAngularFrontend/data/batchexecute"
MEDIA_HOST = "flow-content.google"

RPC_GEN_IMAGE = "ogiZ0b"
RPC_GEN_VIDEO = "eb1hJf"
RPC_OPERATION = "jwpduf"
RPC_PROJECT_MEDIA = "Zzl0ze"
RPC_MEDIA = "as29s"
RPC_UPLOAD_IMAGE = "maseQ"

CAPTCHA_IMAGE = "IMAGE_GENERATION"
CAPTCHA_VIDEO = "VIDEO_GENERATION"

#: Extension sẽ thay thế marker này bằng 1 token reCAPTCHA mint tươi — phải là
#: placeholder vì token chỉ được mint ngay trong trang, ngay trước lúc gửi.
CAPTCHA_SLOT = "__CAPTCHA__"

#: Tên wire mà đường batchexecute chấp nhận — cái khác bị Flow từ chối thẳng.
#: GEM_PIX_2 = Nano Banana Pro, NARWHAL = Banana 2.
IMAGE_MODELS = {"GEM_PIX_2", "NARWHAL"}
IMAGE_MODEL = "GEM_PIX_2"

#: Alias đặt tên kiểu cũ -> tên wire mới.
IMAGE_MODEL_BY_NICKNAME = {"NANO_BANANA_PRO": "GEM_PIX_2", "NANO_BANANA_2": "NARWHAL"}

#: Tỉ lệ ảnh — đo bằng cách tạo từng loại rồi đọc header JPEG thật.
#: 1 = vuông (không phải "số lượng" như nhìn tưởng ban đầu).
ASPECT_SQUARE = 1           # 1024x1024
ASPECT_PORTRAIT = 2         # 768x1376  (9:16)
ASPECT_LANDSCAPE = 3        # 1376x768  (16:9)
ASPECT_PORTRAIT_4_3 = 4     # 896x1200  (3:4)
ASPECT_LANDSCAPE_4_3 = 5    # 1200x896  (4:3)

#: Tên gọi kiểu REST cũ, để code gọi vẫn dùng được tên quen thuộc.
ASPECT_BY_NAME = {
    "IMAGE_ASPECT_RATIO_SQUARE": ASPECT_SQUARE,
    "IMAGE_ASPECT_RATIO_PORTRAIT": ASPECT_PORTRAIT,
    "IMAGE_ASPECT_RATIO_LANDSCAPE": ASPECT_LANDSCAPE,
    "IMAGE_ASPECT_RATIO_PORTRAIT_FOUR_THREE": ASPECT_PORTRAIT_4_3,
    "IMAGE_ASPECT_RATIO_LANDSCAPE_FOUR_THREE": ASPECT_LANDSCAPE_4_3,
}

#: Model video đường batch chấp nhận. Bảng REST cũ khóa theo [tier][chất
#: lượng][tỉ lệ] và có hậu tố _portrait/_fl/_relaxed; giờ tỉ lệ và nối cảnh là
#: field riêng, tên có hậu tố bị từ chối — chỉ còn ý định tier/chất lượng.
VIDEO_MODEL = "veo_3_1_i2v_lite_low_priority"
VIDEO_MODELS = {
    "veo_3_1_i2v_lite_low_priority",
    "veo_3_1_i2v_lite",
    "veo_3_1_i2v_s_fast_ultra",
}

#: Tỉ lệ video KHÔNG dùng chung mã với ảnh: ở đây 1 = dọc (ảnh thì 1 = vuông).
VIDEO_ASPECT_PORTRAIT = 1
VIDEO_ASPECT_LANDSCAPE = 2

VIDEO_ASPECT_BY_NAME = {
    "VIDEO_ASPECT_RATIO_PORTRAIT": VIDEO_ASPECT_PORTRAIT,
    "VIDEO_ASPECT_RATIO_LANDSCAPE": VIDEO_ASPECT_LANDSCAPE,
}

#: "CAE" là trạng thái kết thúc của operation. Khác đi nghĩa là còn đang chạy.
STATUS_DONE = "CAE"

#: Mã kết quả trong khối status của operation. Mã 4 kèm thông báo kiểu
#: "Media not found." — nhưng KHÔNG phải phán quyết cuối: job báo mã này vẫn
#: có thể hoàn thành bình thường, chỉ nên dùng để log khi timeout, không phải
#: lý do dừng chờ.
OUTCOME_OK = 3
OUTCOME_COMPLAINT = 4

#: Surface id web client luôn đóng dấu — hằng số trong mọi lần bắt được.
SURFACE_ID = 22

#: Khung crop trên ảnh tham chiếu, y hệt UI khi không ai chỉnh tay.
FULL_FRAME_CROP = [None, 0.0038759689922481244, 1, 0.9961240310077519]

#: Ảnh tham chiếu, đúng thứ tự UI gửi: media id ở ĐẦU, cờ loại ở vị trí thứ 5.
REF_TYPE_IMAGE = 1


class RpcError(RuntimeError):
    """Envelope batchexecute trả về có ô lỗi thay vì dữ liệu."""

    def __init__(self, rpcid: str, detail: Any):
        super().__init__(f"{rpcid} failed: {detail!r}")
        self.rpcid = rpcid
        self.detail = detail


class FlowBatchError(RuntimeError):
    """Gọi thành công nhưng payload không chứa thứ cần tìm."""


@dataclass(frozen=True)
class RpcResult:
    rpcid: str
    data: Any
    error: Any = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class GeneratedImage:
    media_id: str
    url: str


@dataclass(frozen=True)
class Operation:
    operation_id: str
    project_id: Optional[str]
    status: Optional[str]
    error: Optional[str] = None

    @property
    def done(self) -> bool:
        return self.status == STATUS_DONE

    @property
    def complained(self) -> bool:
        """Poll báo phàn nàn — quan sát cho thấy vẫn có thể sống sót, cứ kiểm tra listing."""
        return self.error is not None


@dataclass(frozen=True)
class MediaUrls:
    media_id: str
    video: Optional[str] = None
    image: Optional[str] = None


# ── model / aspect resolvers ─────────────────────────────────────────────────

def resolve_image_model(key: Optional[str]) -> str:
    """Nhận nickname hoặc tên wire, trả tên wire; cái lạ thì ép về mặc định."""
    if isinstance(key, str):
        if key in IMAGE_MODEL_BY_NICKNAME:
            return IMAGE_MODEL_BY_NICKNAME[key]
        if key in IMAGE_MODELS:
            return key
    return IMAGE_MODEL


def resolve_video_model(key: Optional[str]) -> str:
    """Map model key kiểu REST cũ sang tên đường batch chấp nhận."""
    if isinstance(key, str):
        if key in VIDEO_MODELS:
            return key
        if "ultra" in key:
            return "veo_3_1_i2v_s_fast_ultra"
        if "lite_low_priority" in key:
            return "veo_3_1_i2v_lite_low_priority"
        if "lite" in key:
            return "veo_3_1_i2v_lite"
    return VIDEO_MODEL


def resolve_aspect(aspect: Any) -> int:
    """Nhận cả giá trị wire lẫn tên kiểu REST cũ."""
    if isinstance(aspect, int):
        return aspect
    try:
        return ASPECT_BY_NAME[aspect]
    except KeyError:
        raise ValueError(
            f"unknown aspect {aspect!r} — use one of {sorted(ASPECT_BY_NAME)} or 1-5"
        ) from None


def resolve_video_aspect(aspect: Any) -> int:
    if isinstance(aspect, int):
        if aspect not in (VIDEO_ASPECT_PORTRAIT, VIDEO_ASPECT_LANDSCAPE):
            raise ValueError(f"video aspect must be 1 or 2, got {aspect}")
        return aspect
    try:
        return VIDEO_ASPECT_BY_NAME[aspect]
    except KeyError:
        raise ValueError(
            f"unknown video aspect {aspect!r} — use one of "
            f"{sorted(VIDEO_ASPECT_BY_NAME)} or 1-2"
        ) from None


# ── envelope codec ───────────────────────────────────────────────────────────

def build_envelope(rpcid: str, inner: Any) -> str:
    """Bọc payload bên trong thành chuỗi f.req mà batchexecute cần."""
    return json.dumps(
        [[[rpcid, json.dumps(inner, separators=(",", ":"), ensure_ascii=False), None, "generic"]]],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def parse_envelope(text: str) -> list[RpcResult]:
    """Bóc tiền tố `)]}'` và các chunk có độ dài đứng trước.

    Độ dài chunk đếm ký tự, nhưng payload có thể lệch tiền tố 1-2 byte khi có
    ký tự escape, nên JSON được decode bằng cách quét thay vì tin tiền tố.
    """
    if not text:
        return []
    body = text.split("\n", 1)[1] if text.startswith(")]}'") else text
    decoder = json.JSONDecoder()
    results: list[RpcResult] = []
    index = 0
    while index < len(body):
        start = body.find("[", index)
        if start == -1:
            break
        try:
            chunk, consumed = decoder.raw_decode(body[start:])
        except json.JSONDecodeError:
            # bước qua dấu `[` này và quét tiếp — 1 ranh giới chunk rơi giữa
            # token không nên làm mất các envelope phía sau nó
            index = start + 1
            continue
        index = start + consumed
        for entry in chunk if isinstance(chunk, list) else []:
            if not isinstance(entry, list) or not entry or entry[0] != "wrb.fr":
                continue
            rpcid = entry[1] if len(entry) > 1 else "?"
            payload = entry[2] if len(entry) > 2 else None
            if payload is None:
                # ô 5 là ô lỗi; là mã kiểu `[5]`, không phải văn bản
                results.append(RpcResult(rpcid, None, entry[5] if len(entry) > 5 else True))
                continue
            results.append(
                RpcResult(rpcid, json.loads(payload) if isinstance(payload, str) else payload)
            )
    return results


def first_payload(text: str, rpcid: str) -> Any:
    """Payload của envelope khớp đầu tiên, hoặc raise đúng lỗi đã xảy ra."""
    results = parse_envelope(text)
    for result in results:
        if result.rpcid != rpcid:
            continue
        if not result.ok:
            raise RpcError(rpcid, result.error)
        return result.data
    preview = (text[:160] + "...") if len(text) > 160 else text
    msg = f"no {rpcid} envelope in response ({len(results)} others)"
    if not text:
        msg += " (empty response; tab may be asleep or disconnected)"
    elif "<html" in text.lower() or "<!doctype" in text.lower():
        msg += " (Flow tab returned HTML; session expired or requires login/refresh)"
    elif len(results) == 0:
        msg += f" (response: {preview!r})"
    raise FlowBatchError(msg)


# ── request builders ─────────────────────────────────────────────────────────

def _client_uuid() -> str:
    """UUID phía client. UI gửi dạng chữ hoa — khớp theo đúng kiểu đó."""
    return str(uuid.uuid4()).upper()


def _context(project_id: str) -> list:
    """Envelope surface/project/captcha mà mọi lệnh generate đều lặp lại."""
    return [None, SURFACE_ID, None, None, None, project_id, None, None, None, None,
            [CAPTCHA_SLOT, 1]]


def _reference(media_id: str) -> list:
    return [media_id, None, None, None, REF_TYPE_IMAGE]


def image_request(prompt: str, project_id: str, count: int = 1,
                  aspect: Any = ASPECT_SQUARE, seed: Optional[int] = None,
                  prompts: Optional[list[str]] = None,
                  model: str = IMAGE_MODEL,
                  ref_media_ids: Optional[list[str]] = None) -> str:
    """1 request item / biến thể, đúng như payload REST cũ từng làm.

    Không có field "số lượng": Flow trả 1 ảnh mỗi item trong list, nên `count`
    nhân bản item với seed mới. `ref_media_ids` gán điều kiện theo ảnh đã có
    sẵn trong project — đây là thứ giữ 1 nhân vật giống nhau qua các cảnh.
    """
    ratio = resolve_aspect(aspect)
    base = seed if seed is not None else random.randint(1, 10**9)
    items = []
    for index in range(max(1, count)):
        text = prompts[index] if prompts and index < len(prompts) else prompt
        refs = [_reference(mid) for mid in (ref_media_ids or [])] or None
        items.append([None, None, refs, base + index * 9973, ratio, model, None,
                      _context(project_id), [[[text]]], None, None, None,
                      _client_uuid(), _client_uuid()])
    return build_envelope(RPC_GEN_IMAGE, [None, items, 1, _context(project_id),
                                          [_client_uuid()]])


def video_request(prompt: str, project_id: str, source_media_id: str,
                  crop: Optional[list] = None,
                  aspect: Any = VIDEO_ASPECT_LANDSCAPE,
                  model: str = VIDEO_MODEL) -> str:
    inner = [
        [[[None, None, [[[prompt]]]], model, resolve_video_aspect(aspect), None,
          [None, source_media_id, None, None, None,
           FULL_FRAME_CROP if crop is None else crop],
          [None, None, None, None, _client_uuid(), _client_uuid()]]],
        _context(project_id),
        [_client_uuid(), 2],
    ]
    return build_envelope(RPC_GEN_VIDEO, inner)


def upload_request(image_b64: str, project_id: str, mime_type: str = "image/jpeg",
                   file_name: str = "upload.jpg") -> str:
    """Đưa 1 ảnh cục bộ vào project để dùng làm ảnh tham chiếu.

    Bytes đi kèm ngay trong RPC dạng base64 thuần — không tiền tố `data:`,
    không endpoint upload riêng — và lệnh này cũng mang captcha như 1 lệnh
    generate.
    """
    return build_envelope(RPC_UPLOAD_IMAGE, [
        _context(project_id), image_b64, mime_type, 1, None, None, None, None,
        file_name, None, _client_uuid(), _client_uuid(),
    ])


def operation_request(operation_id: str) -> str:
    return build_envelope(RPC_OPERATION, [None, None, [[operation_id]]])


def project_media_request(project_id: str) -> str:
    return build_envelope(RPC_PROJECT_MEDIA, [f"projects/{project_id}", None, None, None, [1]])


def media_request(media_id: str) -> str:
    return build_envelope(RPC_MEDIA, [media_id])


# ── response readers ─────────────────────────────────────────────────────────

def _walk_strings(node: Any):
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from _walk_strings(item)


def _walk_lists(node: Any):
    if isinstance(node, list):
        yield node
        for item in node:
            yield from _walk_lists(item)


def read_images(payload: Any) -> list[GeneratedImage]:
    """URL CDN ký sẵn trả về ngay trong lệnh ảnh — 1 cái / biến thể.

    Media id đọc ra từ path của URL thay vì từ 1 chỉ số cố định: URL mới là
    thứ thật sự cần, ghép cặp ngay tại nguồn để response bị xáo trộn không
    làm lệch id với ảnh.
    """
    images: list[GeneratedImage] = []
    seen: set[str] = set()
    for text in _walk_strings(payload):
        if MEDIA_HOST + "/image/" not in text:
            continue
        media_id = text.split("/image/", 1)[1].split("?", 1)[0]
        if media_id in seen:
            continue
        seen.add(media_id)
        images.append(GeneratedImage(media_id=media_id, url=text))
    return images


def read_uploaded_media_id(payload: Any) -> str:
    """`[[mediaId, projectId, operationId, "CAE", …]]` — id này là thứ 1 lệnh
    generate sau đó truyền vào làm reference."""
    record = payload[0] if isinstance(payload, list) and payload else None
    media_id = record[0] if isinstance(record, list) and record else None
    if not isinstance(media_id, str) or not media_id:
        raise FlowBatchError("upload response carried no media id")
    return media_id


def read_operation(payload: Any) -> Operation:
    """`[null, 50, [[opId, projectId, sceneId, status, …]]]`.

    Lưu ý uuid thứ 3 là **scene**, không phải media. Đọc nhầm thành media id
    là lý do mọi lần tra `as29s` trả về NOT_FOUND.
    """
    records = payload[2] if isinstance(payload, list) and len(payload) > 2 else None
    record = records[0] if isinstance(records, list) and records else None
    if not isinstance(record, list) or not record:
        raise FlowBatchError("operation payload carried no record")
    return Operation(
        operation_id=record[0],
        project_id=record[1] if len(record) > 1 else None,
        status=record[3] if len(record) > 3 else None,
        error=read_operation_error(record),
    )


def read_operation_error(record: list) -> Optional[str]:
    """Lời phàn nàn gắn theo operation này, nếu có.

    Nó nằm trong ô status của khối detail dạng
    ``[4, [null, "Media not found."], ["Media not found."]]``. Thực tế đo
    được: 1 operation có thể báo đúng cái này mà vẫn giao ra clip 8s hoàn
    chỉnh — nên đây chỉ là chuỗi chẩn đoán, không hơn.
    """
    detail = record[5] if len(record) > 5 else None
    if not isinstance(detail, list) or len(detail) <= 8:
        return None
    block = detail[8]
    if not isinstance(block, list) or not block or block[0] != OUTCOME_COMPLAINT:
        return None
    for text in _walk_strings(block):
        return text
    return "operation failed without a message"


def find_media_id(payload: Any, operation_id: str) -> Optional[str]:
    """Tra 1 operation trong listing của project và lấy media id của nó.

    Entry có dạng
    ``[opId, null, null, [title, created, null, null, mediaId, clientUuid, done], projectId]``.
    """
    for node in _walk_lists(payload):
        if len(node) < 4 or node[0] != operation_id:
            continue
        detail = node[3]
        if isinstance(detail, list) and len(detail) > 4 and isinstance(detail[4], str):
            return detail[4]
    return None


#: Ô media trong 1 dòng listing, khớp thẳng theo dữ liệu thô: tiêu đề, 1 cặp
#: timestamp, 2 null, rồi tới media id. Cả dạng escape lẫn không escape đều
#: xuất hiện tùy văn bản đã qua JSON decode hay chưa.
_MEDIA_SLOT = re.compile(r'null,null,\\?"([0-9a-fA-F-]{36})\\?"')


def find_media_id_in_text(text: str, operation_id: str) -> Optional[str]:
    """Tra cứu y hệt :func:`find_media_id`, nhưng trên listing chưa parse.

    Listing của project không có kích thước trang để giới hạn và lớn dần theo
    mỗi lần tạo, nên nó sẽ vượt bất kỳ giới hạn response nào đang đặt ra — và
    phần đuôi bị cắt cụt không decode JSON được dù entry cần tìm vẫn còn
    nguyên trong đó. Quét trực tiếp trên text vẫn tìm ra được.
    """
    start = text.find(operation_id)
    if start == -1:
        return None
    match = _MEDIA_SLOT.search(text, start, start + 800)
    return match.group(1) if match else None


def read_media_urls(payload: Any, media_id: str) -> MediaUrls:
    video = image = None
    for text in _walk_strings(payload):
        if not text.startswith("https://"):
            continue
        if MEDIA_HOST + "/video/" in text and video is None:
            video = text
        elif MEDIA_HOST + "/image/" in text and image is None:
            image = text
    return MediaUrls(media_id=media_id, video=video, image=image)
