from obs_download import download_file
from upload import upload
from method import TranscriptionProcessor

import os
import configparser
import subprocess
from venv import logger
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

config = configparser.ConfigParser()
config.read("/app/easywhisperx/config/config.ini")

download_directory = config["paths"]["download_directory"].replace('"', "").strip()
output_directory = config["paths"]["output_directory"].replace('"', "").strip()
hf_token = config["token"]["hf_token"].replace('"', "").strip()

callback_url = config["callback"]["url"].replace('"', "").strip()
storage_server = config["storage"]["server"].replace('"', "").strip()
storage_bucket = config["storage"]["bucket"].replace('"', "").strip()

app = FastAPI()


class DownloadRequest(BaseModel):
    object_key: str
    bucket_key: str
    mid: str


@app.post("/meeting_translate")
async def meeting_translate(request: DownloadRequest):
    object_key = request.object_key
    bucket_key = request.bucket_key
    mid = request.mid
    download_path = os.path.join(download_directory, object_key.split("/")[-1])

    result = download_file(bucket_key, object_key, download_path)

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["errorMessage"])

    vtt_file = os.path.join(
        output_directory, f"{os.path.splitext(os.path.basename(download_path))[0]}.vtt"
    )
    json_file = os.path.join(
        output_directory, f"{os.path.splitext(os.path.basename(download_path))[0]}.json"
    )

    try:
        whisperx_command = [
            "whisperx",
            "--model",
            "large-v3-turbo",
            "--language",
            "zh",
            "--diarize",
            "--hf_token",
            hf_token,
            download_path,
            "--output_dir",
            output_directory,
            "--initial_prompt",
            "这是一段openEuelr sig组的会议记录。",
            "--compute_type",
            "float32",
            "--task",
            "transcribe",
            "--chunk_size",
            "20",
            "--suppress_tokens",
            "-1",
            "--max_line_width",
            "20",
        ]

        process = subprocess.run(
            whisperx_command, capture_output=True, text=True, shell=False
        )

        if process.returncode != 0:
            raise HTTPException(status_code=500, detail=process.stderr)

        with open(vtt_file, "r", encoding="utf-8") as f:
            transcription_text = f.read()

        formater = TranscriptionProcessor()

        adjusted_transcription = formater.adjust_speaker_numbers(transcription_text)

        with open(vtt_file, "w", encoding="utf-8") as f:
            f.write(adjusted_transcription)

        formater.convert_vtt_to_json(vtt_file)

        vtt_object_key, json_object_key = formater.generate_object_keys(
            mid, object_key, vtt_file, json_file
        )

        upload(
            storage_server, storage_bucket, file_path=vtt_file, objectKey=vtt_object_key
        )
        upload(
            storage_server,
            storage_bucket,
            file_path=json_file,
            objectKey=json_object_key,
        )

        send_callback(mid, vtt_path=vtt_object_key, json_path=json_object_key)

        return {
            "message": "Transcription succeeded",
            "transcription": adjusted_transcription.strip(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def send_callback(mid: str, vtt_path: str, json_path: str):
    """异步发送回调请求"""
    try:
        response = requests.post(
            callback_url,
            json={
                "mid": mid,
                "text_vtt_url": f"https://{storage_bucket}.{storage_server}/{vtt_path}",
                "text_json_url": f"https://{storage_bucket}.{storage_server}/{json_path}",
            },
        )

        if response.status_code == 200:
            logger.info("Callback succeeded: %s", response.json())
        else:
            logger.error(
                "Callback failed for mid: %s, status code: %d, response: %s",
                mid,
                response.status_code,
                response.text,
            )

    except Exception as e:
        logger.error("Callback failed for mid: %s, error: %s", mid, str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
