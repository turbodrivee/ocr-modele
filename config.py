from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENV: Literal["dev", "staging", "prod"] = "dev"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    INTERNAL_SECRET: str = ""
    INTERNAL_SECRET_PREVIOUS: str = ""

    # Legacy header accepted during rollout — remove after one release.
    LEGACY_API_KEY: str = ""

    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024  # 10 MB

    RATE_LIMIT_PER_MINUTE: int = 30

    OCR_USE_ORIENTATION_DETECTION: bool = True

    SUPPORTED_DOC_TYPES: frozenset[str] = Field(
        default=frozenset({"permis", "cin", "carte_grise", "assurance"})
    )
    SUPPORTED_CONTENT_TYPES: frozenset[str] = Field(
        default=frozenset({"image/jpeg", "image/png", "image/webp"})
    )

    def validate_runtime(self) -> None:
        if self.ENV != "dev" and not self.INTERNAL_SECRET:
            raise RuntimeError("INTERNAL_SECRET is required outside dev environment")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.validate_runtime()
    return s
