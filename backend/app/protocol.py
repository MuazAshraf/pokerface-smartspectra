"""WebSocket messages from the Electron client. Anything else is rejected."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter


def _plausible(lo: float, hi: float) -> AfterValidator:
    """Out-of-range readings are sensor glitches: treat as 'no reading', don't reject."""
    return AfterValidator(lambda v: v if v is None or lo <= v <= hi else None)


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Start(_Msg):
    type: Literal["start"]
    consent: Literal[True]


class Vitals(_Msg):
    type: Literal["vitals"]
    pulse: Annotated[float | None, _plausible(30, 220)] = None
    breathing: Annotated[float | None, _plausible(2, 60)] = None
    expression: Annotated[str, Field(max_length=16)] | None = None
    face_ok: bool = False


class Answer(_Msg):
    type: Literal["answer"]
    text: Annotated[str, Field(min_length=1, max_length=300)]


ClientMessage = TypeAdapter(Annotated[Start | Vitals | Answer, Field(discriminator="type")])
