"""
llm_agent.py
------------
LLM-powered agent using OpenAI (or any AutoGen-compatible backend).

Requires: pip install openai
"""

from __future__ import annotations

import json
import re
import random
from typing import Optional

from clocktower.agents.base_agent import BaseAgent
from clocktower.roles import ALL_ROLES
from clocktower.solver_hints import format_known_roles, extract_claims_and_hints, extract_demon_candidate

# Valid Trouble Brewing roles — prevents hallucinations
VALID_ROLE_NAMES = ", ".join(sorted(ALL_ROLES.keys()))
VALID_ROLE_SET = set(ALL_ROLES.keys())

# Common hallucinated roles → closest valid role (for post-processing)
ROLE_HALLUCINATION_FIX = {
    "scout": "Investigator", "psychic": "Fortune Teller", "doctor": "Monk",
    "oracle": "Fortune Teller", "seer": "Fortune Teller", "sharpshooter": "Slayer",
    "detective": "Investigator", "chemist": "Investigator",
    "tracker": "Fortune Teller", "shepherd": "Librarian", "butcher": "Butler",
    "sheriff": "Slayer", "professor": "Investigator",
    "apprentice": "Librarian", "investigating lady": "Investigator",
    "reticulant": "Recluse", "watchman": "Librarian", "tinkerer": "Librarian",
    "surgeon": "Monk",
}

INFO_ROLES = ("empath", "chef", "fortune teller", "investigator", "ravenkeeper", "undertaker", "washerwoman", "librarian")

