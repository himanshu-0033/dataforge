"""Reviewable synthetic conversation evaluation; no training job or private transcript collection."""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from counselor.config import Settings  # noqa: E402
from counselor.conversation import Conversation  # noqa: E402


async def evaluate(cases, output, model=None, thinking_level=None, mode=None):
    settings = Settings(_env_file=ROOT / ".env")
    if model:
        settings = Settings(_env_file=ROOT / ".env", vertex_model=model, vertex_voice_model=model)
    if thinking_level:
        settings.vertex_thinking_level = thinking_level
        settings.vertex_voice_thinking_level = thinking_level
    if settings.conversation_missing():
        print("Missing configuration: " + ", ".join(settings.conversation_missing()))
        return 1
    conversation = Conversation(settings)
    results = []
    try:
        for case in cases:
            started = time.monotonic()
            first_delta = None

            def delta(text):
                nonlocal first_delta
                if first_delta is None:
                    first_delta = time.monotonic() - started

            result = {"id": case["id"], "review_criteria": case["review"], "human_review": "pending"}
            try:
                async with asyncio.timeout(60):
                    history = list(case["messages"])
                    dialogue = []
                    for followup in [None, *case.get("followups", [])]:
                        if followup is not None:
                            history.append({"role": "user", "content": followup})
                        answer = await conversation.reply(
                            history,
                            support=case.get("support", "explore"),
                            focus=case.get("focus", ""),
                            mode=mode or case.get("mode", "text"),
                            on_delta=delta,
                        )
                        dialogue.append({"user": history[-1]["content"], "reply": answer})
                        history.append({"role": "assistant", "content": answer})
                    result["reply"] = answer
                    if case.get("followups"):
                        result["dialogue"] = dialogue
                result["completed"] = True
            except Exception as error:
                # Provider bodies, authentication details and credential material
                # never enter the report, stdout, or a traceback.
                result.update(completed=False, error_type=type(error).__name__)
                if isinstance(error, httpx.HTTPStatusError):
                    result["http_status"] = error.response.status_code
            result.update(seconds=round(time.monotonic() - started, 2), first_delta_seconds=first_delta)
            results.append(result)
            print(json.dumps(result, ensure_ascii=True), flush=True)
            if not result["completed"]:
                break
    finally:
        await conversation.close()
    record = {
        "provider": conversation.provider,
        "model": conversation.voice_backend.model if mode == "live" else conversation.model,
        "mode_override": mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "synthetic_cases_only": True,
        "quality_is_not_automatically_scored": True,
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if all(row["completed"] for row in results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Call the configured paid provider using synthetic cases"
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--skip", type=int, default=0)
    parser.add_argument(
        "--model", help="Evaluate a specific Vertex model without changing the app configuration"
    )
    parser.add_argument("--thinking-level", choices=["MINIMAL", "LOW", "MEDIUM", "HIGH"])
    parser.add_argument("--mode", choices=["live", "text"], help="Override delivery mode for every case")
    parser.add_argument("--output", type=Path, default=ROOT / ".cache" / "conversation-evaluation.json")
    args = parser.parse_args()
    if args.limit < 1 or args.skip < 0:
        parser.error("--limit must be positive and --skip must be nonnegative")
    cases = json.loads((ROOT / "fixtures" / "counselor-conversations.json").read_text(encoding="utf-8"))[
        args.skip : args.skip + args.limit
    ]
    if not cases:
        parser.error("No cases selected")
    if not args.live:
        print(json.dumps(cases, indent=2, ensure_ascii=True))
        return 0
    return asyncio.run(evaluate(cases, args.output, args.model, args.thinking_level, args.mode))


if __name__ == "__main__":
    raise SystemExit(main())
