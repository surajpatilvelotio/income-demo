# Income Demo - FastAPI + Strands Agents Backend

A FastAPI backend service using Strands Agents SDK with Amazon Bedrock for the Deming Insurance Portal.

## Features

- 🚀 **FastAPI** with Python 3.13
- 🤖 **Strands Agents** for AI-powered conversations
- ☁️ **Amazon Bedrock** (Claude 3 Haiku by default)
- 💾 **Local Session Management** for multi-turn conversations
- 🔄 **SSE Streaming** for real-time responses
- 🛠️ **UV** for fast package management
- ✨ **Ruff** for linting and formatting
- 🔍 **Pyrefly** for type checking

## Project Structure

```
income-demo/
├── app/
│   ├── agent/          # Strands agent configuration
│   │   ├── factory.py  # Agent factory with session management
│   │   ├── llm.py      # BedrockModel configuration
│   │   └── prompts.py  # System prompts
│   ├── api/            # API endpoints
│   │   ├── routes.py   # Chat endpoints (/chat, /chat/stream)
│   │   └── schemas.py  # Pydantic models
│   ├── config.py       # Application settings
│   └── main.py         # FastAPI app entry point
├── Agents.md           # Agent documentation
├── pyproject.toml      # Dependencies and tool config
└── Makefile            # Development commands
```

## Quick Start

### Prerequisites

- Python 3.13+
- UV package manager
- AWS credentials with Bedrock access

### Installation

```bash
# Clone the repository
cd income-demo

# Install dependencies
make install
# or: uv sync
```

### Configuration

1. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

2. Configure your AWS credentials in `.env`:
```env
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
TEMPERATURE=0.7
SESSION_STORAGE_DIR=./sessions
```

### Running

```bash
# Start development server
make dev
# or: uv run uvicorn app.main:app --reload --port 8000
```

The API will be available at: http://localhost:8000

- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## API Endpoints

### POST /chat/

Non-streaming chat endpoint.

**Request:**
```json
{
  "message": "Hello, how can you help me?",
  "session_id": "user-123"
}
```

**Response:**
```json
{
  "response": "I'm here to assist you with insurance-related queries...",
  "session_id": "user-123"
}
```

### POST /chat/stream

Streaming chat endpoint using Server-Sent Events (SSE).

**Request:**
```json
{
  "message": "Explain term life insurance",
  "session_id": "user-123"
}
```

**Response:** Stream of SSE events with text chunks.

## Development

### Available Commands

```bash
# Install dependencies
make install

# Run development server (with hot reload)
make dev

# Format code
make fmt

# Lint code
make lint

# Type check
make typecheck
```

### Testing the API

Using curl:

```bash
# Health check
curl http://localhost:8000/health

# Chat (non-streaming)
curl -X POST http://localhost:8000/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "session_id": "test-123"}'

# Chat (streaming)
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me about insurance", "session_id": "test-123"}'
```

## Configuration

All configuration is managed via environment variables in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_REGION` | AWS region for Bedrock | `us-east-1` |
| `AWS_ACCESS_KEY_ID` | AWS access key | - |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | - |
| `MODEL_ID` | Bedrock model identifier | `anthropic.claude-3-haiku-20240307-v1:0` |
| `TEMPERATURE` | Model temperature (0.0-1.0) | `0.7` |
| `SESSION_STORAGE_DIR` | Directory for session storage | `./sessions` |

## Session Management

The system uses Strands' built-in `FileSessionManager` for local session persistence:

- Sessions are stored in `./sessions/` directory
- Each session maintains conversation history and agent state
- Sessions persist across application restarts
- Use unique `session_id` per user/conversation

## AWS Setup

### Bedrock Access

1. Ensure your AWS account has Bedrock enabled
2. Request access to Claude 3 Haiku model in the AWS Bedrock console
3. Configure IAM permissions for Bedrock access:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "*"
    }
  ]
}
```

## Extending

### Adding Custom Tools

See `Agents.md` for detailed instructions on adding custom tools to the agent.

### Changing Models

Update `MODEL_ID` in `.env` to use different models:
- **Haiku** (fast, economical): `anthropic.claude-3-haiku-20240307-v1:0`
- **Sonnet** (balanced): `anthropic.claude-3-5-sonnet-20241022-v2:0`
- **Opus** (most capable): `anthropic.claude-3-opus-20240229-v1:0`

## Documentation

- [Agents.md](./Agents.md) - Detailed agent documentation
- [Strands Agents Docs](https://strandsagents.com/latest/documentation/docs/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Amazon Bedrock](https://aws.amazon.com/bedrock/)

## License

[Add your license here]

