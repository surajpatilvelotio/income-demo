"""Application configuration using Pydantic settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # AWS / Bedrock
    aws_region: str = "us-east-1"
    model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    temperature: float = 0.7

    # Session
    session_storage_dir: str = "./sessions"

    # Database
    database_url: str = "sqlite+aiosqlite:///./ekyc.db"
    database_echo: bool = False

    # File uploads
    upload_dir: str = "./uploads"
    max_upload_size: int = 10 * 1024 * 1024  # 10MB

    # OCR Configuration
    # Set to True to use real vision-based OCR (Bedrock Claude)
    # Set to False to use mock OCR data (for testing without API calls)
    use_real_ocr: bool = True


settings = Settings()
