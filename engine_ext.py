"""Chế độ Extension cho pipeline Server-Video — thay thế REST/Bearer bằng
batchexecute RPC chạy trong tab flow.google.com thật (qua flow_bridge.py).

Mỗi hàm ở đây map kết quả RPC thật về ĐÚNG bộ trạng thái mà process_one()
trong thin_aptm.py đã quen xử lý cho engine.py (REST) — để chỉ cần rẽ nhánh ở
đầu mỗi lời gọi, không phải viết lại logic retry/circuit-breaker xung quanh.
Vài chỗ map là XẤP XỈ ngữ nghĩa gần nhất, không phải khớp 1-1 hoàn hảo — ghi
rõ trong docstring từng hàm để không ai tưởng nhầm là chính xác tuyệt đối.

KHÔNG map lỗi mất-kết-nối-bridge thành "auth" hay "proxy_dead": ở chế độ này
không có bearer token để mà sai, và không có proxy nào liên quan — mất tab là
sự cố hạ tầng tạm thời (tab đóng, extension chưa kết nối kịp), không phải
bằng chứng tài khoản chết. Việc "tài khoản có đang sẵn sàng hay không" nằm ở
AccountState.ensure_auth_ext() (thin_aptm.py), không phải ở đây.
"""
from __future__ import annotations

import base64
import os
from typing import Optional

import flow_batch as fb
import flow_bridge
import engine as E  # tái dùng download_url() + POLICY_TOKENS/is_policy_reason đã có, không viết lại


def _rpc(email: str, rpcid: str, freq: str, captcha_action: Optional[str] = None,
         match: Optional[str] = None, timeout: float = 120) -> dict:
    """Gọi 1 RPC qua bridge, trả nguyên {"status":.., "data":..} hoặc {"error":..}."""
    params = {"rpcid": rpcid, "freq": freq}
    if captcha_action:
        params["captchaAction"] = captcha_action
    if match:
        params["match"] = match
    return flow_bridge.call(email, "batch_rpc", params, timeout=timeout)


def _payload_or_none(result: dict, rpcid: str):
    """Bóc payload từ kết quả _rpc(); trả (payload, None) hoặc (None, error_text)."""
    if result.get("error"):
        return None, str(result["error"])
    data = result.get("data") or ""
    try:
        return fb.first_payload(data, rpcid), None
    except (fb.RpcError, fb.FlowBatchError) as e:
        return None, str(e)


def upload_image_ext(email: str, project: str, image_path: str,
                      proxy=None, cookie=None, timeout: float = 120):
    """Upload ảnh qua RPC maseQ. Trả về media_id (str) hoặc sentinel:
    "throttle" | "forbidden" | "vi phạm cs" | "net_fail" | None.

    Map xấp xỉ (ghi rõ vì không khớp 1-1 với vốn từ REST cũ):
    - mất kết nối bridge / timeout -> "net_fail" (retry mềm, không phải lỗi tài khoản)
    - UNUSUAL_ACTIVITY / không mint được captcha -> "throttle" (tín hiệu rate/fraud của Google)
    """
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None
    mime = "image/png" if str(image_path).lower().endswith(".png") else "image/jpeg"
    fname = os.path.basename(image_path)
    freq = fb.upload_request(b64, project, mime_type=mime, file_name=fname)

    result = _rpc(email, fb.RPC_UPLOAD_IMAGE, freq, captcha_action=fb.CAPTCHA_IMAGE, timeout=timeout)
    if result.get("error") in ("account_not_connected", "bridge_timeout", "bridge_not_started"):
        return "net_fail"
    payload, err = _payload_or_none(result, fb.RPC_UPLOAD_IMAGE)
    if err:
        up = err.upper()
        if "UNUSUAL_ACTIVITY" in up or "CAPTCHA_FAILED" in up or "NO_AT_TOKEN" in up:
            return "throttle"
        if E.is_policy_reason(err):
            return "vi phạm cs"
        if "403" in up or "FORBIDDEN" in up:
            return "forbidden"
        return None
    try:
        return fb.read_uploaded_media_id(payload)
    except fb.FlowBatchError:
        return None


def submit_video_ext(email: str, project: str, prompt: str, seed, aspect, model: str,
                      ref_media_id: Optional[str] = None, timeout: float = 120):
    """Submit video qua RPC eb1hJf. Trả về (status, ops) — ops là [operation_id]
    (giữ nguyên dạng list để tương thích chỗ gọi hiện có đang đọc ops[0]).

    status ∈ {"ok","unusual","throttle","quota_hard","vi phạm cs","MODEL_ACCESS_DENIED","failed","retry_soft"}.
    KHÔNG có "auth" — chế độ này không có bearer để mà hết hạn.
    """
    if not ref_media_id:
        return "failed", None
    try:
        wire_model = fb.resolve_video_model(model)
        wire_aspect = fb.resolve_video_aspect(aspect)
        freq = fb.video_request(prompt, project, ref_media_id, aspect=wire_aspect, model=wire_model)
    except ValueError:
        return "failed", None

    result = _rpc(email, fb.RPC_GEN_VIDEO, freq, captcha_action=fb.CAPTCHA_VIDEO, timeout=timeout)
    if result.get("error") in ("account_not_connected", "bridge_timeout", "bridge_not_started"):
        return "retry_soft", None
    payload, err = _payload_or_none(result, fb.RPC_GEN_VIDEO)
    if err:
        up = err.upper()
        if "UNUSUAL_ACTIVITY" in up:
            return "unusual", None
        if "QUOTA_REACHED" in up or "QUOTA" in up:
            return "quota_hard", None
        if E.is_policy_reason(err, include_audio=True):
            return "vi phạm cs", None
        if "MODEL_ACCESS_DENIED" in up:
            return "MODEL_ACCESS_DENIED", None
        if "CAPTCHA_FAILED" in up or "NO_AT_TOKEN" in up:
            return "retry_soft", None
        return "failed", None
    try:
        operation = fb.read_operation(payload)
        return "ok", [operation.operation_id]
    except fb.FlowBatchError:
        return "failed", None


