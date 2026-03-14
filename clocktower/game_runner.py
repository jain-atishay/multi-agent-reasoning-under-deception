"""
game_runner.py
--------------
Implements the exact architecture from the diagram.
"""

from __future__ import annotations

import time
from typing import Optional, Callable

from clocktower.storyteller import Storyteller, ROLE_COUNTS
from clocktower.game_state import GameState, Player
from clocktower.stats import GameStats, GameRecord
from clocktower.logger import GameLogger
from clocktower.agents.base_agent import BaseAgent


class HumanInTheLoop:
    """
    Pause point inserted after voting each day, before the game
    checks win conditions.

    Modes:
      "none"        – no pause (fully automated)
      "print"       – print state then continue automatically after delay
      "interactive" – wait for human to press Enter (or type commands)
      "callback"    – call a custom function (for GUI/web integration)
    """

    def __init__(
        self,
        mode: str = "none",
        delay_seconds: float = 1.0,
        callback: Optional[Callable[[GameState, dict], None]] = None,
    ):
        assert mode in ("none", "print", "interactive", "callback")
        self.mode = mode
        self.delay = delay_seconds
        self.callback = callback

    def pause(self, state: GameState, context: dict):
        if self.mode == "none":
            return

        self._print_snapshot(state, context)

        if self.mode == "print":
            time.sleep(self.delay)

        elif self.mode == "interactive":
            self._interactive_prompt(state, context)

        elif self.mode == "callback" and self.callback:
            self.callback(state, context)

    def _print_snapshot(self, state: GameState, context: dict):
        print("\n" + "─" * 50)
        print(f"  [HUMAN-IN-THE-LOOP] Round {context.get('round')} — After Voting")
        print("─" * 50)
        print("  Alive players:")
        for p in state.alive_players:
            print(f"    {p.name:12s}  seat={p.seat}  role=???")
        print("  Dead players:")
        for p in state.dead_players:
            print(f"    {p.name:12s}  role={p.role.name}")
        print(f"  Vote tally: {context.get('vote_tally', {})}")
        print("─" * 50)

    def _interactive_prompt(self, state: GameState, context: dict):
        print("\nCommands: [enter] continue | [r] reveal all roles | [q] quit game")
        while True:
            cmd = input("  > ").strip().lower()
            if cmd == "":
                break
            elif cmd == "r":
                print("  [ROLES REVEALED]")
                for p in state.players:
                    print(f"    {p.name:12s}  {p.role.name:18s}  {'alive' if p.is_alive else 'dead'}")
            elif cmd == "q":
                raise KeyboardInterrupt("Human quit the game.")
            else:
                print("  Unknown command.")


class GameRunner:
    """
    Orchestrates multi-game runs following the architecture diagram.
    """

    def __init__(
        self,
        agent_factory: Callable[[], list[BaseAgent]],
        num_games: int = 1,
        stats_path: str = "logs/stats.json",
        log_dir: str = "logs",
        max_rounds: int = 12,
        human_in_the_loop: Optional[HumanInTheLoop] = None,
        agent_variant: str = "random",
        random_seed: Optional[int] = None,
        verbose: bool = True,
    ):
        self.agent_factory = agent_factory
        self.num_games = num_games
        self.stats_path = stats_path
        self.log_dir = log_dir
        self.max_rounds = max_rounds
        self.hitl = human_in_the_loop or HumanInTheLoop(mode="none")
        self.agent_variant = agent_variant
        self.random_seed = random_seed
        self.verbose = verbose

        self.stats = GameStats.load(stats_path)

    def run(self) -> GameStats:
        print(f"\n{'═'*50}")
        print(f"  Starting {self.num_games} game(s)  |  variant={self.agent_variant}")
        print(f"{'═'*50}")

        for game_num in range(1, self.num_games + 1):
            game_id = f"{self.agent_variant}_{game_num:04d}"

            if self.verbose:
                print(f"\n[Runner] ── Game {game_num}/{self.num_games}  (id={game_id}) ──")

            seed = self.random_seed + game_num if self.random_seed is not None else None

            agents = self.agent_factory()

            storyteller = _InstrumentedStoryteller(
                agents=agents,
                game_id=game_id,
                log_dir=self.log_dir,
                max_rounds=self.max_rounds,
                random_seed=seed,
                hitl=self.hitl,
                verbose=self.verbose,
            )

            winner = storyteller.run_game()

            record = storyteller.build_game_record(self.agent_variant)
            self.stats.update(record)
            self.stats.save(self.stats_path)

            if self.verbose:
                print(f"\n[Runner] Game {game_num} complete. Winner: {winner.upper()}")
                print(f"[Runner] Running stats → Evil win rate: {self.stats.evil_win_rate:.1%} "
                      f"({self.stats.evil_wins}/{self.stats.games_played})")

        print("\n" + self.stats.summary())
        return self.stats


