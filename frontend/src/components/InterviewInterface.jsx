import React, { useState, useEffect, useRef } from 'react'
import { HiMicrophone, HiStop, HiXMark, HiSpeakerWave, HiVideoCamera } from 'react-icons/hi2'
import axios from 'axios'
import './InterviewInterface.css'

// URLs dynamiques basées sur l'emplacement actuel
// Fonctionne en développement (localhost) et en production (IP du serveur)
const getWebSocketURL = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}/ws`
}

const WS_URL = getWebSocketURL()
const API_BASE_URL = '/api'

// ================================================================
// PCM Player — streams 24kHz PCM audio from Gemini Live API
// ================================================================
class PCMPlayer {
  constructor() {
    this.ctx = null
    this.nextTime = 0
    this.sources = []
    this.gainNode = null
    this.preBuffer = []       // Accumulate chunks before playing
    this.preBufferSamples = 0
    this.buffering = true     // Pre-buffering until we have enough data
    this.MIN_BUFFER = 9600    // 400ms at 24kHz — accumulate before first play
  }

  init() {
    if (this.ctx) return
    this.ctx = new AudioContext()
    this.gainNode = this.ctx.createGain()
    this.gainNode.connect(this.ctx.destination)
    if (this.ctx.state === 'suspended') {
      this.ctx.resume()
    }
  }

  feed(pcmBase64) {
    if (!this.ctx || !this.gainNode) this.init()

    const binary = atob(pcmBase64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    const int16 = new Int16Array(bytes.buffer)
    const float32 = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768.0

    if (this.buffering) {
      // Accumulate chunks until we have ~400ms of audio
      this.preBuffer.push(float32)
      this.preBufferSamples += float32.length
      if (this.preBufferSamples >= this.MIN_BUFFER) {
        this.buffering = false
        // Schedule all buffered chunks starting slightly in the future
        this.nextTime = this.ctx.currentTime + 0.05
        for (const chunk of this.preBuffer) {
          this._schedule(chunk)
        }
        this.preBuffer = []
        this.preBufferSamples = 0
      }
      return
    }
    this._schedule(float32)
  }

  _schedule(float32) {
    const buf = this.ctx.createBuffer(1, float32.length, 24000)
    buf.getChannelData(0).set(float32)

    const src = this.ctx.createBufferSource()
    src.buffer = buf
    src.connect(this.gainNode)

    const now = this.ctx.currentTime
    if (this.nextTime < now) {
      this.nextTime = now + 0.05
    }
    src.start(this.nextTime)
    this.nextTime += buf.duration

    this.sources.push(src)
    src.onended = () => {
      const idx = this.sources.indexOf(src)
      if (idx >= 0) this.sources.splice(idx, 1)
    }
  }

  stop() {
    for (const s of this.sources) {
      try { s.stop() } catch {}
    }
    this.sources = []
    this.preBuffer = []
    this.preBufferSamples = 0
    this.buffering = true
    this.nextTime = 0
  }

  isPlaying() {
    return this.sources.length > 0 || this.preBuffer.length > 0
  }

  close() {
    this.stop()
    if (this.ctx) {
      this.ctx.close().catch(() => {})
      this.ctx = null
    }
  }
}

// Voice Activity Detection settings - Optimized for real-time conversation
const SILENCE_THRESHOLD = 30  // Volume below this = silence
const MIN_SPEECH_VOLUME = 35  // Minimum volume to consider as actual speech (filters ambient noise)
const SILENCE_DURATION = 2500  // 2.5s of silence before stopping — gives candidate time to think
const SPEECH_MIN_DURATION = 400  // Minimum 400ms of speech to be valid
const MAX_RECORDING_DURATION = 60000  // 60 seconds max per answer
const RESPONSE_DEBOUNCE_MS = 1000  // Prevent processing duplicate responses within 1 second
const FORCE_STOP_AFTER_MS = 45000  // Failsafe: force stop recording after 45 seconds
const LOW_ACTIVITY_TIMEOUT_MS = 8000  // If no strong speech detected for 8 seconds, stop

function InterviewInterface({ interview, onClose }) {
  const [connected, setConnected] = useState(false)
  const [conversation, setConversation] = useState([])
  const [currentPhase, setCurrentPhase] = useState('')
  const [status, setStatus] = useState('Loading providers...')
  const [statusClass, setStatusClass] = useState('connecting')
  const [isRecording, setIsRecording] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [error, setError] = useState('')
  const [assessment, setAssessment] = useState(null)
  const [isEndingInterview, setIsEndingInterview] = useState(false)
  const [timeRemaining, setTimeRemaining] = useState(null) // in seconds
  const [timeLimitMinutes, setTimeLimitMinutes] = useState(null)

  // Provider config state
  const [providersConfig, setProvidersConfig] = useState(null)

  const wsRef = useRef(null)
  const audioContextRef = useRef(null)
  const analyserRef = useRef(null)
  const mediaStreamRef = useRef(null)
  const mediaRecorderRef = useRef(null)
  const audioChunksRef = useRef([])
  const currentAudioRef = useRef(null)
  const conversationIdRef = useRef(null)
  const vadIntervalRef = useRef(null)
  const silenceStartRef = useRef(null)
  const speechStartRef = useRef(null)
  const recordingStartTimeRef = useRef(null)
  const streamingStartedRef = useRef(false)
  const isStreamingModeRef = useRef(false)
  const countdownIntervalRef = useRef(null)
  const isAudioPlayingRef = useRef(false)
  const pendingListenRef = useRef(false)
  // Refs to track state values inside setInterval (avoid stale closure)
  const isListeningRef = useRef(false)
  const isRecordingRef = useRef(false)
  const lastResponseTimeRef = useRef(0)  // Track last response time to prevent duplicates
  const lastResponseTextRef = useRef('')  // Track last response text to prevent duplicates
  const processingResponseRef = useRef(false)  // Prevent concurrent response processing
  const sendingAudioRef = useRef(false)  // Prevent duplicate audio sends
  const lastAudioSendTimeRef = useRef(0)  // Track last audio send time
  const audioQueueRef = useRef([])  // Queue for audio playback to prevent overlaps
  const isPlayingQueueRef = useRef(false)  // Whether we're currently playing from queue
  const lastStrongSpeechRef = useRef(null)  // Track last strong speech for failsafe

  // Snapshot capture refs (periodic screenshots for identity verification)
  const snapshotStreamRef = useRef(null)
  const snapshotCanvasRef = useRef(null)
  const snapshotIntervalRef = useRef(null)
  const snapshotsRef = useRef([])  // array of {timestamp, dataUrl}
  const videoPreviewRef = useRef(null)

  // PCM capture refs for streaming STT (avoids server-side WebM→PCM conversion)
  const pcmWorkerRef = useRef(null)
  const pcmBufferRef = useRef([])

  // Gemini Live mode refs (always live mode for real-time)
  const isLiveModeRef = useRef(true)
  const pcmPlayerRef = useRef(null)
  const liveFlushIntervalRef = useRef(null)
  const [liveVoice, setLiveVoice] = useState('Kore')
  const [isUserSpeaking, setIsUserSpeaking] = useState(false)

  // Load providers on mount
  useEffect(() => {
    loadProviders()
  }, [])

  // Connect WebSocket when providers are loaded and interview is ready
  useEffect(() => {
    if (!providersConfig) return
    if (!interview || !interview.interview_id) {
      setError('Invalid interview data. Please try again.')
      return
    }

    if (!interview.application_id && !interview.interview_id) {
      setError('Missing interview information. Please contact support.')
      return
    }

    // Don't auto-connect - wait for user to start
    updateStatus('Ready to start', '')

    return () => {
      cleanupResources()
    }
  }, [providersConfig, interview])

  const loadProviders = async () => {
    try {
      updateStatus('Loading...', 'connecting')
      const response = await axios.get(`${API_BASE_URL}/providers`)
      const config = response.data
      setProvidersConfig(config)

      // Set default voice from config
      if (config.gemini_live?.default_voice) {
        setLiveVoice(config.gemini_live.default_voice)
      }

      updateStatus('Ready to start', '')
    } catch (error) {
      console.error('Failed to load providers:', error)
      updateStatus('Failed to load - using defaults', 'error')
      setProvidersConfig({ gemini_live: { voices: [{ id: 'Kore', name: 'Kore — Clear & Professional' }], default_voice: 'Kore' } })
    }
  }

  const cleanupResources = () => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop())
      mediaStreamRef.current = null
    }

    // Clean up snapshot capture stream
    if (snapshotIntervalRef.current) {
      clearInterval(snapshotIntervalRef.current)
      snapshotIntervalRef.current = null
    }
    if (snapshotStreamRef.current) {
      snapshotStreamRef.current.getTracks().forEach(track => track.stop())
      snapshotStreamRef.current = null
    }
    if (videoPreviewRef.current) {
      videoPreviewRef.current.srcObject = null
    }

    if (audioContextRef.current) {
      audioContextRef.current.close()
      audioContextRef.current = null
    }

    if (vadIntervalRef.current) {
      clearInterval(vadIntervalRef.current)
      vadIntervalRef.current = null
    }

    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current)
      countdownIntervalRef.current = null
    }

    stopPcmFlush()
    pcmBufferRef.current = []

    // Clean up live mode resources
    if (liveFlushIntervalRef.current) {
      clearInterval(liveFlushIntervalRef.current)
      liveFlushIntervalRef.current = null
    }
    if (pcmPlayerRef.current) {
      pcmPlayerRef.current.close()
      pcmPlayerRef.current = null
    }

    stopCurrentAudio()
    isAudioPlayingRef.current = false
    pendingListenRef.current = false
  }

  // ========== GEMINI LIVE STREAMING ==========
  const startLiveStreaming = () => {
    console.log('🎙️ Starting live PCM streaming to Gemini...')

    // Ensure audio context and PCM capture are initialized
    // (initAudioContext should already have been called in connectWebSocket)

    // Flush PCM buffer to server every 100ms for low latency
    liveFlushIntervalRef.current = setInterval(() => {
      if (pcmBufferRef.current.length === 0) return
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return

      // Merge all buffered PCM chunks
      const totalLength = pcmBufferRef.current.reduce((sum, buf) => sum + buf.byteLength, 0)
      if (totalLength === 0) return

      const merged = new Uint8Array(totalLength)
      let offset = 0
      for (const buf of pcmBufferRef.current) {
        merged.set(new Uint8Array(buf), offset)
        offset += buf.byteLength
      }
      pcmBufferRef.current = []

      // Convert to base64
      let binary = ''
      for (let i = 0; i < merged.length; i++) {
        binary += String.fromCharCode(merged[i])
      }
      const base64Audio = btoa(binary)

      // Send to server
      try {
        wsRef.current.send(JSON.stringify({
          type: 'live_audio',
          audio: base64Audio,
        }))
      } catch (e) {
        console.error('Error sending live audio:', e)
      }
    }, 100) // 100ms flush interval for real-time feel
  }

  // ========== SNAPSHOT CAPTURE FUNCTIONS ==========
  const SNAPSHOT_INTERVAL_MS = 20000  // Capture a snapshot every 20 seconds

  const startSnapshotCapture = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 320 },
          height: { ideal: 240 },
          frameRate: { ideal: 5, max: 10 }
        }
      })
      snapshotStreamRef.current = stream

      // Show video preview
      if (videoPreviewRef.current) {
        videoPreviewRef.current.srcObject = stream
        videoPreviewRef.current.muted = true
      }

      // Create canvas for capturing frames
      const canvas = document.createElement('canvas')
      canvas.width = 320
      canvas.height = 240
      snapshotCanvasRef.current = canvas
      snapshotsRef.current = []

      // Capture first snapshot immediately
      captureSnapshot()

      // Then capture periodically
      snapshotIntervalRef.current = setInterval(captureSnapshot, SNAPSHOT_INTERVAL_MS)
      console.log('📸 Started periodic snapshot capture (every 20s)')
    } catch (err) {
      console.error('Error starting snapshot capture:', err)
      // Don't block interview if camera fails
    }
  }

  const captureSnapshot = () => {
    const video = videoPreviewRef.current
    const canvas = snapshotCanvasRef.current
    if (!video || !canvas || !snapshotStreamRef.current) return

    try {
      const ctx = canvas.getContext('2d')
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
      const dataUrl = canvas.toDataURL('image/jpeg', 0.7)
      snapshotsRef.current.push({
        timestamp: new Date().toISOString(),
        dataUrl
      })
      console.log(`📸 Snapshot captured (${snapshotsRef.current.length} total)`)
    } catch (err) {
      console.error('Error capturing snapshot:', err)
    }
  }

  const stopSnapshotCapture = async () => {
    // Stop interval
    if (snapshotIntervalRef.current) {
      clearInterval(snapshotIntervalRef.current)
      snapshotIntervalRef.current = null
    }

    // Capture one final snapshot
    captureSnapshot()

    // Upload snapshots
    if (snapshotsRef.current.length > 0) {
      try {
        updateStatus('Uploading verification snapshots...', 'connecting')
        await axios.post(
          `${API_BASE_URL}/candidates/interviews/${interview.interview_id}/snapshots`,
          {
            email: interview?.email || interview?.candidate_email || '',
            snapshots: snapshotsRef.current.map(s => ({
              timestamp: s.timestamp,
              image: s.dataUrl.split(',')[1]  // Send base64 without data URI prefix
            }))
          }
        )
        console.log(`✅ ${snapshotsRef.current.length} snapshots uploaded`)
      } catch (err) {
        console.error('Error uploading snapshots:', err)
      }
    }

    // Clean up stream
    if (snapshotStreamRef.current) {
      snapshotStreamRef.current.getTracks().forEach(track => track.stop())
      snapshotStreamRef.current = null
    }
    if (videoPreviewRef.current) {
      videoPreviewRef.current.srcObject = null
    }
    snapshotsRef.current = []
  }

  const initAudioContext = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      })
      mediaStreamRef.current = stream

      const audioContext = new (window.AudioContext || window.webkitAudioContext)()
      audioContextRef.current = audioContext

      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 512
      analyser.smoothingTimeConstant = 0.5
      analyserRef.current = analyser

      const microphone = audioContext.createMediaStreamSource(stream)
      microphone.connect(analyser)

      // Set up PCM capture for streaming STT (bypasses server-side WebM→PCM conversion)
      // Use ScriptProcessorNode to capture raw float32 samples, downsample to 16kHz 16-bit PCM
      const bufferSize = 4096
      const processorNode = audioContext.createScriptProcessor(bufferSize, 1, 1)
      const targetSampleRate = 16000
      const sourceSampleRate = audioContext.sampleRate

      processorNode.onaudioprocess = (e) => {
        // In live mode, always capture PCM. In classic mode, only during recording.
        if (!isLiveModeRef.current && (!isRecordingRef.current || !isStreamingModeRef.current)) return

        const inputData = e.inputBuffer.getChannelData(0)

        // Downsample from source rate to 16kHz
        const ratio = sourceSampleRate / targetSampleRate
        const newLength = Math.floor(inputData.length / ratio)
        const int16Array = new Int16Array(newLength)
        for (let i = 0; i < newLength; i++) {
          const srcIndex = Math.floor(i * ratio)
          // Clamp and convert float32 [-1,1] to int16
          const s = Math.max(-1, Math.min(1, inputData[srcIndex]))
          int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
        }
        pcmBufferRef.current.push(int16Array.buffer)
      }

      microphone.connect(processorNode)
      processorNode.connect(audioContext.destination) // Required for processing to run
      pcmWorkerRef.current = processorNode
    } catch (error) {
      console.error('Error initializing audio context:', error)
      throw new Error('Please allow microphone access to use this feature.')
    }
  }

  const connectWebSocket = async () => {
    try {
      // Initialize audio context first
      await initAudioContext()

      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('WebSocket connected')
        setConnected(true)
        updateStatus('Connected', 'connected')

        // Start video recording when interview connects
        startSnapshotCapture()

        // Send start interview message — always Gemini Live mode
        const startMessage = {
          type: 'start_interview',
          interview_id: interview.interview_id,
          application_id: interview.application_id,
          mode: 'gemini_live',
          gemini_live_voice: liveVoice,
        }

        console.log('Starting Gemini Live interview:', startMessage)
        ws.send(JSON.stringify(startMessage))
      }

      ws.onmessage = async (event) => {
        const data = JSON.parse(event.data)
        console.log('📥 Received message:', data.type)
        await handleWebSocketMessage(data)
      }

      ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        updateStatus('Connection error', 'error')
        setError('Connection error. Please try again.')
      }

      ws.onclose = async (event) => {
        console.log('WebSocket closed', event.code, event.reason)
        setConnected(false)

        // Check if it's a normal close (interview completed) or an error
        if (event.code === 1000) {
          // Normal close - interview completed
          console.log('✅ Interview ended normally:', event.reason)
          updateStatus('Interview completed', 'connected')
          // Ensure the completed screen shows even if assessment message was missed
          setAssessment(prev => prev || 'Interview completed.')
          // Save recording and clean up
          try {
            await stopSnapshotCapture()
          } catch (err) {
            console.error('Error saving final recording:', err)
          }
          cleanupResources()
        } else if (!isEndingInterview && !assessment) {
          // Unexpected close
          updateStatus('Disconnected', 'error')
          stopListening()
        }
      }
    } catch (err) {
      console.error('Error connecting WebSocket:', err)
      setError(err.message || 'Failed to connect. Please check your connection.')
      updateStatus('Connection failed', 'error')
    }
  }

  const startCountdown = (minutes) => {
    // Clear any existing countdown
    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current)
    }

    const totalSeconds = minutes * 60
    setTimeRemaining(totalSeconds)
    setTimeLimitMinutes(minutes)

    // Start countdown interval
    countdownIntervalRef.current = setInterval(() => {
      setTimeRemaining(prev => {
        if (prev <= 1) {
          clearInterval(countdownIntervalRef.current)
          return 0
        }
        return prev - 1
      })
    }, 1000)
  }

  const formatTime = (seconds) => {
    if (seconds === null || seconds === undefined) return ''
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  const handleWebSocketMessage = async (data) => {
    switch (data.type) {
      case 'greeting':
        conversationIdRef.current = data.conversation_id
        // Update phase only if it actually changed to prevent unnecessary re-renders
        const greetingPhase = data.phase || ''
        if (greetingPhase !== currentPhase) {
          setCurrentPhase(greetingPhase)
        }

        // Start countdown timer if time limit is provided
        if (data.time_limit_minutes) {
          startCountdown(data.time_limit_minutes)
        }

        if (data.interviewer_text) {
          addMessage('interviewer', data.interviewer_text)
        }
        updateStatus('AI is speaking...', 'connected')
        try {
          // Queue the pending listen request
          pendingListenRef.current = true
          await playAudio(data.audio, data.audio_format)
          console.log('✅ Finished playing greeting')
          // startListening will be called by processAudioQueue after audio is done
        } catch (e) {
          console.error('❌ Audio playback error:', e)
          pendingListenRef.current = false
          // Still try to start listening even if audio failed
          startListening()
        }
        break

      case 'response':
        // Prevent duplicate responses - check if this is the same response within debounce window
        const now = Date.now()
        const responseText = data.interviewer_text || ''

        // More robust duplicate detection:
        // 1. Already processing another response
        // 2. Same text within debounce window
        // 3. Text starts with same first 50 chars (catches partial duplicates)
        const textPrefix = responseText.substring(0, 50)
        const lastTextPrefix = lastResponseTextRef.current.substring(0, 50)
        const isDuplicate = (
          processingResponseRef.current ||
          (now - lastResponseTimeRef.current < RESPONSE_DEBOUNCE_MS && responseText === lastResponseTextRef.current) ||
          (now - lastResponseTimeRef.current < RESPONSE_DEBOUNCE_MS && textPrefix === lastTextPrefix && textPrefix.length > 20)
        )

        if (isDuplicate) {
          console.log('⚠️ Ignoring duplicate response:', responseText.substring(0, 50))
          return
        }

        // Mark as processing and update tracking
        processingResponseRef.current = true
        lastResponseTimeRef.current = now
        lastResponseTextRef.current = responseText

        // Stop listening immediately to prevent echo/overlap
        if (isListeningRef.current) {
          stopListening()
        }

        // Stop any recording in progress
        if (isRecordingRef.current) {
          cancelRecording()
        }

        // Update phase only if it actually changed to prevent unnecessary re-renders
        const newPhase = data.phase || ''
        if (newPhase !== currentPhase) {
          setCurrentPhase(newPhase)
        }

        if (data.user_text) {
          addMessage('user', data.user_text)
        }
        if (data.interviewer_text) {
          addMessage('interviewer', data.interviewer_text)
        }
        updateStatus('AI is speaking...', 'connected')

        try {
          // Queue the pending listen request
          pendingListenRef.current = true
          await playAudio(data.audio, data.audio_format)
          console.log('✅ Finished playing response')
          // Reset processing flag after audio finishes
          processingResponseRef.current = false
          // startListening will be called by processAudioQueue after all audio is done
        } catch (e) {
          console.error('❌ Audio playback error:', e)
          processingResponseRef.current = false
          pendingListenRef.current = false
          // Still try to start listening even if audio failed
          startListening()
        }
        break

      case 'assessment':
        console.log('📊 Assessment received')
        setAssessment(data.assessment)
        updateStatus('Interview completed - Saving recording...', 'connected')
        setIsEndingInterview(false)
        // Stop countdown timer
        if (countdownIntervalRef.current) {
          clearInterval(countdownIntervalRef.current)
          countdownIntervalRef.current = null
        }
        setTimeRemaining(null)
        // Upload video BEFORE cleaning up resources (which kills the stream)
        try {
          await stopSnapshotCapture()
          console.log('✅ Video recording saved before cleanup')
        } catch (err) {
          console.error('❌ Error saving video recording:', err)
        }
        updateStatus('Interview completed - Assessment generated', 'connected')
        cleanupResources()
        break

      case 'stream_ready':
        console.log('✅ Streaming session ready')
        streamingStartedRef.current = true
        startStreamingChunks()
        break

      // ============================================================
      // GEMINI LIVE MODE messages
      // ============================================================
      case 'live_ready':
        console.log('🎙️ Gemini Live session ready!')
        conversationIdRef.current = data.conversation_id
        if (data.time_limit_minutes) {
          startCountdown(data.time_limit_minutes)
        }
        updateStatus('Live — speak naturally', 'connected')
        // Initialize PCM player early so it's ready for first audio
        if (!pcmPlayerRef.current) {
          pcmPlayerRef.current = new PCMPlayer()
        }
        pcmPlayerRef.current.init()
        // Start continuous PCM streaming to server
        startLiveStreaming()
        break

      case 'live_audio':
        // Feed audio chunk to PCM player for immediate playback
        if (pcmPlayerRef.current) {
          pcmPlayerRef.current.feed(data.audio)
        }
        if (!isAudioPlayingRef.current) {
          isAudioPlayingRef.current = true
          updateStatus('AI is speaking...', 'connected')
        }
        break

      case 'user_speaking':
        setIsUserSpeaking(true)
        break

      case 'live_user_transcript':
        // Finalized transcription of what the user said (shown only after user finishes speaking)
        setIsUserSpeaking(false)
        if (data.text) {
          addMessage('user', data.text)
        }
        break

      case 'live_turn_complete':
        isAudioPlayingRef.current = false
        setIsUserSpeaking(false)
        updateStatus('Live — speak naturally', 'connected')
        if (data.text) {
          addMessage('interviewer', data.text)
        }
        break

      case 'live_interrupted':
        // User interrupted the AI — stop playback
        if (pcmPlayerRef.current) {
          pcmPlayerRef.current.stop()
        }
        isAudioPlayingRef.current = false
        updateStatus('Live — speak naturally', 'connected')
        break

      case 'interview_ended':
        // AI called the end_interview function — interview is concluding
        console.log('🏁 AI ended the interview:', data.reason)
        updateStatus('Interview ending...', 'connecting')
        // Wait a moment for the farewell audio to finish playing, then the backend
        // will send the assessment message which triggers cleanup
        break

      case 'error':
        console.error('❌ Error from server:', data.message)
        updateStatus(`Error: ${data.message}`, 'error')
        setError(data.message)
        streamingStartedRef.current = false
        if (!isLiveModeRef.current) {
          setTimeout(() => startListening(), 1000)
        }
        break

      default:
        console.log('Unknown message type:', data.type)
    }
  }

  const updateStatus = (text, className = '') => {
    setStatus(text)
    setStatusClass(className)
  }

  const addMessage = (sender, text) => {
    setConversation(prev => [...prev, { sender, text, timestamp: new Date() }])
    // Auto-scroll handled by CSS
  }

  // Internal function to play a single audio item
  const playAudioInternal = async (audioBase64, format = 'mp3') => {
    return new Promise((resolve) => {
      try {
        // Stop any currently playing audio first
        stopCurrentAudio()

        // Set flag that audio is playing
        isAudioPlayingRef.current = true

        console.log('🔊 Playing audio, format:', format)

        const audioData = atob(audioBase64)
        const arrayBuffer = new ArrayBuffer(audioData.length)
        const view = new Uint8Array(arrayBuffer)
        for (let i = 0; i < audioData.length; i++) {
          view[i] = audioData.charCodeAt(i)
        }

        const mimeType = format === 'wav' ? 'audio/wav' : 'audio/mpeg'
        const blob = new Blob([arrayBuffer], { type: mimeType })
        const audioUrl = URL.createObjectURL(blob)
        const audio = new Audio(audioUrl)
        currentAudioRef.current = audio

        audio.onended = () => {
          console.log('🔊 Audio playback ended')
          URL.revokeObjectURL(audioUrl)
          currentAudioRef.current = null
          isAudioPlayingRef.current = false

          // Short delay to ensure audio is completely finished
          setTimeout(() => {
            resolve()
          }, 100)
        }

        audio.onerror = (error) => {
          console.error('🔊 Audio playback error:', error)
          URL.revokeObjectURL(audioUrl)
          currentAudioRef.current = null
          isAudioPlayingRef.current = false
          resolve()
        }

        audio.play()
          .then(() => {
            console.log('🔊 Audio playback started')
            // Verify audio is actually playing
            if (audio.paused) {
              console.warn('⚠️ Audio started but is paused')
              isAudioPlayingRef.current = false
              resolve()
            }
          })
          .catch(e => {
            console.error('🔊 Audio play() failed:', e)
            isAudioPlayingRef.current = false
            resolve()
          })
      } catch (error) {
        console.error('🔊 Audio setup error:', error)
        isAudioPlayingRef.current = false
        resolve()
      }
    })
  }

  // Process the audio queue - ensures only one audio plays at a time
  const processAudioQueue = async () => {
    if (isPlayingQueueRef.current) {
      console.log('⏸️ Audio queue already being processed')
      return
    }

    isPlayingQueueRef.current = true

    while (audioQueueRef.current.length > 0) {
      const item = audioQueueRef.current.shift()
      console.log(`🔊 Processing queued audio (${audioQueueRef.current.length} remaining in queue)`)

      // Stop listening while playing audio
      if (isListeningRef.current) {
        stopListening()
      }

      await playAudioInternal(item.audio, item.format)
    }

    isPlayingQueueRef.current = false

    // After all audio played, start listening if not already
    if (pendingListenRef.current) {
      pendingListenRef.current = false
      setTimeout(() => {
        startListening()
      }, 200) // Brief delay after audio finished before listening
    }
  }

  // Queue-based audio playback to prevent overlapping
  const playAudio = async (audioBase64, format = 'mp3') => {
    // Clear the queue if we're adding new audio - we only want the latest response
    // This prevents multiple responses from stacking up
    if (audioQueueRef.current.length > 0) {
      console.log('🗑️ Clearing audio queue - new audio taking priority')
      audioQueueRef.current = []
    }

    // Add to queue
    audioQueueRef.current.push({ audio: audioBase64, format })
    console.log(`📥 Added audio to queue (queue size: ${audioQueueRef.current.length})`)

    // Process queue
    await processAudioQueue()
  }

  const stopCurrentAudio = () => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause()
      currentAudioRef.current.src = ''
      currentAudioRef.current = null
      isAudioPlayingRef.current = false
    }
  }

  const startListening = () => {
    // Don't start listening if audio is still playing
    if (isAudioPlayingRef.current) {
      console.log('⏸️ Audio still playing, queuing listen request')
      pendingListenRef.current = true
      return
    }

    // Don't start if we're processing a response
    if (processingResponseRef.current) {
      console.log('⏸️ Response processing, queuing listen request')
      pendingListenRef.current = true
      return
    }

    if (isListeningRef.current || !analyserRef.current) return

    console.log('👂 Started listening for voice...')
    setIsListening(true)
    isListeningRef.current = true
    silenceStartRef.current = null
    speechStartRef.current = null

    updateStatus('Listening... Speak when ready', 'listening')

    // Start Voice Activity Detection — 100ms for responsive detection
    vadIntervalRef.current = setInterval(checkVoiceActivity, 100)
  }

  const stopListening = () => {
    setIsListening(false)
    isListeningRef.current = false
    pendingListenRef.current = false
    if (vadIntervalRef.current) {
      clearInterval(vadIntervalRef.current)
      vadIntervalRef.current = null
    }
  }

  const checkVoiceActivity = () => {
    // Use refs instead of state to avoid stale closure in setInterval
    if (!analyserRef.current || !isListeningRef.current) return

    // Don't check if audio is playing or processing response
    if (isAudioPlayingRef.current || processingResponseRef.current) return

    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount)
    analyserRef.current.getByteFrequencyData(dataArray)

    // Calculate average volume (focus on speech frequencies)
    const relevantData = dataArray.slice(2, 128)
    const average = relevantData.reduce((a, b) => a + b, 0) / relevantData.length

    // Calculate peak for click detection
    const peak = Math.max(...relevantData)

    const now = Date.now()

    // FAILSAFE 1: Maximum recording duration
    if (isRecordingRef.current && recordingStartTimeRef.current) {
      const recordingDuration = now - recordingStartTimeRef.current

      if (recordingDuration > MAX_RECORDING_DURATION) {
        console.log('⏱️ Maximum recording duration reached, force stopping...')
        stopRecording()
        return
      }

      // FAILSAFE 2: Force stop after FORCE_STOP_AFTER_MS regardless of VAD
      if (recordingDuration > FORCE_STOP_AFTER_MS) {
        console.log('⚠️ Failsafe: Force stopping after', FORCE_STOP_AFTER_MS, 'ms')
        stopRecording()
        return
      }

      // FAILSAFE 3: If no strong speech for LOW_ACTIVITY_TIMEOUT_MS, stop
      if (lastStrongSpeechRef.current && (now - lastStrongSpeechRef.current > LOW_ACTIVITY_TIMEOUT_MS)) {
        console.log('⚠️ Failsafe: No strong speech detected for', LOW_ACTIVITY_TIMEOUT_MS, 'ms, stopping')
        stopRecording()
        return
      }
    }

    // Simple speech detection: average volume above threshold
    // Filter out clicks (very high peak with low average)
    const isLikelyClick = peak > 200 && average < 20
    const isLikelySpeech = average > MIN_SPEECH_VOLUME && !isLikelyClick

    // Track strong speech (for failsafe)
    if (average > MIN_SPEECH_VOLUME * 1.5) {
      lastStrongSpeechRef.current = now
    }

    if (isLikelySpeech) {
      // Voice detected - reset silence timer
      silenceStartRef.current = null

      if (!isRecordingRef.current) {
        // Start recording when speech is detected
        speechStartRef.current = now
        lastStrongSpeechRef.current = now  // Initialize strong speech tracker
        startRecording()
      }
    } else {
      // Silence detected
      if (isRecordingRef.current) {
        if (!silenceStartRef.current) {
          silenceStartRef.current = now
        } else {
          const silenceDuration = now - silenceStartRef.current
          const speechDuration = now - speechStartRef.current

          // Stop if silence lasted long enough
          if (silenceDuration > SILENCE_DURATION) {
            if (speechDuration > SPEECH_MIN_DURATION) {
              console.log(`🛑 Stopping recording after ${silenceDuration}ms of silence (speech was ${speechDuration}ms)`)
              stopRecording()
            } else {
              // Speech was too short, cancel and restart
              console.log('⚠️ Speech too short, cancelling...')
              cancelRecording()
              silenceStartRef.current = null
              speechStartRef.current = null
            }
          }
        }
      }
    }
  }

  const startRecording = () => {
    if (isRecordingRef.current || !mediaStreamRef.current) return

    try {
      console.log('🔴 Started recording...')
      const mediaRecorder = new MediaRecorder(mediaStreamRef.current, {
        mimeType: 'audio/webm;codecs=opus'
      })
      mediaRecorderRef.current = mediaRecorder

      audioChunksRef.current = []
      pcmBufferRef.current = []
      recordingStartTimeRef.current = Date.now()
      streamingStartedRef.current = false

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
          // In streaming mode, PCM chunks are captured via ScriptProcessorNode
          // and flushed periodically — no need to send WebM chunks here
        }
      }

      mediaRecorder.onstop = async () => {
        console.log('⏹️ Recording stopped, chunks:', audioChunksRef.current.length)
        recordingStartTimeRef.current = null

        if (isStreamingModeRef.current) {
          // In streaming mode, send commit to finalize transcription
          if (streamingStartedRef.current) {
            console.log('📤 Sending stream commit...')
            sendStreamCommit()
          } else {
            console.warn('⚠️ Streaming not started, cannot send commit')
          }
          streamingStartedRef.current = false
        } else {
          // In batch mode, send full audio blob
          if (audioChunksRef.current.length > 0) {
            const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
            console.log('📤 Preparing to send audio blob, size:', (audioBlob.size / 1024).toFixed(2), 'KB')
            try {
              await sendAudio(audioBlob)
            } catch (error) {
              console.error('❌ Error in sendAudio:', error)
            }
          } else {
            console.warn('⚠️ No audio chunks to send')
          }
        }
      }

      // Start recording with smaller chunks for streaming (100ms)
      mediaRecorder.start(100)
      setIsRecording(true)
      isRecordingRef.current = true

      // In streaming mode, request streaming session from server
      if (isStreamingModeRef.current) {
        updateStatus('Starting streaming session...', 'recording')
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({
            type: 'audio_stream_start',
            conversation_id: conversationIdRef.current
          }))
        }
      } else {
        updateStatus('Recording... (will auto-stop when you pause)', 'recording')
      }
    } catch (error) {
      console.error('Error starting recording:', error)
      updateStatus(`Recording error: ${error.message}`, 'error')
    }
  }

  const startStreamingChunks = () => {
    // Flush any PCM buffers accumulated before stream_ready
    if (pcmBufferRef.current.length > 0) {
      console.log(`📤 Stream ready, flushing ${pcmBufferRef.current.length} buffered PCM chunks`)
      for (const buf of pcmBufferRef.current) {
        sendPcmChunk(buf)
      }
      pcmBufferRef.current = []
    }
    // Start the periodic PCM flush (sends accumulated PCM every 250ms)
    startPcmFlush()
    updateStatus('Recording... (STREAMING - will auto-stop when you pause)', 'recording')
  }

  // Periodically flush PCM buffer to server (batches small ScriptProcessor callbacks)
  const pcmFlushIntervalRef = useRef(null)
  const startPcmFlush = () => {
    if (pcmFlushIntervalRef.current) return
    pcmFlushIntervalRef.current = setInterval(() => {
      if (pcmBufferRef.current.length > 0 && streamingStartedRef.current) {
        // Merge all accumulated PCM chunks into one
        const totalLength = pcmBufferRef.current.reduce((sum, buf) => sum + buf.byteLength, 0)
        const merged = new Uint8Array(totalLength)
        let offset = 0
        for (const buf of pcmBufferRef.current) {
          merged.set(new Uint8Array(buf), offset)
          offset += buf.byteLength
        }
        pcmBufferRef.current = []
        sendPcmChunk(merged.buffer)
      }
    }, 250) // Flush every 250ms — balances latency vs overhead
  }

  const stopPcmFlush = () => {
    if (pcmFlushIntervalRef.current) {
      clearInterval(pcmFlushIntervalRef.current)
      pcmFlushIntervalRef.current = null
    }
  }

  const sendPcmChunk = (arrayBuffer) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !streamingStartedRef.current) return
    try {
      const bytes = new Uint8Array(arrayBuffer)
      let binary = ''
      for (let i = 0; i < bytes.length; i++) {
        binary += String.fromCharCode(bytes[i])
      }
      const base64Audio = btoa(binary)
      wsRef.current.send(JSON.stringify({
        type: 'audio_chunk',
        conversation_id: conversationIdRef.current,
        audio: base64Audio,
        format: 'pcm_s16le'
      }))
    } catch (error) {
      console.error('Error sending PCM chunk:', error)
    }
  }

  // Legacy WebM chunk sender (used only in batch/non-streaming mode)
  const sendAudioChunk = (audioBlob) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || !streamingStartedRef.current) return

    try {
      const reader = new FileReader()
      reader.onloadend = () => {
        const base64Audio = reader.result.split(',')[1]
        wsRef.current.send(JSON.stringify({
          type: 'audio_chunk',
          conversation_id: conversationIdRef.current,
          audio: base64Audio
        }))
      }
      reader.readAsDataURL(audioBlob)
    } catch (error) {
      console.error('Error sending audio chunk:', error)
    }
  }

  const sendStreamCommit = () => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return

    console.log('📤 Sending stream commit')
    wsRef.current.send(JSON.stringify({
      type: 'audio_commit',
      conversation_id: conversationIdRef.current
    }))
    updateStatus('Processing your answer...', 'connecting')
  }

  const stopRecording = () => {
    if (!isRecordingRef.current || !mediaRecorderRef.current) return

    stopListening()
    stopPcmFlush()

    // Flush any remaining PCM data before stopping
    if (isStreamingModeRef.current && pcmBufferRef.current.length > 0 && streamingStartedRef.current) {
      const totalLength = pcmBufferRef.current.reduce((sum, buf) => sum + buf.byteLength, 0)
      const merged = new Uint8Array(totalLength)
      let offset = 0
      for (const buf of pcmBufferRef.current) {
        merged.set(new Uint8Array(buf), offset)
        offset += buf.byteLength
      }
      pcmBufferRef.current = []
      sendPcmChunk(merged.buffer)
    }

    if (mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    setIsRecording(false)
    isRecordingRef.current = false
    updateStatus('Processing your answer...', 'connecting')
  }

  const cancelRecording = () => {
    if (!mediaRecorderRef.current) return

    stopPcmFlush()
    pcmBufferRef.current = []

    if (mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    audioChunksRef.current = []
    setIsRecording(false)
    isRecordingRef.current = false
    recordingStartTimeRef.current = null
    streamingStartedRef.current = false
  }

  const sendAudio = async (audioBlob) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.error('❌ WebSocket not connected')
      updateStatus('Not connected', 'error')
      startListening()
      return
    }

    // Prevent duplicate audio sends within 500ms (reduced from 1000ms)
    const now = Date.now()
    if (sendingAudioRef.current) {
      console.log('⚠️ Already sending audio, ignoring duplicate')
      return
    }

    // Only check time if we've sent audio very recently (within 300ms) - reduced to be less aggressive
    if (now - lastAudioSendTimeRef.current < 300) {
      console.log('⚠️ Audio sent too recently (', now - lastAudioSendTimeRef.current, 'ms ago), ignoring duplicate')
      return
    }

    console.log('📤 Starting audio send process...')

    sendingAudioRef.current = true
    lastAudioSendTimeRef.current = now

    // Safety timeout to reset flag in case something goes wrong
    const timeoutId = setTimeout(() => {
      if (sendingAudioRef.current) {
        console.warn('⚠️ Audio send timeout, resetting flag')
        sendingAudioRef.current = false
      }
    }, 10000) // 10 second timeout

    try {
      console.log('📤 Sending audio:', (audioBlob.size / 1024).toFixed(2), 'KB')
      const reader = new FileReader()
      reader.onloadstart = () => {
        console.log('📤 FileReader started reading...')
      }

      reader.onloadend = () => {
        clearTimeout(timeoutId)
        try {
          const result = reader.result
          if (!result) {
            console.error('❌ FileReader result is empty')
            sendingAudioRef.current = false
            return
          }
          const base64Audio = result.split(',')[1]
          if (!base64Audio) {
            console.error('❌ Failed to extract base64 audio from result')
            sendingAudioRef.current = false
            return
          }
          console.log('📤 Audio encoded (', (base64Audio.length / 1024).toFixed(2), 'KB), sending to server...')

          if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
            console.error('❌ WebSocket not open, cannot send')
            sendingAudioRef.current = false
            return
          }

          wsRef.current.send(JSON.stringify({
            type: 'audio',
            conversation_id: conversationIdRef.current,
            audio: base64Audio
          }))
          console.log('✅ Audio sent successfully to server')
          sendingAudioRef.current = false
        } catch (error) {
          console.error('❌ Error in onloadend:', error)
          sendingAudioRef.current = false
        }
      }
      reader.onerror = (error) => {
        clearTimeout(timeoutId)
        console.error('❌ FileReader error:', error)
        sendingAudioRef.current = false
      }
      reader.onabort = () => {
        clearTimeout(timeoutId)
        console.warn('⚠️ FileReader aborted')
        sendingAudioRef.current = false
      }
      reader.readAsDataURL(audioBlob)
    } catch (error) {
      clearTimeout(timeoutId)
      updateStatus(`Error sending audio: ${error.message}`, 'error')
      console.error('Error sending audio:', error)
      sendingAudioRef.current = false
      startListening()
    }
  }

  const endInterview = async () => {
    stopListening()
    stopCurrentAudio()

    // Stop live mode streaming
    if (liveFlushIntervalRef.current) {
      clearInterval(liveFlushIntervalRef.current)
      liveFlushIntervalRef.current = null
    }
    if (pcmPlayerRef.current) {
      pcmPlayerRef.current.stop()
    }

    if (isRecording) {
      cancelRecording()
    }

    // Stop video recording and upload
    await stopSnapshotCapture()

    // Stop countdown timer
    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current)
      countdownIntervalRef.current = null
    }
    setTimeRemaining(null)

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && conversationIdRef.current) {
      setIsEndingInterview(true)
      updateStatus('Generating assessment...', 'connecting')
      wsRef.current.send(JSON.stringify({
        type: 'end_interview',
        conversation_id: conversationIdRef.current
      }))

      // Fallback timeout
      setTimeout(() => {
        if (isEndingInterview) {
          updateStatus('Assessment timed out', 'error')
          setIsEndingInterview(false)
          cleanupResources()
        }
      }, 15000)
    } else {
      cleanupResources()
      setConversation([])
      updateStatus('Interview ended', 'error')
    }
  }

  return (
    <div className="interview-interface">
      <div className="interview-header">
        <div>
          <h2>{interview?.job_offer?.title || 'AI Interview'}</h2>
          <p className={`interview-status ${statusClass}`}>
            {status}
            {currentPhase && ` • ${currentPhase}`}
          </p>
        </div>
        <div className="header-right">
          {timeRemaining !== null && (
            <div className={`countdown-timer ${timeRemaining <= 300 ? 'warning' : ''} ${timeRemaining <= 60 ? 'critical' : ''}`}>
              <span className="countdown-label">Time remaining:</span>
              <span className="countdown-time">{formatTime(timeRemaining)}</span>
            </div>
          )}
          <button className="close-btn" onClick={onClose} disabled={isEndingInterview}>
            <HiXMark />
          </button>
        </div>
      </div>

      {error && (
        <div className="error-banner">
          {error}
        </div>
      )}

      {/* Voice selector — only before interview starts, hidden once assessment exists */}
      {!connected && !assessment && providersConfig && (
        <div className="provider-selectors">
          {providersConfig?.gemini_live && (
            <div className="live-voice-selector">
              <label>AI Voice</label>
              <div className="voice-options">
                {providersConfig.gemini_live.voices.map((v) => (
                  <button
                    key={v.id}
                    className={`voice-btn ${liveVoice === v.id ? 'active' : ''}`}
                    onClick={() => setLiveVoice(v.id)}
                  >
                    {v.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          <button
            className="start-interview-btn"
            onClick={connectWebSocket}
          >
            Start Interview
          </button>
        </div>
      )}

      {/* Completed screen — full-page thank-you */}
      {assessment && (
        <div className="interview-completed-screen">
          <div className="interview-completed-icon">&#10003;</div>
          <h2>Interview Completed</h2>
          <p>Thank you for your participation! Our HR team will carefully review your interview and get back to you soon.</p>
          <p className="interview-completed-luck">We wish you the best of luck.</p>
          <button className="interview-completed-btn" onClick={onClose}>
            Close
          </button>
        </div>
      )}

      {/* Active interview UI — hidden once assessment exists */}
      {!assessment && (
        <>
          {/* Video Preview */}
          {connected && (
            <div className="video-preview-container">
              <video
                ref={videoPreviewRef}
                autoPlay
                playsInline
                muted
                className="video-preview"
              />
              <div className="video-recording-badge">
                <div className="rec-dot"></div>
                <span>REC</span>
              </div>
            </div>
          )}

          <div className="conversation-area" ref={(el) => {
            if (el) {
              el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
            }
          }}>
            {conversation.length === 0 && (
              <div className="waiting-message">
                <p>Waiting for interviewer to start...</p>
              </div>
            )}

            {conversation.map((msg, idx) => (
              <div key={idx} className={`message ${msg.sender}${msg.pending ? ' pending' : ''}`}>
                <div className="message-header">
                  {msg.sender === 'user' ? 'You' : 'Interviewer'}
                </div>
                <div className="message-content">
                  {msg.text}
                  {msg.pending && <span className="typing-cursor" />}
                </div>
              </div>
            ))}

            {isUserSpeaking && (
              <div className="message user">
                <div className="message-header">You</div>
                <div className="message-content speaking-indicator-bubble">
                  <div className="speaking-waves">
                    <span></span><span></span><span></span><span></span><span></span>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="interview-controls">
            {connected && (
              <div className="listening-indicator live-indicator">
                <HiSpeakerWave className="pulse-icon" />
                <span>Live</span>
              </div>
            )}

            {isRecording && (
              <div className="recording-indicator">
                <div className="pulse-dot"></div>
                <span>Recording...</span>
              </div>
            )}

            <button
              className="end-btn"
              onClick={endInterview}
              disabled={!connected || isEndingInterview}
            >
              <HiStop className="icon" />
              <span>End Interview</span>
            </button>
          </div>
        </>
      )}
    </div>
  )
}

export default InterviewInterface
