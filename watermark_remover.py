"""
watermark_remover.py — Module tự động xóa logo / watermark của Google Veo & Omni Flash.
Lấy cảm hứng từ thuật toán xử lý của TstGoogleFlow v1.0.6.

Các tính năng:
- Xóa watermark Video:
  1. Chế độ "crop" (mặc định): Cắt bỏ viền chứa logo và scale lại kích thước gốc bằng bộ lọc Lanczos,
     giữ nguyên 100% chất lượng âm thanh và tỷ lệ khung hình.
  2. Chế độ "delogo": Sử dụng FFmpeg filter delogo vào vùng tọa độ watermark chuẩn của Veo 3.1 & Omni Flash.
- Xóa watermark Ảnh:
  - Tự động phát hiện vị trí logo ở góc dưới phải và áp dụng thuật toán OpenCV Inpainting (Telea)
    để tái tạo điểm ảnh bị che khuất một cách mượt mà.
"""

import os
import sys
import subprocess
import shutil

def _get_ffmpeg():
    """Tìm đường dẫn thực thi của ffmpeg."""
    candidates = [
        "ffmpeg",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe"),
    ]
    for c in candidates:
        if shutil.which(c) or (os.path.isfile(c) and os.access(c, os.X_OK)):
            return c
    return "ffmpeg"


def _get_ffprobe():
    """Tìm đường dẫn thực thi của ffprobe."""
    candidates = [
        "ffprobe",
        r"C:\ffmpeg\bin\ffprobe.exe",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffprobe.exe"),
    ]
    for c in candidates:
        if shutil.which(c) or (os.path.isfile(c) and os.access(c, os.X_OK)):
            return c
    return "ffprobe"


def get_video_dimensions(video_path):
    """Lấy (width, height) của video bằng ffprobe hoặc cv2."""
    ffprobe = _get_ffprobe()
    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        video_path
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        if proc.returncode == 0 and "x" in proc.stdout.strip():
            w_str, h_str = proc.stdout.strip().split("x")[:2]
            w, h = int(w_str), int(h_str)
            return w, h
    except Exception:
        pass

    # Fallback OpenCV
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass

    return 720, 1280  # Mặc định dọc 9:16


def remove_watermark_video(video_path, output_path=None, mode="crop", model="veo_3_1", log_fn=None):
    """
    Xóa watermark khỏi video.
    :param video_path: Đường dẫn file video .mp4 gốc.
    :param output_path: Đường dẫn file xuất ra (nếu None, ghi đè trực tiếp lên video_path).
    :param mode: 'crop' (cắt viền + phóng to Lanczos) hoặc 'delogo' (FFmpeg delogo filter).
    :param model: 'veo_3_1' hoặc 'abra'/'omni'.
    :param log_fn: Hàm callback ghi log (nhận chuỗi thông báo).
    :return: (True, message) nếu thành công, (False, error_message) nếu thất bại.
    """
    if not os.path.isfile(video_path):
        return False, f"Không tìm thấy file: {video_path}"

    ffmpeg = _get_ffmpeg()
    target_out = output_path or video_path
    temp_out = video_path + ".logotmp.mp4"

    try:
        w, h = get_video_dimensions(video_path)
        if w <= 0 or h <= 0:
            return False, "Không xác định được kích thước video."

        is_omni = "abra" in str(model).lower() or "omni" in str(model).lower()

        if mode == "delogo":
            # Chế độ delogo
            if is_omni:
                # Omni Flash watermark nhỏ hơn ở góc dưới phải
                logo_w, logo_h = 32, 22
                logo_x = max(1, w - 44)
                logo_y = max(1, h - 32)
            else:
                # Veo 3.1 watermark chuẩn
                logo_w, logo_h = 60, 60
                logo_x = max(1, w - 150)
                logo_y = max(1, h - 150)

            vf = f"delogo=x={logo_x}:y={logo_y}:w={logo_w}:h={logo_h}"
            msg_mode = f"delogo ({logo_w}x{logo_h} @ {logo_x},{logo_y})"
        else:
            # Chế độ crop & scale (Lanczos)
            if is_omni:
                bottom_margin = 24
            else:
                bottom_margin = 48

            crop_h = h - bottom_margin
            crop_h -= (crop_h & 1)  # Chẵn số pixel
            # Giữ nguyên tỷ lệ khung hình
            margin_x = int(round(w * bottom_margin / h / 2.0))
            crop_w = w - (2 * margin_x)
            crop_w -= (crop_w & 1)
            crop_x = (w - crop_w) // 2

            vf = f"crop={crop_w}:{crop_h}:{crop_x}:0,scale={w}:{h}:flags=lanczos,setsar=1"
            msg_mode = f"crop ({crop_w}x{crop_h} -> {w}x{h})"

        if log_fn:
            log_fn(f"🧽 [Watermark] Xóa logo video ({msg_mode})...")

        # Command FFmpeg
        # Tôn trọng Rule 9.5: -threads 2 chống lag máy
        cmd = [
            ffmpeg,
            "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-threads", "2",
            "-i", video_path,
            "-vf", vf,
            "-map", "0:v:0",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart"
        ]

        # Giữ audio nếu có
        cmd.extend(["-map", "0:a?", "-c:a", "copy"])
        cmd.append(temp_out)

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))

        if proc.returncode != 0:
            err = proc.stderr.strip() or f"FFmpeg exit code {proc.returncode}"
            if os.path.exists(temp_out):
                os.remove(temp_out)
            return False, f"FFmpeg lỗi: {err}"

        if not os.path.exists(temp_out) or os.path.getsize(temp_out) < 1000:
            if os.path.exists(temp_out):
                os.remove(temp_out)
            return False, "FFmpeg không tạo ra video hợp lệ."

        # Di chuyển đè vào file đích
        shutil.move(temp_out, target_out)
        return True, f"Xóa logo thành công ({msg_mode})"

    except subprocess.TimeoutExpired:
        if os.path.exists(temp_out):
            try: os.remove(temp_out)
            except: pass
        return False, "Quá thời gian xử lý FFmpeg (Timeout)."
    except Exception as e:
        if os.path.exists(temp_out):
            try: os.remove(temp_out)
            except: pass
        return False, f"Lỗi xóa logo: {e}"


