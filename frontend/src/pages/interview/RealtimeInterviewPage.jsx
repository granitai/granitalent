import React, { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import axios from 'axios'
import InterviewInterface from '../../components/InterviewInterface'
import { Loader2, ArrowLeft, CheckCircle } from 'lucide-react'

const API_BASE_URL = '/api'

export default function RealtimeInterviewPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [interview, setInterview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [alreadyCompleted, setAlreadyCompleted] = useState(false)

  const interviewId = searchParams.get('interview_id')
  const email = searchParams.get('email')

  useEffect(() => {
    if (!interviewId || !email) {
      setError('Missing interview ID or email.')
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
      if (response.data.status === 'completed' || response.data.status === 'in_progress') {
        setAlreadyCompleted(true)
        setLoading(false)
        return
      }
      setInterview({ ...response.data, interview_id: interviewId, email: email.trim() })
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load interview.')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
      </div>
    )
  }

  if (alreadyCompleted) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4">
        <div className="card p-8 text-center max-w-md">
          <CheckCircle className="mx-auto h-12 w-12 text-emerald-500" />
          <h2 className="mt-4 text-xl font-semibold text-slate-900">Interview Already Completed</h2>
          <p className="mt-2 text-sm text-slate-500">This interview has already been completed. Thank you for your participation!</p>
          <button onClick={() => navigate(`/my-applications?email=${encodeURIComponent(email)}`)} className="btn-secondary mt-6">
            <ArrowLeft className="h-4 w-4" /> Back to Portal
          </button>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4">
        <div className="card p-8 text-center max-w-md">
          <p className="text-lg font-medium text-red-600">{error}</p>
          <button onClick={() => navigate('/my-applications')} className="btn-secondary mt-6">
            <ArrowLeft className="h-4 w-4" /> Back to Portal
          </button>
        </div>
      </div>
    )
  }

  return (
    <InterviewInterface
      interview={interview}
      onClose={() => navigate(`/my-applications?email=${encodeURIComponent(email)}`)}
    />
  )
}
