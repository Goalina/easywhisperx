import subprocess
import re


class Ffmpeg:

    def __init__(
        self, input_file, output_file, noise_threshold=-50.0, duration_threshold=60.0
    ):
        self.input_file = input_file
        self.output_file = output_file
        self.noise_threshold = noise_threshold
        self.duration_threshold = duration_threshold

    def get_total_times(self):
        # 构造ffmpeg命令
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            self.input_file,
        ]

        try:
            output = subprocess.check_output(
                command,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,  # 添加超时防止卡死
            )
            return float(output.strip())
        except subprocess.CalledProcessError as e:
            print(f"命令执行失败: {e.output}")
        except FileNotFoundError:
            print("找不到 ffprobe 命令")
        except ValueError:
            print("无法解析输出内容")

    def merge_intervals(self, intervals):
        if not intervals:
            return []

        # 按开始时间排序
        sorted_intervals = sorted(intervals, key=lambda x: x[0])
        merged = [sorted_intervals[0]]

        for current in sorted_intervals[1:]:
            last = merged[-1]
            # 合并重叠或相邻区间
            if current[0] <= last[1]:
                merged[-1] = (last[0], max(last[1], current[1]))
            else:
                merged.append(current)

        return merged

    def get_silences_segments(self):
        command = [
            "ffmpeg",
            "-i",
            self.input_file,
            "-af",
            f"silencedetect=noise={self.noise_threshold}:d={self.duration_threshold}",
            "-f",
            "null",
            "-",
            "2>&1",
        ]

        # 运行 FFmpeg 并捕获输出
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, shell=True)

        # 使用正则表达式匹配静音区间
        pattern = r"silence_start: (\d+\.?\d*)[\s\S]*?silence_end: (\d+\.?\d*)"
        matches = re.findall(pattern, output)

        # 转换为浮点数元组列表
        segments = [(float(start), float(end)) for start, end in matches]

        return self.merge_intervals(segments)

    def trim_head(self, start):
        if start > self.duration_threshold:
            return

        command = [
            "ffmpeg",
            "-ss",
            str(start),
            "-i",
            self.output_file,
            "-c copy",
            self.output_file,
        ]
        # 运行 FFmpeg 并捕获输出
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, shell=True)
        print(f"trim_head: {output}")

    def trim_tail(self, start, end):
        total_time = self.get_total_time()
        if end <= total_time and total_time - end < self.duration_threshold:
            command = [
                "ffmpeg",
                "-i",
                self.input_file,
                "-t",
                str(start),
                "-c copy",
                self.output_file,
            ]
            # 运行 FFmpeg 并捕获输出
            output = subprocess.check_output(
                command, stderr=subprocess.STDOUT, shell=True
            )
            print(f"trim_tail: {output}")


if __name__ == "__main__":
    video_path = "83887950610.mp4"
    output_path = "output.mp4"
    noise_threshold = 50.0
    duration_threshold = 60.0
    ffmpeg = Ffmpeg(video_path, output_path, noise_threshold, duration_threshold)
    total_seconds = ffmpeg.get_total_times()
    print(f"Video duration: {total_seconds} seconds")

    silences_segments = ffmpeg.get_silences_segments()
    print(f"Silences segments: {silences_segments}")
