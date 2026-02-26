import React from 'react'
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'sonner'
import { AuthProvider } from './contexts/AuthContext'
import ErrorBoundary from './components/ErrorBoundary'
import ProtectedRoute from './components/ProtectedRoute'

import PublicLayout from './components/layouts/PublicLayout'
import AdminLayout from './components/layouts/AdminLayout'

import JobListPage from './pages/public/JobListPage'
import JobDetailPage from './pages/public/JobDetailPage'
import ApplicationPage from './pages/public/ApplicationPage'
import MyApplicationsPage from './pages/public/MyApplicationsPage'
import LoginPage from './pages/public/LoginPage'

import DashboardPage from './pages/admin/DashboardPage'
import ApplicationsPage from './pages/admin/ApplicationsPage'
import ApplicationDetailPage from './pages/admin/ApplicationDetailPage'
import CandidatesPage from './pages/admin/CandidatesPage'
import JobOffersPage from './pages/admin/JobOffersPage'
import JobOfferFormPage from './pages/admin/JobOfferFormPage'
import InterviewsPage from './pages/admin/InterviewsPage'
import InterviewDetailPage from './pages/admin/InterviewDetailPage'

import RealtimeInterviewPage from './pages/interview/RealtimeInterviewPage'
import AsyncInterviewPage from './pages/interview/AsyncInterviewPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Router>
            <Routes>
              {/* Public pages */}
              <Route path="/login" element={<LoginPage />} />

              <Route element={<PublicLayout />}>
                <Route index element={<Navigate to="/jobs" replace />} />
                <Route path="jobs" element={<JobListPage />} />
                <Route path="jobs/:id" element={<JobDetailPage />} />
                <Route path="jobs/:id/apply" element={<ApplicationPage />} />
                <Route path="my-applications" element={<MyApplicationsPage />} />

                {/* Legacy redirects */}
                <Route path="candidates" element={<Navigate to="/jobs" replace />} />
                <Route path="dashboard" element={<Navigate to="/my-applications" replace />} />
                <Route path="interview" element={<Navigate to="/my-applications" replace />} />
                <Route path="interview/async-portal" element={<Navigate to="/my-applications" replace />} />
              </Route>

              {/* Admin pages */}
              <Route
                path="/admin"
                element={
                  <ProtectedRoute>
                    <AdminLayout />
                  </ProtectedRoute>
                }
              >
                <Route index element={<DashboardPage />} />
                <Route path="applications" element={<ApplicationsPage />} />
                <Route path="applications/:id" element={<ApplicationDetailPage />} />
                <Route path="candidates" element={<CandidatesPage />} />
                <Route path="job-offers" element={<JobOffersPage />} />
                <Route path="job-offers/new" element={<JobOfferFormPage />} />
                <Route path="job-offers/:id/edit" element={<JobOfferFormPage />} />
                <Route path="interviews" element={<InterviewsPage />} />
                <Route path="interviews/:id" element={<InterviewDetailPage />} />
              </Route>

              {/* Full-screen interview pages */}
              <Route path="interview/realtime" element={<RealtimeInterviewPage />} />
              <Route path="interview/async" element={<AsyncInterviewPage />} />
            </Routes>
          </Router>
          <Toaster position="top-right" richColors closeButton />
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

export default App
