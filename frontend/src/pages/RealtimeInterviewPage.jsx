import React, { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import axios from 'axios'
import InterviewInterface from '../components/InterviewInterface'
import './InterviewPortal.css' // Reusing existing styles for now or we can create specific ones

const API_BASE_URL = '/api'

function RealtimeInterviewPage() {
    const navigate = useNavigate()
    const [searchParams] = useSearchParams()
    const [interview, setInterview] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')

    const interviewId = searchParams.get('interview_id')
    const email = searchParams.get('email')

    useEffect(() => {
        if (!interviewId || !email) {
            setError('Missing interview ID or email. Please access this page from the portal.')
            setLoading(false)
            return
        }

        loadInterview()
    }, [interviewId, email])

    const loadInterview = async () => {
        try {
            setLoading(true)
            setError('')

            const response = await axios.get(`${API_BASE_URL}/candidates/interviews/${interviewId}`, {
                params: { email: email.trim() }
            })

            setInterview({
                ...response.data,
                interview_id: interviewId,
                email: email.trim()
                // We generally don't need to force interview_mode here as InterviewInterface handles logic based on the object
            })
        } catch (err) {
            console.error('Error loading interview:', err)
            setError(err.response?.data?.detail || 'Failed to load interview. Please try again.')
        } finally {
            setLoading(false)
        }
    }

    if (loading) {
        return (
            <div className="interview-portal">
                <div className="portal-header">
                    <h1>Loading Interview...</h1>
                </div>
            </div>
        )
    }

    if (error) {
        return (
            <div className="interview-portal">
                <div className="portal-header">
                    <h1>Error</h1>
                </div>
                <div className="error-message">{error}</div>
                <button onClick={() => navigate('/my-applications')} className="start-btn">
                    Back to Portal
                </button>
            </div>
        )
    }

    return (
        <InterviewInterface
            interview={interview}
            onClose={() => {
                // Navigate back to the centralized portal
                navigate(`/my-applications?email=${encodeURIComponent(email)}`)
            }}
        />
    )
}

export default RealtimeInterviewPage
