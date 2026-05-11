from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="VOICE_", extra="ignore")

    env: str = Field("dev")
    log_level: str = Field("INFO")

    database_url: str = Field("postgresql+asyncpg://voice:voice@localhost:5432/voice")
    redis_url: str = Field("redis://localhost:6379/0")

    s3_endpoint: str = Field("http://localhost:9000")
    s3_access_key: str = Field("voice")
    s3_secret_key: str = Field("voicevoice")
    s3_bucket_recordings: str = Field("voice-recordings")
    s3_bucket_kb: str = Field("voice-kb")

    livekit_url: str = Field("ws://localhost:7880")
    livekit_api_key: str = Field("devkey")
    livekit_api_secret: str = Field("devsecret-32-chars-min-for-livekit-jwt")

    telnyx_api_key: str = Field("")
    telnyx_webhook_public_key: str = Field("")
    telnyx_connection_id: str = Field("")

    deepgram_api_key: str = Field("")
    elevenlabs_api_key: str = Field("")
    gemini_api_key: str = Field("")

    webhook_hmac_secret: str = Field("dev-hmac-secret-rotate-in-prod")
    api_key_pepper: str = Field("dev-pepper-rotate-in-prod")

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:5174"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
