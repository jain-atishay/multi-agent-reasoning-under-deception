"""
storyteller.py
--------------
The Storyteller is the game engine's core orchestrator.

Responsibilities:
  - Game setup  : assign roles, seats, red herrings, drunk
  - Night phase : wake players one at a time, compute + deliver information,
                  apply kills / poison / protection
  - Day phase   : collect nominations, tally votes, enforce executions
  - Win checks  : detect Good/Evil victory at the right moments
  - Rule edge cases: Saint execution, Mayor 3-player win, Scarlet Woman,
                     Imp star-pass, Virgin triggered execution

The Storyteller never talks to LLM agents directly — it talks to the
agent interface (BaseAgent) and delivers info via structured dicts.
"""

from __future__ import annotations

import random
from typing import Optional, TYPE_CHECKING

from clocktower.roles import (
    ALL_ROLES, Role,
    CHEF, WASHERWOMAN, LIBRARIAN, INVESTIGATOR, EMPATH, FORTUNE_TELLER,
    UNDERTAKER, MONK, RAVENKEEPER, VIRGIN, SLAYER, SOLDIER, MAYOR,
    DRUNK, RECLUSE, BUTLER, SAINT,
    POISONER, SPY, BARON, SCARLET_WOMAN, IMP,
    TOWNSFOLK_ROLES, OUTSIDER_ROLES, MINION_ROLES, DEMON_ROLES,
)
from clocktower.game_state import GameState, Player, NightInfo, NightEvent, DayEvent
from clocktower.logger import GameLogger

if TYPE_CHECKING:
    from clocktower.agents.base_agent import BaseAgent


# ─────────────────────────────────────────────
# Trouble Brewing composition tables
# ─────────────────────────────────────────────
# player_count → (townsfolk, outsiders, minions, demons)
ROLE_COUNTS = {
    5:  (3, 0, 1, 1),
    6:  (3, 1, 1, 1),
    7:  (5, 0, 1, 1),
    8:  (5, 1, 1, 1),
    9:  (5, 2, 1, 1),
    10: (7, 0, 2, 1),
    11: (7, 1, 2, 1),
    12: (7, 2, 2, 1),
    13: (9, 0, 3, 1),
    14: (9, 1, 3, 1),
    15: (9, 2, 3, 1),
}