def poll_video_ext(email: str, project: str, ops, max_attempts: int = 60,
                    interval: float = 8.0, timeout: float = 60):
    """Poll qua RPC jwpduf (+ Zzl0ze mỗi 3 vòng để tra media_id trong listing,
    + as29s khi đã có media_id để lấy URL video). Trả về (status, result, credits)
    khớp dạng poll_video() hiện có: status ∈ {"done","failed"}, result = media_id
    (khi done) hoặc lý do thất bại (str).

    Lỗi bridge giữa chừng KHÔNG trả ngay cho caller — tự lặp lại trong vòng poll
    (coi như 1 lượt poll trống), chỉ "failed" khi hết hẳn max_attempts. Không map
    "proxy_dead" vì không có proxy nào liên quan ở chế độ này.
    """
    import time as _time
    if not ops:
        return "failed", "no_operation", None
    operation_id = ops[0]
    media_id = None
    complaint = None

    for attempt in range(1, max_attempts + 1):
        if not media_id:
            op_result = _rpc(email, fb.RPC_OPERATION, fb.operation_request(operation_id), timeout=timeout)
            payload, err = _payload_or_none(op_result, fb.RPC_OPERATION)
            if not err:
                try:
                    operation = fb.read_operation(payload)
                    complaint = operation.error
                    worth_listing = (attempt % 3 == 0) or operation.done or operation.complained
                except fb.FlowBatchError:
                    worth_listing = True
            else:
                worth_listing = True

            if worth_listing:
                listing = _rpc(email, fb.RPC_PROJECT_MEDIA,
                                fb.project_media_request(project),
                                match=operation_id, timeout=timeout)
                if not listing.get("error"):
                    raw = listing.get("data") or ""
                    media_id = fb.find_media_id_in_text(raw, operation_id)

        if media_id:
            media_result = _rpc(email, fb.RPC_MEDIA, fb.media_request(media_id), timeout=timeout)
            payload, err = _payload_or_none(media_result, fb.RPC_MEDIA)
            if not err:
                urls = fb.read_media_urls(payload, media_id)
                if urls.video:
                    return "done", media_id, None
                # có media_id nhưng clip chưa ghi xong -> chỉ là poster ảnh, chưa tải được

        _time.sleep(interval)

    return "failed", (complaint or "timeout"), None


def download_video_ext(media_id: str, email: str, dst: str, proxy=None,
                        cookie=None, timeout: float = 180):
    """Tải video: thay hẳn boq_execute("Iyc41d") đã chết 401 — gọi RPC as29s lấy
    URL CDN ký sẵn ngay trong response (không cần bước "resolve URL" riêng), rồi
    tái dùng thẳng engine.download_url() (đã có sẵn kiểm tra magic-byte MP4).

    Trả về int (bytes đã ghi) hoặc 0 / E.DL_NET_FAIL — không dùng E.DL_PROXY_DEAD
    vì không có proxy nào liên quan tới bước lấy URL này.
    """
    result = _rpc(email, fb.RPC_MEDIA, fb.media_request(media_id), timeout=60)
    if result.get("error") in ("account_not_connected", "bridge_timeout", "bridge_not_started"):
        return E.DL_NET_FAIL
    payload, err = _payload_or_none(result, fb.RPC_MEDIA)
    if err or not payload:
        return E.DL_NET_FAIL
    urls = fb.read_media_urls(payload, media_id)
    if not urls.video:
        return 0
    return E.download_url(urls.video, dst, timeout=timeout, proxy=proxy)


def generate_image_ext(email: str, project: str, prompt: str, seed: Optional[int] = None,
                       aspect: Any = 1, model: str = "GEM_PIX_2",
                       ref_media_ids: Optional[list[str]] = None, timeout: float = 120):
    """Generate ảnh qua RPC ogiZ0b. Trả về (status, result_dict) tương tự engine.generate_image()."""
    try:
        wire_model = fb.resolve_image_model(model)
        freq = fb.image_request(prompt, project, count=1, aspect=aspect, seed=seed,
                                model=wire_model, ref_media_ids=ref_media_ids)
    except Exception:
        return "failed", None

    result = _rpc(email, fb.RPC_GEN_IMAGE, freq, captcha_action=fb.CAPTCHA_IMAGE, timeout=timeout)
    if result.get("error") in ("account_not_connected", "bridge_timeout", "bridge_not_started"):
        return "retry_soft", None
    payload, err = _payload_or_none(result, fb.RPC_GEN_IMAGE)
    if err:
        up = err.upper()
        if "UNUSUAL_ACTIVITY" in up or "CAPTCHA_FAILED" in up or "NO_AT_TOKEN" in up:
            return "throttle", None
        if "QUOTA_REACHED" in up or "QUOTA" in up:
            return "quota_hard", None
        if E.is_policy_reason(err):
            return "vi phạm cs", None
        return "failed", None
    try:
        imgs = fb.read_images(payload)
        if imgs:
            return "ok", {"fife": imgs[0].url, "name": imgs[0].media_id, "b64": None}
        return "failed", None
    except fb.FlowBatchError:
        return "failed", None

