"""
Lõi xử lý Hậu kỳ Tự động — Auto Voiceover & Subtitles cho Thìn Aptm.
Chuyển đổi thuyết minh tiếng Việt thành giọng đọc AI (edge-tts),
tính toán thời lượng, tạo phụ đề .srt và ghép nối hoàn chỉnh bằng FFmpeg.
"""

import os
import sys
import asyncio
import subprocess
import tempfile
import edge_tts


def get_audio_duration(file_path):
    """Sử dụng ffprobe để đo chính xác thời lượng (giây) của file audio."""
    cmd = [
        "ffprobe", "-v", "quiet", 
        "-show_entries", "format=duration", 
        "-of", "csv=p=0", file_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception as e:
        print(f"⚠️ Lỗi đo thời lượng audio {file_path}: {e}")
        return 5.0  # fallback


async def generate_voice_edge(text, output_file, voice="vi-VN-NamMinhNeural"):
    """Gọi edge-tts sinh file audio đọc tiếng Việt."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)


def make_voice_file(text, output_file, voice="vi-VN-NamMinhNeural", retries=3):
    """Wrapper đồng bộ để chạy async generate_voice_edge với cơ chế retry 3 lần khi lỗi mạng."""
    import time
    last_err = "Chưa thử"
    for attempt in range(1, retries + 1):
        try:
            asyncio.run(generate_voice_edge(text, output_file, voice))
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                return True, None
            else:
                last_err = "File audio trống."
        except Exception as e:
            last_err = str(e)
            print(f"⚠️ Thử lần {attempt}/{retries} sinh voice thất bại: {e}")
            if attempt < retries:
                time.sleep(2)  # chờ 2 giây trước khi thử lại
    return False, last_err


def seconds_to_srt_time(secs):
    """Format giây thành định dạng thời gian SRT: HH:MM:SS,mmm"""
    hours = int(secs // 3600)
    mins = int((secs % 3600) // 60)
    seconds = int(secs % 60)
    millis = int((secs - int(secs)) * 1000)
    return f"{hours:02d}:{mins:02d}:{seconds:02d},{millis:03d}"


def split_text_into_chunks(text, max_words=6):
    """Chia nhỏ một câu dài tiếng Việt thành các cụm từ ngắn tối đa max_words từ để sub không bị quá to/nhiều dòng."""
    # Thay thế các dấu câu để tách câu tự nhiên hơn
    text = text.replace(",", " , ").replace(".", " . ").replace("?", " ? ").replace("!", " ! ")
    words = text.split()
    if not words:
        return []
        
    chunks = []
    current_chunk = []
    
    for word in words:
        current_chunk.append(word)
        # Nếu đạt số lượng từ mong muốn hoặc gặp dấu chấm câu ngắt nghỉ
        if len(current_chunk) >= max_words or word in (",", ".", "?", "!"):
            chunk_str = " ".join(current_chunk)
            # Dọn dẹp dấu cách thừa trước dấu câu
            chunk_str = chunk_str.replace(" ,", ",").replace(" .", ".").replace(" ?", "?").replace(" !", "!")
            if chunk_str.strip():
                chunks.append(chunk_str.strip())
            current_chunk = []
            
    if current_chunk:
        chunk_str = " ".join(current_chunk)
        chunk_str = chunk_str.replace(" ,", ",").replace(" .", ".").replace(" ?", "?").replace(" !", "!")
        if chunk_str.strip():
            chunks.append(chunk_str.strip())
            
    return chunks


def create_srt(voice_texts, durations, srt_path):
    """Tự động sinh file phụ đề .srt khớp với thời lượng của từng cảnh, tự động chia nhỏ câu dài và highlight màu."""
    with open(srt_path, "w", encoding="utf-8") as f:
        current_time = 0.0
        sub_index = 1
        for text, dur in zip(voice_texts, durations):
            # Chia mỗi cụm 4-5 từ để hiện 1 dòng duy nhất trên màn hình
            chunks = split_text_into_chunks(text, max_words=5)
            if not chunks:
                # Nếu không có chữ, vẫn chuyển tiếp timeline
                current_time += dur
                continue
                
            chunk_dur = dur / len(chunks)
            for chunk in chunks:
                # Chuyển thành chữ IN HOA
                chunk_upper = chunk.upper()
                
                # Tạo hiệu ứng màu: chữ cuối màu trắng, các chữ trước màu vàng
                words = chunk_upper.split()
                if len(words) > 1:
                    yellow_count = len(words) - 1
                    yellow_part = " ".join(words[:yellow_count])
                    white_part = " ".join(words[yellow_count:])
                    # Font color trong SRT hỗ trợ các tag HTML
                    formatted_chunk = f'<font color="#FFFF00">{yellow_part}</font> {white_part}'
                else:
                    formatted_chunk = chunk_upper
                
                start = current_time
                end = current_time + chunk_dur
                f.write(f"{sub_index}\n")
                f.write(f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}\n")
                f.write(f"{formatted_chunk}\n\n")
                sub_index += 1
                current_time = end


def build_final_video(clips, voice_audios, voice_texts, output_path, bgm_path=None, bgm_volume=0.15, log_cb=None):
    """
    Tiến trình ghép nối nâng cao:
    1. Đo thời lượng từng file voice thuyết minh.
    2. Cắt âm thanh của clip gốc (mute 100%) và kéo dãn/co tốc độ video khớp với thời lượng voice thuyết minh.
    3. Ghép nối (concat) các clip và các file voice tương ứng.
    4. Sinh phụ đề chạy chữ chia đoạn ngắn và burn trực tiếp lên video ở sát đáy.
    5. Lồng nhạc nền (nếu có BGM).
    """
    if not log_cb:
        log_cb = print

    n = len(clips)
    log_cb(f"🎬 Bắt đầu dựng hậu kỳ tự động cho {n} phân cảnh...")

    # Đo thời lượng của từng file voiceover
    voice_durs = []
    for path in voice_audios:
        dur = get_audio_duration(path)
        voice_durs.append(dur)
    
    total_voice_dur = sum(voice_durs)
    log_cb(f"⏱️ Tổng thời lượng giọng nói AI: {total_voice_dur:.2f} giây.")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Bước 1: Điều chỉnh từng clip Veo khớp với thời lượng voiceover tương ứng
        adjusted_clips = []
        for i in range(n):
            clip = clips[i]
            voice_dur = voice_durs[i]
            adj_clip = os.path.join(tmpdir, f"clip_adj_{i}.mp4")
            
            # Lấy thời lượng gốc của clip Veo
            cmd_probe = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", clip]
            try:
                clip_dur = float(subprocess.run(cmd_probe, capture_output=True, text=True, check=True).stdout.strip())
            except Exception:
                clip_dur = 5.0  # mặc định Veo
            
            # Điều chỉnh tốc độ video (setpts) để khớp hoàn hảo thời lượng voiceover
            pts_ratio = voice_dur / clip_dur
            log_cb(f"   · Phân cảnh {i+1}: Video gốc {clip_dur:.1f}s → Voice {voice_dur:.1f}s (Ratio {pts_ratio:.2f}x)")
            
            # TẠO FILE CÂM TẠM THỜI (MUTE 100%) để triệt tiêu hoàn toàn âm thanh gốc của clip Veo
            silent_clip = os.path.join(tmpdir, f"silent_{i}.mp4")
            cmd_silent = ["ffmpeg", "-y", "-i", clip, "-an", "-c:v", "copy", silent_clip]
            try:
                subprocess.run(cmd_silent, capture_output=True, check=True)
            except Exception:
                # Nếu không thể strip âm thanh bằng copy, dùng luôn file gốc
                silent_clip = clip

            # Ghép video câm với voice thuyết minh edge-tts
            cmd_adj = [
                "ffmpeg", "-y",
                "-i", silent_clip,
                "-i", voice_audios[i],
                "-filter_complex", f"[0:v]setpts={pts_ratio:.4f}*PTS[v]",
                "-map", "[v]", "-map", "1:a",
                "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22",
                "-c:a", "aac", "-b:a", "128k",
                adj_clip
            ]
            try:
                subprocess.run(cmd_adj, capture_output=True, check=True)
            except subprocess.CalledProcessError:
                # Fallback sang CPU encode
                cmd_adj[cmd_adj.index("h264_nvenc")] = "libx264"
                cmd_adj[cmd_adj.index("p4")] = "medium"
                subprocess.run(cmd_adj, capture_output=True, check=True)
                
            adjusted_clips.append(adj_clip)

        # Bước 2: Tạo file concat list
        list_file = os.path.join(tmpdir, "concat_list.txt")
        with open(list_file, "w", encoding="utf-8") as f:
            for c in adjusted_clips:
                escaped = c.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        # Bước 3: Ghép nối các clip đã hiệu chỉnh thành 1 video tạm
        concat_video = os.path.join(tmpdir, "concat.mp4")
        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            concat_video
        ]
        log_cb("🔗 Đang ghép nối các phân cảnh...")
        subprocess.run(cmd_concat, capture_output=True, check=True)

        current_video = concat_video

        # Bước 4: Lồng nhạc nền (nếu có)
        if bgm_path and os.path.exists(bgm_path):
            bgm_video = os.path.join(tmpdir, "bgm.mp4")
            cmd_bgm = [
                "ffmpeg", "-y",
                "-i", current_video,
                "-i", bgm_path,
                "-filter_complex",
                f"[1:a]aloop=loop=-1:size=2e+09,volume={bgm_volume}[bgm];"
                f"[0:a][bgm]amix=inputs=2:duration=first[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                bgm_video
            ]
            log_cb(f"🎵 Đang lồng nhạc nền (Volume {bgm_volume})...")
            subprocess.run(cmd_bgm, capture_output=True, check=True)
            current_video = bgm_video

        # Bước 5: Sinh phụ đề .srt
        srt_path = os.path.join(tmpdir, "subtitle.srt")
        create_srt(voice_texts, voice_durs, srt_path)

        # Bước 6: Burn phụ đề lên video và xuất ra file final
        log_cb("📝 Đang tạo phụ đề vietsub...")
        # FontName=Impact (font chữ in dày giống mẫu), FontSize=13 (chữ nhỏ hơn 50%), PrimaryColour=White
        # MarginV=35 (đẩy chữ sát xuống dưới đáy hơn)
        style = (
            "FontName=Impact,FontSize=13,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=3,"
            "Shadow=0,Bold=1,Alignment=2,MarginV=35"
        )
        srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")
        cmd_sub = [
            "ffmpeg", "-y",
            "-i", current_video,
            "-vf", f"subtitles='{srt_escaped}':force_style='{style}'",
            "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22",
            "-c:a", "copy",
            output_path
        ]
        try:
            subprocess.run(cmd_sub, capture_output=True, check=True)
        except subprocess.CalledProcessError:
            # Fallback CPU encode
            cmd_sub[cmd_sub.index("h264_nvenc")] = "libx264"
            cmd_sub[cmd_sub.index("p4")] = "medium"
            subprocess.run(cmd_sub, capture_output=True, check=True)

    log_cb(f"✅ Hoàn thành hậu kỳ! File đầu ra: {output_path}")
    return True
