"""
roles.py
--------
All role definitions for the Trouble Brewing script.

Each Role captures:
  - team          : "good" | "evil"
  - role_type     : "townsfolk" | "outsider" | "minion" | "demon"
  - ability_type  : when/how the ability fires
  - description   : human-readable summary (also fed into prompts)
"""

from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────
# Base Role Dataclass
# ─────────────────────────────────────────────

@dataclass
class Role:
    name: str
    team: str           # "good" | "evil"
    role_type: str      # "townsfolk" | "outsider" | "minion" | "demon"
    ability_type: str   # "setup" | "nightly" | "triggered" | "passive" | "once_per_game" | "none"
    description: str
    # Whether this role's info can be made false by poisoning/drunk
    gives_info: bool = False
    # Whether this role acts at night
    acts_at_night: bool = False


# ─────────────────────────────────────────────
# TOWNSFOLK  (Good)
# ─────────────────────────────────────────────

CHEF = Role(
    name="Chef",
    team="good",
    role_type="townsfolk",
    ability_type="setup",
    description=(
        "On the first night, you learn how many pairs of adjacent Evil players "
        "are sitting next to each other."
    ),
    gives_info=True,
    acts_at_night=True,
)

WASHERWOMAN = Role(
    name="Washerwoman",
    team="good",
    role_type="townsfolk",
    ability_type="setup",
    description=(
        "On the first night, you learn that one of two specific players is a "
        "particular Townsfolk role."
    ),
    gives_info=True,
    acts_at_night=True,
)

LIBRARIAN = Role(
    name="Librarian",
    team="good",
    role_type="townsfolk",
    ability_type="setup",
    description=(
        "On the first night, you learn that one of two specific players is a "
        "particular Outsider role. (If no Outsiders are in play, you learn that "
        "no Outsiders are in play.)"
    ),
    gives_info=True,
    acts_at_night=True,
)

INVESTIGATOR = Role(
    name="Investigator",
    team="good",
    role_type="townsfolk",
    ability_type="setup",
    description=(
        "On the first night, you learn that one of two specific players is a "
        "particular Minion role."
    ),
    gives_info=True,
    acts_at_night=True,
)

EMPATH = Role(
    name="Empath",
    team="good",
    role_type="townsfolk",
    ability_type="nightly",
    description=(
        "Each night, you learn how many of your two living neighbours are Evil."
    ),
    gives_info=True,
    acts_at_night=True,
)

FORTUNE_TELLER = Role(
    name="Fortune Teller",
    team="good",
    role_type="townsfolk",
    ability_type="nightly",
    description=(
        "Each night, choose two players. You learn if either one is the Demon. "
        "There is always one player who registers falsely as the Demon."
    ),
    gives_info=True,
    acts_at_night=True,
)

UNDERTAKER = Role(
    name="Undertaker",
    team="good",
    role_type="townsfolk",
    ability_type="nightly",
    description=(
        "Each night (except the first), you learn the role of the player who "
        "was executed during the day."
    ),
    gives_info=True,
    acts_at_night=True,
)

MONK = Role(
    name="Monk",
    team="good",
    role_type="townsfolk",
    ability_type="nightly",
    description=(
        "Each night (except the first), choose a player (not yourself). "
        "That player is safe from the Demon tonight."
    ),
    acts_at_night=True,
)

RAVENKEEPER = Role(
    name="Ravenkeeper",
    team="good",
    role_type="townsfolk",
    ability_type="triggered",
    description=(
        "If you are killed at night, you wake and choose a player. "
        "You learn their role."
    ),
    gives_info=True,
    acts_at_night=True,
)

VIRGIN = Role(
    name="Virgin",
    team="good",
    role_type="townsfolk",
    ability_type="triggered",
    description=(
        "The first time you are nominated, if the nominator is a Townsfolk, "
        "they are immediately executed."
    ),
)

SLAYER = Role(
    name="Slayer",
    team="good",
    role_type="townsfolk",
    ability_type="once_per_game",
    description=(
        "Once per game, during the day, publicly choose a player. "
        "If they are the Demon, they die."
    ),
)

