import React, { useState, useEffect } from 'react'
import { HiArrowLeft, HiArrowPath, HiCheckCircle, HiXCircle, HiClock } from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import ApplicationDetailModal from './ApplicationDetailModal'
import './JobOfferApplications.css'

function JobOfferApplications({ jobOffer, onBack, onRefresh }) {
  const { authApi } = useAuth()
  const [applications, setApplications] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedApplication, setSelectedApplication] = useState(null)
  const [showDetailModal, setShowDetailModal] = useState(false)

  useEffect(() => {
    loadApplications()
  }, [jobOffer.offer_id])

  const loadApplications = async () => {
    try {
      setLoading(true)
      const response = await authApi.get(`/api/admin/job-offers/${jobOffer.offer_id}/applications`)
      setApplications(response.data)
    } catch (error) {
      console.error('Error loading applications:', error)
      alert('Error loading applications')
    } finally {
      setLoading(false)
    }
  }

  const handleViewDetails = async (applicationId) => {
    try {
      const response = await authApi.get(`/api/admin/applications/${applicationId}`)
      setSelectedApplication(response.data)
      setShowDetailModal(true)
    } catch (error) {
      console.error('Error loading application details:', error)
      alert('Error loading application details')
    }
  }

  const getStatusBadge = (status) => {
    const colors = {
      approved: { bg: 'rgba(0, 212, 170, 0.2)', color: '#00d4aa', border: '#00d4aa' },
      rejected: { bg: 'rgba(255, 68, 68, 0.2)', color: '#ff4444', border: '#ff4444' },
      pending: { bg: 'rgba(160, 174, 192, 0.2)', color: '#a0aec0', border: '#a0aec0' }
    }
    const style = colors[status] || colors.pending
    return (
      <span className="status-badge" style={style}>
        {status}
      </span>
    )
  }

  if (loading) {
    return <div className="loading">Loading applications...</div>
  }

  return (
    <div className="job-offer-applications">
      <div className="view-header">
        <button className="back-btn" onClick={onBack}>
          <HiArrowLeft className="icon" />
          <span>Back to Job Offers</span>
        </button>
        <h2>{jobOffer.title} - Applications</h2>
        <button className="refresh-btn" onClick={loadApplications}>
          <HiArrowPath className="icon" />
          <span>Refresh</span>
        </button>
      </div>

      <div className="applications-sections">
        <div className="section approved">
          <h3>
            <HiCheckCircle className="section-icon" />
            AI Pre-Selected ({applications.approved.length})
          </h3>
          <p className="section-description">Candidates approved by AI with detailed reasoning</p>
          <div className="applications-list">
            {applications.approved.map(app => (
              <div key={app.application_id} className="application-card approved">
                <div className="card-header">
                  <h4>{app.candidate.full_name}</h4>
                  {getStatusBadge(app.ai_status)}
                </div>
                <p><strong>Email:</strong> {app.candidate.email}</p>
                <div className="ai-reasoning">
                  <strong>AI Reasoning:</strong>
                  <p>{app.ai_reasoning}</p>
                </div>
                <button className="view-btn" onClick={() => handleViewDetails(app.application_id)}>
                  View Details
                </button>
              </div>
            ))}
            {applications.approved.length === 0 && (
              <p className="empty-section">No approved candidates</p>
            )}
          </div>
        </div>

        <div className="section rejected">
          <h3>
            <HiXCircle className="section-icon" />
            AI Rejected ({applications.rejected.length})
          </h3>
          <p className="section-description">Candidates rejected by AI with detailed reasoning</p>
          <div className="applications-list">
            {applications.rejected.map(app => (
              <div key={app.application_id} className="application-card rejected">
                <div className="card-header">
                  <h4>{app.candidate.full_name}</h4>
                  {getStatusBadge(app.ai_status)}
                </div>
                <p><strong>Email:</strong> {app.candidate.email}</p>
                <div className="ai-reasoning">
                  <strong>AI Reasoning:</strong>
                  <p>{app.ai_reasoning}</p>
                </div>
                <button className="view-btn" onClick={() => handleViewDetails(app.application_id)}>
                  View Details & Override
                </button>
              </div>
            ))}
            {applications.rejected.length === 0 && (
              <p className="empty-section">No rejected candidates</p>
            )}
          </div>
        </div>

        <div className="section pending">
          <h3>
            <HiClock className="section-icon" />
            Pending ({applications.pending.length})
          </h3>
          <p className="section-description">Applications pending AI evaluation</p>
          <div className="applications-list">
            {applications.pending.map(app => (
              <div key={app.application_id} className="application-card pending">
                <div className="card-header">
                  <h4>{app.candidate.full_name}</h4>
                  {getStatusBadge(app.ai_status)}
                </div>
                <p><strong>Email:</strong> {app.candidate.email}</p>
                <button className="view-btn" onClick={() => handleViewDetails(app.application_id)}>
                  View Details
                </button>
              </div>
            ))}
            {applications.pending.length === 0 && (
              <p className="empty-section">No pending applications</p>
            )}
          </div>
        </div>
      </div>

      {showDetailModal && selectedApplication && (
        <ApplicationDetailModal
          application={selectedApplication}
          onClose={() => {
            setShowDetailModal(false)
            setSelectedApplication(null)
            loadApplications()
            onRefresh()
          }}
        />
      )}
    </div>
  )
}

export default JobOfferApplications

