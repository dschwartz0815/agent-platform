import uuid
from pydantic import field_validator
from pydantic_settings import BaseSettings

# Hardcoded dev identity — swap for real auth later.
# All tables carry user_id / org_id so no migration is needed when auth lands.
DEV_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./agent_platform.db"
    anthropic_api_key: str = ""
    debug: bool = True
    log_level: str = "INFO"

    # CORS: comma-separated list of allowed origins.
    # In production, set this to your actual frontend origin(s).
    # Default is local dev only — never wildcard.
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Accept either a list or a comma-separated env string."""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    model_config = {"env_file": ".env"}


settings = Settings()
