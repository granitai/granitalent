import React, { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import axios from 'axios'
import InterviewInterface from '../../components/InterviewInterface'
import { Loader2, ArrowLeft } from 'lucide-react'

const API_BASE_URL = '/api'

export default function RealtimeInterviewPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [interview, setInterview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

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
      setInterview({ ...response.data, interview_id: interviewId, email: email.trim() })
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load interview.')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-900">
        <Loader2 className="h-8 w-8 animate-spin text-brand-400" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-900 px-4">
        <p className="text-lg text-red-400">{error}</p>
        <button onClick={() => navigate('/my-applications')} className="mt-4 flex items-center gap-2 rounded-lg bg-white/10 px-4 py-2 text-sm text-white hover:bg-white/20">
          <ArrowLeft className="h-4 w-4" /> Back to Portal
        </button>
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
