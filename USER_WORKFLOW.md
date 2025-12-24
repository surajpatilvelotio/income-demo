# User Workflow: Registration to KYC Completion

This document describes the complete user journey from account registration to KYC (Know Your Customer) verification completion.

---

## Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Registration  │ ──▶│  KYC Initiation │ ──▶ │ Document Upload │ ──▶│  OCR Extraction │
│                 │     │                 │     │                 │     │                 │
│  /users/signup  │     │  /kyc/initiate  │     │  /kyc/documents │     │   (automatic)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
                                                                               │
                                                                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                            SEQUENTIAL VERIFICATION WORKFLOW                             │
├─────────────────┬─────────────────┬─────────────────┬─────────────────┬─────────────────┤
│  User Review    │  Gov DB Check   │  Fraud Check    │  Final Decision │   Result        │
│                 │                 │                 │                 │                 │
│ (confirm data)  │ (automatic)     │ (only if gov ✓) │ (automatic)     │ ✅ or ❌       │
└─────────────────┴─────────────────┴─────────────────┴─────────────────┴─────────────────┘
                        │                                                      
                        ▼ If Gov DB fails                                     
              ┌─────────────────────┐                                          
              │  ⚠️ MANUAL REVIEW   │                                          
              │  (Process stops)    │                                          
              └─────────────────────┘                                          
```

### Key Workflow Rules:
1. **OCR extracts data** from documents
2. **User reviews and confirms** the extracted data
3. **Government DB verification** runs first
4. **If Gov verification FAILS** → Process STOPS → Manual review required
5. **If Gov verification PASSES** → Fraud detection runs
6. **Final decision** based on all checks

---

## Recommended Approach

| Use Case | Endpoints | Description |
|----------|-----------|-------------|
| **Streaming Chat (Recommended)** | `/users/signup` → `/kyc/chat/stream/upload` | Real-time SSE, direct file upload, agent-guided |
| **REST APIs only** | `/users/signup` → `/kyc/initiate` → `/kyc/documents` → `/kyc/process` | Direct API calls, predictable responses |

---

## Flow 1: Streaming Chat with File Upload (Recommended)

Registration via REST, everything else through streaming chat with real-time SSE events.

```
┌─────────────────┐     ┌──────────────────────────────────────────────────────────────┐
│   Registration  │     │           /kyc/chat/stream/upload (SSE Stream)               │
│                 │     │                                                              │
│  /users/signup  │ ──▶ │  Start KYC → Upload Docs → OCR → Confirm → Verify → Result  │
│                 │     │                                                              │
└─────────────────┘     └──────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
                        ┌──────────────────────────────────────────────────────────────┐
                        │           /kyc/status/{application_id} (SSE Stream)          │
                        │                                                              │
                        │  Real-time stage updates: ocr → gov_verification → decision  │
                        └──────────────────────────────────────────────────────────────┘
```

### Step 1: Register User

```bash
curl --location 'http://127.0.0.1:8000/users/signup' \
--header 'Content-Type: application/json' \
--data-raw '{
    "email": "<your_email>",
    "phone": "<your_phone>",
    "password": "<your_password>"
  }'
```

### Step 2: Start KYC

```bash
curl --location 'http://127.0.0.1:8000/kyc/chat/stream/upload' \
--form 'message="Start my KYC verification"' \
--form 'session_id="<session_id>"' \
--form 'user_id="<user_id>"'
```

### Step 3: Upload Document

```bash
curl --location 'http://127.0.0.1:8000/kyc/chat/stream/upload' \
--form 'message="Here is my ID document"' \
--form 'session_id="<session_id>"' \
--form 'documents=@"<path_to_document>"'
```

### Step 4: Confirm & Verify

```bash
curl --location 'http://127.0.0.1:8000/kyc/chat/stream/upload' \
--form 'message="Yes the data is correct. Please verify and complete my KYC."' \
--form 'session_id="<session_id>"'
```

### Step 5: Monitor Status (Optional)

```bash
curl --location 'http://127.0.0.1:8000/kyc/status/<application_id>'
```

---

## Flow 2: REST API Only

For direct API integration without conversational UI.

### Step 1: Register User

```bash
curl -X POST http://127.0.0.1:8000/users/signup \
  -H "Content-Type: application/json" \
  -d '{"email": "<email>", "phone": "<phone>", "password": "<password>"}'
