import React, { useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { toast } from 'sonner'
import { ArrowLeft, Upload, FileText, Trash2, CheckCircle, Loader2 } from 'lucide-react'
import { cn } from '../../lib/utils'

const MAX_FILE_SIZE = 10 * 1024 * 1024

export default function ApplicationPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [form, setForm] = useState({ full_name: '', email: '', phone: '', linkedin: '', portfolio: '', cv_file: null, cover_letter_file: null })
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [errors, setErrors] = useState({})
  const cvRef = useRef(null)
  const clRef = useRef(null)

  const { data: job } = useQuery({
    queryKey: ['public-job', id],
    queryFn: async () => {
      const { data } = await axios.get('/api/job-offers')
      return data.find(j => String(j.offer_id) === String(id))
    },
  })

  const validateFile = (file, field) => {
    if (field === 'cv_file' && !file.name.toLowerCase().endsWith('.pdf')) {
      setErrors(p => ({ ...p, [field]: 'Only PDF files are accepted' })); return false
    }
    if (field === 'cover_letter_file') {
      const ext = file.name.toLowerCase()
      if (!ext.endsWith('.pdf') && !ext.endsWith('.doc') && !ext.endsWith('.docx')) {
        setErrors(p => ({ ...p, [field]: 'Only PDF, DOC, or DOCX files' })); return false
      }
    }
    if (file.size > MAX_FILE_SIZE) {
      setErrors(p => ({ ...p, [field]: `File too large (max 10MB)` })); return false
    }
    setErrors(p => ({ ...p, [field]: '' })); return true
  }

  const handleFileChange = (e, field) => {
    const file = e.target.files[0]
    if (file && validateFile(file, field)) setForm(p => ({ ...p, [field]: file }))
    else e.target.value = ''
  }

  const handleDrop = (e, field) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file && validateFile(file, field)) setForm(p => ({ ...p, [field]: file }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.cv_file) { toast.error('Please upload your CV'); return }

    setSubmitting(true)
    const formData = new FormData()
    formData.append('job_offer_id', id)
    formData.append('full_name', form.full_name)
    formData.append('email', form.email)
    formData.append('phone', form.phone)
    formData.append('linkedin', form.linkedin || '')
    formData.append('portfolio', form.portfolio || '')
    formData.append('cv_file', form.cv_file)
    if (form.cover_letter_file) formData.append('cover_letter_file', form.cover_letter_file)

    try {
      await axios.post('/api/candidates/apply', formData)
      setSubmitted(true)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to submit application')
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted) {
    return (
      <div className="mx-auto max-w-lg px-4 py-24 text-center">
        <div className="flex h-16 w-16 mx-auto items-center justify-center rounded-full bg-emerald-100"><CheckCircle className="h-8 w-8 text-emerald-600" /></div>
        <h2 className="mt-6 text-2xl font-bold text-slate-900">Application Submitted</h2>
        <p className="mt-3 text-slate-500">Your application has been received. Our AI will evaluate your profile and you'll be contacted soon.</p>
        <div className="mt-8 flex justify-center gap-3">
          <button onClick={() => navigate('/jobs')} className="btn-secondary">Browse More Jobs</button>
          <button onClick={() => navigate('/my-applications')} className="btn-primary">Track My Applications</button>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-8 sm:px-6">
      <button onClick={() => navigate(`/jobs/${id}`)} className="mb-6 flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700"><ArrowLeft className="h-4 w-4" />Back to Position</button>

      <h1 className="text-2xl font-bold text-slate-900">Apply for {job?.title || 'Position'}</h1>
      <p className="mt-1 text-sm text-slate-500">Fill out the form below to submit your application.</p>

      <form onSubmit={handleSubmit} className="mt-8 space-y-6">
        <div className="card p-6 space-y-4">
          <h2 className="text-sm font-semibold text-slate-900">Personal Information</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div><label className="label">Full Name *</label><input className="input" required value={form.full_name} onChange={e => setForm(p => ({ ...p, full_name: e.target.value }))} /></div>
            <div><label className="label">Email *</label><input type="email" className="input" required value={form.email} onChange={e => setForm(p => ({ ...p, email: e.target.value }))} /></div>
            <div><label className="label">Phone *</label><input type="tel" className="input" required value={form.phone} onChange={e => setForm(p => ({ ...p, phone: e.target.value }))} /></div>
            <div><label className="label">LinkedIn</label><input type="url" className="input" placeholder="https://linkedin.com/in/..." value={form.linkedin} onChange={e => setForm(p => ({ ...p, linkedin: e.target.value }))} /></div>
          </div>
          <div><label className="label">Portfolio</label><input type="url" className="input" placeholder="https://..." value={form.portfolio} onChange={e => setForm(p => ({ ...p, portfolio: e.target.value }))} /></div>
        </div>

        <div className="card p-6 space-y-4">
          <h2 className="text-sm font-semibold text-slate-900">Documents</h2>

          <div>
            <label className="label">CV (PDF) *</label>
            <div
              onDragOver={e => e.preventDefault()}
              onDrop={e => handleDrop(e, 'cv_file')}
              onClick={() => cvRef.current?.click()}
              className={cn('flex cursor-pointer flex-col items-center rounded-lg border-2 border-dashed p-6 text-center transition-colors', form.cv_file ? 'border-brand-300 bg-brand-50' : 'border-slate-300 hover:border-brand-400')}
            >
              <input ref={cvRef} type="file" accept=".pdf" className="hidden" onChange={e => handleFileChange(e, 'cv_file')} />
              {form.cv_file ? (
                <div className="flex items-center gap-3">
                  <FileText className="h-5 w-5 text-brand-600" />
                  <span className="text-sm font-medium text-slate-900">{form.cv_file.name}</span>
                  <button type="button" onClick={(e) => { e.stopPropagation(); setForm(p => ({ ...p, cv_file: null })); if(cvRef.current) cvRef.current.value='' }} className="text-slate-400 hover:text-red-500"><Trash2 className="h-4 w-4" /></button>
                </div>
              ) : (
                <><Upload className="h-8 w-8 text-slate-400" /><p className="mt-2 text-sm text-slate-600">Click or drag to upload</p><p className="text-xs text-slate-400">PDF only, max 10MB</p></>
              )}
            </div>
            {errors.cv_file && <p className="mt-1 text-xs text-red-500">{errors.cv_file}</p>}
          </div>

          <div>
            <label className="label">Cover Letter (optional)</label>
            <div
              onDragOver={e => e.preventDefault()}
              onDrop={e => handleDrop(e, 'cover_letter_file')}
              onClick={() => clRef.current?.click()}
              className={cn('flex cursor-pointer flex-col items-center rounded-lg border-2 border-dashed p-6 text-center transition-colors', form.cover_letter_file ? 'border-brand-300 bg-brand-50' : 'border-slate-300 hover:border-brand-400')}
            >
              <input ref={clRef} type="file" accept=".pdf,.doc,.docx" className="hidden" onChange={e => handleFileChange(e, 'cover_letter_file')} />
              {form.cover_letter_file ? (
                <div className="flex items-center gap-3">
                  <FileText className="h-5 w-5 text-brand-600" />
                  <span className="text-sm font-medium text-slate-900">{form.cover_letter_file.name}</span>
                  <button type="button" onClick={(e) => { e.stopPropagation(); setForm(p => ({ ...p, cover_letter_file: null })); if(clRef.current) clRef.current.value='' }} className="text-slate-400 hover:text-red-500"><Trash2 className="h-4 w-4" /></button>
                </div>
              ) : (
                <><Upload className="h-8 w-8 text-slate-400" /><p className="mt-2 text-sm text-slate-600">Click or drag to upload</p><p className="text-xs text-slate-400">PDF, DOC, or DOCX, max 10MB</p></>
              )}
            </div>
            {errors.cover_letter_file && <p className="mt-1 text-xs text-red-500">{errors.cover_letter_file}</p>}
          </div>
        </div>

        <div className="flex justify-end gap-3">
          <button type="button" onClick={() => navigate(`/jobs/${id}`)} className="btn-secondary">Cancel</button>
          <button type="submit" disabled={submitting} className="btn-primary">{submitting ? <><Loader2 className="h-4 w-4 animate-spin" />Submitting...</> : 'Submit Application'}</button>
        </div>
      </form>
    </div>
  )
}
