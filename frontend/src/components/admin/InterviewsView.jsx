import React, { useState, useEffect } from 'react'
import { HiArrowPath, HiEye, HiXMark, HiChatBubbleLeftRight, HiDocumentText, HiUser, HiCpuChip, HiSpeakerWave, HiArchiveBox, HiArchiveBoxXMark } from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import './InterviewsView.css'

function InterviewsView({ viewMode = 'card' }) {
  const { authApi } = useAuth()
  const [interviews, setInterviews] = useState([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({
    status: '',
    job_offer_id: '',
    date_from: '',
    date_to: '',
    date_preset: 'all',
    show_archived: false
  })
  const [jobOffers, setJobOffers] = useState([])
  const [selectedInterview, setSelectedInterview] = useState(null)
  const [activeTab, setActiveTab] = useState('assessment')
  const [recordingAudioUrl, setRecordingAudioUrl] = useState(null)
  const [loadingRecording, setLoadingRecording] = useState(false)

  // Helper function to calculate date ranges for quick filters
  const getDateRange = (preset) => {
    const today = new Date()
    const todayStr = today.toISOString().split('T')[0]

    switch (preset) {
      case 'today':
        return { date_from: todayStr, date_to: todayStr }
      case 'week':
        const weekAgo = new Date(today)
        weekAgo.setDate(weekAgo.getDate() - 7)
        return { date_from: weekAgo.toISOString().split('T')[0], date_to: todayStr }
      case 'month':
        const monthAgo = new Date(today)
        monthAgo.setDate(monthAgo.getDate() - 30)
        return { date_from: monthAgo.toISOString().split('T')[0], date_to: todayStr }
      case 'all':
      default:
        return { date_from: '', date_to: '' }
    }
  }

  const handleDatePresetChange = (preset) => {
    const dateRange = getDateRange(preset)
    setFilters(prev => ({
      ...prev,
      date_preset: preset,
      date_from: dateRange.date_from,
      date_to: dateRange.date_to
    }))
  }

  const handleFilterChange = (key, value) => {
    if (key === 'date_from' || key === 'date_to') {
      setFilters(prev => ({ ...prev, [key]: value, date_preset: 'custom' }))
    } else {
      setFilters(prev => ({ ...prev, [key]: value }))
    }
  }

  const handleArchiveInterview = async (interviewId, isArchived) => {
    try {
      const action = isArchived ? 'unarchive' : 'archive'
      await authApi.post(`/admin/interviews/${interviewId}/${action}`)

      // Update locally instead of reloading to preserve scroll position
      if (isArchived) {
        // Unarchiving - update the item's archived status
        setInterviews(prev => prev.map(interview =>
          interview.interview_id === interviewId
            ? { ...interview, is_archived: false, archived_at: null }
            : interview
        ))
      } else {
        // Archiving - either remove from list or update status based on filter
        if (filters.show_archived) {
          // If showing archived, just update the status
          setInterviews(prev => prev.map(interview =>
            interview.interview_id === interviewId
              ? { ...interview, is_archived: true, archived_at: new Date().toISOString() }
              : interview
          ))
        } else {
          // If not showing archived, remove from list
          setInterviews(prev => prev.filter(interview => interview.interview_id !== interviewId))
        }
      }
    } catch (error) {
      console.error(`Error ${isArchived ? 'unarchiving' : 'archiving'} interview:`, error)
      alert(`Failed to ${isArchived ? 'restore' : 'archive'} interview`)
    }
  }

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
      if (filters.date_from) params.append('date_from', filters.date_from)
      if (filters.date_to) params.append('date_to', filters.date_to)
      if (filters.show_archived) params.append('show_archived', 'true')

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
      setRecordingAudioUrl(null) // Reset recording URL
    } catch (error) {
      console.error('Error loading interview details:', error)
      alert('Error loading interview details')
    }
  }

  const loadRecording = async () => {
    if (!selectedInterview) return

    // Only try to load if has_recording is true
    if (!selectedInterview.has_recording) {
      setRecordingAudioUrl(null)
      return
    }

    try {
      setLoadingRecording(true)
      const response = await authApi.get(`/admin/interviews/${selectedInterview.interview_id}/recording`)

      // Convert base64 to audio URL
      const audioData = atob(response.data.recording_audio)
      const audioBytes = new Uint8Array(audioData.length)
      for (let i = 0; i < audioData.length; i++) {
        audioBytes[i] = audioData.charCodeAt(i)
      }

      const blob = new Blob([audioBytes], { type: `audio/${response.data.audio_format || 'mp3'}` })
      const audioUrl = URL.createObjectURL(blob)
      setRecordingAudioUrl(audioUrl)
    } catch (error) {
      console.error('Error loading recording:', error)
      setRecordingAudioUrl(null)
      // Don't show alert, just show "no recording" message
    } finally {
      setLoadingRecording(false)
    }
  }

  useEffect(() => {
    // Load recording when recording tab is selected
    if (activeTab === 'recording' && selectedInterview && !recordingAudioUrl && !loadingRecording) {
      loadRecording()
    }
  }, [activeTab, selectedInterview?.interview_id])

  useEffect(() => {
    // Cleanup audio URL when component unmounts or interview changes
    return () => {
      if (recordingAudioUrl) {
        URL.revokeObjectURL(recordingAudioUrl)
        setRecordingAudioUrl(null)
      }
    }
  }, [selectedInterview?.interview_id])

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
            onChange={(e) => handleFilterChange('status', e.target.value)}
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
            onChange={(e) => handleFilterChange('job_offer_id', e.target.value)}
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

      {/* Date Filter Row */}
      <div className="date-filters">
        <div className="date-presets">
          <span className="filter-label">Time Period:</span>
          <button
            className={`preset-btn ${filters.date_preset === 'today' ? 'active' : ''}`}
            onClick={() => handleDatePresetChange('today')}
          >
            Today
          </button>
          <button
            className={`preset-btn ${filters.date_preset === 'week' ? 'active' : ''}`}
            onClick={() => handleDatePresetChange('week')}
          >
            Last 7 Days
          </button>
          <button
            className={`preset-btn ${filters.date_preset === 'month' ? 'active' : ''}`}
            onClick={() => handleDatePresetChange('month')}
          >
            Last 30 Days
          </button>
          <button
            className={`preset-btn ${filters.date_preset === 'all' ? 'active' : ''}`}
            onClick={() => handleDatePresetChange('all')}
          >
            All Time
          </button>
        </div>
        <div className="date-range">
          <div className="date-input-group">
            <label>From:</label>
            <input
              type="date"
              value={filters.date_from}
              onChange={(e) => handleFilterChange('date_from', e.target.value)}
            />
          </div>
          <div className="date-input-group">
            <label>To:</label>
            <input
              type="date"
              value={filters.date_to}
              onChange={(e) => handleFilterChange('date_to', e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Archive Toggle */}
      <div className="archive-toggle">
        <label className="toggle-label">
          <input
            type="checkbox"
            checked={filters.show_archived}
            onChange={(e) => handleFilterChange('show_archived', e.target.checked)}
          />
          <span>Show Archived Interviews</span>
        </label>
      </div>

      <div className={`interviews-list ${viewMode === 'row' ? 'row-view' : 'card-view'}`}>
        {/* Table Header for Row View */}
        {viewMode === 'row' && interviews.length > 0 && (
          <div className="table-header-row">
            <div className="th-cell">Name</div>
            <div className="th-cell">Status</div>
            <div className="th-cell">Job</div>
            <div className="th-cell">Email</div>
            <div className="th-cell">Created</div>
            <div className="th-cell">Completed</div>
            <div className="th-cell">Actions</div>
          </div>
        )}
        {interviews.length === 0 ? (
          <p className="no-results">No interviews found</p>
        ) : (
          interviews.map(interview => (
            <div key={interview.interview_id} className={`interview-card ${viewMode === 'row' ? 'row-layout' : ''}`}>
              {viewMode === 'row' ? (
                /* Row View - Values Only */
                <>
                  <div className="row-cell name-cell">
                    <span className="candidate-name">{interview.candidate.name}</span>
                  </div>
                  <div className="row-cell status-cell">
                    <div className="badges">
                      {getStatusBadge(interview.status)}
                      {getRecommendationBadge(interview.recommendation)}
                    </div>
                  </div>
                  <div className="row-cell">{interview.job_offer.title}</div>
                  <div className="row-cell">{interview.candidate.email || '-'}</div>
                  <div className="row-cell">{interview.created_at ? new Date(interview.created_at).toLocaleDateString() : '-'}</div>
                  <div className="row-cell">{interview.completed_at ? new Date(interview.completed_at).toLocaleDateString() : '-'}</div>
                  <div className="row-cell actions-cell">
                    <button
                      className="view-btn icon-only"
                      onClick={() => handleViewDetails(interview.interview_id)}
                      title="View Details"
                    >
                      <HiEye className="icon" />
                    </button>
                    <button
                      className={`archive-btn icon-only ${interview.is_archived ? 'unarchive' : ''}`}
                      onClick={() => handleArchiveInterview(interview.interview_id, interview.is_archived)}
                      title={interview.is_archived ? 'Restore' : 'Archive'}
                    >
                      {interview.is_archived ? <HiArchiveBoxXMark className="icon" /> : <HiArchiveBox className="icon" />}
                    </button>
                  </div>
                </>
              ) : (
                /* Card View - Original with Labels */
                <>
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
                    <button
                      className={`archive-btn ${interview.is_archived ? 'unarchive' : ''}`}
                      onClick={() => handleArchiveInterview(interview.interview_id, interview.is_archived)}
                      title={interview.is_archived ? 'Restore Interview' : 'Archive Interview'}
                    >
                      {interview.is_archived ? <HiArchiveBoxXMark className="icon" /> : <HiArchiveBox className="icon" />}
                    </button>
                  </div>
                </>
              )}
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
                <button
                  className={`tab ${activeTab === 'recording' ? 'active' : ''}`}
                  onClick={() => setActiveTab('recording')}
                >
                  <HiSpeakerWave className="tab-icon" />
                  Interview Recording
                  {selectedInterview.has_recording && (
                    <span className="recording-badge" style={{ marginLeft: '8px', fontSize: '10px', background: '#00d4aa', color: 'white', padding: '2px 6px', borderRadius: '10px' }}>●</span>
                  )}
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

                {activeTab === 'recording' && (
                  <div className="recording-tab">
                    {/* Video Recording Section */}
                    {selectedInterview.recording_video && (
                      <div className="video-section" style={{ marginBottom: '2rem' }}>
                        <h3 style={{ marginBottom: '1rem' }}>Video Recording</h3>
                        <div style={{ backgroundColor: '#000', borderRadius: '8px', overflow: 'hidden', maxWidth: '640px' }}>
                          <video
                            controls
                            style={{ width: '100%', display: 'block' }}
                            src={`/uploads/${selectedInterview.recording_video}`}
                          >
                            Your browser does not support the video tag.
                          </video>
                        </div>
                      </div>
                    )}

                    {selectedInterview.audio_segments && selectedInterview.audio_segments.length > 0 ? (
                      <div className="audio-segments-list" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                        <h3 style={{ marginBottom: '1rem' }}>Interview Audio Messages</h3>
                        {selectedInterview.audio_segments.map((segment, index) => {
                          const isQuestion = segment.type === 'question'
                          const audioUrl = segment.audioUrl || (() => {
                            try {
                              const audioData = atob(segment.audio)
                              const audioBytes = new Uint8Array(audioData.length)
                              for (let i = 0; i < audioData.length; i++) {
                                audioBytes[i] = audioData.charCodeAt(i)
                              }
                              const blob = new Blob([audioBytes], { type: `audio/${segment.format || 'mp3'}` })
                              return URL.createObjectURL(blob)
                            } catch (e) {
                              console.error('Error creating audio URL:', e)
                              return null
                            }
                          })()

                          return (
                            <div
                              key={index}
                              style={{
                                display: 'flex',
                                justifyContent: isQuestion ? 'flex-start' : 'flex-end',
                                marginBottom: '0.5rem'
                              }}
                            >
                              <div style={{
                                maxWidth: '70%',
                                padding: '0.75rem 1rem',
                                borderRadius: '18px',
                                backgroundColor: isQuestion ? '#e5e5ea' : '#007bff',
                                color: isQuestion ? '#000' : '#fff',
                                boxShadow: '0 1px 2px rgba(0,0,0,0.1)'
                              }}>
                                <div style={{
                                  fontSize: '0.85em',
                                  marginBottom: '0.5rem',
                                  opacity: 0.8,
                                  fontWeight: '500'
                                }}>
                                  {isQuestion ? '🤖 AI Interviewer' : '👤 Candidate'}
                                  {segment.question_number && ` - Question ${segment.question_number}`}
                                </div>
                                {segment.text && (
                                  <div style={{
                                    marginBottom: '0.5rem',
                                    fontSize: '0.9em',
                                    lineHeight: '1.4'
                                  }}>
                                    {segment.text}
                                  </div>
                                )}
                                {audioUrl && (
                                  <audio
                                    controls
                                    src={audioUrl}
                                    style={{
                                      width: '100%',
                                      maxWidth: '300px',
                                      height: '32px',
                                      marginTop: '0.5rem'
                                    }}
                                  >
                                    Your browser does not support the audio element.
                                  </audio>
                                )}
                                {segment.timestamp && (
                                  <div style={{
                                    fontSize: '0.75em',
                                    marginTop: '0.25rem',
                                    opacity: 0.6
                                  }}>
                                    {new Date(segment.timestamp).toLocaleTimeString()}
                                  </div>
                                )}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    ) : (
                      <div className="empty-state">
                        <p><strong>No audio segments available for this interview.</strong></p>
                        <p className="hint" style={{ marginTop: '1rem', color: '#666' }}>
                          {selectedInterview.status === 'completed'
                            ? 'The audio segments may not have been saved. This feature requires the interview to be completed with the new audio segments system.'
                            : 'The audio segments will be available once the interview is completed.'}
                        </p>
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

