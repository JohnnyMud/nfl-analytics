"""Known / Unknown jsonb payload round-trip."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from features.types import Known, Unknown
from models.rush_yards.matrix import FEATURE_NAMES
from models.rush_yards.payload import features_to_payload, payload_to_features
from tests.models.helpers import RB_A, labeled_row


def test_payload_round_trip_preserves_unknown_reason_and_known_value() -> None:
    row = labeled_row(RB_A, 2016, 1)
    features = row.features

    assert isinstance(features.player_std_rush_yards, Unknown)
    assert isinstance(features.player_prior_season_rush_yards_pg, Known)
    assert isinstance(features.report_status, Unknown)

    payload = features_to_payload(features)
    via_json = json.loads(json.dumps(payload))
    restored = payload_to_features(
        gsis_id=features.gsis_id,
        game_id=features.game_id,
        as_of=features.as_of,
        payload=via_json,
    )

    assert set(payload) == set(FEATURE_NAMES)
    assert payload["player_std_rush_yards"] == {
        "kind": "unknown",
        "reason": features.player_std_rush_yards.reason,
    }
    assert payload["player_prior_season_rush_yards_pg"] == {
        "kind": "known",
        "value": features.player_prior_season_rush_yards_pg.value,
    }
    assert isinstance(restored.player_std_rush_yards, Unknown)
    assert (
        restored.player_std_rush_yards.reason == features.player_std_rush_yards.reason
    )
    assert isinstance(restored.player_prior_season_rush_yards_pg, Known)
    assert (
        restored.player_prior_season_rush_yards_pg.value
        == features.player_prior_season_rush_yards_pg.value
    )
    assert restored.report_status == features.report_status
    assert restored.as_of == features.as_of
    assert restored.as_of.tzinfo is not None


def test_payload_rejects_naive_as_of() -> None:
    row = labeled_row(RB_A, 2016, 2)
    payload = features_to_payload(row.features)
    naive = datetime(2016, 9, 18, 17, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        payload_to_features(
            gsis_id=row.gsis_id,
            game_id=row.game_id,
            as_of=naive,
            payload=payload,
        )


def test_payload_as_of_stays_utc() -> None:
    row = labeled_row(RB_A, 2016, 2)
    as_of = datetime(2016, 9, 18, 17, 0, tzinfo=UTC)
    restored = payload_to_features(
        gsis_id=row.gsis_id,
        game_id=row.game_id,
        as_of=as_of,
        payload=features_to_payload(row.features),
    )
    assert restored.as_of.utcoffset() is not None
    assert restored.as_of.utcoffset().total_seconds() == 0
