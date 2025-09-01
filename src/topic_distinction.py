import configparser
import json
import requests
import webvtt
import re
from typing import List, Dict
from pathlib import Path

config = configparser.ConfigParser()
config.read("/root/wl/wl/easywhisperx/docker_gpu/config.ini")

api_key = config["token"]["api_key"].replace('"', "").strip()

# 配置API密钥和端点
API_KEY = api_key
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
MODEL_NAME = "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"
# MODEL_NAME = "zai-org/GLM-4.5V"


def analyze_vtt(vtt_path: Path) -> List[Dict]:
    """解析VTT文件并提取对话内容"""
    captions = []
    for caption in webvtt.read(vtt_path):
        captions.append(
            {
                "start": caption.start,
                "end": caption.end,
                "speaker": caption.identifier or "Unknown",
                "text": caption.text.strip().replace("\n", ""),
            }
        )
    return captions


def detect_topics(conversation: str) -> Dict:
    """调用API检测议题分段"""
    prompt = f"""请分析以下会议记录，识别并切分不同议题部分。
每个议题应包含：1) id 2) title 3) startTime 4) endTime 5) keyPoints。直接返回JSON格式的列表，不要添加任何额外解释：

格式参考：
        "id": 1,
        "title": "203SP和SP2上去除Kernel的BPFtour子包",
        "startTime": "00:01:29.278",
        "endTime": "00:16:36.192",
        "keyPoints": [
            "BPFTOR工具作为kernel子包发布的问题分析",
            "BPFTOR与libbpf版本差异导致的问题",
            "将BPFTOR从kernel软件包中切出并使用第三方代码仓的解决方案",
            "版本升级计划（从v6.3升级到v6.8）及兼容性分析",
            "对用户使用影响的讨论和最终决策"
        ]

输入内容：
{conversation}

要求：
1. 按自然议题转折点切分
2. 每个议题至少包含多轮对话，不要切分过细
3. 请关注类似"议题"等关键词，注意：议题是与会者讨论特定问题、提出不同观点、寻求解决方案并形成决策的实质性讨论环节，而非简单的信息通报或开场寒暄。
4. 时间戳格式保持原样（HH:MM:SS.SSS）
5. 为每个议题提供开始和结束时间
6. 仅返回JSON格式

识别议题时遵循以下严格标准：
1. **实质讨论原则**：仅当出问题分析或决策讨论时才视为议题
2. **决策导向**：议题必须导向某项结论、行动项或决议
3. **避免识别**：
   - 开场问候/寒暄（如"大家能听到吗？"）
   - 纯信息通报（无讨论环节）
   - 会议过渡性发言（如"接下来讨论..."）
   - 技术细节说明（除非引发争议讨论）
4. **时间连续性**：议题讨论应在时间上连续，中间不穿插其他话题
5. **关键词提示**：关注类似"讨论"、"问题"、"方案"、"决定"、"决议"等核心讨论词"""

    response = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        },
    )
    return response.json()

def extract_json_from_response(response_text: str) -> List[Dict]:
    if not response_text.strip():
        return []

    begin_markers = ["<|begin_of_box|>", "<|start_of_json|>", "```json"]
    end_markers = ["<|end_of_box|>", "<|end_of_json|>", "```"]

    for begin, end in zip(begin_markers, end_markers):
        if begin in response_text and end in response_text:
            start_idx = response_text.find(begin) + len(begin)
            end_idx = response_text.find(end, start_idx)
            json_str = response_text[start_idx:end_idx].strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                continue  # 继续尝试其他提取方式

    markdown_match = re.search(r"```(?:json)?\n(.*?)```", response_text, re.DOTALL)
    if markdown_match:
        try:
            return json.loads(markdown_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    cleaned_text = response_text.strip()
    for pattern in [r'^[^{\[\]\n]+', r'[^}\]]+$']:
        cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.DOTALL).strip()

    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError:
        return []

def process_vtt(input_path: Path, output_dir: Path):
    """处理VTT文件的完整流程"""
    # 1. 解析原始VTT
    captions = analyze_vtt(input_path)
    full_text = "\n".join(
        [f"[{c['start']}] {c['speaker']}: {c['text']}" for c in captions]
    )

    # 2. 调用API进行议题切分
    print("正在分析会议议题结构...")
    analysis = detect_topics(full_text)

    # 保存原始API响应
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "api_raw_response.json", "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)

    # 3. 处理API响应
    content = analysis["choices"][0]["message"]["content"]
    topics = extract_json_from_response(content)

    if not topics:
        print("未能从API响应中提取有效的议题数据")
        return

    # 议题分析结果
    with open(output_dir / "topic_analysis.json", "w", encoding="utf-8") as f:
        json.dump(topics, f, indent=4, ensure_ascii=False)

    return str(output_dir / "topic_analysis.json")
