// WebSocket connection and audio handling
let ws = null;
let mediaRecorder = null;
let audioChunks = [];
let conversationId = null;
let isRecording = false;
let isListening = false;
let audioContext = null;
let analyser = null;
let microphone = null;
let mediaStream = null;
let currentAudio = null;  // Track current playing audio
let isEndingInterview = false;  // Flag to track intentional interview end
let providersConfig = null;  // Store providers configuration

// Streaming mode variables
let isStreamingMode = false;  // Whether to use streaming STT
let streamingStarted = false;  // Whether streaming session is active
let chunkInterval = null;  // Interval for sending audio chunks

// Voice Activity Detection settings
const SILENCE_THRESHOLD = 35;      // Volume level below which is considered silence (higher = more aggressive cutoff)
const SILENCE_DURATION = 1000;      // Ms of silence before stopping (500ms for faster response)
const SPEECH_MIN_DURATION = 300;   // Minimum speech duration to consider valid
const MAX_RECORDING_DURATION = 30000;  // Maximum recording duration (30 seconds) as failsafe
let silenceStart = null;
let speechStart = null;
let vadInterval = null;
let recordingStartTime = null;     // Track when recording started

const API_BASE_URL = 'http://localhost:8000';

// CV Upload and Evaluation state
let currentEvaluationId = null;
let isCvApproved = false;

// DOM elements
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const ttsProviderSelect = document.getElementById('ttsProvider');
const ttsModelSelect = document.getElementById('ttsModel');
const sttProviderSelect = document.getElementById('sttProvider');
const sttModelSelect = document.getElementById('sttModel');
const llmProviderSelect = document.getElementById('llmProvider');
const llmModelSelect = document.getElementById('llmModel');
const listeningIndicator = document.getElementById('listeningIndicator');
const conversationDiv = document.getElementById('conversation');
const statusDiv = document.getElementById('status');

// CV Upload elements (will be initialized after DOM loads)
let cvUploadSection, interviewSection, jobOfferSelect, cvFileInput, uploadCvBtn, evaluationResult, evaluationContent;
let cvDropZone, selectedFileName, clearFormBtn;

// Event listeners
startBtn.addEventListener('click', startInterview);
stopBtn.addEventListener('click', stopInterview);

// Initialize CV upload elements and check evaluation status
document.addEventListener('DOMContentLoaded', () => {
    // Initialize CV upload DOM elements
    cvUploadSection = document.getElementById('cvUploadSection');
    interviewSection = document.getElementById('interviewSection');
    jobOfferSelect = document.getElementById('jobOfferSelect');
    cvFileInput = document.getElementById('cvFileInput');
    uploadCvBtn = document.getElementById('uploadCvBtn');
    evaluationResult = document.getElementById('evaluationResult');
    evaluationContent = document.getElementById('evaluationContent');
    cvDropZone = document.getElementById('cvDropZone');
    selectedFileName = document.getElementById('selectedFileName');
    clearFormBtn = document.getElementById('clearFormBtn');
    
    // Add event listener for CV upload button after element is initialized
    if (uploadCvBtn) {
        uploadCvBtn.addEventListener('click', uploadAndEvaluateCV);
    }
    
    // Add event listener for clear form button
    if (clearFormBtn) {
        clearFormBtn.addEventListener('click', clearForm);
    }
    
    // Setup drag and drop
    setupDragAndDrop();
    
    // Show CV upload section by default, hide interview section
    if (cvUploadSection) cvUploadSection.style.display = 'block';
    if (interviewSection) interviewSection.style.display = 'none';
    
    // Check if CV evaluation exists in localStorage
    const savedEvaluationId = localStorage.getItem('cvEvaluationId');
    if (savedEvaluationId) {
        checkEvaluationStatus(savedEvaluationId);
    } else {
        loadJobOffers();
    }
});

// Provider change listeners
ttsProviderSelect.addEventListener('change', () => updateModelOptions('tts'));
sttProviderSelect.addEventListener('change', () => updateModelOptions('stt'));
llmProviderSelect.addEventListener('change', () => updateModelOptions('llm'));

// Load providers on page load (if not already loaded)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadProviders);
} else {
    loadProviders();
}