class _InstrumentedStoryteller(Storyteller):
    """
    Extends Storyteller with:
      1. Human-in-the-loop pause after each day's voting
      2. Environment description broadcast to agents at Day 1
      3. vote/nomination tracking for stats
    """

    def __init__(self, *args, hitl: HumanInTheLoop, verbose: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.hitl = hitl
        self.verbose = verbose
        self._vote_tracking: list[dict] = []
        self._nomination_tracking: list[dict] = []

    def run_game(self) -> str:
        self._setup()
        self.logger.log_setup(self.state)

        self._broadcast_environment_description()

        self._last_vote_tally = {}
        self._last_nominated = None

        while self.state.winner is None and self.state.round_number < self.max_rounds:
            self.state.round_number += 1

            self._start_new_day()

            if self.state.winner:
                break

            self._run_discussion(self.state.round_number)

            self._run_nominations(self.state.round_number)

            self.hitl.pause(self.state, {
                "round": self.state.round_number,
                "vote_tally": getattr(self, "_last_vote_tally", {}),
                "nominated": getattr(self, "_last_nominated", None),
            })

            self._check_evil_win()
            if self.state.winner:
                break

            self._run_night_inner()

        if self.state.winner is None:
            self.state.winner = "evil"
            self.logger.log_game_end("evil", "max_rounds_exceeded", self.state.round_number)

        self._collect_reflections()
        summary_path = self.logger.finalize(self.state)

        if self.verbose:
            print(f"[Storyteller] Game over. Winner: {self.state.winner}. Log: {summary_path}")

        return self.state.winner

    def _broadcast_environment_description(self):
        n = len(self.state.players)
        seated = sorted(self.state.players, key=lambda p: p.seat)
        seat_order = [p.name for p in seated]

        tf, out, mi, de = ROLE_COUNTS.get(n, (0, 0, 0, 0))

        env_description = {
            "num_players": n,
            "seat_order": seat_order,
            "role_composition": {
                "townsfolk": tf,
                "outsiders": out,
                "minions": mi,
                "demons": de,
            },
            "script": "Trouble Brewing",
            "rules_summary": (
                "Good wins by executing the Demon. "
                "Evil wins if only 2 players remain alive with the Demon. "
                "Each day, players discuss then vote on one execution. "
                "Each night, the Demon kills and roles with night abilities act."
            ),
        }

        for agent in self.agents:
            agent.on_environment_described(env_description)

        if self.verbose:
            print(f"[Storyteller] Environment broadcast: {n} players, seats: {seat_order}")

    def _start_new_day(self):
        self.state.phase = "day"
        self.logger.log_phase_start("day", self.state.round_number)

        if self.verbose:
            print(f"\n[Storyteller] ── Day {self.state.round_number} ──")

        self._check_mayor_win()

    def _run_night_inner(self):
        self.state.phase = "night"
        self.logger.log_phase_start("night", self.state.round_number)

        if self.verbose:
            print(f"\n[Storyteller] ── Night {self.state.round_number} ──")

        for p in self.state.players:
            p.is_poisoned = False
            p.is_protected = False

        self._collect_night_actions(self.state.round_number)
        self._resolve_night_actions(self.state.round_number)
        self._deliver_night_info(self.state.round_number)
        self._check_evil_win()

    def _collect_votes(self, nominator, nominee, round_number):
        vote_count = super()._collect_votes(nominator, nominee, round_number)

        evil_ids = {p.player_id for p in self.state.evil_players}
        self._nomination_tracking.append({
            "round": round_number,
            "nominator": nominator.player_id,
            "nominee": nominee.player_id,
            "nominee_was_evil": nominee.player_id in evil_ids,
            "resulted_in_execution": False,
        })
        self._last_nominated = nominee.player_id
        self._last_vote_tally = {nominee.player_id: vote_count}

        return vote_count

    def _execute_player(self, player_id, vote_tallies, round_number):
        super()._execute_player(player_id, vote_tallies, round_number)

        for nom in reversed(self._nomination_tracking):
            if nom["nominee"] == player_id and nom["round"] == round_number:
                nom["resulted_in_execution"] = True
                break

    def build_game_record(self, variant: str) -> GameRecord:
        evil_ids = {p.player_id for p in self.state.evil_players}
        total_votes = 0
        correct_votes = 0

        for e in self.logger._events:
            if e.get("event") == "vote" and e.get("vote"):
                total_votes += 1
                if e.get("nominee_id") in evil_ids:
                    correct_votes += 1

        demon = next((p for p in self.state.players if p.role.role_type == "demon"), None)
        demon_executed = (
            self.state.winner == "good" and
            demon is not None and not demon.is_alive
        )

        role_survivals = {
            p.role.name: p.is_alive for p in self.state.players
        }

        # Deductive Ability (proposal): collect (role, player_id, message) for embeddings
        player_id_to_role = {p.player_id: p.role.name for p in self.state.players}
        reasoning_samples = []
        for e in self.logger._events:
            if e.get("event") == "discussion":
                pid = e.get("player_id")
                role = player_id_to_role.get(pid, "Unknown")
                reasoning_samples.append({
                    "role": role,
                    "player_id": pid,
                    "message": e.get("message", ""),
                })

        # Theory-of-mind belief metrics (from LLM agents if available)
        belief_samples = []
        belief_eval_count = 0
        belief_correct_count = 0
        belief_brier_total = 0.0
        belief_role_eval_count = 0
        belief_role_correct_count = 0

        player_id_to_team = {p.player_id: p.role.team for p in self.state.players}
        player_id_to_role = {p.player_id: p.role.name for p in self.state.players}

        for agent in self.agents:
            beliefs = getattr(agent, "player_beliefs", None)
            if not isinstance(beliefs, dict) or not beliefs:
                continue
            observer_id = getattr(agent, "player_id", None)
            observer_name = getattr(agent, "name", None)
            for target_id, belief in beliefs.items():
                if target_id == observer_id:
                    continue
                if target_id not in player_id_to_team:
                    continue
                evil_prob = float(belief.get("evil_prob", 0.5))
                actual_evil = player_id_to_team[target_id] == "evil"
                predicted_evil = evil_prob >= 0.5
                brier = (evil_prob - (1.0 if actual_evil else 0.0)) ** 2
                belief_eval_count += 1
                belief_correct_count += 1 if predicted_evil == actual_evil else 0
                belief_brier_total += brier

                role_guess = belief.get("role_guess")
                actual_role = player_id_to_role[target_id]
                if role_guess:
                    belief_role_eval_count += 1
                    belief_role_correct_count += 1 if role_guess == actual_role else 0

                belief_samples.append({
                    "observer_id": observer_id,
                    "observer_name": observer_name,
                    "target_id": target_id,
                    "evil_prob": evil_prob,
                    "predicted_evil": predicted_evil,
                    "actual_evil": actual_evil,
                    "role_guess": role_guess,
                    "actual_role": actual_role,
                })

        return GameRecord(
            game_id=self.game_id,
            winner=self.state.winner or "unknown",
            rounds_played=self.state.round_number,
            num_players=len(self.state.players),
            demon_executed=demon_executed,
            total_votes=total_votes,
            correct_votes=correct_votes,
            nominations=self._nomination_tracking,
            role_survivals=role_survivals,
            agent_variant=variant,
            reasoning_samples=reasoning_samples,
            belief_samples=belief_samples,
            belief_eval_count=belief_eval_count,
            belief_correct_count=belief_correct_count,
            belief_brier_total=belief_brier_total,
            belief_role_eval_count=belief_role_eval_count,
            belief_role_correct_count=belief_role_correct_count,
        )
