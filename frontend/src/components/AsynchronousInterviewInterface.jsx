import React, { useState, useEffect, useRef, useCallback } from 'react'
import { HiMicrophone, HiStop, HiSpeakerWave, HiCheck, HiArrowPath, HiPlay, HiPause, HiChevronRight } from 'react-icons/hi2'
import axios from 'axios'
import './AsynchronousInterviewInterface.css'

const API_BASE_URL = '/api'
const MAX_RECORDING_TIME = 120000 // 2 minutes
const MAX_RETRIES = 3

function AsynchronousInterviewInterface({ interview, onClose }) {
  // ── State ──────────────────────────────────────────────────────
  const [phase, setPhase] = useState('welcome') // welcome | listening | recording | review | submitting | completed
  const [currentQuestion, setCurrentQuestion] = useState(null)
  const [questionNumber, setQuestionNumber] = useState(0)
  const [conversation, setConversation] = useState([])
  const [recordingTime, setRecordingTime] = useState(0)
  const [retryCount, setRetryCount] = useState(0)
  const [recordedAudio, setRecordedAudio] = useState(null)
  const [recordedAudioUrl, setRecordedAudioUrl] = useState(null)
  const [isPlayingRecording, setIsPlayingRecording] = useState(false)
  const [isAiSpeaking, setIsAiSpeaking] = useState(false)
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  // ── Refs ────────────────────────────────────────────────────────
  const mediaRecorderRef = useRef(null)
  const audioChunksRef = useRef([])
  const recordingIntervalRef = useRef(null)
  const currentAudioRef = useRef(null)
  const playbackAudioRef = useRef(null)
  const videoPreviewRef = useRef(null)
  const conversationEndRef = useRef(null)

  // Full interview recording
  const fullInterviewRecorderRef = useRef(null)
  const fullInterviewChunksRef = useRef([])
  const fullInterviewStreamRef = useRef(null)
  const aiAudioChunksRef = useRef([])

  // ── Cleanup ────────────────────────────────────────────────────
  useEffect(() => {
    return () => cleanupResources()
  }, [])

  useEffect(() => {
    if (conversationEndRef.current) {
      conversationEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [conversation])

  const cleanupResources = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    if (recordingIntervalRef.current) clearInterval(recordingIntervalRef.current)
    if (currentAudioRef.current) { currentAudioRef.current.pause(); currentAudioRef.current = null }
    if (playbackAudioRef.current) { playbackAudioRef.current.pause(); playbackAudioRef.current = null }
    if (recordedAudioUrl) URL.revokeObjectURL(recordedAudioUrl)
  }

  // ── Browser Speech Synthesis fallback ──────────────────────────
  const speakWithBrowser = useCallback((text) => {
    return new Promise((resolve) => {
      if (!window.speechSynthesis) { resolve(); return }
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.rate = 0.95
      utterance.pitch = 1
      utterance.onend = () => resolve()
      utterance.onerror = () => resolve()
      setIsAiSpeaking(true)
      window.speechSynthesis.speak(utterance)
      utterance.onend = () => { setIsAiSpeaking(false); resolve() }
      utterance.onerror = () => { setIsAiSpeaking(false); resolve() }
    })
  }, [])

  // ── Audio playback ─────────────────────────────────────────────
  const playAudio = useCallback(async (audioBase64, format = 'mp3') => {
    try {
      if (currentAudioRef.current) { currentAudioRef.current.pause(); currentAudioRef.current = null }
      if (playbackAudioRef.current) { playbackAudioRef.current.pause(); playbackAudioRef.current = null; setIsPlayingRecording(false) }

      setIsAiSpeaking(true)

      aiAudioChunksRef.current.push({ audio: audioBase64, format, timestamp: Date.now() })

      const audioData = atob(audioBase64)
      const audioBytes = new Uint8Array(audioData.length)
      for (let i = 0; i < audioData.length; i++) audioBytes[i] = audioData.charCodeAt(i)

      const blob = new Blob([audioBytes], { type: `audio/${format}` })
      const audioUrl = URL.createObjectURL(blob)
      currentAudioRef.current = new Audio(audioUrl)

      await new Promise((resolve, reject) => {
        if (!currentAudioRef.current) { setIsAiSpeaking(false); reject(new Error('Audio cleared')); return }
        currentAudioRef.current.onended = () => { URL.revokeObjectURL(audioUrl); currentAudioRef.current = null; setIsAiSpeaking(false); resolve() }
        currentAudioRef.current.onerror = (err) => { URL.revokeObjectURL(audioUrl); currentAudioRef.current = null; setIsAiSpeaking(false); reject(err) }
        currentAudioRef.current.play().catch((err) => { setIsAiSpeaking(false); reject(err) })
      })
    } catch (err) {
      console.error('Error playing audio:', err)
      setIsAiSpeaking(false)
      currentAudioRef.current = null
    }
  }, [])

  // ── Play question (audio or browser fallback) ──────────────────
  const playQuestion = useCallback(async (questionText, questionAudio, audioFormat) => {
    setPhase('listening')
    if (questionAudio) {
      await playAudio(questionAudio, audioFormat)
    } else {
      await speakWithBrowser(questionText)
    }
    setPhase('recording')
  }, [playAudio, speakWithBrowser])

  // ── Video recording ────────────────────────────────────────────
  const startFullInterviewRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 15, max: 20 } }
      })
      fullInterviewStreamRef.current = stream
      if (videoPreviewRef.current) { videoPreviewRef.current.srcObject = stream; videoPreviewRef.current.muted = true }

      const mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8,opus', videoBitsPerSecond: 250000 })
      fullInterviewRecorderRef.current = mediaRecorder
      fullInterviewChunksRef.current = []
      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) fullInterviewChunksRef.current.push(e.data) }
      mediaRecorder.start(1000)
    } catch (err) {
      console.error('Error starting full interview recording:', err)
    }
  }

  const stopFullInterviewRecording = async () => {
    return new Promise((resolve) => {
      if (fullInterviewRecorderRef.current && fullInterviewRecorderRef.current.state !== 'inactive') {
        fullInterviewRecorderRef.current.onstop = async () => {
          try {
            if (fullInterviewChunksRef.current.length > 0) {
              const videoBlob = new Blob(fullInterviewChunksRef.current, { type: 'video/webm' })
              if (videoBlob.size > 0) {
                const formData = new FormData()
                formData.append('video_file', videoBlob, 'interview_recording.webm')
                formData.append('email', interview.email || '')
                try {
                  await axios.post(`${API_BASE_URL}/candidates/interviews/${interview.interview_id}/async/upload-video`, formData, { headers: { 'Content-Type': 'multipart/form-data' } })
                } catch (err) { console.error('Error uploading video:', err) }
              }
            }
            if (aiAudioChunksRef.current.length > 0) {
              try {
                await axios.post(`${API_BASE_URL}/candidates/interviews/${interview.interview_id}/async/save-recording`, {
                  interview_id: interview.interview_id, email: interview.email || '', user_audio: '', ai_audio_chunks: aiAudioChunksRef.current
                })
              } catch (err) { console.error('Error saving AI audio chunks:', err) }
            }
          } catch (err) { console.error('Error processing recording:', err) }
          if (fullInterviewStreamRef.current) { fullInterviewStreamRef.current.getTracks().forEach(t => t.stop()); fullInterviewStreamRef.current = null }
          if (videoPreviewRef.current) videoPreviewRef.current.srcObject = null
          resolve()
        }
        fullInterviewRecorderRef.current.stop()
      } else {
        if (fullInterviewStreamRef.current) { fullInterviewStreamRef.current.getTracks().forEach(t => t.stop()); fullInterviewStreamRef.current = null }
        resolve()
      }
    })
  }

  // ── Start interview ────────────────────────────────────────────
  const startInterview = async () => {
    try {
      setIsLoading(true)
      setError('')
      await startFullInterviewRecording()

      const response = await axios.post(`${API_BASE_URL}/candidates/interviews/${interview.interview_id}/async/start`, {
        interview_id: interview.interview_id, email: interview.email || ''
      })

      const { question_text, question_audio, audio_format, question_number } = response.data

      setCurrentQuestion({ text: question_text, audio: question_audio, format: audio_format, number: question_number })
      setQuestionNumber(question_number)
      addMessage('interviewer', question_text)
      setIsLoading(false)

      await playQuestion(question_text, question_audio, audio_format)
    } catch (err) {
      console.error('Error starting interview:', err)
      const detail = err.response?.data?.detail || ''
      const isQuota = detail.toLowerCase().includes('quota') || detail.toLowerCase().includes('rate')
      setError(isQuota
        ? 'The AI service is temporarily busy. Please wait a minute and try again.'
        : detail || 'Failed to start interview')
      setIsLoading(false)
      setPhase('welcome')
    }
  }

  // ── Recording ──────────────────────────────────────────────────
  const startRecording = async () => {
    try {
      if (retryCount >= MAX_RETRIES) { setError(`Maximum retries (${MAX_RETRIES}) reached.`); return }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream)
      mediaRecorderRef.current = mediaRecorder
      audioChunksRef.current = []

      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data) }
      mediaRecorder.onstop = () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
        setRecordedAudio(audioBlob)
        if (recordedAudioUrl) URL.revokeObjectURL(recordedAudioUrl)
        setRecordedAudioUrl(URL.createObjectURL(audioBlob))
        stream.getTracks().forEach(t => t.stop())
        setPhase('review')
      }

      mediaRecorder.start()
      setPhase('recording')
      setRecordingTime(0)
      setError('')

      const startTime = Date.now()
      recordingIntervalRef.current = setInterval(() => {
        const elapsed = Date.now() - startTime
        setRecordingTime(elapsed)
        if (elapsed >= MAX_RECORDING_TIME) stopRecording()
      }, 100)
    } catch (err) {
      console.error('Error starting recording:', err)
      setError('Failed to access microphone. Please check permissions.')
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') mediaRecorderRef.current.stop()
    if (recordingIntervalRef.current) { clearInterval(recordingIntervalRef.current); recordingIntervalRef.current = null }
  }

  const retryRecording = () => {
    if (retryCount >= MAX_RETRIES) { setError(`Maximum retries (${MAX_RETRIES}) reached.`); return }
    if (playbackAudioRef.current) { playbackAudioRef.current.pause(); playbackAudioRef.current = null; setIsPlayingRecording(false) }
    if (recordedAudioUrl) { URL.revokeObjectURL(recordedAudioUrl); setRecordedAudioUrl(null) }
    setRetryCount(prev => prev + 1)
    setRecordedAudio(null)
    setRecordingTime(0)
    setError('')
    setPhase('recording')
  }

  const togglePlayback = () => {
    if (!recordedAudioUrl) return
    if (isPlayingRecording) {
      if (playbackAudioRef.current) { playbackAudioRef.current.pause(); setIsPlayingRecording(false) }
    } else {
      if (playbackAudioRef.current) { playbackAudioRef.current.play() } else {
        const audio = new Audio(recordedAudioUrl)
        playbackAudioRef.current = audio
        audio.onended = () => { setIsPlayingRecording(false); playbackAudioRef.current = null }
        audio.onerror = () => { setIsPlayingRecording(false); setError('Error playing back recording'); playbackAudioRef.current = null }
        audio.play()
      }
      setIsPlayingRecording(true)
    }
  }

  // ── Submit answer ──────────────────────────────────────────────
  const submitAnswer = async () => {
    if (!recordedAudio) { setError('Please record an answer first'); return }
    try {
      setPhase('submitting')
      setError('')

      if (playbackAudioRef.current) { playbackAudioRef.current.pause(); playbackAudioRef.current = null; setIsPlayingRecording(false) }
      if (currentAudioRef.current) { currentAudioRef.current.pause(); currentAudioRef.current = null; setIsAiSpeaking(false) }

      const reader = new FileReader()
      const audioBase64 = await new Promise((resolve, reject) => {
        reader.onload = () => resolve(reader.result.split(',')[1])
        reader.onerror = reject
        reader.readAsDataURL(recordedAudio)
      })

      const response = await axios.post(`${API_BASE_URL}/candidates/interviews/${interview.interview_id}/async/submit-answer`, {
        interview_id: interview.interview_id, email: interview.email || '', audio: audioBase64, question_number: questionNumber
      })

      // Add user's transcribed answer to conversation (shown as "Your answer")
      if (response.data.user_text) {
        addMessage('user', response.data.user_text)
      }

      if (response.data.status === 'completed') {
        await stopFullInterviewRecording()
        // Brief pause so candidate can see their last answer in the conversation
        await new Promise(r => setTimeout(r, 1500))
        setPhase('completed')
        setCurrentQuestion(null)
      } else {
        const { question_text, question_audio, audio_format, question_number } = response.data

        setCurrentQuestion({ text: question_text, audio: question_audio, format: audio_format, number: question_number })
        setQuestionNumber(question_number)
        setRetryCount(0)
        setRecordedAudio(null)
        setRecordingTime(0)
        if (recordedAudioUrl) { URL.revokeObjectURL(recordedAudioUrl); setRecordedAudioUrl(null) }
        if (playbackAudioRef.current) { playbackAudioRef.current.pause(); playbackAudioRef.current = null }
        setIsPlayingRecording(false)

        addMessage('interviewer', question_text)
        await playQuestion(question_text, question_audio, audio_format)
      }
    } catch (err) {
      console.error('Error submitting answer:', err)
      const detail = err.response?.data?.detail || ''
      const isQuota = detail.toLowerCase().includes('quota') || detail.toLowerCase().includes('rate')
      setError(isQuota
        ? 'The AI service is temporarily busy. Please wait a minute and try submitting again.'
        : detail || 'Failed to submit answer')
      setPhase('review')
    }
  }

  // ── End interview ──────────────────────────────────────────────
  const handleEndInterview = async () => {
    try {
      setIsLoading(true)
      await stopFullInterviewRecording()
      try {
        await axios.post(`${API_BASE_URL}/candidates/interviews/${interview.interview_id}/async/end`, {
          interview_id: interview.interview_id, email: interview.email || ''
        })
      } catch (err) { console.error('Error ending interview:', err) }
      setPhase('completed')
      setCurrentQuestion(null)
      setIsLoading(false)
    } catch (err) {
      console.error('Error ending interview:', err)
      cleanupResources()
      if (onClose) onClose()
    }
  }

  // ── Replay question ────────────────────────────────────────────
  const replayQuestion = async () => {
    if (!currentQuestion) return
    if (currentQuestion.audio) {
      await playAudio(currentQuestion.audio, currentQuestion.format)
    } else {
      await speakWithBrowser(currentQuestion.text)
    }
  }

  const addMessage = (sender, text) => {
    setConversation(prev => [...prev, { sender, text, timestamp: new Date() }])
  }

  const formatTime = (ms) => {
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${minutes}:${secs.toString().padStart(2, '0')}`
  }

  // ── Completed screen ──────────────────────────────────────────
  if (phase === 'completed') {
    return (
      <div className="async-interview">
        <div className="async-completed-screen">
          <div className="async-completed-icon">&#10003;</div>
          <h2>Interview Completed</h2>
          <p>Thank you for your participation! Our HR team will carefully review your interview and contact you soon.</p>
          <p className="async-completed-subtitle">We wish you the best of luck.</p>
          <button className="async-btn async-btn-primary" onClick={onClose} style={{ marginTop: '2rem', maxWidth: '280px' }}>
            Back to Jobs
          </button>
        </div>
      </div>
    )
  }

  // ── Welcome screen ────────────────────────────────────────────
  if (phase === 'welcome') {
    return (
      <div className="async-interview">
        <div className="async-welcome-screen">
          <div className="async-welcome-card">
            <div className="async-welcome-icon">
              <HiMicrophone />
            </div>
            <h2>Asynchronous Interview</h2>
            <p className="async-welcome-desc">
              You will be asked a series of questions. Listen to each question carefully,
              then record your answer. You can review and re-record before submitting.
            </p>
            <div className="async-welcome-tips">
              <div className="async-tip">
                <span className="async-tip-num">1</span>
                <span>Listen to the question</span>
              </div>
              <div className="async-tip">
                <span className="async-tip-num">2</span>
                <span>Record your answer</span>
              </div>
              <div className="async-tip">
                <span className="async-tip-num">3</span>
                <span>Review and submit</span>
              </div>
            </div>
            {error && <div className="async-error">{error}</div>}
            <button
              className="async-btn async-btn-primary async-btn-lg"
              onClick={startInterview}
              disabled={isLoading}
            >
              {isLoading ? (
                <><span className="async-spinner" /> Preparing...</>
              ) : (
                <>Start Interview <HiChevronRight /></>
              )}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ── Main interview screen ─────────────────────────────────────
  return (
    <div className="async-interview">
      {/* Camera preview (small, top-right) */}
      <div className="async-camera-pip">
        <video ref={videoPreviewRef} autoPlay muted playsInline />
      </div>

      {/* Top bar */}
      <div className="async-topbar">
        <div className="async-topbar-left">
          <span className="async-badge">Question {questionNumber}</span>
          {phase === 'recording' && <span className="async-badge async-badge-recording">Recording</span>}
          {phase === 'submitting' && <span className="async-badge async-badge-processing">Processing...</span>}
          {isAiSpeaking && <span className="async-badge async-badge-speaking">Speaking...</span>}
        </div>
        <button className="async-btn async-btn-danger async-btn-sm" onClick={handleEndInterview} disabled={isLoading}>
          End Interview
        </button>
      </div>

      {/* Main content area */}
      <div className="async-main">
        {/* Left: Conversation history */}
        <div className="async-sidebar">
          <h3 className="async-sidebar-title">Conversation</h3>
          <div className="async-messages">
            {conversation.map((msg, idx) => (
              <div key={idx} className={`async-msg async-msg-${msg.sender}`}>
                <span className="async-msg-role">{msg.sender === 'interviewer' ? 'Interviewer' : 'You'}</span>
                <span className="async-msg-content">{msg.text}</span>
              </div>
            ))}
            <div ref={conversationEndRef} />
          </div>
        </div>

        {/* Right: Question + Controls */}
        <div className="async-workspace">
          {/* Current question card */}
          {currentQuestion && (
            <div className="async-question-card">
              <div className="async-question-header">
                <HiSpeakerWave className="async-question-icon" />
                <span>Question {currentQuestion.number}</span>
                <button className="async-btn async-btn-ghost async-btn-sm" onClick={replayQuestion} disabled={isAiSpeaking} title="Replay question">
                  <HiArrowPath /> Replay
                </button>
              </div>
              <p className="async-question-text">{currentQuestion.text}</p>
              {isAiSpeaking && (
                <div className="async-speaking-indicator">
                  <span className="async-dot" /><span className="async-dot" /><span className="async-dot" />
                  <span>AI is speaking...</span>
                </div>
              )}
            </div>
          )}

          {error && <div className="async-error">{error}</div>}

          {/* Action area */}
          <div className="async-action-area">
            {/* Listening phase — waiting for AI to finish speaking */}
            {phase === 'listening' && (
              <div className="async-action-center">
                <div className="async-listening-animation">
                  <div className="async-wave" /><div className="async-wave" /><div className="async-wave" />
                </div>
                <p className="async-action-hint">Listening to the question...</p>
              </div>
            )}

            {/* Recording phase — ready to record or recording */}
            {phase === 'recording' && !recordedAudio && (
              <div className="async-action-center">
                {recordingTime === 0 ? (
                  <>
                    <button className="async-mic-btn" onClick={startRecording} disabled={isAiSpeaking}>
                      <HiMicrophone />
                    </button>
                    <p className="async-action-hint">
                      {isAiSpeaking ? 'Wait for the question to finish...' : 'Tap to start recording your answer'}
                    </p>
                  </>
                ) : (
                  <>
                    <button className="async-mic-btn async-mic-btn-active" onClick={stopRecording}>
                      <HiStop />
                    </button>
                    <div className="async-timer">{formatTime(recordingTime)} / {formatTime(MAX_RECORDING_TIME)}</div>
                    <p className="async-action-hint">Recording... tap to stop</p>
                  </>
                )}
              </div>
            )}

            {/* Review phase — playback, retry, submit */}
            {phase === 'review' && recordedAudio && (
              <div className="async-review-panel">
                <div className="async-review-info">
                  <HiCheck className="async-review-check" />
                  <span>Answer recorded ({formatTime(recordingTime)})</span>
                  <span className="async-retry-count">{retryCount}/{MAX_RETRIES} retries used</span>
                </div>
                <div className="async-review-actions">
                  <button className="async-btn async-btn-outline" onClick={togglePlayback}>
                    {isPlayingRecording ? <><HiPause /> Pause</> : <><HiPlay /> Listen</>}
                  </button>
                  <button className="async-btn async-btn-outline" onClick={retryRecording} disabled={retryCount >= MAX_RETRIES}>
                    <HiArrowPath /> Re-record
                  </button>
                  <button className="async-btn async-btn-primary" onClick={submitAnswer}>
                    <HiCheck /> Submit Answer
                  </button>
                </div>
              </div>
            )}

            {/* Submitting phase */}
            {phase === 'submitting' && (
              <div className="async-action-center">
                <span className="async-spinner async-spinner-lg" />
                <p className="async-action-hint">Processing your answer...</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default AsynchronousInterviewInterface