async function loadProviders() {
    try {
        updateStatus('Loading providers...', 'connecting');
        const response = await fetch(`${API_BASE_URL}/api/providers`);
        providersConfig = await response.json();
        
        console.log('📋 Loaded providers config:', providersConfig);
        
        // Populate provider dropdowns
        populateProviderSelect('tts', ttsProviderSelect);
        populateProviderSelect('stt', sttProviderSelect);
        populateProviderSelect('llm', llmProviderSelect);
        
        // Set defaults
        ttsProviderSelect.value = providersConfig.defaults.tts_provider;
        sttProviderSelect.value = providersConfig.defaults.stt_provider;
        llmProviderSelect.value = providersConfig.defaults.llm_provider;
        
        // Update model options
        updateModelOptions('tts');
        updateModelOptions('stt');
        updateModelOptions('llm');
        
        updateStatus('Ready to start', '');
    } catch (error) {
        console.error('Failed to load providers:', error);
        updateStatus('Failed to load providers - using defaults', 'error');
        // Set fallback options
        setFallbackOptions();
    }
}

function populateProviderSelect(type, selectElement) {
    selectElement.innerHTML = '';
    const providers = providersConfig[type];
    
    for (const [providerId, providerData] of Object.entries(providers)) {
        const option = document.createElement('option');
        option.value = providerId;
        option.textContent = providerData.name;
        selectElement.appendChild(option);
    }
}

function updateModelOptions(type) {
    let providerSelect, modelSelect;
    
    switch (type) {
        case 'tts':
            providerSelect = ttsProviderSelect;
            modelSelect = ttsModelSelect;
            break;
        case 'stt':
            providerSelect = sttProviderSelect;
            modelSelect = sttModelSelect;
            break;
        case 'llm':
            providerSelect = llmProviderSelect;
            modelSelect = llmModelSelect;
            break;
    }
    
    const provider = providerSelect.value;
    modelSelect.innerHTML = '';
    
    if (providersConfig && providersConfig[type] && providersConfig[type][provider]) {
        const models = providersConfig[type][provider].models;
        const defaultModel = providersConfig[type][provider].default_model;
        
        for (const model of models) {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = model.name;
            if (model.id === defaultModel) {
                option.selected = true;
            }
            modelSelect.appendChild(option);
        }
    }
    
    // Update streaming mode flag when STT provider changes
    if (type === 'stt') {
        isStreamingMode = provider === 'elevenlabs_streaming';
        console.log(`🎤 STT Provider: ${provider}, Streaming mode: ${isStreamingMode}`);
    }
}

function setFallbackOptions() {
    // TTS fallback
    ttsModelSelect.innerHTML = `
        <option value="eleven_flash_v2_5">Flash v2.5 — Fast</option>
        <option value="eleven_multilingual_v2">Multilingual v2 — Quality</option>
    `;
    
    // STT fallback
    sttModelSelect.innerHTML = `
        <option value="scribe_v1">Scribe v1 — High Accuracy</option>
        <option value="scribe_v2">Scribe v2 — Low Latency</option>
    `;
    
    // LLM fallback
    llmModelSelect.innerHTML = `
        <option value="gemini-2.5-flash-lite">Gemini 2.5 Flash-Lite — Lowest Latency</option>
        <option value="gemini-2.0-flash">Gemini 2.0 Flash — Balanced</option>
    `;
}

