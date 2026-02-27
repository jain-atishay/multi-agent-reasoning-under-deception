"""
base_agent.py
-------------
Abstract interface all agents must implement.

The Storyteller only talks to agents through this interface.
Implement a subclass for:
  - LLM agents (see llm_agent.py)
  - Rule-based bots (for testing)
  - Human input (for experiments)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BaseAgent(ABC):
    """
    Abstract base for all Blood on the Clocktower player agents.

    The Storyteller calls these methods at appropriate game moments.
    Agents return structured responses (usually player IDs or messages).
    """

    def __init__(self, name: str):
        self.name = name
        self.player_id: Optional[str] = None

        self.env_description: Optional[dict] = None
        self.my_role: Optional[str] = None
        self.my_team: Optional[str] = None
        self.role_description: Optional[str] = None
        self.night_infos: list[dict] = []
        self.memory_buffer: list[str] = []

    def on_role_assigned(
        self,
        player_id: str,
        role_name: str,
        role_description: str,
        team: str,
    ):
        self.player_id = player_id
        self.my_role = role_name
        self.my_team = team
        self.role_description = role_description

    def on_evil_briefing(self, evil_summary: list[dict]):
        pass

    def on_night_info(self, info_type: str, content: dict):
        self.night_infos.append({"info_type": info_type, "content": content})

    def on_environment_described(self, env: dict):
        self.env_description = env

    def on_player_died(self, player_id: str, player_name: str):
        pass

    @abstractmethod
    def choose_night_target(
        self,
        action: str,
        valid_targets: list[str],
        public_state: dict,
    ) -> str:
        """Choose a single player ID as a night-action target."""

    def choose_two_targets(
        self,
        action: str,
        valid_targets: list[str],
        public_state: dict,
    ) -> tuple[str, str]:
        import random
        chosen = random.sample(valid_targets, min(2, len(valid_targets)))
        return chosen[0], chosen[1]

    @abstractmethod
    def discuss(
        self,
        public_state: dict,
        discussion_history: list[dict],
        round_number: int,
        is_dead: bool = False,
    ) -> Optional[str]:
        """Generate a public discussion message. Return None to stay silent."""

    @abstractmethod
    def nominate(
        self,
        valid_nominees: list[str],
        public_state: dict,
        discussion_history: list[dict],
    ) -> Optional[str]:
        """Choose a player to nominate for execution, or None to skip."""

    @abstractmethod
    def vote(
        self,
        nominee_id: str,
        nominator_id: str,
        public_state: dict,
        discussion_history: list[dict],
    ) -> bool:
        """Return True to vote for execution, False to pass."""

    def reflect(
        self,
        game_result: str,
        final_state: dict,
        my_role: str,
    ) -> Optional[str]:
        """Post-game reflection for learning."""
        return None
