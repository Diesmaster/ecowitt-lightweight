"""App-wide settings, loaded from environment variables (or a .env file).

Add new config here rather than scattering `os.environ.get(...)` calls
through the codebase - one place to see every env var this app reads,
with types and defaults enforced by pydantic.
"""

from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    data_dir: str = "data"

    # Storage checker thresholds, in GB (see app/services/storage_checker_service.py).
    storage_warning_gb: float = 5.0
    storage_error_gb: float = 8.0

    # Origins allowed to call this API from a browser (e.g. the admin
    # React app). Comma-separated in the env var, e.g.
    # CORS_ORIGINS="http://localhost:5173,https://admin.example.com"
    # Defaults cover Vite's default dev ports so local dev works out of
    # the box; add your real deployed admin URL here for production.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @model_validator(mode="before")
    @classmethod
    def _split_cors_origins(cls, values: dict) -> dict:
        raw = values.get("cors_origins")
        if isinstance(raw, str):
            values["cors_origins"] = [origin.strip() for origin in raw.split(",") if origin.strip()]
        return values

    @model_validator(mode="after")
    def _validate_thresholds(self) -> "Settings":
        if self.storage_error_gb <= self.storage_warning_gb:
            raise ValueError(
                "storage_error_gb must be greater than storage_warning_gb "
                f"(got error={self.storage_error_gb}, warning={self.storage_warning_gb})"
            )
        return self


settings = Settings()
