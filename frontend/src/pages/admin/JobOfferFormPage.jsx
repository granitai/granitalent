import React, { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useJobOffer, useCreateJobOffer, useUpdateJobOffer } from '../../hooks/useJobOffers'
import { EVALUATION_CATEGORIES, LANGUAGES } from '../../lib/constants'
import { parseJSON } from '../../lib/utils'
import { toast } from 'sonner'
import { ArrowLeft, ArrowRight, Check, X, Briefcase, Languages, Settings, Loader2 } from 'lucide-react'
import { cn } from '../../lib/utils'

const STEPS = [
  { id: 1, title: 'Job Details', icon: Briefcase },
  { id: 2, title: 'Interview Setup', icon: Languages },
  { id: 3, title: 'AI Configuration', icon: Settings },
]

const defaultForm = {
  title: '', description: '', required_skills: '', experience_level: '', education_requirements: '',
  required_languages: [], selectedLanguage: '', interview_start_language: '', interview_duration_minutes: 20,
  interview_mode: 'realtime', custom_questions: [], newQuestion: '', evaluation_weights: {},
}

export default function JobOfferFormPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const isEditing = !!id
  const { data: existingOffer, isLoading } = useJobOffer(id)
  const createMutation = useCreateJobOffer()
  const updateMutation = useUpdateJobOffer()
  const [step, setStep] = useState(1)
  const [form, setForm] = useState(defaultForm)
  const [errors, setErrors] = useState({})

  useEffect(() => {
    if (existingOffer) {
      setForm({
        ...defaultForm,
        title: existingOffer.title || '',
        description: existingOffer.description || '',
        required_skills: existingOffer.required_skills || '',
        experience_level: existingOffer.experience_level || '',
        education_requirements: existingOffer.education_requirements || '',
        required_languages: parseJSON(existingOffer.required_languages, []),
        interview_start_language: existingOffer.interview_start_language || '',
        interview_duration_minutes: existingOffer.interview_duration_minutes || 20,
        interview_mode: existingOffer.interview_mode || 'realtime',
        custom_questions: parseJSON(existingOffer.custom_questions, []),
        evaluation_weights: parseJSON(existingOffer.evaluation_weights, {}),
      })
    }
  }, [existingOffer])

  const validate = () => {
    const e = {}
    if (step === 1) {
      if (!form.title.trim()) e.title = 'Required'
      if (!form.description.trim()) e.description = 'Required'
    }
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleNext = () => { if (validate()) setStep(s => Math.min(s + 1, 3)) }
  const handleBack = () => setStep(s => Math.max(s - 1, 1))

  const handleSubmit = async () => {
    if (!validate()) return
    const { selectedLanguage, newQuestion, ...data } = form
    data.required_languages = JSON.stringify(form.required_languages)
    data.custom_questions = JSON.stringify(form.custom_questions)
    const filtered = Object.fromEntries(Object.entries(form.evaluation_weights).filter(([_, v]) => v > 0))
    data.evaluation_weights = Object.keys(filtered).length > 0 ? JSON.stringify(filtered) : ''

    try {
      if (isEditing) {
        await updateMutation.mutateAsync({ id, data })
        toast.success('Job offer updated')
      } else {
        await createMutation.mutateAsync(data)
        toast.success('Job offer created')
      }
      navigate('/admin/job-offers')
    } catch {
      toast.error('Failed to save job offer')
    }
  }

  if (isEditing && isLoading) {
    return <div className="flex h-[60vh] items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>
  }

  const isSaving = createMutation.isPending || updateMutation.isPending

  return (
    <div className="mx-auto max-w-3xl">
      <button onClick={() => navigate('/admin/job-offers')} className="mb-4 flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft className="h-4 w-4" /> Back to Job Offers
      </button>

      <h1 className="text-2xl font-bold text-slate-900">{isEditing ? 'Edit Job Offer' : 'Create Job Offer'}</h1>

      <div className="mt-6 flex items-center gap-2">
        {STEPS.map((s, i) => (
          <React.Fragment key={s.id}>
            <div className={cn('flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium', step === s.id ? 'bg-brand-50 text-brand-700' : step > s.id ? 'text-brand-600' : 'text-slate-400')}>
              <div className={cn('flex h-6 w-6 items-center justify-center rounded-full text-xs', step > s.id ? 'bg-brand-500 text-white' : step === s.id ? 'bg-brand-100 text-brand-700' : 'bg-slate-100 text-slate-400')}>
                {step > s.id ? <Check className="h-3 w-3" /> : s.id}
              </div>
              <span className="hidden sm:inline">{s.title}</span>
            </div>
            {i < STEPS.length - 1 && <div className={cn('h-px flex-1', step > s.id ? 'bg-brand-500' : 'bg-slate-200')} />}
          </React.Fragment>
        ))}
      </div>

      <div className="card mt-6 p-6">
        {step === 1 && (
          <div className="space-y-4">
            <div><label className="label">Job Title *</label><input className={cn('input', errors.title && 'border-red-300 focus:border-red-500 focus:ring-red-500')} value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} placeholder="e.g., Senior Software Engineer" />{errors.title && <p className="mt-1 text-xs text-red-500">{errors.title}</p>}</div>
            <div><label className="label">Description *</label><textarea className={cn('textarea', errors.description && 'border-red-300')} rows={4} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} placeholder="Describe the role..." />{errors.description && <p className="mt-1 text-xs text-red-500">{errors.description}</p>}</div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div><label className="label">Required Skills</label><textarea className="textarea" rows={3} value={form.required_skills} onChange={e => setForm({ ...form, required_skills: e.target.value })} placeholder="Key skills..." /></div>
              <div><label className="label">Education Requirements</label><textarea className="textarea" rows={3} value={form.education_requirements} onChange={e => setForm({ ...form, education_requirements: e.target.value })} placeholder="Required education..." /></div>
            </div>
            <div><label className="label">Experience Level</label><input className="input" value={form.experience_level} onChange={e => setForm({ ...form, experience_level: e.target.value })} placeholder="e.g., 3-5 years" /></div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-6">
            <div>
              <label className="label">Required Languages</label>
              <div className="flex gap-2">
                <select className="select flex-1" value={form.selectedLanguage} onChange={e => setForm({ ...form, selectedLanguage: e.target.value })}>
                  <option value="">Select a language...</option>
                  {LANGUAGES.filter(l => !form.required_languages.includes(l)).map(l => <option key={l} value={l}>{l}</option>)}
                </select>
                <button type="button" onClick={() => { if (form.selectedLanguage) { setForm({ ...form, required_languages: [...form.required_languages, form.selectedLanguage], selectedLanguage: '' }) } }} disabled={!form.selectedLanguage} className="btn-secondary">Add</button>
              </div>
              {form.required_languages.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{form.required_languages.map((l, i) => <span key={i} className="badge bg-violet-50 text-violet-700 ring-1 ring-violet-600/20">{l}<button type="button" onClick={() => setForm({ ...form, required_languages: form.required_languages.filter((_, j) => j !== i) })} className="ml-1 text-violet-400 hover:text-violet-600"><X className="h-3 w-3" /></button></span>)}</div>}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div><label className="label">Interview Start Language</label><select className="select" value={form.interview_start_language} onChange={e => setForm({ ...form, interview_start_language: e.target.value })}><option value="">Select...</option>{LANGUAGES.map(l => <option key={l} value={l}>{l}</option>)}</select></div>
              <div><label className="label">Duration (minutes)</label><input type="number" min={5} max={120} className="input" value={form.interview_duration_minutes} onChange={e => setForm({ ...form, interview_duration_minutes: parseInt(e.target.value) || 20 })} /></div>
            </div>
            <div>
              <label className="label">Interview Mode</label>
              <div className="mt-1 grid grid-cols-2 gap-3">
                {['realtime', 'asynchronous'].map(mode => (
                  <button key={mode} type="button" onClick={() => setForm({ ...form, interview_mode: mode })} className={cn('rounded-lg border-2 p-4 text-left transition-all', form.interview_mode === mode ? 'border-brand-500 bg-brand-50' : 'border-slate-200 hover:border-slate-300')}>
                    <p className="text-sm font-semibold capitalize text-slate-900">{mode}</p>
                    <p className="mt-1 text-xs text-slate-500">{mode === 'realtime' ? 'Live conversation with AI' : 'Push-to-talk, 1 min max, 3 retries'}</p>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-6">
            <div>
              <label className="label">Custom Interview Questions</label>
              <p className="mb-2 text-xs text-slate-500">Leave empty to let the AI generate questions automatically.</p>
              <div className="flex gap-2">
                <input className="input flex-1" value={form.newQuestion} onChange={e => setForm({ ...form, newQuestion: e.target.value })} placeholder="Type a question..." onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); if (form.newQuestion.trim()) { setForm({ ...form, custom_questions: [...form.custom_questions, form.newQuestion.trim()], newQuestion: '' }) } } }} />
                <button type="button" onClick={() => { if (form.newQuestion.trim()) { setForm({ ...form, custom_questions: [...form.custom_questions, form.newQuestion.trim()], newQuestion: '' }) } }} disabled={!form.newQuestion?.trim()} className="btn-secondary">Add</button>
              </div>
              {form.custom_questions.length > 0 && (
                <div className="mt-3 space-y-2">
                  {form.custom_questions.map((q, i) => (
                    <div key={i} className="flex items-start gap-2 rounded-lg bg-slate-50 p-3">
                      <span className="text-xs font-medium text-slate-400">{i + 1}.</span>
                      <p className="flex-1 text-sm text-slate-700">{q}</p>
                      <button type="button" onClick={() => setForm({ ...form, custom_questions: form.custom_questions.filter((_, j) => j !== i) })} className="text-slate-400 hover:text-red-500"><X className="h-4 w-4" /></button>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div>
              <label className="label">Evaluation Priorities</label>
              <p className="mb-3 text-xs text-slate-500">Higher values = more AI focus on that aspect.</p>
              <div className="grid gap-3 sm:grid-cols-2">
                {EVALUATION_CATEGORIES.map(cat => (
                  <div key={cat.key} className="rounded-lg border border-slate-200 p-3">
                    <div className="flex items-center justify-between">
                      <label className="text-sm font-medium text-slate-700">{cat.label}</label>
                      <span className={cn('text-sm font-bold', (form.evaluation_weights[cat.key] || 0) >= 7 ? 'text-brand-600' : (form.evaluation_weights[cat.key] || 0) >= 4 ? 'text-amber-600' : 'text-slate-400')}>{form.evaluation_weights[cat.key] || 0}</span>
                    </div>
                    <input type="range" min={0} max={10} value={form.evaluation_weights[cat.key] || 0} onChange={e => { const w = { ...form.evaluation_weights }; const v = parseInt(e.target.value); if (v === 0) delete w[cat.key]; else w[cat.key] = v; setForm({ ...form, evaluation_weights: w }) }} className="mt-2 w-full accent-brand-500" />
                    <p className="mt-1 text-xs text-slate-400">{cat.description}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="mt-6 flex items-center justify-between">
        <div>{step > 1 && <button onClick={handleBack} className="btn-ghost"><ArrowLeft className="h-4 w-4" />Back</button>}</div>
        <div className="flex gap-3">
          <button onClick={() => navigate('/admin/job-offers')} className="btn-ghost">Cancel</button>
          {step < 3 ? (
            <button onClick={handleNext} className="btn-primary">Next<ArrowRight className="h-4 w-4" /></button>
          ) : (
            <button onClick={handleSubmit} disabled={isSaving} className="btn-primary"><Check className="h-4 w-4" />{isSaving ? 'Saving...' : isEditing ? 'Update' : 'Create'}</button>
          )}
        </div>
      </div>
    </div>
  )
}
