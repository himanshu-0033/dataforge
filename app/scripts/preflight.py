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
from counselor.config import GROQ_BASE_URL, Settings  # noqa: E402
from counselor.conversation import Conversation  # noqa: E402
from counselor.providers import CATALOG_URL, RimeConfig, error_category, validate_catalog  # noqa: E402

REQUIRED = (
    "RIME_API_KEY",
    "DEEPGRAM_API_KEY",
    "GROQ_API_KEY",
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
    secrets = [
        os.getenv(k)
        for k in (*REQUIRED, "GOOGLE_CREDENTIALS_BASE64")
        if ("KEY" in k or "SECRET" in k or "CREDENTIALS" in k)
    ]
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
        pattern = bool(re.search(r"(?:sk-proj-|sk-live-|sk_test_|gsk_)[A-Za-z0-9_-]{24,}", value))
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
                ("Hi, I'm Heard. What's on your mind?", "Take your time. We can talk this through."), 1
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
                path = output / f"voice-sample-{index}.wav"
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
    settings = Settings(_env_file=None)
    adapter = Conversation(settings)
    started = time.monotonic()
    try:
        async with asyncio.timeout(60):
            await adapter.reply(
                [{"role": "user", "content": "I'm feeling overwhelmed by exams. Can we talk?"}]
            )
        return {
            "provider": adapter.provider,
            "endpoint": "Vertex Gemini" if adapter.provider == "vertex" else GROQ_BASE_URL,
            "model": adapter.model,
            "streaming_response": "completed",
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
    parser.add_argument("--output", type=Path, default=ROOT / ".cache" / "preflight")
    args = parser.parse_args()
    if args.live and args.offline:
        parser.error("--live cannot be combined with --offline")
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    args.output.mkdir(parents=True, exist_ok=True)
    settings = Settings(_env_file=None)
    record = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if args.live else "preflight",
        "missing_credentials": settings.missing(),
        "catalog": "not run",
        "synthesis": "not run",
        "llm_streaming": "not run",
        "llm_configuration": {
            "provider": settings.counselor_provider,
            "model": settings.vertex_model if settings.counselor_provider == "vertex" else settings.llm_model,
            "endpoint": "Vertex Gemini" if settings.counselor_provider == "vertex" else GROQ_BASE_URL,
        },
        "versions": {
            p: version(p)
            for p in (
                "livekit-agents",
                "livekit-plugins-rime",
                "livekit-plugins-deepgram",
                "livekit-plugins-silero",
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
        if not settings.conversation_missing() and not args.offline:
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
