# RunPod single-pod image. Three processes managed by supervisord:
#   - ollama serve         (LLM)
#   - kokoro-fastapi       (TTS, baked into the kokoro-fastapi-gpu base image)
#   - agent (Pipecat)      (orchestrator + Whisper STT)
#
# Build context is voice-agent/ (parent dir):
#   docker build -f voice-agent/runpod/Dockerfile -t mnq-jarvis:latest voice-agent/
#
# Runs against LiveKit Cloud — no SFU container needed.
FROM ghcr.io/remsky/kokoro-fastapi-gpu:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OLLAMA_MODELS=/workspace/ollama-models \
    HF_HOME=/workspace/huggingface \
    TRANSFORMERS_CACHE=/workspace/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
        supervisor curl ca-certificates \
    && curl -fsSL https://ollama.com/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*

# Install agent deps in a separate dir so we don't clash with kokoro's site-packages
WORKDIR /opt/agent
COPY requirements.txt .
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

COPY agent/ ./agent/
COPY runpod/supervisord.conf /etc/supervisor/conf.d/voice-agent.conf
COPY runpod/start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

# 11434 = Ollama, 8880 = Kokoro. Neither needs to be exposed publicly on RunPod —
# the agent talks to them on localhost. Listed only for local-dev parity.
EXPOSE 11434 8880

ENTRYPOINT ["/usr/local/bin/start.sh"]
