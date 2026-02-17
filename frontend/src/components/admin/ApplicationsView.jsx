import React, { useState, useEffect } from 'react'
import { HiArrowPath, HiEye, HiArchiveBox, HiArchiveBoxXMark } from 'react-icons/hi2'
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
    search: '',
    date_from: '',
    date_to: '',
    date_preset: 'all',
    show_archived: false
  })
  const [jobOffers, setJobOffers] = useState([])
  const [selectedApplication, setSelectedApplication] = useState(null)
  const [showDetailModal, setShowDetailModal] = useState(false)

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
      if (filters.date_from) params.append('date_from', filters.date_from)
      if (filters.date_to) params.append('date_to', filters.date_to)
      if (filters.show_archived) params.append('show_archived', 'true')

      const response = await authApi.get(`/admin/applications?${params}`)
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
      const response = await authApi.get(`/admin/job-offers`)
      setJobOffers(response.data)
    } catch (error) {
      console.error('Error loading job offers:', error)
    }
  }

  const handleFilterChange = (key, value) => {
    // If changing custom date, clear preset
    if (key === 'date_from' || key === 'date_to') {
      setFilters(prev => ({ ...prev, [key]: value, date_preset: 'custom' }))
    } else {
      setFilters(prev => ({ ...prev, [key]: value }))
    }
  }

  const handleArchiveApplication = async (applicationId, isArchived) => {
    try {
      const action = isArchived ? 'unarchive' : 'archive'
      await authApi.post(`/admin/applications/${applicationId}/${action}`)

      // Update locally instead of reloading to preserve scroll position
      if (isArchived) {
        // Unarchiving - update the item's archived status
        setApplications(prev => prev.map(app =>
          app.application_id === applicationId
            ? { ...app, is_archived: false, archived_at: null }
            : app
        ))
      } else {
        // Archiving - either remove from list or update status based on filter
        if (filters.show_archived) {
          // If showing archived, just update the status
          setApplications(prev => prev.map(app =>
            app.application_id === applicationId
              ? { ...app, is_archived: true, archived_at: new Date().toISOString() }
              : app
          ))
        } else {
          // If not showing archived, remove from list
          setApplications(prev => prev.filter(app => app.application_id !== applicationId))
        }
      }
    } catch (error) {
      console.error(`Error ${isArchived ? 'unarchiving' : 'archiving'} application:`, error)
      alert(`Failed to ${isArchived ? 'restore' : 'archive'} application`)
    }
  }

  const handleViewDetails = async (applicationId) => {
    try {
      const response = await authApi.get(`/admin/applications/${applicationId}`)
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
        <button onClick={loadApplications} className="refresh-btn" title="Refresh">
          <HiArrowPath className="icon" />
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
          <span>Show Archived Applications</span>
        </label>
      </div>

      <div className={`applications-list ${viewMode === 'row' ? 'row-view' : 'card-view'}`}>
        {/* Table Header for Row View */}
        {viewMode === 'row' && applications.length > 0 && (
          <div className="table-header-row">
            <div className="th-cell">Name</div>
            <div className="th-cell">Status</div>
            <div className="th-cell">Email</div>
            <div className="th-cell">Job</div>
            <div className="th-cell">Actions</div>
          </div>
        )}
        {applications.length === 0 ? (
          <p className="no-results">No applications found</p>
        ) : (
          applications.map(app => (
            <div key={app.application_id} className={`application-card ${viewMode === 'row' ? 'row-layout' : ''}`}>
              {viewMode === 'row' ? (
                /* Row View - Values Only */
                <>
                  <div className="row-cell name-cell">
                    <span className="candidate-name">{app.candidate.full_name}</span>
                  </div>
                  <div className="row-cell status-cell">
                    <div className="status-badges">
                      {getStatusBadge(app.ai_status, 'ai')}
                      {getStatusBadge(app.hr_status, 'hr')}
                    </div>
                  </div>
                  <div className="row-cell">{app.candidate.email}</div>
                  <div className="row-cell">{app.job_offer.title}</div>
                  <div className="row-cell actions-cell">
                    <button
                      className="view-btn icon-only"
                      onClick={() => handleViewDetails(app.application_id)}
                      title="View Details"
                    >
                      <HiEye className="icon" />
                    </button>
                    <button
                      className={`archive-btn icon-only ${app.is_archived ? 'unarchive' : ''}`}
                      onClick={() => handleArchiveApplication(app.application_id, app.is_archived)}
                      title={app.is_archived ? 'Restore' : 'Archive'}
                    >
                      {app.is_archived ? <HiArchiveBoxXMark className="icon" /> : <HiArchiveBox className="icon" />}
                    </button>
                  </div>
                </>
              ) : (
                /* Card View - Original with Labels */
                <>
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
                    <button
                      className={`archive-btn ${app.is_archived ? 'unarchive' : ''}`}
                      onClick={() => handleArchiveApplication(app.application_id, app.is_archived)}
                      title={app.is_archived ? 'Restore Application' : 'Archive Application'}
                    >
                      {app.is_archived ? <HiArchiveBoxXMark className="icon" /> : <HiArchiveBox className="icon" />}
                    </button>
                  </div>
                </>
              )}
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

