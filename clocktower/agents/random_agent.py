"""
random_agent.py
---------------
A simple rule-free random agent for smoke-testing the engine
without incurring any LLM API costs.

Evil agents are slightly smarter: they avoid killing/nominating
each other.
"""

from __future__ import annotations

import random
from typing import Optional

from clocktower.agents.base_agent import BaseAgent


class RandomAgent(BaseAgent):
    """
    Makes all decisions randomly (with minor Evil team awareness).
    Useful for smoke-testing the game engine.
    """

    def __init__(self, name: str):
        super().__init__(name)
        self.evil_team_ids: list[str] = []
        self.known_deaths: list[str] = []
        self.suspicion: dict[str, float] = {}

    def on_evil_briefing(self, evil_summary: list[dict]):
        self.evil_team_ids = [p["player_id"] for p in evil_summary]

    def on_player_died(self, player_id: str, player_name: str):
        self.known_deaths.append(player_id)

    def choose_night_target(
        self,
        action: str,
        valid_targets: list[str],
        public_state: dict,
    ) -> str:
        if self.my_team == "evil" and action in ("kill", "poison"):
            safe = [t for t in valid_targets if t not in self.evil_team_ids]
            if safe:
                return random.choice(safe)
        return random.choice(valid_targets)

    def choose_two_targets(
        self,
        action: str,
        valid_targets: list[str],
        public_state: dict,
    ) -> tuple[str, str]:
        chosen = random.sample(valid_targets, min(2, len(valid_targets)))
        return chosen[0], chosen[1]

    def discuss(
        self,
        public_state: dict,
        discussion_history: list[dict],
        round_number: int,
        is_dead: bool = False,
    ) -> Optional[str]:
        if is_dead and random.random() < 0.5:
            return None

        options = [
            "I think we should be suspicious of the players who haven't spoken much.",
            "I have some information but I'm not sure who to trust yet.",
            "Based on what I know, I believe someone at this table is lying.",
            "I'm not comfortable revealing my role just yet.",
            "I think we should execute today — every day we wait, Evil gets stronger.",
        ]
        return random.choice(options)

    def nominate(
        self,
        valid_nominees: list[str],
        public_state: dict,
        discussion_history: list[dict],
    ) -> Optional[str]:
        if random.random() < 0.4:
            return None

        if self.my_team == "evil":
            safe = [t for t in valid_nominees if t not in self.evil_team_ids]
            if safe:
                return random.choice(safe)

        return random.choice(valid_nominees)

    def vote(
        self,
        nominee_id: str,
        nominator_id: str,
        public_state: dict,
        discussion_history: list[dict],
    ) -> bool:
        if self.my_team == "evil":
            if nominee_id in self.evil_team_ids:
                return False

        return random.random() < 0.5

    def reflect(
        self,
        game_result: str,
        final_state: dict,
        my_role: str,
    ) -> Optional[str]:
        outcome = "won" if (
            (game_result == "good" and self.my_team == "good") or
            (game_result == "evil" and self.my_team == "evil")
        ) else "lost"
        return f"I played as {my_role} and {outcome}. (Random agent — no strategy.)"
