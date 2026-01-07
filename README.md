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
# cp .env.example .env
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

### Authentication

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/signup` | POST | Register new user (returns JWT token + member_id) |
| `/auth/login` | POST | Login by member ID or email |
| `/auth/logout` | POST | Logout (invalidate session) |
| `/auth/me` | GET | Get current authenticated user |

### User Management (Admin)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/users/{user_id}` | GET | Get user details by ID |
| `/users/` | GET | List all users (paginated) |

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

### 1. User Registration (Signup)

```bash
curl --location 'http://127.0.0.1:8000/auth/signup' \
--header 'Content-Type: application/json' \
--data-raw '{
    "email": "<your_email>",
    "password": "<your_password>",
    "firstName": "<first_name>",
    "lastName": "<last_name>",
    "phone": "<phone_number>",
    "dateOfBirth": "<YYYY-MM-DD>"
  }'
```

**Response:** Returns user data with auto-generated `memberId` (e.g., `INS2025001`) and JWT token.

### 2. Login (by Member ID or Email)

```bash
# Login with Member ID
curl --location 'http://127.0.0.1:8000/auth/login' \
--header 'Content-Type: application/json' \
--data-raw '{
    "identifier": "<member_id>",
    "password": "<your_password>"
  }'

# Login with Email
curl --location 'http://127.0.0.1:8000/auth/login' \
--header 'Content-Type: application/json' \
--data-raw '{
    "identifier": "<your_email>",
    "password": "<your_password>"
  }'
```

### 3. Get Current User (Authenticated)

```bash
curl --location 'http://127.0.0.1:8000/auth/me' \
--header 'Authorization: Bearer <your_jwt_token>'
```

### 4. Check KYC Status (SSE Stream)

```bash
curl --location 'http://127.0.0.1:8000/kyc/status/<application_id>'
```

### 5. Start KYC via Chat (Form-data)

```bash
curl --location 'http://127.0.0.1:8000/kyc/chat/stream/upload' \
--form 'message="Start my KYC verification"' \
--form 'session_id="<session_id>"' \
--form 'user_id="<user_id>"'
```

### 6. Upload Document via Chat (Form-data)

```bash
curl --location 'http://127.0.0.1:8000/kyc/chat/stream/upload' \
--form 'message="Here is my ID document"' \
--form 'session_id="<session_id>"' \
--form 'documents=@"<path_to_document>"'
```

### 7. Confirm & Complete KYC

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
| `DATABASE_URL` | Database connection string | PostgreSQL |
| `USE_REAL_OCR` | Use real OCR vs mock | `true` |
| `JWT_SECRET_KEY` | Secret key for JWT tokens | (required) |
| `JWT_ALGORITHM` | JWT signing algorithm | `HS256` |
| `JWT_EXPIRE_MINUTES` | Token expiration time | `10080` (7 days) |

---

## Documentation

- [Agents.md](./Agents.md) - Agent architecture and tools
- [USER_WORKFLOW.md](./USER_WORKFLOW.md) - Complete KYC workflow guide
