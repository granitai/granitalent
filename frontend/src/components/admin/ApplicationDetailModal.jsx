import React, { useState } from 'react'
import { HiXMark, HiCheckCircle, HiXCircle, HiClock, HiUser, HiEnvelope, HiPhone, HiGlobeAlt, HiDocumentText, HiAcademicCap, HiSparkles, HiUserCircle, HiClipboardDocumentCheck, HiBriefcase, HiMicrophone } from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import OverrideModal from './OverrideModal'
import InterviewInviteModal from './InterviewInviteModal'
import './ApplicationDetailModal.css'

function ApplicationDetailModal({ application, onClose }) {
  const { authApi } = useAuth()
  const [showOverrideModal, setShowOverrideModal] = useState(false)
  const [showInterviewModal, setShowInterviewModal] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSelect = async () => {
    try {
      setLoading(true)
      await authApi.post(`/admin/applications/${application.application_id}/select`)
      alert('Candidate selected successfully')
      onClose()
    } catch (error) {
      console.error('Error selecting candidate:', error)
      alert('Error selecting candidate')
    } finally {
      setLoading(false)
    }
  }

  const handleReject = async () => {
    const reason = prompt('Enter rejection reason (optional):')
    if (reason === null) return // User cancelled

    try {
      setLoading(true)
      await authApi.post(`/admin/applications/${application.application_id}/reject`, null, {
        params: { reason }
      })
      alert('Candidate rejected')
      onClose()
    } catch (error) {
      console.error('Error rejecting candidate:', error)
      alert('Error rejecting candidate')
    } finally {
      setLoading(false)
    }
  }

  const getStatusBadge = (status, type) => {
    const colors = {
      approved: { bg: 'rgba(0, 212, 170, 0.2)', color: '#00d4aa', border: '#00d4aa' },
      rejected: { bg: 'rgba(255, 68, 68, 0.2)', color: '#ff4444', border: '#ff4444' },
      pending: { bg: 'rgba(160, 174, 192, 0.2)', color: '#a0aec0', border: '#a0aec0' },
      selected: { bg: 'rgba(108, 99, 255, 0.2)', color: '#6c63ff', border: '#6c63ff' },
      interview_sent: { bg: 'rgba(255, 193, 7, 0.2)', color: '#ffc107', border: '#ffc107' },
      recommended: { bg: 'rgba(0, 212, 170, 0.2)', color: '#00d4aa', border: '#00d4aa' },
      not_recommended: { bg: 'rgba(255, 68, 68, 0.2)', color: '#ff4444', border: '#ff4444' }
    }
    const style = colors[status] || colors.pending
    return (
      <span className="status-badge" style={style}>
        {status}
      </span>
    )
  }

  return (
    <>
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal-content large" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header">
            <h2>Application Details</h2>
            <button className="close-btn" onClick={onClose}>
              <HiXMark />
            </button>
          </div>

          <div className="modal-body">
            <div className="detail-section">
              <h3>
                <HiUser className="section-icon" />
                Candidate Information
              </h3>
              <div className="info-grid">
                <div><HiUserCircle className="info-icon" /><strong>Name:</strong> {application.candidate.full_name}</div>
                <div><HiEnvelope className="info-icon" /><strong>Email:</strong> {application.candidate.email}</div>
                <div><HiPhone className="info-icon" /><strong>Phone:</strong> {application.candidate.phone || 'N/A'}</div>
                {application.candidate.linkedin && (
                  <div><HiGlobeAlt className="info-icon" /><strong>LinkedIn:</strong> <a href={application.candidate.linkedin} target="_blank" rel="noopener noreferrer">{application.candidate.linkedin}</a></div>
                )}
                {application.candidate.portfolio && (
                  <div><HiGlobeAlt className="info-icon" /><strong>Portfolio:</strong> <a href={application.candidate.portfolio} target="_blank" rel="noopener noreferrer">{application.candidate.portfolio}</a></div>
                )}
              </div>
            </div>

            <div className="detail-section">
              <h3>
                <HiBriefcase className="section-icon" />
                Job Application
              </h3>
              <p><strong>Position:</strong> {application.job_offer.title}</p>
              {application.job_offer.required_languages && (
                <div className="required-languages-section">
                  <strong>Required Languages:</strong>
                  <div className="required-languages">
                    {(() => {
                      try {
                        const langs = JSON.parse(application.job_offer.required_languages)
                        return Array.isArray(langs) ? langs.map(lang => (
                          <span key={lang} className="lang-badge">
                            <HiGlobeAlt style={{ fontSize: '0.9rem' }} />
                            {lang}
                          </span>
                        )) : null
                      } catch {
                        return <span className="lang-badge">{application.job_offer.required_languages}</span>
                      }
                    })()}
                  </div>
                </div>
              )}
              <p><strong>Submitted:</strong> {new Date(application.submitted_at).toLocaleString()}</p>
              {application.cover_letter && (
                <div>
                  <strong>Cover Letter:</strong>
                  <div className="cover-letter">{application.cover_letter}</div>
                </div>
              )}
            </div>

            <div className="detail-section">
              <h3>
                <HiSparkles className="section-icon" />
                AI Evaluation
              </h3>
              <div className="status-row">
                <span>Overall Status: {getStatusBadge(application.ai_status, 'ai')}</span>
                <span>Score: {application.ai_score}/10</span>
              </div>

              {/* Dual Evaluation Display */}
              <div className="dual-evaluation">
                {/* Language Check Section */}
                <div className="evaluation-card language-check">
                  <h4>🌐 Language Check</h4>
                  {application.language_check ? (
                    <>
                      <div className={`check-result ${application.language_check.passed ? 'passed' : 'failed'}`}>
                        {application.language_check.passed ? '✅ Passed' : '❌ Failed'}
                      </div>
                      {application.language_check.languages_required && application.language_check.languages_required.length > 0 && (
                        <div className="language-details">
                          <p><strong>Required:</strong> {application.language_check.languages_required.join(', ')}</p>
                          {application.language_check.languages_found && application.language_check.languages_found.length > 0 && (
                            <p><strong>Found:</strong> {application.language_check.languages_found.join(', ')}</p>
                          )}
                          {application.language_check.languages_missing && application.language_check.languages_missing.length > 0 && (
                            <p className="missing"><strong>Missing:</strong> {application.language_check.languages_missing.join(', ')}</p>
                          )}
                        </div>
                      )}
                      <p className="reasoning">{application.language_check.reasoning}</p>
                    </>
                  ) : (
                    <p className="no-data">Language evaluation not available</p>
                  )}
                </div>

                {/* Job Fit Check Section */}
                <div className="evaluation-card job-fit-check">
                  <h4>💼 Job Fit Check</h4>
                  {application.job_fit_check ? (
                    <>
                      <div className={`check-result ${application.job_fit_check.status === 'approved' ? 'passed' : 'failed'}`}>
                        {application.job_fit_check.status === 'approved' ? '✅ Approved' : '❌ Rejected'}
                      </div>
                      <div className="score-breakdown">
                        <div><HiAcademicCap className="score-icon" /> Skills: {application.job_fit_check.skills_match || application.ai_skills_match}/10</div>
                        <div><HiClipboardDocumentCheck className="score-icon" /> Experience: {application.job_fit_check.experience_match || application.ai_experience_match}/10</div>
                        <div><HiDocumentText className="score-icon" /> Education: {application.job_fit_check.education_match || application.ai_education_match}/10</div>
                      </div>
                      <p className="reasoning">{application.job_fit_check.reasoning}</p>
                    </>
                  ) : (
                    <>
                      {/* Fallback to legacy fields if job_fit_check not available */}
                      <div className="score-breakdown">
                        <div><HiAcademicCap className="score-icon" /> Skills Match: {application.ai_skills_match}/10</div>
                        <div><HiClipboardDocumentCheck className="score-icon" /> Experience Match: {application.ai_experience_match}/10</div>
                        <div><HiDocumentText className="score-icon" /> Education Match: {application.ai_education_match}/10</div>
                      </div>
                    </>
                  )}
                </div>
              </div>

              {application.ai_reasoning && !application.language_check && !application.job_fit_check && (
                <div className="reasoning-box">
                  <strong>AI Reasoning:</strong>
                  <p>{application.ai_reasoning}</p>
                </div>
              )}
            </div>

            <div className="detail-section">
              <h3>
                <HiUserCircle className="section-icon" />
                HR Status
              </h3>
              <div className="status-row">
                Status: {getStatusBadge(application.hr_status, 'hr')}
              </div>
              {application.hr_override_reason && (
                <div className="reasoning-box">
                  <strong>Override Reason:</strong>
                  <p>{application.hr_override_reason}</p>
                </div>
              )}
            </div>

            {application.interviews && application.interviews.length > 0 && (
              <div className="detail-section">
                <h3>
                  <HiMicrophone className="section-icon" />
                  Interview Attempts ({application.interviews.length})
                </h3>
                <div className="interviews-list">
                  {application.interviews.map((interview, index) => (
                    <div key={interview.interview_id} className="interview-attempt">
                      <div className="interview-attempt-header">
                        <h4>Attempt #{index + 1}</h4>
                        <div className="interview-badges">
                          {getStatusBadge(interview.status, 'interview')}
                          {interview.recommendation && getStatusBadge(interview.recommendation, 'interview')}
                        </div>
                      </div>
                      <div className="interview-attempt-info">
                        <p><strong>Created:</strong> {new Date(interview.created_at).toLocaleString()}</p>
                        {interview.completed_at && (
                          <p><strong>Completed:</strong> {new Date(interview.completed_at).toLocaleString()}</p>
                        )}
                        {interview.has_recording && (
                          <p><strong>Recording:</strong> Available</p>
                        )}
                      </div>
                      {interview.assessment && (
                        <div className="interview-assessment">
                          <strong>Assessment:</strong>
                          <div className="assessment-box">
                            <pre>{interview.assessment}</pre>
                          </div>
                        </div>
                      )}
                      <div className="interview-actions">
                        <button
                          className="btn-view-interview"
                          onClick={async () => {
                            try {
                              const response = await authApi.get(`/admin/interviews/${interview.interview_id}`)
                              // Open interview details in a new modal or navigate
                              alert(`Interview ID: ${interview.interview_id}\nStatus: ${interview.status}\nView full details in Interviews section.`)
                            } catch (error) {
                              console.error('Error loading interview details:', error)
                              alert('Error loading interview details')
                            }
                          }}
                        >
                          View Full Details
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {application.cv_text && (
              <div className="detail-section">
                <h3>
                  <HiDocumentText className="section-icon" />
                  CV Text
                </h3>
                <div className="cv-text-box">
                  <pre>{application.cv_text.substring(0, 2000)}{application.cv_text.length > 2000 ? '...' : ''}</pre>
                </div>
              </div>
            )}
          </div>

          <div className="modal-actions">
            {application.ai_status === 'rejected' && application.hr_status === 'pending' && (
              <button className="btn-override" onClick={() => setShowOverrideModal(true)}>
                <HiCheckCircle className="icon" />
                <span>Override AI Decision</span>
              </button>
            )}
            <button className="btn-interview" onClick={() => setShowInterviewModal(true)}>
              <HiMicrophone className="icon" />
              <span>
                {application.interviews && application.interviews.length > 0
                  ? 'Create New Interview'
                  : 'Send Interview Invitation'}
              </span>
            </button>
            <button className="btn-select" onClick={handleSelect} disabled={loading}>
              <HiCheckCircle className="icon" />
              <span>Select Candidate</span>
            </button>
            <button className="btn-reject" onClick={handleReject} disabled={loading}>
              <HiXCircle className="icon" />
              <span>Reject</span>
            </button>
            <button className="btn-close" onClick={onClose}>
              <HiXMark className="icon" />
              <span>Close</span>
            </button>
          </div>
        </div>
      </div>

      {showOverrideModal && (
        <OverrideModal
          application={application}
          onClose={() => setShowOverrideModal(false)}
          onSuccess={onClose}
        />
      )}

      {showInterviewModal && (
        <InterviewInviteModal
          application={application}
          onClose={() => setShowInterviewModal(false)}
          onSuccess={onClose}
        />
      )}
    </>
  )
}

export default ApplicationDetailModal

