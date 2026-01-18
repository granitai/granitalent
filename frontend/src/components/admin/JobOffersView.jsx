import React, { useState, useEffect, useRef } from 'react'
import { HiPlus, HiPencil, HiTrash, HiArrowLeft, HiChevronDown } from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import JobOfferApplications from './JobOfferApplications'
import './JobOffersView.css'

// Common languages for interviews
const LANGUAGES = [
  'English',
  'French',
  'Spanish',
  'German',
  'Italian',
  'Portuguese',
  'Arabic',
  'Chinese',
  'Japanese',
  'Korean',
  'Russian',
  'Dutch',
  'Swedish',
  'Norwegian',
  'Danish',
  'Finnish',
  'Polish',
  'Turkish',
  'Hindi',
  'Hebrew',
  'Greek',
  'Czech',
  'Hungarian',
  'Romanian',
  'Bulgarian',
  'Croatian',
  'Serbian',
  'Slovak',
  'Slovenian',
  'Ukrainian'
]

// Custom Dropdown Component
function CustomDropdown({ value, onChange, options, placeholder, disabled = false }) {
  const [isOpen, setIsOpen] = useState(false)
  const dropdownRef = useRef(null)

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false)
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  const selectedLabel = value ? options.find(opt => opt === value) : placeholder

  return (
    <div className="custom-dropdown" ref={dropdownRef}>
      <button
        type="button"
        className={`dropdown-button ${isOpen ? 'open' : ''}`}
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
      >
        <span className={!value ? 'placeholder' : ''}>{selectedLabel}</span>
        <HiChevronDown className={`dropdown-icon ${isOpen ? 'open' : ''}`} />
      </button>
      {isOpen && (
        <div className="dropdown-menu">
          <div className="dropdown-menu-content">
            {options.length === 0 ? (
              <div className="dropdown-item">No options available</div>
            ) : (
              options.map((option) => (
                <div
                  key={option}
                  className={`dropdown-item ${value === option ? 'selected' : ''}`}
                  onClick={() => {
                    onChange(option)
                    setIsOpen(false)
                  }}
                >
                  {option}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

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
    required_languages: [], // Array instead of JSON string
    selectedLanguage: '', // Temporary selection for adding languages
    interview_start_language: '',
    interview_duration_minutes: 20 // Default 20 minutes
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
      // Convert arrays to JSON strings for backend, exclude UI-only fields
      const { selectedLanguage, ...submitData } = formData
      submitData.required_languages = JSON.stringify(formData.required_languages)
      
      if (editingOffer) {
        await authApi.put(`/admin/job-offers/${editingOffer.offer_id}`, submitData)
        alert('Job offer updated successfully')
      } else {
        await authApi.post(`/admin/job-offers`, submitData)
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
        required_languages: [],
        selectedLanguage: '',
        interview_start_language: '',
        interview_duration_minutes: 20
      })
      loadJobOffers()
    } catch (error) {
      console.error('Error saving job offer:', error)
      alert('Error saving job offer')
    }
  }

  const handleEdit = (offer) => {
    setEditingOffer(offer)
    
    // Parse required_languages JSON string to array
    let requiredLanguagesArray = []
    if (offer.required_languages) {
      try {
        requiredLanguagesArray = JSON.parse(offer.required_languages)
        if (!Array.isArray(requiredLanguagesArray)) {
          requiredLanguagesArray = []
        }
      } catch (e) {
        console.error('Error parsing required_languages:', e)
        requiredLanguagesArray = []
      }
    }
    
    setFormData({
      title: offer.title,
      description: offer.description,
      required_skills: offer.required_skills || '',
      experience_level: offer.experience_level || '',
      education_requirements: offer.education_requirements || '',
      required_languages: requiredLanguagesArray,
      selectedLanguage: '',
      interview_start_language: offer.interview_start_language || '',
      interview_duration_minutes: offer.interview_duration_minutes || 20
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
            required_languages: [],
            interview_start_language: '',
            interview_duration_minutes: 20
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
              <label>Required Languages</label>
              <div className="language-selector">
                <div className="language-select-row">
                  <CustomDropdown
                    value={formData.selectedLanguage}
                    onChange={(value) => setFormData({ ...formData, selectedLanguage: value })}
                    options={LANGUAGES.filter(lang => !formData.required_languages.includes(lang))}
                    placeholder="Select a language..."
                  />
                  <button
                    type="button"
                    className="add-language-btn"
                    onClick={() => {
                      if (formData.selectedLanguage && !formData.required_languages.includes(formData.selectedLanguage)) {
                        setFormData({
                          ...formData,
                          required_languages: [...formData.required_languages, formData.selectedLanguage],
                          selectedLanguage: ''
                        })
                      }
                    }}
                    disabled={!formData.selectedLanguage}
                  >
                    Add
                  </button>
                </div>
                {formData.required_languages.length > 0 && (
                  <div className="selected-languages">
                    {formData.required_languages.map((lang, index) => (
                      <span key={index} className="language-tag">
                        {lang}
                        <button
                          type="button"
                          className="remove-language-btn"
                          onClick={() => {
                            setFormData({
                              ...formData,
                              required_languages: formData.required_languages.filter((_, i) => i !== index)
                            })
                          }}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <small>Select a language and click "Add" to add it to the required languages list</small>
            </div>
            <div className="form-group">
              <label>Interview Start Language</label>
              <CustomDropdown
                value={formData.interview_start_language}
                onChange={(value) => setFormData({ ...formData, interview_start_language: value })}
                options={LANGUAGES}
                placeholder="Select a language..."
              />
              <small>The language the AI interviewer should start the interview with</small>
            </div>
            <div className="form-group">
              <label>Interview Duration (minutes)</label>
              <input
                type="number"
                min="5"
                max="120"
                value={formData.interview_duration_minutes || 20}
                onChange={(e) => setFormData({ ...formData, interview_duration_minutes: parseInt(e.target.value) || 20 })}
              />
              <small>How long the interview should last (5-120 minutes, default: 20)</small>
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
                  required_languages: [],
                  interview_start_language: '',
                  interview_duration_minutes: 20
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

