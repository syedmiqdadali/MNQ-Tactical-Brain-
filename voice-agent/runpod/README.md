# RunPod deployment guide

Phase 2 cloud setup for the Jarvis voice agent. End-to-end checklist below — at the
end you'll have a RunPod pod running that the dashboard can talk to via LiveKit Cloud.

## 1. LiveKit Cloud project

1. Sign up at <https://cloud.livekit.io>. Free tier covers 2,000 connection-minutes/month.
2. Create a project. Note three values from **Settings → Keys**:
   - `URL` — `wss://your-project-name-XXXXXXXX.livekit.cloud`
   - `API Key` — starts with `API…`
   - `API Secret` — long random string

These three values go into both:
- The **agent** (this folder, on RunPod) — set them in the RunPod template env
- The **dashboard backend** — added to `backend/data/jarvis-config.json` per the backend section of [voice-agent/README.md](../README.md)

## 2. Build and push the agent image

RunPod can pull from any container registry. Three options:

### Option A — push to Docker Hub (simplest)

```bash
# from voice-agent/ as the build context
docker build -f runpod/Dockerfile -t YOUR_DOCKERHUB_USER/mnq-jarvis:v0.1 .
docker push YOUR_DOCKERHUB_USER/mnq-jarvis:v0.1
```

### Option B — RunPod's GitHub integration

If `voice-agent/` is in a public repo (or RunPod has access via deploy keys), point a
RunPod template directly at it and they'll build on every push. Works but tightly couples
RunPod to your repo structure.

### Option C — push to GHCR (free, private)

```bash
echo $GITHUB_PAT | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin
docker build -f runpod/Dockerfile -t ghcr.io/YOUR_GITHUB_USER/mnq-jarvis:v0.1 .
docker push ghcr.io/YOUR_GITHUB_USER/mnq-jarvis:v0.1
```

## 3. Create the RunPod template

In <https://www.runpod.io/console/user/templates> click **New Template**:

| Field | Value |
|---|---|
| Template Name | `mnq-jarvis-agent` |
| Container Image | `YOUR_DOCKERHUB_USER/mnq-jarvis:v0.1` (or the GHCR equivalent) |
| Container Disk | **20 GB** (image + buffers, no models) |
| Volume Disk | **30 GB** (persists across pod restarts; holds Ollama models) |
| Volume Mount Path | `/workspace` |
| Expose HTTP Ports | *(none — agent doesn't expose HTTP)* |
| Expose TCP Ports | *(none — agent only makes outbound WebSocket to LiveKit)* |
| Container Start Command | leave blank — Dockerfile ENTRYPOINT handles it |

**Environment Variables** (paste exactly):

```
LIVEKIT_URL=wss://your-project-name-XXXXXXXX.livekit.cloud
LIVEKIT_API_KEY=APIxxxxxxxxxxxxxxx
LIVEKIT_API_SECRET=long-random-secret-from-livekit-cloud
LIVEKIT_ROOM_NAME=jarvis-room
LIVEKIT_AGENT_IDENTITY=jarvis-agent
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
OLLAMA_MODEL=llama3.1:8b-instruct-q4_K_M
KOKORO_BASE_URL=http://127.0.0.1:8880/v1
KOKORO_VOICE=bm_lewis
WHISPER_MODEL=medium
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16
WHISPER_LANGUAGE=en
LOG_LEVEL=INFO
```

## 4. Deploy a pod from the template

In <https://www.runpod.io/console/pods> click **+ Deploy** → **Pods** → **Pick GPU**.

Recommended GPU for Phase 2 MVP (1–2 concurrent sessions):
- **RTX 4090 24 GB** — ~$0.40/hr spot, ~$0.69/hr on-demand
- **RTX A5000 24 GB** — comparable
- **A10 24 GB** — slightly slower but cheaper at ~$0.50/hr on-demand

For the full 10 concurrent sessions target:
- **A6000 48 GB** — ~$0.79/hr on-demand
- **A100 40 GB** — overkill, more expensive

Pick a region close to your dispatchers (US-East-1 or EU-CE-1 if Pakistan-based).
Select your template. Deploy. First boot pulls the 5 GB Llama model — takes ~3 minutes.
Subsequent boots are seconds.

Watch the pod's **Logs** tab. Healthy startup ends with:

```
[start.sh] $MODEL already cached — skipping pull
[start.sh] Handing off to supervisord
2026-04-26 12:34:56 INFO     Starting Jarvis voice agent | livekit=wss://… room=jarvis-room llm=llama3.1:… tts=bm_lewis
2026-04-26 12:34:58 INFO     Connected to LiveKit room jarvis-room as jarvis-agent
```

If Whisper model downloads happen on the first turn (~1.5 GB) you'll see them in the
logs too — they persist on the `/workspace` volume after that.

## 5. Test it

From any browser, mint a token via the LiveKit CLI or web playground:

<https://meet.livekit.io> → paste your `wss://…` URL and a token.

Easiest token-mint for a one-off test: <https://livekit.io/get-token-test> (their hosted
helper) or via CLI:

```bash
livekit-cli token create \
  --api-key APIxxxxxxxxxxxxxxx \
  --api-secret long-random-secret-from-livekit-cloud \
  --identity test-dispatcher \
  --room jarvis-room \
  --join --valid-for 1h
```

Join the room. The agent (`jarvis-agent`) should be the other participant. Speak —
you'll hear Jarvis reply through Kokoro. **Phase 1 ship gate met when this works.**

In Phase 2.5 (next step), the dashboard will mint these tokens automatically via
`/api/jarvis/session` so dispatchers don't touch the CLI.

## 6. Cost notes

- **GPU pod** running 24/7: 24 GB GPU at ~$0.50/hr ≈ $360/month. Use **Spot** pricing
  (~50% off) for non-production, or stop the pod when not in active use.
- **LiveKit Cloud**: free for first 2,000 conn-min/month, then $0.0015/conn-min
  (~$0.09/hour per active dispatcher). At 10 concurrent dispatchers 8 hours/day,
  ≈ $215/month.
- **Total Phase 2 burn**: ~$575/month if always-on. Cut to <$100/month by stopping the
  pod outside business hours.

## 7. Updating the agent

Build a new image with a new tag, push, then in RunPod **edit the pod → Image →** new
tag → restart. The `/workspace` volume keeps the Llama and Whisper models so restart
is fast (no re-download).

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Pod stays in "Initializing" >5 min on first boot | Llama 3 model pull | Watch logs; first pull is slow but caches afterwards |
| `RuntimeError: Required env var LIVEKIT_API_KEY is not set` | Template env not propagated | RunPod sometimes requires a pod restart after template edit |
| Whisper hangs at first utterance | Model download | One-time, 1.5 GB for `medium`, 3 GB for `large-v3` |
| Agent reconnects every ~30s | LiveKit ws disconnect | Check the URL uses `wss://` not `ws://` for cloud |
| `kokoro` process keeps restarting | Image's CMD path changed in a kokoro-fastapi update | Verify `api.src.main:app` is still the right module path; update [supervisord.conf](supervisord.conf) |
| `cuda out of memory` | GPU too small or session overhead too high | Drop to `WHISPER_MODEL=small` or upsize the pod GPU |
