# Poker Face: AI Detective

An interrogation game. Inspector Noor questions you about a stolen diamond while your webcam reads your pulse, breathing and expression live, using the [Presage SmartSpectra SDK](https://smartspectra.presagetech.com). Stay calm for 6 questions and you're cleared.

> Entertainment game. Not a real lie detector or medical tool.

## Requirements

- **Node.js 20+**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**, which installs Python 3.12 for you
- **Git Bash** on Windows, to run `start.sh`
- A webcam. A microphone is optional, for voice answers.
- API keys:
  - **SmartSpectra**, required. Get one at [physiology.presagetech.com](https://physiology.presagetech.com/auth/register).
  - **OpenAI**, required. Get one at [platform.openai.com](https://platform.openai.com/api-keys).
  - **Deepgram**, optional, for voice. Get one at [console.deepgram.com](https://console.deepgram.com). Without it, you type your answers.

Tested on Windows 10. The SDK also ships builds for macOS (Apple Silicon) and Linux.

## Install

```bash
git clone https://github.com/MuazAshraf/pokerface-smartspectra.git
cd pokerface-smartspectra
cp .env.example .env      # then open .env and paste your keys
npm install
cd backend && uv sync && cd ..
```

## Run

```bash
./start.sh
```

This starts the backend on `127.0.0.1:8000` and then opens the game window. Closing the window stops both.

<details>
<summary>Run the backend and app separately</summary>

```bash
npm run backend   # terminal 1
npm start         # terminal 2
```
</details>

## How to play

1. Tick the consent box and click **Start interrogation**.
2. Sit facing the camera in good light, with your head and shoulders in view.
3. Hold still for about 30 s while the game calibrates your calm baseline.
4. Answer 6 questions out loud, or type them. Noor speaks each question if voice is on.
5. See the verdict: **CLEARED** or **SUSPICIOUS**, with a timeline of what your signals did after each question.

**Tips:** use earphones so Noor's voice isn't picked up by the mic. Keep your face lit from the front and avoid moving around.

## Configuration (`.env`)

| Variable | Required | Default |
|---|---|---|
| `SMARTSPECTRA_API_KEY` | yes | |
| `OPENAI_API_KEY` | yes | |
| `DEEPGRAM_API_KEY` | no (enables voice) | |
| `DG_TTS_MODEL` | no | `aura-2-thalia-en` |
| `DG_EOT_THRESHOLD` | no | `0.75` |
| `DG_EOT_TIMEOUT_MS` | no | `1800` |
| `DG_MIP_OPT_OUT` | no | `true` |

`.env` is gitignored. The OpenAI and Deepgram keys stay in the backend and are never sent to the app window.

## Privacy

- **SmartSpectra:** vitals are computed on your computer. Presage's server is contacted only to validate the API key.
- **OpenAI:** receives your text answers and a short signal summary (e.g. "pulse +8 BPM") to write the next question. No video or images leave your computer.
- **Deepgram:** receives mic audio only while you're answering, and generates Noor's voice. The game opts out of Deepgram's model-improvement program.
- **Storage:** nothing is saved. Everything is discarded when the game ends.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Port 8000 is already in use` | An old backend is still running. Close it and run `./start.sh` again. |
| Electron opens as plain Node, or shows no window | Run `unset ELECTRON_RUN_AS_NODE` first (VS Code terminals set it). `start.sh` already does this. |
| Stuck on "Calibrating…" | Improve the lighting on your face, centre yourself and sit still. |
| "Lost connection to the game server" | The backend isn't running. Start it with `npm run backend`. |
| No voice | Check `DEEPGRAM_API_KEY` in `.env`. You can still type your answers. |

## Tests

```bash
cd backend && uv run pytest
```

## Architecture

```
Electron app (SmartSpectra SDK, camera, mic)  ──WebSocket──►  FastAPI backend
   pulse · breathing · expression · answers                   game rules + verdict (code)
                                                              OpenAI: questions, closing speech
                                                              Deepgram: speech-to-text, voice
```

The verdict is decided by code from your signal changes against your own baseline. The AI only writes the questions and rates how evasive each answer is, and evasiveness can't convict you on its own.

## Credits

- [Presage SmartSpectra SDK](https://smartspectra.presagetech.com). The Electron window setup is adapted from Presage's `electron-quickstart` sample.
- [OpenAI](https://openai.com) for the detective's questions, and [Deepgram](https://deepgram.com) for voice.
