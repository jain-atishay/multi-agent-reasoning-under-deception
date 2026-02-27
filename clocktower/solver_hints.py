"""
solver_hints.py
---------------
ClocktowerSolver-inspired helpers: known roles, claim extraction, deduction hints.
Injected into LLM prompts to improve Good team reasoning.
"""

from __future__ import annotations

import re
from typing import Optional


def format_known_roles(public_state: dict) -> str:
    """Build KNOWN ROLES FROM EXECUTIONS block from dead players."""
    players = public_state.get("players", [])
    dead_with_roles = [
        (p.get("name", ""), p.get("player_id", ""), p.get("role", ""))
        for p in players
        if not p.get("is_alive", True) and p.get("role") and p.get("role") != "unknown"
    ]
    if not dead_with_roles:
        return ""
    parts = [f"{name}({pid})→{role}" for name, pid, role in dead_with_roles]
    return f"KNOWN ROLES FROM EXECUTIONS: {'; '.join(parts)}."


def _parse_chef_claim(msg: str) -> Optional[int]:
    """Extract Chef pair count from message. Returns 0, 1, or 2 or None."""
    msg_lower = msg.lower()
    if "chef" not in msg_lower and "pairs" not in msg_lower and "adjacent" not in msg_lower:
        return None
    for n in (0, 1, 2):
        if re.search(rf"\b{n}\s*(pair|pairs)\s*(of\s+)?adjacent", msg_lower, re.I):
            return n
        if re.search(rf"(no|zero)\s*(pairs|adjacent)", msg_lower) and n == 0:
            return 0
    return None


def _parse_washerwoman_claim(msg: str, players: list) -> Optional[tuple]:
    """Extract Washerwoman claim: (player1_id, player2_id, role_name) or None."""
    # Look for "A or B is X" pattern
    for p in players:
        pid = p.get("player_id", "")
        name = (p.get("name") or "").lower()
        if pid and name and len(name) >= 3:
            if pid in msg or name in msg.lower():
                # Find another player mentioned
                for p2 in players:
                    if p2["player_id"] == pid:
                        continue
                    pid2 = p2.get("player_id", "")
                    name2 = (p2.get("name") or "").lower()
                    if pid2 and name2 and (pid2 in msg or name2 in msg.lower()):
                        # Extract role - common Townsfolk names
                        roles = ["Empath", "Chef", "Fortune Teller", "Investigator", "Librarian",
                                 "Monk", "Ravenkeeper", "Virgin", "Slayer", "Soldier", "Mayor", "Washerwoman"]
                        for r in roles:
                            if r.lower() in msg.lower():
                                return (pid, pid2, r)
    return None


def _parse_undertaker_from_night(night_infos: list) -> list:
    """Extract Undertaker info from night_infos: list of (player_id, role)."""
    result = []
    for ni in (night_infos or []):
        if ni.get("info_type") == "undertaker":
            content = ni.get("content") or {}
            executed = content.get("executed_player_id") or content.get("executed_player")
            role = content.get("role")
            if executed and role:
                result.append((executed, role))
    return result


def _get_adjacent_pairs(players: list) -> list:
    """Return list of (pid1, pid2) for adjacent seats."""
    seated = sorted([p for p in players if p.get("player_id")], key=lambda x: x.get("seat", 0))
    pairs = []
    n = len(seated)
    for i in range(n):
        p1 = seated[i].get("player_id")
        p2 = seated[(i + 1) % n].get("player_id")
        if p1 and p2:
            pairs.append((p1, p2))
    return pairs


