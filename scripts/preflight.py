"""Credential-safe offline/catalog checks and opt-in real streaming smoke tests."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import wave
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from pickmate.voice.providers import CATALOG_URL, RimeConfig, error_category, validate_catalog  # noqa: E402

REQUIRED = (
    "RIME_API_KEY",
    "DEEPGRAM_API_KEY",
    "OPENAI_API_KEY",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "WORKER_SECRET",
)


def scan_secrets():
    """Inspect tracked and candidate generated source; report paths only, never values."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    findings = []
    secrets = [os.getenv(k) for k in REQUIRED if "KEY" in k or "SECRET" in k]
    for name in result.stdout.decode().split("\0"):
        path = ROOT / name
        if not name or not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        if any(p in ("node_modules", ".venv", ".git") for p in path.parts):
            continue
        content = path.read_bytes()
        if b"\0" in content:
            continue
        value = content.decode(errors="replace")
        known = any(s and len(s) >= 12 and s in value for s in secrets)
        pattern = bool(re.search(r"(?:sk-proj-|sk-live-|sk_test_)[A-Za-z0-9_-]{24,}", value))
        private_key = "-----BEGIN " + "PRIVATE KEY-----" in value
        if known or pattern or private_key:
            findings.append(name)
    return findings


async def synthesis(config, output):
    import aiohttp
    from livekit.agents import APIConnectOptions

    clips = []
    async with aiohttp.ClientSession() as http:
        provider = config.make_tts(http_session=http)
        try:
            for index, text in enumerate(
                ("Pick four red cartons from bin B-04.", "Pick four red cartons. Bin B, zero four."), 1
            ):
                started = time.monotonic()
                first = None
                frames = bytearray()
                async with asyncio.timeout(30):
                    async with provider.stream(
                        conn_options=APIConnectOptions(timeout=10, max_retry=0)
                    ) as stream:
                        stream.push_text(text)
                        stream.end_input()
                        async for event in stream:
                            if first is None:
                                first = time.monotonic() - started
                            frames.extend(event.frame.data.cast("B"))
                if not frames:
                    raise RuntimeError("Rime returned no audio")
                path = output / f"bin-variant-{index}.wav"
                with wave.open(str(path), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(config.sample_rate)
                    wav.writeframes(frames)
                clips.append(
                    {
                        "text": text,
                        "file": path.name,
                        "pcm_bytes": len(frames),
                        "first_decoded_frame_seconds": first,
                        "listening_comparison": "pending human review",
                    }
                )
        finally:
            await provider.aclose()
    return clips


async def llm_smoke():
    from pickmate.domain.language import resolve
    from pickmate.storage.seed import inventory
    from pickmate.voice.interpreter import Interpreter

    model = os.getenv("LLM_MODEL", "gpt-4.1-mini-2025-04-14")
    adapter = Interpreter(os.environ["OPENAI_API_KEY"], model)
    items = [item.model_dump() for item in inventory()]
    started = time.monotonic()
    try:
        async with asyncio.timeout(15):
            proposal = await adapter.interpret("Find four red cartons", None, items)
        item = resolve(proposal.query or "", items)
        if proposal.action != "request" or proposal.quantity != 4 or not item or item["sku"] != "CT-RED":
            raise ValueError("Live model did not return the expected complete structured operation")
        return {
            "model": model,
            "streaming_tool_call": "validated",
            "duration_ms": (time.monotonic() - started) * 1000,
        }
    finally:
        await adapter.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live", action="store_true", help="Require all live credentials and real Rime synthesis"
    )
    parser.add_argument("--catalog-file", type=Path, help="Use an explicitly downloaded catalog")
    parser.add_argument(
        "--offline", action="store_true", help="Skip network; catalog and synthesis remain unverified"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "evidence" / "preflight")
    args = parser.parse_args()
    if args.live and args.offline:
        parser.error("--live cannot be combined with --offline")
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    args.output.mkdir(parents=True, exist_ok=True)
    record = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if args.live else "preflight",
        "missing_credentials": [key for key in REQUIRED if not os.getenv(key)],
        "catalog": "not run",
        "synthesis": "not run",
        "llm_streaming": "not run",
        "organizer_checker": "not supplied; pending",
        "versions": {
            p: version(p)
            for p in (
                "livekit-agents",
                "livekit-plugins-rime",
                "livekit-plugins-deepgram",
                "livekit-plugins-silero",
                "livekit-plugins-openai",
                "openai",
            )
        },
    }
    failed = False
    try:
        config = RimeConfig.from_env()
        record["configuration"] = config.public()
        record["secret_exposure_paths"] = scan_secrets()
        failed |= bool(record["secret_exposure_paths"])
        if not args.offline:
            if args.catalog_file:
                raw = args.catalog_file.read_bytes()
                source = str(args.catalog_file)
            else:
                with urllib.request.urlopen(CATALOG_URL, timeout=20) as response:
                    raw = response.read(2_000_000)
                source = CATALOG_URL
            record["catalog"] = {
                "source": source,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "validated": validate_catalog(json.loads(raw), config),
            }
        if os.getenv("RIME_API_KEY") and not args.offline:
            record["synthesis"] = asyncio.run(synthesis(config, args.output))
        if os.getenv("OPENAI_API_KEY") and not args.offline:
            record["llm_streaming"] = asyncio.run(llm_smoke())
        if args.live and (record["missing_credentials"] or record["synthesis"] == "not run"):
            failed = True
    except Exception as error:
        failed = True
        record["error_category"] = error_category(error)
        record["error_type"] = type(error).__name__
    record["passed_requested_checks"] = not failed
    target = args.output / ("preflight-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    target.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))
    print(f"Evidence: {target}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
