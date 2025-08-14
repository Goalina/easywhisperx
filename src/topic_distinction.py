import json
import requests
import webvtt
import re
from typing import List, Dict
from pathlib import Path

# 配置API密钥和端点
API_KEY = ""
API_URL = "https://api.siliconflow.cn/v1/chat/completions"
MODEL_NAME = "zai-org/GLM-4.5"


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
每个议题应包含：1) 议题序号 2)标题 3) 开始时间 4) 结束时间 5) 关键讨论点，也用序号区分。直接返回JSON格式的列表，字段名使用英文，不要添加任何额外解释：

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
            "temperature": 0.2,  # 进一步降低随机性确保结构化输出
        },
    )
    return response.json()


def extract_json_from_response(response_text: str) -> List[Dict]:
    """从API响应中提取JSON内容"""
    # 尝试从Markdown代码块中提取JSON
    match = re.search(r"```json\n(.*?)```", response_text, re.DOTALL)
    if match:
        json_content = match.group(1).strip()
        try:
            return json.loads(json_content)
        except json.JSONDecodeError:
            pass

    # 如果Markdown提取失败，尝试直接解析整个响应
    try:
        return json.loads(response_text)
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("input_vtt", help="输入VTT文件路径")
    parser.add_argument("-o", "--output", default="./output3", help="输出目录")
    args = parser.parse_args()

    process_vtt(input_path=Path(args.input_vtt), output_dir=Path(args.output))
    print(f"处理完成！结果已保存到 {args.output} 目录")
