import React, { useState } from 'react'
import { HiXMark } from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import './Modal.css'

function InterviewInviteModal({ application, onClose, onSuccess }) {
  const { authApi } = useAuth()
  const [interviewDate, setInterviewDate] = useState('')
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    
    try {
      setLoading(true)
      await authApi.post(
        `/admin/applications/${application.application_id}/send-interview`,
        {
          interview_date: interviewDate || null,
          notes: notes
        }
      )
      alert('Interview invitation sent successfully')
      onSuccess()
    } catch (error) {
      console.error('Error sending interview invitation:', error)
      alert('Error sending interview invitation')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Send Interview Invitation</h2>
          <button className="close-btn" onClick={onClose}>
            <HiXMark />
          </button>
        </div>

        <div className="modal-body">
          <p>Send an interview invitation to <strong>{application.candidate.full_name}</strong></p>
          {application.interviews && application.interviews.length > 0 && (
            <div className="existing-interviews-notice">
              <p><strong>Note:</strong> This candidate has {application.interviews.length} existing interview attempt(s).</p>
              <p className="text-muted">Creating a new interview will add a new attempt. Previous interviews and their assessments will be preserved.</p>
            </div>
          )}
          <p className="text-muted">Email integration will be added later. For now, this updates the application status.</p>

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label>Interview Date (optional)</label>
              <input
                type="datetime-local"
                value={interviewDate}
                onChange={(e) => setInterviewDate(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>Notes (optional)</label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Additional notes for the interview invitation..."
                rows="4"
              />
            </div>

            <div className="form-actions">
              <button type="submit" className="btn-primary" disabled={loading}>
                {loading ? 'Sending...' : 'Send Interview Invitation'}
              </button>
              <button type="button" className="btn-secondary" onClick={onClose}>
                Cancel
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

export default InterviewInviteModal

