"""Deepgram voice: Aura-2 speaks the detective's lines, Flux transcribes the player.

Only speech-to-text and text-to-speech — the game logic stays in game.py.
"""

import asyncio
import base64
import logging
from collections.abc import Awaitable, Callable

from deepgram import AsyncDeepgramClient

from .config import Settings

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000  # the renderer sends 16 kHz mono linear16
TTS_TIMEOUT_S = 8.0


class Voice:
    def __init__(self, settings: Settings):
        self._dg = AsyncDeepgramClient(api_key=settings.deepgram_api_key.get_secret_value())
        self._s = settings

    async def speak(self, text: str) -> str | None:
        """Text -> base64 mp3, or None if Deepgram is unavailable (game continues silently)."""
        async def generate() -> bytes:
            chunks = self._dg.speak.v1.audio.generate(
                text=text, model=self._s.dg_tts_model, mip_opt_out=self._s.dg_mip_opt_out
            )
            return b"".join([c async for c in chunks])

        try:
            return base64.b64encode(await asyncio.wait_for(generate(), TTS_TIMEOUT_S)).decode()
        except Exception:
            log.exception("TTS failed")
            return None

    def listener(self, on_partial: Callable[[str], Awaitable[None]], on_final: Callable[[str], Awaitable[None]]) -> "Listener":
        return Listener(self._dg, self._s, on_partial, on_final)


class Listener:
    """One Flux session per answer: feed() mic audio, on_final fires once at end of turn."""

    def __init__(self, dg: AsyncDeepgramClient, s: Settings, on_partial, on_final):
        self._dg, self._s = dg, s
        self._on_partial, self._on_final = on_partial, on_final
        self._audio: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
        self._task = asyncio.create_task(self._run())

    def feed(self, chunk: bytes) -> None:
        if not self._task.done():
            try:
                self._audio.put_nowait(chunk)
            except asyncio.QueueFull:  # network stalled: drop audio rather than lag
                pass

    def close(self) -> None:
        self._task.cancel()

    @property
    def done(self) -> bool:
        return self._task.done()

    async def _run(self) -> None:
        try:
            async with self._dg.listen.v2.connect(
                model="flux-general-en",
                encoding="linear16",
                sample_rate=str(SAMPLE_RATE),
                eot_threshold=str(self._s.dg_eot_threshold),
                eot_timeout_ms=str(self._s.dg_eot_timeout_ms),
                mip_opt_out=str(self._s.dg_mip_opt_out).lower(),
            ) as sock:
                pump = asyncio.create_task(self._pump(sock))
                try:
                    async for msg in sock:
                        # SDK 7.4 yields plain dicts for Flux events.
                        m = msg if isinstance(msg, dict) else getattr(msg, "__dict__", {})
                        if m.get("type") == "TurnInfo":
                            text = (m.get("transcript") or "").strip()
                            if m.get("event") == "EndOfTurn" and text:
                                await self._on_final(text[:300])
                                return
                            if text:
                                await self._on_partial(text[:300])
                        elif m.get("type") in ("Error", "FatalError"):
                            log.error("Flux error: %s", m)
                            return
                finally:
                    pump.cancel()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Speech-to-text session failed")

    async def _pump(self, sock) -> None:
        while (chunk := await self._audio.get()) is not None:
            await sock.send_media(chunk)