SYSTEM_PROMPT_GOOD = """VALID ROLES (Trouble Brewing only — use these exact names):
{valid_role_names}
There is NO Scout, Psychic, Doctor, Surgeon, Sharpshooter, Oracle, Seer, Detective, Chemist, Tracker, Shepherd, Butcher, or Sheriff. Do not claim or reference them.

You are {name}, a player in a game of Blood on the Clocktower.

YOUR ROLE: {role_name}
YOUR ROLE DESCRIPTION: {role_description}
YOUR TEAM: Good

⚠️ SAINT RULE (NEVER FORGET): Executing the Saint = Evil wins IMMEDIATELY. If a player claims Saint, you MUST vote NO on them. Never nominate someone who claimed Saint. No exception.

OBJECTIVE:
Your team must identify and execute the Demon before Evil reduces the alive players to 2.

GAME BASICS:
- Each round alternates Night (hidden actions) and Day (public discussion + vote).
- Only alive players vote, though dead players may speak and spend one ghost vote.
- You win if the Demon is ever executed during the day.

VOTE COORDINATION (critical):
- Converge on ONE suspect each day. If 2+ players have said they suspect X, nominate X or vote YES on X.
- Avoid split votes — if others are voting for a candidate, vote with them so an execution happens.
- Indecision helps Evil. Execute someone by Day 2–3 if you have a plausible suspect.

DEDUCTION: If Empath says one of [A, B] is evil and you know one is Good (e.g. verified role), the other is evil — execute them. Trust direct info (Empath neighbors, Chef pairs) over opinions. Evil will push to execute Good players — cross-check against raw info.

RECLUSE CAVEAT: The Recluse can register as Evil to information roles. If Empath says one neighbor is Evil and one neighbor is (or was) Recluse, the Recluse may be the one pinging — do NOT assume the other neighbor is Evil without other evidence.

TRUST HIERARCHY (use this order): (1) Empath/Chef night info from living players, (2) Undertaker info on executed roles, (3) role claims from living players, (4) opinions. Investigator/Fortune Teller info can come from Evil — cross-check with other sources.

DEMON FIRST: Executing a minion (Baron, Poisoner, Spy) helps but doesn't win — only executing the Demon wins. If you execute the Baron and the Imp survives, Evil wins immediately. Prioritize executing the Demon. If info points to the Demon, converge there first.

FINAL FEW: When only 2–4 players are alive, pick ONE consensus suspect and ALL vote for them. At least 3 of 4 must vote the same; with 3 alive you need 2 votes — a 1-1 split = no execution = Evil wins. Split votes (2-2-2-2) guarantee no execution and Evil wins. If the two suspects are Demon vs minion, execute the Demon — executing the minion leaves the Demon and Evil wins.

THREE ALIVE: With exactly 3 players alive, both Good players MUST nominate and vote for the SAME suspect. Pick ONE (e.g. if Empath said "one of Frank or Grace is evil", pick Frank OR Grace — do not split). BOTH Good: nominate the same player, BOTH vote YES on them. If you disagree on who the Demon is, converge on the stronger candidate — a 1-1 split = no execution = Evil wins. Do NOT nominate or vote for each other or for info roles. Identify the Demon from info and BOTH vote YES for that player only.

POST-MINION: After executing a minion, the remaining player in the Fortune Teller/Investigator "A or B" pool is likely the Demon. Focus ALL votes on them — do not split.

PROCRASTINATION: Evil stalls with "let's discuss more" or "let's verify first." If you have solid info (Fortune Teller, Chef) and 2+ rounds of discussion, DECIDE and vote. Procrastination helps Evil.

ANTI-SPLIT: If the last vote round was a tie (e.g. 2-2) or near-tie, pick the single most likely Demon from info (Chef pairs, Fortune Teller, duplicate claimants) and ALL vote for that player next round. Do not keep splitting.

DUPLICATE CLAIMANTS: When two players claim the same role, one is Evil. Execute the claimant you suspect is fake — the one whose story conflicts with Undertaker/Washerwoman/Empath, or steers executions toward likely Good players. The claimant whose info aligns with verified facts is likely the real one — do NOT execute them. Do NOT split votes between claimants.

DEMON vs MINION: Before executing, ask: is this the Demon or a minion? ALWAYS prefer the Demon. If info points to A as Demon and B as minion, execute A. Executing a minion when the Demon survives = Evil wins immediately.

LIBRARIAN: If Librarian says there are no Outsiders, claims that a specific player is Baron (or another minion) may be wrong or from Evil — cross-check with other info.

CHEF NUMBER-PAIRS: Chef says how many adjacent Evil pairs exist. 0 pairs = no two Evil sit next to each other. 1 pair = exactly one adjacent pair (e.g. seats 2–3) has both Evil. 2 pairs = two adjacent pairs. Use seating order to narrow suspects.
CHEF + WASHERWOMAN: If Washerwoman says "A or B is a Townsfolk role," do NOT execute that player just because Chef says adjacent Evil — the Townsfolk candidate is likely Good. Chef's "1 adjacent Evil pair" may be a different pair.

EMPATH "ONE OF A OR B": If Empath said "one of A or B is evil" and A is dead (was a minion), then A was the Evil one. The other (B) may be Good — the Demon could be a different player. Do NOT assume B is the Demon. Only "BOTH A and B are evil" (with one dead) implies the alive one is the Demon.

VIRGIN/TOWNSFOLK CANNOT BE THE DEMON: Virgin, Mayor, Soldier, Slayer, Butler, etc. are Townsfolk — they are NEVER the Demon. If someone claimed Virgin (or another Townsfolk role) and it's plausible, do NOT execute them as the Demon. When the Imp is executed, Scarlet Woman becomes the new Demon — the other player in the Fortune Teller pair is NOT automatically the Demon; the new Demon is now the Scarlet Woman.

INVESTIGATOR PAIR: If Investigator says "A or B is a minion" and one is executed and Undertaker confirms they were Good (e.g. Ravenkeeper, Soldier), the other is the minion. Focus on finding the Demon among remaining players — do NOT execute the Investigator. Evil often pushes to execute the Investigator to silence them.

DECISION FATIGUE: After 2+ rounds discussing the same suspects or duplicate claims, DECIDE and vote. Endless verification helps Evil. Nominate and vote for your top Demon suspect now.

PROTECT INFO ROLES: Empath, Chef, Fortune Teller, Investigator, Ravenkeeper, Undertaker, Washerwoman, and Librarian are your primary info sources. Do NOT execute them unless you have very strong evidence (e.g. Undertaker confirmed they were bluffing, or multiple independent proofs). Executing your own info roles cripples Good. When 3 alive, NEVER vote to execute an info role — both Good must vote for the Demon candidate only.

DUPLICATE INFO ROLES (Chef, Empath, Fortune Teller): When two claim the same info role, execute the FAKE claimant — the one whose story conflicts with Washerwoman/Undertaker/other verified info, or who is pushing to execute likely Good players. The claimant whose info matches verified facts is likely real — protect them, execute the other.

SANITY CHECKS:
- Duplicate role claims = Evil signal. If two players claim the same unique role (Investigator, Slayer, Fortune Teller, Monk, etc.), one is lying. Suspect the CLAIMANT whose story steers executions toward likely Good players — execute that claimant, not the player they accuse.
- Duplicate Fortune Teller: execute the claimant whose story conflicts with other info or would execute Townsfolk. Do NOT execute the claimant whose info aligns with Empath/Washerwoman/Undertaker.
- If Investigator/Fortune Teller says "A or B" and one is already dead with a known different role, the info is wrong or the claimant is Evil. Consider executing the claimant instead of the accused.
- SAINT: Executing the Saint = Evil wins INSTANTLY. ALWAYS vote NO on anyone who claimed Saint. Overrides all other rules.
- Do NOT vote to execute the Mayor, Virgin, Empath, Chef, Fortune Teller, Investigator, Ravenkeeper, Undertaker, Washerwoman, or Librarian unless there is very strong corroborating evidence. A single accusation (especially from Evil pushing for it) is NOT enough. Evil often nominates info roles to silence them — resist.
- VIRGIN IS NEVER THE DEMON: If someone claimed Virgin, they cannot be the Demon. Do NOT execute a Virgin claimant as the Demon. When Imp was executed, Scarlet Woman became the new Demon — look for Scarlet Woman, not the other in the FT pair.

LAST-SPEAKER BIAS: Don't over-trust whoever spoke last. Consider all evidence equally — the last speaker may be Evil deflecting. Weigh night info (Empath, Chef, Undertaker) over recency.

GHOST CAUTION: Dead players can lie. If a ghost's claim pushes you to execute a living player and it contradicts or isn't corroborated by living players, trust living players' info first. Evil ghosts often misdirect.

GHOST DEDUCTIONS: Ghost deductions based on confirmed facts (e.g. Empath + Fortune Teller narrowing to one suspect) can be correct. If a ghost uses live info roles to deduce a suspect, consider that suspect — but apply the Recluse caveat.
RAVENKEEPER: If a dead player (ghost) says "Ravenkeeper learned X is Baron/Imp/Poisoner/Spy/Scarlet Woman," the Ravenkeeper learned this on death — prioritize executing X or the Demon. Do not ignore Ravenkeeper death-info.

YOUR STRATEGY ({variant}):
{strategy_instructions}

ACCUMULATED INFO FROM PREVIOUS NIGHTS:
{night_info_summary}

MEMORY FROM PAST GAMES:
{memory_summary}

INFO ROLE DISCLOSURE (Empath, Chef, Fortune Teller, Investigator, etc.): Share your night information clearly and early. Be direct and concise — avoid over-explaining or seeming defensive. One clear statement (e.g. "I learned X") is better than long justifications. Trust helps Good; hedging or waffling helps Evil.

NAMES NOT IDs: When discussing suspects, use player NAMES (e.g. Alice, Bob, Charlie) not p1/p2/p3 — it reduces confusion and helps coordination.

CRITICAL: Output ONLY the exact words your character says aloud. Never add meta-commentary,
reasoning, or analysis (e.g. no "This statement aligns with..." or "I'm saying this because...").
Share your role and night information clearly and early so the Good team can coordinate.
Some information may be false due to the Drunk, Poisoner, or Spy."""

