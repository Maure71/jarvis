// Jarvis V2 — Frontend
const orb = document.getElementById('orb');
const status = document.getElementById('status');
const transcript = document.getElementById('transcript');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const chatSend = document.getElementById('chat-send');

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

// Mobile-only geolocation override. On iPhone/Android the user often
// isn't at home (Kisdorf) — ask the browser for the current position
// and hand it to the server BEFORE the first "Jarvis activate" so the
// greeting uses the right city + weather. On desktop we skip this
// entirely, so the Mac Mini keeps its fixed home location without ever
// prompting for a permission the user doesn't want there.
const IS_MOBILE = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);

function sendLocation() {
    return new Promise((resolve) => {
        if (!IS_MOBILE || !navigator.geolocation) {
            resolve();
            return;
        }
        let done = false;
        const finish = () => { if (!done) { done = true; resolve(); } };
        // Hard 5s budget — we don't want the activate greeting to sit
        // silent forever if the user taps "Deny" or the GPS is slow.
        const timer = setTimeout(finish, 5000);
        try {
            navigator.geolocation.getCurrentPosition(
                (pos) => {
                    clearTimeout(timer);
                    try {
                        ws.send(JSON.stringify({
                            type: 'location',
                            lat: pos.coords.latitude,
                            lon: pos.coords.longitude,
                        }));
                        console.log('[jarvis] Location sent:',
                            pos.coords.latitude.toFixed(4),
                            pos.coords.longitude.toFixed(4));
                    } catch (e) {
                        console.warn('[jarvis] Location send failed', e);
                    }
                    finish();
                },
                (err) => {
                    clearTimeout(timer);
                    console.log('[jarvis] Geolocation denied/unavailable:', err.message);
                    finish();
                },
                { enableHighAccuracy: false, timeout: 4000, maximumAge: 300000 }
            );
        } catch (e) {
            clearTimeout(timer);
            finish();
        }
    });
}

function connect() {
    // Use wss:// when the page itself is HTTPS (e.g. accessed via
    // Tailscale serve / reverse proxy). Browsers block mixed-content
    // ws:// from an https:// origin, which would manifest as the orb
    // staying in the "thinking" state forever because the user's
    // transcript is sent into a socket that never opened.
    const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${wsProto}//${location.host}/ws`);
    ws.onopen = async () => {
        console.log('[jarvis] WebSocket connected');
        status.textContent = 'Klicke einmal irgendwo, dann spricht Jarvis.';
        setOrbState('thinking');
        // On mobile, push the current location first so the server has
        // it ready before it builds the system prompt for the greeting.
        // Bounded by a 5s timeout inside sendLocation() so a denied or
        // slow GPS never blocks the greeting entirely.
        await sendLocation();
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
    // Don't hijack the mic while the user is typing in the chat input
    // — it would compete with the keyboard for attention and risk
    // sending a spoken transcript on top of a half-typed message.
    if (document.activeElement === chatInput) return;
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
//
// Exception: ignore keystrokes that originate inside the chat input or
// its form — the user is typing a message, not trying to start voice
// recognition. Same for clicks on chat-form children, so focusing the
// input doesn't grab the mic.
const isChatTarget = (target) =>
    target && (target === chatInput || (chatForm && chatForm.contains(target)));

const firstGesture = (event) => {
    if (isChatTarget(event.target)) return;
    document.removeEventListener('click', firstGesture);
    document.removeEventListener('keydown', firstGesture);
    if (recognition && !isListening && !isPlaying) {
        startListening();
    }
};
document.addEventListener('click', firstGesture);
document.addEventListener('keydown', firstGesture);

// Chat form: text input as an alternative to voice. Sends the same
// {text: ...} payload over the WebSocket that voice recognition uses,
// so the server pipeline (Claude + TTS) is identical. While the user
// is typing we deliberately do NOT start recognition — focusing the
// input and sending a message pauses any active listening and lets
// Jarvis reply via audio as usual.
if (chatForm) {
    chatInput.addEventListener('focus', () => {
        if (isListening) {
            try { recognition.stop(); } catch (e) {}
            isListening = false;
            setOrbState('idle');
        }
    });

    chatForm.addEventListener('submit', (event) => {
        event.preventDefault();
        const text = chatInput.value.trim();
        if (!text) return;
        if (!ws || ws.readyState !== WebSocket.OPEN) {
            status.textContent = 'Keine Verbindung — bitte neu laden.';
            return;
        }
        addTranscript('user', text);
        setOrbState('thinking');
        status.textContent = 'Jarvis denkt nach...';
        ws.send(JSON.stringify({ text }));
        chatInput.value = '';
        // Keep focus on the input so the iOS keyboard stays up for a
        // quick follow-up message. Blur manually via tapping the orb
        // or elsewhere.
        chatInput.focus();
    });
}

function setOrbState(state) { orb.className = state; }

function addTranscript(role, text) {
    const div = document.createElement('div');
    div.className = role;
    div.textContent = role === 'user' ? `Du: ${text}` : `Jarvis: ${text}`;
    transcript.appendChild(div);
    transcript.scrollTop = transcript.scrollHeight;
}

connect();
