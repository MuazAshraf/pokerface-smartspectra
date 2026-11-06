// Main process. Window + permission wiring adapted from Presage's
// electron-quickstart sample (nodejs/samples/electron-quickstart/main.js).
'use strict';

const path = require('path');
const { app, BrowserWindow, session } = require('electron');
const { bindSmartSpectraIpc } = require('@smartspectra/node-sdk/main');

process.loadEnvFile(path.join(__dirname, '.env'));
const API_KEY = process.env.SMARTSPECTRA_API_KEY;
if (!API_KEY) throw new Error('SMARTSPECTRA_API_KEY is missing — copy .env.example to .env and set it.');

function createWindow() {
    const win = new BrowserWindow({
        width: 1100,
        height: 760,
        backgroundColor: '#0b0c10',
        webPreferences: {
            preload: require.resolve('@smartspectra/node-sdk/preload'),
            contextIsolation: true,
            sandbox: true,
            nodeIntegration: false,
        },
    });

    bindSmartSpectraIpc(win);

    // Only our bundled page may run in this window (it holds the camera grant).
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('will-navigate', (event) => event.preventDefault());

    // The renderer-side SDK needs the key; hand it over at load time instead of
    // baking it into the bundle.
    win.loadFile(path.join(__dirname, 'index.html'), { query: { key: API_KEY } });
}

app.whenReady().then(() => {
    // Grant only camera (vitals) and microphone (voice answers), only to our local page.
    session.defaultSession.setPermissionRequestHandler((wc, permission, callback, details) => {
        const url = (details && details.requestingUrl) || (wc && wc.getURL()) || '';
        const mediaTypes = (details && details.mediaTypes) || [];
        const cameraOrMic = mediaTypes.length > 0 && mediaTypes.every((t) => t === 'video' || t === 'audio');
        callback(permission === 'media' && cameraOrMic && url.startsWith('file://'));
    });

    createWindow();
    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});
