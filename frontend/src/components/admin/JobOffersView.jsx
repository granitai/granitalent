import React, { useState, useEffect, useRef } from 'react'
import { HiPlus, HiPencil, HiTrash, HiChevronDown, HiXMark, HiArrowRight, HiArrowLeft, HiCheck, HiBriefcase, HiLanguage, HiCog6Tooth, HiEye, HiClipboardDocumentList } from 'react-icons/hi2'
import { useAuth } from '../../contexts/AuthContext'
import JobOfferApplications from './JobOfferApplications'
import './JobOffersView.css'

// Evaluation categories that recruiters can prioritize
const EVALUATION_CATEGORIES = [
  { key: 'technical_skills', label: 'Technical Skills', description: 'Technical knowledge and abilities' },
  { key: 'communication', label: 'Communication', description: 'Clarity, articulation, and expression' },
  { key: 'problem_solving', label: 'Problem Solving', description: 'Analytical and logical thinking' },
  { key: 'language_proficiency', label: 'Language Proficiency', description: 'Fluency in required languages' },
  { key: 'job_fit', label: 'Job Fit', description: 'Alignment with role requirements' },
  { key: 'experience', label: 'Experience', description: 'Relevant work experience' },
  { key: 'cultural_fit', label: 'Cultural Fit', description: 'Values and team compatibility' },
  { key: 'motivation', label: 'Motivation', description: 'Interest and enthusiasm for the role' }
]

// Common languages for interviews
const LANGUAGES = [
  'English', 'French', 'Spanish', 'German', 'Italian', 'Portuguese', 'Arabic',
  'Chinese', 'Japanese', 'Korean', 'Russian', 'Dutch', 'Swedish', 'Norwegian',
  'Danish', 'Finnish', 'Polish', 'Turkish', 'Hindi', 'Hebrew', 'Greek', 'Czech',
  'Hungarian', 'Romanian', 'Bulgarian', 'Croatian', 'Serbian', 'Slovak', 'Slovenian', 'Ukrainian'
]

