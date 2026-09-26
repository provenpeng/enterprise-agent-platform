from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.rag.embedding_space import embedding_space_id

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    database_url: str
    auth_public_key_path: Path = ROOT_DIR / "config" / "auth-public.pem"
    auth_issuer: str = "enterprise-agent-platform"
    auth_audience: str = "enterprise-agent-api"
    upload_dir: Path = ROOT_DIR / "data" / "uploads"
    max_upload_size_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    document_processing_backend: Literal["manual", "langchain"] = "manual"
    openai_api_key: SecretStr | None = None
    embedding_api_key: SecretStr | None = None
    embedding_api_base_url: AnyHttpUrl | None = None
    embedding_native_dimensions: int = Field(default=1536, ge=1, le=1536)
    embedding_revision: str = Field(default="default", min_length=1, max_length=100)
    chat_api_key: SecretStr | None = None
    chat_api_base_url: AnyHttpUrl | None = None
    chat_disable_thinking: bool = False
    chat_structured_output_method: Literal["json_schema", "json_mode"] = "json_schema"
    embedding_model: str = Field(
        default="text-embedding-3-small", min_length=1, max_length=100
    )
    index_target_tokens: int = Field(default=400, gt=0, le=8192)
    index_max_tokens: int = Field(default=600, gt=0, le=8192)
    index_max_chunks: int = Field(default=1000, gt=0)
    index_embed_batch_size: int = Field(default=32, gt=0, le=256)
    index_embedding_timeout_seconds: float = Field(default=60, gt=0)
    index_lease_seconds: int = Field(default=900, gt=0)
    index_max_attempts: int = Field(default=3, gt=0)
    index_poll_interval_seconds: float = Field(default=2.0, gt=0)
    retrieval_embedding_timeout_seconds: float = Field(default=15, gt=0, le=120)
    answer_model: str = "gpt-4o-mini"
    answer_generation_timeout_seconds: float = Field(default=30, gt=0, le=120)
    diagnostic_planning_timeout_seconds: float = Field(default=10, gt=0, le=60)
    model_max_inflight_requests: int = Field(default=8, ge=1, le=1024)
    model_admission_wait_seconds: float = Field(default=0.1, gt=0, le=30)

    @property
    def effective_chat_api_key(self) -> SecretStr | None:
        if self.chat_api_key and self.chat_api_key.get_secret_value():
            return self.chat_api_key
        return self.openai_api_key

    @property
    def effective_embedding_api_key(self) -> SecretStr | None:
        if self.embedding_api_key and self.embedding_api_key.get_secret_value():
            return self.embedding_api_key
        return self.openai_api_key

    @property
    def embedding_space_id(self) -> str:
        return embedding_space_id(
            model=self.embedding_model,
            base_url=str(self.embedding_api_base_url)
            if self.embedding_api_base_url
            else None,
            native_dimensions=self.embedding_native_dimensions,
            revision=self.embedding_revision,
        )

    @field_validator("chat_api_base_url", "embedding_api_base_url", mode="before")
    @classmethod
    def empty_chat_base_url_is_unset(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def validate_index_token_limits(self) -> "Settings":
        if self.index_target_tokens > self.index_max_tokens:
            raise ValueError("INDEX_TARGET_TOKENS must not exceed INDEX_MAX_TOKENS")
        if self.index_embedding_timeout_seconds + 30 >= self.index_lease_seconds:
            raise ValueError(
                "INDEX_EMBEDDING_TIMEOUT_SECONDS must be at least 30 seconds below INDEX_LEASE_SECONDS"
            )
        return self

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
