"""
SlideShow.py — Module tạo video slideshow từ ảnh sản phẩm.
Dựa trên logic ffmpeg từ VideoCreatorApp (tao_video.py).
Xuất: VOICES, create_slideshow(), _generate_ai_script(), và các constants.
"""

import os
import sys
import re
import json
import random
import subprocess
import tempfile
import time
import threading
import asyncio
import concurrent.futures
import shutil
import uuid

# ═══════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════

VOICES = {
    "Nam Minh (Nam)": "vi-VN-NamMinhNeural",
    "Hoài My (Nữ)": "vi-VN-HoaiMyNeural",
    "🇻🇳 HoaiMy (Nữ)": "vi-VN-HoaiMyNeural",
    "🇻🇳 NamMinh (Nam)": "vi-VN-NamMinhNeural",
    "Angelo (Male)": "fil-PH-AngeloNeural",
    "Blessica (Female)": "fil-PH-BlessicaNeural",
    "🇵🇭 Blessica (Nữ)": "fil-PH-BlessicaNeural",
    "🇵🇭 Angelo (Nam)": "fil-PH-AngeloNeural",
    "Guy (Male - US)": "en-US-GuyNeural",
    "Aria (Female - US)": "en-US-AriaNeural",
    "🇺🇸 Aria (Nữ)": "en-US-AriaNeural",
    "🇺🇸 Guy (Nam)": "en-US-GuyNeural",
    "Ardi (Male)": "id-ID-ArdiNeural",
    "Gadis (Female)": "id-ID-GadisNeural",
    "🇮🇩 Gadis (Nữ)": "id-ID-GadisNeural",
    "🇮🇩 Ardi (Nam)": "id-ID-ArdiNeural",
}

ASPECT_RATIOS = {"9:16 (Dọc)": (1080, 1920), "16:9 (Ngang)": (1920, 1080)}
EFFECTS = ["🎲 Random", "🔍 Zoom In", "🔎 Zoom Out", "⬅ Pan Left", "➡ Pan Right", "⬆ Pan Up", "⬇ Pan Down"]
FADE_DURATIONS = ["0.5s", "0.8s", "1.0s", "1.5s"]
FPS_OPTIONS = ["24", "30", "60"]
IMG_EXT = ('.jpg', '.jpeg', '.png', '.webp')
LANGUAGES = ["🇻🇳 Tiếng Việt", "🇵🇭 Tiếng Philippines", "🇺🇸 Tiếng Anh", "🇮🇩 Tiếng Indonesia"]

# ── Quản lý API Key (Phân loại: Hỏng Vĩnh Viễn vs Cooldown Tạm Thời) ──
BAD_API_KEYS = set()          # Key hỏng vĩnh viễn (401/403: Sai key hoặc bị khóa)
COOLDOWN_API_KEYS = {}        # Key nghẽn tạm thời (429 Rate Limit): {key: unblock_timestamp}
_BAD_KEYS_LOCK = threading.Lock()

def mark_bad_key(key: str):
    """Đánh dấu 1 API key hỏng vĩnh viễn (401/403)."""
    if key and isinstance(key, str):
        with _BAD_KEYS_LOCK:
            BAD_API_KEYS.add(key.strip())

def mark_cooldown_key(key: str, cooldown_seconds: int = 45):
    """Tạm thời tạm dừng key bị 429 Rate Limit trong cooldown_seconds giây (không xóa hẳn)."""
    if key and isinstance(key, str):
        with _BAD_KEYS_LOCK:
            COOLDOWN_API_KEYS[key.strip()] = time.time() + cooldown_seconds

def is_key_available(key: str) -> bool:
    """Kiểm tra key có sẵn sàng không (loại bỏ key hỏng và key đang cooldown)."""
    if not key or not isinstance(key, str):
        return False
    k = key.strip()
    with _BAD_KEYS_LOCK:
        if k in BAD_API_KEYS:
            return False
        if k in COOLDOWN_API_KEYS:
            if time.time() < COOLDOWN_API_KEYS[k]:
                return False  # Vẫn đang cooldown
            else:
                del COOLDOWN_API_KEYS[k]  # Hết cooldown -> Mở lại key!
        return True

def is_bad_key(key: str) -> bool:
    return not is_key_available(key)

