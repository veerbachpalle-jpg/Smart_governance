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
    STORAGE_BACKEND: str = Field(default="local")
    LOCAL_UPLOAD_DIR: str = Field(default="uploads")

    # JWT Security
    JWT_SECRET_KEY: str = Field(
        default="change_this_super_secret_key_in_production_min_32_bytes_3892718923"
    )
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7)

    @field_validator("JWT_ALGORITHM", mode="before")
    @classmethod
    def normalize_jwt_algorithm(cls, v: Any) -> str:
        if isinstance(v, str):
            cleaned = v.strip().strip("'\"").upper()
            if cleaned in {"HS256", "HS384", "HS512"}:
                return cleaned
        return "HS256"

    # AI Assist & Guardrails
    AI_ENABLED: bool = Field(default=True)

    # Provider selection: 'groq' (default) | 'gemini' | 'mock'
    # Switch providers by changing this value in your .env — no code changes needed.
    AI_PROVIDER: str = Field(default="groq")

    # --- Groq (Llama 3.3-70B on LPU cloud) ---
    GROQ_API_KEY: str | None = Field(default=None)
    GROQ_MODEL: str = Field(default="openai/gpt-oss-120b")

    # --- Google Gemini (kept as fallback) ---
    GEMINI_API_KEY: str | None = Field(default=None)
    # Keep defaults on currently supported stable Gemini endpoints. Deployments can
    # override these without changing code when a provider model is rotated.
    GEMINI_MODEL: str = Field(default="gemini-3.8-flash")
    GEMINI_EMBEDDING_MODEL: str = Field(default="gemini-embedding-2")
    AI_CONFIDENCE_THRESHOLD: float = Field(default=0.7)
    AI_TIMEOUT_SECONDS: float = Field(default=10.0)
    AI_CIRCUIT_BREAKER_FAILURES: int = Field(default=3)
    AI_CIRCUIT_BREAKER_RESET_SECONDS: float = Field(default=60.0)

    # External AI Complaint Management API (facebook/bart-large-mnli & all-MiniLM-L6-v2)
    EXTERNAL_ML_API_URL: str = Field(default="http://localhost:8000")
    EXTERNAL_ML_API_TIMEOUT: float = Field(default=35.0)
    EXTERNAL_ML_API_ENABLED: bool = Field(default=True)

    # WhatsApp Integration
    WHATSAPP_VERIFY_TOKEN: str = Field(default="smart_governance_wa_verify")
    WHATSAPP_ACCESS_TOKEN: str | None = Field(default=None)
    WHATSAPP_PHONE_NUMBER_ID: str | None = Field(default=None)

    # WhatsApp / Twilio Webhook Signature Verification
    WHATSAPP_APP_SECRET: str | None = Field(default=None)
    TWILIO_AUTH_TOKEN: str | None = Field(default=None)
    WHATSAPP_SIGNATURE_REQUIRED: bool = Field(default=True)

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

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, value: Any) -> str:
        """Render and similar hosts expose sync-style Postgres URLs."""
        url = str(value)
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        # asyncpg does not accept sslmode query parameter; convert to ssl
        if "sslmode=" in url:
            url = url.replace("sslmode=require", "ssl=require").replace(
                "sslmode=prefer", "ssl=prefer"
            ).replace("sslmode=disable", "ssl=disable")
        return url

    @field_validator("STORAGE_BACKEND")
    @classmethod
    def validate_storage_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "minio"}:
            raise ValueError("STORAGE_BACKEND must be either 'local' or 'minio'")
        return normalized

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
