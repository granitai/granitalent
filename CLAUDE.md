# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Granitalent is an AI-powered recruitment platform with voice interview capabilities, automated CV screening, and an HR admin dashboard. It consists of a Python FastAPI backend and a React frontend.

## Development Commands

### Backend
```bash
# Install dependencies
pip install -r backend/requirements.txt

# Run dev server (from project root)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Initialize database
python backend/init_db.py

# Create admin user
python backend/create_admin.py

# Run database migrations
python backend/migrate_db.py
```

### Frontend
```bash
cd frontend
npm install
npm run dev      # Vite dev server on :3000 (proxies API to :8000)
npm run build    # Production build to dist/
npm run preview  # Preview production build
```

### Docker
```bash
docker-compose up --build   # Backend on :8000, Frontend (Nginx) on :3034
```

## Architecture

### Backend (`backend/`)
- **main.py** — Monolithic FastAPI application (~5000 lines) containing all 60+ route handlers and business logic
- **config.py** — Provider definitions and configuration constants
- **auth.py** — JWT authentication (python-jose, passlib/bcrypt, 24h token expiry)
- **database.py** — SQLAlchemy setup with SQLite (`database.db`)
- **models/db_models.py** — ORM models: JobOffer, Candidate, Application, CVEvaluation, Interview, Admin
- **models/conversation.py** — In-memory interview conversation state manager with 3-phase workflow (audio_check → name_check → interview)

### Backend Services (`backend/services/`)
Each AI capability is abstracted into provider-specific service files:
- **LLM**: `gemini_llm.py` (Google Gemini) and `gpt_llm.py` (OpenAI via OpenRouter) — interview conversation, evaluation, assessment generation
- **TTS**: `elevenlabs_tts.py`, `cartesia_tts.py` — text-to-speech for interview questions
- **STT**: `elevenlabs_stt.py`, `elevenlabs_stt_streaming.py`, `cartesia_stt.py` — speech-to-text for candidate responses
- **CV**: `cv_parser.py` (PyPDF2 extraction), `cv_evaluator.py` (AI-powered screening)
- **Language**: `language_evaluator.py`, `language_llm_gemini.py`, `language_llm_gpt.py`, `language_prompts.py` — proficiency evaluation

### Frontend (`frontend/src/`)
- **React 18 + Vite 5 + Tailwind CSS 3.4** with React Router 6
- **pages/public/** — Candidate-facing: job listings, application, login
- **pages/admin/** — HR dashboard: applications, candidates, job offers, interviews
- **pages/interview/** — `RealtimeInterviewPage.jsx` (WebSocket live voice) and `AsyncInterviewPage.jsx` (question-by-question recording)
- **contexts/AuthContext.jsx** — Auth state management and pre-configured Axios client (`authApi`)
- **hooks/** — React Query hooks for data fetching (useApplications, useCandidates, useDashboard, useInterviews, useJobOffers)
- **components/shared/** — Reusable UI: Modal, ConfirmDialog, StatusBadge, PageHeader, EmptyState

### Interview Modes
1. **Real-time (WebSocket at `/ws`)** — Live audio streaming, real-time transcript, video recording (WebM), time-limited with warnings
2. **Asynchronous** — Candidates record answers at their own pace, audio/video segments stored per question

### AI Decision Pipeline
CV Upload → Text Extraction → Language Check → Job Fit Evaluation → AI Recommendation (approve/reject) → Optional HR Override → Interview Invitation → Interview → Auto-Assessment with configurable weighted scoring (technical, communication, problem-solving, language, job fit)

## Key Configuration

### Environment Variables (backend/.env)
Required: `ELEVENLABS_API_KEY`, `GOOGLE_API_KEY`, `VOICE_ID`, `CARTESIA_API_KEY`, `OPENAI_API_KEY`, `JWT_SECRET_KEY`, `OPENROUTER_API_KEY`, `INTERVIEW_TIME_LIMIT_MINUTES`

### Vite Proxy (frontend/vite.config.js)
Dev server proxies `/api`, `/ws`, `/uploads` to backend at localhost:8000.

### Tailwind Theme (frontend/tailwind.config.js)
Brand palette uses teal (#0d9488) as primary and purple (#7c3aed) as accent with Inter font.

## No Tests
This project currently has no test suite or test configuration.
