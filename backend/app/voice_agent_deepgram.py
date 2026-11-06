from __future__ import annotations

import argparse
import logging
import os, json
import queue
import sys
import threading
from dataclasses import dataclass
from typing import Any
from tavily import TavilyClient
from dotenv import load_dotenv
from functools import lru_cache

try:
    import sounddevice as sd
except ImportError as exc:
    raise SystemExit(
        "sounddevice is missing. Install dependencies with:\n"
        '  python -m pip install "deepgram-sdk==7.4.0" '
        '"sounddevice>=0.5,<0.6" "python-dotenv>=1,<2"'
    ) from exc

from deepgram import DeepgramClient
from deepgram.agent.v1.types import (
    AgentV1Settings,
    AgentV1SettingsAgent,
    AgentV1SettingsAgentListen,
    AgentV1SettingsAgentListenProvider_V2,
    AgentV1SettingsAudio,
    AgentV1SettingsAudioInput,
    AgentV1SettingsAudioOutput,
    AgentV1SendFunctionCallResponse,
)

from deepgram.core.events import EventType
from deepgram.types.speak_settings_v1 import SpeakSettingsV1
from deepgram.types.speak_settings_v1provider import SpeakSettingsV1Provider_Deepgram
from deepgram.types.think_settings_v1 import ThinkSettingsV1
from deepgram.types.think_settings_v1provider import ThinkSettingsV1Provider_OpenAi
from deepgram.types.think_settings_v1functions_item import (
    ThinkSettingsV1FunctionsItem,
)


@lru_cache(maxsize=1)
def get_tavily_client() -> TavilyClient:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "TAVILY_API_KEY is missing from the .env file"
        )

    return TavilyClient(api_key=api_key)


