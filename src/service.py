import logging

logging.basicConfig(
    level=logging.INFO,
    format='【%(asctime)s】：%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

from .obs_download import download_file
from .upload import upload
from .method import TranscriptionProcessor
from .audio_trimmer import trimmer_video

import os
import configparser
import subprocess
import requests
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from asyncio import Semaphore
import uuid
import shutil

config = configparser.ConfigParser()
config.read("/app/easywhisperx/config/config.ini")

download_directory = config["paths"]["download_directory"].replace('"', "").strip()
output_directory = config["paths"]["output_directory"].replace('"', "").strip()
hf_token = config["token"]["hf_token"].replace('"', "").strip()

callback_url = config["callback"]["url"].replace('"', "").strip()
storage_server = config["storage"]["server"].replace('"', "").strip()
storage_bucket = config["storage"]["bucket"].replace('"', "").strip()

app = FastAPI()
semaphore = Semaphore(2)


class DownloadRequest(BaseModel):
    object_key: str
    bucket_key: str
    mid: str


@app.post("/meeting_translate")
async def meeting_translate(request: DownloadRequest, background_tasks: BackgroundTasks):
    logger.info(f"Received new transcription task, mid: {request.mid}")
    background_tasks.add_task(process_with_semaphore, request.object_key, request.bucket_key, request.mid)
    return {"message": "Transcription task started", "mid": request.mid}


async def process_with_semaphore(object_key: str, bucket_key: str, mid: str):
    async with semaphore:
        await process_transcription_task(object_key, bucket_key, mid)


async def process_transcription_task(object_key: str, bucket_key: str, mid: str):
    download_path = None
    try:
        logger.info(f"Starting processing for mid {mid}")

        uuid_str = str(uuid.uuid4())
        download_path = os.path.join(download_directory, uuid_str, object_key.split("/")[-1])
        output_path = f"{output_directory}/{uuid_str}"

        os.makedirs(os.path.dirname(download_path), exist_ok=True)
        os.makedirs(output_path, exist_ok=True)

        result = download_file(bucket_key, object_key, download_path)
        if not result["success"]:
            raise Exception(f"File download failed: {result['errorMessage']}")

        trimmer_path = trimmer_video(download_path, mid)

        vtt_file = os.path.join(output_path, f"{os.path.splitext(os.path.basename(download_path))[0]}.vtt")
        json_file = os.path.join(output_path, f"{os.path.splitext(os.path.basename(download_path))[0]}.json")

        whisperx_command = [
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
            output_directory,
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
        process = subprocess.run(whisperx_command, capture_output=True, text=True, shell=False, timeout=3600)
        if process.returncode != 0:
            raise Exception(f"whisperx failed: {process.stderr}")

        with open(vtt_file, "r", encoding="utf-8") as f:
            transcription_text = f.read()
        formater = TranscriptionProcessor()
        adjusted_transcription = formater.adjust_speaker_numbers(transcription_text)
        with open(vtt_file, "w", encoding="utf-8") as f:
            f.write(adjusted_transcription)
        formater.convert_vtt_to_json(vtt_file)

        vtt_object_key, json_object_key = formater.generate_object_keys(mid, object_key, vtt_file, json_file)
        mp4_object_key = os.path.splitext(vtt_object_key)[0] + '.mp4'

        upload(storage_server, storage_bucket, file_path=vtt_file, objectKey=vtt_object_key)
        upload(storage_server, storage_bucket, file_path=json_file, objectKey=json_object_key)
        upload(storage_server, storage_bucket, file_path=trimmer_path, objectKey=mp4_object_key)

        send_callback(mid, vtt_path=vtt_object_key, json_path=json_object_key, mp4_path=mp4_object_key)
        logger.info(f"Task for mid {mid} completed successfully")

    except Exception as e:
        logger.error(f"Task for mid {mid} failed: {str(e)}", exc_info=True)
    finally:
        if download_path and os.path.exists(download_path):
            shutil.rmtree(os.path.dirname(download_path))
            logger.debug(f"Cleaned up: {download_path}")


def send_callback(mid: str, vtt_path: str, json_path: str, mp4_path: str):
    """发送回调通知"""
    try:
        callback_data = {
            "mid": mid,
            "text_vtt_url": f"https://{storage_bucket}.{storage_server}/{vtt_path}",
            "text_json_url": f"https://{storage_bucket}.{storage_server}/{json_path}",
            "text_video_url": f"https://{storage_bucket}.{storage_server}/{mp4_path}",
        }

        logger.info(f"Sending callback for mid:{mid}")
        response = requests.post(
            callback_url,
            json=callback_data,
            timeout=30
        )

        if response.status_code == 200:
            logger.info(f"Callback succeeded for mid: {mid}")
        else:
            logger.error(
                f"Callback failed for mid: {mid}, "
                f"status: {response.status_code}, "
                f"response: {response.text}"
            )

    except requests.exceptions.Timeout:
        logger.error(f"Callback timeout for mid: {mid}")
    except Exception as e:
        logger.error(f"Callback error for mid: {mid}: {str(e)}", exc_info=True)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)