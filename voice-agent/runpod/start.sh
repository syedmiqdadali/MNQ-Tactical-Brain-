#!/usr/bin/env bash
# RunPod entrypoint. Pre-pulls the Llama 3 model into the persistent volume on first
# boot so subsequent restarts (or pod re-creations on the same volume) are fast.
# Then hands off to supervisord which manages the three long-running services.
set -euo pipefail

# ─── Required env (LiveKit Cloud creds, set in the RunPod template) ──────────
: "${LIVEKIT_URL:?LIVEKIT_URL must be set (wss://your-project.livekit.cloud)}"
: "${LIVEKIT_API_KEY:?LIVEKIT_API_KEY must be set from your LiveKit Cloud project}"
: "${LIVEKIT_API_SECRET:?LIVEKIT_API_SECRET must be set from your LiveKit Cloud project}"

# ─── Volume layout (RunPod mounts persistent disk at /workspace) ─────────────
# Models live on the volume so we don't re-pull 5+ GB on every pod restart.
mkdir -p /workspace/ollama-models /workspace/huggingface
export OLLAMA_MODELS=/workspace/ollama-models
export HF_HOME=/workspace/huggingface
export TRANSFORMERS_CACHE=/workspace/huggingface

# ─── One-time model pull ─────────────────────────────────────────────────────
# Start ollama in background just for the pull, then stop it so supervisord can
# own the long-running daemon cleanly.
MODEL="${OLLAMA_MODEL_NAME:-llama3.1:8b-instruct-q4_K_M}"

echo "[start.sh] Booting Ollama temporarily to ensure $MODEL is present..."
/usr/local/bin/ollama serve &
OLLAMA_PID=$!
trap 'kill $OLLAMA_PID 2>/dev/null || true' EXIT

# Wait up to 60 s for the API to become reachable
for _ in $(seq 1 60); do
  if curl -sf http://127.0.0.1:11434/api/version > /dev/null; then
    break
  fi
  sleep 1
done

if /usr/local/bin/ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -q "^${MODEL}$"; then
  echo "[start.sh] $MODEL already cached — skipping pull"
else
  echo "[start.sh] Pulling $MODEL (one-time, ~5 GB)..."
  /usr/local/bin/ollama pull "$MODEL"
fi

# Stop the bootstrap ollama. supervisord will restart it as a managed service.
kill $OLLAMA_PID 2>/dev/null || true
wait $OLLAMA_PID 2>/dev/null || true
trap - EXIT

echo "[start.sh] Handing off to supervisord"
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/voice-agent.conf -n
