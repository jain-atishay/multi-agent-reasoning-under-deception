# Blood on the Clocktower — Multi-Agent Game Engine

Python game engine for the CSE 291A research project:  
**"Studying Multi-Agent Reasoning Under Deception"**

---

## Architecture

```
clocktower_engine/
├── main.py                         # Entry point / CLI
├── requirements.txt
└── clocktower/
    ├── roles.py                    # All 22 Trouble Brewing role definitions
    ├── game_state.py               # Player, GameState data models
    ├── storyteller.py              # Full game orchestrator (night + day logic)
    ├── logger.py                   # Structured JSON/NDJSON event logging
    └── agents/
        ├── base_agent.py           # Abstract interface all agents implement
        ├── random_agent.py         # Rule-free random bot (for baseline / testing)
        └── llm_agent.py            # GPT-4 agent with full prompt engineering
```

---

## Quick Start

### 1. Smoke test (no LLM, free)
```bash
python main.py --mode random --players 7 --games 5
```

### 2. Single LLM game
```bash
export OPENAI_API_KEY=sk-...
python main.py --mode llm --players 7 --variant strategic
```

### 3. Ablation study (50 games)
```bash
python main.py --mode ablation --games 50 --players 7
```

---

## Adding Your Own Agent

Subclass `BaseAgent` and implement 4 methods:

```python
from clocktower.agents.base_agent import BaseAgent

class MyAgent(BaseAgent):
    def choose_night_target(self, action, valid_targets, public_state):
        # Return a player_id string
        ...

    def discuss(self, public_state, discussion_history, round_number, is_dead=False):
        # Return a string message, or None to stay silent
        ...

    def nominate(self, valid_nominees, public_state, discussion_history):
        # Return a player_id to nominate, or None to pass
        ...

    def vote(self, nominee_id, nominator_id, public_state, discussion_history):
        # Return True to vote for execution, False to pass
        ...
```

---

## Switching to AutoGen

In `llm_agent.py`, replace `_call_llm()`:

```python
def _call_llm(self, system_prompt: str, user_message: str) -> str:
    from autogen import ConversableAgent
    agent = ConversableAgent(
        name=self.name,
        system_message=system_prompt,
        llm_config={"model": self.model, "api_key": self.api_key},
    )
    reply = agent.generate_reply(
        messages=[{"role": "user", "content": user_message}]
    )
    return reply or ""
```

---

## Logging

Every game writes two files to `logs/`:
- `{game_id}_{timestamp}_events.ndjson` — one JSON event per line (real-time)
- `{game_id}_{timestamp}_summary.json` — full game summary with all events

Key event types: `game_setup`, `night_action`, `info_delivery`, `discussion`,  
`nomination`, `vote`, `execution`, `death`, `game_end`, `reflection`

---

## Prompt Variants

| Variant      | Good strategy             | Evil strategy                     |
|-------------|---------------------------|-----------------------------------|
| `baseline`   | Share info, vote freely   | Lie, survive                      |
| `strategic`  | Cross-reference claims    | Coordinated bluffing              |
| `cautious`   | Hold info back            | Stay quiet, low-risk              |
| `aggressive` | Push nominations fast     | Dominate discussion               |
| `analytical` | Bayesian world-modelling  | Craft internally consistent lies  |

---

## Supported Roles (Trouble Brewing)

**Townsfolk:** Chef, Washerwoman, Librarian, Investigator, Empath, Fortune Teller,  
Undertaker, Monk, Ravenkeeper, Virgin, Slayer, Soldier, Mayor

**Outsiders:** Drunk, Recluse, Butler, Saint

**Minions:** Poisoner, Spy, Baron, Scarlet Woman

**Demon:** Imp
