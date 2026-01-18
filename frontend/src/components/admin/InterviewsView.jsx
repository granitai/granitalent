import React, { useState, useEffect } from 'react'
import { HiArrowPath, HiEye, HiXMark, HiChatBubbleLeftRight, HiDocumentText, HiUser, HiCpuChip } from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import './InterviewsView.css'

function InterviewsView({ viewMode = 'card' }) {
  const { authApi } = useAuth()
  const [interviews, setInterviews] = useState([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({
    status: '',
    job_offer_id: ''
  })
  const [jobOffers, setJobOffers] = useState([])
  const [selectedInterview, setSelectedInterview] = useState(null)
  const [activeTab, setActiveTab] = useState('assessment')

  useEffect(() => {
    loadInterviews()
    loadJobOffers()
  }, [filters])

  const loadInterviews = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams()
      if (filters.status) params.append('status', filters.status)
      if (filters.job_offer_id) params.append('job_offer_id', filters.job_offer_id)

      const response = await authApi.get(`/admin/interviews?${params}`)
      setInterviews(response.data)
    } catch (error) {
      console.error('Error loading interviews:', error)
      alert('Error loading interviews')
    } finally {
      setLoading(false)
    }
  }

  const loadJobOffers = async () => {
    try {
      const response = await authApi.get(`/admin/job-offers`)
      setJobOffers(response.data)
    } catch (error) {
      console.error('Error loading job offers:', error)
    }
  }

  const handleViewDetails = async (interviewId) => {
    try {
      const response = await authApi.get(`/admin/interviews/${interviewId}`)
      setSelectedInterview(response.data)
      setActiveTab('assessment') // Reset to assessment tab when opening new interview
    } catch (error) {
      console.error('Error loading interview details:', error)
      alert('Error loading interview details')
    }
  }

  const getStatusBadge = (status) => {
    const colors = {
      completed: { bg: 'rgba(0, 212, 170, 0.2)', color: '#00d4aa', border: '#00d4aa' },
      pending: { bg: 'rgba(255, 193, 7, 0.2)', color: '#ffc107', border: '#ffc107' },
      cancelled: { bg: 'rgba(160, 174, 192, 0.2)', color: '#a0aec0', border: '#a0aec0' }
    }
    const style = colors[status] || colors.pending
    return (
      <span className="status-badge" style={style}>
        {status}
      </span>
    )
  }

  const getRecommendationBadge = (recommendation) => {
    if (!recommendation) return null
    const colors = {
      recommended: { bg: 'rgba(0, 212, 170, 0.2)', color: '#00d4aa', border: '#00d4aa' },
      not_recommended: { bg: 'rgba(255, 68, 68, 0.2)', color: '#ff4444', border: '#ff4444' }
    }
    const style = colors[recommendation] || colors.recommended
    return (
      <span className="status-badge" style={style}>
        {recommendation.replace('_', ' ')}
      </span>
    )
  }

  const parseConversationHistory = (conversationJson) => {
    if (!conversationJson) return []
    try {
      const parsed = JSON.parse(conversationJson)
      return Array.isArray(parsed) ? parsed : []
    } catch (e) {
      console.error('Error parsing conversation history:', e)
      return []
    }
  }

  const formatAssessment = (assessment) => {
    if (!assessment) return null
    // Convert markdown-like formatting to HTML
    let formatted = assessment
      // Headers (must be done before other replacements)
      .replace(/^### (.*$)/gim, '<h3>$1</h3>')
      .replace(/^## (.*$)/gim, '<h2>$1</h2>')
      .replace(/^# (.*$)/gim, '<h1>$1</h1>')
      // Bold (**text** -> <strong>text</strong>) - must be before italic
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      // Lists (- item -> <li>item</li>)
      .replace(/^- (.*$)/gim, '<li>$1</li>')
      // Numbered lists (1. item -> <li>item</li>)
      .replace(/^\d+\. (.*$)/gim, '<li>$1</li>')
      // Line breaks
      .replace(/\n/g, '<br>')
    
    // Wrap consecutive <li> tags in <ul>
    const lines = formatted.split('<br>')
    let inList = false
    formatted = lines.map((line, idx) => {
      const isListItem = line.trim().startsWith('<li>')
      const prevIsListItem = idx > 0 && lines[idx - 1].trim().startsWith('<li>')
      const nextIsListItem = idx < lines.length - 1 && lines[idx + 1].trim().startsWith('<li>')
      
      if (isListItem && !prevIsListItem) {
        inList = true
        return '<ul>' + line
      } else if (isListItem && !nextIsListItem) {
        inList = false
        return line + '</ul>'
      }
      return line
    }).join('<br>')
    
    return formatted
  }

  if (loading) {
    return <div className="loading">Loading interviews...</div>
  }

  return (
    <div className="interviews-view">
      <div className="view-header">
        <h2>Interviews</h2>
        <button onClick={loadInterviews} className="refresh-btn" title="Refresh">
          <HiArrowPath className="icon" />
        </button>
      </div>

      <div className="filters">
        <div className="filter-group">
          <label>Status</label>
          <select
            value={filters.status}
            onChange={(e) => setFilters({ ...filters, status: e.target.value })}
          >
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
        <div className="filter-group">
          <label>Job Offer</label>
          <select
            value={filters.job_offer_id}
            onChange={(e) => setFilters({ ...filters, job_offer_id: e.target.value })}
          >
            <option value="">All Offers</option>
            {jobOffers.map(offer => (
              <option key={offer.offer_id} value={offer.offer_id}>
                {offer.title}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className={`interviews-list ${viewMode === 'row' ? 'row-view' : 'card-view'}`}>
        {interviews.length === 0 ? (
          <p className="no-results">No interviews found</p>
        ) : (
          interviews.map(interview => (
            <div key={interview.interview_id} className={`interview-card ${viewMode === 'row' ? 'row-layout' : ''}`}>
              <div className="card-header">
                <h3>{interview.candidate.name}</h3>
                <div className="badges">
                  {getStatusBadge(interview.status)}
                  {getRecommendationBadge(interview.recommendation)}
                </div>
              </div>
              <div className="card-body">
                <p><strong>Job:</strong> {interview.job_offer.title}</p>
                {interview.candidate.email && (
                  <p><strong>Email:</strong> {interview.candidate.email}</p>
                )}
                {interview.created_at && (
                  <p><strong>Created:</strong> {new Date(interview.created_at).toLocaleString()}</p>
                )}
                {interview.completed_at && (
                  <p><strong>Completed:</strong> {new Date(interview.completed_at).toLocaleString()}</p>
                )}
              </div>
              <div className="card-actions">
                <button
                  className="view-btn"
                  onClick={() => handleViewDetails(interview.interview_id)}
                >
                  <HiEye className="icon" />
                  <span>View Details</span>
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {selectedInterview && (
        <div className="modal-overlay" onClick={() => setSelectedInterview(null)}>
          <div className="modal-content large" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Interview Results</h2>
              <button className="close-btn" onClick={() => setSelectedInterview(null)}>
                <HiXMark />
              </button>
            </div>

            <div className="modal-body">
              {/* Interview Summary */}
              <div className="interview-summary">
                <div className="summary-item">
                  <span className="label">Candidate</span>
                  <span className="value">{selectedInterview.candidate.name}</span>
                </div>
                {selectedInterview.candidate.email && (
                  <div className="summary-item">
                    <span className="label">Email</span>
                    <span className="value">{selectedInterview.candidate.email}</span>
                  </div>
                )}
                <div className="summary-item">
                  <span className="label">Position</span>
                  <span className="value">{selectedInterview.job_offer.title}</span>
                </div>
                <div className="summary-item">
                  <span className="label">Status</span>
                  <span className="value">{getStatusBadge(selectedInterview.status)}</span>
                </div>
                {selectedInterview.recommendation && (
                  <div className="summary-item">
                    <span className="label">Recommendation</span>
                    <span className="value">{getRecommendationBadge(selectedInterview.recommendation)}</span>
                  </div>
                )}
                {selectedInterview.completed_at && (
                  <div className="summary-item">
                    <span className="label">Completed</span>
                    <span className="value">{new Date(selectedInterview.completed_at).toLocaleString()}</span>
                  </div>
                )}
              </div>

              {/* Tabs */}
              <div className="tabs">
                <button
                  className={`tab ${activeTab === 'assessment' ? 'active' : ''}`}
                  onClick={() => setActiveTab('assessment')}
                >
                  <HiDocumentText className="tab-icon" />
                  Assessment & Evaluation
                </button>
                <button
                  className={`tab ${activeTab === 'transcript' ? 'active' : ''}`}
                  onClick={() => setActiveTab('transcript')}
                >
                  <HiChatBubbleLeftRight className="tab-icon" />
                  Interview Transcript
                </button>
              </div>

              {/* Tab Content */}
              <div className="tab-content">
                {activeTab === 'assessment' && (
                  <div className="assessment-tab">
                    {selectedInterview.assessment ? (
                      <div className="assessment-content">
                        <div 
                          className="assessment-text"
                          dangerouslySetInnerHTML={{ __html: formatAssessment(selectedInterview.assessment) }}
                        />
                      </div>
                    ) : (
                      <div className="empty-state">
                        <p>No assessment available yet.</p>
                        <p className="hint">The assessment will be generated when the interview is completed.</p>
                      </div>
                    )}
                  </div>
                )}

                {activeTab === 'transcript' && (
                  <div className="transcript-tab">
                    {parseConversationHistory(selectedInterview.conversation_history).length > 0 ? (
                      <div className="conversation-list">
                        {parseConversationHistory(selectedInterview.conversation_history).map((message, index) => (
                          <div 
                            key={index} 
                            className={`conversation-message ${message.role === 'assistant' ? 'interviewer' : 'candidate'}`}
                          >
                            <div className="message-header">
                              {message.role === 'assistant' ? (
                                <>
                                  <HiCpuChip className="message-icon" />
                                  <span className="sender">AI Interviewer</span>
                                </>
                              ) : (
                                <>
                                  <HiUser className="message-icon" />
                                  <span className="sender">{selectedInterview.candidate.name || 'Candidate'}</span>
                                </>
                              )}
                            </div>
                            <div className="message-body">
                              {message.content}
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="empty-state">
                        <p>No transcript available.</p>
                        <p className="hint">The conversation transcript will appear here once the interview is completed.</p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="modal-actions">
              <button className="btn-close" onClick={() => setSelectedInterview(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default InterviewsView

