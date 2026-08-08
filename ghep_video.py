"""
Ghép Video Clips — Script hỗ trợ ghép các clip Veo thành video hoàn chỉnh.
Sử dụng: python ghep_video.py <thư_mục_clip> [output.mp4]

Tính năng:
- Ghép nhiều clip .mp4 theo thứ tự tên file
- Thêm transition fade giữa các clip (tùy chọn)
- Thêm file nhạc nền (tùy chọn)
- Thêm phụ đề từ file .srt (tùy chọn)
"""

import os
import sys
import subprocess
import glob
import argparse
import tempfile


def find_clips(folder, pattern="*.mp4"):
    """Tìm tất cả clip trong thư mục, sắp xếp theo tên."""
    clips = sorted(glob.glob(os.path.join(folder, pattern)))
    if not clips:
        print(f"❌ Không tìm thấy file {pattern} trong: {folder}")
        sys.exit(1)
    print(f"📂 Tìm thấy {len(clips)} clip:")
    for i, c in enumerate(clips, 1):
        print(f"   {i}. {os.path.basename(c)}")
    return clips


def create_concat_list(clips, temp_dir):
    """Tạo file danh sách cho FFmpeg concat."""
    list_file = os.path.join(temp_dir, "concat_list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for clip in clips:
            # Escape đường dẫn cho FFmpeg
            escaped = clip.replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
    return list_file


def concat_simple(clips, output, temp_dir):
    """Ghép đơn giản không transition (nhanh, không re-encode)."""
    list_file = create_concat_list(clips, temp_dir)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        output
    ]
    print(f"\n🔧 Ghép {len(clips)} clip (không re-encode)...")
    subprocess.run(cmd, check=True)
    print(f"✅ Xong: {output}")


def concat_with_fade(clips, output, fade_duration=0.5):
    """Ghép với hiệu ứng fade transition giữa các clip (re-encode)."""
    if len(clips) == 1:
        # Chỉ 1 clip, copy thẳng
        subprocess.run(["ffmpeg", "-y", "-i", clips[0], "-c", "copy", output], check=True)
        print(f"✅ Xong: {output}")
        return

    # Lấy duration từng clip
    durations = []
    for clip in clips:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", clip],
            capture_output=True, text=True
        )
        durations.append(float(result.stdout.strip()))

    # Xây dựng filter phức tạp cho xfade
    fd = fade_duration
    inputs = []
    for clip in clips:
        inputs.extend(["-i", clip])

    # Tạo filter_complex cho video xfade
    n = len(clips)
    filter_parts = []
    
    if n == 2:
        offset = durations[0] - fd
        filter_parts.append(f"[0:v][1:v]xfade=transition=fade:duration={fd}:offset={offset}[vout]")
        # Audio crossfade
        filter_parts.append(f"[0:a][1:a]acrossfade=d={fd}[aout]")
        map_v, map_a = "[vout]", "[aout]"
    else:
        # Chain xfade cho nhiều clip
        prev_v = "0:v"
        prev_a = "0:a"
        cumulative_offset = 0
        
        for i in range(1, n):
            offset = cumulative_offset + durations[i-1] - fd * i
            if i < n - 1:
                out_v = f"v{i}"
                out_a = f"a{i}"
            else:
                out_v = "vout"
                out_a = "aout"
            
            filter_parts.append(
                f"[{prev_v}][{i}:v]xfade=transition=fade:duration={fd}:offset={offset:.3f}[{out_v}]"
            )
            filter_parts.append(
                f"[{prev_a}][{i}:a]acrossfade=d={fd}[{out_a}]"
            )
            prev_v = out_v
            prev_a = out_a
            cumulative_offset = offset

        map_v, map_a = "[vout]", "[aout]"

    filter_complex = ";".join(filter_parts)
    
    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", map_v, "-map", map_a,
        "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20",
        "-c:a", "aac", "-b:a", "128k",
        output
    ]
    
    print(f"\n🔧 Ghép {len(clips)} clip với fade transition ({fd}s)...")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        # Fallback: dùng libx264 nếu không có NVIDIA GPU
        cmd[cmd.index("h264_nvenc")] = "libx264"
        cmd[cmd.index("p4")] = "medium"
        subprocess.run(cmd, check=True)
    
    print(f"✅ Xong: {output}")


