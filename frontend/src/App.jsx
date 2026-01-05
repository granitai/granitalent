import React from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import CandidatePortal from './pages/CandidatePortal'
import CandidateDashboard from './pages/CandidateDashboard'
import AdminPanel from './pages/AdminPanel'
import InterviewPortal from './pages/InterviewPortal'
import LoginPage from './pages/LoginPage'
import Layout from './components/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import ProtectedRoute from './components/ProtectedRoute'
import { AuthProvider } from './contexts/AuthContext'

function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <Router>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<Layout />}>
              <Route index element={<Navigate to="/candidates" replace />} />
              <Route path="candidates" element={<CandidatePortal />} />
              <Route path="dashboard" element={<CandidateDashboard />} />
              <Route 
                path="admin" 
                element={
                  <ProtectedRoute>
                    <AdminPanel />
                  </ProtectedRoute>
                } 
              />
              <Route path="interview" element={<InterviewPortal />} />
            </Route>
          </Routes>
        </Router>
      </AuthProvider>
    </ErrorBoundary>
  )
}

export default App

