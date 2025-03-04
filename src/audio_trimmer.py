import os
import shutil
import subprocess
import re
import json


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

    def __init__(self, input_file, noise_threshold=-50.0, duration_threshold=60.0):
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
            raise RuntimeError("获取媒体时长超时: {e}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"获取时长失败: {e}")

    def detect_silence(self):
        """检测静默片段并返回起止时间"""
        cmd = [
            "ffmpeg",
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
                    if duration >= self.duration_threshold:
                        silence_segments.append((current_start, end))
                    current_start = None
        return silence_segments

    def get_valid_segments(self):
        """根据静音片段计算有效（非静音）片段"""
        duration = self.get_media_duration()
        silence_segments = self.detect_silence()
        silence_segments.sort(key=lambda x: x[0])

        valid_segments = []
        prev_end = 0.0
        for start, end in silence_segments:
            if start > prev_end:
                valid_segments.append((prev_end, start))
            prev_end = end
        if prev_end < duration:
            valid_segments.append((prev_end, duration))

        return valid_segments

    def generate_filter_complex(self, segments):
        """生成FFmpeg滤镜链用于剪切和拼接"""
        if not segments:
            return None
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

    def trim_silence(self, output_file):
        """执行静音剪切并生成新文件
        Args:
            output_file (str): 输出文件路径
        Returns:
            bool: 是否成功
        """
        valid_segments = self.get_valid_segments()
        if not valid_segments:
            print("警告：没有有效音频片段，跳过处理！")
            return False

        filter_complex = self.generate_filter_complex(valid_segments)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            self.input_file,
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            output_file,
        ]
        try:
            subprocess.run(cmd, check=True, shell=False)
            print(f"处理完成！输出文件已保存至：{output_file}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"处理失败：{e}")
            return False


# 使用示例
if __name__ == "__main__":
    input_file = "83887950610.mp4"
    output_file = "output.mp4"
    trimmer = AudioTrimmer(input_file, noise_threshold=-50.0, duration_threshold=60.0)

    # 获取有效片段（可选，用于调试）
    valid_segments = trimmer.get_valid_segments()
    print("有效片段:", valid_segments)

    # 执行剪切
    trimmer.trim_silence(output_file)
