# 🎙️ AI Interview Platform

A full-stack AI-powered interview platform that conducts technical interviews using real-time voice conversation. The platform handles the entire recruitment pipeline — from job posting and candidate application, through AI-powered CV screening, to conducting voice-based interviews with automatic evaluation and scoring.

---

## Table of Contents

- [Features Overview](#features-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Architecture Overview](#architecture-overview)
- [Setup & Installation](#setup--installation)
  - [Prerequisites](#prerequisites)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
  - [Creating an Admin User](#creating-an-admin-user)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [Deployment (Docker)](#deployment-docker)
- [Database](#database)
  - [Models](#models)
  - [Migrations](#migrations)
- [API Endpoints Reference](#api-endpoints-reference)
- [AI Service Providers](#ai-service-providers)
- [Frontend Pages & Routes](#frontend-pages--routes)
- [Key Features In Depth](#key-features-in-depth)
- [Development Notes](#development-notes)

---

## Features Overview

### 🎤 AI Interviews
- **Real-time Voice Interview** — WebSocket-based live conversation with AI interviewer, including video recording, speech-to-text, text-to-speech, and real-time transcript
- **Asynchronous Interview** — Question-by-question interview mode where candidates record audio/video answers at their own pace
- **Configurable Interview Duration** — Set per job offer (default: 20 minutes) with intelligent time management prompts
- **Automatic Assessment** — AI generates structured evaluation reports with scoring on multiple axes at the end of each interview
- **Language Evaluation** — Multi-language support with automatic language switching during interviews to test candidate proficiency
- **Custom Questions** — Recruiters can define mandatory questions per job offer that the AI must ask
- **Evaluation Weight Customization** — Recruiters can set priority weights for different evaluation categories (e.g., technical skills vs. communication)

### 📄 CV Processing
- **CV Upload & Parsing** — Extracts text from PDF CVs using PyPDF2
- **AI-Powered CV Evaluation** — Evaluates CVs against job offer requirements, producing an approval/rejection with detailed reasoning
- **Language & Job Fit Checks** — Separate AI analysis for language proficiency and job fit

### 👥 Candidate Management
- **Candidate Portal** — Public-facing page where candidates browse job offers and submit applications (no signup required)
- **Centralized Portal ("My Applications")** — Candidates can check all their applications and interviews by email
- **Candidate Dashboard** — View interview details, transcripts, and assessment reports

### 🛡️ Admin Panel (Protected)
- **JWT Authentication** — Secure admin login with bcrypt password hashing
- **Dashboard Overview** — Statistics on applications, interviews, and candidates
- **Job Offers Management** — Full CRUD for job offers with interview configuration (mode, duration, languages, custom questions, evaluation weights)
- **Applications Management** — View, filter, search, archive/unarchive, and delete applications
- **Interview Management** — View transcripts, assessment reports, evaluation scores, audio/video recordings; archive/unarchive/delete
- **Candidates Management** — Search and manage candidate profiles
- **AI Decision Override** — HR can override AI screening decisions (approve rejected or reject approved candidates)
- **Interview Invitation** — Send interview invitations to approved candidates

---

## Tech Stack

| Layer        | Technology                                                      |
| ------------ | --------------------------------------------------------------- |
| **Backend**  | Python 3.11+, FastAPI, Uvicorn, SQLAlchemy ORM, SQLite          |
| **Frontend** | React 18, Vite 5, React Router 6, Axios, React Icons            |
| **AI / TTS** | ElevenLabs (Flash v2.5, Multilingual v2), Cartesia Sonic        |
| **AI / STT** | ElevenLabs Scribe (v1, v2, Streaming), Cartesia Ink             |
| **AI / LLM** | Google Gemini (2.5 Flash-Lite, 2.0 Flash, 1.5), OpenAI GPT (4o, 4o-mini, 3.5-turbo) via OpenRouter |
| **Auth**     | JWT (python-jose), bcrypt (passlib)                             |
| **Deploy**   | Docker, Docker Compose, Nginx (reverse proxy)                   |

---

## Project Structure

```
AI_Interview/
├── backend/                      # Python FastAPI backend
│   ├── models/
│   │   ├── db_models.py          # SQLAlchemy ORM models (JobOffer, Candidate, Application, CVEvaluation, Interview, Admin)
│   │   ├── conversation.py       # In-memory conversation state model for real-time interviews
│   │   └── job_offer.py          # Job offer pydantic/data models
│   ├── services/
│   │   ├── gemini_llm.py         # Google Gemini LLM integration (interview responses, assessments)
│   │   ├── gpt_llm.py            # OpenAI GPT LLM integration (via OpenRouter)
│   │   ├── elevenlabs_tts.py     # ElevenLabs Text-to-Speech
│   │   ├── elevenlabs_stt.py     # ElevenLabs Speech-to-Text
│   │   ├── elevenlabs_stt_streaming.py  # ElevenLabs streaming STT (real-time)
│   │   ├── cartesia_tts.py       # Cartesia Text-to-Speech
│   │   ├── cartesia_stt.py       # Cartesia Speech-to-Text
│   │   ├── cv_parser.py          # PDF CV text extraction
│   │   ├── cv_evaluator.py       # AI-powered CV evaluation against job requirements
│   │   ├── language_evaluator.py # Language proficiency evaluation service
│   │   ├── language_llm_gemini.py    # Gemini-specific language evaluation
│   │   ├── language_llm_gpt.py       # GPT-specific language evaluation
│   │   ├── language_prompts.py       # System prompts for language evaluation
│   │   └── elevenlabs_account_check.py  # ElevenLabs account/credits checker
│   ├── main.py                   # FastAPI app — all API endpoints + WebSocket handler (~4900 lines)
│   ├── config.py                 # Configuration: providers, models, system prompts, time management
│   ├── database.py               # SQLAlchemy engine & session setup
│   ├── auth.py                   # JWT token management, password hashing, auth middleware
│   ├── init_db.py                # Database initialization script
│   ├── migrate_db.py             # Database migration script (adds new columns to existing tables)
│   ├── create_admin.py           # CLI script to create admin users
│   ├── requirements.txt          # Python dependencies
│   ├── .env                      # Environment variables (NOT committed to git)
│   ├── .env.example              # Example environment variables template
│   └── uploads/                  # Uploaded files (CVs, cover letters, audio, video)
│       ├── cvs/                  # Uploaded CV PDFs
│       ├── cover_letters/        # Uploaded cover letters
│       ├── audio/                # Interview audio recordings
│       └── videos/               # Interview video recordings
│
├── frontend/                     # React + Vite frontend
│   ├── src/
│   │   ├── App.jsx               # Root component with React Router routes
│   │   ├── main.jsx              # React entry point
│   │   ├── index.css             # Global styles
│   │   ├── pages/                # Page-level components
│   │   │   ├── CandidatePortal.jsx           # Public job listing & application page
│   │   │   ├── CandidateDashboard.jsx        # Candidate's view of their interviews
│   │   │   ├── CentralizedPortal.jsx         # "My Applications" search portal
│   │   │   ├── InterviewPortal.jsx           # Interview mode selection portal
│   │   │   ├── AsynchronousInterviewPortal.jsx  # Async interview entry portal
│   │   │   ├── AsynchronousInterviewPage.jsx    # Async interview session wrapper
│   │   │   ├── RealtimeInterviewPage.jsx        # Real-time interview session wrapper
│   │   │   ├── AdminPanel.jsx                # Admin panel layout with tab navigation
│   │   │   └── LoginPage.jsx                 # Admin login page
│   │   ├── components/
│   │   │   ├── InterviewInterface.jsx        # Real-time interview UI (WebSocket, mic, video, transcript)
│   │   │   ├── AsynchronousInterviewInterface.jsx  # Async interview UI (question-by-question)
│   │   │   ├── Layout.jsx                    # App layout with navigation bar
│   │   │   ├── ProtectedRoute.jsx            # Auth guard for admin routes
│   │   │   ├── ErrorBoundary.jsx             # React error boundary
│   │   │   └── admin/                        # Admin panel sub-components
│   │   │       ├── DashboardOverview.jsx     # Stats dashboard (cards with counts)
│   │   │       ├── JobOffersView.jsx         # Job offers CRUD with form
│   │   │       ├── ApplicationsView.jsx      # Applications list with filters
│   │   │       ├── ApplicationDetailModal.jsx # Application detail modal
│   │   │       ├── InterviewsView.jsx        # Interviews list with transcript/report viewers
│   │   │       ├── CandidatesView.jsx        # Candidates list
│   │   │       ├── JobOfferApplications.jsx  # Per-offer applications view
│   │   │       ├── InterviewInviteModal.jsx  # Interview invitation dialog
│   │   │       └── OverrideModal.jsx         # AI decision override dialog
│   │   ├── contexts/
│   │   │   └── AuthContext.jsx               # React context for auth state management
│   │   └── utils/
│   │       └── (utility files)
│   ├── package.json
│   ├── vite.config.js            # Vite config with API/WebSocket proxy
│   ├── Dockerfile                # Multi-stage build (Node → Nginx)
│   └── nginx.conf                # Nginx config for SPA + API reverse proxy
│
├── Dockerfile                    # Backend Dockerfile (Python 3.11-slim)
├── docker-compose.yml            # Docker Compose (backend + frontend services)
├── DEPLOYMENT.md                 # Detailed Docker deployment guide
├── .gitignore                    # Git ignore rules
└── .dockerignore                 # Docker ignore rules
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        FRONTEND                             │
│                   React + Vite (port 3000)                  │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Candidate   │  │  Interview   │  │   Admin Panel    │  │
│  │   Portal     │  │  Interface   │  │  (Protected)     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────────┘  │
│         │                 │                  │              │
│         │    REST API     │   WebSocket      │   REST API   │
└─────────┼─────────────────┼──────────────────┼──────────────┘
          │                 │                  │
          ▼                 ▼                  ▼
┌─────────────────────────────────────────────────────────────┐
│                        BACKEND                              │
│                  FastAPI + Uvicorn (port 8000)               │
│                                                             │
│  ┌─────────┐  ┌───────────────┐  ┌────────────────────┐    │
│  │  Auth   │  │  Interview    │  │  Application &     │    │
│  │  (JWT)  │  │  Engine       │  │  Candidate CRUD    │    │
│  └─────────┘  │  (WebSocket)  │  └────────────────────┘    │
│               └───────┬───────┘                             │
│                       │                                     │
│         ┌─────────────┼─────────────┐                       │
│         ▼             ▼             ▼                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │   TTS    │  │   STT    │  │   LLM    │                  │
│  │ElevenLabs│  │ElevenLabs│  │  Gemini  │                  │
│  │ Cartesia │  │ Cartesia │  │   GPT    │                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
│                                                             │
│  ┌──────────────────────────────────────────┐               │
│  │           SQLite + SQLAlchemy            │               │
│  │  (JobOffer, Candidate, Application,      │               │
│  │   CVEvaluation, Interview, Admin)        │               │
│  └──────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

**Key data flows:**
1. **Candidate applies** → CV uploaded → AI evaluates CV → Application created (approved/rejected)
2. **Admin selects candidate** → Interview invitation sent → Interview created (pending)
3. **Real-time interview** → WebSocket connection → AI asks questions via TTS → Candidate speaks → STT transcribes → LLM generates response → Loop until time expires → Assessment generated
4. **Async interview** → REST API → AI generates question → Candidate records answer → STT transcribes → Next question → Assessment generated

---

## Setup & Installation

### Prerequisites

- **Python** 3.11+ with `pip`
- **Node.js** 18+ with `npm`
- **FFmpeg** (optional, for audio processing with `pydub`)
- API keys for the AI services you want to use (see [Environment Variables](#environment-variables))

### Backend Setup

```bash
# 1. Navigate to the backend directory
cd backend

# 2. Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Create the .env file from the template
copy .env.example .env    # Windows
cp .env.example .env      # Linux/macOS

# 5. Edit .env and add your API keys (see Environment Variables section)

# 6. Initialize the database (auto-creates database.db)
python init_db.py

# 7. (Optional) Run migrations if upgrading from an older version
python migrate_db.py
```

### Frontend Setup

```bash
# 1. Navigate to the frontend directory
cd frontend

# 2. Install dependencies
npm install
```

### Creating an Admin User

Before using the admin panel, you must create at least one admin user:

```bash
# From the project root directory (with venv activated)
cd backend
python create_admin.py
```

You will be prompted to enter:
- **Username** — The admin login username
- **Password** — The admin password (max 72 bytes for bcrypt; ASCII characters recommended)
- **Email** — Optional email address

---

## Environment Variables

Create a `backend/.env` file with the following keys:

| Variable                       | Required | Description                                                           |
|-------------------------------|----------|-----------------------------------------------------------------------|
| `ELEVENLABS_API_KEY`          | Yes*     | ElevenLabs API key for TTS & STT                                      |
| `GOOGLE_API_KEY`              | Yes*     | Google API key for Gemini LLM                                         |
| `OPENAI_API_KEY`              | No       | OpenAI API key (used if GPT provider is selected)                     |
| `OPENROUTER_API_KEY`          | No       | OpenRouter API key (alternative route for GPT models)                 |
| `CARTESIA_API_KEY`            | No       | Cartesia API key (alternative TTS/STT provider)                       |
| `JWT_SECRET_KEY`              | **Yes**  | Secret key for JWT token signing. Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `VOICE_ID`                    | No       | ElevenLabs voice ID (default: `cjVigY5qzO86Huf0OWal`)                |
| `CARTESIA_VOICE_ID`           | No       | Cartesia voice ID (default: `79a125e8-cd45-4c13-8a67-188112f4dd22`)   |
| `INTERVIEW_TIME_LIMIT_MINUTES`| No       | Global interview time limit in minutes (default: `20`)                |

> *At minimum, you need either ElevenLabs + Google API keys **or** Cartesia + OpenAI keys to run interviews.

**Example `.env` file:**
```env
ELEVENLABS_API_KEY=sk-your-elevenlabs-key
GOOGLE_API_KEY=AIzaSy-your-google-key
OPENAI_API_KEY=sk-your-openai-key
JWT_SECRET_KEY=a1b2c3d4e5f6...  # 32+ character hex string
INTERVIEW_TIME_LIMIT_MINUTES=20
```

---

## Running the Application

### Local Development

**Start the backend** (from `backend/` with venv activated):
```bash
python main.py
```
Backend runs at: `http://localhost:8000`
API docs (Swagger): `http://localhost:8000/docs`

**Start the frontend** (from `frontend/`):
```bash
npm run dev
```
Frontend runs at: `http://localhost:3000`

> The Vite dev server proxies `/api/*` → `http://localhost:8000` and `/ws/*` → `ws://localhost:8000` automatically via `vite.config.js`.

---

## Deployment (Docker)

### Quick Start

```bash
# 1. Ensure backend/.env is configured
# 2. From the project root:
docker-compose build
docker-compose up -d
```

- **Frontend** → `http://SERVER_IP:3034` (served by Nginx)
- **Backend API** → `http://SERVER_IP:8000` (or proxied through `/api`)
- **API Docs** → `http://SERVER_IP:3034/docs`

### Docker Architecture

| Service     | Image            | Port    | Description                          |
|-------------|------------------|---------|--------------------------------------|
| `backend`   | Python 3.11-slim | 8000    | FastAPI + Uvicorn                    |
| `frontend`  | Nginx Alpine     | 3034    | Static files + reverse proxy to API  |

The Nginx configuration (`frontend/nginx.conf`) handles:
- SPA routing (`try_files` → `index.html`)
- API proxy (`/api` → `http://backend:8000`)
- WebSocket proxy (`/ws` → `http://backend:8000`)

### Useful Docker Commands

```bash
docker-compose logs -f              # View all logs
docker-compose logs -f backend      # Backend logs only
docker-compose restart              # Restart services
docker-compose down                 # Stop services
docker-compose up -d --build        # Rebuild and restart
docker-compose exec backend bash    # Shell into backend container
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full deployment guide.

---

## Database

The application uses **SQLite** with **SQLAlchemy ORM**. The database file (`database.db`) is automatically created in the backend directory on first startup.

### Models

| Model            | Table            | Description                                                    |
|------------------|------------------|----------------------------------------------------------------|
| **JobOffer**     | `job_offers`     | Job positions with title, description, required skills, languages, interview configuration (mode, duration, custom questions, evaluation weights) |
| **Candidate**    | `candidates`     | Unique candidate profiles (name, email, phone, LinkedIn, portfolio) |
| **Application**  | `applications`   | Links candidates to job offers. Stores CV evaluation results, AI status (approved/rejected/pending), HR status, cover letter & CV filenames. Supports archiving |
| **CVEvaluation** | `cv_evaluations` | Detailed CV evaluation results — score, status, reasoning, parsed CV text |
| **Interview**    | `interviews`     | Interview records — status (pending/completed/cancelled), interview type (realtime/async), transcript, assessment report, evaluation scores, audio/video recording paths. Supports archiving |
| **Admin**        | `admins`         | Admin user accounts with bcrypt-hashed passwords               |

### Key Relationships

```
JobOffer  ──< Application >──  Candidate
                  │
                  └──< Interview
                  │
                  └──< CVEvaluation
```

### Migrations

If you upgrade and new columns have been added, run:

```bash
cd backend
python migrate_db.py
```

This script safely adds missing columns to existing tables without data loss. It checks each column before adding it.

---

## API Endpoints Reference

All API endpoints are prefixed with `/api` when accessed through the Nginx proxy in production.

### Authentication
| Method | Endpoint              | Auth | Description                  |
|--------|-----------------------|------|------------------------------|
| POST   | `/api/login`          | No   | Admin login, returns JWT     |
| GET    | `/api/me`             | Yes  | Get current admin info       |

### Job Offers (Admin)
| Method | Endpoint                         | Auth | Description                    |
|--------|----------------------------------|------|--------------------------------|
| POST   | `/api/admin/job-offers`          | Yes  | Create a new job offer         |
| GET    | `/api/admin/job-offers`          | Yes  | List all job offers            |
| GET    | `/api/admin/job-offers/{id}`     | Yes  | Get job offer details          |
| PUT    | `/api/admin/job-offers/{id}`     | Yes  | Update a job offer             |
| DELETE | `/api/admin/job-offers/{id}`     | Yes  | Delete a job offer             |

### Job Offers (Public)
| Method | Endpoint                      | Auth | Description                         |
|--------|-------------------------------|------|-------------------------------------|
| GET    | `/api/job-offers`             | No   | List active job offers for candidates |

### Applications
| Method | Endpoint                                    | Auth | Description                                   |
|--------|---------------------------------------------|------|-----------------------------------------------|
| POST   | `/api/apply`                                | No   | Submit a candidate application (with CV file) |
| GET    | `/api/admin/applications`                   | Yes  | List/filter/search applications               |
| GET    | `/api/admin/applications/{id}`              | Yes  | Get full application details                  |
| POST   | `/api/admin/applications/{id}/archive`      | Yes  | Archive an application                        |
| POST   | `/api/admin/applications/{id}/unarchive`    | Yes  | Unarchive an application                      |
| DELETE | `/api/admin/applications/{id}`              | Yes  | Permanently delete an application             |

### AI Decision Overrides
| Method | Endpoint                                       | Auth | Description                    |
|--------|------------------------------------------------|------|--------------------------------|
| POST   | `/api/admin/applications/{id}/override`        | Yes  | Override AI screening decision |
| POST   | `/api/admin/applications/{id}/select`          | Yes  | Manually select candidate      |
| POST   | `/api/admin/applications/{id}/reject`          | Yes  | Manually reject candidate      |

### Interview Management
| Method | Endpoint                                       | Auth   | Description                           |
|--------|------------------------------------------------|--------|---------------------------------------|
| POST   | `/api/admin/applications/{id}/invite`          | Yes    | Send interview invitation             |
| GET    | `/api/admin/interviews`                        | Yes    | List/filter interviews                |
| GET    | `/api/admin/interviews/{id}`                   | Yes    | Get interview details + assessment    |
| GET    | `/api/admin/interviews/{id}/recording`         | Yes    | Get interview audio recording         |
| POST   | `/api/admin/interviews/{id}/archive`           | Yes    | Archive an interview                  |
| POST   | `/api/admin/interviews/{id}/unarchive`         | Yes    | Unarchive an interview                |
| DELETE | `/api/admin/interviews/{id}`                   | Yes    | Permanently delete an interview       |

### Candidate Endpoints
| Method | Endpoint                              | Auth | Description                                |
|--------|---------------------------------------|------|--------------------------------------------|
| GET    | `/api/admin/candidates`               | Yes  | List/search all candidates                 |
| GET    | `/api/admin/candidates/{email}`       | Yes  | Get candidate details by email             |
| DELETE | `/api/admin/candidates/{id}`          | Yes  | Delete candidate + all related data        |
| GET    | `/api/candidate/applications`         | No   | Get applications by email (candidate view) |
| GET    | `/api/candidate/interviews`           | No   | Get interviews by email (candidate view)   |
| GET    | `/api/candidate/interviews/{id}`      | No   | Get interview details (with email check)   |

### CV Upload & Evaluation
| Method | Endpoint                    | Auth | Description                              |
|--------|-----------------------------|------|------------------------------------------|
| POST   | `/api/upload-cv`            | No   | Upload and evaluate a CV against a job   |
| GET    | `/api/evaluation/{id}`      | No   | Get CV evaluation result                 |

### Asynchronous Interview
| Method | Endpoint                                     | Auth | Description                               |
|--------|----------------------------------------------|------|-------------------------------------------|
| POST   | `/api/async-interview/{id}/start`            | No   | Start async interview, get first question |
| POST   | `/api/async-interview/{id}/answer`           | No   | Submit answer, get next question          |
| POST   | `/api/async-interview/{id}/end`              | No   | End interview, generate assessment        |
| POST   | `/api/async-interview/{id}/recording`        | No   | Save combined audio recording             |
| POST   | `/api/interview/{id}/upload-video`           | No   | Upload video recording                   |

### Real-time Interview (WebSocket)
| Protocol  | Endpoint      | Description                                              |
|-----------|---------------|----------------------------------------------------------|
| WebSocket | `/ws/interview` | Real-time bidirectional audio streaming for live interviews |

### Dashboard & Search
| Method | Endpoint                        | Auth | Description                      |
|--------|---------------------------------|------|----------------------------------|
| GET    | `/api/admin/dashboard/stats`    | Yes  | Get dashboard statistics         |
| GET    | `/api/admin/search/applications`| Yes  | Search/filter applications       |
| GET    | `/api/admin/search/candidates`  | Yes  | Search candidates by name/skills |

### Utility
| Method | Endpoint                | Auth | Description                       |
|--------|-------------------------|------|-----------------------------------|
| GET    | `/`                     | No   | Root endpoint (health)            |
| GET    | `/api/health`           | No   | Health check                      |
| GET    | `/api/providers`        | No   | Get available AI providers/models |
| GET    | `/api/elevenlabs/status`| No   | Check ElevenLabs account credits  |

---

## AI Service Providers

The platform supports multiple AI providers that can be configured per interview or globally:

### Text-to-Speech (TTS)

| Provider    | Models                                                     | Default        |
|-------------|------------------------------------------------------------|----------------|
| **ElevenLabs** | Flash v2.5 (fast), Multilingual v2 (quality), Turbo v2.5 (balanced) | Flash v2.5  |
| **Cartesia**   | Sonic (standard), Sonic English (optimized), Sonic 2 (HQ)            | Sonic       |

### Speech-to-Text (STT)

| Provider              | Models                                  | Default    |
|-----------------------|-----------------------------------------|------------|
| **ElevenLabs**        | Scribe v1 (high accuracy), Scribe v2 (low latency) | Scribe v1 |
| **ElevenLabs Streaming** | Scribe v2 Streaming (real-time)      | Scribe v2  |
| **Cartesia**          | Ink Whisper (real-time)                 | Ink Whisper|

### Large Language Model (LLM)

| Provider        | Models                                                      | Default            |
|-----------------|-------------------------------------------------------------|--------------------|
| **Google Gemini** | 2.5 Flash-Lite, 2.0 Flash, 1.5 Flash, 1.5 Pro            | 2.5 Flash-Lite     |
| **OpenAI GPT**    | GPT-4o, GPT-4o Mini, GPT-4 Turbo, GPT-3.5 Turbo          | GPT-4o Mini        |

Providers are configured in `backend/config.py` and can be changed via the admin panel when creating job offers or starting interviews.

---

## Frontend Pages & Routes

| Route                    | Page Component              | Description                                    | Auth    |
|--------------------------|-----------------------------|------------------------------------------------|---------|
| `/`                      | *Redirects to `/candidates`* | Default redirect                              | No      |
| `/candidates`            | `CandidatePortal`           | Browse job offers, submit applications         | No      |
| `/dashboard`             | `CandidateDashboard`        | Candidate's interview details view             | No      |
| `/my-applications`       | `CentralizedPortal`         | Search all applications by email               | No      |
| `/interview`             | `InterviewPortal`           | Interview mode selection                       | No      |
| `/interview/async-portal`| `AsynchronousInterviewPortal` | Async interview entry portal                 | No      |
| `/interview/async`       | `AsynchronousInterviewPage` | Async interview session                        | No      |
| `/interview/realtime`    | `RealtimeInterviewPage`     | Real-time interview session                    | No      |
| `/login`                 | `LoginPage`                 | Admin login                                    | No      |
| `/admin`                 | `AdminPanel`                | Admin dashboard (tabs: Overview, Job Offers, Applications, Interviews, Candidates) | **Yes** |

---

## Key Features In Depth

### Real-time Interview Flow

1. Candidate enters interview via link with `interview_id` and `email`
2. WebSocket connection established to `/ws/interview`
3. **Pre-check phase**: AI verifies candidate name and conducts audio check
4. **Interview phase**: AI asks questions → candidate speaks → STT transcribes → LLM generates response → TTS converts to audio → audio sent back via WebSocket
5. **Time management**: The AI system prompt is dynamically updated with time remaining, prompting the AI to conclude when under 2 minutes
6. **Language switching**: If multiple languages are required, AI plans when to switch and explicitly asks candidate to respond in target language
7. **Conclusion**: When time expires or AI concludes, assessment is generated with detailed scores on multiple axes
8. **Recording**: Full video and audio are recorded and uploaded

### Asynchronous Interview Flow

1. Candidate starts interview via REST API with `interview_id` and `email`
2. AI generates first question with TTS audio
3. Candidate records and submits audio answer for each question
4. STT transcribes the answer → LLM generates next question
5. After all questions, assessment is generated
6. Full recording is assembled and saved

### CV Evaluation Pipeline

1. Candidate uploads PDF CV with application
2. `cv_parser.py` extracts text using PyPDF2
3. `cv_evaluator.py` sends CV text + job requirements to LLM
4. LLM returns structured evaluation: score, approved/rejected, reasoning
5. Separate language and job fit checks can be performed
6. Results stored in `CVEvaluation` table and shown in admin panel

### Interview Assessment

The AI generates a structured assessment report with:
- **Overall score** and recommendation (recommended / not recommended)
- **Per-axis scores** across multiple evaluation categories:
  - Technical Knowledge
  - Problem Solving
  - Communication Skills
  - Experience Relevance
  - Cultural Fit
  - Language Proficiency (per language tested)
- **Detailed feedback** with examples from the interview
- **Grammar and language quality** analysis with at least 5 extracted examples

---

## Development Notes

### Key Files to Know

- **`backend/main.py`** — The main application file (~4900 lines). Contains all REST API endpoints and the WebSocket handler for real-time interviews. This is the central nervous system of the backend.
- **`backend/config.py`** — All configuration including AI providers, models, the full interviewer system prompt with dynamic context injection (job info, CV, time management, language requirements).
- **`backend/auth.py`** — JWT authentication logic. Tokens expire after 24 hours. Uses HTTP Bearer scheme.
- **`frontend/src/components/InterviewInterface.jsx`** — The real-time interview UI component. Handles WebSocket communication, audio recording (via MediaRecorder API), video recording, and real-time transcript display.
- **`frontend/src/components/AsynchronousInterviewInterface.jsx`** — The async interview UI component. Handles question-by-question flow with audio recording.

### Important Configuration

- **CORS** is set to allow all origins (`allow_origins=["*"]`). In production, restrict to your frontend URL in `backend/main.py`.
- **API proxy** is configured in `frontend/vite.config.js` for local development. In production, Nginx handles the proxying.
- **Database** auto-initializes on backend startup. No manual schema creation needed.
- **Uploads directory** — CVs, cover letters, audio, and video files are stored in `backend/uploads/`. This directory is gitignored.
- **WebSocket** communication uses JSON messages with base64-encoded audio data.
- **Interview deduplication** — Audio messages are deduplicated within a 5-second window to prevent processing the same audio twice.

### Adding a New AI Provider

1. Create a new service file in `backend/services/` (e.g., `new_provider_tts.py`)
2. Add the provider to the corresponding dictionary in `backend/config.py` (`TTS_PROVIDERS`, `STT_PROVIDERS`, or `LLM_PROVIDERS`)
3. Import and register the functions in `main.py` (`get_tts_function`, `get_stt_function`, or `get_llm_functions`)

### Database Tips

- Database file is at `backend/database.db` (gitignored)
- Use `python migrate_db.py` after pulling updates that add new columns
- The migration script is idempotent — safe to run multiple times
- For a fresh start, delete `database.db` and run `python init_db.py`

---
