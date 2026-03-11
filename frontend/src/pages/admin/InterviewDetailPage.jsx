import React, { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useInterview } from '../../hooks/useInterviews'
import { useAuth } from '../../contexts/AuthContext'
import StatusBadge from '../../components/shared/StatusBadge'
import { formatDateTime, parseJSON } from '../../lib/utils'
import { cn } from '../../lib/utils'
import { ArrowLeft, FileText, MessageSquare, Volume2, Loader2, Bot, User, AlertTriangle } from 'lucide-react'

export default function InterviewDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { authApi } = useAuth()
  const { data: interview, isLoading } = useInterview(id)
  const [activeTab, setActiveTab] = useState('assessment')
  const [recordingUrl, setRecordingUrl] = useState(null)
  const [loadingRecording, setLoadingRecording] = useState(false)
  const [videoUrl, setVideoUrl] = useState(null)

  useEffect(() => {
    return () => {
      if (recordingUrl) URL.revokeObjectURL(recordingUrl)
      if (videoUrl) URL.revokeObjectURL(videoUrl)
    }
  }, [recordingUrl, videoUrl])

  // Load video via authenticated fetch
  useEffect(() => {
    if (activeTab === 'recording' && interview?.recording_video && !videoUrl) {
      const token = localStorage.getItem('admin_token')
      fetch(`/api/admin/interviews/${interview.interview_id}/video`, {
        headers: { Authorization: `Bearer ${token}` }
      })
        .then(res => res.ok ? res.blob() : null)
        .then(blob => { if (blob) setVideoUrl(URL.createObjectURL(blob)) })
        .catch(() => {})
    }
  }, [activeTab, interview?.interview_id])

  const loadRecording = async () => {
    if (!interview?.has_recording || loadingRecording) return
    try {
      setLoadingRecording(true)
      const { data } = await authApi.get(`/admin/interviews/${id}/recording`)
      const audioData = atob(data.recording_audio)
      const bytes = new Uint8Array(audioData.length)
      for (let i = 0; i < audioData.length; i++) bytes[i] = audioData.charCodeAt(i)
      const blob = new Blob([bytes], { type: `audio/${data.audio_format || 'mp3'}` })
      setRecordingUrl(URL.createObjectURL(blob))
    } catch { setRecordingUrl(null) }
    finally { setLoadingRecording(false) }
  }

  useEffect(() => { if (activeTab === 'recording' && interview && !recordingUrl && !loadingRecording) loadRecording() }, [activeTab, interview?.interview_id])

  if (isLoading) return <div className="flex h-[60vh] items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>
  if (!interview) return <div className="flex h-[60vh] flex-col items-center justify-center gap-4"><p className="text-slate-500">Interview not found</p><button onClick={() => navigate('/admin/interviews')} className="btn-secondary">Back</button></div>

  const conversation = parseJSON(interview.conversation_history, [])
  const tabs = [
    { id: 'assessment', label: 'Assessment', icon: FileText },
    { id: 'transcript', label: 'Transcript', icon: MessageSquare },
    { id: 'recording', label: 'Recording', icon: Volume2 },
  ]

  return (
    <div>
      <button onClick={() => navigate('/admin/interviews')} className="mb-4 flex items-center gap-2 text-sm text-slate-500 hover:text-slate-700"><ArrowLeft className="h-4 w-4" />Back to Interviews</button>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{interview.candidate.name}</h1>
          <p className="text-sm text-slate-500">{interview.job_offer.title} &middot; {formatDateTime(interview.created_at)}</p>
        </div>
        <div className="flex gap-2"><StatusBadge status={interview.status} />{interview.recommendation && <StatusBadge status={interview.recommendation} />}</div>
      </div>

      <div className="card mt-6 overflow-hidden">
        <div className="flex border-b border-slate-200">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)} className={cn('flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors', activeTab === t.id ? 'border-brand-500 text-brand-700' : 'border-transparent text-slate-500 hover:text-slate-700')}>
              <t.icon className="h-4 w-4" />{t.label}
              {t.id === 'recording' && interview.has_recording && <span className="h-2 w-2 rounded-full bg-emerald-500" />}
            </button>
          ))}
        </div>

        <div className="p-6">
          {activeTab === 'assessment' && (
            interview.assessment ? <div className="prose prose-sm max-w-none"><pre className="whitespace-pre-wrap font-sans text-sm text-slate-700">{interview.assessment}</pre></div>
            : <div className="py-12 text-center"><p className="text-sm text-slate-500">No assessment available yet.</p><p className="mt-1 text-xs text-slate-400">Assessment will be generated when the interview is completed.</p></div>
          )}

          {activeTab === 'transcript' && (
            conversation.length > 0 ? (
              <div className="space-y-4">
                {conversation.map((msg, idx) => (
                  <div key={idx} className={cn('flex gap-3', msg.role === 'assistant' ? '' : 'flex-row-reverse')}>
                    <div className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-full', msg.role === 'assistant' ? 'bg-brand-100 text-brand-700' : 'bg-slate-100 text-slate-600')}>
                      {msg.role === 'assistant' ? <Bot className="h-4 w-4" /> : <User className="h-4 w-4" />}
                    </div>
                    <div className={cn('max-w-[75%]', msg.role === 'assistant' ? '' : 'flex flex-col items-end')}>
                      <div className={cn('rounded-xl px-4 py-3', msg.role === 'assistant' ? 'bg-slate-50 text-slate-700' : 'bg-brand-50 text-brand-900')}>
                        <p className="text-xs font-medium text-slate-500">{msg.role === 'assistant' ? 'AI Interviewer' : interview.candidate.name}</p>
                        <p className="mt-1 text-sm">{msg.content}</p>
                      </div>
                      {msg.ai_comment && (
                        <div className="mt-1.5 flex items-start gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 max-w-full">
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
                          <p className="text-xs text-amber-800">{msg.ai_comment}</p>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : <div className="py-12 text-center text-sm text-slate-500">No transcript available.</div>
          )}

          {activeTab === 'recording' && (
            <div>
              {interview.recording_video && (
                <div className="mb-6"><h3 className="mb-3 text-sm font-semibold text-slate-900">Video Recording</h3><div className="overflow-hidden rounded-lg bg-black" style={{ maxWidth: 640 }}>{videoUrl ? <video controls className="w-full" src={videoUrl} /> : <div className="flex items-center justify-center p-8 text-white"><Loader2 className="h-6 w-6 animate-spin" /></div>}</div></div>
              )}
              {interview.audio_segments?.length > 0 ? (
                <div><h3 className="mb-3 text-sm font-semibold text-slate-900">Audio Segments</h3><div className="space-y-3">{interview.audio_segments.map((seg, idx) => {
                  let audioUrl = seg.audioUrl
                  if (!audioUrl && seg.audio) {
                    try { const d = atob(seg.audio); const b = new Uint8Array(d.length); for (let i = 0; i < d.length; i++) b[i] = d.charCodeAt(i); audioUrl = URL.createObjectURL(new Blob([b], { type: `audio/${seg.format || 'mp3'}` })) } catch {}
                  }
                  return (
                    <div key={idx} className={cn('flex', seg.type === 'question' ? '' : 'justify-end')}>
                      <div className={cn('max-w-[70%] rounded-xl px-4 py-3', seg.type === 'question' ? 'bg-slate-100' : 'bg-brand-50')}>
                        <p className="text-xs font-medium text-slate-500">{seg.type === 'question' ? 'AI Interviewer' : 'Candidate'}{seg.question_number ? ` - Q${seg.question_number}` : ''}</p>
                        {seg.text && <p className="mt-1 text-sm text-slate-700">{seg.text}</p>}
                        {audioUrl && <audio controls src={audioUrl} className="mt-2 h-8 w-full max-w-[300px]" />}
                      </div>
                    </div>
                  )
                })}</div></div>
              ) : <div className="py-12 text-center text-sm text-slate-500">{interview.status === 'completed' ? 'No audio segments available.' : 'Audio will be available after interview completion.'}</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
