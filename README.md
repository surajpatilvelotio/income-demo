# eKYC Backend - FastAPI + Strands Agents

A FastAPI backend service for eKYC (electronic Know Your Customer) verification using Strands Agents SDK with Amazon Bedrock.

## Features

- 🚀 **FastAPI** with Python 3.13
- 🤖 **Strands Agents** for AI-powered KYC conversations
- 👁️ **OCR** with Claude Vision for document extraction
- ☁️ **Amazon Bedrock** (Claude 3 Haiku)
- 💾 **Session Management** for multi-turn conversations
- 🔄 **SSE Streaming** for real-time responses
- 🐳 **Docker** support with PostgreSQL

## Quick Start

### Prerequisites

- Python 3.13+ / Docker
- AWS credentials with Bedrock access

### Installation

```bash
# Install dependencies
make install
# or: uv sync

# Copy environment file
cp .env.example .env
# Configure AWS credentials in .env
```

### Running

```bash
# Local development
make dev

# Docker
docker-compose up --build
```

API available at: http://localhost:8000/docs

---

## API Endpoints

### User Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/users/signup` | POST | Register new user |
| `/users/{user_id}` | GET | Get user details |

### KYC Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/kyc/initiate` | POST | Start KYC application |
| `/kyc/documents` | POST | Upload document (multipart) |
| `/kyc/process/{application_id}` | POST | Trigger verification |
| `/kyc/status/{application_id}` | GET | Stream status updates (SSE) |
| `/kyc/application/{application_id}` | GET | Get application details |
| `/kyc/applications/{user_id}` | GET | List user's applications |
| `/kyc/chat` | POST | Conversational KYC (JSON) |
| `/kyc/chat/stream` | POST | Streaming KYC chat (JSON + SSE) |
| `/kyc/chat/stream/upload` | POST | Streaming KYC with file upload (Form-data + SSE) |

---

## Curl Examples

### 1. User Registration

```bash
curl --location 'http://127.0.0.1:8000/users/signup' \
--header 'Content-Type: application/json' \
--data-raw '{
    "email": "<your_email>",
    "phone": "<your_phone>",
    "password": "<your_password>"
  }'
```

### 2. Check KYC Status (SSE Stream)

```bash
curl --location 'http://127.0.0.1:8000/kyc/status/<application_id>'
```

### 3. Start KYC via Chat (Form-data)

```bash
curl --location 'http://127.0.0.1:8000/kyc/chat/stream/upload' \
--form 'message="Start my KYC verification"' \
--form 'session_id="<session_id>"' \
--form 'user_id="<user_id>"'
```

### 4. Upload Document via Chat (Form-data)

```bash
curl --location 'http://127.0.0.1:8000/kyc/chat/stream/upload' \
--form 'message="Here is my ID document"' \
--form 'session_id="<session_id>"' \
--form 'documents=@"<path_to_document>"'
```

### 5. Confirm & Complete KYC

```bash
curl --location 'http://127.0.0.1:8000/kyc/chat/stream/upload' \
--form 'message="Yes the data is correct. Please verify and complete my KYC."' \
--form 'session_id="<session_id>"'
```

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_REGION` | AWS region for Bedrock | `us-east-1` |
| `AWS_ACCESS_KEY_ID` | AWS access key | - |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key | - |
| `MODEL_ID` | Bedrock model identifier | Claude 3 Haiku |
| `DATABASE_URL` | Database connection string | SQLite |
| `USE_REAL_OCR` | Use real OCR vs mock | `true` |

---

## Documentation

- [Agents.md](./Agents.md) - Agent architecture and tools
- [USER_WORKFLOW.md](./USER_WORKFLOW.md) - Complete KYC workflow guide
