import React, { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import axios from 'axios'
import StatusBadge from '../../components/shared/StatusBadge'
import EmptyState from '../../components/shared/EmptyState'
import { formatDate } from '../../lib/utils'
import { Mail, ArrowRight, Loader2, FolderOpen, Mic, Video, CheckCircle, Play, Calendar, Sparkles } from 'lucide-react'

export default function MyApplicationsPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [email, setEmail] = useState(searchParams.get('email') || '')
  const [interviews, setInterviews] = useState([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const e = searchParams.get('email')
    if (e) { setEmail(e); loadInterviews(e) }
  }, [])

  const loadInterviews = async (emailOverride) => {
    const searchEmail = (emailOverride || email).trim()
    if (!searchEmail) { setError('Please enter your email'); return }
    try {
      setLoading(true); setError('')
      const { data } = await axios.get('/api/candidates/interviews', { params: { email: searchEmail } })
      setInterviews(data); setSearched(true)
      if (data.length > 0) setSearchParams({ email: searchEmail })
      else setError('No interviews found for this email.')
    } catch (err) {
      setError(err.response?.status === 404 ? 'No interviews found.' : 'Unable to load. Please try again.')
      setInterviews([]); setSearched(true)
    } finally { setLoading(false) }
  }

  const handleStartInterview = (interview) => {
    const mode = interview.job_offer?.interview_mode || interview.interview_mode || 'realtime'
    const emailEnc = encodeURIComponent(email.trim())
    navigate(mode === 'asynchronous'
      ? `/interview/async?interview_id=${interview.interview_id}&email=${emailEnc}`
      : `/interview/realtime?interview_id=${interview.interview_id}&email=${emailEnc}`
    )
  }

  return (
    <div>
      <div className="bg-white border-b border-slate-200">
        <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
          <div className="flex items-center gap-2 text-brand-600"><Sparkles className="h-5 w-5" /><span className="text-sm font-semibold">AI Talent Platform</span></div>
          <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-900">My Applications</h1>
          <p className="mt-2 text-slate-500">Manage your interviews and track application status.</p>

          <div className="mt-8 flex max-w-lg gap-3">
            <div className="relative flex-1">
              <Mail className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
              <input type="email" placeholder="Enter your email address" className="w-full rounded-xl border border-slate-200 bg-slate-50 py-3 pl-11 pr-4 text-base focus:border-brand-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20" value={email} onChange={e => setEmail(e.target.value)} onKeyDown={e => e.key === 'Enter' && loadInterviews()} />
            </div>
            <button onClick={() => loadInterviews()} disabled={loading} className="btn-primary">{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <><span>Find</span><ArrowRight className="h-4 w-4" /></>}</button>
          </div>
          {error && <p className="mt-3 text-sm text-red-500">{error}</p>}
        </div>
      </div>

      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {searched && interviews.length > 0 && (
          <>
            <div className="mb-6 flex items-center gap-3"><FolderOpen className="h-5 w-5 text-slate-400" /><h2 className="text-lg font-semibold text-slate-900">Available Interviews</h2><span className="badge bg-brand-50 text-brand-700">{interviews.length}</span></div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {interviews.map(interview => {
                const isAsync = (interview.job_offer?.interview_mode || interview.interview_mode) === 'asynchronous'
                const isCompleted = interview.status === 'completed'
                return (
                  <div key={interview.interview_id} className="card flex flex-col overflow-hidden">
                    <div className="flex-1 p-5">
                      <div className="flex items-center justify-between">
                        <span className={`badge ${isAsync ? 'bg-violet-50 text-violet-700' : 'bg-blue-50 text-blue-700'}`}>
                          {isAsync ? <><Video className="mr-1 h-3 w-3" />Async</> : <><Mic className="mr-1 h-3 w-3" />Real-time</>}
                        </span>
                        <span className={`badge ${isCompleted ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
                          {isCompleted ? 'Completed' : 'Pending'}
                        </span>
                      </div>
                      <h3 className="mt-3 text-base font-semibold text-slate-900">{interview.job_offer.title}</h3>
                      <div className="mt-2 flex items-center gap-1.5 text-xs text-slate-400"><Calendar className="h-3 w-3" />{formatDate(interview.created_at)}</div>
                    </div>
                    <div className="border-t border-slate-100 px-5 py-3">
                      <button onClick={() => isCompleted ? handleStartInterview(interview) : handleStartInterview(interview)} className={`flex w-full items-center justify-center gap-2 rounded-lg py-2 text-sm font-medium transition-colors ${isCompleted ? 'bg-slate-100 text-slate-700 hover:bg-slate-200' : 'bg-brand-500 text-white hover:bg-brand-600'}`}>
                        {isCompleted ? <><CheckCircle className="h-4 w-4" />View Details</> : <><Play className="h-4 w-4" />Start Interview</>}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </>
        )}
        {searched && interviews.length === 0 && !error && (
          <EmptyState icon={FolderOpen} title="No interviews yet" description="Once you apply and get invited, your interviews will appear here." />
        )}
      </div>
    </div>
  )
}
