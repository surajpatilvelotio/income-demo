"""LLM configuration for Amazon Bedrock."""

from strands.models import BedrockModel

from app.config import settings


def get_bedrock_model() -> BedrockModel:
    """
    Create and return a BedrockModel instance configured with application settings.

    Returns:
        BedrockModel: Configured Bedrock model instance
    """
    return BedrockModel(
        model_id=settings.model_id,
        region_name=settings.aws_region,
        temperature=settings.temperature,
    )
