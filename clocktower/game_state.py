"""
game_state.py
-------------
Core data models: Player and GameState.

GameState is the single source of truth for the engine.
The Storyteller reads/writes it; Agents receive filtered views.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from clocktower.roles import Role


# ─────────────────────────────────────────────
# Player
# ─────────────────────────────────────────────

@dataclass
class Player:
    player_id: str          # "p0", "p1", …
    name: str               # Human-readable name / agent name
    role: "Role"

    # Status
    is_alive: bool = True
    has_ghost_vote: bool = True     # Dead players get one ghost vote

    # Poisoning / drunk
    is_poisoned: bool = False       # Set by Poisoner each night
    is_drunk: bool = False          # Permanent for Drunk outsider

    # Night-specific protection
    is_protected: bool = False      # Set by Monk each night

    # Role-specific flags
    slayer_used: bool = False       # Slayer has already fired
    virgin_triggered: bool = False  # Virgin's ability has fired

    # Butler state
    butler_master: Optional[str] = None   # player_id of master

    # Fortune Teller red herring (one player always pings as demon)
    is_red_herring: bool = False

    # Seat index in the circle (for Chef / Empath neighbour logic)
    seat: int = 0

    def __repr__(self):
        status = "alive" if self.is_alive else "dead"
        return f"Player({self.name}, {self.role.name}, {status})"

    @property
    def info_is_reliable(self) -> bool:
        """False if the player is drunk or poisoned (info should be faked)."""
        return not (self.is_drunk or self.is_poisoned)

    @property
    def can_vote(self) -> bool:
        if self.is_alive:
            return True
        # Dead players may spend their one ghost vote
        return self.has_ghost_vote


# ─────────────────────────────────────────────
# NightInfo  –  what was delivered to a player on a given night
# ─────────────────────────────────────────────

@dataclass
class NightInfo:
    night: int
    player_id: str
    info_type: str      # "chef", "washerwoman", "empath", "demon_ping", etc.
    content: dict       # Flexible payload — see storyteller.py for schemas
    was_reliable: bool  # Stored for logging / post-hoc analysis


# ─────────────────────────────────────────────
# DayEvent  –  execution / slayer kill / death log
# ─────────────────────────────────────────────

@dataclass
class DayEvent:
    day: int
    event_type: str     # "execution" | "slayer_kill" | "saint_triggered" | "mayor_win"
    target_id: str
    votes: dict = field(default_factory=dict)   # player_id → True/False


# ─────────────────────────────────────────────
# NightEvent  –  kills, protections, poison
# ─────────────────────────────────────────────

@dataclass
class NightEvent:
    night: int
    event_type: str     # "demon_kill" | "monk_protect" | "poisoner_poison" | "ravenkeeper_info" | "imp_starpass"
    actor_id: str
    target_id: str
    extra: dict = field(default_factory=dict)


# ─────────────────────────────────────────────
# GameState
# ─────────────────────────────────────────────

@dataclass
class GameState:
    players: list[Player] = field(default_factory=list)

    round_number: int = 0           # Current round (day/night cycle)
    phase: str = "setup"            # "setup" | "night" | "day" | "ended"
    winner: Optional[str] = None    # "good" | "evil" | None

    night_infos: list[NightInfo] = field(default_factory=list)
    night_events: list[NightEvent] = field(default_factory=list)
    day_events: list[DayEvent] = field(default_factory=list)

    # Discussion log: list of {"round": int, "phase": str, "player_id": str, "message": str}
    discussion_log: list[dict] = field(default_factory=list)

    # Pending actions collected during the current night (before resolution)
    pending_night_actions: list[dict] = field(default_factory=list)

    def get_player(self, player_id: str) -> Optional[Player]:
        for p in self.players:
            if p.player_id == player_id:
                return p
        return None

    def get_player_by_name(self, name: str) -> Optional[Player]:
        for p in self.players:
            if p.name == name:
                return p
        return None

    @property
    def alive_players(self) -> list[Player]:
        return [p for p in self.players if p.is_alive]

    @property
    def dead_players(self) -> list[Player]:
        return [p for p in self.players if not p.is_alive]

    @property
    def demon_player(self) -> Optional[Player]:
        for p in self.players:
            if p.role.role_type == "demon" and p.is_alive:
                return p
        return None

    @property
    def evil_players(self) -> list[Player]:
        return [p for p in self.players if p.role.team == "evil"]

    def living_neighbours(self, player: Player) -> tuple[Optional[Player], Optional[Player]]:
        """
        Returns the two closest living neighbours in seat order
        (wrapping around). Used by Empath.
        """
        alive = sorted(self.alive_players, key=lambda p: p.seat)
        idx = next((i for i, p in enumerate(alive) if p.player_id == player.player_id), None)
        if idx is None or len(alive) < 2:
            return None, None
        left  = alive[(idx - 1) % len(alive)]
        right = alive[(idx + 1) % len(alive)]
        return left, right

    def seated_neighbours(self, player: Player) -> tuple[Optional[Player], Optional[Player]]:
        """
        Returns the two seated neighbours (including dead) in seat order.
        Used by Chef.
        """
        seated = sorted(self.players, key=lambda p: p.seat)
        idx = next((i for i, p in enumerate(seated) if p.player_id == player.player_id), None)
        if idx is None:
            return None, None
        left  = seated[(idx - 1) % len(seated)]
        right = seated[(idx + 1) % len(seated)]
        return left, right

    def add_discussion(self, player_id: str, message: str):
        self.discussion_log.append({
            "round": self.round_number,
            "phase": self.phase,
            "player_id": player_id,
            "message": message,
        })

    def to_public_dict(self) -> dict:
        """
        Returns the publicly visible game state (no hidden roles).
        This is what agents receive.
        """
        return {
            "round": self.round_number,
            "phase": self.phase,
            "players": [
                {
                    "player_id": p.player_id,
                    "name": p.name,
                    "is_alive": p.is_alive,
                    "has_ghost_vote": p.has_ghost_vote,
                    "seat": p.seat,
                    # Role only revealed if dead (common rule variant: revealed on execution)
                    "role": p.role.name if not p.is_alive else "unknown",
                }
                for p in self.players
            ],
            "winner": self.winner,
        }

    def to_full_dict(self) -> dict:
        """
        Full game state including all hidden info.
        Used only for logging/analysis — never shown to agents.
        """
        return {
            "round": self.round_number,
            "phase": self.phase,
            "players": [
                {
                    "player_id": p.player_id,
                    "name": p.name,
                    "role": p.role.name,
                    "team": p.role.team,
                    "is_alive": p.is_alive,
                    "is_poisoned": p.is_poisoned,
                    "is_protected": p.is_protected,
                    "is_drunk": p.is_drunk,
                    "is_red_herring": p.is_red_herring,
                    "seat": p.seat,
                }
                for p in self.players
            ],
            "winner": self.winner,
        }