def clear_bad_keys():
    """Reset danh sách key hỏng & cooldown khi khởi chạy job mới."""
    with _BAD_KEYS_LOCK:
        BAD_API_KEYS.clear()
        COOLDOWN_API_KEYS.clear()

TEMPLATE_STYLES = [
    "🎲 Random (Xoay Vòng Tất Cả Mẫu Demo)",
    "📷 Template 1: Camera Viewfinder (Khung Máy Ảnh DSLR)",
    "⚡ Template 2: Fast Beat Snap (Giật Beat Nhanh Năng Động)",
    "🛒 Template 3: Shopee App UI (Giao diện App Shopee)",
    "🏷️ Template 4: Product Specs Card (Thẻ Thông Số Sản Phẩm)",
    "📱 Template 5: Dynamic Mockup (Khung Thẻ Bo Tròn CapCut)",
    "🎬 Template 6: Shopee Video Classic (Mẫu Mặc Định + Kết Shopee)"
]

# Windows: ẩn cửa sổ console khi gọi subprocess
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# ═══════════════════════════════════════════════════════════
#  HELPER: chạy ffmpeg/ffprobe
# ═══════════════════════════════════════════════════════════

def _run_cmd(cmd, timeout=300):
    """Chạy subprocess ẩn cửa sổ, trả (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, creationflags=_CREATE_NO_WINDOW
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, b"", b"timeout"
    except FileNotFoundError:
        return -2, b"", b"command not found"


def _get_duration(path):
    """Lấy duration (giây) của file audio/video bằng ffprobe."""
    cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
           '-of', 'default=noprint_wrappers=1:nokey=1', path]
    rc, out, _ = _run_cmd(cmd, timeout=30)
    try:
        return float(out.strip())
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════
#  ZOOMPAN EFFECTS
# ═══════════════════════════════════════════════════════════

def _get_zoompan_vf(effect, duration_frames, width, height, is_first=False):
    """Tạo filter string zoompan cho ffmpeg. Ưu tiên hiệu ứng nảy/giật cho ảnh đầu tiên."""
    d = max(1, duration_frames)
    s = f"{width}x{height}"

    effects_map = {
        "shake_beat": f"zoompan=z='1.10+0.05*sin(2*PI*in/10)':d={d}:x='iw/2-(iw/zoom)/2+6*sin(in*2.5)':y='ih/2-(ih/zoom)/2+6*cos(in*2.5)':s={s}",
        "pulse_flash": f"zoompan=z='1.08+0.08*abs(sin(2*PI*in/10))':d={d}:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s={s}",
        "zoom_in": f"zoompan=z='min(zoom+0.0015,1.5)':d={d}:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s={s}",
        "zoom_out": f"zoompan=z='if(eq(in,0),1.5,max(zoom-0.0015,1))':d={d}:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':s={s}",
        "pan_left": f"zoompan=z=1.15:d={d}:x='(iw-iw/zoom)*(1-in/{d})':y='ih/2-(ih/zoom)/2':s={s}",
        "pan_right": f"zoompan=z=1.15:d={d}:x='(iw-iw/zoom)*(in/{d})':y='ih/2-(ih/zoom)/2':s={s}",
        "pan_up": f"zoompan=z=1.15:d={d}:x='iw/2-(iw/zoom)/2':y='(ih-ih/zoom)*(1-in/{d})':s={s}",
        "pan_down": f"zoompan=z=1.15:d={d}:x='iw/2-(iw/zoom)/2':y='(ih-ih/zoom)*(in/{d})':s={s}",
    }

    if is_first and effect == "random":
        # Ảnh đầu tiên ưu tiên 100% hiệu ứng giật nảy gây chú ý
        effect = random.choice(["shake_beat", "pulse_flash"])
    elif effect == "random" or effect not in effects_map:
        effect = random.choice(list(effects_map.keys()))

    return effects_map[effect]


# ═══════════════════════════════════════════════════════════
#  TTS: edge-tts
# ═══════════════════════════════════════════════════════════

def _generate_voice(text, voice_name, output_path, log_cb=None):
    """Tạo file audio TTS bằng edge-tts subprocess."""
    if not text or not text.strip():
        return False
    cmd = ['edge-tts', '--voice', voice_name, '--text', text.strip(), '--write-media', output_path]
    rc, _, err = _run_cmd(cmd, timeout=120)
    if rc != 0:
        if log_cb:
            log_cb(f"edge-tts lỗi (rc={rc}): {err.decode('utf-8', errors='replace')[:200]}")
        return False
    return os.path.exists(output_path) and os.path.getsize(output_path) > 0


# ═══════════════════════════════════════════════════════════
#  AI SCRIPT GENERATION
# ═══════════════════════════════════════════════════════════

def _generate_ai_script(
    item_id="",
    gemini_keys=None,
    accounts=None,
    num_images=5,
    duration=16,
    lang="vi",
    log_cb=None,
    groq_key="",
    voice_mode="ai",
):
    """Tạo kịch bản AI cho TTS voiceover. Hỗ trợ Groq."""

    product_name = str(item_id).strip()
    if not product_name:
        return None

    # Tạo prompt theo ngôn ngữ
    if lang in ("en", "English"):
        min_words = 45 if duration <= 15 else 60
        prompt = (
            f"Write a TTS voiceover script introducing the product '{product_name}'. "
            f"STRICT REQUIREMENTS: MINIMUM {min_words} words. "
            f"The script MUST be at least {min_words} words. "
            "Do NOT include any special characters like parentheses, brackets, asterisks, or hashtags. "
            "Do NOT include any action instructions, scene descriptions, annotations, or stage directions. "
            "Output ONLY the smooth, continuous read-aloud text for TTS — nothing else."
        )
    elif lang in ("fil", "Philippines"):
        min_words = 50 if duration <= 15 else 70
        prompt = (
            f"Write a TTS voiceover script in Filipino/Tagalog introducing the product '{product_name}'. "
            f"STRICT REQUIREMENTS: MINIMUM {min_words} words. "
            "Do NOT include any special characters. Output ONLY the read-aloud text for TTS."
        )
    elif lang in ("id", "Indonesia"):
        min_words = 50 if duration <= 15 else 70
        prompt = (
            f"Tulis skrip voiceover TTS dalam Bahasa Indonesia untuk memperkenalkan produk '{product_name}'. "
            f"MINIMUM {min_words} kata. Hanya keluarkan teks untuk dibaca TTS."
        )
    else:  # vi
        min_words = 50 if duration <= 15 else 70
        prompt = (
            f"Viết kịch bản đọc TTS giới thiệu sản phẩm '{product_name}'. "
            f"YÊU CẦU BẮT BUỘC: TỐI THIỂU {min_words} từ. "
            "Đọc liên tục, trôi chảy, không ngắt quãng. "
            "KHÔNG chứa ký tự đặc biệt như dấu ngoặc, dấu sao, dấu thăng. "
            "Chỉ xuất ra duy nhất nội dung lời đọc mượt mà để dùng cho TTS."
        )

    # ── Groq API ──
    if groq_key and voice_mode == "groq":
        # Hỗ trợ cả 1 key (str) hoặc nhiều key (list)
        if isinstance(groq_key, list):
            keys = [k.strip() for k in groq_key if k.strip()]
        else:
            keys = [k.strip() for k in str(groq_key).splitlines() if k.strip()]

        # Lọc bỏ các key đã bị đánh dấu hỏng từ trước
        valid_keys = [k for k in keys if not is_bad_key(k)]
        ignored_bad = len(keys) - len(valid_keys)
        if ignored_bad > 0 and log_cb:
            log_cb(f"ℹ️ Đã tự động loại bỏ {ignored_bad}/{len(keys)} Groq key bị hỏng/khóa từ các job trước")
        keys = valid_keys

        if not keys:
            if log_cb:
                log_cb("Không còn Groq API key khả dụng (tất cả đều bị khóa/lỗi)")
            return None

        random.shuffle(keys)

        from urllib.request import Request, urlopen
        import urllib.error
        import json as _json
        import time

        # Danh sách mô hình Groq ưu tiên theo hạn ngạch RPM (llama-3.1-8b-instant có quota 14,400 RPM cực lớn)
        groq_models = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "mixtral-8x7b-32768"]

        failed_count = 0
        for idx, key in enumerate(keys):
            key_success = False
            for model in groq_models:
                try:
                    payload = _json.dumps({
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.7
                    }).encode("utf-8")

                    req = Request(
                        "https://api.groq.com/openai/v1/chat/completions",
                        data=payload,
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        },
                        method="POST"
                    )

                    with urlopen(req, timeout=25) as resp:
                        data = _json.loads(resp.read().decode("utf-8"))
                        script = data["choices"][0]["message"]["content"]
                        script = script.replace('*', '').replace('#', '').strip()
                        if script:
                            if log_cb:
                                if failed_count > 0:
                                    log_cb(f"Groq OK (Key #{idx+1} [{model}], {len(script)} ký tự, đã thử {failed_count} key trước)")
                                else:
                                    log_cb(f"Groq OK [{model}] ({len(script)} ký tự)")
                            return script

                except urllib.error.HTTPError as http_err:
                    status_code = http_err.code
                    if status_code in (401, 403):
                        # Key hỏng vĩnh viễn (sai key, hết hạn, bị khóa account)
                        mark_bad_key(key)
                        break
                    elif status_code == 429:
                        # Bị Rate Limit tạm thời -> Cooldown 45 giây rồi tự mở lại
                        mark_cooldown_key(key, 45)
                        time.sleep(0.2)
                        continue
                    else:
                        continue
                except Exception:
                    continue

            failed_count += 1

        if log_cb:
            log_cb(f"Tất cả {len(keys)} Groq key thử nghiệm đều không thành công")
        return None

    # ── Gemini API (nếu có key) ──
    if gemini_keys:
        try:
            from google import genai
            
            # Lọc bỏ các key đã bị đánh dấu hỏng từ trước
            valid_keys = [k.strip() for k in gemini_keys if k.strip() and not is_bad_key(k)]
            ignored_bad = len(gemini_keys) - len(valid_keys)
            if ignored_bad > 0 and log_cb:
                log_cb(f"ℹ️ Đã tự động loại bỏ {ignored_bad}/{len(gemini_keys)} Gemini key bị hỏng/khóa từ các job trước")
            gemini_keys = valid_keys

            if not gemini_keys:
                if log_cb:
                    log_cb("Không còn Gemini API key khả dụng")
                return None

            random.shuffle(gemini_keys)
            failed_count = 0
            for idx, key in enumerate(gemini_keys):
                try:
                    client = genai.Client(api_key=key)
                    try:
                        response = client.models.generate_content(
                            model="gemini-2.0-flash", contents=prompt
                        )
                    except Exception:
                        response = client.models.generate_content(
                            model="gemini-1.5-flash", contents=prompt
                        )
                    script = response.text.replace('*', '').replace('#', '').strip()
                    if script:
                        if log_cb:
                            if failed_count > 0:
                                log_cb(f"Gemini OK (Key #{idx+1}, {len(script)} ký tự, đã bỏ qua {failed_count} key lỗi)")
                            else:
                                log_cb(f"Gemini OK ({len(script)} ký tự)")
                        return script
                except Exception as e_gem:
                    err_str = str(e_gem).lower()
                    if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
                        mark_cooldown_key(key, 45)
                    elif "401" in err_str or "403" in err_str or "invalid" in err_str or "api_key" in err_str:
                        mark_bad_key(key)
                    failed_count += 1
                    continue
            if log_cb:
                log_cb(f"Tất cả {len(gemini_keys)} Gemini key thử nghiệm đều lỗi (Đã đánh dấu blacklist)")
        except ImportError:
            if log_cb:
                log_cb("Không tìm thấy google-genai. Chạy: pip install google-genai")

    return None


# ═══════════════════════════════════════════════════════════
#  MAIN: create_slideshow
# ═══════════════════════════════════════════════════════════

def create_slideshow(
    images,
    output_path,
    duration_per_img=3.0,
    fps=30,
    width=1080,
    height=1920,
    effect="random",
    fade_duration=0.8,
    voice_text=None,
    voice_name="vi-VN-NamMinhNeural",
    bgm_path=None,
    bgm_volume=0.15,
    burn_sub=False,
    log_cb=None,
    cancel_event=None,
    target_duration=None,
    template_style="random"
):
    """
    Tạo video slideshow từ danh sách ảnh bằng ffmpeg.
    Returns: (success: bool, error_message: str)
    """

    def _log(msg):
        if log_cb:
            try:
                log_cb(str(msg))
            except Exception:
                pass

    def _cancelled():
        return cancel_event and cancel_event.is_set()

    if not images:
        return False, "Không có ảnh"

    out_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(out_dir, exist_ok=True)

    temp_files = []  # Track tất cả file tạm để cleanup

    try:
        # ── Quyết định Template Style thực tế (1..6) ──
        tpl_str = str(template_style)
        if "Template 1" in tpl_str or "Camera" in tpl_str:
            tpl_id = 1
        elif "Template 2" in tpl_str or "Fast Beat" in tpl_str:
            tpl_id = 2
        elif "Template 3" in tpl_str or "Shopee App" in tpl_str:
            tpl_id = 3
        elif "Template 4" in tpl_str or "Specs" in tpl_str:
            tpl_id = 4
        elif "Template 5" in tpl_str or "Dynamic" in tpl_str:
            tpl_id = 5
        elif "Template 6" in tpl_str or "Classic" in tpl_str:
            tpl_id = 6
        else:
            tpl_id = random.choice([1, 2, 3, 4, 5, 6])

        _log(f"🎬 Áp dụng Mẫu Template #{tpl_id} chuẩn demo cho video...")

        # ── 1. Tạo từng clip video cho mỗi ảnh ──
        job_uid = uuid.uuid4().hex[:8]
        temp_clips = []
        for i, img_path in enumerate(images):
            if _cancelled():
                return False, "Đã hủy"

            if not os.path.exists(img_path):
                _log(f"Ảnh không tồn tại: {img_path}")
                continue

            temp_mp4 = os.path.join(out_dir, f"_ss_temp_{i}_{job_uid}_{uuid.uuid4().hex[:4]}.mp4")
            temp_files.append(temp_mp4)

            eff_choice = "shake_beat" if (tpl_id == 2 and effect == "random") else effect
            duration_frames = max(1, int(fps * duration_per_img))
            zoompan_vf = _get_zoompan_vf(eff_choice, duration_frames, width, height, is_first=(i == 0))

            clean_title = ""
            if voice_text and isinstance(voice_text, str):
                raw_t = voice_text.strip().split('\n')[0][:45]
                # Loại bỏ TẤT CẢ ký tự đặc biệt gây lỗi FFmpeg drawtext trên Windows
                for ch in "'\"\\:;[]{}()%$#@!&|<>^~`":
                    raw_t = raw_t.replace(ch, "")
                clean_title = raw_t.strip()

            fg_w, fg_h = int(width * 0.85), int(height * 0.85)
            base_filter = (
                f"[0:v]split[bg][fg];"
                f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=25:10[blurred];"
                f"[fg]scale={fg_w}:{fg_h}:force_original_aspect_ratio=decrease[fg_scaled];"
                f"[blurred][fg_scaled]overlay=(W-w)/2:(H-h)/2,fps={fps},"
                f"{zoompan_vf}[vbase]"
            )

            # Phủ Lớp Đồ Họa Độc Quyền Theo Từng Mẫu Template (1..6)
            if tpl_id == 1 or (tpl_id == 6 and i == 0):
                # 📷 Template 1: Camera Viewfinder Mockup (REC / 60FPS / F2.3)
                if i == 0:
                    overlay_filter = (
                        f"[vbase]"
                        f"drawbox=x=30:y=30:w={width-60}:h={height-60}:color=red@0.8:t=3,"
                        f"drawtext=text='REC':fontcolor=red:fontsize=28:x={width-150}:y=50,"
                        f"drawtext=text='60FPS':fontcolor=white:fontsize=22:x=60:y={height-80},"
                        f"drawtext=text='F2.3 0dB 15.7V':fontcolor=white@0.8:fontsize=20:x={width-220}:y={height-80},"
                        f"format=yuv420p[v]"
                    )
                else:
                    overlay_filter = (
                        f"[vbase]"
                        f"drawtext=text='{clean_title}':fontcolor=black:fontsize=26:x=(w-text_w)/2:y=h-140:box=1:boxcolor=white@0.9:boxborderw=12,"
                        f"format=yuv420p[v]"
                    ) if clean_title else f"[vbase]format=yuv420p[v]"

            elif tpl_id == 3:
                # 🛒 Template 3: Giao diện Shopee App UI (Header Search Bar + Card)
                overlay_filter = (
                    f"[vbase]"
                    f"drawbox=x=100:y=25:w={width-200}:h=45:color=black@0.4:t=fill,"
                    f"drawtext=text='Q Search':fontcolor=white@0.8:fontsize=22:x={width//2-40}:y=35,"
                    f"drawtext=text='{clean_title}':fontcolor=black:fontsize=24:x=(w-text_w)/2:y=h-130:box=1:boxcolor=white@0.95:boxborderw=10,"
                    f"format=yuv420p[v]"
                ) if clean_title else f"[vbase]format=yuv420p[v]"

            elif tpl_id == 4:
                # 🏷️ Template 4: Product Specs Card (Viền Xanh Lá + Banner)
                overlay_filter = (
                    f"[vbase]"
                    f"drawbox=x=0:y=80:w={width}:h=6:color=0x00B159:t=fill,"
                    f"drawbox=x=0:y={height-80}:w={width}:h=6:color=0x00B159:t=fill,"
                    f"drawtext=text='{clean_title}':fontcolor=black:fontsize=26:x=(w-text_w)/2:y=h-140:box=1:boxcolor=white@0.9:boxborderw=12,"
                    f"format=yuv420p[v]"
                ) if clean_title else f"[vbase]format=yuv420p[v]"

            else:
                # ⚡ Template 2 & 5: Card Mockup Bo Tròn
                overlay_filter = (
                    f"[vbase]"
                    f"drawtext=text='{clean_title}':fontcolor=black:fontsize=26:x=(w-text_w)/2:y=h-140:box=1:boxcolor=white@0.9:boxborderw=12,"
                    f"format=yuv420p[v]"
                ) if clean_title else f"[vbase]format=yuv420p[v]"

            fc = f"{base_filter};{overlay_filter}"

            # Đặt giới hạn luồng cho mỗi tiến trình FFmpeg (2 luồng/process) để không ngốn 100% CPU
            ff_threads = '2'

            # Chuỗi ưu tiên Hardware Acceleration -> Fallback CPU libx264
            encoders_to_try = [
                # 1. NVIDIA GPU (NVENC)
                ['ffmpeg', '-y', '-threads', ff_threads, '-loop', '1', '-i', img_path,
                 '-t', str(duration_per_img), '-filter_complex', fc, '-map', '[v]',
                 '-c:v', 'h264_nvenc', '-pix_fmt', 'yuv420p', '-b:v', '4M', temp_mp4],
                # 2. Intel iGPU QuickSync (QSV)
                ['ffmpeg', '-y', '-threads', ff_threads, '-loop', '1', '-i', img_path,
                 '-t', str(duration_per_img), '-filter_complex', fc, '-map', '[v]',
                 '-c:v', 'h264_qsv', '-pix_fmt', 'nv12', '-b:v', '4M', temp_mp4],
                # 3. AMD APU/GPU (AMF)
                ['ffmpeg', '-y', '-threads', ff_threads, '-loop', '1', '-i', img_path,
                 '-t', str(duration_per_img), '-filter_complex', fc, '-map', '[v]',
                 '-c:v', 'h264_amf', '-pix_fmt', 'yuv420p', '-b:v', '4M', temp_mp4],
                # 4. CPU libx264 Tối Ưu Tốc Độ Max (2 luồng + superfast + tune stillimage)
                ['ffmpeg', '-y', '-threads', ff_threads, '-loop', '1', '-i', img_path,
                 '-t', str(duration_per_img), '-filter_complex', fc, '-map', '[v]',
                 '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                 '-preset', 'superfast', '-tune', 'stillimage', '-crf', '22',
                 temp_mp4]
            ]

            success = False
            last_err_msg = ""
            for cmd in encoders_to_try:
                rc, _, err = _run_cmd(cmd, timeout=120)
                if rc == 0 and os.path.exists(temp_mp4) and os.path.getsize(temp_mp4) > 0:
                    success = True
                    break
                last_err_msg = err.decode('utf-8', errors='replace')[-300:] if err else f"rc={rc}"

            # ── FALLBACK: Nếu lỗi Fontconfig (drawtext) → Retry KHÔNG có chữ ──
            if not success and 'fontconfig' in last_err_msg.lower():
                _log(f"⚠️ Fontconfig không có → Tạo clip #{i} không chữ (fallback)")
                fc_notext = f"{base_filter};[vbase]format=yuv420p[v]"
                fallback_encoders = [
                    ['ffmpeg', '-y', '-threads', ff_threads, '-loop', '1', '-i', img_path,
                     '-t', str(duration_per_img), '-filter_complex', fc_notext, '-map', '[v]',
                     '-c:v', 'h264_nvenc', '-pix_fmt', 'yuv420p', '-b:v', '4M', temp_mp4],
                    ['ffmpeg', '-y', '-threads', ff_threads, '-loop', '1', '-i', img_path,
                     '-t', str(duration_per_img), '-filter_complex', fc_notext, '-map', '[v]',
                     '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                     '-preset', 'superfast', '-tune', 'stillimage', '-crf', '22', temp_mp4]
                ]
                for cmd in fallback_encoders:
                    rc, _, err = _run_cmd(cmd, timeout=120)
                    if rc == 0 and os.path.exists(temp_mp4) and os.path.getsize(temp_mp4) > 0:
                        success = True
                        break

            if not success:
                _log(f"ffmpeg lỗi clip #{i}: {last_err_msg}")
                continue

            if os.path.exists(temp_mp4):
                temp_clips.append(temp_mp4)
                _log(f"Clip {i+1}/{len(images)} OK")

        if not temp_clips:
            return False, "Không tạo được clip nào"

        if _cancelled():
            return False, "Đã hủy"

        # ── 2. Ghép clip với hiệu ứng chuyển cảnh xfade (Transition Effects) ──
        temp_video = os.path.join(out_dir, f"_ss_video_{job_uid}.mp4")
        temp_files.append(temp_video)

        if len(temp_clips) == 1:
            shutil.copy(temp_clips[0], temp_video)
        else:
            # Danh sách hiệu ứng xfade phong phú hấp dẫn chuẩn Shopee Video / TikTok
            available_transitions = [
                "slideleft", "slideright", "slideup", "slidedown",
                "wiperight", "wipeleft", "wipeup", "wipedown",
                "circlecrop", "circleclose", "rectcrop",
                "fade", "fadeblack", "fadewhite", "zoomin"
            ]

            fade_dur = max(0.3, min(float(fade_duration), 1.0))
            inputs = []
            for clip in temp_clips:
                inputs.extend(['-i', clip])

            filter_parts = []
            current_v = "[0:v]"
            offset = duration_per_img - fade_dur

            for idx in range(1, len(temp_clips)):
                trans = random.choice(available_transitions)
                next_v = f"[v{idx}]" if idx < len(temp_clips) - 1 else "[vout]"
                filter_parts.append(
                    f"{current_v}[{idx}:v]xfade=transition={trans}:duration={fade_dur:.2f}:offset={offset:.2f}{next_v}"
                )
                current_v = next_v
                offset += (duration_per_img - fade_dur)

            fc_xfade = ";".join(filter_parts)

            concat_cmd = ['ffmpeg', '-y'] + inputs + [
                '-filter_complex', fc_xfade,
                '-map', '[vout]',
                '-c:v', 'libx264', '-preset', 'superfast', '-crf', '22',
                temp_video
            ]

            rc, _, err = _run_cmd(concat_cmd, timeout=300)
            if rc != 0:
                _log(f"xfade fallback concat copy: {err.decode('utf-8', errors='replace')[:100]}")
                concat_list = os.path.join(out_dir, f"_ss_concat_{job_uid}.txt")
                temp_files.append(concat_list)
                with open(concat_list, "w", encoding="utf-8") as f:
                    for clip in temp_clips:
                        safe_clip = clip.replace('\\', '/')
                        f.write(f"file '{safe_clip}'\n")
                _run_cmd(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list, '-c:v', 'copy', temp_video], timeout=300)

        _log("Ghép clip & hiệu ứng chuyển cảnh xfade OK")

        if _cancelled():
            return False, "Đã hủy"

        # ── 3. TTS Voice (nếu có) ──
        tts_audio = None
        if voice_text and voice_text.strip():
            tts_audio = os.path.join(out_dir, f"_ss_tts_{job_uid}.mp3")
            temp_files.append(tts_audio)
            _log("Đang tạo TTS...")
            if not _generate_voice(voice_text, voice_name, tts_audio, log_cb=_log):
                _log("❌ Tạo TTS Voiceover thất bại — Hủy tạo video để nhả SP về DB!")
                return False, "Tạo TTS Voiceover thất bại"

        # ── 4. Mix audio: TTS + BGM ──
        has_audio = tts_audio or bgm_path
        if has_audio:
            _log("Đang mix audio...")
            audio_inputs = []
            filter_parts = []
            input_idx = 1  # index 0 = video

            mix_cmd = ['ffmpeg', '-y', '-i', temp_video]

            if tts_audio and os.path.exists(tts_audio):
                mix_cmd.extend(['-i', tts_audio])
                filter_parts.append(f"[{input_idx}:a]aformat=fltp:44100:stereo[tts]")
                audio_inputs.append("[tts]")
                input_idx += 1

            if bgm_path and os.path.exists(bgm_path):
                mix_cmd.extend(['-i', bgm_path])
                vol = max(0.0, min(1.0, float(bgm_volume)))
                filter_parts.append(f"[{input_idx}:a]aformat=fltp:44100:stereo,volume={vol}[bgm]")
                audio_inputs.append("[bgm]")
                input_idx += 1

            if len(audio_inputs) > 1:
                filter_parts.append(f"{''.join(audio_inputs)}amix=inputs={len(audio_inputs)}:duration=longest[aout]")
                audio_filter = ";".join(filter_parts)
                mix_cmd.extend(['-filter_complex', audio_filter, '-map', '0:v', '-map', '[aout]'])
            elif len(audio_inputs) == 1:
                label = audio_inputs[0]
                audio_filter = ";".join(filter_parts)
                mix_cmd.extend(['-filter_complex', audio_filter, '-map', '0:v', '-map', label])
            else:
                # No audio
                shutil.copy2(temp_video, output_path)
                _log("Hoàn tất (không có audio)")
                return True, ""

            # Lấy duration video
            vid_dur = _get_duration(temp_video)
            if target_duration and float(target_duration) > 0:
                mix_dur = float(target_duration)
            else:
                mix_dur = vid_dur

            if mix_dur > 0:
                mix_cmd.extend(['-t', str(mix_dur)])

            mix_cmd.extend([
                '-c:v', 'copy',
                '-c:a', 'aac', '-b:a', '192k',
                '-shortest',
                output_path
            ])

            rc, _, err = _run_cmd(mix_cmd, timeout=300)
            if rc != 0:
                # Fallback: copy video không audio
                _log(f"Mix audio lỗi, lưu video không audio")
                shutil.copy2(temp_video, output_path)
        else:
            # Không có audio → copy/trim video
            if target_duration and float(target_duration) > 0:
                trim_cmd = ['ffmpeg', '-y', '-i', temp_video, '-t', str(target_duration), '-c', 'copy', output_path]
                rc_t, _, _ = _run_cmd(trim_cmd, timeout=120)
                if rc_t != 0 or not os.path.exists(output_path):
                    shutil.copy2(temp_video, output_path)
            else:
                shutil.copy2(temp_video, output_path)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            _log("Hoàn tất!")
            return True, ""
        else:
            return False, "File output không tồn tại hoặc rỗng"

    except Exception as e:
        return False, str(e)

    finally:
        # ── Cleanup tất cả file tạm ──
        for f in temp_files:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════
#  STUBS (tương thích với .pyc cũ)
# ═══════════════════════════════════════════════════════════

def build_tab(parent=None):
    """Stub — GUI tab builder (không cần trong chế độ headless)."""
    return None

def scan_images(directory):
    """Quét thư mục tìm file ảnh."""
    if not directory or not os.path.isdir(directory):
        return []
    result = []
    for f in os.listdir(directory):
        if f.lower().endswith(IMG_EXT):
            result.append(os.path.join(directory, f))
    return sorted(result)

def fetch_gsheet_data(*args, **kwargs):
    """Stub — đọc dữ liệu từ Google Sheet."""
    return []

def load_json_data(path=None):
    """Stub — đọc dữ liệu từ JSON file."""
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def update_gsheet_status(*args, **kwargs):
    """Stub — cập nhật trạng thái lên Google Sheet."""
    pass
