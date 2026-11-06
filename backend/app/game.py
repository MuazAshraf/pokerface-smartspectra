"""One interrogation per WebSocket connection:
consent -> 30 s calm baseline -> QUESTION_COUNT questions -> verdict."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from statistics import fmean

from .case import CASE_BRIEF, CASE_TITLE, FALLBACK_QUESTIONS, OPENING_QUESTION, QUESTION_COUNT
from .detective import Detective, Turn
from .protocol import Answer, Start, Vitals
from .signals import Baseline, Reaction, Sample, read_reaction

log = logging.getLogger(__name__)

BASELINE_SECONDS = 30
MIN_BASELINE_SAMPLES = 10
MIN_ANSWER_WINDOW_S = 10  # always watch at least this long after a question
SUSPICIOUS_AT = 45  # meter value (0-100) at which the verdict flips; tune in playtests
# Share of each question's score that comes from how evasive the answer was.
# Kept below SUSPICIOUS_AT / 100 so words alone can never convict — body signals decide.
EVASION_WEIGHT = 0.2
EVASIVE_REASON_AT = 6

Send = Callable[[dict], Awaitable[None]]


class Phase(StrEnum):
    CONSENT = "consent"
    BASELINE = "baseline"
    QUESTION = "question"  # question asked, waiting for the answer
    REVIEW = "review"  # answer in, still watching the reaction window
    DETECTIVE = "detective"  # LLM is writing the next question
    VERDICT = "verdict"


class Game:
    def __init__(self, detective: Detective, send: Send, clock: Callable[[], float] = time.monotonic):
        self._detective = detective
        self._send = send
        self._clock = clock
        self.phase = Phase.CONSENT
        self._baseline_samples: list[Sample] = []
        self._baseline: Baseline | None = None
        self._window: list[Sample] = []
        self._question = ""
        self._question_at = 0.0
        self._turns: list[Turn] = []
        self._scores: list[float] = []
        self._timeline: list[dict] = []
        self._task: asyncio.Task | None = None

    async def handle(self, msg: Start | Vitals | Answer) -> None:
        if isinstance(msg, Start):
            await self._start()
        elif isinstance(msg, Vitals):
            await self._vitals(msg)
        elif isinstance(msg, Answer) and self.phase is Phase.QUESTION:
            self.phase = Phase.REVIEW
            self._task = asyncio.create_task(self._advance(msg.text.strip()))

    def close(self) -> None:
        if self._task:
            self._task.cancel()

    @property
    def meter(self) -> int:
        return round(100 * fmean(self._scores)) if self._scores else 0

    async def _start(self) -> None:
        if self.phase is not Phase.CONSENT:
            return
        self.phase = Phase.BASELINE
        self._baseline_started = self._clock()
        await self._send({"type": "case", "title": CASE_TITLE, "brief": CASE_BRIEF, "questions": QUESTION_COUNT})
        await self._send({"type": "phase", "phase": "baseline", "seconds": BASELINE_SECONDS})

    async def _vitals(self, v: Vitals) -> None:
        if not v.face_ok or v.pulse is None or v.breathing is None:
            return
        sample = Sample(v.pulse, v.breathing, v.expression)

        if self.phase is Phase.BASELINE:
            self._baseline_samples.append(sample)
            elapsed = self._clock() - self._baseline_started
            if elapsed >= BASELINE_SECONDS and len(self._baseline_samples) >= MIN_BASELINE_SAMPLES:
                self._baseline = Baseline.from_samples(self._baseline_samples)
                await self._ask(OPENING_QUESTION)

        elif self.phase in (Phase.QUESTION, Phase.REVIEW):
            self._window.append(sample)
            live = read_reaction(self._baseline, self._window, len(self._turns) + 1)
            if live:
                value = round(100 * fmean([*self._scores, (1 - EVASION_WEIGHT) * live.score]))
                await self._send({"type": "meter", "value": value})

    async def _ask(self, question: str) -> None:
        self._question = question
        self._question_at = self._clock()
        self._window = []
        self.phase = Phase.QUESTION
        await self._send({"type": "question", "index": len(self._turns) + 1, "text": question})

    async def _advance(self, answer: str) -> None:
        try:
            # Keep watching briefly so a quick answer still gets a fair reaction window.
            await asyncio.sleep(max(0.0, self._question_at + MIN_ANSWER_WINDOW_S - self._clock()))
            self.phase = Phase.DETECTIVE
            await self._send({"type": "phase", "phase": "detective"})

            n = len(self._turns) + 1
            reaction = read_reaction(self._baseline, self._window, n)
            if reaction:
                note = "; ".join(reaction.reasons) or "stayed calm, no notable change"
            else:
                note = "signal unavailable (face out of view or poor light)"
            self._turns.append(Turn(self._question, answer, note))

            review = await self._detective.review(self._turns)
            await self._record(n, answer, reaction, note, review.evasiveness if review else None)

            if n == QUESTION_COUNT:
                await self._verdict()
                return
            question = review.question if review else None
            if not question or question.lower() in {t.question.lower() for t in self._turns}:
                question = FALLBACK_QUESTIONS[n - 1]
            await self._ask(question)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Game step failed")
            await self._send({"type": "error", "message": "The detective lost his notes. Please restart."})

    async def _record(self, n: int, answer: str, reaction: Reaction | None, note: str, evasiveness: int | None) -> None:
        reasons = list(reaction.reasons) if reaction else []
        if evasiveness is not None and evasiveness >= EVASIVE_REASON_AT:
            reasons.append(f"Evasive answer to Question {n} ({evasiveness}/10)")

        score = None
        if reaction:
            # Without a rating (LLM unavailable) the body signals score alone.
            score = reaction.score if evasiveness is None else (
                (1 - EVASION_WEIGHT) * reaction.score + EVASION_WEIGHT * evasiveness / 10
            )
            self._scores.append(score)

        entry = {
            "index": n,
            "question": self._question,
            "answer": answer,
            "reasons": reasons,
            "signal": note,
            "evasiveness": evasiveness,
            "score": round(100 * score) if score is not None else None,
            "pulse_delta": reaction.pulse_delta if reaction else None,
            "breath_delta": reaction.breath_delta if reaction else None,
        }
        self._timeline.append(entry)
        await self._send({"type": "reaction", **entry, "meter": self.meter})

    async def _verdict(self) -> None:
        self.phase = Phase.VERDICT
        suspicious = self.meter >= SUSPICIOUS_AT
        speech = await self._detective.closing_speech(self._turns, suspicious, self.meter) or (
            "Your pulse told me more than your words." if suspicious else "Cool as ice. You're free to go — for now."
        )
        await self._send({
            "type": "verdict",
            "suspicious": suspicious,
            "meter": self.meter,
            "speech": speech,
            "timeline": self._timeline,
        })