def extract_claims_and_hints(
    public_state: dict,
    discussion_history: list,
    night_infos: Optional[list] = None,
) -> str:
    """
    Extract structured claims from discussion + night_info and produce deduction hints.
    Returns a string to inject into prompts.
    """
    players = public_state.get("players", [])
    hints = []

    # Undertaker from night_info (agent's own info)
    undertaker_roles = _parse_undertaker_from_night(night_infos or [])
    if undertaker_roles:
        parts = [f"{pid}→{role}" for pid, role in undertaker_roles]
        hints.append(f"Undertaker learned: {'; '.join(parts)}")

    # Chef claims from discussion
    chef_pairs = None
    for d in (discussion_history or []):
        msg = d.get("message") or ""
        n = _parse_chef_claim(msg)
        if n is not None:
            chef_pairs = n
            break
    if chef_pairs is not None:
        pairs = _get_adjacent_pairs(players)
        pair_str = ", ".join(f"({a},{b})" for a, b in pairs)
        if chef_pairs == 0:
            hints.append(f"Chef said 0 adjacent Evil pairs → no adjacent pair is (Evil, Evil). Adjacent pairs: {pair_str}")
        elif chef_pairs == 1:
            hints.append(f"Chef said 1 adjacent Evil pair → exactly one adjacent pair has both Evil. Adjacent pairs: {pair_str}")
        else:
            hints.append(f"Chef said {chef_pairs} adjacent Evil pairs. Adjacent pairs: {pair_str}")

    known_roles = {p["player_id"]: p["role"] for p in players if not p.get("is_alive") and p.get("role") != "unknown"}

    # Saint: player claimed Saint — never execute
    for d in (discussion_history or []):
        msg = (d.get("message") or "").lower()
        if "saint" not in msg:
            continue
        if re.search(r"\b(i(?:'m| am) (?:the |a )?saint|as (?:the |a )?saint|if i am executed)", msg, re.I):
            pid = d.get("player_id")
            if pid:
                p = next((x for x in players if x.get("player_id") == pid), None)
                name = (p.get("name") or pid) if p else pid
                hints.append(f"⚠️ {name}({pid}) CLAIMED SAINT. NEVER nominate or vote YES on them — executing Saint = Evil wins immediately.")
                break

    # Investigator: "A or B is minion" + one dead with known role
    for d in (discussion_history or []):
        msg = (d.get("message") or "").lower()
        if "investigator" not in msg or "or" not in msg:
            continue
        for pid in known_roles:
            if pid in msg:
                role = known_roles[pid]
                # If Investigator said A or B is minion, and A (pid) is dead and was Good (e.g. Ravenkeeper, Soldier)
                good_roles = ["ravenkeeper", "soldier", "mayor", "monk", "virgin", "saint", "slayer", "washerwoman", "librarian", "chef", "empath", "fortune teller", "undertaker"]
                if role.lower() in good_roles:
                    hints.append(f"Investigator said one of [A,B] is minion; {pid} is dead and was {role} (Good). The other in the pair is likely the minion — Demon is elsewhere.")

    # Fortune Teller: "A or B pinged" + one dead
    for d in (discussion_history or []):
        msg = (d.get("message") or "").lower()
        if "fortune teller" not in msg and "checked" not in msg:
            continue
        if "ping" in msg or "positive" in msg or "demon" in msg:
            for pid in known_roles:
                if pid in msg:
                    hints.append(f"Fortune Teller said one of pair pinged; {pid} is dead (role {known_roles[pid]}). The other in the pair is the Demon candidate.")

    # Empath caveat: "one of A or B is evil" + A is dead (minion) does NOT mean B is the Demon
    for d in (discussion_history or []):
        msg = (d.get("message") or "").lower()
        if "empath" not in msg or "evil" not in msg or "one" not in msg:
            continue
        if "both" in msg:
            continue
        for pid, role in known_roles.items():
            if role.lower() not in ("baron", "imp", "poisoner", "spy", "scarlet woman"):
                continue
            p = next((x for x in players if x.get("player_id") == pid), None)
            if not p or p.get("is_alive"):
                continue
            name = (p.get("name") or "").lower()
            if name in msg or pid in msg:
                hints.append("Empath: 'one of A or B is evil' + A is dead (minion) means A was the Evil one. The other (B) may be Good — the Demon could be a different player. Do NOT assume B is the Demon.")
                break
        break

    # Empath: "both X and Y are evil" + one dead (Baron) → the alive one is Demon
    seen_empath_demon = False
    for d in (discussion_history or []):
        if seen_empath_demon:
            break
        msg = (d.get("message") or "")
        msg_lower = msg.lower()
        if "empath" not in msg_lower or "evil" not in msg_lower:
            continue
        if "both" not in msg_lower and "neighbors" not in msg_lower:
            continue
        # Find alive player mentioned + dead Baron/Imp mentioned → alive one is Demon
        for p in players:
            if not p.get("is_alive"):
                continue
            pid = p.get("player_id", "")
            name = (p.get("name") or "").strip()
            if not pid or not name or (name.lower() not in msg_lower and pid not in msg):
                continue
            for pid2, role in known_roles.items():
                if role.lower() not in ("baron", "imp"):
                    continue
                p2 = next((x for x in players if x.get("player_id") == pid2), None)
                if not p2 or p2.get("is_alive"):
                    continue
                name2 = (p2.get("name") or "").lower()
                if pid2 in msg or name2 in msg_lower:
                    hints.append(f"Empath said both {name}({pid}) and the dead {role} were evil. {name} is the Demon — execute them, NOT info roles.")
                    seen_empath_demon = True
                    break

    # Ravenkeeper: ghost says "learned X is Imp" = Demon (definitive). "X is Baron/minion" = prioritize.
    seen_ravenkeeper = False
    for d in (discussion_history or []):
        msg = (d.get("message") or "")
        msg_lower = msg.lower()
        if "ravenkeeper" not in msg_lower or "learned" not in msg_lower or seen_ravenkeeper:
            continue
        minion_roles = ["imp", "baron", "poisoner", "spy", "scarlet woman"]
        for mr in minion_roles:
            if mr not in msg_lower:
                continue
            for p in players:
                pid = p.get("player_id", "")
                name = (p.get("name") or "").strip()
                if not pid or not name:
                    continue
                if (pid in msg or name.lower() in msg_lower) and f" {mr}" in msg_lower:
                    if mr == "imp":
                        hints.append(f"⚠️ Ravenkeeper learned {name}({pid}) is the Imp = the Demon. Execute {name}; vote NO on info roles.")
                    else:
                        hints.append(f"Ravenkeeper (ghost) learned {name}({pid}) is {mr.capitalize()}. Prioritize executing them or the Demon.")
                    seen_ravenkeeper = True
                    break
            if seen_ravenkeeper:
                break

    # Virgin claimant: Virgin cannot be the Demon
    for d in (discussion_history or []):
        msg = (d.get("message") or "").lower()
        if "virgin" not in msg:
            continue
        pid = d.get("player_id")
        if pid and re.search(r"\b(i(?:'m| am) (?:the |a )?virgin|as (?:the |a )?virgin)", msg, re.I):
            p = next((x for x in players if x.get("player_id") == pid), None)
            name = (p.get("name") or pid) if p else pid
            hints.append(f"⚠️ {name}({pid}) CLAIMED VIRGIN. Virgin is Townsfolk — CANNOT be the Demon. Do NOT execute them as the Demon. When Imp was executed, Scarlet Woman became the new Demon.")
            break

    # "X is the Demon" / "vote for X" — direct Demon identification
    seen_demon_id = set()
    for d in (discussion_history or []):
        msg = (d.get("message") or "")
        msg_lower = msg.lower()
        if "demon" not in msg_lower and "evil" not in msg_lower and ("vote" not in msg_lower or "execute" not in msg_lower):
            continue
        for p in players:
            if not p.get("is_alive") or p.get("player_id") in seen_demon_id:
                continue
            pid = p.get("player_id", "")
            name = (p.get("name") or "").strip()
            if not pid or not name:
                continue
            if (name.lower() in msg_lower or pid in msg) and ("demon" in msg_lower or ("execute" in msg_lower and "vote" in msg_lower)):
                hints.append(f"Someone identified {name}({pid}) as the Demon — execute them; vote NO on info roles.")
                seen_demon_id.add(pid)
                break

    if not hints:
        return ""
    return "SOLVER HINTS:\n" + "\n".join(f"- {h}" for h in hints) + "\n"