async function startInterview() {
    try {
        // Check if CV is approved
        if (!isCvApproved || !currentEvaluationId) {
            alert('Please upload and get your CV approved before starting the interview.');
            return;
        }
        
        updateStatus('Starting interview...', 'connecting');
        startBtn.disabled = true;
        
        // Request microphone access upfront
        await initAudioContext();
        
        // Initialize WebSocket connection
        ws = new WebSocket(`ws://localhost:8000/ws`);
        
        ws.onopen = () => {
            updateStatus('Connected', 'connected');
            
            // Get selected providers and models
            const config = {
                type: 'start_interview',
                evaluation_id: currentEvaluationId,  // Include evaluation ID
                tts_provider: ttsProviderSelect.value,
                tts_model: ttsModelSelect.value,
                stt_provider: sttProviderSelect.value,
                stt_model: sttModelSelect.value,
                llm_provider: llmProviderSelect.value,
                llm_model: llmModelSelect.value
            };
            
            console.log('🚀 Starting interview with config:', config);
            ws.send(JSON.stringify(config));
            
            // Disable all selectors during interview
            disableSelectors(true);
        };
        
        ws.onmessage = async (event) => {
            const data = JSON.parse(event.data);
            console.log('📥 Received message:', data.type);
            
            if (data.type === 'greeting') {
                // AI interviewer starts with a greeting
                conversationId = data.conversation_id;
                console.log('🎤 Greeting:', data.text);
                addMessage('interviewer', data.text);
                stopBtn.disabled = false;
                updateStatus('AI is speaking...', 'connected');
                try {
                    await playAudio(data.audio, data.audio_format);
                    console.log('✅ Finished playing greeting');
                } catch (e) {
                    console.error('❌ Audio playback error:', e);
                }
                // Auto-start listening after AI finishes speaking
                startListening();
            } else if (data.type === 'response') {
                console.log('🎤 User said:', data.user_text);
                console.log('🤖 AI responds:', data.interviewer_text);
                addMessage('user', data.user_text);
                addMessage('interviewer', data.interviewer_text);
                updateStatus('AI is speaking...', 'connected');
                try {
                    await playAudio(data.audio, data.audio_format);
                    console.log('✅ Finished playing response');
                } catch (e) {
                    console.error('❌ Audio playback error:', e);
                }
                // Auto-start listening after AI finishes speaking
                startListening();
            } else if (data.type === 'assessment') {
                console.log('📊 Assessment received');
                // Display assessment
                displayAssessment(data.assessment);
            } else if (data.type === 'stream_ready') {
                console.log('✅ Streaming session ready');
                streamingStarted = true;
                // Start sending audio chunks
                startStreamingChunks();
            } else if (data.type === 'error') {
                console.error('❌ Error from server:', data.message);
                updateStatus(`Error: ${data.message}`, 'error');
                // Restart listening on error
                streamingStarted = false;
                setTimeout(() => startListening(), 1000);
            }
        };
        
        ws.onerror = (error) => {
            updateStatus('Connection error', 'error');
            console.error('WebSocket error:', error);
        };
        
        ws.onclose = () => {
            // Don't reset UI if we're intentionally ending (waiting for assessment)
            if (!isEndingInterview) {
                updateStatus('Disconnected', 'error');
                stopListening();
                resetUI();
            }
        };
        
    } catch (error) {
        updateStatus(`Error: ${error.message}`, 'error');
        console.error('Error starting interview:', error);
        startBtn.disabled = false;
    }
}

async function initAudioContext() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.5;
        microphone = audioContext.createMediaStreamSource(mediaStream);
        microphone.connect(analyser);
    } catch (error) {
        console.error('Error initializing audio context:', error);
        throw new Error('Please allow microphone access to use this feature.');
    }
}

function startListening() {
    if (isListening) return;
    
    console.log('👂 Started listening for voice...');
    isListening = true;
    silenceStart = null;
    speechStart = null;
    
    updateStatus('Listening... Speak when ready', 'listening');
    if (listeningIndicator) {
        listeningIndicator.classList.add('active');
    }
    
    // Start Voice Activity Detection
    vadInterval = setInterval(checkVoiceActivity, 100);
}

function stopListening() {
    isListening = false;
    if (vadInterval) {
        clearInterval(vadInterval);
        vadInterval = null;
    }
    if (listeningIndicator) {
        listeningIndicator.classList.remove('active');
    }
}

// Throttle for volume logging (don't spam console)
let lastVolumeLog = 0;

