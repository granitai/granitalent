import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import {
  HiMicrophone,
  HiBriefcase,
  HiClock,
  HiCheckCircle,
  HiPlay,
  HiEye,
  HiEnvelope,
  HiSparkles,
  HiChatBubbleLeftRight,
  HiVideoCamera,
  HiShieldCheck,
  HiArrowRight,
  HiCalendarDays
} from 'react-icons/hi2'
import AsynchronousInterviewInterface from '../components/AsynchronousInterviewInterface'
import './InterviewPortal.css'

const API_BASE_URL = '/api'

function AsynchronousInterviewPortal() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [interviews, setInterviews] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedInterview, setSelectedInterview] = useState(null)
  const [activeInterview, setActiveInterview] = useState(null)
  const [isSearchFocused, setIsSearchFocused] = useState(false)

  const loadInterviews = async () => {
    if (!email.trim()) {
      setError('Please enter your email address')
      return
    }

    try {
      setLoading(true)
      setError('')
      const response = await axios.get(`${API_BASE_URL}/candidates/interviews`, {
        params: { email: email.trim() }
      })

      // Filter only asynchronous interviews
      const asyncInterviews = response.data.filter(interview => {
        const interviewMode = interview.job_offer?.interview_mode || interview.interview_mode
        return interviewMode === 'asynchronous'
      })

      setInterviews(asyncInterviews)
      if (asyncInterviews.length === 0) {
        setError('No asynchronous interviews found for this email address. Make sure you use the same email you used when applying.')
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

  const handleStartInterview = async (e, interview) => {
    if (e) {
      e.preventDefault()
      e.stopPropagation()
    }

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
      // Navigate to asynchronous interview page
      const url = `/interview/async?interview_id=${interview.interview_id}&email=${encodeURIComponent(email.trim())}`
      navigate(url)
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
        {status === 'completed' && <HiCheckCircle className="badge-icon" />}
        {status === 'pending' && <HiClock className="badge-icon" />}
        {status.charAt(0).toUpperCase() + status.slice(1)}
      </span>
    )
  }

  const features = [
    {
      icon: <HiClock />,
      title: 'Flexible Timing',
      description: 'Complete your interview anytime within the deadline'
    },
    {
      icon: <HiChatBubbleLeftRight />,
      title: 'AI-Powered',
      description: 'Engage with our intelligent interview assistant'
    },
    {
      icon: <HiShieldCheck />,
      title: 'Fair & Consistent',
      description: 'Every candidate gets the same opportunity'
    }
  ]

  return (
    <div className="async-portal">
      {/* Decorative Background for the whole page */}
      <div className="portal-background">
        <div className="bg-gradient-orb bg-orb-1"></div>
        <div className="bg-gradient-orb bg-orb-2"></div>
        <div className="bg-grid-pattern"></div>
      </div>

      <div className="portal-layout">
        {/* LEFT PANEL: Branding & Info */}
        <div className="portal-left-panel">
          <div className="hero-content">
            <div className="hero-badge">
              <HiSparkles className="badge-sparkle" />
              <span>AI-Powered Interviews</span>
            </div>

            <div className="branding-container">
              <div className="hero-icon-wrapper">
                <div className="hero-icon-ring"></div>
                <div className="hero-icon-ring hero-icon-ring-2"></div>
                <HiMicrophone className="hero-icon" />
              </div>

              <h1 className="hero-title">
                <span className="title-line">Asynchronous</span>
                <span className="title-line gradient-text">Interview Portal</span>
              </h1>
            </div>

            <p className="hero-subtitle">
              Complete your interview on your own schedule. Our AI assistant will guide you
              through a seamless professional experience.
            </p>

            <div className="features-compact">
              {features.map((feature, index) => (
                <div key={index} className="feature-item" style={{ '--delay': `${index * 0.1}s` }}>
                  <div className="feature-icon-small">{feature.icon}</div>
                  <div className="feature-text">
                    <strong>{feature.title}</strong>
                    <span>{feature.description}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* RIGHT PANEL: Interaction Area */}
        <div className="portal-right-panel">
          <div className="panel-content-wrapper">
            {/* Search Section */}
            <section className={`portal-search-section ${interviews.length > 0 ? 'compact' : 'centered'}`}>
              <div className="search-container">
                <div className="search-header">
                  <h2>Find Your Interviews</h2>
                  <p>Enter your application email to begin</p>
                </div>

                <div className={`search-input-wrapper ${isSearchFocused ? 'focused' : ''} ${email ? 'has-value' : ''}`}>
                  <div className="search-input-icon">
                    <HiEnvelope />
                  </div>
                  <input
                    type="email"
                    placeholder="your.email@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    onFocus={() => setIsSearchFocused(true)}
                    onBlur={() => setIsSearchFocused(false)}
                    onKeyPress={(e) => e.key === 'Enter' && loadInterviews()}
                    className="search-input"
                  />
                  <button
                    onClick={loadInterviews}
                    disabled={loading}
                    className="search-button"
                  >
                    {loading ? (
                      <span className="loading-spinner"></span>
                    ) : (
                      <HiArrowRight className="btn-arrow" />
                    )}
                  </button>
                </div>

                {error && (
                  <div className="search-error">
                    <span className="error-icon">!</span>
                    {error}
                  </div>
                )}
              </div>
            </section>

            {/* Interviews List */}
            {interviews.length > 0 && (
              <section className="portal-interviews-section">
                <div className="section-header">
                  <h3>
                    <HiVideoCamera className="section-icon" />
                    Available Interviews
                  </h3>
                  <span className="interview-count">{interviews.length}</span>
                </div>

                <div className="interviews-grid">
                  {interviews.map((interview, index) => (
                    <div
                      key={interview.interview_id}
                      className={`interview-card-enhanced ${interview.status}`}
                      style={{ '--index': index }}
                    >
                      <div className="card-status-indicator"></div>

                      <div className="card-top">
                        <div className="card-job-badge">
                          <HiBriefcase />
                        </div>
                        {getStatusBadge(interview.status)}
                      </div>

                      <div className="card-content">
                        <h3 className="card-title">{interview.job_offer.title}</h3>

                        <div className="card-meta">
                          {interview.created_at && (
                            <div className="meta-item">
                              <HiCalendarDays />
                              <span>{new Date(interview.created_at).toLocaleDateString()}</span>
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="card-action">
                        {interview.status === 'pending' && (
                          <button
                            type="button"
                            className="action-btn primary"
                            onClick={(e) => handleStartInterview(e, interview)}
                          >
                            <HiPlay />
                            <span>Start</span>
                          </button>
                        )}
                        {interview.status === 'completed' && (
                          <button
                            className="action-btn secondary"
                            onClick={() => handleStartInterview(null, interview)}
                          >
                            <HiEye />
                            <span>Details</span>
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
        </div>
      </div>

      {/* Modal for Interview Details */}
      {selectedInterview && (
        <div className="modal-overlay" onClick={() => setSelectedInterview(null)}>
          <div className="modal-content enhanced-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-group">
                <div className="modal-icon">
                  <HiBriefcase />
                </div>
                <div>
                  <h2>Interview Details</h2>
                  <p className="modal-subtitle">{selectedInterview.job_offer.title}</p>
                </div>
              </div>
              <button className="close-btn" onClick={() => setSelectedInterview(null)}>
                ×
              </button>
            </div>
            <div className="modal-body">
              <div className="detail-row">
                <span className="detail-label">Status</span>
                <span className={`detail-value status-${selectedInterview.status}`}>
                  {selectedInterview.status === 'completed' ? '✓ Completed' : 'Pending'}
                </span>
              </div>
              {selectedInterview.assessment && (
                <div className="assessment-section">
                  <h3>
                    <HiSparkles />
                    Assessment Summary
                  </h3>
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

export default AsynchronousInterviewPortal
