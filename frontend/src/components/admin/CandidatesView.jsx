import React, { useState, useEffect } from 'react'
import { HiMagnifyingGlass, HiEye, HiXMark } from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import './CandidatesView.css'

function CandidatesView({ viewMode = 'card' }) {
  const { authApi } = useAuth()
  const [candidates, setCandidates] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedCandidate, setSelectedCandidate] = useState(null)

  useEffect(() => {
    loadCandidates()
  }, [search])

  const loadCandidates = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams()
      if (search) params.append('search', search)

      const response = await authApi.get(`/admin/candidates?${params}`)
      setCandidates(response.data)
    } catch (error) {
      console.error('Error loading candidates:', error)
      alert('Error loading candidates')
    } finally {
      setLoading(false)
    }
  }

  const handleViewCandidate = async (email) => {
    try {
      const response = await authApi.get(`/admin/candidates/${email}`)
      setSelectedCandidate(response.data)
    } catch (error) {
      console.error('Error loading candidate details:', error)
      alert('Error loading candidate details')
    }
  }

  if (loading) {
    return <div className="loading">Loading candidates...</div>
  }

  return (
    <div className="candidates-view">
      <div className="view-header">
        <h2>Candidate Archive</h2>
        <div className="search-box">
          <HiMagnifyingGlass className="search-icon" />
          <input
            type="text"
            placeholder="Search by name or email..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div className={`candidates-list ${viewMode === 'row' ? 'row-view' : 'card-view'}`}>
        {/* Table Header for Row View */}
        {viewMode === 'row' && candidates.length > 0 && (
          <div className="table-header-row">
            <div className="th-cell">Name</div>
            <div className="th-cell">Applications</div>
            <div className="th-cell">Email</div>
            <div className="th-cell">Phone</div>
            <div className="th-cell">Latest Application</div>
            <div className="th-cell">Actions</div>
          </div>
        )}
        {candidates.length === 0 ? (
          <p className="no-results">No candidates found</p>
        ) : (
          candidates.map(candidate => (
            <div key={candidate.candidate_id} className={`candidate-card ${viewMode === 'row' ? 'row-layout' : ''}`}>
              {viewMode === 'row' ? (
                /* Row View - Values Only */
                <>
                  <div className="row-cell name-cell">
                    <span className="candidate-name">{candidate.full_name}</span>
                  </div>
                  <div className="row-cell">
                    <span className="applications-count">{candidate.total_applications}</span>
                  </div>
                  <div className="row-cell">{candidate.email}</div>
                  <div className="row-cell">{candidate.phone || '-'}</div>
                  <div className="row-cell">{candidate.latest_application ? new Date(candidate.latest_application).toLocaleDateString() : '-'}</div>
                  <div className="row-cell actions-cell">
                    <button
                      className="view-btn"
                      onClick={() => handleViewCandidate(candidate.email)}
                    >
                      View All Applications
                    </button>
                  </div>
                </>
              ) : (
                /* Card View - Original with Labels */
                <>
                  <div className="card-header">
                    <h3>{candidate.full_name}</h3>
                    <span className="applications-count">{candidate.total_applications} application(s)</span>
                  </div>
                  <div className="card-body">
                    <p><strong>Email:</strong> {candidate.email}</p>
                    {candidate.phone && <p><strong>Phone:</strong> {candidate.phone}</p>}
                    {candidate.latest_application && (
                      <p><strong>Latest Application:</strong> {new Date(candidate.latest_application).toLocaleDateString()}</p>
                    )}
                  </div>
                  <div className="card-actions">
                    <button
                      className="view-btn"
                      onClick={() => handleViewCandidate(candidate.email)}
                    >
                      View All Applications
                    </button>
                  </div>
                </>
              )}
            </div>
          ))
        )}
      </div>

      {selectedCandidate && (
        <div className="modal-overlay" onClick={() => setSelectedCandidate(null)}>
          <div className="modal-content large" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{selectedCandidate.candidate.full_name}</h2>
              <button className="close-btn" onClick={() => setSelectedCandidate(null)}>
                <HiXMark />
              </button>
            </div>

            <div className="modal-body">
              <div className="detail-section">
                <h3>Candidate Information</h3>
                <div className="info-grid">
                  <div><strong>Email:</strong> {selectedCandidate.candidate.email}</div>
                  <div><strong>Phone:</strong> {selectedCandidate.candidate.phone || 'N/A'}</div>
                  {selectedCandidate.candidate.linkedin && (
                    <div><strong>LinkedIn:</strong> <a href={selectedCandidate.candidate.linkedin} target="_blank" rel="noopener noreferrer">{selectedCandidate.candidate.linkedin}</a></div>
                  )}
                  {selectedCandidate.candidate.portfolio && (
                    <div><strong>Portfolio:</strong> <a href={selectedCandidate.candidate.portfolio} target="_blank" rel="noopener noreferrer">{selectedCandidate.candidate.portfolio}</a></div>
                  )}
                </div>
              </div>

              <div className="detail-section">
                <h3>Applications ({selectedCandidate.applications.length})</h3>
                <div className="applications-list">
                  {selectedCandidate.applications.map(app => (
                    <div key={app.application_id} className="application-item">
                      <div className="app-header">
                        <h4>{app.job_offer.title}</h4>
                        <div className="status-badges">
                          <span className={`status-badge ${app.ai_status}`}>{app.ai_status}</span>
                          <span className={`status-badge ${app.hr_status}`}>{app.hr_status}</span>
                        </div>
                      </div>
                      <p><strong>Submitted:</strong> {new Date(app.submitted_at).toLocaleString()}</p>
                      {app.ai_reasoning && (
                        <p className="ai-reasoning">{app.ai_reasoning.substring(0, 100)}...</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="modal-actions">
              <button className="btn-close" onClick={() => setSelectedCandidate(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default CandidatesView