function checkVoiceActivity() {
    if (!analyser || !isListening) return;
    
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(dataArray);
    
    // Calculate average volume (focus on speech frequencies - skip very low frequencies)
    const relevantData = dataArray.slice(2, 128);  // Focus on speech frequency range
    const average = relevantData.reduce((a, b) => a + b, 0) / relevantData.length;
    
    const now = Date.now();
    
    // Log volume level every 500ms to help debug (only when recording or about to record)
    if (now - lastVolumeLog > 500) {
        const status = isRecording ? '🔴 REC' : '👂 LISTEN';
        console.log(`${status} Volume: ${average.toFixed(1)} | Threshold: ${SILENCE_THRESHOLD} | ${average > SILENCE_THRESHOLD ? '🗣️ SPEECH' : '🔇 SILENCE'}`);
        lastVolumeLog = now;
    }
    
    // Check for maximum recording duration (failsafe)
    if (isRecording && recordingStartTime && (now - recordingStartTime > MAX_RECORDING_DURATION)) {
        console.log('⏱️ Maximum recording duration reached, stopping...');
        stopRecording();
        return;
    }
    
    if (average > SILENCE_THRESHOLD) {
        // Voice detected
        silenceStart = null;
        
        if (!isRecording) {
            // Start recording when speech is detected
            speechStart = now;
            startRecording();
        }
    } else {
        // Silence detected
        if (isRecording) {
            if (!silenceStart) {
                silenceStart = now;
            } else if (now - silenceStart > SILENCE_DURATION) {
                // Silence lasted long enough, stop recording
                const speechDuration = now - speechStart;
                if (speechDuration > SPEECH_MIN_DURATION) {
                    console.log(`🛑 Stopping recording after ${SILENCE_DURATION}ms of silence (speech duration: ${speechDuration}ms)`);
                    stopRecording();
                } else {
                    // Speech was too short, cancel and restart
                    console.log('⚠️ Speech too short, cancelling...');
                    cancelRecording();
                    silenceStart = null;
                    speechStart = null;
                }
            }
        }
    }
}

function stopInterview() {
    // Stop listening first
    stopListening();
    
    // Stop any playing audio immediately
    stopCurrentAudio();
    
    // Cancel any ongoing recording
    if (isRecording) {
        cancelRecording();
    }
    
    // Request assessment before closing
    if (ws && ws.readyState === WebSocket.OPEN && conversationId) {
        isEndingInterview = true;  // Set flag to prevent onclose from resetting UI
        updateStatus('Generating assessment...', 'connecting');
        ws.send(JSON.stringify({
            type: 'end_interview',
            conversation_id: conversationId
        }));
        
        // Fallback timeout in case assessment never arrives
        setTimeout(() => {
            if (isEndingInterview) {
                updateStatus('Assessment timed out', 'error');
                isEndingInterview = false;
                cleanupResources();
            }
        }, 15000);  // 15 second timeout for assessment
    } else {
        cleanupResources();
        conversationDiv.innerHTML = '<p class="placeholder">Interview ended. Click "Start Interview" to begin a new one...</p>';
        updateStatus('Interview ended', 'error');
    }
}

function stopCurrentAudio() {
    if (currentAudio) {
        currentAudio.pause();
        currentAudio.src = '';
        currentAudio = null;
    }
}

function cleanupResources() {
    if (ws) {
        ws.close();
        ws = null;
    }
    
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
    
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    
    resetUI();
}

function startRecording() {
    if (isRecording || !mediaStream) return;
    
    try {
        console.log('🔴 Started recording...' + (isStreamingMode ? ' (STREAMING MODE)' : ' (BATCH MODE)'));
        mediaRecorder = new MediaRecorder(mediaStream, {
            mimeType: 'audio/webm;codecs=opus'
        });
        
        audioChunks = [];
        recordingStartTime = Date.now();  // Track recording start time
        streamingStarted = false;
        
        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
                
                // In streaming mode, send chunks immediately if stream is ready
                if (isStreamingMode && streamingStarted) {
                    sendAudioChunk(event.data);
                }
            }
        };
        
        mediaRecorder.onstop = async () => {
            console.log('⏹️ Recording stopped, chunks:', audioChunks.length);
            recordingStartTime = null;  // Reset recording start time
            
            if (isStreamingMode) {
                // In streaming mode, send commit to finalize transcription
                if (streamingStarted) {
                    sendStreamCommit();
                }
                streamingStarted = false;
            } else {
                // In batch mode, send full audio blob
                if (audioChunks.length > 0) {
                    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                    await sendAudio(audioBlob);
                }
            }
        };
        
        // Start recording with smaller chunks for streaming (100ms)
        mediaRecorder.start(100);
        isRecording = true;
        
        // In streaming mode, request streaming session from server
        if (isStreamingMode) {
            updateStatus('Starting streaming session...', 'recording');
            ws.send(JSON.stringify({
                type: 'audio_stream_start',
                conversation_id: conversationId
            }));
        } else {
            updateStatus('Recording... (will auto-stop when you pause)', 'recording');
        }
        
    } catch (error) {
        console.error('Error starting recording:', error);
        updateStatus(`Recording error: ${error.message}`, 'error');
    }
}

