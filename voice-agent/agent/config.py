"""Centralised, env-driven configuration. Fail fast with a clear message if a
required value is missing — easier than chasing AttributeErrors deep in Pipecat."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _required(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Required env var {key} is not set. See .env.example.")
    return value


@dataclass(frozen=True)
class Config:
    # LiveKit
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    livekit_room: str
    livekit_agent_identity: str

    # Ollama (OpenAI-compatible)
    ollama_base_url: str
    ollama_model: str

    # Kokoro (OpenAI-compatible TTS)
    kokoro_base_url: str
    kokoro_voice: str

    # Whisper
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    whisper_language: str

    # Logging
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            livekit_url=_required("LIVEKIT_URL"),
            livekit_api_key=_required("LIVEKIT_API_KEY"),
            livekit_api_secret=_required("LIVEKIT_API_SECRET"),
            livekit_room=os.environ.get("LIVEKIT_ROOM_NAME", "jarvis-room"),
            livekit_agent_identity=os.environ.get("LIVEKIT_AGENT_IDENTITY", "jarvis-agent"),
            ollama_base_url=_required("OLLAMA_BASE_URL"),
            ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M"),
            kokoro_base_url=_required("KOKORO_BASE_URL"),
            kokoro_voice=os.environ.get("KOKORO_VOICE", "bm_lewis"),
            whisper_model=os.environ.get("WHISPER_MODEL", "medium"),
            whisper_device=os.environ.get("WHISPER_DEVICE", "cuda"),
            whisper_compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "float16"),
            whisper_language=os.environ.get("WHISPER_LANGUAGE", "en"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
