import datetime
import os
import shutil
import subprocess
import re
import json
import tempfile


def check_ffmpeg():
    """验证ffmpeg是否存在"""
    if path := shutil.which("ffmpeg"):
        return path
    raise EnvironmentError("未找到ffmpeg，请先安装并添加到PATH")


def check_ffprobe():
    """验证ffprobe是否存在"""
    if path := shutil.which("ffprobe"):
        return path
    raise EnvironmentError("未找到ffprobe，请先安装并添加到PATH")


class AudioTrimmer:
    """音频/视频静音剪切工具类，提供检测和剪切功能"""

    def __init__(self, input_file, noise_threshold=-30.0, duration_threshold=5.0):
        """初始化剪切工具
        Args:
            input_file (str): 输入文件路径
            noise_threshold (float): 静音检测阈值（dB，默认 -50.0）
            duration_threshold (float): 最小静音持续时间（秒，默认 60.0）
        """
        if not os.path.isfile(input_file):
            raise ValueError(f"输入文件不存在或不可访问: {input_file}")
        self.input_file = os.path.abspath(input_file)

        if not isinstance(noise_threshold, (int, float)):
            raise TypeError("噪声阈值必须是数值类型")
        if not isinstance(duration_threshold, (int, float)) or duration_threshold <= 0:
            raise ValueError("静音时长阈值必须是正数")

        self.ffmpeg_path = check_ffmpeg()
        self.ffprobe_path = check_ffprobe()
        self.noise_threshold = noise_threshold
        self.duration_threshold = duration_threshold

    def get_media_duration(self):
        """获取媒体文件的总时长（秒）"""
        cmd = [
            self.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            self.input_file,
        ]
        try:
            output = subprocess.check_output(cmd, shell=False).decode("utf-8")
            data = json.loads(output)
            return float(data["format"]["duration"])
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"获取媒体时长超时: {e}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"获取时长失败: {e}")

    def detect_silence(self):
        """改进版静音检测方法，支持完整日志解析"""
        cmd = [
            self.ffmpeg_path,
            "-i", self.input_file,
            "-af", f"silencedetect=noise={self.noise_threshold}dB:d={self.duration_threshold}",
            "-f", "null", "-",
        ]

        process = subprocess.Popen(
            cmd, stderr=subprocess.PIPE,
            universal_newlines=True, shell=False
        )

        silence_segments = []
        current_start = None
        buffer = ""

        # 更健壮的正则表达式
        start_pattern = re.compile(r"silence_start:\s*([\d.]+)")
        end_pattern = re.compile(r"silence_end:\s*([\d.]+).*?silence_duration:\s*([\d.]+)")

        while True:
            chunk = process.stderr.read(1024)
            if not chunk and process.poll() is not None:
                break
            buffer += chunk

            # 按行处理日志
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()

                # 检测静音开始
                if "silence_start" in line:
                    if match := start_pattern.search(line):
                        current_start = float(match.group(1))
                        print(f"[DEBUG] 检测到静音开始: {current_start}")  # 调试输出

                # 检测静音结束
                elif "silence_end" in line:
                    if match := end_pattern.search(line):
                        end = float(match.group(1))
                        duration = float(match.group(2))
                        if duration >= self.duration_threshold and current_start is not None:
                            silence_segments.append((current_start, end))
                            print(f"[DEBUG] 检测到静音结束: {end}, 持续时间: {duration}")  # 调试输出
                        current_start = None

        # 处理视频结尾的静音
        duration = self.get_media_duration()
        if current_start is not None and duration - current_start >= self.duration_threshold:
            silence_segments.append((current_start, duration))
            print(f"[DEBUG] 检测到结尾静音: {current_start} 到 {duration}")  # 调试输出

        return silence_segments

    # 修改 get_valid_segments 方法
    def get_valid_segments(self):
        duration = self.get_media_duration()
        silence_segments = self.detect_silence()
        print(f"[DEBUG] 静音段落: {silence_segments}")  # 新增调试输出

        silence_segments.sort(key=lambda x: x[0])

        valid_segments = []
        prev_end = 0.0
        for start, end in silence_segments:
            if start > prev_end:
                valid_segments.append((prev_end, start))
            prev_end = end
        if prev_end < duration:
            valid_segments.append((prev_end, duration))

        print(f"[DEBUG] 有效段落: {valid_segments}")  # 新增调试输出
        return valid_segments

    def generate_filter_complex(self, segments):
        """生成FFmpeg滤镜链用于剪切和拼接音频和视频"""
        if not segments:
            return None

        audio_filter = []
        video_filter = []

        # 生成音频处理链
        audio_parts = []
        for i, (start, end) in enumerate(segments):
            audio_filter.append(
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}];"
            )
            audio_parts.append(f"[a{i}]")

        # 生成音频concat
        audio_filter.append(
            f"{''.join(audio_parts)}concat=n={len(segments)}:v=0:a=1[out_audio];"
        )

        # 生成视频处理链
        video_parts = []
        for i, (start, end) in enumerate(segments):
            video_filter.append(
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}];"
            )
            video_parts.append(f"[v{i}]")

        # 生成视频concat
        video_filter.append(
            f"{''.join(video_parts)}concat=n={len(segments)}[out_video]"
        )

        # 合并过滤器链
        return "".join(audio_filter + video_filter)

    def trim_silence(self, output_file):
        """执行静音剪切并生成新文件"""
        valid_segments = self.get_valid_segments()
        print("有效片段:", valid_segments)

        if not valid_segments:
            print("警告：没有有效音频片段，跳过处理！")
            return False

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            self.input_file,
            "-filter_complex",
            self.generate_filter_complex(valid_segments),
            "-map", "[out_audio]",
            "-map", "[out_video]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            output_file,
        ]
        try:
            subprocess.run(cmd, check=True, shell=False)
            print(f"处理完成！输出文件已保存至：{output_file}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"处理失败：{e}")
            return False


class FastAudioTrimmer(AudioTrimmer):
    def fast_trim(self, output_file):
        valid_segments = self.get_valid_segments()
        print(f"有效片段：{valid_segments}")

        if not valid_segments:
            print("没有需要处理的片段")
            return False

        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            # 阶段1：生成切割片段
            segment_files = []
            for idx, (start, end) in enumerate(valid_segments):
                output_segment = os.path.join(tmpdir, f"segment_{idx}.mp4")
                duration = end - start

                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(start),
                    "-i", self.input_file,
                    "-t", str(duration),
                    "-c:v", "copy",  # 视频流直接复制
                    "-c:a", "copy",  # 音频流直接复制
                    "-avoid_negative_ts", "make_zero",
                    output_segment
                ]
                subprocess.run(cmd, check=True)
                segment_files.append(output_segment)

            # 阶段2：合并片段
            list_file = os.path.join(tmpdir, "filelist.txt")
            with open(list_file, "w") as f:
                for file in segment_files:
                    f.write(f"file '{file}'\n")

            merge_cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c", "copy",  # 直接流复制
                output_file
            ]
            subprocess.run(merge_cmd, check=True)

        print(f"处理完成，输出文件：{output_file}")
        return True


# 使用示例
if __name__ == "__main__":
    print("当前时间:", datetime.datetime.now())
    input_file = "83887950610.mp4"
    input_file = "test_pattern.mp4"
    output_file = "10_fast.mp4"
    # trimmer = AudioTrimmer(input_file, noise_threshold=-50.0, duration_threshold=60.0)
    # trimmer.trim_silence(output_file)
    trimmer = FastAudioTrimmer(input_file)
    trimmer.fast_trim(output_file)