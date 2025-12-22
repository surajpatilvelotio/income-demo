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


settings = Settings()
