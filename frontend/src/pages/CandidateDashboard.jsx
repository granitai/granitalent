import React, { useState } from 'react'
import axios from 'axios'
import { HiDocumentText, HiMicrophone, HiCheckCircle, HiXCircle, HiClock, HiEye, HiPlay, HiBriefcase } from 'react-icons/hi2'
import { useNavigate } from 'react-router-dom'
import InterviewInterface from '../components/InterviewInterface'
import './CandidateDashboard.css'

// Utiliser une URL relative qui sera gérée par Nginx en production
// et par le proxy Vite en développement
const API_BASE_URL = '/api'

function CandidateDashboard() {
  const [email, setEmail] = useState('')
  const [applications, setApplications] = useState([])
  const [interviews, setInterviews] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState('applications')
  const [selectedInterview, setSelectedInterview] = useState(null)
  const [activeInterview, setActiveInterview] = useState(null)
  const navigate = useNavigate()

  const loadData = async () => {
    if (!email.trim()) {
      setError('Please enter your email address')
      return
    }

    try {
      setLoading(true)
      setError('')
      
      // Load both applications and interviews
      const [applicationsRes, interviewsRes] = await Promise.all([
        axios.get(`${API_BASE_URL}/candidates/applications`, {
          params: { email: email.trim() }
        }),
        axios.get(`${API_BASE_URL}/candidates/interviews`, {
          params: { email: email.trim() }
        })
      ])
      
      setApplications(applicationsRes.data)
      setInterviews(interviewsRes.data)
      
      if (applicationsRes.data.length === 0 && interviewsRes.data.length === 0) {
        setError('No applications or interviews found for this email address. Make sure you use the same email you used when applying.')
      }
    } catch (err) {
      console.error('Error loading data:', err)
      if (err.response?.status === 404) {
        setError('No data found for this email address. Make sure you use the same email you used when applying.')
      } else {
        setError('Error loading data. Please try again.')
      }
      setApplications([])
      setInterviews([])
    } finally {
      setLoading(false)
    }
  }

  const handleStartInterview = async (interview) => {
    if (interview.status === 'completed') {
      // Load full details for completed interviews
      try {
        const response = await axios.get(`${API_BASE_URL}/candidates/interviews/${interview.interview_id}`, {
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

  const getStatusBadge = (status, type = 'application') => {
    const statusClass = status === 'selected' ? 'approved' 
      : status === 'rejected' ? 'rejected' 
      : status === 'completed' ? 'completed'
      : status === 'interview_sent' ? 'approved'
      : 'pending'
    
    const statusText = type === 'application' 
      ? (status === 'selected' ? 'Selected' 
        : status === 'rejected' ? 'Not Selected' 
        : status === 'interview_sent' ? 'Interview Invited' 
        : status === 'under_review' ? 'Under Review'
        : 'Pending')
      : (status === 'completed' ? 'Completed' : status === 'pending' ? 'Pending' : status)
    
    return (
      <span className={`status-badge ${statusClass}`}>
        {statusText}
      </span>
    )
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'selected':
      case 'interview_sent':
      case 'completed':
        return <HiCheckCircle className="status-icon approved" />
      case 'rejected':
        return <HiXCircle className="status-icon rejected" />
      default:
        return <HiClock className="status-icon pending" />
    }
  }

  return (
    <div className="candidate-dashboard">
      <div className="dashboard-header">
        <h1>My Applications & Interviews</h1>
        <p>Track your job applications and interview status</p>
      </div>

      <div className="email-search">
        <div className="search-box">
          <input
            type="email"
            placeholder="Enter your email address"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && loadData()}
          />
          <button onClick={loadData} disabled={loading}>
            {loading ? 'Loading...' : 'View My Applications'}
          </button>
        </div>
        {error && <div className="error-message">{error}</div>}
      </div>

      {(applications.length > 0 || interviews.length > 0) && (
        <div className="dashboard-content">
          <div className="tabs">
            <button 
              className={`tab ${activeTab === 'applications' ? 'active' : ''}`}
              onClick={() => setActiveTab('applications')}
            >
              <HiDocumentText className="tab-icon" />
              <span>Applications ({applications.length})</span>
            </button>
            <button 
              className={`tab ${activeTab === 'interviews' ? 'active' : ''}`}
              onClick={() => setActiveTab('interviews')}
            >
              <HiMicrophone className="tab-icon" />
              <span>Interviews ({interviews.length})</span>
            </button>
          </div>

          {activeTab === 'applications' && (
            <div className="applications-section">
              {applications.length === 0 ? (
                <div className="empty-state">
                  <HiDocumentText className="empty-icon" />
                  <p>No applications found</p>
                </div>
              ) : (
                <div className="applications-grid">
                  {applications.map(app => (
                    <div key={app.application_id} className="application-card">
                      <div className="card-header">
                        <div className="job-info">
                          <HiBriefcase className="job-icon" />
                          <h3>{app.job_offer.title}</h3>
                        </div>
                        {getStatusIcon(app.status || app.hr_status)}
                      </div>
                      
                      <div className="card-body">
                        <div className="status-row">
                          <strong>Status:</strong> {getStatusBadge(app.status || app.hr_status)}
                        </div>
                        {app.submitted_at && (
                          <p className="date-info">
                            <strong>Submitted:</strong> {new Date(app.submitted_at).toLocaleDateString()}
                          </p>
                        )}
                        {app.interview_invited_at && (
                          <p className="date-info">
                            <strong>Interview Invited:</strong> {new Date(app.interview_invited_at).toLocaleDateString()}
                          </p>
                        )}
                        {app.has_interview && (
                          <div className="interview-link">
                            <HiMicrophone className="icon" />
                            <span>Interview {app.interview_status === 'completed' ? 'Completed' : 'Pending'}</span>
                            <button 
                              className="view-interview-btn"
                              onClick={() => {
                                setActiveTab('interviews')
                                // Find and show the interview
                                const interview = interviews.find(i => i.interview_id === app.interview_id)
                                if (interview) {
                                  handleStartInterview(interview)
                                }
                              }}
                            >
                              View Interview
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === 'interviews' && (
            <div className="interviews-section">
              {interviews.length === 0 ? (
                <div className="empty-state">
                  <HiMicrophone className="empty-icon" />
                  <p>No interviews found</p>
                </div>
              ) : (
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
                          Status: {getStatusBadge(interview.status, 'interview')}
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
              )}
            </div>
          )}
        </div>
      )}

      {activeInterview && (
        <InterviewInterface
          interview={activeInterview}
          onClose={() => {
            setActiveInterview(null)
            // Reload data to get updated status
            loadData()
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

export default CandidateDashboard