SYSTEM_PROMPT_EVIL = """You are {name}, a player in a game of Blood on the Clocktower.

YOUR ROLE: {role_name}
YOUR ROLE DESCRIPTION: {role_description}
YOUR TEAM: Evil

YOUR EVIL TEAMMATES:
{evil_team_summary}

OBJECTIVE:
Survive until only 2 players are alive (and the Demon is one of them).
NEVER let the Good team successfully execute the Demon.

STRATEGY ({variant}):
{strategy_instructions}

CORE DECEPTION TACTICS:
- Claim a believable Good role (ideally one with limited verifiable info).
- Create doubt about trustworthy Good players.
- Support execution of Good players by building plausible cases against them.
- Avoid drawing suspicion — be helpful-seeming but subtly misleading.

ACCUMULATED INFO:
{night_info_summary}

MEMORY FROM PAST GAMES:
{memory_summary}

NAMES NOT IDs: When discussing suspects, use player NAMES (e.g. Alice, Bob) not p1/p2 — reduces confusion.
"""

STRATEGY_VARIANTS = {
    "baseline": {
        "good": "Play normally. Share what you know. Vote when you feel confident.",
        "evil": "Lie about your role. Try to survive. Vote against Good players.",
    },
    "strategic": {
        "good": (
            "Share your role and night information clearly in the first 1–2 days so the team can coordinate. "
            "Cross-reference all claims. When duplicate role claims exist, pick ONE claimant and ALL vote for them. "
            "Converge on ONE suspect. When 3 alive, both Good MUST vote same (1-1 = Evil wins). When 4 alive, need 3+ votes. "
            "After executing a minion, the remaining person in Fortune Teller/Investigator pool is likely the Demon — focus all votes there. "
            "Evil stalls with 'let's discuss more.' With solid info and 2+ rounds, DECIDE and vote. Recluse can register as Evil. Execute by Day 2–3."
        ),
        "evil": (
            "Pick a Townsfolk role to bluff as (ideally one not in play). "
            "Manufacture a plausible story that seems helpful but subtly misdirects. "
            "Coordinate with your evil team to converge on one Good scapegoat. "
            "Never both vote the same way obviously — it reveals coordination."
        ),
    },
    "cautious": {
        "good": (
            "Be conservative. Don't reveal your role unless necessary. "
            "Wait for contradictions to emerge before committing to a nomination."
        ),
        "evil": (
            "Stay quiet and unobtrusive. Let other Evil players take risks. "
            "Only act when it's safe to do so."
        ),
    },
    "aggressive": {
        "good": (
            "Take charge. Push hard for nominations early. Force players to reveal info. "
            "Accept some risk of being wrong in exchange for moving fast."
        ),
        "evil": (
            "Dominate the discussion. Be the loudest voice. Redirect suspicion hard and fast. "
            "If a Good player seems close to exposing the Demon, nominate them immediately."
        ),
    },
    "analytical": {
        "good": (
            "Maintain a mental model of all possible role configurations. "
            "Use Bayesian-style reasoning: which world is most consistent with all claims? "
            "When duplicate role claims exist, pick ONE claimant. If Librarian says no Outsiders, Baron claims may be wrong. "
            "When 3 alive, both Good MUST vote same. After executing a minion, focus on remaining Demon candidate from info. "
            "Evil stalls. With solid info and 2+ rounds, DECIDE and vote. Recluse can register as Evil. Execute by Day 2–3."
        ),
        "evil": (
            "Understand what each Good role's information looks like. "
            "Craft lies that are internally consistent with what Good players might be seeing. "
            "Actively poison the information space with plausible false claims."
        ),
    },
}


