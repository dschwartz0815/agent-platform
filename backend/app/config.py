import uuid
from pydantic import field_validator
from pydantic_settings import BaseSettings

# Well-known IDs used only by the dev seed (DEBUG mode). Routers never
# reference these — identity comes from SSO headers (see security/identity.py).
DEV_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./agent_platform.db"
    anthropic_api_key: str = ""
    debug: bool = True
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # Identity / multi-tenancy
    #
    # The platform trusts identity headers injected by an SSO reverse proxy
    # (Azure AD App Proxy, ADFS WAP, oauth2-proxy, ...) that authenticates
    # users against Active Directory:
    #   X-Auth-User-Email — UPN / email (required)
    #   X-Auth-User-Name  — display name (optional, defaults to email)
    #   X-Auth-Groups     — AD group names, comma- or semicolon-separated
    #
    # Workspace membership is derived from the groups via tenant_group_mappings.
    # ------------------------------------------------------------------
    auth_user_header: str = "X-Auth-User-Email"
    auth_name_header: str = "X-Auth-User-Name"
    auth_groups_header: str = "X-Auth-Groups"
    # Header the frontend sends to select the active workspace
    workspace_header: str = "X-Workspace-Id"

    # When no identity headers are present (local dev without a proxy),
    # fall back to this identity instead of returning 401. MUST be disabled
    # in production. Groups match the dev seed's group mappings.
    auth_dev_fallback: bool = True
    dev_user_email: str = "dev@example.com"
    dev_user_name: str = "Dev User"
    dev_user_groups: list[str] = ["agent-platform-admins", "agent-platform-users"]

    @field_validator("dev_user_groups", mode="before")
    @classmethod
    def parse_dev_user_groups(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [g.strip() for g in v.replace(";", ",").split(",") if g.strip()]
        return v

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
