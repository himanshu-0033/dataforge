"""Explicit provider configuration. Catalog validation is an offline pure function."""

import os
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

CATALOG_URL = "https://users.rime.ai/data/voices/all-v2.json"


@dataclass(frozen=True)
class RimeConfig:
    model: str = "coda"
    speaker: str = "hesse"
    language: str = "en"
    sample_rate: int = 24000
    base_url: str = "wss://users-ws.rime.ai"
    segment: str = "bySentence"

    @classmethod
    def from_env(cls):
        return cls(
            model=os.getenv("RIME_MODEL", "coda"),
            speaker=os.getenv("RIME_SPEAKER", "hesse"),
            language=os.getenv("RIME_LANGUAGE", "en"),
            sample_rate=int(os.getenv("RIME_SAMPLE_RATE", "24000")),
            base_url=os.getenv("RIME_BASE_URL", "wss://users-ws.rime.ai").rstrip("/"),
        )

    def validate(self):
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "wss"
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("RIME_BASE_URL must be a bare secure WebSocket origin; plugin appends /ws3")
        if not parsed.hostname.endswith(".rime.ai"):
            raise ValueError("RIME_BASE_URL must use an official Rime host")
        if self.sample_rate not in (8000, 16000, 22050, 24000, 44100, 48000):
            raise ValueError("Unsupported sample rate")
        if self.language not in ("en", "eng"):
            raise ValueError("This MVP accepts English only")
        if self.segment != "bySentence":
            raise ValueError("This path requires bySentence segmentation")

    def public(self):
        self.validate()
        return {
            **asdict(self),
            "endpoint": self.base_url + "/ws3",
            "use_websocket": True,
            "audio_format": "PCM signed 16-bit mono",
            "region": {
                "wss://users-ws.rime.ai": "US West (us-west-2)",
                "wss://users-east-ws.rime.ai": "US East (us-east-1)",
            }.get(self.base_url, "unverified"),
            "region_selection_measurement": "not run",
        }

    def make_tts(self, *, api_key=None, http_session=None):
        from livekit.plugins import rime

        self.validate()
        key = api_key or os.getenv("RIME_API_KEY")
        if not key:
            raise ValueError("RIME_API_KEY is required")
        return rime.TTS(
            model=self.model,
            speaker=self.speaker,
            lang=self.language,
            sample_rate=self.sample_rate,
            base_url=self.base_url,
            use_websocket=True,
            segment=self.segment,
            api_key=key,
            http_session=http_session,
        )


def validate_catalog(catalog, config: RimeConfig):
    config.validate()
    if not isinstance(catalog, dict) or not catalog:
        raise ValueError("Catalog must be model -> language -> speaker list")
    for languages in catalog.values():
        if not isinstance(languages, dict) or not languages:
            raise ValueError("Invalid catalog language map")
        for voices in languages.values():
            if not isinstance(voices, list) or not all(isinstance(v, str) for v in voices):
                raise ValueError("Invalid catalog speaker list")
    language = "eng" if config.language == "en" else config.language
    if config.speaker not in catalog.get(config.model, {}).get(language, []):
        raise ValueError("Selected model, speaker and language are absent from catalog")
    return {"model": config.model, "speaker": config.speaker, "catalog_language": language}


def error_category(error):
    status = getattr(error, "status_code", None)
    if status in (401, 403):
        return "authentication"
    if status == 429:
        return "rate_limit"
    if status in (400, 404, 422):
        return "invalid_configuration_or_input"
    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
        return "timeout"
    return "provider_or_network"
