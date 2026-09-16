"""Team dimension reads."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from api.deps import DbSession
from api.schemas import TeamOut
from infra.models import Team

router = APIRouter()


@router.get("/teams", response_model=list[TeamOut])
def list_teams(db: DbSession) -> list[Team]:
    stmt = select(Team).order_by(
        Team.team_conf,
        Team.team_division,
        Team.team_name,
    )
    return list(db.scalars(stmt).all())


@router.get("/teams/{team_abbr}", response_model=TeamOut)
def get_team(team_abbr: str, db: DbSession) -> Team:
    team = db.get(Team, team_abbr)
    if team is None:
        raise HTTPException(status_code=404, detail="team not found")
    return team
