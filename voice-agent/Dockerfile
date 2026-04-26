# CUDA 12.1 + cuDNN runtime — matches faster-whisper's prebuilt CTranslate2 wheels.
# Switch to nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04 for prod; -devel only needed if we
# end up building wheels from source.
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3-pip \
        ffmpeg \
        ca-certificates \
        curl \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for Docker layer caching
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

COPY agent/ ./agent/

# faster-whisper downloads model weights to this dir on first use; mount as a volume
# in compose so we don't re-download on every container restart.
ENV HF_HOME=/models/huggingface \
    TRANSFORMERS_CACHE=/models/huggingface \
    XDG_CACHE_HOME=/models/cache

ENTRYPOINT ["python", "-m", "agent.main"]