SOLDIER = Role(
    name="Soldier",
    team="good",
    role_type="townsfolk",
    ability_type="passive",
    description="You cannot be killed by the Demon at night.",
)

MAYOR = Role(
    name="Mayor",
    team="good",
    role_type="townsfolk",
    ability_type="passive",
    description=(
        "If only 3 players are alive and no execution occurs that day, "
        "Good wins. If you are killed at night, the Storyteller may redirect "
        "the attack to another player."
    ),
)


# ─────────────────────────────────────────────
# OUTSIDERS  (Good, but with hindrances)
# ─────────────────────────────────────────────

DRUNK = Role(
    name="Drunk",
    team="good",
    role_type="outsider",
    ability_type="passive",
    description=(
        "You do not know you are the Drunk. You think you are a Townsfolk, "
        "but your ability gives false information."
    ),
    gives_info=True,  # False info, but agent THINKS it's real
)

RECLUSE = Role(
    name="Recluse",
    team="good",
    role_type="outsider",
    ability_type="passive",
    description=(
        "You might register as Evil to information roles, even as a specific "
        "Minion type."
    ),
)

BUTLER = Role(
    name="Butler",
    team="good",
    role_type="outsider",
    ability_type="passive",
    description=(
        "Each night, choose a player (your master). You may only vote if your "
        "master is voting too."
    ),
    acts_at_night=True,
)

SAINT = Role(
    name="Saint",
    team="good",
    role_type="outsider",
    ability_type="triggered",
    description="If you are executed, Evil wins immediately.",
)


# ─────────────────────────────────────────────
# MINIONS  (Evil)
# ─────────────────────────────────────────────

POISONER = Role(
    name="Poisoner",
    team="evil",
    role_type="minion",
    ability_type="nightly",
    description=(
        "Each night, choose a player. That player is poisoned until the next "
        "nightfall — their ability gives false information (if any)."
    ),
    acts_at_night=True,
)

SPY = Role(
    name="Spy",
    team="evil",
    role_type="minion",
    ability_type="passive",
    description=(
        "Each night, you see the Grimoire (all roles and statuses). "
        "You might register as Good to information roles."
    ),
    acts_at_night=True,
    gives_info=True,
)

BARON = Role(
    name="Baron",
    team="evil",
    role_type="minion",
    ability_type="setup",
    description=(
        "There are an extra two Outsiders in play (and two fewer Townsfolk)."
    ),
)

SCARLET_WOMAN = Role(
    name="Scarlet Woman",
    team="evil",
    role_type="minion",
    ability_type="triggered",
    description=(
        "If there are five or more players alive and the Demon dies, "
        "you become the Demon."
    ),
)


# ─────────────────────────────────────────────
# DEMON  (Evil)
# ─────────────────────────────────────────────

IMP = Role(
    name="Imp",
    team="evil",
    role_type="demon",
    ability_type="nightly",
    description=(
        "Each night (except the first), choose a player. They die. "
        "If you kill yourself, a living Minion becomes the Demon."
    ),
    acts_at_night=True,
)


# ─────────────────────────────────────────────
# Convenience lookup
# ─────────────────────────────────────────────

ALL_ROLES: dict[str, Role] = {
    r.name: r for r in [
        CHEF, WASHERWOMAN, LIBRARIAN, INVESTIGATOR, EMPATH, FORTUNE_TELLER,
        UNDERTAKER, MONK, RAVENKEEPER, VIRGIN, SLAYER, SOLDIER, MAYOR,
        DRUNK, RECLUSE, BUTLER, SAINT,
        POISONER, SPY, BARON, SCARLET_WOMAN,
        IMP,
    ]
}

TOWNSFOLK_ROLES = [r for r in ALL_ROLES.values() if r.role_type == "townsfolk"]
OUTSIDER_ROLES  = [r for r in ALL_ROLES.values() if r.role_type == "outsider"]
MINION_ROLES    = [r for r in ALL_ROLES.values() if r.role_type == "minion"]
DEMON_ROLES     = [r for r in ALL_ROLES.values() if r.role_type == "demon"]
