import configparser
import logging
import asyncio
from pathlib import Path

import aiofiles
from fastapi import FastAPI, responses
from pydantic import BaseModel, Field
import os
import uuid
import shutil
from typing import Dict, Optional, Union
import aiohttp
from contextlib import asynccontextmanager

from .topic_distinction import process_vtt
from .obs_download import download_file
from .upload import upload
from .method import TranscriptionProcessor
from .audio_trimmer import trimmer_video

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="【%(asctime)s】：%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# 读取配置
config = configparser.ConfigParser()
config.read("/app/easywhisperx/config/config.ini")

download_directory = config["paths"]["download_directory"].replace('"', "").strip()
output_directory = config["paths"]["output_directory"].replace('"', "").strip()
hf_token = config["token"]["hf_token"].replace('"', "").strip()
api_key = config["token"]["api_key"].replace('"', "").strip()

callback_url = config["callback"]["url"].replace('"', "").strip()
callback_url_openubmc = config["openubmc"]["url"].replace('"', "").strip()
callback_username = config["openubmc"]["username"].replace('"', "").strip()
callback_password = config["openubmc"]["password"].replace('"', "").strip()

storage_server = config["storage"]["server"].replace('"', "").strip()
storage_bucket = config["storage"]["bucket"].replace('"', "").strip()
storage_server_ubmc = config["openubmc"]["server"].replace('"', "").strip()
storage_server_bucket = config["openubmc"]["bucket"].replace('"', "").strip()


class TaskManager:
    def __init__(self):
        self.task_queue = asyncio.Queue()
        self.task_status: Dict[str, str] = {}
        self.current_task: Optional[str] = None
        self.lock = asyncio.Lock()

    async def add_task(self, request):
        async with self.lock:
            if request.mid in self.task_status:
                return False
            current_size = self.task_queue.qsize()
            if current_size >= 10:
                logger.warning(f"High task queue volume! Current queue size: {current_size}")
            await self.task_queue.put(request)
            self.task_status[request.mid] = "queued"
            return True

    async def process_next_task(self):
        async with self.lock:
            if self.task_queue.empty():
                return None

            request = await self.task_queue.get()
            self.current_task = request.mid
            self.task_status[request.mid] = "processing"
            return request

    async def complete_task(self, mid: str):
        """完成任务后立即清除状态"""
        async with self.lock:
            self.current_task = None
            if mid in self.task_status:
                del self.task_status[mid]


task_manager = TaskManager()


@asynccontextmanager
async def lifespan(application: FastAPI):
    # 启动任务处理器
    processor_task = asyncio.create_task(task_processor())
    yield
    # 关闭时取消任务
    processor_task.cancel()
    try:
        await processor_task
    except asyncio.CancelledError:
        logger.info("Task processor stopped gracefully")


app = FastAPI(lifespan=lifespan)


class DownloadRequest(BaseModel):
    object_key: str
    bucket_key: str
    mid: str


class DownloadRequestUBMC(BaseModel):
    object_key: str
    bucket_key: str
    mid: str
    sub_id: str | None = Field(..., description="必须显式传递 sub_id 字段")


@app.post("/meeting_translate")
async def meeting_translate(request: Union[DownloadRequestUBMC, DownloadRequest]):
    """接收翻译请求并加入队列"""
    if not await task_manager.add_task(request):
        return {"message": "Task already in queue", "mid": request.mid}

    return {
        "message": "Task added to queue",
        "mid": request.mid,
        "queue_position": task_manager.task_queue.qsize(),
        "current_status": "queued",
    }


@app.get("/task_status/{mid}")
async def get_status(mid: str):
    """获取任务状态（不在字典中即表示已完成/不存在）"""
    status = task_manager.task_status.get(mid, "not_found")
    return {
        "mid": mid,
        "status": status,
        "is_processing": task_manager.current_task == mid,
        "queue_size": task_manager.task_queue.qsize(),
    }


async def task_processor():
    """后台任务处理器"""
    while True:
        try:
            request = await task_manager.process_next_task()
            if not request:
                await asyncio.sleep(1)
                continue

            try:
                if hasattr(request, "sub_id"):
                    await process_transcription_task_for_openubmc(
                        object_key=request.object_key,
                        bucket_key=request.bucket_key,
                        mid=request.mid,
                        sub_id=request.sub_id
                    )
                else:
                    await process_transcription_task(
                        object_key=request.object_key,
                        bucket_key=request.bucket_key,
                        mid=request.mid
                    )
                await task_manager.complete_task(request.mid)
            except Exception as e:
                logger.error(f"Task processing failed: {str(e)}", exc_info=True)
                await task_manager.complete_task(request.mid)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Task processor error: {str(e)}", exc_info=True)
            await asyncio.sleep(5)


