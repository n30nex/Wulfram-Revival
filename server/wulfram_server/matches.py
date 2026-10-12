"""Round scoring and public, credential-free match information."""
from dataclasses import dataclass
import time
from typing import Any

from wulfram_server.network.packets.player import UpdateStatsPacket


@dataclass
class PlayerScore:
    kills: int = 0
    deaths: int = 0
    structures: int = 0
    points: int = 0
    healing: float = 0.0
    total_kills: int = 0
    total_deaths: int = 0


def score_for(session: Any) -> PlayerScore:
    if getattr(session, "score", None) is None:
        session.score = PlayerScore()
    return session.score


def stats_packet(session: Any) -> UpdateStatsPacket:
    score = score_for(session)
    return UpdateStatsPacket(session.player_id, session.team, score.total_kills, score.total_deaths, score.kills)


def reset_round(server: Any) -> None:
    from wulfram_server import application as app
    for session in server.sessions:
        previous = score_for(session)
        session.score = PlayerScore(total_kills=previous.total_kills, total_deaths=previous.total_deaths)
        if session.is_logged_in:
            app.broadcast(server, stats_packet(session))


def record_destruction(server: Any, victim: Any, killer_player_id: int) -> None:
    """Called once at the terminal combat transition, before releasing ownership."""
    from wulfram_server import application as app
    owner = next((session for session in server.sessions if session.entity is victim), None)
    if owner is None and victim.unit_type not in (25, 26, 27, 29, 30):
        return
    killer = next((session for session in server.sessions
                   if session.player_id == killer_player_id and session.is_logged_in), None)
    if owner is not None:
        score = score_for(owner)
        score.deaths += 1
        score.total_deaths += 1
        app.broadcast(server, stats_packet(owner))
    if killer is None or killer is owner or victim.team_id == killer.team:
        return
    points = 0
    score = score_for(killer)
    if owner is not None:
        score.kills += 1
        score.total_kills += 1
        points = 1
    elif victim.unit_type in (25, 26, 27, 29, 30):
        score.structures += 1
        points = 3
    if points:
        score.points += points
        state = getattr(server, "match_state", None)
        if state is not None and killer.team in (1, 2):
            state.team_scores[killer.team] += points
        app.broadcast(server, stats_packet(killer))


def seconds_remaining(server: Any, now: float | None = None) -> int | None:
    limit = server.cfg.game.round_seconds
    if not limit:
        return None
    state = getattr(server, "match_state", None)
    return max(0, int(limit - ((time.monotonic() if now is None else now) - state.started_at))) if state else limit


def record_repair(server: Any, player_id: int, amount: float) -> None:
    session = next((session for session in server.sessions if session.player_id == player_id), None)
    if session is None or amount <= 0:
        return
    score = score_for(session)
    previous = int(score.healing / 100)
    score.healing += amount
    points = int(score.healing / 100) - previous
    score.points += points
    if points and getattr(server, "match_state", None) is not None and session.team in (1, 2):
        server.match_state.team_scores[session.team] += points


def public_snapshot(server: Any) -> dict:
    from datetime import datetime, timezone
    sessions = [session for session in server.sessions if session.is_logged_in]
    state = getattr(server, "match_state", None)
    teams = []
    for team in (1, 2):
        members = [session for session in sessions if session.team == team]
        teams.append({"id": team, "name": "Red" if team == 1 else "Blue",
                      "points": state.team_scores[team] if state else 0,
                      "bots": sum(bool(getattr(session, "is_bot", False)) for session in members),
                      "players": sum(not getattr(session, "is_bot", False) for session in members),
                      "repair_pads": sum(entity.unit_type == 27 and entity.team_id == team
                                         and entity.health_points > 0 for entity in server.entities.get_all())})
    return {"updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "name": server.cfg.game.display_name, "map": server.current_map_name,
            "phase": "changing_map" if getattr(server, "map_change_transition", None) else "playing",
            "seconds_remaining": seconds_remaining(server), "teams": teams,
            "bots": sum(bool(getattr(session, "is_bot", False)) for session in sessions),
            "players": sum(not getattr(session, "is_bot", False) for session in sessions),
            "human_capacity": server.cfg.game.player_limit - 2 * server.cfg.game.bots_per_team,
            "leaders": [{"name": session.name, "team": session.team,
                         "bot": bool(getattr(session, "is_bot", False)),
                         "kills": score_for(session).kills, "deaths": score_for(session).deaths,
                         "structures": score_for(session).structures, "points": score_for(session).points,
                         "healing": round(score_for(session).healing),
                         "vehicle": getattr(getattr(session, "entity", None), "vehicle_loadout", "deploying")}
                        for session in sorted(sessions, key=lambda session: (-score_for(session).points,
                                                                            session.player_id))[:10]]}
