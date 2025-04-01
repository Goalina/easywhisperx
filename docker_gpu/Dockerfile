FROM nvcr.io/nvidia/cuda:12.6.3-devel-ubuntu22.04

# 设置非root用户环境
ARG APP_USER=appuser
ARG APP_UID=1000
ARG APP_GID=1000
ENV HOME=/home/$APP_USER
ENV HF_ENDPOINT=https://hf-mirror.com
ENV PATH=$HOME/.local/bin:$PATH

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
    git curl vim net-tools python3 python3-pip ffmpeg libcudnn8 libcudnn8-dev && \
    rm -rf /var/lib/apt/lists/*

# 切换到非root用户
USER $APP_USER

# 配置pip镜像（用户级配置）
RUN mkdir -p $HOME/.pip && \
    echo "[global]" > $HOME/.pip/pip.conf && \
    echo "index-url = https://pypi.tuna.tsinghua.edu.cn/simple" >> $HOME/.pip/pip.conf && \
    chown -R $APP_USER:$APP_USER $HOME/.pip

# 安装Python依赖
RUN pip install whisperx fastapi uvicorn pydantic esdk-obs-python

# 克隆代码
ARG GIT_USER
ARG GIT_PASS
RUN git clone https://${GIT_USER}:${GIT_PASS}@github.com/opensourceways/easywhisperx.git && \
    chown -R $APP_USER:$APP_USER /app/easywhisperx
RUN cp /app/easywhisperx/src/transcribe.py /home/appuser/.local/lib/python3.10/site-packages/whisperx/transcribe.py

EXPOSE 8000

CMD ["uvicorn", "easywhisperx.src.service:app", "--host", "0.0.0.0", "--port", "8000"]