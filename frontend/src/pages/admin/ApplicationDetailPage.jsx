import React, { useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useApplication, useSelectApplication, useRejectApplication, useOverrideApplication, useSendInterview } from '../../hooks/useApplications'
import PageHeader from '../../components/shared/PageHeader'
import StatusBadge from '../../components/shared/StatusBadge'
import Modal from '../../components/shared/Modal'
import { formatDateTime, parseJSON } from '../../lib/utils'
import { toast } from 'sonner'
import {
  ArrowLeft, User, Mail, Phone, Globe, Briefcase, Sparkles,
  CheckCircle2, XCircle, Mic, FileText, Loader2, Send, ShieldCheck,
  GraduationCap, ClipboardCheck, BookOpen,
} from 'lucide-react'

export default function ApplicationDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data: app, isLoading } = useApplication(id)
  const selectMutation = useSelectApplication()
  const rejectMutation = useRejectApplication()
  const overrideMutation = useOverrideApplication()
  const sendInterviewMutation = useSendInterview()

  const [showOverrideModal, setShowOverrideModal] = useState(false)
  const [showInterviewModal, setShowInterviewModal] = useState(false)
  const [overrideReason, setOverrideReason] = useState('')
  const [interviewDate, setInterviewDate] = useState('')
  const [interviewNotes, setInterviewNotes] = useState('')

  if (isLoading) {
    return <div className="flex h-[60vh] items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>
  }

  if (!app) {
    return <div className="flex h-[60vh] flex-col items-center justify-center gap-4"><p className="text-slate-500">Application not found</p><button onClick={() => navigate('/admin/applications')} className="btn-secondary">Back to Applications</button></div>
  }

  const handleSelect = async () => {
    try { await selectMutation.mutateAsync(id); toast.success('Candidate selected'); navigate('/admin/applications') } catch { toast.error('Failed to select candidate') }
  }

  const handleReject = async () => {
    const reason = window.prompt('Enter rejection reason (optional):')
    if (reason === null) return
    try { await rejectMutation.mutateAsync({ id, reason }); toast.success('Candidate rejected'); navigate('/admin/applications') } catch { toast.error('Failed to reject candidate') }
  }

  const handleOverride = async () => {
    try { await overrideMutation.mutateAsync({ id, reason: overrideReason }); toast.success('AI decision overridden'); setShowOverrideModal(false); navigate('/admin/applications') } catch { toast.error('Failed to override') }
  }

  const handleSendInterview = async () => {
    try { await sendInterviewMutation.mutateAsync({ id, interview_date: interviewDate, notes: interviewNotes }); toast.success('Interview invitation sent'); setShowInterviewModal(false); navigate('/admin/applications') } catch { toast.error('Failed to send invitation') }
  }

  const languages = parseJSON(app.job_offer?.required_languages, [])

  return (
    <div>
      <button onClick={() => navigate('/admin/applications')} className="mb-4 flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft className="h-4 w-4" /> Back to Applications
      </button>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{app.candidate.full_name}</h1>
          <p className="mt-1 text-sm text-slate-500">{app.candidate.email} &middot; Applied {formatDateTime(app.submitted_at)}</p>
          <div className="mt-2 flex items-center gap-2">
            <StatusBadge status={app.ai_status} />
            <StatusBadge status={app.hr_status} />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {app.ai_status === 'rejected' && app.hr_status === 'pending' && (
            <button onClick={() => setShowOverrideModal(true)} className="btn-secondary"><ShieldCheck className="h-4 w-4" />Override AI</button>
          )}
          <button onClick={() => setShowInterviewModal(true)} className="btn-secondary"><Send className="h-4 w-4" />{app.interviews?.length > 0 ? 'New Interview' : 'Send Interview'}</button>
          <button onClick={handleSelect} disabled={selectMutation.isPending} className="btn-primary"><CheckCircle2 className="h-4 w-4" />Select</button>
          <button onClick={handleReject} disabled={rejectMutation.isPending} className="btn-danger"><XCircle className="h-4 w-4" />Reject</button>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <div className="card p-6">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Sparkles className="h-4 w-4 text-brand-500" />AI Evaluation</h3>
            <div className="mt-4 flex items-center gap-4">
              <div className="text-center"><p className="text-3xl font-bold text-slate-900">{app.ai_score ?? '-'}</p><p className="text-xs text-slate-500">Overall Score /10</p></div>
              <div className="h-12 w-px bg-slate-200" />
              <div className="flex-1">
                <StatusBadge status={app.ai_status} />
              </div>
            </div>

            {(app.language_check || app.job_fit_check) && (
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                {app.language_check && (
                  <div className="rounded-lg border border-slate-200 p-4">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Language Check</h4>
                    <div className={`mt-2 text-sm font-semibold ${app.language_check.passed ? 'text-emerald-600' : 'text-red-600'}`}>
                      {app.language_check.passed ? 'Passed' : 'Failed'}
                    </div>
                    {app.language_check.languages_required?.length > 0 && <p className="mt-1 text-xs text-slate-500">Required: {app.language_check.languages_required.join(', ')}</p>}
                    {app.language_check.languages_found?.length > 0 && <p className="text-xs text-slate-500">Found: {app.language_check.languages_found.join(', ')}</p>}
                    {app.language_check.languages_missing?.length > 0 && <p className="text-xs text-red-500">Missing: {app.language_check.languages_missing.join(', ')}</p>}
                    {app.language_check.reasoning && <p className="mt-2 text-xs text-slate-600">{app.language_check.reasoning}</p>}
                  </div>
                )}
                {app.job_fit_check && (
                  <div className="rounded-lg border border-slate-200 p-4">
                    <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Job Fit Check</h4>
                    <div className={`mt-2 text-sm font-semibold ${app.job_fit_check.status === 'approved' ? 'text-emerald-600' : 'text-red-600'}`}>
                      {app.job_fit_check.status === 'approved' ? 'Approved' : 'Rejected'}
                    </div>
                    <div className="mt-2 space-y-1">
                      {[
                        { label: 'Skills', value: app.job_fit_check.skills_match || app.ai_skills_match, icon: GraduationCap },
                        { label: 'Experience', value: app.job_fit_check.experience_match || app.ai_experience_match, icon: ClipboardCheck },
                        { label: 'Education', value: app.job_fit_check.education_match || app.ai_education_match, icon: BookOpen },
                      ].map(s => (
                        <div key={s.label} className="flex items-center justify-between text-xs">
                          <span className="text-slate-500">{s.label}</span>
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-200">
                              <div className="h-full rounded-full bg-brand-500" style={{ width: `${(s.value || 0) * 10}%` }} />
                            </div>
                            <span className="font-medium text-slate-700">{s.value || 0}/10</span>
                          </div>
                        </div>
                      ))}
                    </div>
                    {app.job_fit_check.reasoning && <p className="mt-2 text-xs text-slate-600">{app.job_fit_check.reasoning}</p>}
                  </div>
                )}
              </div>
            )}

            {app.ai_reasoning && !app.language_check && !app.job_fit_check && (
              <div className="mt-4 rounded-lg bg-slate-50 p-4"><p className="text-sm text-slate-600">{app.ai_reasoning}</p></div>
            )}
          </div>

          {app.hr_override_reason && (
            <div className="card p-6">
              <h3 className="text-sm font-semibold text-slate-900">HR Override</h3>
              <p className="mt-2 text-sm text-slate-600">{app.hr_override_reason}</p>
            </div>
          )}

          {app.interviews?.length > 0 && (
            <div className="card p-6">
              <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Mic className="h-4 w-4 text-violet-500" />Interview Attempts ({app.interviews.length})</h3>
              <div className="mt-4 space-y-3">
                {app.interviews.map((interview, idx) => (
                  <div key={interview.interview_id} className="rounded-lg border border-slate-200 p-4">
                    <div className="flex items-center justify-between">
                      <h4 className="text-sm font-medium text-slate-900">Attempt #{idx + 1}</h4>
                      <div className="flex gap-2"><StatusBadge status={interview.status} />{interview.recommendation && <StatusBadge status={interview.recommendation} />}</div>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">Created: {formatDateTime(interview.created_at)}{interview.completed_at && ` · Completed: ${formatDateTime(interview.completed_at)}`}</p>
                    {interview.assessment && <div className="mt-2 max-h-32 overflow-y-auto rounded bg-slate-50 p-3 text-xs text-slate-600"><pre className="whitespace-pre-wrap font-sans">{interview.assessment}</pre></div>}
                    <button onClick={() => navigate(`/admin/interviews/${interview.interview_id}`)} className="mt-2 text-xs font-medium text-brand-600 hover:text-brand-700">View Full Details →</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {(app.cv_text || app.cv_file_available) && (
            <div className="card p-6">
              <div className="flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><FileText className="h-4 w-4 text-slate-500" />CV</h3>
                {app.cv_file_available && (
                  <button
                    onClick={async () => {
                      try {
                        const token = localStorage.getItem('admin_token')
                        const res = await fetch(`/api/admin/applications/${app.application_id}/cv-file`, {
                          headers: { Authorization: `Bearer ${token}` }
                        })
                        if (!res.ok) throw new Error('Failed to fetch CV')
                        const blob = await res.blob()
                        const url = URL.createObjectURL(blob)
                        window.open(url, '_blank')
                      } catch (err) {
                        toast.error('Failed to load CV file')
                      }
                    }}
                    className="inline-flex items-center gap-1.5 rounded-md bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-100 transition-colors"
                  >
                    <FileText className="h-3.5 w-3.5" />
                    Preview PDF
                  </button>
                )}
              </div>
              {app.cv_text && (
                <div className="mt-3 max-h-64 overflow-y-auto rounded-lg bg-slate-50 p-4"><pre className="whitespace-pre-wrap font-sans text-xs text-slate-600">{app.cv_text.substring(0, 3000)}{app.cv_text.length > 3000 ? '...' : ''}</pre></div>
              )}
            </div>
          )}
        </div>

        <div className="space-y-6">
          <div className="card p-6">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><User className="h-4 w-4 text-slate-500" />Candidate Info</h3>
            <dl className="mt-4 space-y-3">
              <div className="flex items-center gap-3"><Mail className="h-4 w-4 text-slate-400" /><div><dt className="text-xs text-slate-500">Email</dt><dd className="text-sm text-slate-900">{app.candidate.email}</dd></div></div>
              <div className="flex items-center gap-3"><Phone className="h-4 w-4 text-slate-400" /><div><dt className="text-xs text-slate-500">Phone</dt><dd className="text-sm text-slate-900">{app.candidate.phone || 'N/A'}</dd></div></div>
              {app.candidate.linkedin && <div className="flex items-center gap-3"><Globe className="h-4 w-4 text-slate-400" /><div><dt className="text-xs text-slate-500">LinkedIn</dt><dd><a href={app.candidate.linkedin} target="_blank" rel="noopener noreferrer" className="text-sm text-brand-600 hover:underline">View Profile</a></dd></div></div>}
              {app.candidate.portfolio && <div className="flex items-center gap-3"><Globe className="h-4 w-4 text-slate-400" /><div><dt className="text-xs text-slate-500">Portfolio</dt><dd><a href={app.candidate.portfolio} target="_blank" rel="noopener noreferrer" className="text-sm text-brand-600 hover:underline">View Portfolio</a></dd></div></div>}
            </dl>
          </div>

          <div className="card p-6">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900"><Briefcase className="h-4 w-4 text-slate-500" />Position</h3>
            <p className="mt-2 text-sm font-medium text-slate-900">{app.job_offer.title}</p>
            {languages.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {languages.map(lang => <span key={lang} className="badge bg-violet-50 text-violet-700 ring-1 ring-violet-600/20">{lang}</span>)}
              </div>
            )}
          </div>

          {app.cover_letter && (
            <div className="card p-6">
              <h3 className="text-sm font-semibold text-slate-900">Cover Letter</h3>
              <p className="mt-2 text-sm text-slate-600 whitespace-pre-wrap">{app.cover_letter}</p>
            </div>
          )}
        </div>
      </div>

      <Modal open={showOverrideModal} onClose={() => setShowOverrideModal(false)} title="Override AI Decision" footer={
        <><button onClick={() => setShowOverrideModal(false)} className="btn-secondary">Cancel</button><button onClick={handleOverride} disabled={overrideMutation.isPending} className="btn-primary">{overrideMutation.isPending ? 'Processing...' : 'Override & Select'}</button></>
      }>
        <p className="text-sm text-slate-600">The AI has rejected this candidate. You can override this decision.</p>
        {app.ai_reasoning && <div className="mt-3 rounded-lg bg-slate-50 p-3"><p className="text-xs font-medium text-slate-500">AI Reasoning:</p><p className="mt-1 text-sm text-slate-600">{app.ai_reasoning}</p></div>}
        <div className="mt-4"><label className="label">Override Reason (optional)</label><textarea className="textarea" rows={3} value={overrideReason} onChange={(e) => setOverrideReason(e.target.value)} placeholder="Why are you overriding the AI decision?" /></div>
      </Modal>

      <Modal open={showInterviewModal} onClose={() => setShowInterviewModal(false)} title="Send Interview Invitation" footer={
        <><button onClick={() => setShowInterviewModal(false)} className="btn-secondary">Cancel</button><button onClick={handleSendInterview} disabled={sendInterviewMutation.isPending} className="btn-primary">{sendInterviewMutation.isPending ? 'Sending...' : 'Send Invitation'}</button></>
      }>
        <p className="text-sm text-slate-600">Send an interview invitation to <strong>{app.candidate.full_name}</strong></p>
        {app.interviews?.length > 0 && <div className="mt-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-700">This candidate has {app.interviews.length} existing interview attempt(s). A new interview will be created.</div>}
        <div className="mt-4 space-y-4">
          <div><label className="label">Interview Date (optional)</label><input type="datetime-local" className="input" value={interviewDate} onChange={(e) => setInterviewDate(e.target.value)} /></div>
          <div><label className="label">Notes (optional)</label><textarea className="textarea" rows={3} value={interviewNotes} onChange={(e) => setInterviewNotes(e.target.value)} placeholder="Additional notes..." /></div>
        </div>
      </Modal>
    </div>
  )
}
