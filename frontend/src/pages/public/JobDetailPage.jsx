import React from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { parseJSON, formatDate } from '../../lib/utils'
import { ArrowLeft, Briefcase, Clock, GraduationCap, Languages, Mic, Video, Calendar, Loader2 } from 'lucide-react'

export default function JobDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()

  const { data: job, isLoading } = useQuery({
    queryKey: ['public-job', id],
    queryFn: async () => {
      const { data } = await axios.get('/api/job-offers')
      return data.find(j => String(j.offer_id) === String(id))
    },
  })

  if (isLoading) return <div className="flex h-[60vh] items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>
  if (!job) return <div className="mx-auto max-w-7xl px-4 py-16 text-center"><p className="text-slate-500">Position not found</p><button onClick={() => navigate('/jobs')} className="btn-secondary mt-4">Back to Jobs</button></div>

  const skills = job.required_skills ? job.required_skills.split(/[,;]/).filter(s => s.trim()) : []
  const langs = parseJSON(job.required_languages, [])

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <button onClick={() => navigate('/jobs')} className="mb-6 flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700"><ArrowLeft className="h-4 w-4" />All Positions</button>

      <div className="grid gap-8 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-slate-900">{job.title}</h1>
            {job.created_at && <p className="mt-2 text-sm text-slate-400">Posted {formatDate(job.created_at)}</p>}
          </div>

          <div className="card p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Description</h2>
            <p className="mt-3 whitespace-pre-wrap text-slate-700">{job.description}</p>
          </div>

          {job.required_skills && (
            <div className="card p-6">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Required Skills</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {skills.map((s, i) => <span key={i} className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-700">{s.trim()}</span>)}
              </div>
            </div>
          )}

          {job.education_requirements && (
            <div className="card p-6">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500">Education</h2>
              <p className="mt-3 text-slate-700">{job.education_requirements}</p>
            </div>
          )}
        </div>

        <div className="space-y-6">
          <div className="card sticky top-24 p-6">
            <Link to={`/jobs/${id}/apply`} className="btn-primary w-full justify-center text-base py-3">Apply Now</Link>

            <div className="mt-6 space-y-4">
              {job.experience_level && (
                <div className="flex items-center gap-3"><Clock className="h-5 w-5 text-slate-400" /><div><p className="text-xs text-slate-500">Experience</p><p className="text-sm font-medium text-slate-900">{job.experience_level}</p></div></div>
              )}
              {langs.length > 0 && (
                <div className="flex items-start gap-3"><Languages className="mt-0.5 h-5 w-5 text-slate-400" /><div><p className="text-xs text-slate-500">Languages</p><div className="mt-1 flex flex-wrap gap-1">{langs.map(l => <span key={l} className="badge bg-violet-50 text-violet-700">{l}</span>)}</div></div></div>
              )}
              {job.interview_mode && (
                <div className="flex items-center gap-3">{job.interview_mode === 'realtime' ? <Mic className="h-5 w-5 text-slate-400" /> : <Video className="h-5 w-5 text-slate-400" />}<div><p className="text-xs text-slate-500">Interview Format</p><p className="text-sm font-medium capitalize text-slate-900">{job.interview_mode}</p></div></div>
              )}
              {job.interview_duration_minutes && (
                <div className="flex items-center gap-3"><Calendar className="h-5 w-5 text-slate-400" /><div><p className="text-xs text-slate-500">Duration</p><p className="text-sm font-medium text-slate-900">{job.interview_duration_minutes} minutes</p></div></div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
