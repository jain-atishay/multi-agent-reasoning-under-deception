"""
logger.py
---------
Structured JSON logging for every game event.

Writes a single NDJSON-style file (one JSON object per line)
as well as a final full-game summary JSON.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from clocktower.game_state import GameState


class GameLogger:
    def __init__(self, game_id: str, log_dir: str = "logs"):
        self.game_id = game_id
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.event_file = self.log_dir / f"{game_id}_{timestamp}_events.ndjson"
        self.summary_file = self.log_dir / f"{game_id}_{timestamp}_summary.json"

        self._events: list[dict] = []
        self._open()

    def _open(self):
        self._fh = open(self.event_file, "w")

    def _write(self, event: dict):
        event["_game_id"] = self.game_id
        event["_ts"] = datetime.utcnow().isoformat()
        self._events.append(event)
        self._fh.write(json.dumps(event) + "\n")
        self._fh.flush()

    # ── Convenience log methods ──────────────────────────

    def log_setup(self, state: "GameState"):
        self._write({
            "event": "game_setup",
            "players": [
                {
                    "player_id": p.player_id,
                    "name": p.name,
                    "role": p.role.name,
                    "team": p.role.team,
                    "seat": p.seat,
                }
                for p in state.players
            ],
        })

    def log_phase_start(self, phase: str, round_number: int):
        self._write({
            "event": "phase_start",
            "phase": phase,
            "round": round_number,
        })

    def log_night_action(self, actor_id: str, action_type: str, target_id: str | None, extra: dict = None):
        self._write({
            "event": "night_action",
            "actor_id": actor_id,
            "action_type": action_type,
            "target_id": target_id,
            **(extra or {}),
        })

    def log_info_delivery(self, player_id: str, info_type: str, content: dict, was_reliable: bool):
        self._write({
            "event": "info_delivery",
            "player_id": player_id,
            "info_type": info_type,
            "content": content,
            "was_reliable": was_reliable,
        })

    def log_death(self, player_id: str, cause: str, round_number: int):
        self._write({
            "event": "death",
            "player_id": player_id,
            "cause": cause,
            "round": round_number,
        })

    def log_discussion(self, player_id: str, message: str, round_number: int):
        self._write({
            "event": "discussion",
            "player_id": player_id,
            "message": message,
            "round": round_number,
        })

    def log_nomination(self, nominator_id: str, nominee_id: str, round_number: int):
        self._write({
            "event": "nomination",
            "nominator_id": nominator_id,
            "nominee_id": nominee_id,
            "round": round_number,
        })

    def log_vote(self, voter_id: str, nominee_id: str, vote: bool, round_number: int):
        self._write({
            "event": "vote",
            "voter_id": voter_id,
            "nominee_id": nominee_id,
            "vote": vote,
            "round": round_number,
        })

    def log_execution(self, player_id: str, vote_tally: dict[str, int], round_number: int):
        self._write({
            "event": "execution",
            "player_id": player_id,
            "vote_tally": vote_tally,
            "round": round_number,
        })

    def log_slayer_shot(self, slayer_id: str, target_id: str, success: bool):
        self._write({
            "event": "slayer_shot",
            "slayer_id": slayer_id,
            "target_id": target_id,
            "success": success,
        })

    def log_game_end(self, winner: str, reason: str, round_number: int):
        self._write({
            "event": "game_end",
            "winner": winner,
            "reason": reason,
            "round": round_number,
        })

    def log_reflection(self, player_id: str, reflection: str, round_number: int):
        """Store post-game agent reflections for learning."""
        self._write({
            "event": "reflection",
            "player_id": player_id,
            "reflection": reflection,
            "round": round_number,
        })

    def finalize(self, state: "GameState"):
        """Write the full game summary JSON."""
        summary = {
            "game_id": self.game_id,
            "winner": state.winner,
            "rounds_played": state.round_number,
            "final_state": state.to_full_dict(),
            "all_events": self._events,
        }
        with open(self.summary_file, "w") as f:
            json.dump(summary, f, indent=2)
        self._fh.close()
        return str(self.summary_file)
