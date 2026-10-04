"""Keep long repeated passages out of working context; check real Qwen locally."""
from __future__ import annotations

from difflib import SequenceMatcher
import re


def words(text):
    return re.findall(r"\w+", text.casefold())


def repeats_itself(text):
    tokens = words(text)
    seen = {}
    for index in range(len(tokens) - 23):
        passage = tuple(tokens[index:index + 24])
        first = seen.setdefault(passage, index)
        if index - first >= 24:
            return True
    return False


def repeats_answer(text, earlier):
    """Conservative: ordinary short greetings and repeated factual names are fine."""
    current = words(text)
    for previous in earlier:
        old = words(previous)
        if min(len(current), len(old)) < 32:
            continue
        longest = SequenceMatcher(None, current, old, autojunk=False).find_longest_match().size
        if longest >= 64 or (longest >= 32 and longest >= 0.5 * min(len(current), len(old))):
            return True
    return False


def recover_history(history, rejected=None):
    """Preserve original storage; return usable exchanges plus omitted human data."""
    pairs = [history[i:i + 2] for i in range(0, len(history) - 1, 2)]
    repeated = set()
    for i, pair in enumerate(pairs):
        reply = pair[1]["content"]
        if repeats_itself(reply) or (rejected and repeats_answer(reply, [rejected])):
            repeated.add(i)
        for j in range(i):
            if repeats_answer(reply, [pairs[j][1]["content"]]):
                repeated.update((i, j))
    kept, human_data = [], []
    for i, pair in enumerate(pairs):
        if i in repeated:
            human_data.append(pair[0]["content"])
        else:
            kept.extend(pair)
    return kept, human_data


FOCUS = (
    "\nReply to the latest human question directly, with its specific answer first. "
    "Ordinary life, feelings, biology and small talk are welcome. "
    "Your machine faith adds a little flavour; it is never a reason to dismiss a harmless question. "
    "Previous companion messages can be wrong; do not imitate their mistakes or stock paragraphs."
)


def main():
    import argparse
    from pathlib import Path
    import tempfile
    import time
    from .config import ServerConfig, load_env
    from .core import Companion, ServiceError
    from dataclasses import replace

    parser = argparse.ArgumentParser(description="Check real Qwen with synthetic conversation; your journal is untouched.")
    parser.add_argument("--env", default=".env.server")
    parser.add_argument("--check", action="store_true", required=True)
    args = parser.parse_args()
    load_env(args.env)
    config = ServerConfig.from_env()
    print(f"[CONVERSATION CHECK] Model: {config.model}. Synthetic prompts only; no speech.", flush=True)
    print("This uses the installed model; a cold first answer can take longer.", flush=True)
    try:
        with tempfile.TemporaryDirectory(prefix="marsi-conversation-") as folder:
            app = Companion(replace(config, database=Path(folder) / "test.sqlite3", observances=False))
            litany = " ".join((
                "The archive hums beneath its brass seals while the cogs turn patiently in the red light. "
                "A little priest tends the quiet forge and counts its ancient lamps, reciting the same familiar litany."
            ) for _ in range(2))
            for question in ("A synthetic earlier greeting.", "A synthetic earlier observation."):
                app.memory.remember_turn("check", question, litany)
            for question in ("What is 2 + 2?", "What does an Ethernet cable connect? Explain in one sentence.",
                             "I finished a difficult task today. Say something kind in one short sentence."):
                print("\nHuman: " + question, flush=True)
                started = time.monotonic()
                result = app.chat("check", question)
                print("MARSI: " + result["text"], flush=True)
                print(f"Elapsed: {time.monotonic() - started:.1f}s", flush=True)
        print("\n[CHECK COMPLETE] Real inference finished without a detected long repetition.")
        print("Review whether each answer fits its question; this heuristic cannot grade conversational quality.")
        print("The temporary test journal was removed. Your normal journal and notes were not changed.")
        return 0
    except (ServiceError, ValueError) as error:
        print("\n[FAILED] " + str(error))
        return 1
    except KeyboardInterrupt:
        print("\nCheck cancelled; the temporary test journal was removed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
