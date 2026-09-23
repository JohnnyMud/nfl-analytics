"""RushRbV1 ↔ jsonb payload. Unknown reasons and Known values round-trip."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from features.rush_yards import RushRbV1
from features.types import Known, Unknown
from models.rush_yards.matrix import FEATURE_NAMES

JsonScalar = bool | int | float | str


class KnownPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["known"] = "known"
    value: JsonScalar


class UnknownPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["unknown"] = "unknown"
    reason: str


def features_to_payload(features: RushRbV1) -> dict[str, dict[str, JsonScalar]]:
    """Encode each registry field as ``{kind, value}`` or ``{kind, reason}``."""
    payload: dict[str, dict[str, JsonScalar]] = {}
    for name in FEATURE_NAMES:
        value = getattr(features, name)
        if isinstance(value, Unknown):
            payload[name] = UnknownPayload(reason=value.reason).model_dump()
        elif isinstance(value, Known):
            known = KnownPayload(value=_as_json_scalar(value.value))
            payload[name] = known.model_dump()
        else:
            raise TypeError(f"{name} is neither Known nor Unknown: {type(value)!r}")
    return payload


def payload_to_features(
    *,
    gsis_id: str,
    game_id: str,
    as_of: datetime,
    payload: dict[str, object],
) -> RushRbV1:
    """Rebuild ``RushRbV1`` from a stored jsonb payload plus row keys."""
    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        raise ValueError("as_of must be timezone-aware")

    fields: dict[str, object] = {
        "gsis_id": gsis_id,
        "game_id": game_id,
        "as_of": as_of,
    }
    for name in FEATURE_NAMES:
        raw = payload.get(name)
        if not isinstance(raw, dict):
            raise ValueError(f"payload[{name!r}] is missing or not an object")
        kind = raw.get("kind")
        if kind == "unknown":
            reason = raw.get("reason")
            if not isinstance(reason, str) or not reason:
                raise ValueError(f"payload[{name!r}] Unknown is missing reason")
            fields[name] = Unknown(reason=reason)
        elif kind == "known":
            if "value" not in raw:
                raise ValueError(f"payload[{name!r}] Known is missing value")
            fields[name] = Known(value=_as_json_scalar(raw["value"]))
        else:
            raise ValueError(f"payload[{name!r}] has unknown kind {kind!r}")
    return RushRbV1.model_validate(fields)


def _as_json_scalar(value: object) -> JsonScalar:
    if isinstance(value, bool | int | float | str):
        return value
    raise TypeError(f"unsupported payload value type: {type(value)!r}")