class LLMAgent(BaseAgent):
    """
    LLM-powered agent for Blood on the Clocktower.
    Requires: pip install openai
    Set OPENAI_API_KEY or pass api_key.
    """

    def __init__(
        self,
        name: str,
        model: str = "gpt-3.5-turbo",
        variant: str = "strategic",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        use_belief_modeling: bool = True,
        use_learning: bool = True,
    ):
        super().__init__(name)
        self.model = model
        self.variant = variant
        self.api_key = api_key
        self.base_url = base_url
        self.use_belief_modeling = use_belief_modeling
        self.use_learning = use_learning

        self.evil_team: list[dict] = []
        self.suspicion_scores: dict[str, float] = {}
        self.conversation_history: list[dict] = []
        self.game_reflections: list[dict] = []  # Track reflections across games

        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                import os
                key = self.api_key or os.environ.get("OPENAI_API_KEY")
                base_url = self.base_url or os.environ.get("OPENAI_API_BASE")
                if base_url:
                    self._client = OpenAI(api_key=key, base_url=base_url)
                else:
                    self._client = OpenAI(api_key=key)
            except ImportError:
                raise ImportError(
                    "openai package not installed. Run: pip install openai"
                )
        return self._client

    def _call_llm(self, system_prompt: str, user_message: str) -> str:
        import os
        client = self._get_client()
        kwargs = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        # LiteLLM proxy may require 'user' param (e.g. for blocked user lists)
        if os.environ.get("LITELLM_USER"):
            kwargs["user"] = os.environ.get("LITELLM_USER")
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content
        return (content or "").strip()

    def _build_system_prompt(self) -> str:
        team = self.my_team or "good"
        variant_instructions = STRATEGY_VARIANTS.get(
            self.variant, STRATEGY_VARIANTS["strategic"]
        ).get(team, "")

        evil_summary = (
            "\n".join(f"  - {p['name']} ({p['role']})" for p in self.evil_team)
            if self.evil_team else "N/A"
        )

        night_summary = self._format_night_infos()
        memory_summary = (
            "\n".join(f"  - {m}" for m in self.memory_buffer[-5:])
            if self.use_learning and self.memory_buffer
            else "No prior games."
        )

        template = SYSTEM_PROMPT_EVIL if team == "evil" else SYSTEM_PROMPT_GOOD
        kwargs = dict(
            name=self.name,
            role_name=self.my_role or "Unknown",
            role_description=self.role_description or "",
            variant=self.variant,
            strategy_instructions=variant_instructions,
            evil_team_summary=evil_summary,
            night_info_summary=night_summary,
            memory_summary=memory_summary,
        )
        if team == "good":
            kwargs["valid_role_names"] = VALID_ROLE_NAMES
        return template.format(**kwargs)

    def _format_night_infos(self) -> str:
        if not self.night_infos:
            return "No information received yet."
        return "\n".join(f"  [{i['info_type']}] {json.dumps(i['content'])}" for i in self.night_infos)

    def _format_public_state(self, public_state: dict) -> str:
        players = public_state.get("players", [])
        lines = [f"Round {public_state.get('round')}, Phase: {public_state.get('phase')}"]
        # Seat order (for Empath/Chef: neighbors are adjacent in circle)
        seated = sorted(players, key=lambda p: p.get("seat", 0))
        seat_order = [f"{p['name']}({p['player_id']})" for p in seated]
        lines.append(f"Seating (neighbors adjacent): {' — '.join(seat_order)}")
        lines.append("Players:")
        for p in players:
            status = "alive" if p["is_alive"] else f"dead (role: {p['role']})"
            lines.append(f"  - {p['name']} [{p['player_id']}]: {status}")
        return "\n".join(lines)

    def _format_discussion(self, discussion_history: list[dict]) -> str:
        if not discussion_history:
            return "No discussion yet."
        recent = discussion_history[-10:]
        return "\n".join(f"  {d['player_id']}: {d['message']}" for d in recent)

    def _format_suspicion(self) -> str:
        if not self.suspicion_scores:
            return "No suspicion data yet."
        sorted_s = sorted(self.suspicion_scores.items(), key=lambda x: -x[1])
        return ", ".join(f"{pid}:{score:.2f}" for pid, score in sorted_s)

    # Exponential smoothing for suspicion (WOLF benchmark: suspicion aggregates across rounds)
    SUSPICION_ALPHA = 0.4  # Weight for new observation; 1-alpha for prior

    def _update_suspicion(self, response_text: str, public_state: dict):
        players = public_state.get("players", [])
        pid_list = [p["player_id"] for p in players if p["player_id"] != self.player_id]

        prompt = (
            f"Based on your current knowledge, output a JSON object with "
            f"suspicion scores (0.0 = definitely good, 1.0 = definitely demon/evil) "
            f"for each of these player IDs: {pid_list}.\n"
            f"Respond ONLY with valid JSON, e.g. {{\"p1\": 0.3, \"p2\": 0.8}}"
        )
        raw = self._call_llm(self._build_system_prompt(), prompt)
        try:
            match = re.search(r'\{[^{}]+\}', raw)
            if match:
                new_scores = json.loads(match.group())
                for pid, new_val in new_scores.items():
                    old_val = self.suspicion_scores.get(pid, 0.5)
                    smoothed = (
                        self.SUSPICION_ALPHA * float(new_val)
                        + (1 - self.SUSPICION_ALPHA) * old_val
                    )
                    self.suspicion_scores[pid] = max(0.0, min(1.0, smoothed))
        except (json.JSONDecodeError, AttributeError, TypeError):
            pass

    def on_evil_briefing(self, evil_summary: list[dict]):
        self.evil_team = evil_summary

    def initialize_suspicion_for_players(self, player_ids: list[str]):
        """Initialize suspicion scores for all players at game start."""
        if self.use_belief_modeling and not self.suspicion_scores:
            for pid in player_ids:
                if pid != self.player_id:
                    # Start neutral (0.5 = unknown)
                    self.suspicion_scores[pid] = 0.5
        # Always initialize evil teammates at low suspicion (we know them)
        if self.use_belief_modeling and self.evil_team:
            for teammate in self.evil_team:
                self.suspicion_scores[teammate['player_id']] = 0.1
    def choose_night_target(
        self,
        action: str,
        valid_targets: list[str],
        public_state: dict,
    ) -> str:
        action_prompts = {
            "kill": (
                f"It is night. Choose one player to kill. Valid target IDs: {valid_targets}.\n"
                f"Respond with ONLY the player_id, e.g.: p2"
            ),
            "poison": (
                f"As the Poisoner, choose one player to poison. Valid targets: {valid_targets}.\n"
                f"Respond with ONLY the player_id."
            ),
            "protect": (
                f"As the Monk, choose one player to protect. Valid targets: {valid_targets}.\n"
                f"Respond with ONLY the player_id."
            ),
            "choose_master": (
                f"As the Butler, choose your master. Valid choices: {valid_targets}.\n"
                f"Respond with ONLY the player_id."
            ),
            "ravenkeeper_learn": (
                f"As the Ravenkeeper, choose a player to learn their role. "
                f"Valid targets: {valid_targets}.\nRespond with ONLY the player_id."
            ),
        }
        user_msg = action_prompts.get(
            action,
            f"Choose a target from {valid_targets}. Respond with ONLY the player_id."
        )
        system = self._build_system_prompt()
        state_context = self._format_public_state(public_state)
        full_msg = f"CURRENT GAME STATE:\n{state_context}\n\n{user_msg}"

        response = self._call_llm(system, full_msg)
        for pid in valid_targets:
            if pid in response:
                return pid
        return random.choice(valid_targets)

    def choose_two_targets(
        self,
        action: str,
        valid_targets: list[str],
        public_state: dict,
    ) -> tuple[str, str]:
        system = self._build_system_prompt()
        state_context = self._format_public_state(public_state)
        user_msg = (
            f"CURRENT GAME STATE:\n{state_context}\n\n"
            f"As the Fortune Teller, choose TWO players to divine tonight. "
            f"Valid targets: {valid_targets}.\n"
            f"Respond with ONLY two player IDs separated by a comma, e.g.: p1, p3"
        )
        response = self._call_llm(system, user_msg)
        found = [pid for pid in valid_targets if pid in response]
        if len(found) >= 2:
            return found[0], found[1]
        chosen = random.sample(valid_targets, min(2, len(valid_targets)))
        return chosen[0], chosen[1]

    def discuss(
        self,
        public_state: dict,
        discussion_history: list[dict],
        round_number: int,
        is_dead: bool = False,
    ) -> Optional[str]:
        system = self._build_system_prompt()
        state_str = self._format_public_state(public_state)
        discussion_str = self._format_discussion(discussion_history)
        suspicion_str = self._format_suspicion()

        if is_dead:
            tone = "You are dead but may speak. You have one ghost vote remaining."
        else:
            tone = "It is the day discussion phase. Speak publicly to help your team."

        suspicion_block = (
            f"YOUR SUSPICION SCORES: {suspicion_str}\n\n"
            if self.use_belief_modeling else ""
        )
        known_roles_block = format_known_roles(public_state)
        solver_block = extract_claims_and_hints(public_state, discussion_history, self.night_infos) if self.my_team == "good" else ""
        user_msg = (
            f"CURRENT GAME STATE:\n{state_str}\n\n"
            + (f"{known_roles_block}\n\n" if known_roles_block else "")
            + (f"{solver_block}\n" if solver_block else "")
            + f"RECENT DISCUSSION:\n{discussion_str}\n\n"
            f"{suspicion_block}"
            f"{tone}\n"
            f"Keep to 1–2 SHORT sentences (under 50 words). Be direct. Do NOT repeat what you've already said. "
            f"Output ONLY the exact words your character says aloud. No meta-commentary."
        )
        response = self._call_llm(system, user_msg)

        if self.use_belief_modeling:
            try:
                self._update_suspicion(response, public_state)
            except Exception:
                pass

        if response:
            response = response.strip()
            for marker in ("\n\nThis statement", "\n\nThis aligns", ".\n\nIt ", ".\n\nThis "):
                if marker in response:
                    response = response.split(marker)[0].strip()
            response = self._sanitize_role_claims(response)
        return response if response else None

    def _did_player_claim_info_role(
        self, player_id: str, public_state: dict, discussion_history: list
    ) -> bool:
        """True if this player has claimed an info role (Empath, Chef, Ravenkeeper, etc.)."""
        players = public_state.get("players", [])
        nom = next((p for p in players if p.get("player_id") == player_id), None)
        nom_name = (nom.get("name") or "").strip().lower() if nom else ""
        for d in (discussion_history or []):
            msg = (d.get("message") or "").lower()
            if d.get("player_id") != player_id:
                if nom_name and len(nom_name) >= 3 and nom_name in msg:
                    for ir in INFO_ROLES:
                        if ir in msg and ("claim" in msg or f"is the {ir}" in msg or f"as the {ir}" in msg):
                            return True
                continue
            for ir in INFO_ROLES:
                # Match "I'm the Investigator", "I'm Eve, the Investigator", "as the Investigator"
                if re.search(
                    rf"\b(?:i(?:'m| am)(?:\s+\w+)?\s*,?\s*(?:the\s+)?{re.escape(ir)}|as\s+(?:the\s+)?{re.escape(ir)})\b",
                    msg, re.I
                ):
                    return True
        return False

    def _did_player_claim_virgin(
        self, player_id: str, public_state: dict, discussion_history: list
    ) -> bool:
        """True if this player has claimed to be the Virgin in discussion. Virgin cannot be the Demon."""
        players = public_state.get("players", [])
        nom = next((p for p in players if p.get("player_id") == player_id), None)
        nom_name = (nom.get("name") or "").strip() if nom else ""
        for d in (discussion_history or []):
            msg = (d.get("message") or "").lower()
            if "virgin" not in msg:
                continue
            if d.get("player_id") == player_id:
                if re.search(
                    r"\b(?:i(?:'m| am)(?:\s+\w+)?\s*,?\s*(?:the\s+)?virgin|"
                    r",\s*(?:the\s+)?virgin\b|as\s+(?:the\s+)?virgin|"
                    r"i(?:'m| am)\s+(?:the\s+)?virgin)\b",
                    msg, re.I
                ):
                    return True
            if nom_name and len(nom_name) >= 3 and nom_name.lower() in msg:
                if "virgin" in msg and ("claim" in msg or "is the virgin" in msg or "as the virgin" in msg):
                    return True
        return False

    def _did_player_claim_saint(
        self, player_id: str, public_state: dict, discussion_history: list
    ) -> bool:
        """True if this player has claimed to be the Saint in discussion."""
        players = public_state.get("players", [])
        nom = next((p for p in players if p.get("player_id") == player_id), None)
        nom_name = (nom.get("name") or "").strip() if nom else ""
        for d in (discussion_history or []):
            msg = (d.get("message") or "").lower()
            if "saint" not in msg:
                continue
            if d.get("player_id") == player_id:
                if re.search(
                    r"\b(i(?:'m| am) (?:the |a )?saint|as (?:the |a )?saint|"
                    r"(?:the |a )?saint[,.]?\s|if i am executed)",
                    msg,
                    re.I,
                ):
                    return True
            if nom_name and len(nom_name) >= 3:
                if nom_name.lower() in msg and "saint" in msg and (
                    "claim" in msg or "is the saint" in msg or "as the saint" in msg
                ):
                    return True
        return False

    def _extract_consensus_suspect(
        self,
        discussion_history: list[dict],
        valid_nominees: list[str],
        public_state: Optional[dict] = None,
    ) -> Optional[str]:
        """Extract the most-mentioned suspect from discussion (player IDs and names in suspect context)."""
        if not discussion_history or not valid_nominees:
            return None
        name_to_pid: dict[str, str] = {}
        if public_state:
            for p in public_state.get("players", []):
                pid = p.get("player_id")
                name = (p.get("name") or "").strip()
                if pid and name and pid in valid_nominees:
                    name_to_pid[name.lower()] = pid
        suspect_words = r"\b(suspect|execute|focus on|nominate|verify|duplicate|accuse|converge on|demon|vote for|must be)\b"
        counts: dict[str, int] = {p: 0 for p in valid_nominees}
        for d in discussion_history:
            msg = (d.get("message") or "").lower()
            if not re.search(suspect_words, msg, re.I):
                continue
            for pid in valid_nominees:
                if pid in msg or pid.upper() in msg.upper():
                    counts[pid] += 1
            for name, pid in name_to_pid.items():
                if name in msg and len(name) >= 3:
                    counts[pid] += 1
        if not counts:
            return None
        best = max(counts.items(), key=lambda x: x[1])
        return best[0] if best[1] >= 2 else None

    def _sanitize_role_claims(self, text: str) -> str:
        """Replace common hallucinated role names with valid Trouble Brewing roles."""
        result = text
        for invalid, valid in ROLE_HALLUCINATION_FIX.items():
            # Word-boundary replacement (e.g. Scout -> Investigator)
            result = re.sub(rf"\b{re.escape(invalid)}\b", valid, result, flags=re.IGNORECASE)
        return result

    def nominate(
        self,
        valid_nominees: list[str],
        public_state: dict,
        discussion_history: list[dict],
    ) -> Optional[str]:
        system = self._build_system_prompt()
        state_str = self._format_public_state(public_state)
        discussion_str = self._format_discussion(discussion_history)
        suspicion_str = self._format_suspicion()
        suspicion_block = (
            f"YOUR SUSPICION SCORES: {suspicion_str}\n\n"
            if self.use_belief_modeling else ""
        )
        alive = sum(1 for p in public_state.get("players", []) if p.get("is_alive", True))
        votes_needed = (alive // 2) + 1 if alive else 1
        lylo_block = (
            f"LYLO: 3 alive. If Good splits (1-1) or misvotes, Evil wins. Both Good MUST nominate and vote for the SAME suspect — the Demon. "
            if alive == 3 and self.my_team == "good" else ""
        )
        final_few_hint = (
            f"CRITICAL: Only {alive} alive — need {votes_needed}+ votes. Pick ONE consensus suspect. Split votes = Evil wins. DEMON over minion — execute the Demon. "
            + lylo_block
            + (f"With 3 alive: both Good nominate the SAME Demon candidate. Do NOT nominate fellow Good or info roles (Empath, Chef, FT, Investigator, Ravenkeeper, Undertaker, Washerwoman, Librarian). " if alive == 3 and self.my_team == "good" else "")
            if alive <= 4 and self.my_team == "good" else ""
        )
        known_roles_block = format_known_roles(public_state)
        solver_block = extract_claims_and_hints(public_state, discussion_history, self.night_infos) if self.my_team == "good" else ""
        demon_candidate_id, _ = extract_demon_candidate(public_state, discussion_history) if self.my_team == "good" else (None, None)
        consensus = self._extract_consensus_suspect(discussion_history, valid_nominees, public_state)
        # Override consensus when we have Demon candidate and 3 alive
        if self.my_team == "good" and alive == 3 and demon_candidate_id and demon_candidate_id in valid_nominees:
            consensus = demon_candidate_id
        consensus_hint = (
            f"Consensus suspect from discussion: {consensus}. Nominate them to avoid split votes. "
            if consensus and self.my_team == "good" else ""
        )
        demon_nominate_block = (
            f"⚠️ LYLO: With 3 alive, you MUST nominate {demon_candidate_id} — they are the Demon. Pass or nominating anyone else = Evil wins. Both Good must nominate and vote for {demon_candidate_id}. "
            if self.my_team == "good" and alive == 3 and demon_candidate_id and demon_candidate_id in valid_nominees else ""
        )
        saint_claimants = (
            [p for p in valid_nominees if self._did_player_claim_saint(p, public_state, discussion_history)]
            if self.my_team == "good" else []
        )
        saint_block = (
            f"⚠️ CRITICAL: These players claimed SAINT — NEVER nominate them (executing Saint = Evil wins): {saint_claimants}. "
            if saint_claimants else ""
        )

        user_msg = (
            f"CURRENT GAME STATE:\n{state_str}\n\n"
            + (f"{known_roles_block}\n\n" if known_roles_block else "")
            + (f"{solver_block}\n" if solver_block else "")
            + f"RECENT DISCUSSION:\n{discussion_str}\n\n"
            f"{suspicion_block}"
            f"Nomination phase. Valid nominees: {valid_nominees}.\n"
            f"{saint_block}{demon_nominate_block}{final_few_hint}{consensus_hint}"
            f"Identify the consensus suspect (player 2+ others have named). Nominate that player. "
            f"If duplicate info roles (Chef/Empath/Fortune Teller): nominate the FAKE claimant — the one whose story conflicts with verified info or steers toward Good. Protect the claimant whose info aligns with Washerwoman/Undertaker. "
            f"NEVER nominate the Saint — executing Saint = Evil wins. Do NOT nominate Mayor, Virgin, Empath, Chef, Fortune Teller, Investigator, Ravenkeeper, Undertaker, Washerwoman, or Librarian unless there is strong corroboration. Evil often nominates info roles to silence them. "
            f"Respond with EITHER: NOMINATE <player_id>  or  PASS"
        )
        response = self._call_llm(system, user_msg)

        if "PASS" in response.upper():
            # With 3 alive and Demon candidate: Good MUST nominate — override PASS
            if (
                self.my_team == "good"
                and alive == 3
                and demon_candidate_id
                and demon_candidate_id in valid_nominees
            ):
                return demon_candidate_id
            return None

        for pid in valid_nominees:
            if pid in response:
                if self.my_team == "good" and pid in saint_claimants:
                    return None  # Reject: never nominate Saint claimant
                # Virgin cannot be the Demon — if agent picked Virgin but we have Demon candidate, override
                if (
                    self.my_team == "good"
                    and demon_candidate_id
                    and pid != demon_candidate_id
                    and self._did_player_claim_virgin(pid, public_state, discussion_history)
                ):
                    return demon_candidate_id
                # When Demon candidate exists: if agent picked an info role (not the Demon), override to Demon
                if (
                    self.my_team == "good"
                    and demon_candidate_id
                    and pid != demon_candidate_id
                    and self._did_player_claim_info_role(pid, public_state, discussion_history)
                ):
                    return demon_candidate_id
                return pid

        return None

    def vote(
        self,
        nominee_id: str,
        nominator_id: str,
        public_state: dict,
        discussion_history: list[dict],
    ) -> bool:
        # Hardcoded: Good players NEVER vote YES on the Saint — Evil wins immediately
        if self.my_team == "good" and self._did_player_claim_saint(
            nominee_id, public_state, discussion_history
        ):
            return False

        # Virgin cannot be the Demon — do not execute Virgin claimant as Demon
        if self.my_team == "good" and self._did_player_claim_virgin(
            nominee_id, public_state, discussion_history
        ):
            return False

        alive = sum(1 for p in public_state.get("players", []) if p.get("is_alive", True))
        demon_candidate_id, _ = extract_demon_candidate(public_state, discussion_history) if self.my_team == "good" else (None, None)

        # CRITICAL: When nominee IS the Demon candidate, vote YES — Demon often bluffs as info role; don't protect them
        if (
            self.my_team == "good"
            and demon_candidate_id
            and nominee_id == demon_candidate_id
        ):
            return True

        # With 3 alive: vote NO on info roles (protect real ones) — but NOT when nominee is Demon (handled above)
        if self.my_team == "good" and alive == 3 and self._did_player_claim_info_role(
            nominee_id, public_state, discussion_history
        ):
            return False

        # When we've identified the Demon: vote NO on info roles (execute Demon, not them). Extended to alive<=5.
        if (
            self.my_team == "good"
            and alive <= 5
            and demon_candidate_id
            and nominee_id != demon_candidate_id
            and self._did_player_claim_info_role(nominee_id, public_state, discussion_history)
        ):
            return False

        system = self._build_system_prompt()
        state_str = self._format_public_state(public_state)
        discussion_str = self._format_discussion(discussion_history)
        suspicion = self.suspicion_scores.get(nominee_id, 0.5) if self.use_belief_modeling else 0.5
        suspicion_line = (
            f"Your suspicion score for {nominee_id}: {suspicion:.2f}\n\n"
            if self.use_belief_modeling else ""
        )

        alive = sum(1 for p in public_state.get("players", []) if p.get("is_alive", True))
        valid_nominees = [p["player_id"] for p in public_state.get("players", []) if p.get("is_alive", True)]
        consensus = self._extract_consensus_suspect(discussion_history, valid_nominees, public_state) if self.my_team == "good" else None
        # Prefer solver-identified Demon candidate when 3 alive
        if self.my_team == "good" and alive == 3 and demon_candidate_id and demon_candidate_id in valid_nominees:
            consensus = demon_candidate_id
        consensus_vote = (
            f" {nominee_id} is the consensus suspect — vote YES to avoid split votes. "
            if consensus == nominee_id and self.my_team == "good" else ""
        )
        votes_needed = (alive // 2) + 1 if alive else 1
        final_few = (
            f" Only {alive} alive — need {votes_needed}+ YES votes. Converge on ONE. Split = Evil wins. "
            + (f"LYLO: With 3 alive, both Good MUST vote for the Demon candidate. A 1-1 split = Evil wins. Do NOT vote YES on info roles — vote NO, execute the Demon. " if alive == 3 and self.my_team == "good" else "")
            if alive <= 4 and self.my_team == "good" else ""
        )
        demon_candidate_block = (
            f"⚠️ DEMON CANDIDATE: {demon_candidate_id}. Vote YES only when {demon_candidate_id} is nominated. Vote NO on info roles (Empath, Chef, FT, Investigator, Ravenkeeper, Undertaker, Washerwoman, Librarian) — execute the Demon, not them. "
            if self.my_team == "good" and alive <= 5 and demon_candidate_id else ""
        )
        vote_hint = (
            f"⚠️ FIRST: If nominee claimed Saint in discussion → you MUST vote NO (executing Saint = Evil wins). "
            f"{demon_candidate_block}{final_few}{consensus_vote}If nominee is consensus Demon candidate, vote YES. If nominee claimed Saint: vote NO. "
            f"If Empath or ghost identified someone else as the Demon (e.g. 'Empath said X and Y are evil', 'X must be the Demon'), vote NO on info roles (Fortune Teller, Empath, Investigator, etc.) — execute the Demon candidate instead. "
            f"If nominee claimed Mayor, Virgin, Empath, Chef, Fortune Teller, Investigator, Ravenkeeper, Undertaker, Washerwoman, or Librarian: vote YES only with strong corroboration — Evil often nominates info roles to silence them. DEMON over minion. With 3 alive, both Good must vote the same. Indecision helps Evil."
            if self.my_team == "good" else ""
        )
        known_roles_block = format_known_roles(public_state)
        solver_block = extract_claims_and_hints(public_state, discussion_history, self.night_infos) if self.my_team == "good" else ""
        user_msg = (
            f"CURRENT GAME STATE:\n{state_str}\n\n"
            + (f"{known_roles_block}\n\n" if known_roles_block else "")
            + (f"{solver_block}\n" if solver_block else "")
            + f"RECENT DISCUSSION:\n{discussion_str}\n\n"
            f"VOTE: {nominator_id} has nominated {nominee_id} for execution.\n"
            f"{suspicion_line}"
            f"Should you vote to execute {nominee_id}?{vote_hint}\n"
            f"Respond with ONLY: YES or NO"
        )
        response = self._call_llm(system, user_msg)
        return "YES" in response.upper()

    def reflect(
        self,
        game_result: str,
        final_state: dict,
        my_role: str,
    ) -> Optional[str]:
        """
        Post-game reflection: learn from outcomes.
        Stores key lessons in memory_buffer for future games.
        """
        won = (
            (game_result == "good" and self.my_team == "good") or
            (game_result == "evil" and self.my_team == "evil")
        )
        outcome = "won" if won else "lost"

        system = self._build_system_prompt()
        user_msg = (
            f"The game has ended. Your team ({self.my_team}) {outcome}.\n"
            f"You played as: {my_role}\n\n"
            f"Analysis:\n"
            f"- What were the key moments that led to {outcome}ing?\n"
            f"- Which players did you misjudge?\n"
            f"- What information or signals did you miss or over-value?\n\n"
            f"Please provide a structured reflection:\n"
            f"1. KEY LESSON: (1 sentence capturing the main insight)\n"
            f"2. MISTAKES: (what you got wrong)\n"
            f"3. BETTER NEXT TIME: (specific tactical improvement)\n\n"
            f"Be concise (2-3 sentences per point). This will inform your future play."
        )
        reflection = self._call_llm(system, user_msg)

        if reflection and self.use_learning:
            # Store structured reflection
            memory_entry = f"[{my_role}, {outcome}] {reflection}"
            self.memory_buffer.append(memory_entry)
            
            # Store full reflection for analysis
            self.game_reflections.append({
                "role": my_role,
                "outcome": outcome,
                "reflection": reflection,
            })
            
            # Keep only last 5 games in memory buffer (for prompt context)
            if len(self.memory_buffer) > 5:
                self.memory_buffer = self.memory_buffer[-5:]

        return reflection

    def on_game_end(self):
        """Called at the end of each game to reset per-game state."""
        if self.use_belief_modeling:
            self.suspicion_scores = {}
        self.night_infos = []
        self.evil_team = []
        self.conversation_history = []
