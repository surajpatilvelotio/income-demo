# Agent Instructions

This document provides guidelines for developing and managing agents within the eKYC backend service.

## Overview

The system uses the Strands Agents SDK to provide AI-powered conversational capabilities through Amazon Bedrock's Claude models.

## Architecture

### Agent Factory (`app/agent/factory.py`)

The `create_agent()` function is the central factory for creating Strands agent instances:

- **Session Management**: Uses `FileSessionManager` for local persistence of conversation history and agent state
- **Model Configuration**: Configures the BedrockModel with settings from environment variables
- **System Prompts**: Applies the system prompt to guide agent behavior
- **State Persistence**: Uses custom `SessionStateStore` for persisting agent state across calls

**Usage:**
```python
from app.agent import create_agent

agent = create_agent(session_id="user-123", include_kyc_tools=True)
response = agent("Start my KYC verification")
```

### LLM Configuration (`app/agent/llm.py`)

The `get_bedrock_model()` function returns a configured BedrockModel instance:

- **Default Model**: Claude 3 Haiku (fast and cost-effective)
- **Configuration**: Temperature, region, and model ID are configurable via environment variables
- **AWS Credentials**: Uses standard AWS credential chain (environment variables, ~/.aws/credentials, IAM roles)

### System Prompts (`app/agent/prompts.py`)

System prompts define the agent's behavior and personality:

- **KYC Agent Prompt**: Guides users through identity verification
- **Customization**: Modify `SYSTEM_PROMPT` to change agent behavior
- **Best Practices**:
  - Be clear about the agent's role and capabilities
  - Include guidelines for handling edge cases
  - Specify tone and style expectations

### OCR Agent (`app/agent/ocr_agent.py`)

Specialized agent for document text extraction using Claude's vision capabilities:

- Uses Bedrock's `invoke_model` API for image processing
- Extracts structured identity data from ID cards and passports
- Supports mock mode for testing (`USE_REAL_OCR` config)

### KYC Workflow (`app/agent/kyc_workflow.py`)

Orchestrates the KYC verification process:

1. **OCR Step**: Extract data from documents (parallel processing)
2. **User Review**: Present extracted data for confirmation
3. **Government Verification**: Check against mock government database
4. **Fraud Detection**: Run fraud indicators check
5. **Decision**: Approve, reject, or flag for manual review

## Session & State Management

### Session Storage
Sessions are managed using Strands' `FileSessionManager`:

```
sessions/
└── session_<session_id>/
    ├── session.json
    └── agents/
        └── agent_<agent_id>/
            ├── agent.json
            └── messages/
```

### State Persistence (`app/agent/state_store.py`)
Custom state store for persisting agent state (user_id, application_id, workflow_stage):

```
sessions/state/
└── <session_id>.json
```

## Agent Tools

Tools are defined in `app/agent/tools/`:

| Tool | Purpose |
|------|---------|
| `register_user` | Create new user account |
| `find_user_by_email` | Look up user by email |
| `initiate_kyc_process` | Start KYC application |
| `upload_kyc_document` | Upload document via chat |
| `get_uploaded_documents` | List uploaded documents |
| `run_ocr_extraction` | Extract data from documents |
| `confirm_and_verify` | Run full verification workflow |
| `get_kyc_status` | Get application status |
| `update_kyc_stage` | Track processing stages |
| `verify_with_government` | Government DB check |
| `check_fraud_indicators` | Fraud detection |
| `make_kyc_decision` | Final approval/rejection |

### Adding New Tools

1. Create a tool function in `app/agent/tools/`
2. Decorate with `@tool` from Strands
3. Import and add to `ALL_TOOLS` in `__init__.py`

**Example:**
```python
from strands import tool

@tool
def my_custom_tool(param1: str, param2: int) -> dict:
    """Tool description for the LLM."""
    # Implementation
    return {"success": True, "result": "..."}
```

## Configuration

Environment variables (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_REGION` | AWS region for Bedrock | `us-east-1` |
| `MODEL_ID` | Bedrock model identifier | Claude 3 Haiku |
| `TEMPERATURE` | Model temperature (0.0-1.0) | `0.7` |
| `SESSION_STORAGE_DIR` | Session storage directory | `./sessions` |
| `USE_REAL_OCR` | Use real OCR vs mock | `true` |

## Best Practices

1. **Session Management**: Always use unique session IDs per user/conversation
2. **State Persistence**: Use `ToolContext` to store/retrieve state within tools
3. **Timeouts**: Long operations (OCR, verification) use 120s timeout
4. **Error Handling**: Tools return `{"success": False, "error": "..."}` on failure
5. **Streaming**: Use `/kyc/chat/stream/upload` for real-time responses

## Troubleshooting

### Agent Not Responding
- Check AWS credentials are configured correctly
- Verify Bedrock model access is enabled in AWS console
- Check logs for authentication errors

### OCR Timeout
- OCR can take 60+ seconds for complex documents
- Timeout is set to 120 seconds
- Check network connectivity to AWS Bedrock

### State Not Persisting
- Verify `sessions/state/` directory exists and is writable
- Check session_id is consistent across calls

## Resources

- [Strands Agents Documentation](https://strandsagents.com/latest/documentation/docs/)
- [Amazon Bedrock](https://aws.amazon.com/bedrock/)