function startStreamingChunks() {
    // Send any buffered chunks that were recorded before stream was ready
    console.log(`📤 Stream ready, sending ${audioChunks.length} buffered chunks`);
    for (const chunk of audioChunks) {
        sendAudioChunk(chunk);
    }
    updateStatus('Recording... (STREAMING - will auto-stop when you pause)', 'recording');
}

async function sendAudioChunk(audioBlob) {
    if (!ws || ws.readyState !== WebSocket.OPEN || !streamingStarted) return;
    
    try {
        const reader = new FileReader();
        reader.onloadend = () => {
            const base64Audio = reader.result.split(',')[1];
            ws.send(JSON.stringify({
                type: 'audio_chunk',
                conversation_id: conversationId,
                audio: base64Audio
            }));
        };
        reader.readAsDataURL(audioBlob);
    } catch (error) {
        console.error('Error sending audio chunk:', error);
    }
}

function sendStreamCommit() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    
    console.log('📤 Sending stream commit');
    ws.send(JSON.stringify({
        type: 'audio_commit',
        conversation_id: conversationId
    }));
    updateStatus('Processing your answer...', 'connecting');
}

function stopRecording() {
    if (!isRecording || !mediaRecorder) return;
    
    stopListening();
    
    if (mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
    }
    isRecording = false;
    updateStatus('Processing your answer...', 'connecting');
}

function cancelRecording() {
    if (!mediaRecorder) return;
    
    if (mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
    }
    audioChunks = [];
    isRecording = false;
    recordingStartTime = null;
    streamingStarted = false;
}

async function sendAudio(audioBlob) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        console.error('❌ WebSocket not connected');
        updateStatus('Not connected', 'error');
        startListening();
        return;
    }
    
    try {
        console.log('📤 Sending audio:', (audioBlob.size / 1024).toFixed(2), 'KB');
        // Convert blob to base64
        const reader = new FileReader();
        reader.onloadend = () => {
            const base64Audio = reader.result.split(',')[1];
            console.log('📤 Audio encoded, sending to server...');
            ws.send(JSON.stringify({
                type: 'audio',
                conversation_id: conversationId,
                audio: base64Audio
            }));
            console.log('✅ Audio sent successfully');
        };
        reader.readAsDataURL(audioBlob);
        
    } catch (error) {
        updateStatus(`Error sending audio: ${error.message}`, 'error');
        console.error('Error sending audio:', error);
        startListening();
    }
}

async function playAudio(base64Audio, format = 'mp3') {
    return new Promise((resolve, reject) => {
        try {
            // Stop any currently playing audio
            stopCurrentAudio();
            
            console.log('🔊 Playing audio, format:', format, 'length:', base64Audio.length);
            
            const audioData = atob(base64Audio);
            const arrayBuffer = new ArrayBuffer(audioData.length);
            const view = new Uint8Array(arrayBuffer);
            for (let i = 0; i < audioData.length; i++) {
                view[i] = audioData.charCodeAt(i);
            }
            
            // Set correct MIME type based on format
            const mimeType = format === 'wav' ? 'audio/wav' : 'audio/mpeg';
            const blob = new Blob([arrayBuffer], { type: mimeType });
            console.log('🔊 Audio blob size:', (blob.size / 1024).toFixed(2), 'KB');
            
            const audioUrl = URL.createObjectURL(blob);
            currentAudio = new Audio(audioUrl);
            
            currentAudio.onended = () => {
                console.log('🔊 Audio playback ended');
                URL.revokeObjectURL(audioUrl);
                currentAudio = null;
                resolve();
            };
            
            currentAudio.onerror = (error) => {
                console.error('🔊 Audio playback error:', error);
                URL.revokeObjectURL(audioUrl);
                currentAudio = null;
                // Resolve instead of reject to continue flow
                resolve();
            };
            
            currentAudio.play()
                .then(() => console.log('🔊 Audio playback started'))
                .catch(e => {
                    console.error('🔊 Audio play() failed:', e);
                    resolve(); // Continue even if audio fails
                });
            
        } catch (error) {
            console.error('🔊 Audio setup error:', error);
            resolve(); // Continue even if audio fails
        }
    });
}

