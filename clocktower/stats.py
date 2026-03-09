"""
stats.py
--------
Tracks statistics across multiple games.
Updated after each game ends, persisted to JSON.

Metrics tracked:
  - Win rates (good / evil)
  - Demon win rate (target: 25-40% per proposal)
  - Vote accuracy (% of votes that correctly targeted demon/minion)
  - Correct nomination rate
  - Survival rates by role
  - Per-agent performance
  - reasoning_samples for Deductive Ability (role-to-reasoning semantic similarity)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class GameRecord:
    game_id: str
    winner: str                     # "good" | "evil"
    rounds_played: int
    num_players: int
    demon_executed: bool            # Did good correctly execute demon?
    total_votes: int
    correct_votes: int              # Votes cast against actual evil players
    nominations: list[dict]         # {nominator, nominee, nominee_was_evil, resulted_in_execution}
    role_survivals: dict[str, bool] # role_name → survived to end?
    agent_variant: str              # "baseline" | "strategic" | etc.
    # For Deductive Ability (proposal): role-to-reasoning semantic similarity
    # Each item: {role, player_id, message} — use embeddings for post-hoc analysis
    reasoning_samples: list[dict] = field(default_factory=list)
    # Theory of Mind metrics
    belief_metrics: dict = field(default_factory=dict)  # Per-agent belief accuracy metrics


@dataclass
class GameStats:
    """
    Persistent statistics updated after every game.
    Call update(game_record) after each game.
    """
    games_played: int = 0
    good_wins: int = 0
    evil_wins: int = 0

    total_votes_cast: int = 0
    correct_votes: int = 0         # Votes against actual evil players

    total_nominations: int = 0
    evil_nominations: int = 0      # Nominations of actual evil players
    executions: int = 0
    correct_executions: int = 0    # Executions of actual evil players

    demon_executions: int = 0      # Times demon specifically was executed
    avg_rounds: float = 0.0

    # Per-role survival: role_name → [survived_count, total_count]
    role_survival: dict[str, list[int]] = field(default_factory=dict)

    # Per-variant performance: variant → {good_wins, evil_wins, games}
    variant_performance: dict[str, dict] = field(default_factory=dict)

    # History of all game records (for deep analysis)
    game_history: list[dict] = field(default_factory=list)
    
    # Theory of Mind aggregate metrics
    avg_role_accuracy: float = 0.0
    avg_team_accuracy: float = 0.0
    avg_suspicion_correlation: float = 0.0

    def update(self, record: GameRecord):
        self.games_played += 1
        if record.winner == "good":
            self.good_wins += 1
        else:
            self.evil_wins += 1

        if record.demon_executed:
            self.demon_executions += 1

        self.total_votes_cast += record.total_votes
        self.correct_votes += record.correct_votes

        for nom in record.nominations:
            self.total_nominations += 1
            if nom.get("nominee_was_evil"):
                self.evil_nominations += 1
            if nom.get("resulted_in_execution"):
                self.executions += 1
                if nom.get("nominee_was_evil"):
                    self.correct_executions += 1

        for role_name, survived in record.role_survivals.items():
            if role_name not in self.role_survival:
                self.role_survival[role_name] = [0, 0]
            self.role_survival[role_name][1] += 1
            if survived:
                self.role_survival[role_name][0] += 1

        # Running average rounds
        self.avg_rounds = (
            (self.avg_rounds * (self.games_played - 1) + record.rounds_played)
            / self.games_played
        )

        # Variant performance
        v = record.agent_variant
        if v not in self.variant_performance:
            self.variant_performance[v] = {"good_wins": 0, "evil_wins": 0, "games": 0}
        self.variant_performance[v]["games"] += 1
        self.variant_performance[v][f"{record.winner}_wins"] += 1

        self.game_history.append({
            "game_id": record.game_id,
            "winner": record.winner,
            "rounds": record.rounds_played,
            "demon_executed": record.demon_executed,
            "variant": record.agent_variant,
            "reasoning_samples": record.reasoning_samples,  # for Deductive Ability analysis
            "belief_metrics": record.belief_metrics,  # Theory of Mind metrics
        })
        
        # Update belief accuracy running averages
        if record.belief_metrics:
            # Aggregate belief metrics across all agents in this game
            role_accs = [m.get("role_accuracy", 0) for m in record.belief_metrics.values() if m.get("belief_count", 0) > 0]
            team_accs = [m.get("team_accuracy", 0) for m in record.belief_metrics.values() if m.get("belief_count", 0) > 0]
            susp_corrs = [m.get("suspicion_correlation", 0) for m in record.belief_metrics.values() if m.get("belief_count", 0) > 0]
            
            if role_accs:
                game_role_acc = sum(role_accs) / len(role_accs)
                self.avg_role_accuracy = (
                    (self.avg_role_accuracy * (self.games_played - 1) + game_role_acc)
                    / self.games_played
                )
            
            if team_accs:
                game_team_acc = sum(team_accs) / len(team_accs)
                self.avg_team_accuracy = (
                    (self.avg_team_accuracy * (self.games_played - 1) + game_team_acc)
                    / self.games_played
                )
            
            if susp_corrs:
                game_susp_corr = sum(susp_corrs) / len(susp_corrs)
                self.avg_suspicion_correlation = (
                    (self.avg_suspicion_correlation * (self.games_played - 1) + game_susp_corr)
                    / self.games_played
                )

    # ── Derived metrics ────────────────────────────────────────

    @property
    def evil_win_rate(self) -> float:
        return self.evil_wins / self.games_played if self.games_played > 0 else 0.0

    @property
    def good_win_rate(self) -> float:
        return self.good_wins / self.games_played if self.games_played > 0 else 0.0

    @property
    def vote_accuracy(self) -> float:
        """% of votes cast against actual evil players."""
        return self.correct_votes / self.total_votes_cast if self.total_votes_cast > 0 else 0.0

    @property
    def nomination_accuracy(self) -> float:
        """% of nominations targeting actual evil players."""
        return self.evil_nominations / self.total_nominations if self.total_nominations > 0 else 0.0

    @property
    def execution_accuracy(self) -> float:
        """% of executions that killed an evil player."""
        return self.correct_executions / self.executions if self.executions > 0 else 0.0

    def summary(self) -> str:
        lines = [
            f"═══════════════════════════════════════",
            f"  GAME STATISTICS ({self.games_played} games played)",
            f"═══════════════════════════════════════",
            f"  Evil win rate:        {self.evil_win_rate:.1%}  (target: 25–40%)",
            f"  Good win rate:        {self.good_win_rate:.1%}",
            f"  Demon executions:     {self.demon_executions}/{self.games_played}",
            f"  Avg rounds per game:  {self.avg_rounds:.1f}",
            f"",
            f"  Vote accuracy:        {self.vote_accuracy:.1%}",
            f"  Nomination accuracy:  {self.nomination_accuracy:.1%}",
            f"  Execution accuracy:   {self.execution_accuracy:.1%}",
        ]
        
        # Add Theory of Mind metrics if available
        if self.avg_role_accuracy > 0 or self.avg_team_accuracy > 0:
            lines.append("")
            lines.append("  Theory of Mind (Belief Accuracy):")
            lines.append(f"    Role accuracy:       {self.avg_role_accuracy:.1%}")
            lines.append(f"    Team accuracy:       {self.avg_team_accuracy:.1%}")
            lines.append(f"    Suspicion corr:      {self.avg_suspicion_correlation:+.3f}")
        
        if self.variant_performance:
            lines.append("")
            lines.append("  Per-variant evil win rate:")
            for v, perf in self.variant_performance.items():
                g = perf["games"]
                ew = perf["evil_wins"] / g if g > 0 else 0
                lines.append(f"    {v:12s}: {ew:.1%} ({g} games)")
        lines.append("═══════════════════════════════════════")
        return "\n".join(lines)

    # ── Persistence ────────────────────────────────────────────

    def save(self, path: str = "logs/stats.json"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.__dict__, f, indent=2)

    @classmethod
    def load(cls, path: str = "logs/stats.json") -> "GameStats":
        try:
            with open(path) as f:
                data = json.load(f)
            s = cls()
            for k, v in data.items():
                setattr(s, k, v)
            return s
        except FileNotFoundError:
            return cls()
