from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import re
import os
import configparser

from .obs_download import download_file

config = configparser.ConfigParser()
config.read("/app/config.ini")

download_directory = config["paths"]["download_directory"].replace('"', "").strip()
output_directory = config["paths"]["output_directory"].replace('"', "").strip()
hf_token = config["token"]["hf_token"].replace('"', "").strip()

app = FastAPI()


class DownloadRequest(BaseModel):
    object_key: str
    bucket_key: str


@app.post("/meeting_translate")
async def meeting_translate(request: DownloadRequest):
    object_key = request.object_key
    bucket_key = request.bucket_key
    download_path = os.path.join(download_directory, object_key.split("/")[-1])

    result = download_file(bucket_key, object_key, download_path)

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["errorMessage"])

    output_file = os.path.join(
        output_directory, f"{os.path.splitext(os.path.basename(download_path))[0]}.srt"
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
        ]

        process = subprocess.run(whisperx_command, capture_output=True, text=True)

        if process.returncode != 0:
            raise HTTPException(status_code=500, detail=process.stderr)

        with open(output_file, "r", encoding="utf-8") as f:
            transcription_text = f.read()

        adjusted_transcription = adjust_speaker_numbers(transcription_text)

        return {
            "message": "Transcription succeeded",
            "transcription": adjusted_transcription.strip(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
