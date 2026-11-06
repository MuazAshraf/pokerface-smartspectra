"""Turns raw vitals into a per-player baseline and per-question reactions.

Entertainment heuristics only: a change from the player's own calm baseline,
not a measure of truthfulness.
"""

from dataclasses import dataclass
from statistics import fmean, pstdev

STRESS_EXPRESSIONS = {"Angry", "Contempt", "Disgust", "Fear", "Sad", "Surprise"}

# Floors keep a very steady baseline from turning tiny wobbles into big z-scores.
MIN_PULSE_STD = 3.0  # BPM
MIN_BREATH_STD = 1.5  # breaths/min
MIN_WINDOW_SAMPLES = 3

# How much each signal contributes to the 0..1 reaction score.
WEIGHTS = {"pulse": 0.45, "breathing": 0.35, "expression": 0.20}


@dataclass(frozen=True)
class Sample:
    pulse: float
    breathing: float
    expression: str | None


@dataclass(frozen=True)
class Baseline:
    pulse_mean: float
    pulse_std: float
    breath_mean: float
    breath_std: float
    stress_share: float

    @classmethod
    def from_samples(cls, samples: list[Sample]) -> "Baseline":
        pulses = [s.pulse for s in samples]
        breaths = [s.breathing for s in samples]
        return cls(
            pulse_mean=fmean(pulses),
            pulse_std=max(pstdev(pulses), MIN_PULSE_STD),
            breath_mean=fmean(breaths),
            breath_std=max(pstdev(breaths), MIN_BREATH_STD),
            stress_share=_stress_share(samples),
        )


@dataclass(frozen=True)
class Reaction:
    score: float  # 0..1
    pulse_delta: float
    breath_delta: float
    stress_delta: float
    reasons: list[str]


def _stress_share(samples: list[Sample]) -> float:
    return sum(s.expression in STRESS_EXPRESSIONS for s in samples) / len(samples)


def _clamp01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def read_reaction(baseline: Baseline, samples: list[Sample], question_no: int) -> Reaction | None:
    """Score one question's window against the baseline. None if too little signal."""
    if len(samples) < MIN_WINDOW_SAMPLES:
        return None

    pulse_delta = fmean(s.pulse for s in samples) - baseline.pulse_mean
    breath_delta = fmean(s.breathing for s in samples) - baseline.breath_mean
    stress_delta = _stress_share(samples) - baseline.stress_share

    pulse_z = pulse_delta / baseline.pulse_std  # only a rise counts
    breath_z = abs(breath_delta) / baseline.breath_std  # faster or held breath both count

    score = (
        WEIGHTS["pulse"] * _clamp01(pulse_z / 3)
        + WEIGHTS["breathing"] * _clamp01(breath_z / 3)
        + WEIGHTS["expression"] * _clamp01(stress_delta / 0.5)
    )

    q = f"Question {question_no}"
    reasons = []
    if pulse_z >= 1.5:
        reasons.append(f"Pulse rose {pulse_delta:+.0f} BPM after {q}")
    if breath_z >= 1.5:
        reasons.append(f"Breathing {'sped up' if breath_delta > 0 else 'slowed'} after {q}")
    if stress_delta >= 0.25:
        top = max(STRESS_EXPRESSIONS, key=lambda e: sum(s.expression == e for s in samples))
        reasons.append(f"{top} expression showed after {q}")

    return Reaction(
        score=round(score, 3),
        pulse_delta=round(pulse_delta, 1),
        breath_delta=round(breath_delta, 1),
        stress_delta=round(stress_delta, 2),
        reasons=reasons,
    )
