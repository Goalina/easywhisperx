import json
import os
import re


def adjust_speaker_numbers(transcription):
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

    adjusted_transcription = speaker_pattern.sub(replace_speaker, transcription)

    return adjusted_transcription


def convert_vtt_to_json(input_file):
    segments = []

    with open(input_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        for i in range(len(lines)):
            line = lines[i].strip()
            if "-->" in line:
                start_time, end_time = line.split(" --> ")
                content = lines[i + 1].strip()
                # 提取说话者
                speaker_match = re.search(r"\[SPEAKER_(\d+)\]", content)
                if speaker_match:
                    speaker_id = speaker_match.group(0)
                    # 替换内容中的 speaker 编号
                    content = re.sub(r"\[SPEAKER_\d+\]: ", "", content)
                    segments.append(
                        {
                            "ID": len(segments) + 1,
                            "start_time": start_time,
                            "end_time": end_time,
                            "speaker": speaker_id,  # 使用原始 speaker_id
                            "content": content,
                        }
                    )

    json_output = {"segments": segments}

    # 生成输出文件名，替换后缀为 .json
    output_file = os.path.splitext(input_file)[0] + ".json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(json_output, f, ensure_ascii=False, indent=4)


def generate_object_keys(mid, object_key, vtt_file, json_file):
    month_mapping = {
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

    # 从 object_key 中提取月份部分
    month_str = object_key.split("/")[-2]  # 获取月份部分
    year_str = "25"  # 假设年份为 2025

    # 获取对应的月份格式
    month_number = month_mapping.get(month_str.lower())
    current_year_month = f"{year_str}-{month_number}"

    vtt_object_key = (
        f"{object_key.split('/')[0]}/{current_year_month}/{os.path.basename(vtt_file)}"
    )
    json_object_key = (
        f"{object_key.split('/')[0]}/{current_year_month}/{os.path.basename(json_file)}"
    )

    return vtt_object_key, json_object_key