def add_bgm(video_path, music_path, output, music_volume=0.15):
    """Thêm nhạc nền vào video, giữ audio gốc."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex",
        f"[1:a]aloop=loop=-1:size=2e+09,volume={music_volume}[bgm];"
        f"[0:a][bgm]amix=inputs=2:duration=first[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output
    ]
    print(f"\n🎵 Thêm nhạc nền: {os.path.basename(music_path)} (volume: {music_volume})...")
    subprocess.run(cmd, check=True)
    print(f"✅ Xong: {output}")


def burn_subtitles(video_path, srt_path, output):
    """Burn phụ đề .srt vào video (bold, yellow, bottom)."""
    style = (
        "FontName=Arial,FontSize=22,PrimaryColour=&H0000FFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2,"
        "Shadow=1,Bold=1,Alignment=2,MarginV=40"
    )
    srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"subtitles='{srt_escaped}':force_style='{style}'",
        "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20",
        "-c:a", "copy",
        output
    ]
    print(f"\n📝 Burn phụ đề: {os.path.basename(srt_path)}...")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        # Fallback CPU encoder
        cmd[cmd.index("h264_nvenc")] = "libx264"
        cmd[cmd.index("p4")] = "medium"
        subprocess.run(cmd, check=True)
    print(f"✅ Xong: {output}")


def main():
    parser = argparse.ArgumentParser(
        description="Ghép các clip Veo thành video hoàn chỉnh",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ sử dụng:
  python ghep_video.py D:\\output\\clips
  python ghep_video.py D:\\output\\clips video_final.mp4 --fade 0.5
  python ghep_video.py D:\\output\\clips video_final.mp4 --bgm nhac_nen.mp3 --bgm-vol 0.2
  python ghep_video.py D:\\output\\clips video_final.mp4 --srt phude.srt
        """
    )
    parser.add_argument("folder", help="Thư mục chứa các clip .mp4")
    parser.add_argument("output", nargs="?", default=None, help="File output (mặc định: <folder>/video_final.mp4)")
    parser.add_argument("--fade", type=float, default=0, help="Thời gian fade transition giữa clip (giây, mặc định: 0 = không fade)")
    parser.add_argument("--bgm", default=None, help="File nhạc nền .mp3/.wav")
    parser.add_argument("--bgm-vol", type=float, default=0.15, help="Volume nhạc nền (0.0-1.0, mặc định: 0.15)")
    parser.add_argument("--srt", default=None, help="File phụ đề .srt để burn vào video")
    parser.add_argument("--pattern", default="*.mp4", help="Pattern file (mặc định: *.mp4)")

    args = parser.parse_args()
    
    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print(f"❌ Thư mục không tồn tại: {folder}")
        sys.exit(1)

    output = args.output or os.path.join(folder, "video_final.mp4")
    output = os.path.abspath(output)

    clips = find_clips(folder, args.pattern)
    
    with tempfile.TemporaryDirectory() as tmp:
        # Bước 1: Ghép clip
        if args.fade > 0:
            concat_output = os.path.join(tmp, "concat.mp4") if (args.bgm or args.srt) else output
            concat_with_fade(clips, concat_output, args.fade)
        else:
            concat_output = os.path.join(tmp, "concat.mp4") if (args.bgm or args.srt) else output
            concat_simple(clips, concat_output, tmp)
        
        current = concat_output
        
        # Bước 2: Thêm nhạc nền (nếu có)
        if args.bgm:
            bgm_output = os.path.join(tmp, "bgm.mp4") if args.srt else output
            add_bgm(current, args.bgm, bgm_output, args.bgm_vol)
            current = bgm_output
        
        # Bước 3: Burn phụ đề (nếu có)
        if args.srt:
            burn_subtitles(current, args.srt, output)

    size_mb = os.path.getsize(output) / (1024 * 1024)
    print(f"\n🎬 Video hoàn chỉnh: {output} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
