'use strict';

const {
    SmartSpectraSDK,
    ProcessingStatus,
    ValidationCode,
    breathingMetrics,
    cardioMetrics,
    faceMetrics,
} = require('@smartspectra/node-sdk/renderer');
const { decodeMetrics } = require('@smartspectra/node-sdk/messages');

const BACKEND_URL = 'ws://127.0.0.1:8000/ws';
const VITALS_INTERVAL_MS = 1000;
const STALE_MS = 3000; // a reading older than this is not sent as "current"
const MAX_RECOVERIES = 3;
const POSITION_TIP = 'Sit back so your head and upper chest are both in view, and face a light.';

// ExpressionType enum from the SmartSpectra data-types schema.
const EXPRESSIONS = [null, 'Angry', 'Contempt', 'Disgust', 'Fear', 'Happy', 'Neutral', 'Sad', 'Surprise'];
const STATUS = Object.fromEntries(Object.entries(ProcessingStatus).map(([k, v]) => [v, k.slice(1)]));
const VALIDATION = Object.fromEntries(Object.entries(ValidationCode).map(([k, v]) => [v, k.slice(1)]));

const $ = (id) => document.getElementById(id);
const latest = (arr) => (arr && arr.length ? arr[arr.length - 1] : null);

// Latest reading of each signal and when it arrived; sent to the backend once per second.
const vitals = { pulse: null, breathing: null, expression: null, face_ok: false };
const updatedAt = { pulse: 0, breathing: 0, expression: 0 };
let recoveries = 0;

function setVital(key, value) {
    vitals[key] = value;
    updatedAt[key] = Date.now();
}

function freshVitals() {
    const now = Date.now();
    const fresh = (key) => (now - updatedAt[key] < STALE_MS ? vitals[key] : null);
    return { pulse: fresh('pulse'), breathing: fresh('breathing'), expression: fresh('expression'), face_ok: vitals.face_ok };
}

// --- SmartSpectra ----------------------------------------------------------

const sdk = new SmartSpectraSDK({
    apiKey: new URLSearchParams(location.search).get('key'),
    requestedMetrics: [...breathingMetrics, ...cardioMetrics, ...faceMetrics],
});

sdk.on('streamAvailable', (stream) => {
    $('preview').srcObject = stream;
    $('preview').play().catch(() => {});
});

sdk.on('processingStatus', (status) => {
    $('status').textContent = STATUS[status] ?? `Status ${status}`;
    if (status === ProcessingStatus.kError) recover();
});

sdk.on('validationStatus', (code, _ts, hint) => {
    vitals.face_ok = code === ValidationCode.kOk;
    $('hint').textContent = vitals.face_ok ? 'Signal good' : hint || VALIDATION[code] || '';
    $('hint').className = 'hint ' + (vitals.face_ok ? 'ok' : 'warn');
    if (!ws && !vitals.face_ok) setStage(`${hint || 'Adjusting…'} ${POSITION_TIP}`);
});

sdk.on('metrics', (buf) => {
    const m = decodeMetrics(buf);

    const pulse = latest(m.cardio?.pulseRate);
    if (pulse) {
        setVital('pulse', pulse.value);
        $('pulse').textContent = pulse.value.toFixed(0);
        recoveries = 0;
        if (!ws) connect(); // the game starts only once the SDK is really measuring
    }
    const breathing = latest(m.breathing?.rate);
    if (breathing) {
        setVital('breathing', breathing.value);
        $('breathing').textContent = breathing.value.toFixed(0);
    }
    const scores = latest(m.face?.expression)?.scores;
    if (scores?.length) {
        const top = scores.reduce((a, b) => (b.confidence > a.confidence ? b : a));
        setVital('expression', EXPRESSIONS[top.type] ?? null);
        $('expression').textContent = vitals.expression ?? '—';
        $('expression-conf').textContent = `${top.confidence.toFixed(0)}%`;
    }
});

sdk.on('error', (code, message) => console.warn(`[sdk] error ${code}: ${message}`));

// The SDK enters kError if it cannot measure for too long (e.g. chest out of
// view). reset() + start() is its documented recovery path.
async function recover() {
    if (recoveries >= MAX_RECOVERIES) {
        showError(`The camera could not get a reading. ${POSITION_TIP} Then press Play again.`);
        return;
    }
    recoveries++;
    // Mid-game, never cover the question; the video corner label is enough.
    if (ws) {
        $('hint').textContent = 'Camera reconnecting…';
        $('hint').className = 'hint warn';
    } else {
        setStage(`Re-calibrating the camera… ${POSITION_TIP}`);
    }
    try {
        await sdk.reset();
        await sdk.start();
    } catch (err) {
        showError(`Camera could not restart: ${err.message}`);
    }
}

// --- Backend ---------------------------------------------------------------

let ws = null;
let baselineTimer = null;

function send(msg) {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

// --- Voice -----------------------------------------------------------------

const SPEECH_WAIT_MS = 5000; // if the detective's voice doesn't arrive, open the mic anyway
let micReady = false;
let micOpen = false;
let currentQuestion = 0;
let playing = null;

// Captures 16 kHz PCM via an AudioWorklet; chunks are only sent while micOpen.
async function setupMic() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
        });
        const ctx = new AudioContext({ sampleRate: 16000 });
        await ctx.audioWorklet.addModule('./mic-worklet.js');
        const node = new AudioWorkletNode(ctx, 'mic-capture');
        node.port.onmessage = (e) => {
            if (micOpen && ws?.readyState === WebSocket.OPEN) ws.send(e.data);
        };
        ctx.createMediaStreamSource(stream).connect(node);
        node.connect(ctx.destination); // keeps the node processing; it outputs silence
        micReady = true;
    } catch (err) {
        console.warn('[mic] unavailable:', err);
        setMic('Microphone unavailable: type your answers.');
    }
}

