import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { HiMicrophone, HiBriefcase, HiClock, HiCheckCircle, HiXCircle, HiPlay, HiEye } from 'react-icons/hi2'
import InterviewInterface from '../components/InterviewInterface'
import './InterviewPortal.css'

const API_BASE_URL = 'http://localhost:8000'

function InterviewPortal() {
  const [email, setEmail] = useState('')
  const [interviews, setInterviews] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedInterview, setSelectedInterview] = useState(null)
  const [activeInterview, setActiveInterview] = useState(null)

  const loadInterviews = async () => {
    if (!email.trim()) {
      setError('Please enter your email address')
      return
    }

    try {
      setLoading(true)
      setError('')
      const response = await axios.get(`${API_BASE_URL}/api/candidates/interviews`, {
        params: { email: email.trim() }
      })
      setInterviews(response.data)
      if (response.data.length === 0) {
        setError('No interviews found for this email address. Make sure you use the same email you used when applying.')
      }
    } catch (err) {
      console.error('Error loading interviews:', err)
      if (err.response?.status === 404) {
        setError('No interviews found for this email address. Make sure you use the same email you used when applying.')
      } else {
        setError('Error loading interviews. Please try again.')
      }
      setInterviews([])
    } finally {
      setLoading(false)
    }
  }

  const handleStartInterview = async (interview) => {
    if (interview.status === 'completed') {
      // Load full details for completed interviews
      try {
        const response = await axios.get(`${API_BASE_URL}/api/candidates/interviews/${interview.interview_id}`, {
          params: { email: email.trim() }
        })
        setSelectedInterview(response.data)
      } catch (err) {
        console.error('Error loading interview details:', err)
        setError('Error loading interview details')
      }
    } else {
      // Start active interview
      setActiveInterview(interview)
    }
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'completed':
        return <HiCheckCircle className="status-icon completed" />
      case 'pending':
        return <HiClock className="status-icon pending" />
      default:
        return <HiClock className="status-icon" />
    }
  }

  const getStatusBadge = (status) => {
    const statusClass = status === 'completed' ? 'completed' : status === 'pending' ? 'pending' : ''
    return (
      <span className={`status-badge ${statusClass}`}>
        {status.charAt(0).toUpperCase() + status.slice(1)}
      </span>
    )
  }

  return (
    <div className="interview-portal">
      <div className="portal-header">
        <HiMicrophone className="portal-icon" />
        <h1>Interview Portal</h1>
        <p>Access and start your AI interviews</p>
      </div>

      <div className="interview-search">
        <div className="search-box">
          <input
            type="email"
            placeholder="Enter your email address"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && loadInterviews()}
          />
          <button onClick={loadInterviews} disabled={loading}>
            {loading ? 'Loading...' : 'Find My Interviews'}
          </button>
        </div>
        {error && <div className="error-message">{error}</div>}
      </div>

      {interviews.length > 0 && (
        <div className="interviews-list">
          <h2>Your Interviews</h2>
          <div className="interviews-grid">
            {interviews.map(interview => (
              <div key={interview.interview_id} className="interview-card">
                <div className="card-header">
                  <div className="job-info">
                    <HiBriefcase className="job-icon" />
                    <h3>{interview.job_offer.title}</h3>
                  </div>
                  {getStatusIcon(interview.status)}
                </div>
                
                <div className="card-body">
                  <div className="status-row">
                    Status: {getStatusBadge(interview.status)}
                  </div>
                  {interview.recommendation && (
                    <div className="recommendation">
                      Recommendation: 
                      <span className={`rec-${interview.recommendation}`}>
                        {interview.recommendation === 'recommended' ? ' ✓ Recommended' : ' ✗ Not Recommended'}
                      </span>
                    </div>
                  )}
                  {interview.created_at && (
                    <p className="date-info">
                      Created: {new Date(interview.created_at).toLocaleDateString()}
                    </p>
                  )}
                  {interview.completed_at && (
                    <p className="date-info">
                      Completed: {new Date(interview.completed_at).toLocaleDateString()}
                    </p>
                  )}
                </div>

                <div className="card-actions">
                  {interview.status === 'pending' && (
                    <button 
                      className="start-btn"
                      onClick={() => handleStartInterview(interview)}
                    >
                      <HiPlay className="icon" />
                      <span>Start Interview</span>
                    </button>
                  )}
                  {interview.status === 'completed' && (
                    <button 
                      className="view-btn"
                      onClick={() => handleStartInterview(interview)}
                    >
                      <HiEye className="icon" />
                      <span>View Details</span>
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeInterview && (
        <InterviewInterface
          interview={activeInterview}
          onClose={() => {
            setActiveInterview(null)
            // Reload interviews to get updated status
            loadInterviews()
          }}
        />
      )}

      {selectedInterview && !activeInterview && (
        <div className="modal-overlay" onClick={() => setSelectedInterview(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Interview Details</h2>
              <button className="close-btn" onClick={() => setSelectedInterview(null)}>
                ×
              </button>
            </div>
            <div className="modal-body">
              <p><strong>Position:</strong> {selectedInterview.job_offer.title}</p>
              <p><strong>Status:</strong> {selectedInterview.status}</p>
              {selectedInterview.assessment && (
                <div className="assessment-section">
                  <h3>Assessment</h3>
                  <div className="assessment-text">
                    {selectedInterview.assessment}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default InterviewPortal

