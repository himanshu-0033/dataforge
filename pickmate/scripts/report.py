import argparse
import json
from pathlib import Path

from pickmate.observability.report import audio_summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stress", type=Path, default=Path("evidence/stress"))
    parser.add_argument("--audio-annotations", type=Path)
    parser.add_argument("--output", type=Path, default=Path("evidence/report.json"))
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.stress / "trials.jsonl").read_text().splitlines() if line]
    audio = (
        []
        if not args.audio_annotations
        else [json.loads(line) for line in args.audio_annotations.read_text().splitlines() if line]
    )
    result = {
        "fixture": {
            "n": len(rows),
            "passed": sum(r["passed"] for r in rows),
            "stale_instruction_leaks": sum(r["stale_instruction_leaks"] for r in rows),
            "duplicate_writes": sum(r["duplicate_writes"] for r in rows),
            "failed_trials": [r["trial"] for r in rows if not r["passed"]],
        },
        "audio": audio_summary(audio),
        "end_of_turn_to_first_audio": "not run",
        "end_of_turn_to_substantive_audio": "not run",
        "stt_latency": "not run",
        "reasoning_latency": "not run",
        "tts_first_byte": "see preflight records; not run if no synthesis",
        "physical_barge_in": "unverified"
        if not audio
        else "inspect strata; rendered proxies do not establish audibility",
        "live_recording": "pending" if not audio else "see supplied annotation references",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