function setMic(text, live = false) {
    $('mic').textContent = text;
    $('mic').className = live ? 'mic live' : 'mic';
}

function openMic(index) {
    if (!micReady || index !== currentQuestion || $('answer').disabled) return;
    micOpen = true;
    setMic('Listening… answer out loud, or type.', true);
}

function closeMic() {
    micOpen = false;
    setMic('');
}

function playSpeech(base64, onEnd) {
    playing?.pause();
    const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/mpeg' }));
    playing = new Audio(url);
    playing.onended = () => { URL.revokeObjectURL(url); onEnd?.(); };
    playing.play().catch(() => onEnd?.());
}

function answerSent() {
    closeMic();
    $('answer').value = '';
    $('answer').disabled = true;
    setStage('Inspector Noor is watching you…');
}

function connect() {
    ws = new WebSocket(BACKEND_URL);
    ws.onopen = () => send({ type: 'start', consent: true });
    ws.onmessage = (e) => onServerMessage(JSON.parse(e.data));
    ws.onclose = () => {
        if ($('verdict').hidden) showError('Lost connection to the game server. Is the backend running?');
    };
    setInterval(() => send({ type: 'vitals', ...freshVitals() }), VITALS_INTERVAL_MS);
}

function onServerMessage(msg) {
    switch (msg.type) {
        case 'case':
            $('case').textContent = msg.brief;
            if (msg.voice) setupMic();
            break;
        case 'phase':
            if (msg.phase === 'baseline') startBaselineCountdown(msg.seconds);
            if (msg.phase === 'detective') setStage('Inspector Noor is reviewing your answer…');
            break;
        case 'question': {
            clearInterval(baselineTimer);
            closeMic();
            currentQuestion = msg.index;
            setStage(`Question ${msg.index}: ${msg.text}`);
            $('answer-form').hidden = false;
            $('answer').disabled = false;
            $('answer').focus();
            if (micReady) setMic('Inspector Noor is speaking…');
            const index = msg.index;
            setTimeout(() => { if (!playing || playing.ended || playing.paused) openMic(index); }, SPEECH_WAIT_MS);
            break;
        }
        case 'speech':
            // index null = the verdict speech; otherwise mute the mic while Noor talks
            // (so the voice isn't transcribed) and open it when the question finishes.
            if (msg.index === currentQuestion && micOpen) closeMic();
            playSpeech(msg.audio, msg.index == null ? null : () => openMic(msg.index));
            break;
        case 'transcript':
            if (msg.final) answerSent();
            else $('answer').value = msg.text;
            break;
        case 'meter':
            setMeter(msg.value);
            break;
        case 'reaction':
            setMeter(msg.meter);
            addReason(msg.reasons.length ? msg.reasons.join(' · ') : `Question ${msg.index}: ${msg.signal}`);
            break;
        case 'verdict':
            showVerdict(msg);
            break;
        case 'error':
            showError(msg.message);
            break;
    }
}

// --- UI --------------------------------------------------------------------

function setStage(text) { $('stage').textContent = text; }

function setMeter(value) {
    $('meter-value').textContent = value;
    $('meter-fill').style.width = `${value}%`;
}

function addReason(text) {
    const li = document.createElement('li');
    li.textContent = text;
    $('reasons').prepend(li);
}

function showError(text) {
    $('error').hidden = false;
    $('error').textContent = text;
}

function startBaselineCountdown(seconds) {
    let left = seconds;
    const tick = () => setStage(left > 0
        ? `Calibrating… sit still, look at the camera and breathe normally. ${left--}s`
        : 'Almost there… hold still while your signal settles.');
    tick();
    baselineTimer = setInterval(tick, 1000);
}

function showVerdict(v) {
    $('answer-form').hidden = true;
    $('verdict-title').textContent = v.suspicious ? `SUSPICIOUS — ${v.meter}/100` : `CLEARED — ${v.meter}/100`;
    $('verdict-title').className = v.suspicious ? 'bad' : 'good';
    $('verdict-speech').textContent = v.speech;
    for (const t of v.timeline) {
        const tr = document.createElement('tr');
        for (const text of [t.index, t.question, t.answer, t.reasons.join(' · ') || t.signal]) {
            const td = document.createElement('td');
            td.textContent = text;
            tr.append(td);
        }
        $('timeline').append(tr);
    }
    $('verdict').hidden = false;
}

$('agree').addEventListener('change', (e) => { $('btn-consent').disabled = !e.target.checked; });

$('btn-consent').addEventListener('click', async () => {
    $('consent').hidden = true;
    setStage(`Starting camera… ${POSITION_TIP}`);
    try {
        // The SDK's default 1280x720 floods the renderer->main frame pipe and drops
        // below its 25 fps minimum on ordinary laptops; 640x360 holds 30 fps.
        const stream = await navigator.mediaDevices.getUserMedia({
            video: { width: 640, height: 360, frameRate: { ideal: 30 } },
        });
        sdk.useMediaStream(stream);
        $('preview').srcObject = stream;
        await sdk.start();
    } catch (err) {
        showError(`Camera could not start: ${err.message}`);
    }
});

$('answer-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const text = $('answer').value.trim();
    if (!text) return;
    send({ type: 'answer', text });
    answerSent();
});

$('btn-again').addEventListener('click', () => location.reload());

window.addEventListener('beforeunload', () => sdk.destroy());