class Storyteller:
    """
    Runs a complete game of Blood on the Clocktower (Trouble Brewing).

    Usage
    -----
        st = Storyteller(agents, game_id="game_001")
        winner = st.run_game()
    """

    def __init__(
        self,
        agents: list["BaseAgent"],
        game_id: str = "game_001",
        log_dir: str = "logs",
        max_rounds: int = 12,
        random_seed: Optional[int] = None,
    ):
        if len(agents) not in ROLE_COUNTS:
            raise ValueError(f"Unsupported player count {len(agents)}. Must be 5–15.")

        self.agents = agents
        self.game_id = game_id
        self.max_rounds = max_rounds
        self.logger = GameLogger(game_id, log_dir)

        if random_seed is not None:
            random.seed(random_seed)

        self.state = GameState()
        self._agent_map: dict[str, "BaseAgent"] = {}   # player_id → agent

    # ──────────────────────────────────────────
    # PUBLIC: Run a full game
    # ──────────────────────────────────────────

    def run_game(self) -> str:
        """Run setup + rounds until a winner is found. Returns "good" or "evil"."""
        self._setup()
        self.logger.log_setup(self.state)

        while self.state.winner is None and self.state.round_number < self.max_rounds:
            self.state.round_number += 1
            self._run_night()
            if self.state.winner:
                break
            self._run_day()

        if self.state.winner is None:
            # Max rounds hit — rule: Evil wins by default
            self.state.winner = "evil"
            self.logger.log_game_end("evil", "max_rounds_exceeded", self.state.round_number)

        self._collect_reflections()
        summary_path = self.logger.finalize(self.state)
        print(f"[Storyteller] Game over. Winner: {self.state.winner}. Log: {summary_path}")
        return self.state.winner

    # ──────────────────────────────────────────
    # SETUP
    # ──────────────────────────────────────────

    def _setup(self):
        n = len(self.agents)
        tf_count, out_count, min_count, dem_count = ROLE_COUNTS[n]

        # Check for Baron (+2 outsiders, -2 townsfolk)
        baron_in_play = random.random() < 0.4 and n >= 7

        if baron_in_play:
            tf_count -= 2
            out_count += 2

        # Sample roles
        available_tf  = [r for r in TOWNSFOLK_ROLES]
        available_out = [r for r in OUTSIDER_ROLES]
        available_min = [r for r in MINION_ROLES]

        if baron_in_play:
            available_min = [BARON] + [r for r in available_min if r != BARON]

        chosen_tf  = random.sample(available_tf, tf_count)
        chosen_out = random.sample(available_out, out_count)
        chosen_min = random.sample(available_min, min_count)
        if baron_in_play and BARON not in chosen_min:
            chosen_min[0] = BARON

        chosen_demon = [IMP]
        role_pool = chosen_tf + chosen_out + chosen_min + chosen_demon
        random.shuffle(role_pool)

        seats = list(range(n))
        random.shuffle(seats)

        for i, agent in enumerate(self.agents):
            pid = f"p{i}"
            role = role_pool[i]
            display_role = role
            if role == DRUNK:
                fake_tf = random.choice([r for r in TOWNSFOLK_ROLES if r not in chosen_tf])
                display_role = fake_tf

            player = Player(
                player_id=pid,
                name=agent.name,
                role=role,
                seat=seats[i],
                is_drunk=(role == DRUNK),
            )
            self.state.players.append(player)
            self._agent_map[pid] = agent

            agent.on_role_assigned(
                player_id=pid,
                role_name=display_role.name,
                role_description=display_role.description,
                team=role.team,
            )

        non_demon = [p for p in self.state.players if p.role != IMP]
        if non_demon:
            rh = random.choice(non_demon)
            rh.is_red_herring = True

        self._brief_evil_team()
        self.state.phase = "night"
        print(f"[Storyteller] Setup complete. {n} players. Evil: "
              f"{[p.name for p in self.state.evil_players]}")

    def _brief_evil_team(self):
        evil_summary = [
            {"player_id": p.player_id, "name": p.name, "role": p.role.name}
            for p in self.state.evil_players
        ]
        for p in self.state.evil_players:
            agent = self._agent_map[p.player_id]
            agent.on_evil_briefing(evil_summary)

    # ──────────────────────────────────────────
    # NIGHT PHASE
    # ──────────────────────────────────────────

    def _run_night(self):
        n = self.state.round_number
        self.state.phase = "night"
        self.logger.log_phase_start("night", n)
        print(f"\n[Storyteller] ── Night {n} ──")

        for p in self.state.players:
            p.is_poisoned = False
            p.is_protected = False

        self._collect_night_actions(n)
        self._resolve_night_actions(n)
        self._deliver_night_info(n)
        self._check_evil_win()

    def _collect_night_actions(self, night: int):
        self.state.pending_night_actions.clear()
        alive = sorted(self.state.alive_players, key=lambda p: p.seat)
        wake_order_roles = ["Poisoner", "Spy", "Monk", "Butler", "Imp"]

        for role_name in wake_order_roles:
            player = next((p for p in alive if p.role.name == role_name), None)
            if player is None:
                continue

            agent = self._agent_map[player.player_id]
            public_state = self.state.to_public_dict()

            if role_name == "Poisoner":
                targets = [p.player_id for p in alive if p.player_id != player.player_id]
                target_id = agent.choose_night_target(
                    action="poison", valid_targets=targets, public_state=public_state
                )
                self.state.pending_night_actions.append(
                    {"role": "Poisoner", "actor": player.player_id, "target": target_id}
                )
            elif role_name == "Spy":
                pass
            elif role_name == "Monk" and night > 1:
                targets = [p.player_id for p in alive if p.player_id != player.player_id]
                target_id = agent.choose_night_target(
                    action="protect", valid_targets=targets, public_state=public_state
                )
                self.state.pending_night_actions.append(
                    {"role": "Monk", "actor": player.player_id, "target": target_id}
                )
            elif role_name == "Butler":
                targets = [p.player_id for p in alive if p.player_id != player.player_id]
                master_id = agent.choose_night_target(
                    action="choose_master", valid_targets=targets, public_state=public_state
                )
                player.butler_master = master_id
                self.state.pending_night_actions.append(
                    {"role": "Butler", "actor": player.player_id, "target": master_id}
                )
            elif role_name == "Imp" and night > 1:
                targets = [p.player_id for p in alive if p.player_id != player.player_id]
                target_id = agent.choose_night_target(
                    action="kill", valid_targets=targets, public_state=public_state
                )
                self.state.pending_night_actions.append(
                    {"role": "Imp", "actor": player.player_id, "target": target_id}
                )

        ft_player = next((p for p in alive if p.role.name == "Fortune Teller"), None)
        if ft_player:
            targets = [p.player_id for p in alive if p.player_id != ft_player.player_id]
            if len(targets) >= 2:
                chosen = self._agent_map[ft_player.player_id].choose_two_targets(
                    action="divine", valid_targets=targets,
                    public_state=self.state.to_public_dict()
                )
                self.state.pending_night_actions.append(
                    {"role": "Fortune Teller", "actor": ft_player.player_id,
                     "target_a": chosen[0], "target_b": chosen[1]}
                )

    def _resolve_night_actions(self, night: int):
        for action in self.state.pending_night_actions:
            if action["role"] == "Poisoner":
                target = self.state.get_player(action["target"])
                if target:
                    target.is_poisoned = True
                    self.logger.log_night_action(action["actor"], "poison", action["target"])
                    ne = NightEvent(night, "poisoner_poison", action["actor"], action["target"])
                    self.state.night_events.append(ne)

        for action in self.state.pending_night_actions:
            if action["role"] == "Monk":
                target = self.state.get_player(action["target"])
                if target:
                    target.is_protected = True
                    self.logger.log_night_action(action["actor"], "protect", action["target"])
                    ne = NightEvent(night, "monk_protect", action["actor"], action["target"])
                    self.state.night_events.append(ne)

        if night > 1:
            for action in self.state.pending_night_actions:
                if action["role"] == "Imp":
                    target = self.state.get_player(action["target"])
                    if target:
                        self._apply_demon_kill(target, action["actor"], night)

    def _apply_demon_kill(self, target: Player, actor_id: str, night: int):
        actor = self.state.get_player(actor_id)

        if actor and target.player_id == actor_id:
            self._imp_starpass(actor, night)
            return

        if target.role == SOLDIER:
            print(f"[Storyteller] {target.name} (Soldier) is immune to the Demon kill.")
            self.logger.log_night_action(actor_id, "demon_kill_blocked_soldier", target.player_id)
            return

        if target.is_protected:
            print(f"[Storyteller] {target.name} is protected by the Monk tonight.")
            self.logger.log_night_action(actor_id, "demon_kill_blocked_monk", target.player_id)
            return

        target.is_alive = False
        print(f"[Storyteller] {target.name} was killed by the Demon.")
        self.logger.log_death(target.player_id, "demon_kill", night)
        ne = NightEvent(night, "demon_kill", actor_id, target.player_id)
        self.state.night_events.append(ne)

        if target.role == RAVENKEEPER:
            self._ravenkeeper_trigger(target, night)

        for agent in self.agents:
            agent.on_player_died(target.player_id, target.name)

    def _imp_starpass(self, imp: Player, night: int):
        imp.is_alive = False
        self.logger.log_death(imp.player_id, "imp_starpass_self", night)
        ne = NightEvent(night, "imp_starpass", imp.player_id, imp.player_id)
        self.state.night_events.append(ne)

        living_minions = [
            p for p in self.state.alive_players if p.role.role_type == "minion"
        ]
        if living_minions:
            new_demon = random.choice(living_minions)
            new_demon.role = IMP
            print(f"[Storyteller] Imp star-passed to {new_demon.name}!")
            self._agent_map[new_demon.player_id].on_role_assigned(
                player_id=new_demon.player_id,
                role_name=IMP.name,
                role_description=IMP.description,
                team=IMP.team,
            )
        else:
            self.state.winner = "good"
            self.logger.log_game_end("good", "demon_died_no_successor", night)

    def _ravenkeeper_trigger(self, ravenkeeper: Player, night: int):
        agent = self._agent_map[ravenkeeper.player_id]
        alive_ids = [p.player_id for p in self.state.alive_players]
        if not alive_ids:
            return

        target_id = agent.choose_night_target(
            action="ravenkeeper_learn",
            valid_targets=alive_ids,
            public_state=self.state.to_public_dict(),
        )
        target = self.state.get_player(target_id)
        if target:
            info = {"target_id": target_id, "target_name": target.name, "role": target.role.name}
            agent.on_night_info("ravenkeeper", info)
            self.logger.log_info_delivery(ravenkeeper.player_id, "ravenkeeper", info, True)

    # ──────────────────────────────────────────
    # NIGHT INFO DELIVERY
    # ──────────────────────────────────────────

    def _deliver_night_info(self, night: int):
        alive = self.state.alive_players

        spy = next((p for p in alive if p.role == SPY), None)
        if spy:
            grimoire = {
                p.player_id: {"name": p.name, "role": p.role.name, "alive": p.is_alive}
                for p in self.state.players
            }
            self._agent_map[spy.player_id].on_night_info("spy_grimoire", grimoire)

        if night == 1:
            self._deliver_chef_info()
            self._deliver_washerwoman_info()
            self._deliver_librarian_info()
            self._deliver_investigator_info()

        self._deliver_empath_info()
        self._deliver_fortune_teller_info()

        if night > 1:
            self._deliver_undertaker_info()

    def _make_info_reliable(self, player: Player) -> bool:
        return player.info_is_reliable

    def _deliver_chef_info(self):
        chef = next((p for p in self.state.players if p.role == CHEF and p.is_alive), None)
        if not chef:
            return
        reliable = self._make_info_reliable(chef)
        if reliable:
            seated = sorted(self.state.players, key=lambda p: p.seat)
            count = sum(
                1 for i in range(len(seated))
                if seated[i].role.team == "evil" and seated[(i + 1) % len(seated)].role.team == "evil"
            )
        else:
            count = random.randint(0, 2)

        info = {"evil_pairs": count}
        self._agent_map[chef.player_id].on_night_info("chef", info)
        self.logger.log_info_delivery(chef.player_id, "chef", info, reliable)
        ni = NightInfo(1, chef.player_id, "chef", info, reliable)
        self.state.night_infos.append(ni)

    def _deliver_washerwoman_info(self):
        ww = next((p for p in self.state.players if p.role == WASHERWOMAN and p.is_alive), None)
        if not ww:
            return
        reliable = self._make_info_reliable(ww)
        if reliable:
            tf_players = [p for p in self.state.players if p.role.role_type == "townsfolk"]
            if not tf_players:
                return
            true_player = random.choice(tf_players)
            others = [p for p in self.state.players if p.player_id != true_player.player_id]
            decoy = random.choice(others)
            pair = [true_player.player_id, decoy.player_id]
            random.shuffle(pair)
            info = {"player_a": pair[0], "player_b": pair[1], "role_type": true_player.role.name}
        else:
            all_pids = [p.player_id for p in self.state.players if p.player_id != ww.player_id]
            pair = random.sample(all_pids, min(2, len(all_pids)))
            fake_role = random.choice([r.name for r in TOWNSFOLK_ROLES])
            info = {"player_a": pair[0], "player_b": pair[1], "role_type": fake_role}

        self._agent_map[ww.player_id].on_night_info("washerwoman", info)
        self.logger.log_info_delivery(ww.player_id, "washerwoman", info, reliable)
        ni = NightInfo(1, ww.player_id, "washerwoman", info, reliable)
        self.state.night_infos.append(ni)

    def _deliver_librarian_info(self):
        lib = next((p for p in self.state.players if p.role == LIBRARIAN and p.is_alive), None)
        if not lib:
            return
        reliable = self._make_info_reliable(lib)
        out_players = [p for p in self.state.players if p.role.role_type == "outsider"]

        if reliable:
            if not out_players:
                info = {"no_outsiders": True}
            else:
                true_player = random.choice(out_players)
                others = [p for p in self.state.players if p.player_id != true_player.player_id]
                decoy = random.choice(others)
                pair = [true_player.player_id, decoy.player_id]
                random.shuffle(pair)
                info = {"player_a": pair[0], "player_b": pair[1], "role_type": true_player.role.name}
        else:
            all_pids = [p.player_id for p in self.state.players if p.player_id != lib.player_id]
            pair = random.sample(all_pids, min(2, len(all_pids)))
            fake_role = random.choice([r.name for r in OUTSIDER_ROLES])
            info = {"player_a": pair[0], "player_b": pair[1], "role_type": fake_role}

        self._agent_map[lib.player_id].on_night_info("librarian", info)
        self.logger.log_info_delivery(lib.player_id, "librarian", info, reliable)
        ni = NightInfo(1, lib.player_id, "librarian", info, reliable)
        self.state.night_infos.append(ni)

    def _deliver_investigator_info(self):
        inv = next((p for p in self.state.players if p.role == INVESTIGATOR and p.is_alive), None)
        if not inv:
            return
        reliable = self._make_info_reliable(inv)
        minion_players = [p for p in self.state.players if p.role.role_type == "minion"]
        recluse = next((p for p in self.state.players if p.role == RECLUSE), None)

        if reliable and (minion_players or recluse):
            pool = minion_players[:]
            if recluse and random.random() < 0.5:
                pool.append(recluse)
            if not pool:
                return
            true_player = random.choice(pool)
            others = [p for p in self.state.players if p.player_id != true_player.player_id]
            decoy = random.choice(others)
            pair = [true_player.player_id, decoy.player_id]
            random.shuffle(pair)
            shown_role = true_player.role.name if true_player.role.role_type == "minion" else random.choice([r.name for r in MINION_ROLES])
            info = {"player_a": pair[0], "player_b": pair[1], "role_type": shown_role}
        else:
            all_pids = [p.player_id for p in self.state.players if p.player_id != inv.player_id]
            pair = random.sample(all_pids, min(2, len(all_pids)))
            fake_role = random.choice([r.name for r in MINION_ROLES])
            info = {"player_a": pair[0], "player_b": pair[1], "role_type": fake_role}

        self._agent_map[inv.player_id].on_night_info("investigator", info)
        self.logger.log_info_delivery(inv.player_id, "investigator", info, reliable)
        ni = NightInfo(1, inv.player_id, "investigator", info, reliable)
        self.state.night_infos.append(ni)

    def _deliver_empath_info(self):
        emp = next((p for p in self.state.alive_players if p.role == EMPATH), None)
        if not emp:
            return
        reliable = self._make_info_reliable(emp)
        if reliable:
            left, right = self.state.living_neighbours(emp)
            count = sum(
                1 for nb in [left, right]
                if nb and nb.role.team == "evil" and not (nb.role == SPY)
            )
            for nb in [left, right]:
                if nb and nb.role == RECLUSE and random.random() < 0.5:
                    count = min(count + 1, 2)
        else:
            count = random.randint(0, 2)

        info = {"evil_neighbours": count}
        self._agent_map[emp.player_id].on_night_info("empath", info)
        self.logger.log_info_delivery(emp.player_id, "empath", info, reliable)
        ni = NightInfo(self.state.round_number, emp.player_id, "empath", info, reliable)
        self.state.night_infos.append(ni)

    def _deliver_fortune_teller_info(self):
        ft = next((p for p in self.state.alive_players if p.role == FORTUNE_TELLER), None)
        if not ft:
            return
        reliable = self._make_info_reliable(ft)
        ft_action = next(
            (a for a in self.state.pending_night_actions if a["role"] == "Fortune Teller"),
            None
        )
        if not ft_action:
            return

        target_a = self.state.get_player(ft_action["target_a"])
        target_b = self.state.get_player(ft_action["target_b"])

        if reliable:
            is_demon = (
                (target_a and (target_a.role.role_type == "demon" or target_a.is_red_herring)) or
                (target_b and (target_b.role.role_type == "demon" or target_b.is_red_herring))
            )
        else:
            is_demon = random.choice([True, False])

        info = {
            "target_a": ft_action["target_a"],
            "target_b": ft_action["target_b"],
            "demon_ping": is_demon,
        }
        self._agent_map[ft.player_id].on_night_info("fortune_teller", info)
        self.logger.log_info_delivery(ft.player_id, "fortune_teller", info, reliable)
        ni = NightInfo(self.state.round_number, ft.player_id, "fortune_teller", info, reliable)
        self.state.night_infos.append(ni)

    def _deliver_undertaker_info(self):
        ut = next((p for p in self.state.alive_players if p.role == UNDERTAKER), None)
        if not ut:
            return
        reliable = self._make_info_reliable(ut)
        last_exec = next(
            (e for e in reversed(self.state.day_events) if e.event_type == "execution"),
            None
        )
        if not last_exec:
            return

        executed_player = self.state.get_player(last_exec.target_id)
        if not executed_player:
            return

        if reliable:
            shown_role = executed_player.role.name
        else:
            shown_role = random.choice(list(ALL_ROLES.keys()))

        info = {"executed_player_id": last_exec.target_id, "role": shown_role}
        self._agent_map[ut.player_id].on_night_info("undertaker", info)
        self.logger.log_info_delivery(ut.player_id, "undertaker", info, reliable)
        ni = NightInfo(self.state.round_number, ut.player_id, "undertaker", info, reliable)
        self.state.night_infos.append(ni)

    # ──────────────────────────────────────────
    # DAY PHASE
    # ──────────────────────────────────────────

    def _run_day(self):
        n = self.state.round_number
        self.state.phase = "day"
        self.logger.log_phase_start("day", n)
        print(f"\n[Storyteller] ── Day {n} ──")

        if self._check_mayor_win():
            return

        self._run_discussion(n)
        self._run_nominations(n)
        self._check_evil_win()

    def _run_discussion(self, round_number: int):
        print("[Storyteller] Discussion phase begins.")
        public_state = self.state.to_public_dict()
        discussion_history = list(self.state.discussion_log)

        # Randomize speaking order to reduce name/position bias (LLM research: last-speaker advantage)
        alive_list = list(self.state.alive_players)
        random.shuffle(alive_list)
        for player in alive_list:
            agent = self._agent_map[player.player_id]
            message = agent.discuss(
                public_state=public_state,
                discussion_history=discussion_history,
                round_number=round_number,
            )
            if message:
                self.state.add_discussion(player.player_id, message)
                discussion_history.append({
                    "round": round_number, "phase": "day",
                    "player_id": player.player_id, "message": message,
                })
                self.logger.log_discussion(player.player_id, message, round_number)
                print(f"  [{player.name}]: {message}")

        for player in self.state.dead_players:
            agent = self._agent_map[player.player_id]
            message = agent.discuss(
                public_state=public_state,
                discussion_history=discussion_history,
                round_number=round_number,
                is_dead=True,
            )
            if message:
                self.state.add_discussion(player.player_id, message)
                self.logger.log_discussion(player.player_id, message, round_number)
                print(f"  [{player.name} 👻]: {message}")

    def _run_nominations(self, round_number: int):
        print("[Storyteller] Nomination phase begins.")
        public_state = self.state.to_public_dict()
        discussion_history = list(self.state.discussion_log)

        vote_tallies: dict[str, int] = {}
        nominations_made: set[str] = set()
        nominations_received: set[str] = set()

        for nominator in self.state.alive_players:
            if nominator.player_id in nominations_made:
                continue

            agent = self._agent_map[nominator.player_id]
            valid_nominees = [
                p.player_id for p in self.state.alive_players
                if p.player_id != nominator.player_id
                and p.player_id not in nominations_received
            ]
            if not valid_nominees:
                break

            nominee_id = agent.nominate(
                valid_nominees=valid_nominees,
                public_state=public_state,
                discussion_history=discussion_history,
            )
            if nominee_id is None:
                continue

            nominee = self.state.get_player(nominee_id)
            if not nominee:
                continue

            nominations_made.add(nominator.player_id)
            nominations_received.add(nominee_id)

            self.logger.log_nomination(nominator.player_id, nominee_id, round_number)
            print(f"  [{nominator.name}] nominates [{nominee.name}]")

            if (nominee.role == VIRGIN and not nominee.virgin_triggered
                    and nominator.role.role_type == "townsfolk"):
                nominee.virgin_triggered = True
                nominator.is_alive = False
                print(f"  [Virgin] {nominator.name} is executed for nominating the Virgin!")
                self.logger.log_death(nominator.player_id, "virgin_trigger", round_number)
                for ag in self.agents:
                    ag.on_player_died(nominator.player_id, nominator.name)
                continue

            vote_count = self._collect_votes(nominator, nominee, round_number)
            vote_tallies[nominee_id] = vote_count

        if not vote_tallies:
            print("[Storyteller] No executions today.")
            return

        max_votes = max(vote_tallies.values())
        threshold = len(self.state.alive_players) / 2
        candidates = [pid for pid, v in vote_tallies.items() if v == max_votes]

        if max_votes <= threshold or len(candidates) > 1:
            print(f"[Storyteller] No execution — insufficient votes or tie.")
            return

        executed_id = candidates[0]
        self._execute_player(executed_id, vote_tallies, round_number)

    def _collect_votes(self, nominator: Player, nominee: Player, round_number: int) -> int:
        public_state = self.state.to_public_dict()
        discussion_history = list(self.state.discussion_log)
        vote_count = 0
        vote_log: dict[str, bool] = {}

        all_voters = self.state.alive_players + [
            p for p in self.state.dead_players if p.has_ghost_vote
        ]

        for voter in all_voters:
            agent = self._agent_map[voter.player_id]

            if voter.role == BUTLER and voter.butler_master:
                master = self.state.get_player(voter.butler_master)
                if master and not vote_log.get(voter.butler_master, False):
                    vote_log[voter.player_id] = False
                    continue

            vote = agent.vote(
                nominee_id=nominee.player_id,
                nominator_id=nominator.player_id,
                public_state=public_state,
                discussion_history=discussion_history,
            )

            if not voter.is_alive and vote:
                voter.has_ghost_vote = False

            vote_log[voter.player_id] = vote
            if vote:
                vote_count += 1
                self.logger.log_vote(voter.player_id, nominee.player_id, True, round_number)

        print(f"  [{nominee.name}] received {vote_count} votes "
              f"(need >{len(self.state.alive_players)/2:.1f})")
        return vote_count

    def _execute_player(self, player_id: str, vote_tallies: dict, round_number: int):
        player = self.state.get_player(player_id)
        if not player:
            return

        self.logger.log_execution(player_id, vote_tallies, round_number)
        de = DayEvent(round_number, "execution", player_id, vote_tallies)
        self.state.day_events.append(de)

        if player.role == SAINT:
            player.is_alive = False
            self.state.winner = "evil"
            print(f"[Storyteller] {player.name} (Saint) was executed — Evil wins!")
            self.logger.log_game_end("evil", "saint_executed", round_number)
            de.event_type = "saint_triggered"
            for agent in self.agents:
                agent.on_player_died(player_id, player.name)
            return

        player.is_alive = False
        print(f"[Storyteller] {player.name} ({player.role.name}) is executed!")
        self.logger.log_death(player_id, "execution", round_number)
        for agent in self.agents:
            agent.on_player_died(player_id, player.name)

        if player.role.role_type == "demon":
            self.state.winner = "good"
            print("[Storyteller] The Demon was executed — Good wins!")
            self.logger.log_game_end("good", "demon_executed", round_number)

        if player.role.role_type == "demon":
            sw = next(
                (p for p in self.state.alive_players if p.role == SCARLET_WOMAN), None
            )
            if sw and len(self.state.alive_players) >= 4:
                sw.role = IMP
                self.state.winner = None
                print(f"[Storyteller] Scarlet Woman {sw.name} becomes the new Demon!")
                self._agent_map[sw.player_id].on_role_assigned(
                    sw.player_id, IMP.name, IMP.description, IMP.team
                )

    def _check_evil_win(self):
        if self.state.winner:
            return
        alive = self.state.alive_players
        if len(alive) <= 2 and self.state.demon_player is not None:
            self.state.winner = "evil"
            print("[Storyteller] Evil wins — only the Demon and one other remain!")
            self.logger.log_game_end("evil", "demon_outlasted", self.state.round_number)

    def _check_mayor_win(self) -> bool:
        mayor = next((p for p in self.state.alive_players if p.role == MAYOR), None)
        if not mayor:
            return False
        alive = self.state.alive_players
        if len(alive) != 3:
            return False
        today_executions = [
            e for e in self.state.day_events
            if e.day == self.state.round_number and e.event_type == "execution"
        ]
        if today_executions:
            return False
        self.state.winner = "good"
        print("[Storyteller] Mayor ability triggered — Good wins with 3 alive and no execution!")
        self.logger.log_game_end("good", "mayor_win", self.state.round_number)
        return True

    def _collect_reflections(self):
        full_state = self.state.to_full_dict()
        for player in self.state.players:
            agent = self._agent_map[player.player_id]
            reflection = agent.reflect(
                game_result=self.state.winner,
                final_state=full_state,
                my_role=player.role.name,
            )
            if reflection:
                self.logger.log_reflection(
                    player.player_id, reflection, self.state.round_number
                )
