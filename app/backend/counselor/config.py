import base64
import json
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"
AGENT_NAME = "heard"
ROOM_PREFIX = "heard-"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    api_url: str = "http://127.0.0.1:8000"
    web_origin: str = "http://localhost:5173"
    worker_secret: str = Field(default="", repr=False)
    livekit_url: str = ""
    livekit_api_key: str = Field(default="", repr=False)
    livekit_api_secret: str = Field(default="", repr=False)
    rime_api_key: str = Field(default="", repr=False)
    deepgram_api_key: str = Field(default="", repr=False)
    groq_api_key: str = Field(default="", repr=False)
    llm_model: str = DEFAULT_LLM_MODEL
    counselor_provider: Literal["groq", "vertex"] = "groq"
    google_credentials_base64: SecretStr = Field(default="", repr=False)
    google_cloud_project: str = Field(default="", pattern=r"^[a-z0-9-]*$")
    google_cloud_location: str = Field(default="global", pattern=r"^[a-z0-9-]+$")
    vertex_model: str = Field(default="gemini-3.1-pro-preview", pattern=r"^[a-zA-Z0-9._-]+$")
    vertex_thinking_level: Literal["MINIMAL", "LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    vertex_voice_model: str = Field(default="gemini-3-flash-preview", pattern=r"^[a-zA-Z0-9._-]+$")
    vertex_voice_thinking_level: Literal["MINIMAL", "LOW", "MEDIUM", "HIGH"] = "MINIMAL"
    vertex_voice_retry_delay: float = Field(default=3.5, ge=1, le=15)

    def service_account_info(self):
        value = self.google_credentials_base64.get_secret_value()
        if not value:
            return None
        try:
            info = json.loads(base64.b64decode(value, validate=True))
            if (
                not isinstance(info, dict)
                or info.get("type") != "service_account"
                or info.get("token_uri") != "https://oauth2.googleapis.com/token"
                or info.get("universe_domain", "googleapis.com") != "googleapis.com"
                or not all(
                    isinstance(info.get(key), str) and info[key]
                    for key in ("project_id", "client_email", "private_key")
                )
            ):
                raise ValueError()
            return info
        except (ValueError, TypeError):
            raise ValueError(
                "GOOGLE_CREDENTIALS_BASE64 must contain a valid Google service account JSON."
            ) from None

    @property
    def vertex_project(self):
        info = self.service_account_info()
        return self.google_cloud_project or (info["project_id"] if info else "")

    def conversation_missing(self):
        if self.counselor_provider == "groq":
            return [] if self.groq_api_key else ["GROQ_API_KEY"]
        try:
            return [] if self.vertex_project else ["GOOGLE_CLOUD_PROJECT"]
        except ValueError:
            return ["GOOGLE_CREDENTIALS_BASE64"]

    def missing(self):
        names = (
            "livekit_url",
            "livekit_api_key",
            "livekit_api_secret",
            "rime_api_key",
            "deepgram_api_key",
            "worker_secret",
        )
        return [name.upper() for name in names if not getattr(self, name)] + self.conversation_missing()
