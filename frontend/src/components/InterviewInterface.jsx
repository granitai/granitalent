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

// Voice Activity Detection settings
const SILENCE_THRESHOLD = 35
const SILENCE_DURATION = 1000
const SPEECH_MIN_DURATION = 300
const MAX_RECORDING_DURATION = 30000

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
  // Refs to track state values inside setInterval (avoid stale closure)
  const isListeningRef = useRef(false)
  const isRecordingRef = useRef(false)

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
    
    stopCurrentAudio()
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

      ws.onclose = () => {
        console.log('WebSocket closed')
        setConnected(false)
        if (!isEndingInterview) {
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

  const handleWebSocketMessage = async (data) => {
    switch (data.type) {
      case 'greeting':
        conversationIdRef.current = data.conversation_id
        setCurrentPhase(data.phase || '')
        if (data.interviewer_text) {
          addMessage('interviewer', data.interviewer_text)
        }
        updateStatus('AI is speaking...', 'connected')
        try {
          await playAudio(data.audio, data.audio_format)
          console.log('✅ Finished playing greeting')
        } catch (e) {
          console.error('❌ Audio playback error:', e)
        }
        // Auto-start listening after AI finishes speaking
        startListening()
        break
      
      case 'response':
        setCurrentPhase(data.phase || '')
        if (data.user_text) {
          addMessage('user', data.user_text)
        }
        if (data.interviewer_text) {
          addMessage('interviewer', data.interviewer_text)
        }
        updateStatus('AI is speaking...', 'connected')
        try {
          await playAudio(data.audio, data.audio_format)
          console.log('✅ Finished playing response')
        } catch (e) {
          console.error('❌ Audio playback error:', e)
        }
        // Auto-start listening after AI finishes speaking
        startListening()
        break
      
      case 'assessment':
        console.log('📊 Assessment received')
        setAssessment(data.assessment)
        updateStatus('Interview completed - Assessment generated', 'connected')
        setIsEndingInterview(false)
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

  const playAudio = async (audioBase64, format = 'mp3') => {
    return new Promise((resolve) => {
      try {
        stopCurrentAudio()
        
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
          resolve()
        }
        
        audio.onerror = (error) => {
          console.error('🔊 Audio playback error:', error)
          URL.revokeObjectURL(audioUrl)
          currentAudioRef.current = null
          resolve()
        }
        
        audio.play()
          .then(() => console.log('🔊 Audio playback started'))
          .catch(e => {
            console.error('🔊 Audio play() failed:', e)
            resolve()
          })
      } catch (error) {
        console.error('🔊 Audio setup error:', error)
        resolve()
      }
    })
  }

  const stopCurrentAudio = () => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause()
      currentAudioRef.current.src = ''
      currentAudioRef.current = null
    }
  }

  const startListening = () => {
    if (isListeningRef.current || !analyserRef.current) return
    
    console.log('👂 Started listening for voice...')
    setIsListening(true)
    isListeningRef.current = true
    silenceStartRef.current = null
    speechStartRef.current = null
    
    updateStatus('Listening... Speak when ready', 'listening')
    
    // Start Voice Activity Detection
    vadIntervalRef.current = setInterval(checkVoiceActivity, 100)
  }

  const stopListening = () => {
    setIsListening(false)
    isListeningRef.current = false
    if (vadIntervalRef.current) {
      clearInterval(vadIntervalRef.current)
      vadIntervalRef.current = null
    }
  }

  const checkVoiceActivity = () => {
    // Use refs instead of state to avoid stale closure in setInterval
    if (!analyserRef.current || !isListeningRef.current) return
    
    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount)
    analyserRef.current.getByteFrequencyData(dataArray)
    
    // Calculate average volume (focus on speech frequencies)
    const relevantData = dataArray.slice(2, 128)
    const average = relevantData.reduce((a, b) => a + b, 0) / relevantData.length
    
    const now = Date.now()
    
    // Check for maximum recording duration
    if (isRecordingRef.current && recordingStartTimeRef.current && (now - recordingStartTimeRef.current > MAX_RECORDING_DURATION)) {
      console.log('⏱️ Maximum recording duration reached, stopping...')
      stopRecording()
      return
    }
    
    if (average > SILENCE_THRESHOLD) {
      // Voice detected
      silenceStartRef.current = null
      
      if (!isRecordingRef.current) {
        // Start recording when speech is detected
        speechStartRef.current = now
        startRecording()
      }
    } else {
      // Silence detected
      if (isRecordingRef.current) {
        if (!silenceStartRef.current) {
          silenceStartRef.current = now
        } else if (now - silenceStartRef.current > SILENCE_DURATION) {
          // Silence lasted long enough, stop recording
          const speechDuration = now - speechStartRef.current
          if (speechDuration > SPEECH_MIN_DURATION) {
            console.log(`🛑 Stopping recording after ${SILENCE_DURATION}ms of silence`)
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
        console.log('⏹️ Recording stopped')
        recordingStartTimeRef.current = null
        
        if (isStreamingModeRef.current) {
          // In streaming mode, send commit to finalize transcription
          if (streamingStartedRef.current) {
            sendStreamCommit()
          }
          streamingStartedRef.current = false
        } else {
          // In batch mode, send full audio blob
          if (audioChunksRef.current.length > 0) {
            const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
            await sendAudio(audioBlob)
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
    
    try {
      console.log('📤 Sending audio:', (audioBlob.size / 1024).toFixed(2), 'KB')
      const reader = new FileReader()
      reader.onloadend = () => {
        const base64Audio = reader.result.split(',')[1]
        console.log('📤 Audio encoded, sending to server...')
        wsRef.current.send(JSON.stringify({
          type: 'audio',
          conversation_id: conversationIdRef.current,
          audio: base64Audio
        }))
        console.log('✅ Audio sent successfully')
      }
      reader.readAsDataURL(audioBlob)
    } catch (error) {
      updateStatus(`Error sending audio: ${error.message}`, 'error')
      console.error('Error sending audio:', error)
      startListening()
    }
  }

  const endInterview = () => {
    stopListening()
    stopCurrentAudio()
    
    if (isRecording) {
      cancelRecording()
    }
    
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
        <button className="close-btn" onClick={onClose} disabled={isEndingInterview}>
          <HiXMark />
        </button>
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
