import React, { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import axios from 'axios'
import {
    HiMicrophone,
    HiBriefcase,
    HiClock,
    HiCheckCircle,
    HiPlay,
    HiArrowRight,
    HiEnvelope,
    HiCalendarDays,
    HiSparkles,
    HiVideoCamera
} from 'react-icons/hi2'
import './CentralizedPortal.css'

const API_BASE_URL = '/api'

function CentralizedPortal() {
    const navigate = useNavigate()
    const [searchParams, setSearchParams] = useSearchParams()
    const [email, setEmail] = useState(searchParams.get('email') || '')
    const [interviews, setInterviews] = useState([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')
    const [searched, setSearched] = useState(false)

    // Initialize from URL param if present
    useEffect(() => {
        const emailParam = searchParams.get('email')
        if (emailParam) {
            setEmail(emailParam)
            loadInterviews(emailParam)
        }
    }, []) // Run once on mount

    const loadInterviews = async (emailToSearch) => {
        const searchEmail = emailToSearch || email
        if (!searchEmail.trim()) {
            setError('Please enter your email address')
            return
        }

        try {
            setLoading(true)
            setError('')
            const response = await axios.get(`${API_BASE_URL}/candidates/interviews`, {
                params: { email: searchEmail.trim() }
            })

            setInterviews(response.data)
            setSearched(true)

            if (response.data.length === 0) {
                setError('No available interviews found for this email address.')
            } else {
                // Update URL with email so refreshing works
                setSearchParams({ email: searchEmail.trim() })
            }
        } catch (err) {
            console.error('Error loading interviews:', err)
            if (err.response?.status === 404) {
                setError('No interviews found for this email address. Please check and try again.')
            } else {
                setError('Unable to load interviews. Please try again later.')
            }
            setInterviews([])
            setSearched(true)
        } finally {
            setLoading(false)
        }
    }

    const handleStartInterview = (interview) => {
        const interviewMode = interview.job_offer?.interview_mode || interview.interview_mode || 'realtime'
        const emailEncoded = encodeURIComponent(email.trim())

        // Redirect based on interview type
        if (interviewMode === 'asynchronous') {
            navigate(`/interview/async?interview_id=${interview.interview_id}&email=${emailEncoded}`)
        } else {
            // Realtime
            navigate(`/interview/realtime?interview_id=${interview.interview_id}&email=${emailEncoded}`)
        }
    }

    const handleViewDetails = (interview) => {
        // For now, view details can just re-open the interview page which usually handles "completed" state
        // Or we could create a dedicated details modal.
        // To keep it simple and centralized, let's just use the same link,
        // as the interview pages should handle "Completed" state by showing summary/results.
        const interviewMode = interview.job_offer?.interview_mode || interview.interview_mode || 'realtime'
        const emailEncoded = encodeURIComponent(email.trim())

        if (interviewMode === 'asynchronous') {
            navigate(`/interview/async?interview_id=${interview.interview_id}&email=${emailEncoded}`)
        } else {
            navigate(`/interview/realtime?interview_id=${interview.interview_id}&email=${emailEncoded}`)
        }
    }

    return (
        <div className="centralized-portal">
            <div className="centralized-background">
                <div className="centralized-orb orb-1"></div>
                <div className="centralized-orb orb-2"></div>
            </div>

            <div className="centralized-container">
                <header className="centralized-header">
                    <div className="brand-badge">
                        <HiSparkles />
                        <span>AI Talent Platform</span>
                    </div>
                    <h1>My Applications</h1>
                    <p>Manage all your AI interviews in one place</p>
                </header>

                <section className="centralized-search">
                    <div className="input-group">
                        <div className="input-icon">
                            <HiEnvelope />
                        </div>
                        <input
                            type="email"
                            placeholder="Enter your email address"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            onKeyPress={(e) => e.key === 'Enter' && loadInterviews()}
                        />
                        <button
                            className="search-btn"
                            onClick={() => loadInterviews()}
                            disabled={loading}
                        >
                            {loading ? 'Searching...' : 'Find My Applications'}
                            {!loading && <HiArrowRight />}
                        </button>
                    </div>
                    {error && (
                        <div className="error-message">
                            <HiMicrophone />
                            {error}
                        </div>
                    )}
                </section>

                {searched && interviews.length > 0 && (
                    <section className="interviews-section">
                        <div className="section-title">
                            <HiBriefcase />
                            <h2>Available Interviews</h2>
                            <span className="count-badge">{interviews.length}</span>
                        </div>

                        <div className="interviews-grid">
                            {interviews.map((interview) => {
                                const isAsync = (interview.job_offer?.interview_mode || interview.interview_mode) === 'asynchronous'
                                const isCompleted = interview.status === 'completed'

                                return (
                                    <div key={interview.interview_id} className="interview-card">
                                        <div className="card-content">
                                            <div className="card-header">
                                                <div className={`mode-badge ${isAsync ? 'async' : 'realtime'}`}>
                                                    {isAsync ? <HiVideoCamera /> : <HiMicrophone />}
                                                    {isAsync ? 'Asynchronous' : 'Real-time'}
                                                </div>
                                                <div className={`status-indicator ${isCompleted ? 'completed' : ''}`}>
                                                    {isCompleted ? 'Completed' : 'Pending'}
                                                </div>
                                            </div>

                                            <h3 className="job-title">{interview.job_offer.title}</h3>
                                            <p className="company-name">AI Interview Request</p>
                                        </div>

                                        <div className="card-footer">
                                            <div className="date">
                                                <HiCalendarDays />
                                                {new Date(interview.created_at).toLocaleDateString()}
                                            </div>

                                            <button
                                                className={`action-btn ${isCompleted ? 'view' : 'start'}`}
                                                onClick={() => isCompleted ? handleViewDetails(interview) : handleStartInterview(interview)}
                                            >
                                                {isCompleted ? 'View Details' : 'Start Interview'}
                                                {isCompleted ? <HiCheckCircle /> : <HiPlay />}
                                            </button>
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    </section>
                )}
            </div>
        </div>
    )
}

export default CentralizedPortal
