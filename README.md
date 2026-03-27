# AI Learning Journal API (FastAPI Practice Project)

## Project Goal

Build a small but practical backend using **FastAPI** that allows users to record learning logs and use AI to analyze, summarize, and improve those logs.

This project is designed to help learn the core backend concepts of FastAPI such as:

- API design
- Request validation
- Dependency injection
- Background tasks
- File upload
- WebSockets
- AI API integration
- Authentication
- Database interaction

The AI component is used to analyze learning logs and generate insights.

---

# Core Entities

## User

Represents a registered user.

Fields:

- id
- name
- email
- password_hash
- created_at

---

## Learning Log

Represents a learning entry written by a user.

Fields:

- id
- user_id
- title
- content
- tags
- created_at

---

## AI Analysis

Stores AI generated results for a log.

Fields:

- id
- log_id
- summary
- key_points
- suggested_tags
- learning_score
- created_at

---

# API Endpoints

---

# 1. Authentication APIs

## Register User

POST
`/auth/register`

Request

```json
{
  "name": "Arif",
  "email": "arif@email.com",
  "password": "securepassword"
}
```

Response

```json
{
  "message": "User created successfully",
  "user_id": 1
}
```

---

## Login

POST
`/auth/login`

Request

```json
{
  "email": "arif@email.com",
  "password": "securepassword"
}
```

Response

```json
{
  "access_token": "jwt_token_here",
  "token_type": "bearer"
}
```

---

## Get Current User

GET
`/auth/me`

Headers

```
Authorization: Bearer <token>
```

Response

```json
{
  "id": 1,
  "name": "Arif",
  "email": "arif@email.com"
}
```

---

# 2. Learning Log APIs

## Create Learning Log

POST
`/logs`

Request

```json
{
  "title": "Learning FastAPI",
  "content": "Today I learned about async endpoints and dependency injection",
  "tags": ["fastapi", "backend"]
}
```

Response

```json
{
  "id": 1,
  "title": "Learning FastAPI",
  "content": "Today I learned about async endpoints and dependency injection",
  "tags": ["fastapi", "backend"],
  "created_at": "2026-03-14T10:30:00"
}
```

---

## Get All Logs

GET
`/logs`

Response

```json
[
  {
    "id": 1,
    "title": "Learning FastAPI",
    "tags": ["fastapi", "backend"],
    "created_at": "2026-03-14T10:30:00"
  }
]
```

---

## Get Single Log

GET
`/logs/{log_id}`

Response

```json
{
  "id": 1,
  "title": "Learning FastAPI",
  "content": "Today I learned about async endpoints and dependency injection",
  "tags": ["fastapi", "backend"],
  "created_at": "2026-03-14T10:30:00"
}
```

---

## Delete Log

DELETE
`/logs/{log_id}`

Response

```json
{
  "message": "Log deleted successfully"
}
```

---

# 3. AI Processing APIs

These endpoints integrate AI into the system.

---

## Trigger AI Analysis (Background Task)

POST
`/logs/{log_id}/ai-process`

Description
Starts AI processing in the background. The API returns immediately while AI runs asynchronously.

Response

```json
{
  "status": "processing",
  "message": "AI analysis started"
}
```

AI Task Responsibilities

- Read log content
- Generate summary
- Extract key points
- Suggest tags
- Calculate learning score

---

## Get AI Result

GET
`/logs/{log_id}/ai-result`

Response

```json
{
  "log_id": 1,
  "summary": "User studied FastAPI async architecture and dependency injection",
  "key_points": [
    "Async endpoints",
    "Dependency injection",
    "FastAPI performance advantages"
  ],
  "suggested_tags": ["fastapi", "python", "backend"],
  "learning_score": 8.5
}
```

---

# 4. File Upload API

Allows users to upload notes or documents.

POST
`/upload`

Request

Multipart form-data

```
file: learning_notes.pdf
```

Response

```json
{
  "file_id": 5,
  "filename": "learning_notes.pdf",
  "message": "File uploaded successfully"
}
```

Optional AI Processing

Extract:

- summary
- topics
- difficulty level

---

# 5. WebSocket API (Real-time AI Feedback)

Endpoint

```
/ws/ai-feedback
```

Description

Allows users to send learning text and receive live AI feedback.

Client Message

```json
{
  "content": "I am learning FastAPI dependency injection"
}
```

Server Response

```json
{
  "feedback": "Consider also exploring FastAPI dependency overrides for testing."
}
```

---

# Optional Advanced Features

These can be added later.

## Pagination

GET `/logs?page=1&limit=10`

---

## Search Logs

GET `/logs/search?q=fastapi`

---

## Update Log

PUT `/logs/{log_id}`

---

# Suggested Tech Stack

Backend Framework
FastAPI

Database
PostgreSQL or SQLite

ORM
SQLModel or SQLAlchemy

AI Integration
OpenAI API or local LLM

Authentication
JWT

---

# Final Project Structure (Suggested)

```
app
 ├── main.py
 ├── models
 ├── schemas
 ├── routes
 ├── services
 ├── ai
 ├── database
 └── utils
```

---

# Expected Learning Outcomes

By completing this project you will learn:

- FastAPI architecture
- API design best practices
- Request validation
- Authentication
- Background processing
- AI API integration
- File uploads
- WebSockets
- Clean backend structure

---

# Estimated Project Size

- 12–15 endpoints
- 4 core modules
- 1 AI integration layer
- 1 background processing system

---

# Background Jobs (Production-Learning Setup)

This project now uses a cron-style worker with APScheduler for AI analysis.

Detailed learning guide: `BACKGROUND_JOBS_PLAYBOOK.md`

## What happens now

- API only enqueues analysis (`queued`)
- Worker picks queued jobs every 30 seconds
- Failed jobs are retried every 2 minutes
- Stuck `processing` jobs are marked failed/dead-letter every 5 minutes

## Status flow

`queued -> processing -> completed`

If errors occur:

`processing -> failed -> processing (retry) -> dead_letter`

## New fields on `AiAnalysis`

- `retryCount`
- `lastError`
- `processingStartedAt`
- `updatedAt`

## Run commands

Apply schema and regenerate client:

```bash
uv run prisma migrate deploy
uv run prisma generate
```

Run API server:

```bash
uv run uvicorn app.main:app --reload
```

Run worker (separate terminal/process):

```bash
uv run python -m app.background_jobs.worker
```

Optional: run scheduler in API process (local-only)

```bash
RUN_SCHEDULER_IN_API=true
```

Recommended production mode is separate API + worker processes.
