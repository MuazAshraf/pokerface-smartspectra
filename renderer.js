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

// ExpressionType enum from the SmartSpectra data-types schema.
const EXPRESSIONS = ['—', 'Angry', 'Contempt', 'Disgust', 'Fear', 'Happy', 'Neutral', 'Sad', 'Surprise'];
const STATUS = Object.fromEntries(Object.entries(ProcessingStatus).map(([k, v]) => [v, k.slice(1)]));
const VALIDATION = Object.fromEntries(Object.entries(ValidationCode).map(([k, v]) => [v, k.slice(1)]));

const $ = (id) => document.getElementById(id);
const latest = (arr) => (arr && arr.length ? arr[arr.length - 1] : null);

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
    const busy = status === ProcessingStatus.kStarting || status === ProcessingStatus.kRunning;
    $('btn-start').disabled = busy || status === ProcessingStatus.kStopping;
    $('btn-stop').disabled = !busy;
});

sdk.on('validationStatus', (code, _ts, hint) => {
    $('hint').textContent = hint || VALIDATION[code] || '';
    $('hint').className = 'hint ' + (code === ValidationCode.kOk ? 'ok' : 'warn');
});

sdk.on('metrics', (buf) => {
    const m = decodeMetrics(buf);

    const pulse = latest(m.cardio?.pulseRate);
    if (pulse) $('pulse').textContent = pulse.value.toFixed(0);

    const breathing = latest(m.breathing?.rate);
    if (breathing) $('breathing').textContent = breathing.value.toFixed(0);

    const scores = latest(m.face?.expression)?.scores;
    if (scores?.length) {
        const top = scores.reduce((a, b) => (b.confidence > a.confidence ? b : a));
        $('expression').textContent = EXPRESSIONS[top.type] ?? '—';
        $('expression-conf').textContent = `${top.confidence.toFixed(0)}%`;
    }
});

sdk.on('error', (code, message) => {
    $('error').hidden = false;
    $('error').textContent = `${code}: ${message}`;
});

$('btn-start').addEventListener('click', async () => {
    $('error').hidden = true;
    try {
        await sdk.start();
    } catch (err) {
        $('error').hidden = false;
        $('error').textContent = `${err.code ?? 'Error'}: ${err.message}`;
    }
});

$('btn-stop').addEventListener('click', () => sdk.stop());

window.addEventListener('beforeunload', () => sdk.destroy());
