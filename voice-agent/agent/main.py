"""Entrypoint. Boots the Pipecat pipeline and keeps it alive."""
from __future__ import annotations

import asyncio
import sys

from loguru import logger

from .config import Config
from .pipeline import build_pipeline


async def _amain() -> int:
    cfg = Config.from_env()

    # Replace loguru's default handler with one driven by LOG_LEVEL
    logger.remove()
    logger.add(sys.stderr, level=cfg.log_level)
    logger.info(
        "Starting Jarvis voice agent | livekit={livekit} room={room} llm={llm} tts={voice}",
        livekit=cfg.livekit_url,
        room=cfg.livekit_room,
        llm=cfg.ollama_model,
        voice=cfg.kokoro_voice,
    )

    task, runner = build_pipeline(cfg)
    try:
        await runner.run(task)
    except KeyboardInterrupt:
        logger.info("SIGINT received, shutting down")
    except Exception:
        logger.exception("Pipeline crashed")
        return 1
    return 0


def main() -> None:
    exit_code = asyncio.run(_amain())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