def remove_watermark_image(image_path, output_path=None, model="veo_3_1", log_fn=None):
    """
    Xóa watermark khỏi file ảnh bằng OpenCV Inpainting.
    :param image_path: Đường dẫn ảnh gốc (.png/.jpg).
    :param output_path: Đường dẫn file xuất ra (nếu None, ghi đè trực tiếp).
    :param model: 'veo_3_1' hoặc 'abra'/'omni'.
    :param log_fn: Hàm callback ghi log.
    :return: (True, message) nếu thành công, (False, error_message) nếu thất bại.
    """
    if not os.path.isfile(image_path):
        return False, f"Không tìm thấy file: {image_path}"

    try:
        import cv2
        import numpy as np
    except ImportError:
        return False, "Thiếu thư viện OpenCV (cv2) để xóa watermark ảnh."

    target_out = output_path or image_path
    try:
        img = cv2.imread(image_path)
        if img is None:
            return False, "Không decode được ảnh."

        h, w = img.shape[:2]
        is_omni = "abra" in str(model).lower() or "omni" in str(model).lower()

        if is_omni:
            logo_w, logo_h = 36, 26
            logo_x = max(0, w - 46)
            logo_y = max(0, h - 36)
        else:
            logo_w, logo_h = 55, 55
            logo_x = max(0, w - 125)
            logo_y = max(0, h - 125)

        # Tạo mask màu đen, vùng logo màu trắng
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[logo_y:min(h, logo_y + logo_h), logo_x:min(w, logo_x + logo_w)] = 255

        if log_fn:
            log_fn(f"🧽 [Watermark] Inpainting xóa logo ảnh ({logo_w}x{logo_h} @ {logo_x},{logo_y})...")

        # Áp dụng thuật toán Inpainting Telea
        restored = cv2.inpaint(img, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)

        # Ghi đè an toàn
        temp_out = image_path + ".logotmp.png"
        cv2.imwrite(temp_out, restored)
        if os.path.exists(temp_out) and os.path.getsize(temp_out) > 0:
            shutil.move(temp_out, target_out)
            return True, "Xóa logo ảnh thành công"
        else:
            return False, "Ghi file ảnh thất bại."

    except Exception as e:
        return False, f"Lỗi xóa logo ảnh: {e}"
