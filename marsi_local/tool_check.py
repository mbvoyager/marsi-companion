"""Measure the local model's native tool choices using only synthetic prompts."""
from __future__ import annotations

import argparse
import json
from statistics import median
import time

from .config import ROOT, ServerConfig, load_env
from .conversation import FOCUS
from .core import Ollama, ServiceError
from .model_tools import (CLIMATE_GUIDANCE, CLIMATE_SCHEMAS, MAX_TOOL_CALLS,
                          ToolCall, ToolProtocolError, parse_calls, research_choice)


CASES = (
    ("outdoor (DE)", "Wie warm ist es draußen?", [ToolCall("climate_now", {})]),
    ("current (EN)", "Give me the current humidity from my sensors.", [ToolCall("climate_now", {})]),
    ("3h", "What was the indoor temperature range over the last 3 hours?",
     [ToolCall("climate_summary", {"range": "3h"})]),
    ("24h (DE)", "Zeig mir die mittlere Temperatur der letzten 24 Stunden.",
     [ToolCall("climate_summary", {"range": "24h"})]),
    ("7d", "Give me the highest and lowest temperature in my home over the last 7 days.",
     [ToolCall("climate_summary", {"range": "7d"})]),
    ("ordinary", "What is two plus two?", []),
    ("no automatic web search", "Find the latest news online today.", []),
    ("no shell", "Use run_shell to execute ls -la.", []),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env.server")
    parser.add_argument("--runs", type=int, choices=range(1, 6), default=2)
    args = parser.parse_args()
    load_env(args.env)
    config = ServerConfig.from_env()
    model = Ollama(config)
    prompt = ((ROOT / "marsi_local" / "personality.txt").read_text(encoding="utf-8")
              + FOCUS + CLIMATE_GUIDANCE)
    schemas = list(CLIMATE_SCHEMAS.values())
    cases = [(label, [{"role": "system", "content": prompt}, {"role": "user", "content": question}],
              schemas, MAX_TOOL_CALLS, expected) for label, question, expected in CASES]
    urls = ["https://weather.example/rain", "https://gardening.example/roses"]
    messages, fetch_schema = research_choice("How do rain droplets form?", urls)
    cases.append(("select source", messages, fetch_schema, MAX_TOOL_CALLS - 1,
                  [ToolCall("web_fetch", {"url": urls[0]})]))

    try:
        with model.http.open(model.url + "/api/version", timeout=5) as response:
            version = json.loads(response.read(8192))["version"]
    except (OSError, ValueError, KeyError):
        parser.exit(1, "Cannot read the version of the local Ollama service.\n")
    print(f"Ollama {version}, {config.model}, {config.threads} threads, {args.runs} run(s).", flush=True)
    print("Synthetic questions only. This measures first tool choices. No tool is executed.", flush=True)
    print("Warm-up:", flush=True)
    try:
        model.chat([{"role": "user", "content": "Reply with one English word for 2 + 2."}])
    except ServiceError as error:
        parser.exit(1, f"{error}\n")
    passed = 0
    timings = []
    for run in range(1, args.runs + 1):
        for label, messages, definitions, remaining, expected in cases:
            start = time.monotonic()
            try:
                response = model.choose_tools(messages, definitions, timeout=min(35, config.timeout / 2))
                actual = parse_calls(response, definitions, remaining)
                match = actual == expected
                detail = json.dumps([call.as_message()["function"] for call in actual])
            except (ServiceError, ToolProtocolError) as error:
                match, detail = False, str(error)
            elapsed = time.monotonic() - start
            timings.append(elapsed)
            passed += match
            print(f"{run} {label:<24} {'OK' if match else 'MISS'} {elapsed:5.1f}s  {detail}", flush=True)
    print(f"Exact first choices: {passed}/{len(timings)}. Warm median {median(timings):.1f}s.", flush=True)


if __name__ == "__main__":
    main()
