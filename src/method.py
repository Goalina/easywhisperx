import json
import os
import re
from typing import Dict, List, Tuple


class TranscriptionProcessor:
    """
    处理转录文件的工具类，支持VTT转JSON格式、说话者编号调整和对象键生成
    """

    def __init__(self):
        self.month_mapping = {
            "jan": "01",
            "feb": "02",
            "mar": "03",
            "apr": "04",
            "may": "05",
            "jun": "06",
            "jul": "07",
            "aug": "08",
            "sep": "09",
            "oct": "10",
            "nov": "11",
            "dec": "12",
        }

    @staticmethod
    def adjust_speaker_numbers(transcription: str) -> str:
        """
        调整转录文本中的说话者编号，使其从1开始连续

        Args:
            transcription: 包含说话者标记的文本(如"[SPEAKER_01]")

        Returns:
            调整后的文本，说话者编号连续
        """
        speaker_count = 1
        speaker_map = {}
        speaker_pattern = re.compile(r"\[SPEAKER_(\d+)\]")

        def replace_speaker(match):
            nonlocal speaker_count
            speaker = match.group(1)
            if speaker not in speaker_map:
                speaker_map[speaker] = f"SPEAKER_{speaker_count:02d}"
                speaker_count += 1
            return f"[{speaker_map[speaker]}]"

        return speaker_pattern.sub(replace_speaker, transcription)

    @staticmethod
    def convert_vtt_to_json(input_file: str) -> str:
        segments = []

        with open(input_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

            i = 0
            while i < len(lines):
                line = lines[i]

                if line == "WEBVTT":
                    i += 1
                    continue

                if "-->" in line:
                    start_time, end_time = [t.strip() for t in line.split("-->")]
                    content_lines = []

                    i += 1
                    while i < len(lines) and "-->" not in lines[i]:
                        content_lines.append(lines[i])
                        i += 1

                    full_content = "".join(content_lines)
                    full_content = re.sub(r"\s+", " ", full_content).strip()

                    speaker_match = re.search(
                        r"\[(SPEAKER_\d+)\]:\s*(.*)", full_content
                    )
                    if speaker_match:
                        segments.append(
                            {
                                "ID": len(segments) + 1,
                                "start_time": start_time,
                                "end_time": end_time,
                                "speaker": f"[{speaker_match.group(1)}]",
                                "content": speaker_match.group(2),
                            }
                        )
                else:
                    i += 1

        output_file = os.path.splitext(input_file)[0] + ".json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({"segments": segments}, f, ensure_ascii=False, indent=4)

        return output_file

    def generate_object_keys(
        self, mid: str, object_key: str, vtt_file: str, json_file: str
    ) -> Tuple[str, str]:
        """
        生成VTT和JSON文件在对象存储中的完整路径

        Args:
            mid: 会议ID
            object_key: 基础对象键
            vtt_file: VTT本地文件路径
            json_file: JSON本地文件路径

        Returns:
            (vtt_object_key, json_object_key) 元组
        """
        month_str = object_key.split("/")[-3]
        sig_str = object_key.split("/")[-4]
        year_str = "25"
        month_number = self.month_mapping.get(month_str.lower(), "01")
        current_year_month = f"{year_str}-{month_number}"

        base_path = object_key.split("/")[0]
        vtt_object_key = f"{base_path}/{sig_str}/{current_year_month}/{mid}/{os.path.basename(vtt_file)}"
        json_object_key = f"{base_path}/{sig_str}/{current_year_month}/{mid}/{os.path.basename(json_file)}"

        return vtt_object_key, json_object_key

    @staticmethod
    def deduplicate(text, max_repeat=3):
        # 处理连续重复的相同短语（支持中文）
        pattern = rf"((?:\S+?|\s+?))\1{{{max_repeat},}}"
        text = re.sub(pattern, r"\1", text)

        return text

    @staticmethod
    def deduplicate_vtt_file(file_path, max_repeat):
        """
        对VTT文件的每一行进行去重处理，并将结果写入指定的输出文件
        :param file_path: VTT文件输入路径
        :param max_repeat: 最大允许重复次数
        """
        try:
            # 读取VTT文件内容
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            mode = True

            # 处理每一行
            output_lines = []
            for line in lines:
                # 去除首尾空白后处理，但保留原始换行符
                stripped_line = line.rstrip("\n")
                if stripped_line:
                    if mode:
                        processed_line = TranscriptionProcessor.deduplicate(
                            stripped_line, max_repeat - 1
                        )
                        if processed_line != stripped_line:
                            mode = False
                        # 只在需要的时候将处理后的行添加到输出列表中
                        output_lines.append(processed_line)
                        print(processed_line)
                    else:
                        continue
                else:
                    output_lines.append("")  # 保留空行
                    mode = True

            # 将处理后的内容写入输出文件
            with open(file_path, "w", encoding="utf-8") as f_out:
                f_out.write("\n".join(output_lines))

        except FileNotFoundError:
            raise FileNotFoundError(f"文件 {file_path} 未找到")
        except Exception as e:
            raise Exception(f"处理文件 {file_path} 时出错: {str(e)}")
