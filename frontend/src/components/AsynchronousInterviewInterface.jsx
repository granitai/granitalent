import React, { useState, useEffect, useRef } from 'react'
import { HiMicrophone, HiStop, HiXMark, HiSpeakerWave, HiCheck, HiArrowPath, HiPower, HiPlay, HiPause } from 'react-icons/hi2'
import axios from 'axios'
import './AsynchronousInterviewInterface.css'

const API_BASE_URL = '/api'

const MAX_RECORDING_TIME = 60000 // 1 minute in milliseconds
const MAX_RETRIES = 3

function AsynchronousInterviewInterface({ interview, onClose }) {
  const [status, setStatus] = useState('Initializing...')
  const [conversation, setConversation] = useState([])
  const [currentQuestion, setCurrentQuestion] = useState(null)
  const [isRecording, setIsRecording] = useState(false)
  const [recordingTime, setRecordingTime] = useState(0)
  const [retryCount, setRetryCount] = useState(0)
  const [recordedAudio, setRecordedAudio] = useState(null)
  const [recordedAudioUrl, setRecordedAudioUrl] = useState(null)
  const [isPlayingRecording, setIsPlayingRecording] = useState(false)
  const [isAiSpeaking, setIsAiSpeaking] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [assessment, setAssessment] = useState(null)
  const [interviewCompleted, setInterviewCompleted] = useState(false)
  const [error, setError] = useState('')
  const [questionNumber, setQuestionNumber] = useState(0)

  // Provider/Model selection state
  const [providersConfig, setProvidersConfig] = useState(null)
  const [ttsProvider, setTtsProvider] = useState('')
  const [ttsModel, setTtsModel] = useState('')
  const [sttProvider, setSttProvider] = useState('')
  const [sttModel, setSttModel] = useState('')
  const [llmProvider, setLlmProvider] = useState('')
  const [llmModel, setLlmModel] = useState('')
  const [showProviderSelection, setShowProviderSelection] = useState(true)

  const mediaRecorderRef = useRef(null)
  const audioChunksRef = useRef([])
  const recordingIntervalRef = useRef(null)
  const audioContextRef = useRef(null)
  const currentAudioRef = useRef(null)
  const playbackAudioRef = useRef(null)
  const videoPreviewRef = useRef(null)

  // Full interview recording
  const fullInterviewRecorderRef = useRef(null)
  const fullInterviewChunksRef = useRef([])
  const fullInterviewStreamRef = useRef(null)
  const aiAudioChunksRef = useRef([]) // Store AI audio with timestamps

  useEffect(() => {
    loadProviders()
    // No longer start full interview recording - we'll record each answer separately
    return () => {
      cleanupResources()
    }
  }, [])

  const loadProviders = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/providers`)
      const config = response.data
      setProvidersConfig(config)

      // Set defaults - prefer GPT over Gemini to avoid quota issues
      setTtsProvider(config.defaults.tts_provider)
      setSttProvider(config.defaults.stt_provider)
      // Use GPT as default LLM to avoid Gemini quota issues, but allow user to change
      const defaultLlmProvider = config.defaults.llm_provider === 'gemini' ? 'gpt' : config.defaults.llm_provider
      setLlmProvider(defaultLlmProvider)

      // Set default models
      const ttsDefaultModel = config.tts[config.defaults.tts_provider]?.default_model
      const sttDefaultModel = config.stt[config.defaults.stt_provider]?.default_model
      const llmDefaultModel = config.llm[defaultLlmProvider]?.default_model

      if (ttsDefaultModel) setTtsModel(ttsDefaultModel)
      if (sttDefaultModel) setSttModel(sttDefaultModel)
      if (llmDefaultModel) setLlmModel(llmDefaultModel)
    } catch (error) {
      console.error('Failed to load providers:', error)
      // Set fallback defaults
      setTtsProvider('elevenlabs')
      setTtsModel('eleven_flash_v2_5')
      setSttProvider('elevenlabs')
      setSttModel('scribe_v1')
      setLlmProvider('gpt') // Use GPT instead of Gemini to avoid quota issues
      setLlmModel('gpt-4o-mini')
      setProvidersConfig({
        tts: {},
        stt: {},
        llm: {},
        defaults: { tts_provider: 'elevenlabs', stt_provider: 'elevenlabs', llm_provider: 'gpt' }
      })
    }
  }

  const handleProviderChange = (type, providerId) => {
    if (!providersConfig) return

    if (type === 'tts') {
      setTtsProvider(providerId)
      const defaultModel = providersConfig.tts[providerId]?.default_model
      if (defaultModel) setTtsModel(defaultModel)
    } else if (type === 'stt') {
      setSttProvider(providerId)
      const defaultModel = providersConfig.stt[providerId]?.default_model
      if (defaultModel) setSttModel(defaultModel)
    } else if (type === 'llm') {
      setLlmProvider(providerId)
      const defaultModel = providersConfig.llm[providerId]?.default_model
      if (defaultModel) setLlmModel(defaultModel)
    }
  }

  const cleanupResources = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    if (recordingIntervalRef.current) {
      clearInterval(recordingIntervalRef.current)
    }
    if (currentAudioRef.current) {
      currentAudioRef.current.pause()
      currentAudioRef.current = null
      setIsAiSpeaking(false)
    }
    if (playbackAudioRef.current) {
      playbackAudioRef.current.pause()
      playbackAudioRef.current = null
    }
    if (audioContextRef.current) {
      audioContextRef.current.close()
    }
    if (recordedAudioUrl) {
      URL.revokeObjectURL(recordedAudioUrl)
      setRecordedAudioUrl(null)
    }
  }

  const handleEndInterview = async () => {
    try {
      setStatus('Ending interview...')

      // Stop recording and upload video BEFORE marking as completed
      // This ensures we have the full recording
      await stopFullInterviewRecording()

      // Mark interview as completed and generate assessment
      // Audio segments are already saved during submit-answer, no need to save here
      try {
        const response = await axios.post(
          `${API_BASE_URL}/candidates/interviews/${interview.interview_id}/async/end`,
          {
            interview_id: interview.interview_id,
            email: interview.email || ''
          }
        )
        console.log('✅ Interview marked as completed')

        // If assessment was generated, show completion screen
        if (response.data.assessment) {
          // setAssessment(response.data.assessment) // Don't show assessment to candidate
          setInterviewCompleted(true)
          setStatus('Interview completed')
          setCurrentQuestion(null)
          addMessage('system', 'Interview ended.')
          // Don't close immediately - let user see the completion message
          return
        }
      } catch (err) {
        console.error('Error ending interview:', err)
        // Still continue to close even if endpoint fails
      }

      cleanupResources()
      if (onClose) {
        onClose()
      }
    } catch (err) {
      console.error('Error ending interview:', err)
      cleanupResources()
      if (onClose) {
        onClose()
      }
    }
  }

  const startFullInterviewRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true })
      fullInterviewStreamRef.current = stream

      // Show video preview
      if (videoPreviewRef.current) {
        videoPreviewRef.current.srcObject = stream
        videoPreviewRef.current.muted = true
      }

      const mediaRecorder = new MediaRecorder(stream, {
        mimeType: 'video/webm;codecs=vp8,opus'
      })
      fullInterviewRecorderRef.current = mediaRecorder
      fullInterviewChunksRef.current = []

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          fullInterviewChunksRef.current.push(event.data)
        }
      }

      mediaRecorder.start(1000) // Collect data every second
      console.log('🎥 Started full interview video recording')
    } catch (err) {
      console.error('Error starting full interview recording:', err)
      // Don't block interview if recording fails
    }
  }

  const stopFullInterviewRecording = async () => {
    return new Promise((resolve) => {
      if (fullInterviewRecorderRef.current && fullInterviewRecorderRef.current.state !== 'inactive') {
        fullInterviewRecorderRef.current.onstop = async () => {
          try {
            // Process video recording
            if (fullInterviewChunksRef.current.length > 0) {
              const videoBlob = new Blob(fullInterviewChunksRef.current, { type: 'video/webm' })

              if (videoBlob.size > 0) {
                console.log(`🎥 Video recording ready: ${videoBlob.size} bytes`)

                // Upload video
                const formData = new FormData()
                formData.append('video_file', videoBlob, 'interview_recording.webm')
                formData.append('email', interview.email || '')

                try {
                  setStatus('Uploading interview recording...')
                  await axios.post(
                    `${API_BASE_URL}/candidates/interviews/${interview.interview_id}/async/upload-video`,
                    formData,
                    {
                      headers: {
                        'Content-Type': 'multipart/form-data'
                      }
                    }
                  )
                  console.log('✅ Video uploaded successfully')
                } catch (err) {
                  console.error('Error uploading video:', err)
                  // Don't fail the whole process if video upload fails
                }
              }
            }

            // We still want to process the audio aggregation if needed, but the original code 
            // was trying to combine user audio strings. Since we now have a video file, 
            // the backend might not need this complex audio combination logic if we are relying on video.
            // However, to preserve existing functionality (audio segments for transcript), we keep passing AI chunks if needed.
            // But we don't need to save the "combined" audio anymore since we have the video.
            // The original logic was complex creating a blob from chunks and sending base64. 
            // We can simplify this or leave it as a backup. 
            // For now, let's keep the AI chunks saving just in case, but skip the user audio base64 part 
            // since we are uploading the full video.

            if (aiAudioChunksRef.current && aiAudioChunksRef.current.length > 0) {
              try {
                await axios.post(
                  `${API_BASE_URL}/candidates/interviews/${interview.interview_id}/async/save-recording`,
                  {
                    interview_id: interview.interview_id,
                    email: interview.email || '',
                    user_audio: '',  // We uploaded video separately
                    ai_audio_chunks: aiAudioChunksRef.current
                  }
                )
                console.log('✅ AI audio chunks saved')
              } catch (err) {
                console.error('Error saving AI audio chunks:', err)
              }
            }

          } catch (err) {
            console.error('Error processing interview recording:', err)
          }

          // Clean up stream
          if (fullInterviewStreamRef.current) {
            fullInterviewStreamRef.current.getTracks().forEach(track => track.stop())
            fullInterviewStreamRef.current = null
          }

          if (videoPreviewRef.current) {
            videoPreviewRef.current.srcObject = null
          }

          resolve()
        }

        fullInterviewRecorderRef.current.stop()
      } else {
        // Recorder wasn't active
        if (fullInterviewStreamRef.current) {
          fullInterviewStreamRef.current.getTracks().forEach(track => track.stop())
          fullInterviewStreamRef.current = null
        }
        resolve()
      }
    })
  }

  const startInterview = async () => {
    if (!ttsProvider || !sttProvider || !llmProvider) {
      setError('Please select all providers before starting the interview')
      return
    }

    try {
      setStatus('Starting interview...')
      setShowProviderSelection(false)

      // Request media permissions and start recording immediately
      await startFullInterviewRecording()

      const response = await axios.post(
        `${API_BASE_URL}/candidates/interviews/${interview.interview_id}/async/start`,
        {
          interview_id: interview.interview_id,
          email: interview.email || '',
          tts_provider: ttsProvider,
          tts_model: ttsModel,
          stt_provider: sttProvider,
          stt_model: sttModel,
          llm_provider: llmProvider,
          llm_model: llmModel
        }
      )

      const { question_text, question_audio, audio_format, question_number, resumed } = response.data

      setCurrentQuestion({
        text: question_text,
        audio: question_audio,
        format: audio_format,
        number: question_number
      })
      setQuestionNumber(question_number)

      addMessage('interviewer', question_text)
      setStatus(resumed ? 'Resumed interview - Question ready' : 'Question ready')

      // Play the question audio if available (not resumed)
      if (question_audio) {
        await playAudio(question_audio, audio_format)
      }

      setStatus('Ready to record')
    } catch (err) {
      console.error('Error starting interview:', err)
      setError(err.response?.data?.detail || 'Failed to start interview')
      setStatus('Error')
    }
  }

  const playAudio = async (audioBase64, format = 'mp3') => {
    try {
      // Stop any currently playing audio (including question audio and playback audio)
      if (currentAudioRef.current) {
        currentAudioRef.current.pause()
        currentAudioRef.current = null
      }
      if (playbackAudioRef.current) {
        playbackAudioRef.current.pause()
        playbackAudioRef.current = null
        setIsPlayingRecording(false)
      }

      // Set AI speaking state to true
      setIsAiSpeaking(true)

      // Store AI audio chunk with timestamp for recording
      const timestamp = Date.now()
      aiAudioChunksRef.current.push({
        audio: audioBase64,
        format: format,
        timestamp: timestamp
      })

      const audioData = atob(audioBase64)
      const audioBytes = new Uint8Array(audioData.length)
      for (let i = 0; i < audioData.length; i++) {
        audioBytes[i] = audioData.charCodeAt(i)
      }

      const blob = new Blob([audioBytes], { type: `audio/${format}` })
      const audioUrl = URL.createObjectURL(blob)

      currentAudioRef.current = new Audio(audioUrl)

      // Clean up URL after audio ends
      currentAudioRef.current.onended = () => {
        URL.revokeObjectURL(audioUrl)
        currentAudioRef.current = null
        setIsAiSpeaking(false)
      }

      currentAudioRef.current.onerror = () => {
        URL.revokeObjectURL(audioUrl)
        currentAudioRef.current = null
        setIsAiSpeaking(false)
      }

      await new Promise((resolve, reject) => {
        if (!currentAudioRef.current) {
          setIsAiSpeaking(false)
          reject(new Error('Audio element was cleared'))
          return
        }
        currentAudioRef.current.onended = () => {
          URL.revokeObjectURL(audioUrl)
          currentAudioRef.current = null
          setIsAiSpeaking(false)
          resolve()
        }
        currentAudioRef.current.onerror = (err) => {
          URL.revokeObjectURL(audioUrl)
          currentAudioRef.current = null
          setIsAiSpeaking(false)
          reject(err)
        }
        currentAudioRef.current.play().catch((err) => {
          setIsAiSpeaking(false)
          reject(err)
        })
      })
    } catch (err) {
      console.error('Error playing audio:', err)
      setIsAiSpeaking(false)
      if (currentAudioRef.current) {
        currentAudioRef.current = null
      }
    }
  }

  const startRecording = async () => {
    try {
      if (retryCount >= MAX_RETRIES) {
        setError(`Maximum retries (${MAX_RETRIES}) reached for this question. Please submit your current recording.`)
        return
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream)
      mediaRecorderRef.current = mediaRecorder
      audioChunksRef.current = []

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
        }
      }

      mediaRecorder.onstop = () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
        setRecordedAudio(audioBlob)

        // Create URL for playback
        if (recordedAudioUrl) {
          URL.revokeObjectURL(recordedAudioUrl)
        }
        const audioUrl = URL.createObjectURL(audioBlob)
        setRecordedAudioUrl(audioUrl)

        stream.getTracks().forEach(track => track.stop())
      }

      mediaRecorder.start()
      setIsRecording(true)
      setStatus('Recording...')
      setRecordingTime(0)
      setError('')

      // Start timer
      const startTime = Date.now()
      recordingIntervalRef.current = setInterval(() => {
        const elapsed = Date.now() - startTime
        setRecordingTime(elapsed)

        if (elapsed >= MAX_RECORDING_TIME) {
          stopRecording()
        }
      }, 100)
    } catch (err) {
      console.error('Error starting recording:', err)
      setError('Failed to access microphone. Please check permissions.')
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    if (recordingIntervalRef.current) {
      clearInterval(recordingIntervalRef.current)
      recordingIntervalRef.current = null
    }
    setIsRecording(false)
    setStatus('Recording stopped')
  }

  const retryRecording = () => {
    if (retryCount >= MAX_RETRIES) {
      setError(`Maximum retries (${MAX_RETRIES}) reached. Please submit your current recording.`)
      return
    }

    // Stop any playing audio
    if (playbackAudioRef.current) {
      playbackAudioRef.current.pause()
      playbackAudioRef.current = null
      setIsPlayingRecording(false)
    }

    // Clean up audio URL
    if (recordedAudioUrl) {
      URL.revokeObjectURL(recordedAudioUrl)
      setRecordedAudioUrl(null)
    }

    setRetryCount(prev => prev + 1)
    setRecordedAudio(null)
    setRecordingTime(0)
    setError('')
    setStatus('Ready to record')
  }

  const togglePlayback = () => {
    if (!recordedAudioUrl) return

    if (isPlayingRecording) {
      // Pause playback
      if (playbackAudioRef.current) {
        playbackAudioRef.current.pause()
        setIsPlayingRecording(false)
      }
    } else {
      // Start playback
      if (playbackAudioRef.current) {
        playbackAudioRef.current.play()
      } else {
        const audio = new Audio(recordedAudioUrl)
        playbackAudioRef.current = audio

        audio.onended = () => {
          setIsPlayingRecording(false)
          playbackAudioRef.current = null
        }

        audio.onerror = () => {
          setIsPlayingRecording(false)
          setError('Error playing back recording')
          playbackAudioRef.current = null
        }

        audio.play()
      }
      setIsPlayingRecording(true)
    }
  }

  const submitAnswer = async () => {
    if (!recordedAudio) {
      setError('Please record an answer first')
      return
    }

    // Prevent multiple simultaneous submissions
    if (isSubmitting) {
      return
    }

    try {
      setIsSubmitting(true)
      setStatus('Processing answer...')
      setError('')

      // Stop any playing audio before submitting
      if (playbackAudioRef.current) {
        playbackAudioRef.current.pause()
        playbackAudioRef.current = null
        setIsPlayingRecording(false)
      }
      if (currentAudioRef.current) {
        currentAudioRef.current.pause()
        currentAudioRef.current = null
        setIsAiSpeaking(false)
      }

      // Convert audio to base64
      const reader = new FileReader()
      const audioBase64 = await new Promise((resolve, reject) => {
        reader.onload = () => {
          const base64 = reader.result.split(',')[1]
          resolve(base64)
        }
        reader.onerror = reject
        reader.readAsDataURL(recordedAudio)
      })

      const response = await axios.post(
        `${API_BASE_URL}/candidates/interviews/${interview.interview_id}/async/submit-answer`,
        {
          interview_id: interview.interview_id,
          email: interview.email || '',
          audio: audioBase64,
          question_number: questionNumber
        }
      )

      if (response.data.status === 'completed') {
        // Interview completed - stop recording and save video
        await stopFullInterviewRecording()

        setInterviewCompleted(true)
        setStatus('Interview completed')
        setCurrentQuestion(null)
        addMessage('system', 'Interview completed.')
        setIsSubmitting(false)
      } else {
        // Next question
        const { question_text, question_audio, audio_format, question_number } = response.data

        setCurrentQuestion({
          text: question_text,
          audio: question_audio,
          format: audio_format,
          number: question_number
        })
        setQuestionNumber(question_number)
        setRetryCount(0)
        setRecordedAudio(null)
        setRecordingTime(0)

        // Clean up audio URL
        if (recordedAudioUrl) {
          URL.revokeObjectURL(recordedAudioUrl)
          setRecordedAudioUrl(null)
        }
        if (playbackAudioRef.current) {
          playbackAudioRef.current.pause()
          playbackAudioRef.current = null
        }
        setIsPlayingRecording(false)

        addMessage('interviewer', question_text)
        setStatus('Question ready')

        // Play the question audio (only once)
        if (question_audio) {
          await playAudio(question_audio, audio_format)
        }

        setStatus('Ready to record')
        setIsSubmitting(false)
      }
    } catch (err) {
      console.error('Error submitting answer:', err)
      setError(err.response?.data?.detail || 'Failed to submit answer')
      setStatus('Error')
      setIsSubmitting(false)
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

  if (interviewCompleted) {
    return (
      <div className="async-interview-interface">
        <div className="async-interview-header">
          <h2>Interview Completed</h2>
          <button className="async-close-btn" onClick={onClose} title="Close">
            <HiXMark />
          </button>
        </div>
        <div className="async-interview-content">
          <div className="async-assessment-section" style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '300px' }}>
            <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>🎉</div>
            <h3 style={{ marginBottom: '1rem' }}>Thank Your for Your Time!</h3>
            <p className="async-assessment-text" style={{ fontSize: '1.2rem', maxWidth: '600px' }}>
              The interview is done. An HR representative will contact you very soon.
            </p>
            <button
              className="async-start-interview-btn"
              onClick={onClose}
              style={{ marginTop: '2rem', maxWidth: '300px' }}
            >
              Back to Candidates
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (assessment && !interviewCompleted) {
    // This block is kept just in case, but logically we should use interviewCompleted now
    // If we want to strictly hide it, we can remove this block or redirect it to interviewCompleted logic
    return null;
  }

  return (
    <div className="async-interview-interface">
      <div className="async-interview-header">
        <h2>Asynchronous Interview</h2>
        <div className="async-header-actions">
          <button
            className="async-end-btn"
            onClick={handleEndInterview}
            title="End Interview"
          >
            <HiPower className="icon" />
            <span>End Interview</span>
          </button>
          <button className="async-close-btn" onClick={onClose} title="Close">
            <HiXMark />
          </button>
        </div>
      </div>

      <div className="async-interview-content">
        {/* Video Preview */}
        <div className="video-preview-container" style={{ textAlign: 'center', marginBottom: '1rem', display: 'flex', justifyContent: 'center' }}>
          <video
            ref={videoPreviewRef}
            autoPlay
            muted
            playsInline
            style={{
              width: '100%',
              maxWidth: '320px',
              borderRadius: '12px',
              boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
              backgroundColor: '#2d3748',
              aspectRatio: '16/9',
              objectFit: 'cover'
            }}
          />
        </div>

        <div className="async-status-bar">
          <span className={`async-status ${status.toLowerCase().replace(/\s+/g, '-')}`}>
            {status}
          </span>
          {currentQuestion && (
            <span className="async-question-number">Question {currentQuestion.number}</span>
          )}
        </div>

        {error && (
          <div className="async-error-message">
            {error}
          </div>
        )}

        {showProviderSelection && !currentQuestion && providersConfig && (
          <div className="async-provider-selection">
            <h3>Select AI Providers</h3>
            <p className="provider-selection-hint">Choose the AI models you want to use for this interview</p>

            <div className="provider-selectors-grid">
              <div className="provider-selector-group">
                <label>Text-to-Speech (TTS) Provider</label>
                <select
                  value={ttsProvider}
                  onChange={(e) => handleProviderChange('tts', e.target.value)}
                >
                  {Object.entries(providersConfig.tts || {}).map(([id, config]) => (
                    <option key={id} value={id}>{config.name}</option>
                  ))}
                </select>
              </div>

              <div className="provider-selector-group">
                <label>TTS Model</label>
                <select
                  value={ttsModel}
                  onChange={(e) => setTtsModel(e.target.value)}
                  disabled={!ttsProvider}
                >
                  {providersConfig.tts?.[ttsProvider]?.models.map((model) => (
                    <option key={model.id} value={model.id}>{model.name}</option>
                  ))}
                </select>
              </div>

              <div className="provider-selector-group">
                <label>Speech-to-Text (STT) Provider</label>
                <select
                  value={sttProvider}
                  onChange={(e) => handleProviderChange('stt', e.target.value)}
                >
                  {Object.entries(providersConfig.stt || {}).map(([id, config]) => (
                    <option key={id} value={id}>{config.name}</option>
                  ))}
                </select>
              </div>

              <div className="provider-selector-group">
                <label>STT Model</label>
                <select
                  value={sttModel}
                  onChange={(e) => setSttModel(e.target.value)}
                  disabled={!sttProvider}
                >
                  {providersConfig.stt?.[sttProvider]?.models.map((model) => (
                    <option key={model.id} value={model.id}>{model.name}</option>
                  ))}
                </select>
              </div>

              <div className="provider-selector-group">
                <label>Language Model (LLM) Provider</label>
                <select
                  value={llmProvider}
                  onChange={(e) => handleProviderChange('llm', e.target.value)}
                >
                  {Object.entries(providersConfig.llm || {}).map(([id, config]) => (
                    <option key={id} value={id}>{config.name}</option>
                  ))}
                </select>
              </div>

              <div className="provider-selector-group">
                <label>LLM Model</label>
                <select
                  value={llmModel}
                  onChange={(e) => setLlmModel(e.target.value)}
                  disabled={!llmProvider}
                >
                  {providersConfig.llm?.[llmProvider]?.models.map((model) => (
                    <option key={model.id} value={model.id}>{model.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <button
              className="async-start-interview-btn"
              onClick={startInterview}
              disabled={!ttsProvider || !sttProvider || !llmProvider || !ttsModel || !sttModel || !llmModel}
            >
              Start Interview
            </button>
          </div>
        )}

        {currentQuestion && (
          <div className="async-question-section">
            <div className="async-question-text">
              <HiSpeakerWave className="icon" />
              <p>{currentQuestion.text}</p>
            </div>
          </div>
        )}

        <div className="async-recording-section">
          {!recordedAudio ? (
            <div className="async-recording-controls">
              {!isRecording ? (
                <button
                  className="async-record-btn"
                  onClick={startRecording}
                  disabled={!currentQuestion || isAiSpeaking || isSubmitting}
                  title={isAiSpeaking ? 'Please wait for the AI to finish speaking' : ''}
                >
                  <HiMicrophone className="icon" />
                  <span>Start Recording</span>
                </button>
              ) : (
                <button
                  className="async-stop-btn"
                  onClick={stopRecording}
                >
                  <HiStop className="icon" />
                  <span>Stop Recording</span>
                </button>
              )}

              {isRecording && (
                <div className="async-recording-timer">
                  {formatTime(recordingTime)} / {formatTime(MAX_RECORDING_TIME)}
                </div>
              )}
            </div>
          ) : (
            <div className="async-recorded-audio-section">
              <div className="async-audio-info">
                <span>✓ Recording saved ({formatTime(recordingTime)})</span>
                <span className="async-retry-info">Retries: {retryCount} / {MAX_RETRIES}</span>
              </div>
              <div className="async-audio-actions">
                <button
                  className="async-play-btn"
                  onClick={togglePlayback}
                  title={isPlayingRecording ? 'Pause playback' : 'Play recording'}
                >
                  {isPlayingRecording ? <HiPause className="icon" /> : <HiPlay className="icon" />}
                  <span>{isPlayingRecording ? 'Pause' : 'Play'}</span>
                </button>
                <button
                  className="async-retry-btn"
                  onClick={retryRecording}
                  disabled={retryCount >= MAX_RETRIES}
                >
                  <HiArrowPath />
                  <span>Retry</span>
                </button>
                <button
                  className="async-submit-btn"
                  onClick={submitAnswer}
                  disabled={isSubmitting}
                >
                  <HiCheck />
                  <span>{isSubmitting ? 'Submitting...' : 'Submit Answer'}</span>
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="async-conversation-history">
          <h3>Conversation</h3>
          <div className="async-messages">
            {conversation.map((msg, idx) => (
              <div key={idx} className={`async-message ${msg.sender}`}>
                {msg.text}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default AsynchronousInterviewInterface

