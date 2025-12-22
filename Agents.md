# Agent Instructions

This document provides guidelines and instructions for developing and managing agents within the Income Demo - Deming Insurance Portal backend service.

## Overview

The Income Demo uses the Strands Agents SDK to provide AI-powered conversational capabilities through Amazon Bedrock's Claude models. The system is designed to be simple, extensible, and production-ready.

## Architecture

### Agent Factory (`app/agent/factory.py`)

The `create_agent()` function is the central factory for creating Strands agent instances. It handles:

- **Session Management**: Uses `FileSessionManager` for local persistence of conversation history and agent state
- **Model Configuration**: Configures the BedrockModel with settings from environment variables
- **System Prompts**: Applies the system prompt to guide agent behavior

**Usage:**
```python
from app.agent import create_agent

agent = create_agent(session_id="user-123")
response = agent("Hello, how can you help me?")
```

### LLM Configuration (`app/agent/llm.py`)

The `get_bedrock_model()` function returns a configured BedrockModel instance:

- **Default Model**: Claude 3 Haiku (fast and cost-effective)
- **Configuration**: Temperature, region, and model ID are configurable via environment variables
- **AWS Credentials**: Uses standard AWS credential chain (environment variables, ~/.aws/credentials, IAM roles)

### System Prompts (`app/agent/prompts.py`)

System prompts define the agent's behavior and personality:

- **Current Prompt**: Generic helpful assistant for insurance queries
- **Customization**: Modify `SYSTEM_PROMPT` to change agent behavior
- **Best Practices**:
  - Be clear about the agent's role and capabilities
  - Include guidelines for handling edge cases
  - Specify tone and style expectations

## Session Management

Sessions are managed locally using Strands' built-in `FileSessionManager`:

- **Storage Location**: `./sessions/` (configurable via `SESSION_STORAGE_DIR`)
- **Session ID**: Unique identifier per user/conversation
- **Persistence**: Conversation history and agent state are automatically saved
- **Multi-turn**: Supports multi-turn conversations with context retention

**Session Structure:**
```
sessions/
└── session_<session_id>/
    ├── session.json
    └── agents/
        └── agent_<agent_id>/
            ├── agent.json
            └── messages/
```

## API Endpoints

### POST /chat/

Non-streaming chat endpoint for simple request/response interactions.

**Request:**
```json
{
  "message": "What insurance options are available?",
  "session_id": "user-123"
}
```

**Response:**
```json
{
  "response": "We offer various insurance options...",
  "session_id": "user-123"
}
```

### POST /chat/stream

Streaming chat endpoint using Server-Sent Events (SSE) for real-time responses.

**Request:**
```json
{
  "message": "Explain the benefits of term life insurance",
  "session_id": "user-123"
}
```

**Response:** Stream of SSE events with incremental text chunks.

## Configuration

All configuration is managed through environment variables (see `.env.example`):

- `AWS_REGION`: AWS region for Bedrock (default: us-east-1)
- `AWS_ACCESS_KEY_ID`: AWS access key
- `AWS_SECRET_ACCESS_KEY`: AWS secret key
- `MODEL_ID`: Bedrock model identifier (default: Claude 3 Haiku)
- `TEMPERATURE`: Model temperature for response randomness (0.0-1.0)
- `SESSION_STORAGE_DIR`: Directory for session storage

## Development

### Running Locally

```bash
# Install dependencies
make install

# Run development server
make dev

# Format code
make fmt

# Lint code
make lint

# Type check
make typecheck
```

### Adding Tools

To add custom tools for the agent:

1. Create a tool function in a new file under `app/agent/tools/`
2. Decorate with `@tool` from Strands
3. Import and pass to the agent in `factory.py`

**Example:**
```python
from strands import tool

@tool
def calculate_premium(age: int, coverage: int) -> dict:
    """Calculate insurance premium based on age and coverage."""
    # Implementation here
    return {"premium": calculated_amount}
```

### Extending the Agent

To customize agent behavior:

1. **Modify System Prompt**: Edit `app/agent/prompts.py`
2. **Add Tools**: Create tools in `app/agent/tools/`
3. **Adjust Model Settings**: Update `.env` file
4. **Custom Logic**: Extend `factory.py` for advanced configurations

## Best Practices

1. **Session Management**: Always use unique session IDs per user/conversation
2. **Error Handling**: The agent handles most errors gracefully, but validate input in routes
3. **Streaming**: Use `/chat/stream` for better user experience in chat interfaces
4. **Model Selection**: Claude Haiku is fast and affordable; upgrade to Sonnet for more complex tasks
5. **Security**: Never commit `.env` files; use appropriate AWS IAM permissions
6. **Testing**: Test with various session IDs to ensure proper isolation

## Troubleshooting

### Agent Not Responding

- Check AWS credentials are configured correctly
- Verify Bedrock model access is enabled in AWS console
- Check logs for authentication errors

### Session Issues

- Ensure `sessions/` directory exists and is writable
- Check session_id is being passed correctly
- Verify `SESSION_STORAGE_DIR` path is valid

### Import Errors

- Run `uv sync` to ensure all dependencies are installed
- Check Python version is 3.13+

## Future Enhancements

Areas for future development:

- **eKYC Tools**: Add specific tools for identity verification
- **Document Processing**: Integrate document analysis capabilities
- **Multi-Agent**: Implement specialized agents for different insurance domains
- **Analytics**: Add logging and metrics for agent performance
- **Security**: Implement PII redaction and guardrails

## Resources

- [Strands Agents Documentation](https://strandsagents.com/latest/documentation/docs/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Amazon Bedrock](https://aws.amazon.com/bedrock/)