def _player_claimed_virgin(player_id: str, players: list, discussion_history: list) -> bool:
    """True if this player has claimed Virgin in discussion. Virgin cannot be the Demon."""
    nom = next((p for p in players if p.get("player_id") == player_id), None)
    nom_name = (nom.get("name") or "").strip().lower() if nom else ""
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
        if nom_name and len(nom_name) >= 3 and nom_name in msg and "virgin" in msg:
            if "claim" in msg or "is the virgin" in msg or "as the virgin" in msg:
                return True
    return False


def extract_demon_candidate(public_state: dict, discussion_history: list) -> tuple[Optional[str], Optional[str]]:
    """Return (player_id, name) of identified Demon candidate, or (None, None)."""
    players = public_state.get("players", [])
    known_roles = {p["player_id"]: p["role"] for p in players if not p.get("is_alive") and p.get("role") != "unknown"}
    # Count how many messages identify each alive player as Demon/execute target (consensus)
    execute_counts: dict[str, int] = {}
    for p in players:
        if p.get("is_alive") and p.get("player_id"):
            execute_counts[p["player_id"]] = 0

    # Ravenkeeper: "learned X is Imp" → X is the Demon (HIGHEST priority — death info is definitive)
    for d in (discussion_history or []):
        msg = (d.get("message") or "").lower()
        if "ravenkeeper" not in msg or "learned" not in msg or "imp" not in msg:
            continue
        for p in players:
            if not p.get("is_alive"):
                continue
            pid, name = p.get("player_id", ""), (p.get("name") or "").strip()
            if not pid or not name:
                continue
            if (name.lower() in msg or pid in msg) and " imp" in msg:
                if not _player_claimed_virgin(pid, players, discussion_history):
                    return (pid, name)

    # Empath: both X and Y evil, one dead Baron → alive one is Demon
    for d in (discussion_history or []):
        msg = (d.get("message") or "")
        msg_lower = msg.lower()
        if "empath" not in msg_lower or "evil" not in msg_lower or "both" not in msg_lower:
            continue
        for p in players:
            if not p.get("is_alive"):
                continue
            pid, name = p.get("player_id", ""), (p.get("name") or "").strip()
            if not pid or not name or (name.lower() not in msg_lower and pid not in msg):
                continue
            for pid2, role in known_roles.items():
                if role.lower() not in ("baron", "imp"):
                    continue
                p2 = next((x for x in players if x.get("player_id") == pid2), None)
                if not p2 or p2.get("is_alive"):
                    continue
                if pid2 in msg or ((p2.get("name") or "").lower() in msg_lower):
                    if not _player_claimed_virgin(pid, players, discussion_history):
                        return (pid, name)

    # "X is the Demon" / "X must be the Demon" — single strong explicit claim
    for d in (discussion_history or []):
        msg = (d.get("message") or "").lower()
        if "demon" not in msg:
            continue
        for p in players:
            if not p.get("is_alive"):
                continue
            pid, name = p.get("player_id", ""), (p.get("name") or "").strip()
            if not pid or not name or (name.lower() not in msg and pid not in msg):
                continue
            if re.search(rf"\b{re.escape(name.lower())}\s+(?:is|must be)\s+(?:the\s+)?demon", msg, re.I):
                if not _player_claimed_virgin(pid, players, discussion_history):
                    return (pid, name)
            if pid in msg and ("is the demon" in msg or "must be the demon" in msg):
                if not _player_claimed_virgin(pid, players, discussion_history):
                    return (pid, name)

    # "execute X" / "X is Evil" / "vote for X" — count consensus (2+ messages, or 1 if "X is evil")
    for d in (discussion_history or []):
        msg = (d.get("message") or "").lower()
        if "demon" not in msg and "evil" not in msg and "execute" not in msg and "vote" not in msg and "converge" not in msg:
            continue
        for p in players:
            if not p.get("is_alive"):
                continue
            pid, name = p.get("player_id", ""), (p.get("name") or "").strip()
            if not pid or not name:
                continue
            if name.lower() not in msg and pid not in msg:
                continue
            if (
                ("demon" in msg and ("must be" in msg or "is the demon" in msg or "execute" in msg))
                or ("execute" in msg and ("demon" in msg or "vote" in msg or "converge" in msg or "focus" in msg))
                or ("vote" in msg and ("execute" in msg or "demon" in msg))
                or re.search(rf"\b{re.escape(name.lower())}\s+is\s+(?:the\s+)?evil\b", msg)
            ):
                execute_counts[pid] = execute_counts.get(pid, 0) + 1

    # "X is Evil" / "X must be the Demon" — single strong claim from ghost when few alive
    alive_count = sum(1 for p in players if p.get("is_alive", True))
    for d in (discussion_history or []):
        msg = (d.get("message") or "").lower()
        for p in players:
            if not p.get("is_alive"):
                continue
            pid, name = p.get("player_id", ""), (p.get("name") or "").strip()
            if not pid or not name or (name.lower() not in msg and pid not in msg):
                continue
            if re.search(rf"\b{re.escape(name.lower())}\s+is\s+(?:the\s+)?evil\b", msg):
                if alive_count <= 4 and not _player_claimed_virgin(pid, players, discussion_history):
                    return (pid, name)
                execute_counts[pid] = execute_counts.get(pid, 0) + 2

    # Post-minion: FT said "A or B is Demon", one (A) was just executed and is a minion → the other (B) is the Demon
    minion_roles = {"baron", "poisoner", "spy", "scarlet woman"}
    for pid_dead, role in known_roles.items():
        if role.lower() not in minion_roles:
            continue
        p_dead = next((x for x in players if x.get("player_id") == pid_dead), None)
        if not p_dead:
            continue
        name_dead = (p_dead.get("name") or "").lower()
        for d in (discussion_history or []):
            msg = (d.get("message") or "").lower()
            if "fortune teller" not in msg and "demon" not in msg:
                continue
            if name_dead not in msg and pid_dead not in msg:
                continue
            for p in players:
                if not p.get("is_alive"):
                    continue
                pid, name = p.get("player_id", ""), (p.get("name") or "").strip()
                if not pid or not name or pid == pid_dead:
                    continue
                if name.lower() in msg or pid in msg:
                    if not _player_claimed_virgin(pid, players, discussion_history):
                        return (pid, name)

    # Consensus: 2+ messages identify same player as execute/Demon target (exclude Virgin claimants)
    if execute_counts:
        candidates = [(pid, c) for pid, c in execute_counts.items() if c >= 2 and not _player_claimed_virgin(pid, players, discussion_history)]
        if candidates:
            best_pid = max(candidates, key=lambda x: x[1])[0]
            p = next((x for x in players if x.get("player_id") == best_pid), None)
            if p:
                return (best_pid, (p.get("name") or best_pid))
    return (None, None)

