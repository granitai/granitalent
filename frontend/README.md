# AI Interview Frontend - React

This is the React frontend for the AI Interview platform.

## Setup

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

3. **Build for production:**
   ```bash
   npm run build
   ```

## Project Structure

```
frontend/
├── src/
│   ├── components/     # Reusable React components
│   ├── pages/         # Page components
│   ├── App.jsx        # Main app component with routing
│   ├── main.jsx       # Entry point
│   └── index.css      # Global styles
├── index.html         # HTML template
├── vite.config.js     # Vite configuration
└── package.json       # Dependencies
```

## Features

- **Candidate Portal**: Browse and apply to job offers
- **Admin Panel**: Manage applications, candidates, and interviews
- **Interview Portal**: Conduct AI interviews (to be integrated)

## Development

The frontend uses:
- **React 18** for UI
- **React Router** for navigation
- **Vite** for build tooling
- **Axios** for API calls

The backend API should be running on `http://localhost:8000` (configured in `vite.config.js` proxy settings).








