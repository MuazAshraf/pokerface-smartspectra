import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, status
from openai import AsyncOpenAI
from pydantic import ValidationError

from .config import settings
from .detective import Detective
from .game import Game, Phase
from .protocol import Answer, ClientMessage
from .voice import Listener, Voice

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

MAX_AUDIO_CHUNK = 32_000  # bytes; the renderer sends ~640-byte (20 ms) chunks


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
    app.state.detective = Detective(client, settings.openai_model, settings.llm_timeout_s)
    app.state.voice = Voice(settings) if settings.deepgram_api_key else None
    if app.state.voice is None:
        log.warning("DEEPGRAM_API_KEY not set: voice disabled, text input only")
    yield
    await client.close()


app = FastAPI(title="Poker Face backend", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.websocket("/ws")
async def interrogation(ws: WebSocket) -> None:
    if ws.headers.get("origin") not in settings.allowed_origins:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()

    voice: Voice | None = app.state.voice
    game = Game(app.state.detective, ws.send_json, speak=voice.speak if voice else None)
    listener: Listener | None = None
    listening_for = 0  # question index the current speech-to-text session belongs to

    async def on_partial(text: str) -> None:
        await ws.send_json({"type": "transcript", "text": text, "final": False})

    async def on_final(text: str) -> None:
        await ws.send_json({"type": "transcript", "text": text, "final": True})
        await game.handle(Answer(type="answer", text=text))

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break

            audio = msg.get("bytes")
            if audio is not None:
                # Mic audio only counts while a question is waiting for its answer.
                if voice and game.phase is Phase.QUESTION and len(audio) <= MAX_AUDIO_CHUNK:
                    if listening_for != game.question_index:  # one session per question, no retry storms
                        if listener:
                            listener.close()
                        listener = voice.listener(on_partial, on_final)
                        listening_for = game.question_index
                    listener.feed(audio)
                continue

            try:
                parsed = ClientMessage.validate_json(msg.get("text") or "")
            except ValidationError:
                await ws.send_json({"type": "error", "message": "Invalid message"})
                continue
            await game.handle(parsed)
            if listener and game.phase is not Phase.QUESTION:  # answered by typing
                listener.close()
    finally:
        if listener:
            listener.close()
        game.close()
