from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_LLM_MODEL = "openai/gpt-oss-120b"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_mode: str = "fixture"
    demo_enabled: bool = True
    database_path: str = "data/pickmate.sqlite"
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
    rime_model: str = "coda"
    rime_speaker: str = "astra"
    rime_language: str = "en"
    rime_sample_rate: int = 24000
    rime_base_url: str = "wss://users-ws.rime.ai"

    def missing(self):
        names = (
            "livekit_url",
            "livekit_api_key",
            "livekit_api_secret",
            "rime_api_key",
            "deepgram_api_key",
            "groq_api_key",
            "worker_secret",
        )
        return [name.upper() for name in names if not getattr(self, name)]
