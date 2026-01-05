import React, { useState } from 'react'
import { HiXMark } from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import './Modal.css'

function OverrideModal({ application, onClose, onSuccess }) {
  const { authApi } = useAuth()
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    
    try {
      setLoading(true)
      await authApi.post(
        `/api/admin/applications/${application.application_id}/override`,
        {
          hr_status: 'selected',
          reason: reason
        }
      )
      alert('AI decision overridden successfully')
      onSuccess()
    } catch (error) {
      console.error('Error overriding decision:', error)
      alert('Error overriding decision')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Override AI Decision</h2>
          <button className="close-btn" onClick={onClose}>
            <HiXMark />
          </button>
        </div>

        <div className="modal-body">
          <p>The AI has <strong>rejected</strong> this candidate, but you can override this decision.</p>
          
          <div className="ai-reasoning-box">
            <strong>AI Reasoning:</strong>
            <p>{application.ai_reasoning}</p>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label>Override Reason (optional)</label>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Explain why you're overriding the AI decision..."
                rows="4"
              />
            </div>

            <div className="form-actions">
              <button type="submit" className="btn-primary" disabled={loading}>
                {loading ? 'Processing...' : 'Override & Select Candidate'}
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

export default OverrideModal

