import React, { useState, useEffect } from 'react'
import { HiPlus, HiPencil, HiTrash, HiArrowLeft } from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import JobOfferApplications from './JobOfferApplications'
import './JobOffersView.css'

function JobOffersView({ viewMode = 'card' }) {
  const { authApi } = useAuth()
  const [jobOffers, setJobOffers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingOffer, setEditingOffer] = useState(null)
  const [selectedOffer, setSelectedOffer] = useState(null)
  const [formData, setFormData] = useState({
    title: '',
    description: '',
    required_skills: '',
    experience_level: '',
    education_requirements: '',
    required_languages: '',
    interview_start_language: ''
  })

  useEffect(() => {
    loadJobOffers()
  }, [])

  const loadJobOffers = async () => {
    try {
      setLoading(true)
      const response = await authApi.get(`/admin/job-offers`)
      setJobOffers(response.data)
    } catch (error) {
      console.error('Error loading job offers:', error)
      alert('Error loading job offers')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    try {
      if (editingOffer) {
        await authApi.put(`/admin/job-offers/${editingOffer.offer_id}`, formData)
        alert('Job offer updated successfully')
      } else {
        await authApi.post(`/admin/job-offers`, formData)
        alert('Job offer created successfully')
      }
      setShowForm(false)
      setEditingOffer(null)
      setFormData({
        title: '',
        description: '',
        required_skills: '',
        experience_level: '',
        education_requirements: '',
        required_languages: '',
        interview_start_language: ''
      })
      loadJobOffers()
    } catch (error) {
      console.error('Error saving job offer:', error)
      alert('Error saving job offer')
    }
  }

  const handleEdit = (offer) => {
    setEditingOffer(offer)
    setFormData({
      title: offer.title,
      description: offer.description,
      required_skills: offer.required_skills || '',
      experience_level: offer.experience_level || '',
      education_requirements: offer.education_requirements || '',
      required_languages: offer.required_languages || '',
      interview_start_language: offer.interview_start_language || ''
    })
    setShowForm(true)
  }

  const handleDelete = async (offerId) => {
    if (!confirm('Are you sure you want to delete this job offer?')) return

    try {
      await authApi.delete(`/admin/job-offers/${offerId}`)
      alert('Job offer deleted successfully')
      loadJobOffers()
    } catch (error) {
      console.error('Error deleting job offer:', error)
      alert('Error deleting job offer')
    }
  }

  if (loading) {
    return <div className="loading">Loading job offers...</div>
  }

  if (selectedOffer) {
    return (
      <JobOfferApplications
        jobOffer={selectedOffer}
        onBack={() => setSelectedOffer(null)}
        onRefresh={loadJobOffers}
      />
    )
  }

  return (
    <div className="job-offers-view">
      <div className="view-header">
        <h2>Job Offers</h2>
        <button className="create-btn" onClick={() => {
          setShowForm(true)
          setEditingOffer(null)
          setFormData({
            title: '',
            description: '',
            required_skills: '',
            experience_level: '',
            education_requirements: '',
            required_languages: '',
            interview_start_language: ''
          })
        }}>
          <HiPlus className="icon" />
          <span>Create New Job Offer</span>
        </button>
      </div>

      {showForm && (
        <div className="form-container">
          <h3>{editingOffer ? 'Edit' : 'Create'} Job Offer</h3>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label>Job Title *</label>
              <input
                type="text"
                value={formData.title || ''}
                onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                required
              />
            </div>
            <div className="form-group">
              <label>Description *</label>
              <textarea
                value={formData.description || ''}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                required
                rows="5"
              />
            </div>
            <div className="form-group">
              <label>Required Skills</label>
              <textarea
                value={formData.required_skills || ''}
                onChange={(e) => setFormData({ ...formData, required_skills: e.target.value })}
                rows="3"
              />
            </div>
            <div className="form-group">
              <label>Experience Level</label>
              <input
                type="text"
                value={formData.experience_level || ''}
                onChange={(e) => setFormData({ ...formData, experience_level: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Education Requirements</label>
              <textarea
                value={formData.education_requirements || ''}
                onChange={(e) => setFormData({ ...formData, education_requirements: e.target.value })}
                rows="3"
              />
            </div>
            <div className="form-group">
              <label>Required Languages (JSON array, e.g., ["English", "French"])</label>
              <input
                type="text"
                value={formData.required_languages || ''}
                onChange={(e) => setFormData({ ...formData, required_languages: e.target.value })}
                placeholder='["English", "French"]'
              />
              <small>Enter languages as a JSON array. Example: ["English", "French", "Spanish"]</small>
            </div>
            <div className="form-group">
              <label>Interview Start Language</label>
              <input
                type="text"
                value={formData.interview_start_language || ''}
                onChange={(e) => setFormData({ ...formData, interview_start_language: e.target.value })}
                placeholder="English"
              />
              <small>The language the AI interviewer should start the interview with</small>
            </div>
            <div className="form-actions">
              <button type="submit" className="btn-primary">Save</button>
              <button type="button" className="btn-secondary" onClick={() => {
                setShowForm(false)
                setEditingOffer(null)
                setFormData({
                  title: '',
                  description: '',
                  required_skills: '',
                  experience_level: '',
                  education_requirements: '',
                  required_languages: '',
                  interview_start_language: ''
                })
              }}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      <div className={`job-offers-list ${viewMode === 'row' ? 'row-view' : 'card-view'}`}>
        {jobOffers.length === 0 ? (
          <p className="no-results">No job offers yet. Create one to get started!</p>
        ) : (
          jobOffers.map(offer => (
            <div key={offer.offer_id} className={`job-offer-card ${viewMode === 'row' ? 'row-layout' : ''}`}>
              <div className="card-content">
                <h3>{offer.title}</h3>
                <p className="description">{offer.description.substring(0, viewMode === 'row' ? 300 : 200)}...</p>
                {offer.required_skills && (
                  <p><strong>Skills:</strong> {offer.required_skills}</p>
                )}
              </div>
              <div className="card-actions">
                <button className="view-apps-btn" onClick={() => setSelectedOffer(offer)}>
                  View Applications
                </button>
                <button className="edit-btn" onClick={() => handleEdit(offer)}>
                  <HiPencil className="icon" />
                  <span>Edit</span>
                </button>
                <button className="delete-btn" onClick={() => handleDelete(offer.offer_id)}>
                  <HiTrash className="icon" />
                  <span>Delete</span>
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default JobOffersView

