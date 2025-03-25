import datetime
import os
import shutil
import subprocess
import re
import json
import tempfile
import sys


class AudioTrimmer:
    """音频/视频静音剪切工具类，提供检测和剪切功能"""

    @staticmethod
    def check_ffmpeg():
        """验证ffmpeg是否存在"""
        if path := shutil.which("ffmpeg"):
            return path
        raise EnvironmentError("未找到ffmpeg，请先安装并添加到PATH")

    @staticmethod
    def check_ffprobe():
        """验证ffprobe是否存在"""
        if path := shutil.which("ffprobe"):
            return path
        raise EnvironmentError("未找到ffprobe，请先安装并添加到PATH")

    def __init__(self, input_file, noise_threshold=-60.0, duration_threshold=20.0):
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

        self.ffmpeg_path = AudioTrimmer.check_ffmpeg()
        self.ffprobe_path = AudioTrimmer.check_ffprobe()

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
            "-i",
            self.input_file,
            "-af",
            f"silencedetect=noise={self.noise_threshold}dB:d={self.duration_threshold}",
            "-f",
            "null",
            "-",
        ]

        process = subprocess.Popen(
            cmd, stderr=subprocess.PIPE, universal_newlines=True, shell=False
        )

        silence_segments = []
        current_start = None
        buffer = ""

        start_pattern = re.compile(r"silence_start:\s*([\d.]+)")
        end_pattern = re.compile(
            r"silence_end:\s*([\d.]+).*?silence_duration:\s*([\d.]+)"
        )

        while True:
            chunk = process.stderr.read(1024)
            if not chunk and process.poll() is not None:
                break
            buffer += chunk

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()

                if "silence_start" in line:
                    if match := start_pattern.search(line):
                        current_start = float(match.group(1))
                        print(f"[DEBUG] 检测到静音开始: {current_start}")

                elif "silence_end" in line:
                    if match := end_pattern.search(line):
                        end = float(match.group(1))
                        duration = float(match.group(2))
                        if (
                            duration >= self.duration_threshold
                            and current_start is not None
                        ):
                            silence_segments.append((current_start, end))
                            print(
                                f"[DEBUG] 检测到静音结束: {end}, 持续时间: {duration}"
                            )
                        current_start = None

        # 处理视频结尾的静音
        duration = self.get_media_duration()
        if current_start is not None:
            if duration - current_start >= self.duration_threshold:
                silence_segments.append((current_start, duration))
                print(f"[DEBUG] 检测到结尾静音: {current_start} 到 {duration}")

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


class FastAudioTrimmer(AudioTrimmer):
    def fast_trim(self, output_file):
        valid_segments = self.get_valid_segments()
        print(f"有效片段：{valid_segments}")

        if not valid_segments:
            print("没有需要处理的片段")
            return False

        # 如果只有一个有效片段且与整个视频时长相同，则直接复制原文件
        duration = self.get_media_duration()
        if len(valid_segments) == 1 and valid_segments[0] == (0.0, duration):
            print("视频中没有静音片段，直接复制原文件")
            shutil.copy2(self.input_file, output_file)
            return True

        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            # 阶段1：生成切割片段
            segment_files = []
            for idx, (start, end) in enumerate(valid_segments):
                output_segment = os.path.join(
                    tmpdir, f"{output_file}_segment_{idx}.mp4"
                )
                duration = end - start

                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(start),
                    "-i",
                    self.input_file,
                    "-t",
                    str(duration),
                    "-c:v",
                    "copy",  # 视频流直接复制
                    "-c:a",
                    "copy",  # 音频流直接复制
                    "-avoid_negative_ts",
                    "make_zero",
                    output_segment,
                ]
                subprocess.run(cmd, check=True)
                segment_files.append(output_segment)

            # 阶段2：合并片段
            list_file = os.path.join(tmpdir, f"{output_file}_filelist.txt")
            with open(list_file, "w") as f:
                for file in segment_files:
                    f.write(f"file '{file}'\n")

            merge_cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_file,
                "-c",
                "copy",  # 直接流复制
                output_file,
            ]
            subprocess.run(merge_cmd, check=True)

        print(f"处理完成，输出文件：{output_file}")
        return True


def auto_trimmer(input_file, output_file):
    """自动剪辑的入口，输入是本地一个原始视频路径，输出是一个剪辑后的视频路径"""
    trimmer = FastAudioTrimmer(input_file)
    trimmer.fast_trim(output_file)
