from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    database_url: str
    upload_dir: Path = ROOT_DIR / "data" / "uploads"
    max_upload_size_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    document_processing_backend: Literal["manual", "langchain"] = "manual"
    openai_api_key: SecretStr | None = None
    embedding_model: Literal["text-embedding-3-small"] = "text-embedding-3-small"
    index_target_tokens: int = Field(default=400, gt=0, le=8192)
    index_max_tokens: int = Field(default=600, gt=0, le=8192)
    index_max_chunks: int = Field(default=1000, gt=0)
    index_embed_batch_size: int = Field(default=32, gt=0, le=256)
    index_lease_seconds: int = Field(default=900, gt=0)
    index_max_attempts: int = Field(default=3, gt=0)
    index_poll_interval_seconds: float = Field(default=2.0, gt=0)

    @model_validator(mode="after")
    def validate_index_token_limits(self) -> "Settings":
        if self.index_target_tokens > self.index_max_tokens:
            raise ValueError("INDEX_TARGET_TOKENS must not exceed INDEX_MAX_TOKENS")
        return self

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
