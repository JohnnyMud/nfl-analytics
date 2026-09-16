"""Player dimension reads."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from api.deps import DbSession
from api.schemas import PlayerOut
from infra.models import Player

router = APIRouter()


@router.get("/players", response_model=list[PlayerOut])
def list_players(team_abbr: str, db: DbSession) -> list[Player]:
    stmt = (
        select(Player)
        .where(Player.latest_team == team_abbr)
        .order_by(Player.last_name, Player.first_name, Player.display_name)
    )
    return list(db.scalars(stmt).all())


@router.get("/players/{gsis_id}", response_model=PlayerOut)
def get_player(gsis_id: str, db: DbSession) -> Player:
    player = db.get(Player, gsis_id)
    if player is None:
        raise HTTPException(status_code=404, detail="player not found")
    return player
