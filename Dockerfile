FROM nvcr.io/nvidia/cuda:12.1.1-devel-ubuntu22.04  # 使用与可运行环境匹配的CUDA 12.1

# 设置非root用户环境
ARG APP_USER=appuser
ARG APP_UID=1000
ARG APP_GID=1000
ENV HOME=/home/$APP_USER
ENV HF_ENDPOINT=https://hf-mirror.com
ENV PATH=$HOME/.local/bin:$PATH
ENV LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64:$LD_LIBRARY_PATH

# 创建非特权用户和组
RUN groupadd -g $APP_GID $APP_USER && \
    useradd -u $APP_UID -g $APP_GID -d $HOME -s /bin/bash $APP_USER && \
    mkdir -p $HOME && \
    chown $APP_USER:$APP_USER $HOME

WORKDIR /app
RUN chown $APP_USER:$APP_USER /app

# 安装系统依赖（root阶段）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git curl vim net-tools python3 python3-pip ffmpeg \
    libcudnn8=8.9.2.26-1+cuda12.1 \
    libcudnn8-dev=8.9.2.26-1+cuda12.1 && \
    rm -rf /var/lib/apt/lists/*

# 切换到非root用户
USER $APP_USER

# 配置pip镜像（用户级配置）
RUN mkdir -p $HOME/.pip && \
    echo "[global]" > $HOME/.pip/pip.conf && \
    echo "index-url = https://pypi.tuna.tsinghua.edu.cn/simple" >> $HOME/.pip/pip.conf && \
    chown -R $APP_USER:$APP_USER $HOME/.pip

# 安装Python依赖（严格版本控制）
RUN pip install \
    torch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0 \
    --index-url https://download.pytorch.org/whl/cu121

RUN pip install \
    numpy==1.26.4 \
    transformers==4.44.2 \
    whisperx==3.3.2 \
    fastapi==0.110.3 \
    uvicorn==0.30.1 \
    pydantic==2.7.3 \
    esdk-obs-python==3.24.12 \
    aiofiles==23.2.1 \
    soundfile==0.12.1 \
    protobuf==5.27.1 \
    tokenizers==0.19.1

# 创建目标目录并复制本地文件
RUN mkdir -p /app/easywhisperx
COPY --chown=$APP_USER:$APP_USER . /app/easywhisperx/

RUN cp /app/easywhisperx/src/transcribe.py /home/appuser/.local/lib/python3.10/site-packages/whisperx/transcribe.py

EXPOSE 8000

CMD ["uvicorn", "easywhisperx.src.service:app", "--host", "0.0.0.0", "--port", "8000"]