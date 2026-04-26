"""In-process Kokoro TTS for Pipecat.

Uses the `kokoro` Python library directly instead of going through kokoro-fastapi's
HTTP layer. This:
  - Eliminates the HTTP round-trip per chunk (saves ~30–80 ms TTFB).
  - Avoids kokoro-fastapi's hardcoded `/app/...` paths and brittle init flow.
  - Auto-downloads model weights from HuggingFace (hexgrad/Kokoro-82M) on first
    use; subsequent runs load from $HF_HOME (set to /workspace/huggingface in
    the RunPod pod so it persists across restarts).

Requires PyTorch >= 2.4 — older PyTorch makes transformers fall back to "no
PyTorch" mode and Kokoro init silently aborts. Bootstrap upgrades torch first.
"""
from __future__ import annotations

from typing import AsyncGenerator, Optional

import numpy as np
from loguru import logger

from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.ai_services import TTSService


class KokoroTTSService(TTSService):
    """Streams Kokoro-82M synthesised audio chunks into the Pipecat pipeline.

    Args:
        voice: Kokoro voice ID. British male = bm_lewis / bm_george / bm_daniel.
            British female = bf_emma / bf_alice / bf_lily / bf_isabella.
            American female = af_heart (default upstream), af_bella, af_nicole.
            See `KPipeline.list_voices()` for the full set (~70 voices).
        lang_code: Kokoro language hint. Must match the voice's first letter.
            'b' = British English, 'a' = American, 'j' = Japanese, etc.
        speed: 1.0 = normal. <1.0 slower, >1.0 faster.
        sample_rate: Output PCM rate. Kokoro is natively 24 kHz; resampling here
            is wasted work — keep at 24000.
    """

    def __init__(
        self,
        *,
        voice: str = "bm_lewis",
        lang_code: str = "b",
        speed: float = 1.0,
        sample_rate: int = 24000,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._voice = voice
        self._lang_code = lang_code
        self._speed = speed
        self._sample_rate = sample_rate
        self._pipeline: Optional[object] = None  # KPipeline lazily imported

    def can_generate_metrics(self) -> bool:
        return True

    async def _ensure_pipeline(self) -> None:
        """Lazy-init the KPipeline. First call downloads the model (~330 MB)
        from HuggingFace and warms it onto the GPU."""
        if self._pipeline is not None:
            return
        # Imported lazily so module import never fails when kokoro isn't installed
        # (e.g. during unit tests on the dev box).
        from kokoro import KPipeline

        logger.info(
            "Initialising Kokoro KPipeline | lang={lang} voice={voice} sample_rate={sr}",
            lang=self._lang_code,
            voice=self._voice,
            sr=self._sample_rate,
        )
        self._pipeline = KPipeline(lang_code=self._lang_code)

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        """Pipecat entrypoint. Yields one TTSStartedFrame, then 1+ audio chunks
        (one per text segment Kokoro splits on), then a TTSStoppedFrame."""
        await self._ensure_pipeline()
        await self.start_ttfb_metrics()
        yield TTSStartedFrame()

        try:
            assert self._pipeline is not None
            generator = self._pipeline(
                text,
                voice=self._voice,
                speed=self._speed,
            )

            ttfb_recorded = False
            for _graphemes, _phonemes, audio in generator:
                # Kokoro returns float32 in [-1.0, 1.0]; LiveKit publishes int16 PCM.
                if hasattr(audio, "detach"):
                    # torch.Tensor → numpy
                    audio = audio.detach().cpu().numpy()
                pcm16 = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)

                if not ttfb_recorded:
                    await self.stop_ttfb_metrics()
                    ttfb_recorded = True

                yield TTSAudioRawFrame(
                    audio=pcm16.tobytes(),
                    sample_rate=self._sample_rate,
                    num_channels=1,
                )
        except Exception as e:
            logger.exception("Kokoro TTS failed for text: {!r}", text[:80])
            yield ErrorFrame(error=f"Kokoro TTS error: {e}")
        finally:
            yield TTSStoppedFrame()
