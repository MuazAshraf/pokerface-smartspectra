import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status
from openai import AsyncOpenAI
from pydantic import ValidationError

from .config import settings
from .detective import Detective
from .game import Game
from .protocol import ClientMessage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
    app.state.detective = Detective(client, settings.openai_model, settings.llm_timeout_s)
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
    game = Game(app.state.detective, ws.send_json)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = ClientMessage.validate_json(raw)
            except ValidationError:
                await ws.send_json({"type": "error", "message": "Invalid message"})
                continue
            await game.handle(msg)
    except WebSocketDisconnect:
        pass
    finally:
        game.close()
