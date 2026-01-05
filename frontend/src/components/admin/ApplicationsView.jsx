import React, { useState, useEffect } from 'react'
import { HiArrowPath, HiEye } from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import ApplicationDetailModal from './ApplicationDetailModal'
import './ApplicationsView.css'

function ApplicationsView({ viewMode = 'card' }) {
  const { authApi } = useAuth()
  const [applications, setApplications] = useState([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({
    job_offer_id: '',
    ai_status: '',
    hr_status: '',
    search: ''
  })
  const [jobOffers, setJobOffers] = useState([])
  const [selectedApplication, setSelectedApplication] = useState(null)
  const [showDetailModal, setShowDetailModal] = useState(false)

  useEffect(() => {
    loadApplications()
    loadJobOffers()
  }, [filters])

  const loadApplications = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams()
      if (filters.job_offer_id) params.append('job_offer_id', filters.job_offer_id)
      if (filters.ai_status) params.append('ai_status', filters.ai_status)
      if (filters.hr_status) params.append('hr_status', filters.hr_status)
      if (filters.search) params.append('search', filters.search)

      const response = await authApi.get(`/api/admin/applications?${params}`)
      setApplications(response.data)
    } catch (error) {
      console.error('Error loading applications:', error)
      alert('Error loading applications')
    } finally {
      setLoading(false)
    }
  }

  const loadJobOffers = async () => {
    try {
      const response = await authApi.get(`/api/admin/job-offers`)
      setJobOffers(response.data)
    } catch (error) {
      console.error('Error loading job offers:', error)
    }
  }

  const handleFilterChange = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }))
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

  const getStatusBadge = (status, type) => {
    const colors = {
      approved: { bg: 'rgba(0, 212, 170, 0.2)', color: '#00d4aa', border: '#00d4aa' },
      rejected: { bg: 'rgba(255, 68, 68, 0.2)', color: '#ff4444', border: '#ff4444' },
      pending: { bg: 'rgba(160, 174, 192, 0.2)', color: '#a0aec0', border: '#a0aec0' },
      selected: { bg: 'rgba(108, 99, 255, 0.2)', color: '#6c63ff', border: '#6c63ff' },
      interview_sent: { bg: 'rgba(255, 193, 7, 0.2)', color: '#ffc107', border: '#ffc107' }
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
    <div className="applications-view">
      <div className="view-header">
        <h2>Applications</h2>
        <button onClick={loadApplications} className="refresh-btn">
          <HiArrowPath className="icon" />
          <span>Refresh</span>
        </button>
      </div>

      <div className="filters">
        <div className="filter-group">
          <label>Search</label>
          <input
            type="text"
            placeholder="Search by name or email..."
            value={filters.search}
            onChange={(e) => handleFilterChange('search', e.target.value)}
          />
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
        <div className="filter-group">
          <label>AI Status</label>
          <select
            value={filters.ai_status}
            onChange={(e) => handleFilterChange('ai_status', e.target.value)}
          >
            <option value="">All</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="pending">Pending</option>
          </select>
        </div>
        <div className="filter-group">
          <label>HR Status</label>
          <select
            value={filters.hr_status}
            onChange={(e) => handleFilterChange('hr_status', e.target.value)}
          >
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="selected">Selected</option>
            <option value="rejected">Rejected</option>
            <option value="interview_sent">Interview Sent</option>
          </select>
        </div>
      </div>

      <div className={`applications-list ${viewMode === 'row' ? 'row-view' : 'card-view'}`}>
        {applications.length === 0 ? (
          <p className="no-results">No applications found</p>
        ) : (
          applications.map(app => (
            <div key={app.application_id} className={`application-card ${viewMode === 'row' ? 'row-layout' : ''}`}>
              <div className="card-header">
                <h3>{app.candidate.full_name}</h3>
                <div className="status-badges">
                  {getStatusBadge(app.ai_status, 'ai')}
                  {getStatusBadge(app.hr_status, 'hr')}
                </div>
              </div>
              <div className="card-body">
                <p><strong>Email:</strong> {app.candidate.email}</p>
                <p><strong>Job:</strong> {app.job_offer.title}</p>
                {app.ai_reasoning && (
                  <p className="ai-reasoning">
                    <strong>AI Reasoning:</strong> {app.ai_reasoning.substring(0, 150)}...
                  </p>
                )}
              </div>
              <div className="card-actions">
                <button
                  className="view-btn"
                  onClick={() => handleViewDetails(app.application_id)}
                >
                  <HiEye className="icon" />
                  <span>View Details</span>
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {showDetailModal && selectedApplication && (
        <ApplicationDetailModal
          application={selectedApplication}
          onClose={() => {
            setShowDetailModal(false)
            setSelectedApplication(null)
            loadApplications()
          }}
        />
      )}
    </div>
  )
}

export default ApplicationsView

