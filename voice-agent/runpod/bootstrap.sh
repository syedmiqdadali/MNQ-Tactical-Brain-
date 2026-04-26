#!/usr/bin/env bash
# bootstrap.sh — One-command setup for a vanilla RunPod GPU pod.
#
# Use this when you DON'T want to build a custom Docker image. Boot a generic
# pod (e.g. runpod/pytorch:2.1.0-py3.10-cuda12.1.1-devel-ubuntu22.04), open the
# web terminal, paste this command:
#
#   curl -fsSL https://raw.githubusercontent.com/syedmiqdadali/MNQ-Tactical-Brain-/voice-agent/voice-agent/runpod/bootstrap.sh | bash
#
# The script installs Ollama, pulls Llama 3, sets up Kokoro-FastAPI and our
# Pipecat agent, and wires them together via supervisord. Total time on first
# run: ~5 min for the model pull + ~2 min for deps.
set -euo pipefail

# ─── Required env (set in RunPod template) ────────────────────────────────────
: "${LIVEKIT_URL:?LIVEKIT_URL must be set in the pod env (wss://....livekit.cloud)}"
: "${LIVEKIT_API_KEY:?LIVEKIT_API_KEY must be set in the pod env}"
: "${LIVEKIT_API_SECRET:?LIVEKIT_API_SECRET must be set in the pod env}"

REPO_DIR=/workspace/mnq-voice-agent
MODEL="${OLLAMA_MODEL:-llama3.1:8b-instruct-q4_K_M}"

echo "═══════════════════════════════════════════════════════════════════════════"
echo " MNQ Jarvis voice agent — bootstrap"
echo "═══════════════════════════════════════════════════════════════════════════"
echo " LiveKit URL : $LIVEKIT_URL"
echo " Model       : $MODEL"
echo " Working dir : $REPO_DIR"
echo "═══════════════════════════════════════════════════════════════════════════"

# ─── Step 1: System packages ──────────────────────────────────────────────────
echo ""
echo "[1/7] Installing apt packages (supervisor, ffmpeg, git)..."
apt-get update -qq
apt-get install -y --no-install-recommends supervisor ffmpeg git curl ca-certificates > /dev/null

# ─── Step 2: Clone (or refresh) the agent source ──────────────────────────────
echo ""
echo "[2/7] Cloning voice-agent source..."
if [ -d "$REPO_DIR/.git" ]; then
  echo "  refresh existing checkout"
  git -C "$REPO_DIR" fetch --quiet origin voice-agent
  git -C "$REPO_DIR" reset --hard origin/voice-agent --quiet
else
  rm -rf "$REPO_DIR"
  git clone --depth 1 --branch voice-agent \
    https://github.com/syedmiqdadali/MNQ-Tactical-Brain-.git "$REPO_DIR" --quiet
fi
cd "$REPO_DIR/voice-agent"

# ─── Step 3: Install Ollama (LLM daemon) ──────────────────────────────────────
echo ""
echo "[3/7] Installing Ollama..."
if ! command -v ollama > /dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh > /dev/null
fi

# Persist Ollama models on the pod's volume so they survive restarts
mkdir -p /workspace/ollama-models /workspace/huggingface
export OLLAMA_MODELS=/workspace/ollama-models

# Boot a temporary Ollama daemon to pull the model, then stop it
echo "  starting temporary daemon for model pull..."
ollama serve > /workspace/ollama-bootstrap.log 2>&1 &
OLLAMA_PID=$!
trap 'kill $OLLAMA_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  if curl -sf http://127.0.0.1:11434/api/version > /dev/null; then break; fi
  sleep 1
done

if ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -q "^${MODEL}$"; then
  echo "  $MODEL already cached — skipping pull"
else
  echo "  pulling $MODEL (one-time, ~5 GB; may take 3–5 min)..."
  ollama pull "$MODEL"
fi

kill $OLLAMA_PID 2>/dev/null || true
wait $OLLAMA_PID 2>/dev/null || true
trap - EXIT

# ─── Step 4: Install Kokoro-FastAPI from source ───────────────────────────────
echo ""
echo "[4/7] Installing Kokoro-FastAPI..."
if [ ! -d /workspace/kokoro-fastapi ]; then
  git clone --depth 1 https://github.com/remsky/Kokoro-FastAPI.git /workspace/kokoro-fastapi --quiet
fi
cd /workspace/kokoro-fastapi
pip install --quiet -e .

# ─── Step 5: Install agent Python deps ────────────────────────────────────────
echo ""
echo "[5/7] Installing agent Python deps (this is the slow step, ~3 min)..."
cd "$REPO_DIR/voice-agent"
pip install --quiet -r requirements.txt

# ─── Step 6: Generate supervisord config ──────────────────────────────────────
echo ""
echo "[6/7] Writing supervisord config..."
cat > /etc/supervisor/conf.d/jarvis.conf <<EOF
[supervisord]
nodaemon=true
user=root
logfile=/workspace/supervisord.log
pidfile=/var/run/supervisord.pid

[program:ollama]
command=/usr/local/bin/ollama serve
autostart=true
autorestart=true
priority=10
stdout_logfile=/workspace/ollama.log
stdout_logfile_maxbytes=20MB
stderr_logfile=/workspace/ollama.err
stderr_logfile_maxbytes=20MB
environment=OLLAMA_MODELS="/workspace/ollama-models",OLLAMA_HOST="127.0.0.1:11434"

[program:kokoro]
command=python -m uvicorn api.src.main:app --host 0.0.0.0 --port 8880
directory=/workspace/kokoro-fastapi
autostart=true
autorestart=true
priority=20
stdout_logfile=/workspace/kokoro.log
stdout_logfile_maxbytes=20MB
stderr_logfile=/workspace/kokoro.err
stderr_logfile_maxbytes=20MB

[program:agent]
command=python -m agent.main
directory=$REPO_DIR/voice-agent
autostart=true
autorestart=true
startretries=10
startsecs=15
priority=30
stdout_logfile=/workspace/agent.log
stdout_logfile_maxbytes=20MB
stderr_logfile=/workspace/agent.err
stderr_logfile_maxbytes=20MB
environment=LIVEKIT_URL="$LIVEKIT_URL",LIVEKIT_API_KEY="$LIVEKIT_API_KEY",LIVEKIT_API_SECRET="$LIVEKIT_API_SECRET",LIVEKIT_ROOM_NAME="${LIVEKIT_ROOM_NAME:-jarvis-room}",LIVEKIT_AGENT_IDENTITY="${LIVEKIT_AGENT_IDENTITY:-jarvis-agent}",OLLAMA_BASE_URL="http://127.0.0.1:11434/v1",OLLAMA_MODEL="$MODEL",KOKORO_BASE_URL="http://127.0.0.1:8880/v1",KOKORO_VOICE="${KOKORO_VOICE:-bm_lewis}",WHISPER_MODEL="${WHISPER_MODEL:-medium}",WHISPER_DEVICE="cuda",WHISPER_COMPUTE_TYPE="float16",WHISPER_LANGUAGE="${WHISPER_LANGUAGE:-en}",LOG_LEVEL="INFO",HF_HOME="/workspace/huggingface"
EOF

# ─── Step 7: Launch ───────────────────────────────────────────────────────────
echo ""
echo "[7/7] Starting supervisord (foreground — Ctrl+C to stop)..."
echo ""
echo "  Logs are streamed to /workspace/{ollama,kokoro,agent}.{log,err}"
echo "  Tail the agent in another terminal: tail -f /workspace/agent.log"
echo ""
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/jarvis.conf -n
