import React, { useState, useEffect, useRef } from 'react'
import { HiMicrophone, HiStop, HiXMark, HiSpeakerWave } from 'react-icons/hi2'
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

// Voice Activity Detection settings - Balanced for responsiveness and avoiding interruption
const SILENCE_THRESHOLD = 30  // Volume below this = silence
const MIN_SPEECH_VOLUME = 35  // Minimum volume to consider as actual speech (filters ambient noise)
const SILENCE_DURATION = 2500  // 2.5 seconds of silence before stopping - balanced
const SPEECH_MIN_DURATION = 600  // Minimum 600ms of speech to be valid
const MAX_RECORDING_DURATION = 60000  // 60 seconds max per answer
const RESPONSE_DEBOUNCE_MS = 2000  // Prevent processing duplicate responses within 2 seconds
const FORCE_STOP_AFTER_MS = 45000  // Failsafe: force stop recording after 45 seconds even if VAD fails
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
  
  // Provider/Model selection state
  const [providersConfig, setProvidersConfig] = useState(null)
  const [ttsProvider, setTtsProvider] = useState('')
  const [ttsModel, setTtsModel] = useState('')
  const [sttProvider, setSttProvider] = useState('')
  const [sttModel, setSttModel] = useState('')
  const [llmProvider, setLlmProvider] = useState('')
  const [llmModel, setLlmModel] = useState('')
  
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
      updateStatus('Loading providers...', 'connecting')
      const response = await axios.get(`${API_BASE_URL}/providers`)
      const config = response.data
      setProvidersConfig(config)
      
      // Set defaults
      setTtsProvider(config.defaults.tts_provider)
      setSttProvider(config.defaults.stt_provider)
      setLlmProvider(config.defaults.llm_provider)
      
      // Set default models
      const ttsDefaultModel = config.tts[config.defaults.tts_provider]?.default_model
      const sttDefaultModel = config.stt[config.defaults.stt_provider]?.default_model
      const llmDefaultModel = config.llm[config.defaults.llm_provider]?.default_model
      
      if (ttsDefaultModel) setTtsModel(ttsDefaultModel)
      if (sttDefaultModel) setSttModel(sttDefaultModel)
      if (llmDefaultModel) setLlmModel(llmDefaultModel)
      
      updateStatus('Ready to start', '')
    } catch (error) {
      console.error('Failed to load providers:', error)
      updateStatus('Failed to load providers - using defaults', 'error')
      // Set fallback defaults
      setTtsProvider('elevenlabs')
      setTtsModel('eleven_flash_v2_5')
      setSttProvider('elevenlabs')
      setSttModel('scribe_v1')
      setLlmProvider('gemini')
      setLlmModel('gemini-2.5-flash-lite')
    }
  }

  const updateModelOptions = (type) => {
    if (!providersConfig) return
    
    let provider, setModel
    switch (type) {
      case 'tts':
        provider = ttsProvider
        setModel = setTtsModel
        break
      case 'stt':
        provider = sttProvider
        setModel = setSttModel
        break
      case 'llm':
        provider = llmProvider
        setModel = setLlmModel
        break
      default:
        return
    }
    
    const providerConfig = providersConfig[type]?.[provider]
    if (providerConfig) {
      const defaultModel = providerConfig.default_model
      if (defaultModel) {
        setModel(defaultModel)
      }
      
      // Update streaming mode for STT
      if (type === 'stt') {
        isStreamingModeRef.current = provider === 'elevenlabs_streaming'
        console.log(`🎤 STT Provider: ${provider}, Streaming mode: ${isStreamingModeRef.current}`)
      }
    }
  }

  const handleProviderChange = (type, provider) => {
    switch (type) {
      case 'tts':
        setTtsProvider(provider)
        break
      case 'stt':
        setSttProvider(provider)
        break
      case 'llm':
        setLlmProvider(provider)
        break
    }
    // Update model options will be handled in useEffect
  }

  useEffect(() => {
    if (providersConfig && ttsProvider) {
      updateModelOptions('tts')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ttsProvider, providersConfig])

  useEffect(() => {
    if (providersConfig && sttProvider) {
      updateModelOptions('stt')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sttProvider, providersConfig])

  useEffect(() => {
    if (providersConfig && llmProvider) {
      updateModelOptions('llm')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [llmProvider, providersConfig])

  const cleanupResources = () => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop())
      mediaStreamRef.current = null
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
    
    stopCurrentAudio()
    isAudioPlayingRef.current = false
    pendingListenRef.current = false
  }

  const initAudioContext = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream
      
      const audioContext = new (window.AudioContext || window.webkitAudioContext)()
      audioContextRef.current = audioContext
      
      const analyser = audioContext.createAnalyser()
      analyser.fftSize = 512
      analyser.smoothingTimeConstant = 0.5
      analyserRef.current = analyser
      
      const microphone = audioContext.createMediaStreamSource(stream)
      microphone.connect(analyser)
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
        
        // Send start interview message with selected providers/models
        const startMessage = {
          type: 'start_interview',
          interview_id: interview.interview_id,
          application_id: interview.application_id,
          tts_provider: ttsProvider,
          tts_model: ttsModel,
          stt_provider: sttProvider,
          stt_model: sttModel,
          llm_provider: llmProvider,
          llm_model: llmModel
        }
        
        console.log('Sending start interview message:', startMessage)
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

      ws.onclose = (event) => {
        console.log('WebSocket closed', event.code, event.reason)
        setConnected(false)
        
        // Check if it's a normal close (interview completed) or an error
        if (event.code === 1000) {
          // Normal close - interview completed
          console.log('✅ Interview ended normally:', event.reason)
          updateStatus('Interview completed', 'connected')
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
        updateStatus('Interview completed - Assessment generated', 'connected')
        setIsEndingInterview(false)
        // Stop countdown timer
        if (countdownIntervalRef.current) {
          clearInterval(countdownIntervalRef.current)
          countdownIntervalRef.current = null
        }
        setTimeRemaining(null)
        cleanupResources()
        break
      
      case 'stream_ready':
        console.log('✅ Streaming session ready')
        streamingStartedRef.current = true
        startStreamingChunks()
        break
      
      case 'error':
        console.error('❌ Error from server:', data.message)
        updateStatus(`Error: ${data.message}`, 'error')
        setError(data.message)
        streamingStartedRef.current = false
        setTimeout(() => startListening(), 1000)
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
          }, 300)
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
      }, 500) // Extra delay after all audio finished
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
    
    // Start Voice Activity Detection with slightly slower interval to reduce CPU usage
    vadIntervalRef.current = setInterval(checkVoiceActivity, 150)
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
      recordingStartTimeRef.current = Date.now()
      streamingStartedRef.current = false
      
      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
          
          // In streaming mode, send chunks immediately if stream is ready
          if (isStreamingModeRef.current && streamingStartedRef.current) {
            sendAudioChunk(event.data)
          }
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
    console.log(`📤 Stream ready, sending ${audioChunksRef.current.length} buffered chunks`)
    for (const chunk of audioChunksRef.current) {
      sendAudioChunk(chunk)
    }
    updateStatus('Recording... (STREAMING - will auto-stop when you pause)', 'recording')
  }

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
    
    if (mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    setIsRecording(false)
    isRecordingRef.current = false
    updateStatus('Processing your answer...', 'connecting')
  }

  const cancelRecording = () => {
    if (!mediaRecorderRef.current) return
    
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

  const endInterview = () => {
    stopListening()
    stopCurrentAudio()
    
    if (isRecording) {
      cancelRecording()
    }
    
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

      {!connected && providersConfig && (
        <div className="provider-selectors">
          <div className="selector-group">
            <label>TTS Provider</label>
            <select
              value={ttsProvider}
              onChange={(e) => handleProviderChange('tts', e.target.value)}
              disabled={connected}
            >
              {Object.entries(providersConfig.tts || {}).map(([id, config]) => (
                <option key={id} value={id}>{config.name}</option>
              ))}
            </select>
          </div>
          
          <div className="selector-group">
            <label>TTS Model</label>
            <select
              value={ttsModel}
              onChange={(e) => setTtsModel(e.target.value)}
              disabled={connected || !ttsProvider}
            >
              {providersConfig.tts?.[ttsProvider]?.models.map((model) => (
                <option key={model.id} value={model.id}>{model.name}</option>
              ))}
            </select>
          </div>

          <div className="selector-group">
            <label>STT Provider</label>
            <select
              value={sttProvider}
              onChange={(e) => handleProviderChange('stt', e.target.value)}
              disabled={connected}
            >
              {Object.entries(providersConfig.stt || {}).map(([id, config]) => (
                <option key={id} value={id}>{config.name}</option>
              ))}
            </select>
          </div>
          
          <div className="selector-group">
            <label>STT Model</label>
            <select
              value={sttModel}
              onChange={(e) => setSttModel(e.target.value)}
              disabled={connected || !sttProvider}
            >
              {providersConfig.stt?.[sttProvider]?.models.map((model) => (
                <option key={model.id} value={model.id}>{model.name}</option>
              ))}
            </select>
          </div>

          <div className="selector-group">
            <label>LLM Provider</label>
            <select
              value={llmProvider}
              onChange={(e) => handleProviderChange('llm', e.target.value)}
              disabled={connected}
            >
              {Object.entries(providersConfig.llm || {}).map(([id, config]) => (
                <option key={id} value={id}>{config.name}</option>
              ))}
            </select>
          </div>
          
          <div className="selector-group">
            <label>LLM Model</label>
            <select
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              disabled={connected || !llmProvider}
            >
              {providersConfig.llm?.[llmProvider]?.models.map((model) => (
                <option key={model.id} value={model.id}>{model.name}</option>
              ))}
            </select>
          </div>

          <button 
            className="start-interview-btn"
            onClick={connectWebSocket}
            disabled={!ttsProvider || !ttsModel || !sttProvider || !sttModel || !llmProvider || !llmModel}
          >
            Start Interview
          </button>
        </div>
      )}

      <div className="conversation-area" ref={(el) => {
        if (el) {
          el.scrollTop = el.scrollHeight
        }
      }}>
        {conversation.length === 0 && !assessment && (
          <div className="waiting-message">
            <p>Waiting for interviewer to start...</p>
          </div>
        )}
        
        {conversation.map((msg, idx) => (
          <div key={idx} className={`message ${msg.sender}`}>
            <div className="message-header">
              {msg.sender === 'user' ? 'You' : 'Interviewer'}
            </div>
            <div className="message-content">
              {msg.text}
            </div>
          </div>
        ))}

        {assessment && (
          <div className="assessment-section">
            <h3>Interview Assessment</h3>
            <div 
              className="assessment-content"
              dangerouslySetInnerHTML={{
                __html: (() => {
                  let formatted = assessment
                    // Headers
                    .replace(/^### (.*$)/gim, '<h3>$1</h3>')
                    .replace(/^## (.*$)/gim, '<h2>$1</h2>')
                    .replace(/^# (.*$)/gim, '<h1>$1</h1>')
                    // Bold (must be before italic)
                    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                    // Italic (only single asterisks)
                    .replace(/(?<!\*)\*(?!\*)([^*]+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>')
                    // Lists
                    .replace(/^- (.*$)/gim, '<li>$1</li>')
                    .replace(/^\d+\. (.*$)/gim, '<li>$1</li>')
                    // Line breaks
                    .replace(/\n/g, '<br>')
                  
                  // Wrap consecutive <li> tags in <ul>
                  const lines = formatted.split('<br>')
                  formatted = lines.reduce((acc, line, idx, arr) => {
                    if (line.trim().startsWith('<li>')) {
                      if (idx === 0 || !arr[idx - 1].trim().startsWith('<li>')) {
                        acc += '<ul>'
                      }
                      acc += line + '<br>'
                      if (idx === arr.length - 1 || !arr[idx + 1].trim().startsWith('<li>')) {
                        acc = acc.replace(/<br>$/, '') + '</ul><br>'
                      }
                    } else {
                      acc += line + '<br>'
                    }
                    return acc
                  }, '').replace(/<br>$/g, '')
                  
                  return formatted
                })()
              }}
            />
          </div>
        )}
      </div>

      <div className="interview-controls">
        {isListening && !isRecording && (
          <div className="listening-indicator">
            <HiSpeakerWave className="pulse-icon" />
            <span>Listening...</span>
          </div>
        )}
        
        {!assessment && (
          <>
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
          </>
        )}
        
        {assessment && (
          <button className="close-btn-large" onClick={onClose}>
            Close
          </button>
        )}
      </div>
    </div>
  )
}

export default InterviewInterface
