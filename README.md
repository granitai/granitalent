# AI Interview Platform

A conversational AI interviewer platform that conducts technical interviews using voice interaction, with candidate management and recruitment features.

## Features

- **Real-time voice conversation** with AI interviewer
- **Text-to-Speech** using ElevenLabs Flash v2.5
- **Speech-to-Text** using ElevenLabs Scribe v1
- **LLM** using Google Gemini 2.5 Flash Lite or GPT via OpenRouter
- **CV Evaluation**: AI-powered CV screening against job requirements
- **Candidate Portal**: Browse and apply to job offers
- **Admin Panel**: Manage applications, candidates, and interviews
- **Database**: SQLite with SQLAlchemy for data persistence

## Project Structure

```
AI_Interview/
├── backend/          # Python FastAPI backend
│   ├── models/       # Data models (database and in-memory)
│   ├── services/     # AI services (LLM, TTS, STT, CV parsing)
│   ├── database.py   # Database configuration
│   └── main.py      # FastAPI application
├── frontend/         # React frontend
│   ├── src/
│   │   ├── components/  # React components
│   │   └── pages/      # Page components
│   └── package.json
└── README.md
```

## Setup

### Backend Setup

1. **Install Python dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Configure environment variables:**
   - Copy `.env.example` to `.env` (if exists)
   - Add your API keys:
     - `ELEVENLABS_API_KEY`: Your ElevenLabs API key
     - `GOOGLE_API_KEY`: Your Google API key (for Gemini)
     - `OPENROUTER_API_KEY`: Your OpenRouter API key (for GPT, configured in `gpt_llm.py`)

3. **Initialize database:**
   ```bash
   python init_db.py
   ```

4. **Run the backend:**
   ```bash
   python main.py
   ```
   
   The backend will be available at `http://localhost:8000`

### Frontend Setup

1. **Install dependencies:**
   ```bash
   cd frontend
   npm install
   ```

2. **Start development server:**
   ```bash
   npm run dev
   ```
   
   The frontend will be available at `http://localhost:3000`

## Usage

1. **Candidates**: Visit `/candidates` to browse and apply to job offers
2. **Admin**: Visit `/admin` to manage job offers, applications, and candidates
3. **Interview**: Visit `/interview` to conduct AI interviews (to be fully integrated)

## Database

The application uses **SQLite** with **SQLAlchemy** ORM. The database file (`database.db`) will be created automatically in the backend directory on first run.

### Database Models

- **JobOffer**: Job/internship offers
- **Candidate**: Unique candidate information
- **Application**: Links candidates to job offers with application data
- **CVEvaluation**: CV evaluation results
- **Interview**: Interview records and assessments

## Models Used

- **TTS**: ElevenLabs Flash v2.5 (ultra-low latency) or Cartesia
- **STT**: ElevenLabs Scribe v1 (high accuracy) or Cartesia
- **LLM**: Google Gemini 2.5 Flash Lite or GPT via OpenRouter

## Development Notes

- The backend maintains backward compatibility with in-memory storage
- Database is initialized automatically on backend startup
- Frontend uses React Router for navigation
- API proxy is configured in `vite.config.js` for development

## Future Features

- Email notifications for interview invitations
- Advanced search and filtering
- Interview scheduling
- Analytics dashboard
- PostgreSQL migration option