function addMessage(role, text) {
    const placeholder = conversationDiv.querySelector('.placeholder');
    if (placeholder) {
        conversationDiv.innerHTML = '';
    }
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    const header = document.createElement('div');
    header.className = 'message-header';
    header.textContent = role === 'interviewer' ? 'Interviewer' : 'You';
    
    const messageText = document.createElement('div');
    messageText.className = 'message-text';
    messageText.textContent = text;
    
    messageDiv.appendChild(header);
    messageDiv.appendChild(messageText);
    conversationDiv.appendChild(messageDiv);
    
    // Scroll to bottom
    conversationDiv.scrollTop = conversationDiv.scrollHeight;
}

function displayAssessment(assessment) {
    // Create assessment section
    const assessmentDiv = document.createElement('div');
    assessmentDiv.className = 'assessment';
    
    const header = document.createElement('h3');
    header.textContent = 'Interview Assessment';
    header.className = 'assessment-header';
    
    const content = document.createElement('div');
    content.className = 'assessment-content';
    content.innerHTML = assessment.replace(/\n/g, '<br>').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    
    assessmentDiv.appendChild(header);
    assessmentDiv.appendChild(content);
    conversationDiv.appendChild(assessmentDiv);
    
    // Scroll to bottom
    conversationDiv.scrollTop = conversationDiv.scrollHeight;
    
    updateStatus('Interview completed - Assessment generated', 'connected');
    
    // Reset flag and cleanup
    isEndingInterview = false;
    
    // Cleanup resources but keep UI showing the assessment
    if (ws) {
        ws.close();
        ws = null;
    }
    
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
    
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    
    // Reset buttons only
    startBtn.disabled = false;
    stopBtn.disabled = true;
    disableSelectors(false);
}

function disableSelectors(disabled) {
    ttsProviderSelect.disabled = disabled;
    ttsModelSelect.disabled = disabled;
    sttProviderSelect.disabled = disabled;
    sttModelSelect.disabled = disabled;
    llmProviderSelect.disabled = disabled;
    llmModelSelect.disabled = disabled;
}

function updateStatus(text, className = '') {
    statusDiv.textContent = text;
    statusDiv.className = `status-text ${className}`;
}

function resetUI() {
    startBtn.disabled = false;
    stopBtn.disabled = true;
    disableSelectors(false);
    isRecording = false;
    isListening = false;
    isEndingInterview = false;
    conversationId = null;
    streamingStarted = false;
    if (listeningIndicator) {
        listeningIndicator.classList.remove('active');
    }
}

// ============================================================
// CV Upload and Evaluation Functions
// ============================================================

async function loadJobOffers() {
    if (!jobOfferSelect) return;
    
    try {
        const response = await fetch(`${API_BASE_URL}/api/job-offers`);
        const offers = await response.json();
        
        jobOfferSelect.innerHTML = '<option value="">Select a job offer...</option>';
        offers.forEach(offer => {
            const option = document.createElement('option');
            option.value = offer.offer_id;
            option.textContent = offer.title;
            jobOfferSelect.appendChild(option);
        });
    } catch (error) {
        console.error('Error loading job offers:', error);
        if (jobOfferSelect) {
            jobOfferSelect.innerHTML = '<option value="">Error loading offers</option>';
        }
    }
}

async function uploadAndEvaluateCV() {
    if (!cvFileInput || !jobOfferSelect || !uploadCvBtn) {
        console.error('CV upload elements not initialized');
        return;
    }
    
    const file = cvFileInput.files[0];
    const jobOfferId = jobOfferSelect.value;
    
    if (!file) {
        alert('Please select a PDF file');
        return;
    }
    
    if (!jobOfferId) {
        alert('Please select a job offer');
        return;
    }
    
    if (file.size > 10 * 1024 * 1024) {
        alert('File size must be less than 10MB');
        return;
    }
    
    if (file.type !== 'application/pdf') {
        alert('Please upload a PDF file');
        return;
    }
    
    try {
        uploadCvBtn.disabled = true;
        uploadCvBtn.innerHTML = '<span>⏳</span> Processing...';
        if (evaluationResult) evaluationResult.style.display = 'none';
        
        const formData = new FormData();
        formData.append('file', file);
        formData.append('job_offer_id', jobOfferId);
        formData.append('llm_provider', llmProviderSelect.value);
        formData.append('llm_model', llmModelSelect.value);
        
        const response = await fetch(`${API_BASE_URL}/api/cv/upload`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Error evaluating CV');
        }
        
        const result = await response.json();
        currentEvaluationId = result.evaluation_id;
        
        // Store in localStorage
        localStorage.setItem('cvEvaluationId', currentEvaluationId);
        
        // Display result
        displayEvaluationResult(result);
        
        // Check if approved - but don't automatically show interview section
        if (result.status === 'approved') {
            isCvApproved = true;
            // Don't automatically show interview section - user will click button
        } else {
            isCvApproved = false;
            hideInterviewSection();
        }
        
    } catch (error) {
        console.error('Error uploading CV:', error);
        alert(`Error: ${error.message}`);
    } finally {
        if (uploadCvBtn) {
            uploadCvBtn.disabled = false;
            uploadCvBtn.innerHTML = '<span>📄</span> Upload & Evaluate CV';
        }
    }
}