async def process_transcription_task(object_key: str, bucket_key: str, mid: str):
    """实际处理任务"""
    download_path = None
    try:
        logger.info(f"Starting processing for mid {mid}")

        # 1. 创建目录
        uuid_str = str(uuid.uuid4())
        download_path = os.path.join(
            download_directory, uuid_str, object_key.split("/")[-1]
        )
        output_path = f"{output_directory}/{mid}"

        await asyncio.to_thread(
            os.makedirs, os.path.dirname(download_path), exist_ok=True
        )
        await asyncio.to_thread(os.makedirs, output_path, exist_ok=True)

        result = await asyncio.to_thread(
            download_file, bucket_key, object_key, download_path, 1
        )
        if not result["success"]:
            raise Exception(f"File download failed: {result['errorMessage']}")

        trimmer_path = await asyncio.to_thread(trimmer_video, download_path, mid)

        vtt_file = os.path.join(
            output_path, f"{os.path.splitext(os.path.basename(trimmer_path))[0]}.vtt"
        )
        json_file = os.path.join(
            output_path, f"{os.path.splitext(os.path.basename(trimmer_path))[0]}.json"
        )

        await run_async_subprocess(
            [
                "whisperx",
                "--model",
                "large-v3-turbo",
                "--language",
                "zh",
                "--diarize",
                "--hf_token",
                hf_token,
                trimmer_path,
                "--output_dir",
                output_path,
                "--initial_prompt",
                "这是一段openEuelr的会议记录，尽可能使用hotwords，不要翻译重复字数超过3的词。",
                "--compute_type",
                "float16",
                "--task",
                "transcribe",
                "--chunk_size",
                "20",
                "--suppress_tokens",
                "-1",
                "--max_line_width",
                "20",
            ]
        )

        await asyncio.to_thread(
            TranscriptionProcessor.deduplicate_vtt_file, vtt_file, max_repeat=5
        )

        async with aiofiles.open(vtt_file, "r", encoding="utf-8") as f:
            transcription_text = await f.read()

        formater = TranscriptionProcessor()
        adjusted_transcription = formater.adjust_speaker_numbers(transcription_text)

        async with aiofiles.open(vtt_file, "w", encoding="utf-8") as f:
            await f.write(adjusted_transcription)

        formater.convert_vtt_to_json(vtt_file)

        vtt_object_key, json_object_key = formater.generate_object_keys(
            mid, object_key, vtt_file, json_file
        )
        mp4_object_key = os.path.splitext(vtt_object_key)[0] + ".mp4"

        await asyncio.gather(
            upload(storage_server, storage_bucket, vtt_object_key, vtt_file, 1),
            upload(storage_server, storage_bucket, json_object_key, json_file, 1),
            upload(storage_server, storage_bucket, mp4_object_key, trimmer_path, 1),
        )

        await send_callback_async(
            mid,
            vtt_path=vtt_object_key,
            json_path=json_object_key,
            mp4_path=mp4_object_key,
        )

        logger.info(f"Task for mid {mid} completed successfully")

    finally:
        if download_path and os.path.exists(download_path):
            await asyncio.to_thread(shutil.rmtree, os.path.dirname(download_path))


