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

    @model_validator(mode="after")
    def _validate_thresholds(self) -> "Settings":
        if self.storage_error_gb <= self.storage_warning_gb:
            raise ValueError(
                "storage_error_gb must be greater than storage_warning_gb "
                f"(got error={self.storage_error_gb}, warning={self.storage_warning_gb})"
            )
        return self


settings = Settings()
