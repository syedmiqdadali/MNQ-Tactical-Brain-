# Jarvis voice agent (Phase 1)

Real-time voice assistant for the MNQ Tactical Brain dashboard. End-to-end open-source stack:
**LiveKit (WebRTC SFU) → Silero VAD → Faster-Whisper STT → Llama 3 8B via Ollama → Kokoro-82M TTS → LiveKit**.

This folder is **not** shipped in the OTA worker zip — it runs on a GPU server (RunPod / Lambda / on-prem).
The dashboard frontend connects via WebRTC; the dashboard backend mints LiveKit session tokens.

## What Phase 1 delivers

A local Docker Compose stack that round-trips voice end-to-end. **Ship gate:** join the LiveKit room
in a browser, say something, hear Llama 3's reply spoken back through Kokoro, total latency < 1s.

No business logic yet — no `run_report`, no Suthra portal, no DB function calls. Phase 3 adds those.

## Prerequisites

- **NVIDIA GPU** with ≥ 12 GB VRAM (Llama 3 8B Q4 ≈ 5 GB, Whisper medium ≈ 2 GB, Kokoro ≈ 0.5 GB,
  with headroom for Pipecat audio buffers)
- **NVIDIA Container Toolkit** installed on the host: <https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html>
- Docker + Docker Compose v2

CPU-only fallback works for plumbing checks but takes ~5s per turn — see `WHISPER_DEVICE=cpu` in `.env.example`.

## Run locally

```bash
cd voice-agent
cp .env.example .env

# Pull the Llama 3 model into the Ollama container's volume (one-time, ~5 GB)
docker compose up -d ollama
docker exec jarvis-ollama ollama pull llama3.1:8b-instruct-q4_K_M

# Bring up the full stack
docker compose up --build

# In another terminal, join the room from a test browser:
# https://meet.livekit.io/?liveKitUrl=ws://localhost:7880&token=<paste-test-token>
# Mint a test token: see "Minting a browser token" below.
```

When everything's healthy you should see:
```
jarvis-livekit  | starting LiveKit server  v1.7.x
jarvis-ollama   | listening on 0.0.0.0:11434
jarvis-kokoro   | Uvicorn running on http://0.0.0.0:8880
jarvis-agent    | Starting Jarvis voice agent | livekit=ws://livekit:7880 ...
jarvis-agent    | Participant joined: jarvis-test-user
```

## Minting a browser token (dev)

For Phase 1 we mint test tokens with the LiveKit CLI so we can join from a browser. In Phase 2,
the Express backend will issue these via `/api/jarvis/session`.

```bash
docker run --rm livekit/livekit-cli token create \
  --api-key devkey --api-secret devsecret_at_least_32_chars_long_string \
  --identity jarvis-test-user --room jarvis-room \
  --join --valid-for 24h
```

Paste the token into <https://meet.livekit.io> with `wss://localhost:7880` (or `ws://` if no TLS).

## Common issues

- **`pipecat.transports.services.livekit` import fails** — Pipecat's import paths drift between
  versions. Check `pip show pipecat-ai` and adjust [agent/pipeline.py](agent/pipeline.py) imports
  in one place. The pinned 0.0.55 in `requirements.txt` matches the paths used here.
- **`could not find tensorrt`** — harmless warning; faster-whisper falls back to CTranslate2 + cuDNN.
- **Whisper hangs at first turn** — model download (1.5–3 GB depending on size). Persists in the
  `whisper-models` volume after first run.
- **No audio out** — confirm Kokoro's `/health` returns 200: `curl http://localhost:8880/health`.

## Going to RunPod (Phase 2 preview)

The same `Dockerfile` runs on RunPod. The only changes:

1. Build + push the image to a registry (or use RunPod's git integration).
2. Replace local `livekit` container with **LiveKit Cloud** or a self-hosted LiveKit on a small
   non-GPU VM in the same region — keeps GPU $$$ focused on inference.
3. Set `LIVEKIT_URL=wss://<cloud-livekit-host>`, regenerate API keys, configure TURN.
4. The Express backend (running on workers' PCs or a central host) mints participant tokens via
   `livekit-server-sdk` (Node) and serves them at `/api/jarvis/session`.

## Code map

| File | Purpose |
|---|---|
| [agent/main.py](agent/main.py) | Entrypoint; boots the pipeline and keeps it alive. |
| [agent/pipeline.py](agent/pipeline.py) | Pipecat pipeline composition: VAD → STT → LLM → TTS. |
| [agent/config.py](agent/config.py) | Env-driven config with fail-fast validation. |
| [Dockerfile](Dockerfile) | CUDA 12.1 + Python 3.11 + Pipecat. |
| [docker-compose.yml](docker-compose.yml) | Local-dev stack: LiveKit + Ollama + Kokoro + agent. |
| [livekit.yaml](livekit.yaml) | LiveKit dev-mode server config. **Replace keys for prod.** |

## License notes

- **Pipecat** — BSD-2-Clause ✅
- **Faster-Whisper** — MIT ✅
- **Llama 3.1** — Meta Llama 3.1 Community License (free for ≤700M MAU; commercial OK at our scale) ✅
- **Kokoro-82M** — Apache-2.0 ✅
- **LiveKit server** — Apache-2.0 ✅

No CPML / non-commercial blockers. Safe to ship.
