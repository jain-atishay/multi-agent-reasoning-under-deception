"""
main.py
-------
Entry point. Uses GameRunner which follows the architecture diagram exactly.

Examples:
  # Smoke test - random agents, no LLM, no cost
  python main.py --mode random --players 7 --games 5

  # Interactive: pause after each vote so a human can inspect state
  python main.py --mode random --games 3 --hitl interactive

  # LLM game (requires OPENAI_API_KEY)
  python main.py --mode llm --players 7 --variant strategic --games 10

  # Ablation: run all variants, 50 games each
  python main.py --mode ablation --games 50 --players 7

  # Proposal ablation (Slide 13): baseline | belief_only | learning_only | full
  python main.py --mode ablation_proposal --games 50 --players 7 --seed 42
"""
from dotenv import load_dotenv
load_dotenv()
import argparse
import os

from clocktower.agents.random_agent import RandomAgent
from clocktower.agents.llm_agent import LLMAgent
from clocktower.game_runner import GameRunner, HumanInTheLoop


def random_factory(num_players):
    def factory():
        return [RandomAgent(f"Player_{i+1}") for i in range(num_players)]
    return factory


def llm_factory(num_players, variant, model, api_key, base_url=None,
                use_belief_modeling=True, use_learning=True):
    names = ["Alice", "Bob", "Charlie", "Diana", "Eve", "Frank", "Grace",
             "Hank", "Iris", "Jake", "Kira", "Leo", "Mia", "Ned", "Olga"][:num_players]
    # Memory buffers persist across games (only when use_learning=True)
    memory_buffers = {name: [] for name in names}

    def factory():
        agents = []
        for name in names:
            agent = LLMAgent(
                name=name, model=model, variant=variant,
                api_key=api_key, base_url=base_url,
                use_belief_modeling=use_belief_modeling,
                use_learning=use_learning,
            )
            agent.memory_buffer = memory_buffers[name]  # shared ref so reflections persist
            agents.append(agent)
        return agents
    return factory


def main():
    parser = argparse.ArgumentParser(description="Blood on the Clocktower Multi-Agent Engine")
    parser.add_argument("--mode",
        choices=["random", "llm", "ablation", "ablation_proposal"],
        default="random",
        help="ablation=prompt variants; ablation_proposal=belief/learning ablations (Slide 13)")
    parser.add_argument("--players", type=int, default=7)
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--variant",
        choices=["baseline", "strategic", "cautious", "aggressive", "analytical"],
        default="strategic")
    parser.add_argument("--model", default=None,
        help="Model name. Default: OPENAI_MODEL from .env, else gpt-3.5-turbo. For Triton: api-mistral-small-3.2-2506")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--api-base", default=None,
        help="API base URL for LiteLLM/university proxy (or set OPENAI_API_BASE in .env)")
    parser.add_argument("--hitl", choices=["none", "print", "interactive"], default="none")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--stats", default="logs/stats.json")
    parser.add_argument("--max-rounds", type=int, default=15,
        help="Max rounds before Evil wins (default 15, gives Good more chances)")

    args = parser.parse_args()
    model = args.model or os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")
    hitl = HumanInTheLoop(mode=args.hitl, delay_seconds=0.5)

    if args.mode == "random":
        GameRunner(
            agent_factory=random_factory(args.players),
            num_games=args.games,
            stats_path=args.stats,
            max_rounds=args.max_rounds,
            human_in_the_loop=hitl,
            agent_variant="random",
            random_seed=args.seed,
        ).run()

    elif args.mode == "llm":
        api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("ERROR: Set OPENAI_API_KEY or pass --api-key")
        base_url = args.api_base or os.environ.get("OPENAI_API_BASE")
        GameRunner(
            agent_factory=llm_factory(args.players, args.variant, model, api_key, base_url),
            num_games=args.games,
            stats_path=args.stats,
            max_rounds=args.max_rounds,
            human_in_the_loop=hitl,
            agent_variant=args.variant,
            random_seed=args.seed,
        ).run()

    elif args.mode == "ablation":
        api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
        print("[Ablation] Running random baseline...")
        GameRunner(
            agent_factory=random_factory(args.players),
            num_games=args.games, stats_path=args.stats,
            max_rounds=args.max_rounds, agent_variant="random",
            random_seed=args.seed, verbose=False,
        ).run()

        if api_key:
            for variant in ["baseline", "strategic", "analytical"]:
                print(f"[Ablation] Running variant: {variant}...")
                GameRunner(
                    agent_factory=llm_factory(args.players, variant, model, api_key,
                        os.environ.get("OPENAI_API_BASE")),
                    num_games=args.games, stats_path=args.stats,
                    max_rounds=args.max_rounds, agent_variant=variant,
                    random_seed=args.seed, verbose=False,
                ).run()
        else:
            print("[Ablation] No OPENAI_API_KEY - skipping LLM variants.")

    elif args.mode == "ablation_proposal":
        # Per proposal Slide 13: 50 games each
        # baseline (no beliefs, no learning) | belief_modeling | learning | full
        api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("ERROR: ablation_proposal requires OPENAI_API_KEY")
        base_url = args.api_base or os.environ.get("OPENAI_API_BASE")

        configs = [
            ("baseline", False, False),
            ("belief_only", True, False),
            ("learning_only", False, True),
            ("full", True, True),
        ]
        for label, use_belief, use_learning in configs:
            print(f"[Ablation Proposal] Running: {label} (belief={use_belief}, learning={use_learning})...")
            GameRunner(
                agent_factory=llm_factory(
                    args.players, args.variant, model, api_key, base_url,
                    use_belief_modeling=use_belief,
                    use_learning=use_learning,
                ),
                num_games=args.games, stats_path=args.stats,
                max_rounds=args.max_rounds, agent_variant=label,
                random_seed=args.seed, verbose=False,
            ).run()


if __name__ == "__main__":
    main()