def web_search(arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Search the live web using Tavily.

    Designed for voice-agent usage:
    - fast search depth
    - limited results
    - compact content returned to the LLM
    """

    query = str(arguments.get("query", "")).strip()

    if not query:
        return {
            "success": False,
            "error": "A non-empty search query is required.",
        }

    topic = str(
        arguments.get("topic", "general")
    ).strip().lower()

    if topic not in {"general", "news"}:
        topic = "general"

    time_range = str(
        arguments.get("time_range", "none")
    ).strip().lower()

    if time_range not in {
        "none",
        "day",
        "week",
        "month",
        "year",
    }:
        time_range = "none"

    try:
        max_results = int(
            arguments.get("max_results", 4)
        )
    except (TypeError, ValueError):
        max_results = 4

    # Do not let the LLM request excessive results.
    max_results = max(
        1,
        min(max_results, 5),
    )

    search_options: dict[str, Any] = {
        "search_depth": "fast",
        "topic": topic,
        "max_results": max_results,

        # Deepgram's LLM will produce the final answer.
        # Avoid another answer-generation layer inside Tavily.
        "include_answer": False,

        "include_raw_content": False,
        "include_images": False,
    }

    if time_range != "none":
        search_options["time_range"] = time_range

    try:
        logging.info(
            "Searching Tavily | query=%r topic=%s time_range=%s",
            query,
            topic,
            time_range,
        )

        response = get_tavily_client().search(
            query,
            **search_options,
        )

        compact_results: list[dict[str, Any]] = []

        for item in response.get("results", []):
            title = str(
                item.get("title", "")
            ).strip()

            url = str(
                item.get("url", "")
            ).strip()

            content = str(
                item.get("content", "")
            ).strip()

            # Prevent massive tool responses from increasing LLM latency.
            if len(content) > 1200:
                content = content[:1200].rstrip() + "..."

            compact_results.append(
                {
                    "title": title,
                    "url": url,
                    "content": content,
                    "relevance_score": item.get("score"),
                }
            )

        if not compact_results:
            return {
                "success": True,
                "query": query,
                "message": "No relevant web results were found.",
                "results": [],
            }

        return {
            "success": True,
            "query": response.get("query", query),
            "topic": topic,
            "time_range": time_range,
            "response_time_seconds": response.get(
                "response_time"
            ),
            "results": compact_results,
        }

    except Exception as exc:
        logging.exception(
            "Tavily web search failed"
        )

        return {
            "success": False,
            "query": query,
            "error": str(exc),
        }

# Tool Schema
WEB_SEARCH_TOOL = ThinkSettingsV1FunctionsItem(
    name="web_search",
    description=(
        "Search the live web for current and potentially changed information. "
        "You must use this function whenever the user asks about latest, "
        "current, recent, today, this week, news, newly released products, "
        "current people or positions, prices, events, or information that "
        "may have changed after the model's training data. "
        "Use topic='news' for recent news and topic='general' for broader "
        "web information."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A complete standalone search query. "
                    "Include important names, dates, products, companies, "
                    "or locations mentioned by the user."
                ),
            },
            "topic": {
                "type": "string",
                "enum": [
                    "general",
                    "news",
                ],
                "description": (
                    "Use news for current events or recent announcements. "
                    "Use general for all other web searches."
                ),
            },
            "time_range": {
                "type": "string",
                "enum": [
                    "none",
                    "day",
                    "week",
                    "month",
                    "year",
                ],
                "description": (
                    "Limit results by recency. Use day for today/latest, "
                    "week for this week or recent news, month for recent "
                    "developments, and none when no date restriction is needed."
                ),
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": (
                    "Number of web results. Usually use 3 or 4."
                ),
            },
        },
        "required": [
            "query",
            "topic",
            "time_range",
        ],
        "additionalProperties": False,
    },
)

# Function Handler
TOOL_HANDLERS = {
    "web_search": web_search,
}


INPUT_SAMPLE_RATE = 16_000
OUTPUT_SAMPLE_RATE = 24_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2  # linear16 / int16
INPUT_BLOCK_MS = 20
INPUT_BLOCK_FRAMES = INPUT_SAMPLE_RATE * INPUT_BLOCK_MS // 1000
OUTPUT_BLOCK_MS = 20
OUTPUT_BLOCK_FRAMES = OUTPUT_SAMPLE_RATE * OUTPUT_BLOCK_MS // 1000

DEFAULT_PROMPT = """
You are a real-time voice assistant speaking with a person through a live audio call.

ROLE AND BEHAVIOR
- Be useful, calm, direct, and conversational.
- Sound like a capable human assistant, not a scripted bot.
- Use contractions and ordinary spoken English where natural.
- Never say that you are "just an AI" unless directly asked what you are.
- You are speaking aloud through a voice interface. Never claim that you can only reply in text or that this is a text-only chat.

SPEAKING STYLE
- Keep most turns to one or two short sentences.
- Ask only one question at a time.
- Do not use markdown, bullet points, headings, tables, code formatting, or emojis.
- Do not produce long introductions, summaries, or repeated confirmations.
- Do not repeat the caller's full sentence back to them.
- Use brief acknowledgements such as "Got it", "Okay", or "Right" only when useful.
- Do not randomly add fillers such as "um", "uh", or "you know".
- Avoid exaggerated enthusiasm and customer-service clichés.

CONVERSATION CONTROL
- Respond to the caller's latest complete request.
- If the caller interrupts or changes direction, follow the new request and do not resume an obsolete answer.
- If speech appears incomplete or ambiguous, ask one short clarification question.
- If transcription may have confused a name, number, date, email address, or identifier, confirm only the uncertain part.
- Do not claim that an action was completed unless a tool or verified result confirms it.
- Never invent facts, availability, prices, policies, records, reference numbers, or tool results.

SPOKEN DATA
- Read dates, times, prices, phone numbers, email addresses, and identifiers clearly.
- Group long numbers into understandable chunks.
- Confirm high-impact details before treating them as final.

ENDING
- Do not repeatedly ask "Is there anything else I can help with?"
- When the caller is clearly finished, close with one brief natural sentence.

WEB SEARCH
- You have access to a live web-search tool.
- You must use web_search whenever the user asks for latest, current,
  recent, today, this week, news, newly announced, current prices,
  current roles, current events, or facts that may have changed.
- Never answer a time-sensitive question from memory.
- For news, use topic "news" and an appropriate time range.
- For today's news, use time_range "day".
- For this week's or latest general developments, use time_range "week".
- Wait for the tool result before answering.
- Base the response only on the returned search results.
- Briefly mention source names when useful.
- Do not read full URLs aloud unless the user specifically asks.
- If sources conflict, clearly say that reports disagree.
- If no useful result is returned, say that you could not verify it.
""".strip()


@dataclass(frozen=True)
class Config:
    api_key: str
    llm_model: str
    tts_model: str
    greeting: str
    eot_threshold: float
    eager_eot_threshold: float
    eot_timeout_ms: int
    keyterms: list[str]
    input_device: int | str | None
    output_device: int | str | None
    mip_opt_out: bool


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_device(value: str | None) -> int | str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    try:
        return int(value)
    except ValueError:
        return value


def load_config(args: argparse.Namespace) -> Config:
    load_dotenv()

    api_key = os.getenv("DEEPGRAM_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "DEEPGRAM_API_KEY is missing. Create a .env file containing:\n"
            "DEEPGRAM_API_KEY=your_deepgram_api_key"
        )

    keyterms = [
        item.strip()
        for item in os.getenv("DG_KEYTERMS", "").split(",")
        if item.strip()
    ]

    return Config(
        api_key=api_key,
        llm_model=os.getenv("DG_LLM_MODEL", "gpt-5.4-mini").strip(),
        tts_model=os.getenv("DG_TTS_MODEL", "aura-2-thalia-en").strip(),
        greeting=os.getenv(
            "DG_GREETING",
            "Hi, how can I help?",
        ).strip(),
        eot_threshold=float(os.getenv("DG_EOT_THRESHOLD", "0.75")),
        eager_eot_threshold=float(
            os.getenv("DG_EAGER_EOT_THRESHOLD", "0.55")
        ),
        eot_timeout_ms=int(os.getenv("DG_EOT_TIMEOUT_MS", "1800")),
        keyterms=keyterms,
        input_device=parse_device(args.input_device or os.getenv("DG_INPUT_DEVICE")),
        output_device=parse_device(
            args.output_device or os.getenv("DG_OUTPUT_DEVICE")
        ),
        mip_opt_out=env_bool("DG_MIP_OPT_OUT", True),
    )


def validate_config(config: Config) -> None:
    if not 0.5 <= config.eot_threshold <= 0.9:
        raise ValueError("DG_EOT_THRESHOLD must be between 0.5 and 0.9")
    if not 0.3 <= config.eager_eot_threshold <= 0.9:
        raise ValueError("DG_EAGER_EOT_THRESHOLD must be between 0.3 and 0.9")
    if not 500 <= config.eot_timeout_ms <= 10_000:
        raise ValueError("DG_EOT_TIMEOUT_MS must be between 500 and 10000")


class PcmPlaybackBuffer:
    """Thread-safe PCM buffer consumed by a sounddevice output callback."""

    def __init__(self) -> None:
        self._data = bytearray()
        self._lock = threading.Lock()

    def append(self, audio: bytes) -> None:
        if not audio:
            return
        with self._lock:
            self._data.extend(audio)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def read(self, byte_count: int) -> bytes:
        with self._lock:
            available = min(byte_count, len(self._data))
            chunk = bytes(self._data[:available])
            del self._data[:available]

        if available < byte_count:
            chunk += b"\x00" * (byte_count - available)
        return chunk


class AudioPlayer:
    def __init__(self, device: int | str | None) -> None:
        self.buffer = PcmPlaybackBuffer()
        self._status_reported = False
        self.stream = sd.RawOutputStream(
            samplerate=OUTPUT_SAMPLE_RATE,
            blocksize=OUTPUT_BLOCK_FRAMES,
            device=device,
            channels=CHANNELS,
            dtype="int16",
            callback=self._callback,
        )

    def _callback(
        self,
        outdata: Any,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        del time_info
        if status and not self._status_reported:
            logging.warning("Speaker stream status: %s", status)
            self._status_reported = True

        required = frames * CHANNELS * SAMPLE_WIDTH_BYTES
        outdata[:] = self.buffer.read(required)

    def start(self) -> None:
        self.stream.start()

    def stop(self) -> None:
        try:
            self.stream.stop()
        finally:
            self.stream.close()

    def enqueue(self, audio: bytes) -> None:
        self.buffer.append(audio)

    def interrupt(self) -> None:
        # Discard queued TTS immediately when the user begins speaking.
        self.buffer.clear()


class MicrophoneSender:
    """Capture microphone audio without blocking PortAudio's callback thread."""

    def __init__(
        self,
        connection: Any,
        stop_event: threading.Event,
        device: int | str | None,
    ) -> None:
        self.connection = connection
        self.stop_event = stop_event
        self.audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=50)
        self.dropped_chunks = 0
        self._status_reported = False
        self._sender_thread = threading.Thread(
            target=self._send_loop,
            name="deepgram-audio-sender",
            daemon=True,
        )
        self.stream = sd.RawInputStream(
            samplerate=INPUT_SAMPLE_RATE,
            blocksize=INPUT_BLOCK_FRAMES,
            device=device,
            channels=CHANNELS,
            dtype="int16",
            callback=self._callback,
        )

    def _callback(
        self,
        indata: Any,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        del frames, time_info
        if status and not self._status_reported:
            logging.warning("Microphone stream status: %s", status)
            self._status_reported = True

        if self.stop_event.is_set():
            return

        chunk = bytes(indata)
        try:
            self.audio_queue.put_nowait(chunk)
        except queue.Full:
            # Do not let network congestion create seconds of stale audio latency.
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.audio_queue.put_nowait(chunk)
            except queue.Full:
                pass
            self.dropped_chunks += 1

    def _send_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                chunk = self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                self.connection.send_media(chunk)
            except Exception:
                logging.exception("Failed to send microphone audio to Deepgram")
                self.stop_event.set()
                return

    def start(self) -> None:
        self._sender_thread.start()
        self.stream.start()

    def stop(self) -> None:
        try:
            if self.stream.active:
                self.stream.stop()
        finally:
            self.stream.close()
        self._sender_thread.join(timeout=1.0)


def build_settings(config: Config) -> AgentV1Settings:
    listen_kwargs: dict[str, Any] = {
        "model": "flux-general-en",
        "eot_threshold": config.eot_threshold,
        "eager_eot_threshold": config.eager_eot_threshold,
        "eot_timeout_ms": config.eot_timeout_ms,
    }
    if config.keyterms:
        listen_kwargs["keyterms"] = config.keyterms

    listen_provider = AgentV1SettingsAgentListenProvider_V2(**listen_kwargs)

    return AgentV1Settings(
        tags=["local-microphone", "flux", "voice-agent"],
        mip_opt_out=config.mip_opt_out,
        audio=AgentV1SettingsAudio(
            input=AgentV1SettingsAudioInput(
                encoding="linear16",
                sample_rate=INPUT_SAMPLE_RATE,
            ),
            output=AgentV1SettingsAudioOutput(
                encoding="linear16",
                sample_rate=OUTPUT_SAMPLE_RATE,
                container="none",
            ),
        ),
        agent=AgentV1SettingsAgent(
            listen=AgentV1SettingsAgentListen(provider=listen_provider),
            think=ThinkSettingsV1(
                provider=ThinkSettingsV1Provider_OpenAi(
                    type="open_ai",
                    model=config.llm_model
                ),
                prompt=os.getenv("DG_SYSTEM_PROMPT", DEFAULT_PROMPT).strip(),
                functions=[WEB_SEARCH_TOOL,],
            ),
            speak=SpeakSettingsV1(
                provider=SpeakSettingsV1Provider_Deepgram(
                    type="deepgram",
                    model=config.tts_model,
                )
            ),
            greeting=config.greeting or None,
        ),
    )


def run_agent(config: Config) -> None:
    stop_event = threading.Event()
    welcome_event = threading.Event()
    settings_applied_event = threading.Event()
    received_audio_chunks = 0
    player = AudioPlayer(config.output_device)
    microphone: MicrophoneSender | None = None

    client = DeepgramClient(api_key=config.api_key)

    try:
        with client.agent.v1.connect() as connection:

            def on_open(_: Any) -> None:
                logging.info("Deepgram WebSocket opened")
            
            send_lock = threading.Lock()

            def execute_tool_call(function_call: Any) -> None:
                function_name = getattr(
                    function_call,
                    "name",
                    "unknown",
                )

                function_call_id = getattr(
                    function_call,
                    "id",
                    None,
                )

                logging.info(
                    "Executing tool: %s | id=%s",
                    function_name,
                    function_call_id,
                )

                try:
                    raw_arguments = getattr(
                        function_call,
                        "arguments",
                        "{}",
                    )

                    if isinstance(raw_arguments, dict):
                        arguments = raw_arguments
                    else:
                        arguments = json.loads(
                            raw_arguments or "{}"
                        )

                    if not isinstance(arguments, dict):
                        raise ValueError(
                            "Tool arguments must be a JSON object"
                        )

                    logging.info(
                        "Tool arguments: %s",
                        arguments,
                    )

                    handler = TOOL_HANDLERS.get(
                        function_name
                    )

                    if handler is None:
                        result = {
                            "success": False,
                            "error": (
                                f"No handler registered for tool: "
                                f"{function_name}"
                            ),
                        }
                    else:
                        result = handler(arguments)

                except json.JSONDecodeError as exc:
                    logging.exception(
                        "Invalid JSON arguments for %s",
                        function_name,
                    )

                    result = {
                        "success": False,
                        "error": (
                            f"Invalid JSON tool arguments: {exc}"
                        ),
                    }

                except Exception as exc:
                    logging.exception(
                        "Tool execution failed: %s",
                        function_name,
                    )

                    result = {
                        "success": False,
                        "error": str(exc),
                    }

                response = AgentV1SendFunctionCallResponse(
                    id=function_call_id,
                    name=function_name,
                    content=json.dumps(
                        result,
                        ensure_ascii=False,
                    ),
                )

                try:
                    with send_lock:
                        connection.send_function_call_response(
                            response
                        )

                    logging.info(
                        "Tool response sent: %s | result=%s",
                        function_name,
                        result,
                    )

                except Exception:
                    logging.exception(
                        "Failed to send tool response: %s",
                        function_name,
                    )
            def on_message(message: Any) -> None:
                nonlocal received_audio_chunks

                # Deepgram sends synthesized speech as raw binary WebSocket frames.
                # Play every binary frame immediately. Do not gate playback on an
                # AgentStartedSpeaking event: some sessions may deliver audio without
                # that event being observed first, and gating would silently discard TTS.
                if isinstance(message, (bytes, bytearray, memoryview)):
                    audio = bytes(message)
                    received_audio_chunks += 1
                    if received_audio_chunks == 1:
                        logging.info(
                            "Received first agent audio chunk: %d bytes",
                            len(audio),
                        )
                    player.enqueue(audio)
                    return

                message_type = getattr(message, "type", type(message).__name__)

                if message_type == "Welcome":
                    request_id = getattr(message, "request_id", "unknown")
                    logging.info("Welcome received. Request ID: %s", request_id)
                    welcome_event.set()
                elif message_type == "SettingsApplied":
                    logging.info("Agent settings applied")
                    settings_applied_event.set()

                elif message_type == "ConversationText":
                    role = getattr(message, "role", "unknown")
                    content = getattr(message, "content", "")
                    label = "YOU" if role == "user" else "AGENT"
                    print(f"\n{label}: {content}", flush=True)

                elif message_type == "UserStartedSpeaking":
                    # Deepgram cancels the interrupted response server-side. Locally,
                    # discard only audio already queued for playback. Future binary
                    # frames are accepted normally.
                    player.interrupt()
                    logging.info("Barge-in: cleared queued agent audio")

                elif message_type == "AgentThinking":
                    logging.info("Agent is thinking")

                elif message_type == "AgentStartedSpeaking":
                    total = getattr(message, "total_latency", None)
                    ttt = getattr(message, "ttt_latency", None)
                    tts = getattr(message, "tts_latency", None)

                    def milliseconds(value: Any) -> str:
                        return "n/a" if value is None else f"{float(value) * 1000:.0f}"

                    logging.info(
                        "Agent started speaking | total=%s ms, think=%s ms, tts=%s ms",
                        milliseconds(total),
                        milliseconds(ttt),
                        milliseconds(tts),
                    )

                elif message_type == "AgentAudioDone":
                    logging.debug("Agent finished generating audio")

                elif message_type == "Warning":
                    logging.warning(
                        "Deepgram warning [%s]: %s",
                        getattr(message, "code", "unknown"),
                        getattr(message, "description", message),
                    )

                elif message_type == "Error":
                    logging.error(
                        "Deepgram error [%s]: %s",
                        getattr(message, "code", "unknown"),
                        getattr(message, "description", message),
                    )
                    stop_event.set()
                elif message_type == "FunctionCallRequest":
                    function_calls = getattr(message, "functions", [])

                    if not function_calls:
                        logging.warning(
                            "FunctionCallRequest received without functions"
                        )
                        return

                    for function_call in function_calls:
                        function_name = getattr(
                            function_call,
                            "name",
                            "unknown",
                        )

                        is_client_side = getattr(
                            function_call,
                            "client_side",
                            True,
                        )

                        logging.info(
                            "Function call received: %s | client_side=%s",
                            function_name,
                            is_client_side,
                        )

                        if not is_client_side:
                            logging.info(
                                "Skipping server-side function: %s",
                                function_name,
                            )
                            continue

                        threading.Thread(
                            target=execute_tool_call,
                            args=(function_call,),
                            name=f"tool-{function_name}",
                            daemon=True,
                        ).start()
            
                else:
                    logging.debug("Received event: %s", message_type)

            def on_error(error: Any) -> None:
                logging.error("WebSocket error: %s", error)
                stop_event.set()

            def on_close(_: Any) -> None:
                logging.info("Deepgram WebSocket closed")
                stop_event.set()

            connection.on(EventType.OPEN, on_open)
            connection.on(EventType.MESSAGE, on_message)
            connection.on(EventType.ERROR, on_error)
            connection.on(EventType.CLOSE, on_close)

            player.start()

            listener_thread = threading.Thread(
                target=connection.start_listening,
                name="deepgram-event-listener",
                daemon=True,
            )
            listener_thread.start()

            # Correct protocol order: Welcome -> Settings -> SettingsApplied -> audio.
            if not welcome_event.wait(timeout=10):
                raise TimeoutError("Deepgram did not send Welcome within 10 seconds")

            connection.send_settings(build_settings(config))

            if not settings_applied_event.wait(timeout=15):
                raise TimeoutError(
                    "Deepgram did not confirm SettingsApplied within 15 seconds"
                )

            microphone = MicrophoneSender(
                connection=connection,
                stop_event=stop_event,
                device=config.input_device,
            )
            microphone.start()

            print(
                "\nVoice agent is running. Speak normally. Press Ctrl+C to stop.\n"
                "Use headphones to prevent the agent from hearing its own voice.",
                flush=True,
            )

            try:
                try:
                    while not stop_event.wait(0.25):
                        pass
                except KeyboardInterrupt:
                    print("\nStopping...", flush=True)
                    stop_event.set()
            finally:
                # Stop capture before the WebSocket context closes.
                if microphone is not None:
                    microphone.stop()
                    if microphone.dropped_chunks:
                        logging.warning(
                            "Dropped %d microphone chunks because the network sender fell behind",
                            microphone.dropped_chunks,
                        )
                    microphone = None

    finally:
        stop_event.set()
        if microphone is not None:
            microphone.stop()
        player.stop()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a real-time Deepgram Voice Agent using your microphone."
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List audio devices and exit.",
    )
    parser.add_argument(
        "--input-device",
        help="Input device index or name. Overrides DG_INPUT_DEVICE.",
    )
    parser.add_argument(
        "--output-device",
        help="Output device index or name. Overrides DG_OUTPUT_DEVICE.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    if args.list_devices:
        print(sd.query_devices())
        return 0

    try:
        config = load_config(args)
        validate_config(config)
        run_agent(config)
        return 0
    except (ValueError, TimeoutError) as exc:
        logging.error("%s", exc)
        return 1
    except sd.PortAudioError as exc:
        logging.error("Audio device error: %s", exc)
        print("\nAvailable devices:\n", sd.query_devices(), file=sys.stderr)
        print(
            "\nChoose devices with --input-device and --output-device, "
            "or set DG_INPUT_DEVICE and DG_OUTPUT_DEVICE.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.exception("Voice agent failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())