from typing import Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/grievance_db"
    )

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # MinIO
    MINIO_ENDPOINT: str = Field(default="localhost:9000")
    MINIO_ROOT_USER: str = Field(default="minioadmin")
    MINIO_ROOT_PASSWORD: str = Field(default="minioadmin")
    MINIO_BUCKET: str = Field(default="complaints-attachments")
    MINIO_SECURE: bool = Field(default=False)

    # JWT Security
    JWT_SECRET_KEY: str = Field(
        default="change_this_super_secret_key_in_production_min_32_bytes_3892718923"
    )
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)

    # AI Assist & Guardrails
    AI_ENABLED: bool = Field(default=True)
    GEMINI_API_KEY: str | None = Field(default=None)
    GEMINI_MODEL: str = Field(default="gemini-1.5-flash")
    GEMINI_EMBEDDING_MODEL: str = Field(default="text-embedding-004")
    AI_CONFIDENCE_THRESHOLD: float = Field(default=0.7)
    AI_TIMEOUT_SECONDS: float = Field(default=10.0)
    AI_CIRCUIT_BREAKER_FAILURES: int = Field(default=3)
    AI_CIRCUIT_BREAKER_RESET_SECONDS: float = Field(default=60.0)

    # Security: CORS & Rate Limiting
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://localhost:8000"
    )
    RATE_LIMIT_ENABLED: bool = Field(default=True)
    MAX_UPLOAD_SIZE_MB: int = Field(default=15)

    @field_validator("MAX_UPLOAD_SIZE_MB", mode="before")
    @classmethod
    def parse_max_upload_size(cls, v: Any) -> int:
        if isinstance(v, str):
            cleaned = v.upper().replace("MB", "").replace("M", "").strip()
            return int(cleaned)
        return int(v)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