function displayEvaluationResult(result) {
    if (!evaluationContent || !evaluationResult) return;
    
    const isApproved = result.status === 'approved';
    const parsedCvText = result.parsed_cv_text || '';
    const cvTextLength = result.cv_text_length || (parsedCvText ? parsedCvText.length : 0);
    
    evaluationContent.innerHTML = `
        <div class="evaluation-status ${isApproved ? 'approved' : 'rejected'}">
            ${isApproved ? 
                '<div class="approval-header"><h3>✅ CV Approved - You are a good fit for this position!</h3><p class="approval-message">Congratulations! Based on our analysis, your CV matches the job requirements. Review the details below and proceed to the interview when ready.</p></div>' : 
                '<h3>❌ CV Not Approved</h3>'
            }
            <div class="evaluation-scores">
                <div class="score-item">
                    <span class="score-label">Overall Score:</span>
                    <span class="score-value">${result.score}/10</span>
                </div>
                <div class="score-item">
                    <span class="score-label">Skills Match:</span>
                    <span class="score-value">${result.skills_match}/10</span>
                </div>
                <div class="score-item">
                    <span class="score-label">Experience Match:</span>
                    <span class="score-value">${result.experience_match}/10</span>
                </div>
                <div class="score-item">
                    <span class="score-label">Education Match:</span>
                    <span class="score-value">${result.education_match}/10</span>
                </div>
            </div>
            <div class="evaluation-reasoning">
                <h4>Detailed Analysis:</h4>
                <p>${result.reasoning}</p>
            </div>
            ${parsedCvText ? `
            <div class="parsed-cv-section">
                <button class="btn-toggle-cv" onclick="toggleParsedCV(this)" type="button">
                    <span>📄</span> View Parsed CV Content <span class="toggle-icon">▼</span>
                </button>
                <div class="parsed-cv-content" style="display: none;">
                    <div class="parsed-cv-text">
                        <pre>${escapeHtml(parsedCvText)}</pre>
                    </div>
                    <small style="color: var(--text-muted); display: block; margin-top: 8px;">
                        Total characters: ${cvTextLength}
                    </small>
                </div>
            </div>
            ` : ''}
            ${isApproved ? 
                '<div class="interview-access-section"><button class="btn btn-primary btn-large" onclick="proceedToInterview()" style="margin-top: 20px; padding: 14px 28px; font-size: 1.1em;"><span>🚀</span> Proceed to Interview</button></div>' : 
                '<div><p class="error-message">Please review your CV and try again with a different position or updated CV.</p><button class="btn btn-primary" onclick="resetCvUpload()" style="margin-top: 12px;">Try Again</button></div>'
            }
        </div>
    `;
    
    evaluationResult.style.display = 'block';
    // Scroll to evaluation result
    evaluationResult.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function showInterviewSection() {
    if (cvUploadSection) cvUploadSection.style.display = 'none';
    if (interviewSection) interviewSection.style.display = 'block';
}

function hideInterviewSection() {
    if (cvUploadSection) cvUploadSection.style.display = 'block';
    if (interviewSection) interviewSection.style.display = 'none';
}

function resetCvUpload() {
    // Reset CV upload form and clear evaluation result
    clearForm();
}

function clearForm() {
    // Clear job offer selection
    if (jobOfferSelect) {
        jobOfferSelect.value = '';
    }
    
    // Clear file input
    if (cvFileInput) {
        cvFileInput.value = '';
        // Reset file input
        const dataTransfer = new DataTransfer();
        cvFileInput.files = dataTransfer.files;
    }
    
    // Clear selected file display
    if (selectedFileName) {
        selectedFileName.style.display = 'none';
        selectedFileName.textContent = '';
    }
    
    // Reset drop zone appearance
    if (cvDropZone) {
        cvDropZone.classList.remove('file-selected');
    }
    
    // Clear evaluation result
    if (evaluationResult) {
        evaluationResult.style.display = 'none';
    }
    if (evaluationContent) {
        evaluationContent.innerHTML = '';
    }
    
    // Reset state
    currentEvaluationId = null;
    isCvApproved = false;
    localStorage.removeItem('cvEvaluationId');
    
    // Hide interview section if visible
    if (interviewSection) {
        interviewSection.style.display = 'none';
    }
    if (cvUploadSection) {
        cvUploadSection.style.display = 'block';
    }
    
    // Scroll to top of CV upload section
    if (cvUploadSection) {
        cvUploadSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function toggleParsedCV(button) {
    const content = button.nextElementSibling;
    const icon = button.querySelector('.toggle-icon');
    
    if (content.style.display === 'none') {
        content.style.display = 'block';
        icon.textContent = '▲';
    } else {
        content.style.display = 'none';
        icon.textContent = '▼';
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function proceedToInterview() {
    if (!isCvApproved || !currentEvaluationId) {
        alert('Please upload and get your CV approved before starting the interview.');
        return;
    }
    showInterviewSection();
    // Scroll to interview section
    if (interviewSection) {
        interviewSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function setupDragAndDrop() {
    if (!cvDropZone || !cvFileInput) return;
    
    const dropZoneContent = cvDropZone.querySelector('.drop-zone-content');
    const dropZoneLink = cvDropZone.querySelector('.drop-zone-link');
    
    // Click to browse
    cvDropZone.addEventListener('click', () => {
        cvFileInput.click();
    });
    
    dropZoneLink.addEventListener('click', (e) => {
        e.stopPropagation();
        cvFileInput.click();
    });
    
    // File input change
    cvFileInput.addEventListener('change', (e) => {
        handleFileSelect(e.target.files[0]);
    });
    
    // Drag and drop events
    cvDropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        cvDropZone.classList.add('drag-over');
    });
    
    cvDropZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        cvDropZone.classList.remove('drag-over');
    });
    
    cvDropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        cvDropZone.classList.remove('drag-over');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFileSelect(files[0]);
        }
    });
}

