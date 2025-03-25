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
        """
        将VTT格式的字幕文件转换为JSON格式

        Args:
            input_file: 输入的VTT文件路径

        Returns:
            生成的JSON文件路径
        """
        segments = []

        with open(input_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for i in range(len(lines)):
                line = lines[i].strip()
                if "-->" in line:
                    start_time, end_time = line.split(" --> ")
                    content = lines[i + 1].strip()
                    speaker_match = re.search(r"\[SPEAKER_(\d+)\]", content)
                    if speaker_match:
                        speaker_id = speaker_match.group(0)
                        content = re.sub(r"\[SPEAKER_\d+\]: ", "", content)
                        segments.append(
                            {
                                "ID": len(segments) + 1,
                                "start_time": start_time,
                                "end_time": end_time,
                                "speaker": speaker_id,
                                "content": content,
                            }
                        )

        json_output = {"segments": segments}
        output_file = os.path.splitext(input_file)[0] + ".json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(json_output, f, ensure_ascii=False, indent=4)

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
        month_str = object_key.split("/")[-2]
        year_str = "25"
        month_number = self.month_mapping.get(month_str.lower(), "01")
        current_year_month = f"{year_str}-{month_number}"

        base_path = object_key.split("/")[0]
        vtt_object_key = (
            f"{base_path}/{current_year_month}/{os.path.basename(vtt_file)}"
        )
        json_object_key = (
            f"{base_path}/{current_year_month}/{os.path.basename(json_file)}"
        )

        return vtt_object_key, json_object_key
