import subprocess
import re
import json
import argparse


def get_media_duration(input_file):
    """获取媒体文件的总时长（秒）"""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        input_file,
    ]
    output = subprocess.check_output(cmd).decode("utf-8")
    data = json.loads(output)
    return float(data["format"]["duration"])


def detect_silence(input_file, noise_threshold, duration_threshold):
    """检测静默片段并返回起止时间"""
    cmd = [
        "ffmpeg",
        "-i",
        input_file,
        "-af",
        f"silencedetect=noise={noise_threshold}dB:d={duration_threshold}",
        "-f",
        "null",
        "-",
    ]
    process = subprocess.Popen(cmd, stderr=subprocess.PIPE, universal_newlines=True)
    _, stderr = process.communicate()

    silence_segments = []
    current_start = None
    start_pattern = re.compile(r"silence_start: (\d+\.?\d*)")
    end_pattern = re.compile(
        r"silence_end: (\d+\.?\d*) \| silence_duration: (\d+\.?\d*)"
    )

    for line in stderr.split("\n"):
        if "silence_start:" in line:
            match = start_pattern.search(line)
            if match:
                current_start = float(match.group(1))
        elif "silence_end:" in line:
            match = end_pattern.search(line)
            if match and current_start is not None:
                end = float(match.group(1))
                duration = float(match.group(2))
                if duration >= duration_threshold:
                    silence_segments.append((current_start, end))
                current_start = None
    return silence_segments


def generate_filter_complex(segments):
    """生成FFmpeg滤镜链"""
    filter_chain = []
    concat_inputs = []
    for i, (start, end) in enumerate(segments):
        filter_chain.append(
            f"[0:a]trim=start={start}:end={end},asetpts=PTS-STARTPTS[part{i}];"
        )
        concat_inputs.append(f"[part{i}]")
    concat_str = "".join(concat_inputs) + f"concat=n={len(segments)}:v=0:a=1[out]"
    filter_chain.append(concat_str)
    return "".join(filter_chain)


def main():
    parser = argparse.ArgumentParser(description="自动剪切长静默音频片段")
    parser.add_argument("input", help="输入音频文件路径")
    parser.add_argument("output", help="输出音频文件路径")
    parser.add_argument(
        "--noise", type=float, default=-50.0, help="静音检测阈值（单位：dB，默认-50）"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="最小静音持续时间（单位：秒，默认60）",
    )
    args = parser.parse_args()

    # 获取文件信息
    duration = get_media_duration(args.input)
    silence_segments = detect_silence(args.input, args.noise, args.duration)
    silence_segments.sort(key=lambda x: x[0])

    # 生成有效片段
    valid_segments = []
    prev_end = 0.0
    for start, end in silence_segments:
        if start > prev_end:
            valid_segments.append((prev_end, start))
        prev_end = end
    if prev_end < duration:
        valid_segments.append((prev_end, duration))

    if not valid_segments:
        print("警告：没有有效音频片段，输出文件将为空！")
        return

    # 构建并执行FFmpeg命令
    filter_complex = generate_filter_complex(valid_segments)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        args.input,
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        args.output,
    ]
    try:
        subprocess.run(cmd, check=True)
        print(f"处理完成！输出文件已保存至：{args.output}")
    except subprocess.CalledProcessError as e:
        print(f"处理失败：{e}")


if __name__ == "__main__":
    main()