function handleFileSelect(file) {
    if (!file) return;
    
    // Validate file type
    if (file.type !== 'application/pdf') {
        alert('Please upload a PDF file');
        return;
    }
    
    // Validate file size
    if (file.size > 10 * 1024 * 1024) {
        alert('File size must be less than 10MB');
        return;
    }
    
    // Set file to input
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    cvFileInput.files = dataTransfer.files;
    
    // Show selected file name
    if (selectedFileName) {
        selectedFileName.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(2)} KB)`;
        selectedFileName.style.display = 'block';
    }
    
    // Update drop zone appearance
    if (cvDropZone) {
        cvDropZone.classList.add('file-selected');
    }
}

// Make functions global for onclick handlers
window.toggleParsedCV = toggleParsedCV;
window.resetCvUpload = resetCvUpload;
window.proceedToInterview = proceedToInterview;
window.clearForm = clearForm;

async function checkEvaluationStatus(evaluationId) {
    try {
        // Request evaluation with parsed CV text included
        const response = await fetch(`${API_BASE_URL}/api/cv/evaluation/${evaluationId}?include_cv_text=true`);
        if (response.ok) {
            const result = await response.json();
            currentEvaluationId = evaluationId;
            
            if (result.status === 'approved') {
                isCvApproved = true;
                displayEvaluationResult(result);
                // Don't automatically show interview section - user will click button
            } else {
                isCvApproved = false;
                displayEvaluationResult(result);
                hideInterviewSection();
            }
        } else {
            // Evaluation not found, clear localStorage
            localStorage.removeItem('cvEvaluationId');
            loadJobOffers();
        }
    } catch (error) {
        console.error('Error checking evaluation status:', error);
        localStorage.removeItem('cvEvaluationId');
        loadJobOffers();
    }
}
