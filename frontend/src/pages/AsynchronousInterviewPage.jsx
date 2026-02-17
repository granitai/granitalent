import React, { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import axios from 'axios'
import AsynchronousInterviewInterface from '../components/AsynchronousInterviewInterface'
import './InterviewPortal.css'

const API_BASE_URL = '/api'

function AsynchronousInterviewPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [interview, setInterview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const interviewId = searchParams.get('interview_id')
  const email = searchParams.get('email')

  useEffect(() => {
    if (!interviewId || !email) {
      setError('Missing interview ID or email. Please access this page from the interview portal.')
      setLoading(false)
      return
    }

    loadInterview()
  }, [interviewId, email])

  const loadInterview = async () => {
    try {
      setLoading(true)
      setError('')

      const response = await axios.get(`${API_BASE_URL}/candidates/interviews/${interviewId}`, {
        params: { email: email.trim() }
      })

      // Verify it's actually asynchronous mode
      const interviewMode = response.data.job_offer?.interview_mode || 'realtime'
      if (interviewMode !== 'asynchronous') {
        setError('This interview is not in asynchronous mode. Redirecting to realtime interview...')
        setTimeout(() => {
          navigate(`/interview?interview_id=${interviewId}&email=${encodeURIComponent(email)}`)
        }, 2000)
        return
      }

      setInterview({
        ...response.data,
        interview_id: interviewId,
        email: email.trim(),
        interview_mode: 'asynchronous'
      })
    } catch (err) {
      console.error('Error loading interview:', err)
      setError(err.response?.data?.detail || 'Failed to load interview. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="interview-portal">
        <div className="portal-header">
          <h1>Loading Interview...</h1>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="interview-portal">
        <div className="portal-header">
          <h1>Error</h1>
        </div>
        <div className="error-message">{error}</div>
        <button onClick={() => navigate('/interview')} className="start-btn">
          Back to Interview Portal
        </button>
      </div>
    )
  }

  if (!interview) {
    return (
      <div className="interview-portal">
        <div className="portal-header">
          <h1>Interview Not Found</h1>
        </div>
        <button onClick={() => navigate('/interview')} className="start-btn">
          Back to Interview Portal
        </button>
      </div>
    )
  }

  return (
    <AsynchronousInterviewInterface
      interview={interview}
      onClose={() => {
        navigate('/candidates')
      }}
    />
  )
}

export default AsynchronousInterviewPage


