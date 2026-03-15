import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useInterview, useRegenerateAssessment } from '../../hooks/useInterviews'
import { useAuth } from '../../contexts/AuthContext'
import StatusBadge from '../../components/shared/StatusBadge'
import { formatDateTime, parseJSON } from '../../lib/utils'
import { cn } from '../../lib/utils'
import { toast } from 'sonner'
import { ArrowLeft, FileText, MessageSquare, Volume2, Loader2, Bot, User, AlertTriangle, Play, Pause, ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react'
import AssessmentView from '../../components/admin/AssessmentView'

export default function InterviewDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { authApi } = useAuth()
  const { data: interview, isLoading, refetch } = useInterview(id)
  const regenerateMutation = useRegenerateAssessment()
  const [activeTab, setActiveTab] = useState('assessment')
  const [recordingUrl, setRecordingUrl] = useState(null)
  const [loadingRecording, setLoadingRecording] = useState(false)
  const [videoUrl, setVideoUrl] = useState(null)
  const [snapshots, setSnapshots] = useState(null)
  const [snapshotUrls, setSnapshotUrls] = useState({})
  const [turnAudioUrls, setTurnAudioUrls] = useState({}) // {audio_key: blobUrl}

  // Slideshow state
  const [slideshowIndex, setSlideshowIndex] = useState(0)
  const [slideshowPlaying, setSlideshowPlaying] = useState(false)
  const slideshowTimer = useRef(null)

  useEffect(() => {
    return () => {
      if (recordingUrl) URL.revokeObjectURL(recordingUrl)
      if (videoUrl) URL.revokeObjectURL(videoUrl)
      Object.values(snapshotUrls).forEach(url => URL.revokeObjectURL(url))
      Object.values(turnAudioUrls).forEach(url => URL.revokeObjectURL(url))
      if (slideshowTimer.current) clearInterval(slideshowTimer.current)
    }
  }, [recordingUrl, videoUrl, snapshotUrls, turnAudioUrls])

  // Load snapshot images via authenticated fetch
  useEffect(() => {
    if (!snapshots || !interview) return
    const token = localStorage.getItem('admin_token')
    snapshots.snapshots.forEach((snap, idx) => {
      if (snapshotUrls[idx]) return
      fetch(`/api/admin/interviews/${interview.interview_id}/snapshots/${idx}`, {
        headers: { Authorization: `Bearer ${token}` }
      })
        .then(res => res.ok ? res.blob() : null)
        .then(blob => {
          if (blob) {
            setSnapshotUrls(prev => ({ ...prev, [idx]: URL.createObjectURL(blob) }))
          }
        })
        .catch(() => {})
    })
  }, [snapshots, interview?.interview_id])

  // Load video or snapshots via authenticated fetch
  useEffect(() => {
    if (activeTab === 'recording' && interview?.recording_video && !videoUrl && !snapshots) {
      const token = localStorage.getItem('admin_token')
      fetch(`/api/admin/interviews/${interview.interview_id}/video`, {
        headers: { Authorization: `Bearer ${token}` }
      })
        .then(res => {
          if (!res.ok) return null
          const ct = res.headers.get('content-type') || ''
          if (ct.includes('application/json')) {
            return res.json().then(data => {
              if (data?.type === 'snapshots') {
                setSnapshots(data)
              }
              return null
            })
          }
          return res.blob()
        })
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

  // Load per-turn audio for a specific audio_key
  const loadTurnAudio = useCallback((audioKey) => {
    if (!interview || turnAudioUrls[audioKey]) return
    const token = localStorage.getItem('admin_token')
    fetch(`/api/admin/interviews/${interview.interview_id}/turn-audio/${audioKey}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(res => res.ok ? res.blob() : null)
      .then(blob => {
        if (blob) {
          setTurnAudioUrls(prev => ({ ...prev, [audioKey]: URL.createObjectURL(blob) }))
        }
      })
      .catch(() => {})
  }, [interview?.interview_id, turnAudioUrls])

  // Auto-load all per-turn audio when transcript tab is active
  useEffect(() => {
    if (activeTab !== 'transcript' || !interview) return
    const conv = parseJSON(interview.conversation_history, [])
    conv.forEach(msg => {
      if (msg.audio_key && msg.role === 'user') {
        loadTurnAudio(msg.audio_key)
      }
    })
  }, [activeTab, interview?.interview_id])

  // Slideshow controls
  const toggleSlideshow = useCallback(() => {
    if (slideshowPlaying) {
      clearInterval(slideshowTimer.current)
      slideshowTimer.current = null
      setSlideshowPlaying(false)
    } else {
      setSlideshowPlaying(true)
      slideshowTimer.current = setInterval(() => {
        setSlideshowIndex(prev => {
          const max = (snapshots?.snapshots?.length || 1) - 1
          return prev >= max ? 0 : prev + 1
        })
      }, 2000) // 2 seconds per frame
    }
  }, [slideshowPlaying, snapshots])

  useEffect(() => {
    return () => {
      if (slideshowTimer.current) clearInterval(slideshowTimer.current)
    }
  }, [])

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
              {t.id === 'recording' && (interview.has_recording || interview.recording_video) && <span className="h-2 w-2 rounded-full bg-emerald-500" />}
            </button>
          ))}
        </div>

        <div className="p-6">
          {activeTab === 'assessment' && (() => {
            const isFailed = interview.assessment && interview.assessment.startsWith('[ASSESSMENT_FAILED')
            const handleRegenerate = async () => {
              try {
                await regenerateMutation.mutateAsync(interview.interview_id)
                toast.success('Assessment regeneration started. Refresh in a few seconds to see the result.')
                setTimeout(() => refetch(), 8000)
              } catch {
                toast.error('Failed to start assessment regeneration')
              }
            }

            if (isFailed) {
              const isQuota = interview.assessment.includes('QUOTA')
              return (
                <div className="py-8 text-center">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-amber-100">
                    <AlertTriangle className="h-6 w-6 text-amber-600" />
                  </div>
                  <p className="mt-4 text-sm font-medium text-slate-900">
                    {isQuota ? 'Assessment could not be generated — API quota exceeded' : 'Assessment generation failed'}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {isQuota ? 'Reload your API credits, then click the button below to regenerate.' : 'You can try regenerating the assessment.'}
                  </p>
                  <button
                    onClick={handleRegenerate}
                    disabled={regenerateMutation.isPending}
                    className="mt-4 inline-flex items-center gap-2 rounded-lg bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
                  >
                    <RefreshCw className={cn('h-4 w-4', regenerateMutation.isPending && 'animate-spin')} />
                    {regenerateMutation.isPending ? 'Regenerating...' : 'Regenerate Assessment'}
                  </button>
                </div>
              )
            }

            if (interview.assessment) {
              return (
                <div>
                  <div className="flex items-center justify-between mb-4">
                    <div />
                    <button
                      onClick={handleRegenerate}
                      disabled={regenerateMutation.isPending}
                      className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-50"
                      title="Regenerate assessment"
                    >
                      <RefreshCw className={cn('h-3.5 w-3.5', regenerateMutation.isPending && 'animate-spin')} />
                      Regenerate
                    </button>
                  </div>
                  <AssessmentView
                    assessment={interview.assessment}
                    evaluationScores={interview.evaluation_scores}
                  />
                </div>
              )
            }

            return (
              <div className="py-12 text-center">
                <p className="text-sm text-slate-500">No assessment available yet.</p>
                <p className="mt-1 text-xs text-slate-400">Assessment will be generated when the interview is completed.</p>
                {interview.status === 'completed' && (
                  <button
                    onClick={handleRegenerate}
                    disabled={regenerateMutation.isPending}
                    className="mt-4 inline-flex items-center gap-2 rounded-lg bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
                  >
                    <RefreshCw className={cn('h-4 w-4', regenerateMutation.isPending && 'animate-spin')} />
                    {regenerateMutation.isPending ? 'Regenerating...' : 'Generate Assessment'}
                  </button>
                )}
              </div>
            )
          })()}

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
                        {/* Per-turn audio player for candidate messages */}
                        {msg.audio_key && msg.role === 'user' && (
                          <div className="mt-2">
                            {turnAudioUrls[msg.audio_key] ? (
                              <audio controls className="h-8 w-full max-w-[300px]" src={turnAudioUrls[msg.audio_key]} />
                            ) : (
                              <button
                                onClick={() => loadTurnAudio(msg.audio_key)}
                                className="flex items-center gap-1.5 rounded-md bg-slate-100 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-200 transition-colors"
                              >
                                <Volume2 className="h-3 w-3" />
                                Load audio
                              </button>
                            )}
                          </div>
                        )}
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
              {/* Snapshot slideshow */}
              {interview.recording_video && snapshots && snapshots.snapshots.length > 0 ? (
                <div className="mb-6">
                  <h3 className="mb-3 text-sm font-semibold text-slate-900">Identity Verification ({snapshots.count} captures)</h3>
                  <div className="mx-auto" style={{ maxWidth: 480 }}>
                    {/* Main viewer */}
                    <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-black">
                      {snapshotUrls[slideshowIndex] ? (
                        <img
                          src={snapshotUrls[slideshowIndex]}
                          alt={`Snapshot ${slideshowIndex + 1}`}
                          className="aspect-[4/3] w-full object-contain"
                        />
                      ) : (
                        <div className="flex aspect-[4/3] items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-white" /></div>
                      )}
                      {/* Timestamp overlay */}
                      <div className="absolute bottom-0 left-0 right-0 flex items-center justify-between bg-gradient-to-t from-black/70 to-transparent px-3 py-2">
                        <span className="text-xs text-white">
                          {snapshots.snapshots[slideshowIndex]?.timestamp
                            ? new Date(snapshots.snapshots[slideshowIndex].timestamp).toLocaleTimeString()
                            : `#${slideshowIndex + 1}`}
                        </span>
                        <span className="text-xs text-white/70">{slideshowIndex + 1} / {snapshots.snapshots.length}</span>
                      </div>
                    </div>
                    {/* Controls */}
                    <div className="mt-2 flex items-center justify-center gap-3">
                      <button
                        onClick={() => setSlideshowIndex(prev => Math.max(0, prev - 1))}
                        disabled={slideshowIndex === 0}
                        className="rounded-full p-1.5 text-slate-500 hover:bg-slate-100 disabled:opacity-30"
                      >
                        <ChevronLeft className="h-5 w-5" />
                      </button>
                      <button
                        onClick={toggleSlideshow}
                        className="flex items-center gap-1.5 rounded-full bg-brand-500 px-4 py-1.5 text-xs font-medium text-white hover:bg-brand-600"
                      >
                        {slideshowPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                        {slideshowPlaying ? 'Pause' : 'Play'}
                      </button>
                      <button
                        onClick={() => setSlideshowIndex(prev => Math.min(snapshots.snapshots.length - 1, prev + 1))}
                        disabled={slideshowIndex >= snapshots.snapshots.length - 1}
                        className="rounded-full p-1.5 text-slate-500 hover:bg-slate-100 disabled:opacity-30"
                      >
                        <ChevronRight className="h-5 w-5" />
                      </button>
                    </div>
                    {/* Progress bar */}
                    <div className="mt-2 flex gap-0.5">
                      {snapshots.snapshots.map((_, idx) => (
                        <button
                          key={idx}
                          onClick={() => setSlideshowIndex(idx)}
                          className={cn(
                            'h-1 flex-1 rounded-full transition-colors',
                            idx === slideshowIndex ? 'bg-brand-500' : idx < slideshowIndex ? 'bg-brand-200' : 'bg-slate-200'
                          )}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              ) : interview.recording_video && !snapshots ? (
                <div className="mb-6"><h3 className="mb-3 text-sm font-semibold text-slate-900">Video Recording</h3><div className="overflow-hidden rounded-lg bg-black" style={{ maxWidth: 640 }}>{videoUrl ? <video controls className="w-full" src={videoUrl} /> : <div className="flex items-center justify-center p-8 text-white"><Loader2 className="h-6 w-6 animate-spin" /></div>}</div></div>
              ) : null}
              {interview.has_recording && (
                <div className="mb-6">
                  <h3 className="mb-3 text-sm font-semibold text-slate-900">Full Audio Recording</h3>
                  {recordingUrl ? (
                    <audio controls className="w-full max-w-lg" src={recordingUrl} />
                  ) : loadingRecording ? (
                    <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />Loading audio...</div>
                  ) : (
                    <p className="text-sm text-slate-500">Failed to load audio recording.</p>
                  )}
                </div>
              )}
              {!interview.has_recording && !interview.recording_video && (
                <div className="py-12 text-center text-sm text-slate-500">{interview.status === 'completed' ? 'No recordings available.' : 'Recordings will be available after interview completion.'}</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
