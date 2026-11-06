import asyncio

import pytest
from pydantic import ValidationError

from app.case import FALLBACK_QUESTIONS, OPENING_QUESTION, QUESTION_COUNT
from app.detective import Review
from app.game import BASELINE_SECONDS, MIN_ANSWER_WINDOW_S, Game, Phase
from app.protocol import Answer, ClientMessage, Start, Vitals


class FakeDetective:
    def __init__(self, fail=False, evasiveness=0):
        self.fail = fail
        self.evasiveness = evasiveness

    async def review(self, turns):
        if self.fail:
            return None
        return Review(evasiveness=self.evasiveness, question=f"LLM question {len(turns) + 1}")

    async def closing_speech(self, turns, suspicious, meter):
        return None if self.fail else "Case closed."


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def vitals(pulse=70, breathing=14, expression="Neutral"):
    return Vitals(type="vitals", pulse=pulse, breathing=breathing, expression=expression, face_ok=True)


async def play(detective, stressed_from=None):
    sent, clock = [], Clock()

    async def send(msg):
        sent.append(msg)

    game = Game(detective, send, clock)
    await game.handle(Start(type="start", consent=True))
    for _ in range(BASELINE_SECONDS + 1):
        clock.t += 1
        await game.handle(vitals())
    assert game.phase is Phase.QUESTION

    for q in range(1, QUESTION_COUNT + 1):
        stressed = stressed_from is not None and q >= stressed_from
        for _ in range(MIN_ANSWER_WINDOW_S):
            clock.t += 1
            await game.handle(vitals(90, 22, "Fear") if stressed else vitals())
        await game.handle(Answer(type="answer", text=f"answer {q}"))
        await game._task
    return game, sent


def test_full_game_reaches_verdict_with_timeline():
    game, sent = asyncio.run(play(FakeDetective()))
    questions = [m["text"] for m in sent if m["type"] == "question"]
    assert questions[0] == OPENING_QUESTION
    assert questions[1] == "LLM question 2"
    assert len(questions) == QUESTION_COUNT

    verdict = sent[-1]
    assert verdict["type"] == "verdict" and verdict["suspicious"] is False
    assert len(verdict["timeline"]) == QUESTION_COUNT
    assert game.phase is Phase.VERDICT


def test_stress_late_in_game_flips_verdict_and_names_the_question():
    _, sent = asyncio.run(play(FakeDetective(), stressed_from=3))
    verdict = sent[-1]
    assert verdict["suspicious"] is True
    assert any("after Question 3" in r for r in verdict["timeline"][2]["reasons"])


def test_llm_failure_falls_back_to_scripted_questions():
    _, sent = asyncio.run(play(FakeDetective(fail=True)))
    questions = [m["text"] for m in sent if m["type"] == "question"]
    assert questions[1:] == FALLBACK_QUESTIONS[: QUESTION_COUNT - 1]
    assert sent[-1]["speech"]


def test_words_alone_can_never_convict():
    # Maximally evasive answers but perfectly calm body: meter stays under the verdict line.
    _, sent = asyncio.run(play(FakeDetective(evasiveness=10)))
    verdict = sent[-1]
    assert verdict["suspicious"] is False
    assert 15 <= verdict["meter"] <= 20
    assert "Evasive answer to Question 1 (10/10)" in verdict["timeline"][0]["reasons"]


def test_evasiveness_tips_a_borderline_player():
    # Stress on the last 3 questions alone lands just under the line; evasion pushes it over.
    _, calm_words = asyncio.run(play(FakeDetective(evasiveness=0), stressed_from=4))
    _, evasive = asyncio.run(play(FakeDetective(evasiveness=10), stressed_from=4))
    assert evasive[-1]["meter"] > calm_words[-1]["meter"]
    assert calm_words[-1]["suspicious"] is False
    assert evasive[-1]["suspicious"] is True


def test_repeated_llm_question_is_replaced():
    class Repeater(FakeDetective):
        async def review(self, turns):
            return Review(evasiveness=0, question=OPENING_QUESTION.upper())

    _, sent = asyncio.run(play(Repeater()))
    questions = [m["text"] for m in sent if m["type"] == "question"]
    assert questions[1] == FALLBACK_QUESTIONS[0]


def test_answers_outside_question_phase_are_ignored():
    async def run():
        game = Game(FakeDetective(), lambda m: asyncio.sleep(0))
        await game.handle(Answer(type="answer", text="I confess"))
        assert game.phase is Phase.CONSENT and game._task is None

    asyncio.run(run())


@pytest.mark.parametrize("raw", [
    '{"type": "start", "consent": false}',
    '{"type": "answer", "text": ""}',
    '{"type": "answer", "text": "' + "x" * 301 + '"}',
    '{"type": "vitals", "pulse": "fast"}',
    '{"type": "vitals", "face_ok": true, "extra": 1}',
    '{"type": "hack"}',
])
def test_protocol_rejects_bad_messages(raw):
    with pytest.raises(ValidationError):
        ClientMessage.validate_json(raw)


def test_sensor_glitches_become_missing_readings():
    msg = ClientMessage.validate_json('{"type": "vitals", "pulse": 999, "breathing": 61, "face_ok": true}')
    assert msg.pulse is None and msg.breathing is None
