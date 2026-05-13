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
    s3_region: str = Field("us-east-1")
    enable_object_store: bool = Field(False)
    enable_async_kb_ingest: bool = Field(False)
    enable_webhook_worker: bool = Field(False)
    enable_post_call_analysis: bool = Field(False)
    analysis_model: str = Field("gemini/gemini-3.1-flash-lite")

    google_oauth_client_id: str = Field("")
    google_oauth_client_secret: str = Field("")
    google_oauth_redirect_uri: str = Field("http://localhost:8000/v1/auth/callback/google")
    session_cookie_name: str = Field("voice_session")
    session_ttl_seconds: int = Field(60 * 60 * 24 * 14)  # 14 days
    web_app_base_url: str = Field("http://localhost:5173")

    telnyx_api_key: str = Field("")
    telnyx_webhook_public_key: str = Field("")
    telnyx_connection_id: str = Field("")

    deepgram_api_key: str = Field("")
    elevenlabs_api_key: str = Field("")
    gemini_api_key: str = Field("")

    webhook_hmac_secret: str = Field("dev-hmac-secret-rotate-in-prod")
    api_key_pepper: str = Field("dev-pepper-rotate-in-prod")

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:5175",
            "http://localhost:5176",
            "http://localhost:5179",
        ]
    )

    # Public URL that Telnyx + other webhooks can reach (override in prod).
    public_base_url: str = Field("http://localhost:8000")
    # wss:// counterpart used as the Telnyx media stream URL.
    public_ws_base_url: str = Field("ws://localhost:8000")


@lru_cache
def get_settings() -> Settings:
    return Settings()
