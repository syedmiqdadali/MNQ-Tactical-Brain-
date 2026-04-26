"""The Pipecat pipeline.

Audio path: LiveKit input → Silero VAD → Faster-Whisper STT → Llama 3 (Ollama) → Kokoro TTS → LiveKit output.

For Phase 1 we keep this minimal — no function calling, no Suthra portal RAG, no
business logic. Goal is to prove the round-trip latency budget before adding tools.

Pipecat API surface evolves between versions. If imports break after a `pip install -U`,
the most likely fix is renaming the `pipecat.transports.services.livekit` path —
check pipecat-ai's changelog and update the imports here in one place.
"""
from __future__ import annotations

from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import (
    OpenAILLMContext,
    OpenAILLMContextFrame,
)
from pipecat.services.openai import OpenAILLMService
from pipecat.services.whisper import WhisperSTTService
from pipecat.transports.services.livekit import LiveKitParams, LiveKitTransport
from pipecat.vad.silero import SileroVADAnalyzer

from .config import Config
from .services.kokoro_tts import KokoroTTSService


SYSTEM_PROMPT = (
    "You are J.A.R.V.I.S., the voice assistant for the MNQ Penalties Automation "
    "platform. You speak with a crisp, professional, slightly British tone. "
    "Address the user as 'Sir' when appropriate. Keep replies short — one or two "
    "sentences — because the user hears them spoken aloud. If the user's speech "
    "looks transcribed mid-sentence, ask them to finish their thought rather than "
    "guessing."
)


def build_pipeline(cfg: Config) -> tuple[PipelineTask, PipelineRunner]:
    transport = LiveKitTransport(
        url=cfg.livekit_url,
        token=_mint_agent_token(cfg),
        room_name=cfg.livekit_room,
        params=LiveKitParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            # Pipecat will hold the assistant's turn until VAD confirms the user
            # has stopped speaking — this is what eliminates barge-in glitches.
            vad_audio_passthrough=True,
        ),
    )

    stt = WhisperSTTService(
        # Pipecat's WhisperSTTService accepts either Model enum or a HuggingFace
        # repo string; faster-whisper resolves both. Strings like "medium" /
        # "small" / "large-v3" / "Systran/faster-distil-whisper-medium.en" all work.
        model=cfg.whisper_model,
        device=cfg.whisper_device,
        compute_type=cfg.whisper_compute_type,
        # Streaming partials are emitted as soon as Whisper has a stable hypothesis.
        # We feed only finals to the LLM to avoid double-responding.
        no_speech_prob=0.4,
        language=cfg.whisper_language if cfg.whisper_language != "auto" else None,
    )

    # Ollama exposes /v1/chat/completions. Pipecat's OpenAILLMService is a perfect fit;
    # the api_key is unused by Ollama but the SDK requires a non-empty string.
    llm = OpenAILLMService(
        api_key="ollama-local",
        base_url=cfg.ollama_base_url,
        model=cfg.ollama_model,
    )

    # In-process Kokoro (no HTTP layer). Voice ID's first letter must match
    # lang_code: bm_/bf_ → 'b' (British), am_/af_ → 'a' (American), etc.
    tts = KokoroTTSService(
        voice=cfg.kokoro_voice,
        lang_code=cfg.kokoro_voice[0] if cfg.kokoro_voice else "b",
        sample_rate=24000,
    )

    context = OpenAILLMContext(messages=[{"role": "system", "content": SYSTEM_PROMPT}])
    context_aggregator = llm.create_context_aggregator(context)

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        PipelineParams(
            allow_interruptions=True,
            # If the user starts talking while Jarvis is mid-sentence, abort the TTS.
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_first_participant_joined")
    async def _greet_on_join(_transport, participant):
        logger.info(f"Participant joined: {participant['identity']}")
        await task.queue_frames([OpenAILLMContextFrame(context)])

    @transport.event_handler("on_participant_left")
    async def _on_left(_transport, participant, _reason):
        logger.info(f"Participant left: {participant['identity']}")

    return task, PipelineRunner()


def _mint_agent_token(cfg: Config) -> str:
    """Mint a LiveKit JWT for the agent identity. In Phase 2 the Express backend
    will mint these for browsers; for now the agent mints its own."""
    # Imported here so this module is importable without livekit-api at parse time —
    # makes unit-testing the imports above easier.
    from livekit import api as livekit_api

    grants = livekit_api.VideoGrants(
        room_join=True,
        room=cfg.livekit_room,
        can_publish=True,
        can_subscribe=True,
    )
    token = (
        livekit_api.AccessToken(cfg.livekit_api_key, cfg.livekit_api_secret)
        .with_identity(cfg.livekit_agent_identity)
        .with_name("J.A.R.V.I.S.")
        .with_grants(grants)
        .to_jwt()
    )
    return token
