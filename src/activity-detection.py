# from pyannote.audio import Pipeline
# pipeline = Pipeline.from_pretrained("pyannote/voice-activity-detection")
# output = pipeline("input.wav")
# for speech in output.get_timeline().support():
#     print(f"有效语音段: {speech.start:.1f}s -> {speech.end:.1f}s")

import subprocess
import re
import math


def detect_silence(input_file):
    command = [
        "ffmpeg",
        "-i",
        input_file,
        "-af",
        "silencedetect=noise=-50dB:d=60",
        "-f",
        "null",
        "-",
    ]

    # 运行 FFmpeg 并捕获输出
    process = subprocess.run(command, stderr=subprocess.PIPE, text=True)
    return process.stderr


def parse_silences(output):
    # 使用正则表达式匹配静音区间
    pattern = r"silence_start: (\d+\.?\d*)[\s\S]*?silence_end: (\d+\.?\d*)"
    matches = re.findall(pattern, output)

    # 转换为浮点数元组列表
    return [(float(start), float(end)) for start, end in matches]


def merge_intervals(intervals):
    if not intervals:
        return []

    # 按开始时间排序
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_intervals[0]]

    for current in sorted_intervals[1:]:
        last = merged[-1]
        # 合并重叠或相邻区间
        if math.floor(current[0]) <= math.floor(last[1]):
            merged[-1] = (last[0], max(last[1], current[1]))
        else:
            merged.append(current)

    return merged


# 使用示例
if __name__ == "__main__":
    video_path = "83887950610.mp4"

    # 获取 FFmpeg 输出
    ffmpeg_output = detect_silence(video_path)

    # 解析静音区间
    silences = parse_silences(ffmpeg_output)

    # 合并区间
    merged_silences = merge_intervals(silences)

    print("原始静音区间:")
    for s in silences:
        print(f"{s[0]:.2f} - {s[1]:.2f} 秒")

    print("\n合并后静音区间:")
    for m in merged_silences:
        print(f"{m[0]:.2f} - {m[1]:.2f} 秒")