// Step configuration
const FORM_STEPS = [
  { id: 1, title: 'Job Details', icon: HiBriefcase, description: 'Basic information about the position' },
  { id: 2, title: 'Interview Setup', icon: HiLanguage, description: 'Language and duration settings' },
  { id: 3, title: 'AI Configuration', icon: HiCog6Tooth, description: 'Questions and evaluation priorities' }
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

// Step Progress Indicator Component
function StepIndicator({ currentStep, steps }) {
  return (
    <div className="step-indicator">
      {steps.map((step, index) => {
        const StepIcon = step.icon
        const isCompleted = currentStep > step.id
        const isCurrent = currentStep === step.id

        return (
          <React.Fragment key={step.id}>
            <div className={`step ${isCompleted ? 'completed' : ''} ${isCurrent ? 'current' : ''}`}>
              <div className="step-circle">
                {isCompleted ? <HiCheck /> : <StepIcon />}
              </div>
              <div className="step-info">
                <span className="step-title">{step.title}</span>
                <span className="step-description">{step.description}</span>
              </div>
            </div>
            {index < steps.length - 1 && (
              <div className={`step-connector ${currentStep > step.id ? 'completed' : ''}`} />
            )}
          </React.Fragment>
        )
      })}
    </div>
  )
}

// Job Offer Form Wizard Component
function JobOfferFormWizard({ editingOffer, formData, setFormData, onSubmit, onCancel }) {
  const [currentStep, setCurrentStep] = useState(1)
  const [errors, setErrors] = useState({})
  const submitButtonClicked = useRef(false)

  // Reset submit flag whenever step changes
  useEffect(() => {
    submitButtonClicked.current = false
  }, [currentStep])

  const validateStep = (step) => {
    const newErrors = {}

    if (step === 1) {
      if (!formData.title?.trim()) {
        newErrors.title = 'Job title is required'
      }
      if (!formData.description?.trim()) {
        newErrors.description = 'Description is required'
      }
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleNext = () => {
    if (validateStep(currentStep)) {
      setCurrentStep(prev => Math.min(prev + 1, 3))
    }
  }

  const handleBack = () => {
    setCurrentStep(prev => Math.max(prev - 1, 1))
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    e.stopPropagation()

    // Only allow submission if:
    // 1. We're on the final step (step 3)
    // 2. The submit button was explicitly clicked
    if (currentStep !== 3 || !submitButtonClicked.current) {
      // If not on final step or button wasn't clicked, prevent submission
      submitButtonClicked.current = false
      return
    }

    // Reset the flag
    submitButtonClicked.current = false

    // Validate final step before submitting
    if (validateStep(currentStep)) {
      onSubmit(e)
    }
  }

  const handleSubmitButtonClick = (e) => {
    // Mark that the submit button was clicked
    submitButtonClicked.current = true
    // The form's onSubmit will handle the actual submission
  }

  return (
    <div className="form-wizard-overlay">
      <div className="form-wizard">
        <div className="wizard-header">
          <h2>{editingOffer ? 'Edit Job Offer' : 'Create New Job Offer'}</h2>
          <button type="button" className="close-wizard-btn" onClick={onCancel}>
            <HiXMark />
          </button>
        </div>

        <StepIndicator currentStep={currentStep} steps={FORM_STEPS} />

        <form
          onSubmit={handleSubmit}
          onKeyDown={(e) => {
            // Prevent Enter key from submitting form unless submit button was clicked
            if (e.key === 'Enter' && e.target.type !== 'submit' && e.target.tagName !== 'BUTTON') {
              // Allow Enter in textareas for new lines
              if (e.target.tagName === 'TEXTAREA') {
                return // Allow default behavior for textareas
              }
              // For other inputs, prevent form submission
              if (currentStep !== 3) {
                e.preventDefault()
              } else if (currentStep === 3 && !submitButtonClicked.current) {
                // On step 3, only allow Enter if submit button was clicked
                e.preventDefault()
              }
            }
          }}
        >
          <div className="wizard-content">
            {/* Step 1: Job Details */}
            {currentStep === 1 && (
              <div className="wizard-step step-1">
                <div className="step-header">
                  <h3>Tell us about the position</h3>
                  <p>Provide the essential details about this job offer</p>
                </div>

                <div className="form-group">
                  <label>Job Title <span className="required">*</span></label>
                  <input
                    type="text"
                    value={formData.title || ''}
                    onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                    placeholder="e.g., Senior Software Engineer"
                    className={errors.title ? 'error' : ''}
                  />
                  {errors.title && <span className="error-message">{errors.title}</span>}
                </div>

                <div className="form-group">
                  <label>Description <span className="required">*</span></label>
                  <textarea
                    value={formData.description || ''}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    placeholder="Describe the role, responsibilities, and what you're looking for..."
                    rows="4"
                    className={errors.description ? 'error' : ''}
                  />
                  {errors.description && <span className="error-message">{errors.description}</span>}
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Required Skills</label>
                    <textarea
                      value={formData.required_skills || ''}
                      onChange={(e) => setFormData({ ...formData, required_skills: e.target.value })}
                      placeholder="List the key skills needed..."
                      rows="3"
                    />
                  </div>

                  <div className="form-group">
                    <label>Education Requirements</label>
                    <textarea
                      value={formData.education_requirements || ''}
                      onChange={(e) => setFormData({ ...formData, education_requirements: e.target.value })}
                      placeholder="Required education or certifications..."
                      rows="3"
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label>Experience Level</label>
                  <input
                    type="text"
                    value={formData.experience_level || ''}
                    onChange={(e) => setFormData({ ...formData, experience_level: e.target.value })}
                    placeholder="e.g., 3-5 years, Entry Level, Senior"
                  />
                </div>
              </div>
            )}

            {/* Step 2: Interview Setup */}
            {currentStep === 2 && (
              <div className="wizard-step step-2">
                <div className="step-header">
                  <h3>Configure the interview</h3>
                  <p>Set up language requirements and interview duration</p>
                </div>

                <div className="form-group">
                  <label>Required Languages</label>
                  <p className="field-hint">Which languages should the candidate be proficient in?</p>
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
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label>Interview Start Language</label>
                    <p className="field-hint">Which language should the AI start the interview with?</p>
                    <CustomDropdown
                      value={formData.interview_start_language}
                      onChange={(value) => setFormData({ ...formData, interview_start_language: value })}
                      options={LANGUAGES}
                      placeholder="Select a language..."
                    />
                  </div>

                  <div className="form-group">
                    <label>Interview Duration</label>
                    <p className="field-hint">How long should the interview last?</p>
                    <div className="duration-input">
                      <input
                        type="number"
                        min="5"
                        max="120"
                        value={formData.interview_duration_minutes || 20}
                        onChange={(e) => setFormData({ ...formData, interview_duration_minutes: parseInt(e.target.value) || 20 })}
                      />
                      <span className="duration-suffix">minutes</span>
                    </div>
                  </div>
                </div>

                <div className="form-group">
                  <label>Interview Mode</label>
                  <p className="field-hint">Choose how the interview will be conducted</p>
                  <div className="interview-mode-selector">
                    <button
                      type="button"
                      className={`mode-btn ${formData.interview_mode === "realtime" || !formData.interview_mode ? 'active' : ''}`}
                      onClick={() => setFormData({ ...formData, interview_mode: 'realtime' })}
                    >
                      <span className="mode-icon">⚡</span>
                      <span className="mode-label">Real-time</span>
                    </button>
                    <button
                      type="button"
                      className={`mode-btn ${formData.interview_mode === "asynchronous" ? 'active' : ''}`}
                      onClick={() => setFormData({ ...formData, interview_mode: 'asynchronous' })}
                    >
                      <span className="mode-icon">🎙️</span>
                      <span className="mode-label">Asynchronous</span>
                    </button>
                  </div>
                  {formData.interview_mode === "asynchronous" && (
                    <p className="mode-description">Push-to-talk: candidate records answers (1 min max, 3 retries per question)</p>
                  )}
                  {(!formData.interview_mode || formData.interview_mode === "realtime") && (
                    <p className="mode-description">Interactive conversation with live audio streaming</p>
                  )}
                </div>
              </div>
            )}

            {/* Step 3: AI Configuration */}
            {currentStep === 3 && (
              <div className="wizard-step step-3">
                <div className="step-header">
                  <h3>Customize the AI interviewer</h3>
                  <p>Add custom questions and set evaluation priorities</p>
                </div>

                <div className="form-group">
                  <label>Custom Interview Questions</label>
                  <p className="field-hint">Add specific questions you want the AI to ask. Leave empty to let the AI generate questions automatically.</p>
                  <div className="custom-questions-section">
                    <div className="question-input-row">
                      <input
                        type="text"
                        value={formData.newQuestion || ''}
                        onChange={(e) => setFormData({ ...formData, newQuestion: e.target.value })}
                        placeholder="Type a question and press Enter or click Add..."
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            if (formData.newQuestion.trim()) {
                              setFormData({
                                ...formData,
                                custom_questions: [...formData.custom_questions, formData.newQuestion.trim()],
                                newQuestion: ''
                              })
                            }
                          }
                        }}
                      />
                      <button
                        type="button"
                        className="add-question-btn"
                        onClick={() => {
                          if (formData.newQuestion.trim()) {
                            setFormData({
                              ...formData,
                              custom_questions: [...formData.custom_questions, formData.newQuestion.trim()],
                              newQuestion: ''
                            })
                          }
                        }}
                        disabled={!formData.newQuestion?.trim()}
                      >
                        Add
                      </button>
                    </div>
                    {formData.custom_questions.length > 0 && (
                      <div className="questions-list">
                        {formData.custom_questions.map((question, index) => (
                          <div key={index} className="question-item">
                            <span className="question-number">{index + 1}.</span>
                            <span className="question-text">{question}</span>
                            <button
                              type="button"
                              className="remove-question-btn"
                              onClick={() => {
                                setFormData({
                                  ...formData,
                                  custom_questions: formData.custom_questions.filter((_, i) => i !== index)
                                })
                              }}
                            >
                              <HiXMark />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                <div className="form-group">
                  <label>Evaluation Priorities</label>
                  <p className="field-hint">
                    Adjust the importance of each area. Higher values mean the AI will focus more on that aspect.
                  </p>
                  <div className="evaluation-weights-section">
                    <div className="weights-grid">
                      {EVALUATION_CATEGORIES.map((category) => (
                        <div key={category.key} className="weight-item">
                          <div className="weight-header">
                            <label>{category.label}</label>
                            <span className="weight-value">
                              {formData.evaluation_weights[category.key] || 0}
                            </span>
                          </div>
                          <input
                            type="range"
                            min="0"
                            max="10"
                            value={formData.evaluation_weights[category.key] || 0}
                            onChange={(e) => {
                              const newWeights = { ...formData.evaluation_weights }
                              const value = parseInt(e.target.value)
                              if (value === 0) {
                                delete newWeights[category.key]
                              } else {
                                newWeights[category.key] = value
                              }
                              setFormData({ ...formData, evaluation_weights: newWeights })
                            }}
                            className={`weight-slider ${formData.evaluation_weights[category.key] >= 7 ? 'high-priority' : formData.evaluation_weights[category.key] >= 4 ? 'medium-priority' : ''}`}
                          />
                          <small>{category.description}</small>
                        </div>
                      ))}
                    </div>
                    {Object.keys(formData.evaluation_weights).filter(k => formData.evaluation_weights[k] > 0).length > 0 && (
                      <div className="weights-summary">
                        <strong>Active Priorities:</strong>
                        {Object.entries(formData.evaluation_weights)
                          .filter(([_, v]) => v > 0)
                          .sort(([, a], [, b]) => b - a)
                          .map(([key, value]) => {
                            const category = EVALUATION_CATEGORIES.find(c => c.key === key)
                            return (
                              <span key={key} className={`weight-badge ${value >= 7 ? 'high' : value >= 4 ? 'medium' : 'low'}`}>
                                {category?.label}: {value}
                              </span>
                            )
                          })
                        }
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="wizard-footer">
            <div className="footer-left">
              {currentStep > 1 && (
                <button type="button" className="btn-back" onClick={handleBack}>
                  <HiArrowLeft />
                  <span>Back</span>
                </button>
              )}
            </div>
            <div className="footer-right">
              <button type="button" className="btn-cancel" onClick={onCancel}>
                Cancel
              </button>
              {currentStep < 3 ? (
                <button type="button" className="btn-next" onClick={handleNext}>
                  <span>Next</span>
                  <HiArrowRight />
                </button>
              ) : (
                <button
                  type="submit"
                  className="btn-submit"
                  onClick={handleSubmitButtonClick}
                >
                  <HiCheck />
                  <span>{editingOffer ? 'Update' : 'Create'} Job Offer</span>
                </button>
              )}
            </div>
          </div>
        </form>
      </div>
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
    required_languages: [],
    selectedLanguage: '',
    interview_start_language: '',
    interview_duration_minutes: 20,
    interview_mode: 'realtime',
    custom_questions: [],
    newQuestion: '',
    evaluation_weights: {}
  })

  const resetFormData = () => ({
    title: '',
    description: '',
    required_skills: '',
    experience_level: '',
    education_requirements: '',
    required_languages: [],
    selectedLanguage: '',
    interview_start_language: '',
    interview_duration_minutes: 20,
    interview_mode: 'realtime',
    custom_questions: [],
    newQuestion: '',
    evaluation_weights: {}
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
      const { selectedLanguage, newQuestion, ...submitData } = formData
      submitData.required_languages = JSON.stringify(formData.required_languages)
      submitData.custom_questions = JSON.stringify(formData.custom_questions)
      submitData.interview_mode = formData.interview_mode || 'realtime' // Ensure interview_mode is included
      const filteredWeights = Object.fromEntries(
        Object.entries(formData.evaluation_weights).filter(([_, v]) => v > 0)
      )
      submitData.evaluation_weights = Object.keys(filteredWeights).length > 0
        ? JSON.stringify(filteredWeights)
        : ""

      console.log('Submitting job offer with interview_mode:', submitData.interview_mode)

      if (editingOffer) {
        await authApi.put(`/admin/job-offers/${editingOffer.offer_id}`, submitData)
        alert('Job offer updated successfully')
      } else {
        await authApi.post(`/admin/job-offers`, submitData)
        alert('Job offer created successfully')
      }
      setShowForm(false)
      setEditingOffer(null)
      setFormData(resetFormData())
      loadJobOffers()
    } catch (error) {
      console.error('Error saving job offer:', error)
      alert('Error saving job offer')
    }
  }

  const handleEdit = (offer) => {
    setEditingOffer(offer)

    let requiredLanguagesArray = []
    if (offer.required_languages) {
      try {
        requiredLanguagesArray = JSON.parse(offer.required_languages)
        if (!Array.isArray(requiredLanguagesArray)) requiredLanguagesArray = []
      } catch (e) {
        requiredLanguagesArray = []
      }
    }

    let customQuestionsArray = []
    if (offer.custom_questions) {
      try {
        customQuestionsArray = JSON.parse(offer.custom_questions)
        if (!Array.isArray(customQuestionsArray)) customQuestionsArray = []
      } catch (e) {
        customQuestionsArray = []
      }
    }

    let evaluationWeightsObj = {}
    if (offer.evaluation_weights) {
      try {
        evaluationWeightsObj = JSON.parse(offer.evaluation_weights)
        if (typeof evaluationWeightsObj !== 'object' || Array.isArray(evaluationWeightsObj)) {
          evaluationWeightsObj = {}
        }
      } catch (e) {
        evaluationWeightsObj = {}
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
      interview_duration_minutes: offer.interview_duration_minutes || 20,
      interview_mode: offer.interview_mode || 'realtime',
      custom_questions: customQuestionsArray,
      newQuestion: '',
      evaluation_weights: evaluationWeightsObj
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

  const handleCancel = () => {
    setShowForm(false)
    setEditingOffer(null)
    setFormData(resetFormData())
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
          setFormData(resetFormData())
        }}>
          <HiPlus className="icon" />
          <span>Create New Job Offer</span>
        </button>
      </div>

      {showForm && (
        <JobOfferFormWizard
          editingOffer={editingOffer}
          formData={formData}
          setFormData={setFormData}
          onSubmit={handleSubmit}
          onCancel={handleCancel}
        />
      )}

      <div className={`job-offers-list ${viewMode === 'row' ? 'row-view' : 'card-view'}`}>
        {/* Table Header for Row View */}
        {viewMode === 'row' && jobOffers.length > 0 && (
          <div className="table-header-row">
            <div className="th-cell">Title</div>
            <div className="th-cell">Description</div>
            <div className="th-cell">Skills</div>
            <div className="th-cell">Actions</div>
          </div>
        )}
        {jobOffers.length === 0 ? (
          <p className="no-results">No job offers yet. Create one to get started!</p>
        ) : (
          jobOffers.map(offer => (
            <div key={offer.offer_id} className={`job-offer-card ${viewMode === 'row' ? 'row-layout' : ''}`}>
              {viewMode === 'row' ? (
                /* Row View - Values Only */
                <>
                  <div className="row-cell title-cell">
                    <span className="job-title">{offer.title}</span>
                  </div>
                  <div className="row-cell description-cell">
                    {offer.description.substring(0, 100)}...
                  </div>
                  <div className="row-cell">{offer.required_skills || '-'}</div>
                  <div className="row-cell actions-cell">
                    <button className="view-apps-btn icon-only" onClick={() => setSelectedOffer(offer)} title="View Applications">
                      <HiEye className="icon" />
                    </button>
                    <button className="edit-btn icon-only" onClick={() => handleEdit(offer)} title="Edit">
                      <HiPencil className="icon" />
                    </button>
                    <button className="delete-btn icon-only" onClick={() => handleDelete(offer.offer_id)} title="Delete">
                      <HiTrash className="icon" />
                    </button>
                  </div>
                </>
              ) : (
                /* Card View - Original with Labels */
                <>
                  <div className="card-content">
                    <h3>{offer.title}</h3>
                    <p className="description">{offer.description.substring(0, 200)}...</p>
                    {offer.required_skills && (
                      <p><strong>Skills:</strong> {offer.required_skills}</p>
                    )}
                  </div>
                  <div className="card-actions">
                    <button className="view-apps-btn" onClick={() => setSelectedOffer(offer)} title="View Applications">
                      <HiEye className="icon" />
                    </button>
                    <button className="edit-btn" onClick={() => handleEdit(offer)} title="Edit">
                      <HiPencil className="icon" />
                    </button>
                    <button className="delete-btn" onClick={() => handleDelete(offer.offer_id)} title="Delete">
                      <HiTrash className="icon" />
                    </button>
                  </div>
                </>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default JobOffersView