```

### Step 2: Initiate KYC

```bash
curl -X POST http://127.0.0.1:8000/kyc/initiate \
  -H "Content-Type: application/json" \
  -d '{"user_id": "<user_id>"}'
```

### Step 3: Upload Document

```bash
curl -X POST http://127.0.0.1:8000/kyc/documents \
  -F "application_id=<application_id>" \
  -F "document_type=id_card" \
  -F "file=@<path_to_document>"
```

### Step 4: Trigger Processing

```bash
curl -X POST http://127.0.0.1:8000/kyc/process/<application_id>
```

### Step 5: Monitor Status

```bash
curl -N http://127.0.0.1:8000/kyc/status/<application_id>
```

### Step 6: Get Final Result

```bash
curl http://127.0.0.1:8000/kyc/application/<application_id>
```

---

## API Endpoints Reference

### User Management
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/users/signup` | POST | Create user account |
| `/users/{user_id}` | GET | Get user details |

### KYC REST API
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/kyc/initiate` | POST | Start KYC application |
| `/kyc/documents` | POST | Upload document (multipart) |
| `/kyc/process/{application_id}` | POST | Trigger verification |
| `/kyc/status/{application_id}` | GET | Stream status updates (SSE) |
| `/kyc/application/{application_id}` | GET | Get application details |
| `/kyc/applications/{user_id}` | GET | List user's applications |

### KYC Chat API
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/kyc/chat` | POST | Conversational KYC (JSON, base64 uploads) |
| `/kyc/chat/stream` | POST | Streaming chat (JSON + SSE) |
| `/kyc/chat/stream/upload` | POST | Streaming chat with file upload (Form-data + SSE) |

---

## SSE Events Reference

| Event | Endpoint | Description |
|-------|----------|-------------|
| `session` | `/kyc/chat/stream/upload` | Session ID confirmation |
| `document_uploaded` | `/kyc/chat/stream/upload` | File upload status |
| `text` | `/kyc/chat/stream/upload` | Agent response chunks |
| `tool_call` | `/kyc/chat/stream/upload` | Tool invocation |
| `tool_result` | `/kyc/chat/stream/upload` | Tool execution result |
| `kyc_progress` | `/kyc/chat/stream/upload` | Final stages summary |
| `stop` | `/kyc/chat/stream/upload` | Stream end |
| `init` | `/kyc/status/{id}` | Initial application state |
| `stage_update` | `/kyc/status/{id}` | Stage progress update |

---

## Status Reference

### User KYC Status
| Status | Description |
|--------|-------------|
| `pending` | User registered, KYC not started |
| `in_progress` | KYC application active |
| `approved` | Identity verified |
| `rejected` | Verification failed |

### Application Status
| Status | Description |
|--------|-------------|
| `initiated` | Application created |
| `documents_uploaded` | Documents received |
| `processing` | Verification running |
| `completed` | Verified & approved |
| `failed` | Verified & rejected |

### Processing Stages
| Stage | Description |
|-------|-------------|
| `ocr_processing` | Text extraction |
| `user_review` | User confirms data |
| `gov_verification` | Government check |
| `fraud_check` | Fraud analysis |
| `decision` | Final decision |

---

## Error Responses

| Status Code | Error | Cause |
|-------------|-------|-------|
| 400 | "Email already registered" | Duplicate email |
| 400 | "User already has an active KYC application" | Pending KYC exists |
| 404 | "User not found" | Invalid user_id |
| 404 | "Application not found" | Invalid application_id |
| 400 | "No documents uploaded" | Process without documents |
