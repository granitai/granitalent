import React, { useState, useEffect } from 'react'
import axios from 'axios'
import { useNavigate } from 'react-router-dom'
import { HiBriefcase, HiCheckCircle, HiXCircle, HiClock, HiDocumentArrowUp, HiXMark, HiDocumentText, HiEye } from 'react-icons/hi2'
import './CandidatePortal.css'

// Utiliser une URL relative qui sera gérée par Nginx en production
// et par le proxy Vite en développement
const API_BASE_URL = '/api'

function CandidatePortal() {
  const navigate = useNavigate()
  const [jobOffers, setJobOffers] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedOffer, setSelectedOffer] = useState(null)
  const [showDetailsModal, setShowDetailsModal] = useState(false)
  const [showApplicationModal, setShowApplicationModal] = useState(false)
  const [applicationForm, setApplicationForm] = useState({
    full_name: '',
    email: '',
    phone: '',
    linkedin: '',
    portfolio: '',
    cover_letter_file: null,
    cv_file: null
  })
  const [submitting, setSubmitting] = useState(false)
  const [successMessage, setSuccessMessage] = useState('')
  const [dragActive, setDragActive] = useState({ cv: false, coverLetter: false })

  useEffect(() => {
    loadJobOffers()
  }, [])

  const loadJobOffers = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/job-offers`)
      setJobOffers(response.data)
    } catch (error) {
      console.error('Error loading job offers:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleViewDetails = (offer) => {
    setSelectedOffer(offer)
    setShowDetailsModal(true)
  }

  const handleApply = (offer) => {
    setSelectedOffer(offer)
    setShowDetailsModal(false)
    setShowApplicationModal(true)
  }

  const handleFileChange = (e, field) => {
    const file = e.target.files[0]
    if (file) {
      setApplicationForm({
        ...applicationForm,
        [field]: file
      })
    }
  }

  const handleDrag = (e, field) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive({ ...dragActive, [field]: true })
    } else if (e.type === "dragleave") {
      setDragActive({ ...dragActive, [field]: false })
    }
  }

  const handleDrop = (e, field) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive({ ...dragActive, [field]: false })
    
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0]
      // Validate file type
      if (field === 'cv_file' && !file.name.toLowerCase().endsWith('.pdf')) {
        alert('Please upload a PDF file for CV')
        return
      }
      if (field === 'cover_letter_file' && !file.name.toLowerCase().endsWith('.pdf') && !file.name.toLowerCase().endsWith('.doc') && !file.name.toLowerCase().endsWith('.docx')) {
        alert('Please upload a PDF, DOC, or DOCX file for cover letter')
        return
      }
      setApplicationForm({
        ...applicationForm,
        [field]: file
      })
    }
  }

  const handleInputChange = (e) => {
    setApplicationForm({
      ...applicationForm,
      [e.target.name]: e.target.value
    })
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    
    // Custom validation for CV file since the input is hidden
    if (!applicationForm.cv_file) {
      alert('Please upload your CV (PDF)')
      return
    }
    
    setSubmitting(true)

    const formData = new FormData()
    formData.append('job_offer_id', selectedOffer.offer_id)
    formData.append('full_name', applicationForm.full_name)
    formData.append('email', applicationForm.email)
    formData.append('phone', applicationForm.phone)
    formData.append('linkedin', applicationForm.linkedin || '')
    formData.append('portfolio', applicationForm.portfolio || '')
    if (applicationForm.cover_letter_file) {
      formData.append('cover_letter_file', applicationForm.cover_letter_file)
    }
    formData.append('cv_file', applicationForm.cv_file)

    try {
      const response = await axios.post(`${API_BASE_URL}/candidates/apply`, formData)
      setSuccessMessage('Application submitted successfully!')
      setShowApplicationModal(false)
      setApplicationForm({
        full_name: '',
        email: '',
        phone: '',
        linkedin: '',
        portfolio: '',
        cover_letter_file: null,
        cv_file: null
      })
      setTimeout(() => setSuccessMessage(''), 3000)
    } catch (error) {
      alert('Error submitting application: ' + (error.response?.data?.detail || error.message))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <div className="loading">Loading job offers...</div>
  }

  return (
    <div className="candidate-portal">
      <div className="portal-header">
        <div className="header-content">
          <div>
            <h1>Available Job Opportunities</h1>
            <p>Browse and apply to job offers that match your skills</p>
          </div>
          <button 
            className="dashboard-btn"
            onClick={() => navigate('/dashboard')}
            title="View my applications and interviews"
          >
            <HiDocumentText className="icon" />
            <span>My Applications</span>
          </button>
        </div>
      </div>

      {successMessage && (
        <div className="success-message">
          {successMessage}
        </div>
      )}

      <div className="job-offers-grid">
        {jobOffers.length === 0 ? (
          <p className="no-offers">No job offers available at the moment.</p>
        ) : (
          jobOffers.map(offer => (
            <div key={offer.offer_id} className="job-offer-card">
              <div className="job-offer-card-header">
                <h3>{offer.title}</h3>
              </div>
              <div className="job-offer-card-body">
                <p className="description">
                  {offer.description.substring(0, 150)}
                  {offer.description.length > 150 ? '...' : ''}
                </p>
                <div className="job-offer-card-meta">
                  {offer.required_skills && (
                    <div className="skills">
                      <strong>Skills</strong>
                      {offer.required_skills.includes(',') || offer.required_skills.includes(';') ? (
                        <div className="skills-tags">
                          {offer.required_skills.split(/[,;]/).filter(s => s.trim()).slice(0, 4).map((skill, idx) => (
                            <span key={idx} className="skill-tag">
                              {skill.trim()}
                            </span>
                          ))}
                          {offer.required_skills.split(/[,;]/).filter(s => s.trim()).length > 4 && (
                            <span className="skill-tag">
                              +{offer.required_skills.split(/[,;]/).filter(s => s.trim()).length - 4} more
                            </span>
                          )}
                        </div>
                      ) : (
                        <p className="skills-text">{offer.required_skills}</p>
                      )}
                    </div>
                  )}
                  {offer.experience_level && (
                    <div className="experience">
                      <strong>Experience</strong>
                      <span className="experience-badge">
                        {offer.experience_level}
                      </span>
                    </div>
                  )}
                </div>
              </div>
              <div className="job-offer-card-footer">
                <div className="card-actions">
                  <button 
                    className="view-details-btn"
                    onClick={() => handleViewDetails(offer)}
                  >
                    <HiEye className="icon" />
                    <span>View Details</span>
                  </button>
                  <button 
                    className="apply-btn"
                    onClick={() => handleApply(offer)}
                  >
                    <HiDocumentArrowUp className="icon" />
                    <span>Apply Now</span>
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {showDetailsModal && selectedOffer && (
        <div className="modal-overlay" onClick={() => setShowDetailsModal(false)}>
          <div className="modal-content details-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{selectedOffer.title}</h2>
              <button 
                className="close-btn"
                onClick={() => setShowDetailsModal(false)}
                aria-label="Close"
              >
                <HiXMark />
              </button>
            </div>
            
            <div className="offer-details">
              <div className="detail-section">
                <h3>Job Description</h3>
                <p className="detail-content">{selectedOffer.description}</p>
              </div>

              {selectedOffer.required_skills && (
                <div className="detail-section">
                  <h3>Required Skills</h3>
                  <p className="detail-content">{selectedOffer.required_skills}</p>
                </div>
              )}

              {selectedOffer.experience_level && (
                <div className="detail-section">
                  <h3>Experience Level</h3>
                  <p className="detail-content">{selectedOffer.experience_level}</p>
                </div>
              )}

              {selectedOffer.education_requirements && (
                <div className="detail-section">
                  <h3>Education Requirements</h3>
                  <p className="detail-content">{selectedOffer.education_requirements}</p>
                </div>
              )}

              {selectedOffer.required_languages && (
                <div className="detail-section">
                  <h3>Required Languages</h3>
                  <p className="detail-content">{selectedOffer.required_languages}</p>
                </div>
              )}

              {selectedOffer.created_at && (
                <div className="detail-section">
                  <h3>Posted Date</h3>
                  <p className="detail-content">
                    {new Date(selectedOffer.created_at).toLocaleDateString('en-US', {
                      year: 'numeric',
                      month: 'long',
                      day: 'numeric'
                    })}
                  </p>
                </div>
              )}
            </div>

            <div className="modal-actions">
              <button 
                className="apply-btn"
                onClick={() => handleApply(selectedOffer)}
              >
                <HiDocumentArrowUp className="icon" />
                <span>Apply Now</span>
              </button>
              <button 
                className="cancel-btn"
                onClick={() => setShowDetailsModal(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {showApplicationModal && (
        <div className="modal-overlay" onClick={() => setShowApplicationModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h2>Apply for {selectedOffer?.title}</h2>
            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label>Full Name *</label>
                <input
                  type="text"
                  name="full_name"
                  value={applicationForm.full_name}
                  onChange={handleInputChange}
                  required
                />
              </div>
              <div className="form-group">
                <label>Email *</label>
                <input
                  type="email"
                  name="email"
                  value={applicationForm.email}
                  onChange={handleInputChange}
                  required
                />
              </div>
              <div className="form-group">
                <label>Phone *</label>
                <input
                  type="tel"
                  name="phone"
                  value={applicationForm.phone}
                  onChange={handleInputChange}
                  required
                />
              </div>
              <div className="form-group">
                <label>LinkedIn (optional)</label>
                <input
                  type="url"
                  name="linkedin"
                  value={applicationForm.linkedin}
                  onChange={handleInputChange}
                />
              </div>
              <div className="form-group">
                <label>Portfolio (optional)</label>
                <input
                  type="url"
                  name="portfolio"
                  value={applicationForm.portfolio}
                  onChange={handleInputChange}
                />
              </div>
              <div className="form-group">
                <label>Cover Letter (optional - PDF, DOC, DOCX)</label>
                <div
                  className={`file-upload-area ${dragActive.coverLetter ? 'drag-active' : ''} ${applicationForm.cover_letter_file ? 'has-file' : ''}`}
                  onDragEnter={(e) => handleDrag(e, 'coverLetter')}
                  onDragLeave={(e) => handleDrag(e, 'coverLetter')}
                  onDragOver={(e) => handleDrag(e, 'coverLetter')}
                  onDrop={(e) => handleDrop(e, 'cover_letter_file')}
                >
                  <input
                    type="file"
                    accept=".pdf,.doc,.docx"
                    onChange={(e) => handleFileChange(e, 'cover_letter_file')}
                    style={{ display: 'none' }}
                    id="cover_letter_file"
                  />
                  <label htmlFor="cover_letter_file" className="file-upload-label">
                    {applicationForm.cover_letter_file ? (
                      <>
                        <HiDocumentArrowUp className="icon" />
                        <span>{applicationForm.cover_letter_file.name}</span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.preventDefault()
                            setApplicationForm({ ...applicationForm, cover_letter_file: null })
                          }}
                          className="remove-file-btn"
                        >
                          <HiXMark />
                        </button>
                      </>
                    ) : (
                      <>
                        <HiDocumentArrowUp className="icon" />
                        <span>Click to upload or drag and drop</span>
                        <small>PDF, DOC, or DOCX (max 10MB)</small>
                      </>
                    )}
                  </label>
                </div>
              </div>
              <div className="form-group">
                <label>CV (PDF) *</label>
                <div
                  className={`file-upload-area ${dragActive.cv ? 'drag-active' : ''} ${applicationForm.cv_file ? 'has-file' : ''}`}
                  onDragEnter={(e) => handleDrag(e, 'cv')}
                  onDragLeave={(e) => handleDrag(e, 'cv')}
                  onDragOver={(e) => handleDrag(e, 'cv')}
                  onDrop={(e) => handleDrop(e, 'cv_file')}
                >
                  <input
                    type="file"
                    accept=".pdf"
                    onChange={(e) => handleFileChange(e, 'cv_file')}
                    style={{ display: 'none' }}
                    id="cv_file"
                  />
                  <label htmlFor="cv_file" className="file-upload-label">
                    {applicationForm.cv_file ? (
                      <>
                        <HiDocumentArrowUp className="icon" />
                        <span>{applicationForm.cv_file.name}</span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.preventDefault()
                            setApplicationForm({ ...applicationForm, cv_file: null })
                          }}
                          className="remove-file-btn"
                        >
                          <HiXMark />
                        </button>
                      </>
                    ) : (
                      <>
                        <HiDocumentArrowUp className="icon" />
                        <span>Click to upload or drag and drop</span>
                        <small>PDF only (max 10MB)</small>
                      </>
                    )}
                  </label>
                </div>
              </div>
              <div className="form-actions">
                <button type="submit" disabled={submitting} className="submit-btn">
                  {submitting ? 'Submitting...' : 'Submit Application'}
                </button>
                <button 
                  type="button" 
                  onClick={() => setShowApplicationModal(false)}
                  className="cancel-btn"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default CandidatePortal

