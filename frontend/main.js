// Jarvis V2 — Frontend
const orb = document.getElementById('orb');
const status = document.getElementById('status');
const transcript = document.getElementById('transcript');

let ws;
let audioQueue = [];
let isPlaying = false;
let audioUnlocked = false;

// Unlock audio on ANY user interaction
function unlockAudio() {
    if (!audioUnlocked) {
        const silent = new Audio('data:audio/mp3;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjEzAAAAAAAAAAAAAAAAJAAAAAAAAAAAAYZNIGPkAAAAAAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjEzAAAAAAAAAAAAAAAAJAAAAAAAAAAAAYZNIGPkAAAAAAAAAAAAAAAAAAAA');
        silent.play().then(() => {
            audioUnlocked = true;
            console.log('[jarvis] Audio unlocked');
        }).catch(() => {});
    }
}
document.addEventListener('click', unlockAudio, { once: false });
document.addEventListener('touchstart', unlockAudio, { once: false });
document.addEventListener('keydown', unlockAudio, { once: false });

function connect() {
    // Use wss:// when the page itself is HTTPS (e.g. accessed via
    // Tailscale serve / reverse proxy). Browsers block mixed-content
    // ws:// from an https:// origin, which would manifest as the orb
    // staying in the "thinking" state forever because the user's
    // transcript is sent into a socket that never opened.
    const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${wsProto}//${location.host}/ws`);
    ws.onopen = () => {
        console.log('[jarvis] WebSocket connected');
        status.textContent = 'Klicke einmal irgendwo, dann spricht Jarvis.';
        setOrbState('thinking');
        ws.send(JSON.stringify({ text: 'Jarvis activate' }));
    };
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'response') {
            addTranscript('jarvis', data.text);
            if (data.audio && data.audio.length > 0) {
                queueAudio(data.audio);
            } else {
                setOrbState('idle');
                setTimeout(startListening, 500);
            }
        } else if (data.type === 'status') {
            status.textContent = data.text;
        }
    };
    ws.onclose = () => {
        status.textContent = 'Verbindung verloren...';
        setTimeout(connect, 3000);
    };
}

function queueAudio(base64Audio) {
    audioQueue.push(base64Audio);
    if (!isPlaying) playNext();
}

function playNext() {
    if (audioQueue.length === 0) {
        isPlaying = false;
        setOrbState('listening');
        status.textContent = '';
        setTimeout(startListening, 500);
        return;
    }
    isPlaying = true;
    setOrbState('speaking');
    status.textContent = '';
    if (isListening) {
        recognition.stop();
        isListening = false;
    }

    const b64 = audioQueue.shift();
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const blob = new Blob([bytes], { type: 'audio/mpeg' });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => { URL.revokeObjectURL(url); playNext(); };
    audio.onerror = () => { URL.revokeObjectURL(url); playNext(); };
    audio.play().catch(err => {
        console.warn('[jarvis] Autoplay blocked, waiting for user gesture...');
        status.textContent = 'Klicke oder tippe irgendwo damit Jarvis sprechen kann.';
        setOrbState('idle');
        // Wait for ANY user gesture (click or keydown) then retry.
        // Listening on both means the synthetic Tab keystroke injected by
        // scripts/mic_workaround.applescript after the clap-trigger auto-
        // launch also triggers the replay, not just manual mouse clicks.
        const retry = () => {
            document.removeEventListener('click', retry);
            document.removeEventListener('keydown', retry);
            audio.play().then(() => {
                setOrbState('speaking');
                status.textContent = '';
            }).catch(() => playNext());
        };
        document.addEventListener('click', retry);
        document.addEventListener('keydown', retry);
    });
}

// Speech Recognition
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition;
let isListening = false;

if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.lang = 'de-DE';
    recognition.continuous = true;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
        const last = event.results[event.results.length - 1];
        if (last.isFinal) {
            const text = last[0].transcript.trim();
            if (text) {
                addTranscript('user', text);
                setOrbState('thinking');
                status.textContent = 'Jarvis denkt nach...';
                ws.send(JSON.stringify({ text }));
            }
        }
    };

    recognition.onend = () => {
        isListening = false;
        if (!isPlaying) setTimeout(startListening, 300);
    };

    recognition.onerror = (event) => {
        isListening = false;
        if (event.error === 'no-speech' || event.error === 'aborted') {
            if (!isPlaying) setTimeout(startListening, 300);
        } else {
            setTimeout(startListening, 1000);
        }
    };
}

function startListening() {
    if (isPlaying) return;
    try {
        recognition.start();
        isListening = true;
        setOrbState('listening');
        status.textContent = '';
    } catch(e) {}
}

orb.addEventListener('click', () => {
    if (isPlaying) return;
    if (isListening) {
        recognition.stop();
        isListening = false;
        setOrbState('idle');
        status.textContent = 'Pausiert. Klicke zum Fortsetzen.';
    } else {
        startListening();
    }
});

// WebKit/Chrome require a user gesture before webkitSpeechRecognition and
// audio autoplay. Register a one-shot gesture listener that kicks off
// listening on the first click OR keypress anywhere on the document.
// Works both for manual interaction AND for the synthetic click that
// scripts/mic_workaround.applescript injects after the clap-trigger
// auto-launch sequence.
const firstGesture = () => {
    document.removeEventListener('click', firstGesture);
    document.removeEventListener('keydown', firstGesture);
    if (recognition && !isListening && !isPlaying) {
        startListening();
    }
};
document.addEventListener('click', firstGesture);
document.addEventListener('keydown', firstGesture);

function setOrbState(state) { orb.className = state; }

function addTranscript(role, text) {
    const div = document.createElement('div');
    div.className = role;
    div.textContent = role === 'user' ? `Du: ${text}` : `Jarvis: ${text}`;
    transcript.appendChild(div);
    transcript.scrollTop = transcript.scrollHeight;
}

connect();