async def process_transcription_task_for_openubmc(object_key: str, bucket_key: str, mid: str, sub_id: str):
    """实际处理任务"""
    download_path = None
    try:
        logger.info(f"Starting processing for mid {mid}")

        download_path = os.path.join(
            download_directory, mid, object_key.split("/")[-1]
        )
        if not sub_id:
            output_path = f"{output_directory}/{mid}"
        else:
            output_path = f"{output_directory}/{mid}/{sub_id}"

        await asyncio.to_thread(
            os.makedirs, os.path.dirname(download_path), exist_ok=True
        )
        await asyncio.to_thread(os.makedirs, output_path, exist_ok=True)

        result = await asyncio.to_thread(
            download_file, bucket_key, object_key, download_path, 2
        )
        if not result["success"]:
            raise Exception(f"File download failed: {result['errorMessage']}")

        trimmer_path = await asyncio.to_thread(trimmer_video, download_path, mid)

        vtt_file = os.path.join(
            output_path, f"{os.path.splitext(os.path.basename(trimmer_path))[0]}.vtt"
        )
        json_file = os.path.join(
            output_path, f"{os.path.splitext(os.path.basename(trimmer_path))[0]}.json"
        )

        await run_async_subprocess(
            [
                "whisperx",
                "--model",
                "large-v3-turbo",
                "--language",
                "zh",
                "--diarize",
                "--hf_token",
                hf_token,
                trimmer_path,
                "--output_dir",
                output_path,
                "--initial_prompt",
                "这是一段openEuelr的会议记录，尽可能使用hotwords，不要翻译重复字数超过3的词。",
                "--compute_type",
                "float16",
                "--task",
                "transcribe",
                "--chunk_size",
                "20",
                "--suppress_tokens",
                "-1",
                "--max_line_width",
                "20",
            ]
        )

        await asyncio.to_thread(
            TranscriptionProcessor.deduplicate_vtt_file, vtt_file, max_repeat=5
        )

        async with aiofiles.open(vtt_file, "r", encoding="utf-8") as f:
            transcription_text = await f.read()

        formater = TranscriptionProcessor()
        adjusted_transcription = formater.adjust_speaker_numbers(transcription_text)

        async with aiofiles.open(vtt_file, "w", encoding="utf-8") as f:
            await f.write(adjusted_transcription)

        topics_file = await asyncio.to_thread(
            process_vtt,
            input_path=Path(vtt_file),
            output_dir=Path(output_path)
        )

        formater.convert_vtt_to_json(vtt_file)

        vtt_object_key, json_object_key, topic_object_key = formater.generate_object_keys_for_openubmc(
            mid, sub_id, object_key, vtt_file, json_file, topics_file
        )
        mp4_object_key = os.path.splitext(vtt_object_key)[0] + ".mp4"

        await asyncio.gather(
            upload(storage_server_ubmc, storage_server_bucket, vtt_object_key, vtt_file, 2),
            upload(storage_server_ubmc, storage_server_bucket, json_object_key, json_file, 2),
            upload(storage_server_ubmc, storage_server_bucket, topic_object_key, topics_file, 2),
            upload(storage_server_ubmc, storage_server_bucket, mp4_object_key, trimmer_path, 2),
        )

        await send_callback_async_for_openubmc(
            mid,
            sub_id,
            vtt_path=vtt_object_key,
            json_path=json_object_key,
            mp4_path=mp4_object_key,
            topic_path=topic_object_key
        )

        logger.info(f"Task for mid {mid} completed successfully")

    finally:
        if download_path and os.path.exists(download_path):
            await asyncio.to_thread(shutil.rmtree, os.path.dirname(download_path))


async def run_async_subprocess(command):
    """异步执行子进程"""
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise Exception(f"Subprocess failed: {stderr.decode()}")


async def send_callback_async(mid: str, vtt_path: str, json_path: str, mp4_path: str):
    """异步发送回调"""
    try:
        callback_data = {
            "mid": mid,
            "text_vtt_url": f"https://{storage_bucket}.{storage_server}/{vtt_path}",
            "text_json_url": f"https://{storage_bucket}.{storage_server}/{json_path}",
            "text_video_url": f"https://{storage_bucket}.{storage_server}/{mp4_path}",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    callback_url, json=callback_data, timeout=30
            ) as resp:
                if resp.status == 200:
                    logger.info(f"Callback succeeded for mid: {mid}")
                else:
                    logger.error(
                        f"Callback failed for mid: {mid}, status: {resp.status}"
                    )
    except Exception as e:
        logger.error(f"Callback error for mid: {mid}: {str(e)}", exc_info=True)


async def send_callback_async_for_openubmc(mid: str, sub_id: str, vtt_path: str, json_path: str, mp4_path: str,
                                           topic_path: str):
    """异步发送回调"""
    try:
        callback_data = {
            "mid": mid,
            "sub_id": sub_id,
            "text_vtt_url": f"https://{storage_server_bucket}.{storage_server_ubmc}/{vtt_path}",
            "text_json_url": f"https://{storage_server_bucket}.{storage_server_ubmc}/{json_path}",
            "text_video_url": f"https://{storage_server_bucket}.{storage_server_ubmc}/{mp4_path}",
            "topic_url": f"https://{storage_server_bucket}.{storage_server_ubmc}/{topic_path}",
        }

        auth = aiohttp.BasicAuth(callback_username, callback_password)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    callback_url_openubmc, json=callback_data, timeout=30, auth=auth
            ) as resp:
                if resp.status == 200:
                    logger.info(f"Callback succeeded for mid: {mid}")
                else:
                    logger.error(
                        f"Callback failed for mid: {mid}, status: {resp.status}"
                    )
    except Exception as e:
        logger.error(f"Callback error for mid: {mid}: {str(e)}", exc_info=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
