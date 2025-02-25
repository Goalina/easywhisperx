FROM nvcr.io/nvidia/cuda:12.6.3-devel-ubuntu22.04

WORKDIR /app

ENV HF_ENDPOINT=https://hf-mirror.com

EXPOSE 8000

RUN apt-get update && \
    apt-get install -y git python3 python3-pip ffmpeg libcudnn8 libcudnn8-dev && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /root/.pip && \
    echo "[global]" > /root/.pip/pip.conf && \
    echo "index-url = https://pypi.tuna.tsinghua.edu.cn/simple" >> /root/.pip/pip.conf

RUN pip install whisperx

RUN git clone https://github.com/opensourceways/easywhisperx.git

RUN pip install fastapi uvicorn pydantic

RUN pip install esdk-obs-python --trusted-host pypi.org

CMD ["uvicorn", "easywhisperx.src.service:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]