# AI Interview Application - Deployment Guide

This guide explains how to deploy the AI Interview application using Docker.

## 📋 Prerequisites

- **Docker** and **Docker Compose** installed on your machine or server.
- An API Key for:
  - **OpenAI** or **Gemini** (LLM)
  - **ElevenLabs** or **Cartesia** (Text-to-Speech)
  - **Replay.ai** (optional, for analytics)

## 🚀 Quick Start (Local)

1. **Configure Environment Variables**
   Create a `.env` file in the `backend/` directory:
   ```bash
   cp backend/.env.example backend/.env
   # Edit backend/.env with your actual API keys
   ```

2. **Build and Run**
   Open a terminal in the project root and run:
   ```bash
   docker-compose up --build
   ```

3. **Access the Application**
   - **Frontend**: http://localhost
   - **Backend API**: http://localhost/api
   - **API Docs**: http://localhost/docs

## 🌍 Deploying to a Linux Server

### 1. Prepare the Server
```bash
# Update and install Docker
sudo apt update
sudo apt install -y docker.io docker-compose
sudo systemctl start docker
sudo systemctl enable docker
```

### 2. Transfer Files
Clone your repository or copy the files to the server (e.g., to `/opt/ai-interview`).

### 3. Configure Configuration
Navigate to the `backend` directory and create your `.env` file:
```bash
cd backend
nano .env
```
Paste your API keys and configuration.

### 4. Start the Application
Return to the root directory and start the services:
```bash
cd /opt/ai-interview
docker-compose up -d --build
```

### 5. Verify Deployment
Check the status of your containers:
```bash
docker-compose ps
```
View logs if needed:
```bash
docker-compose logs -f
```

## 📂 Data Persistence

The application is configured to persist important data even if containers are restarted:
- **Database**: Stored in `./backend/database.db`
- **Video Recordings**: Stored in `./backend/uploads/`

**Note:** Ensure your server has enough disk space for video recordings.

## 🔧 Troubleshooting

**Frontend not loading?**
- Ensure port 80 is not blocked by a firewall (`sudo ufw allow 80`).
- Check frontend logs: `docker-compose logs frontend`

**API errors?**
- Check backend logs: `docker-compose logs backend`
- Verify your API keys in `backend/.env` are correct.

**Video uploads failing?**
- Ensure the `./backend/uploads` directory exists and is writable.
- Docker should handle this automatically, but you can try: `mkdir -p backend/uploads && chmod 777 backend/uploads`
