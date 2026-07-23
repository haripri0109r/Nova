# Project: Nova
Author: HARIPRIYAN
Repository: <my repository>

# Voice trigger “hello nova” → Nova‑style welcome

Python script that listens to your default microphone and runs a **wake‑phrase** welcome flow (Spotify, Chrome windows, ElevenLabs voice, Cursor) when it hears “hello nova” or “hey nova”. The STT engine is **Google Web Speech API** (requires internet, no API key). See constants in `src/nova/config.py` for behaviour and tuning.

## Setup

From this project directory:

```bash
python -m pip install -r requirements.txt
```

No model download is required – Google Web Speech API is used online.

## Environment variables

The script loads a **`.env` file** in the same folder as `nova.py` (via `python-dotenv`). You can also set variables in the shell.

### Required (ElevenLabs welcome line)

| Variable | Purpose |
| -------- | ------- |
| `ELEVENLABS_API_KEY` | API key from [ElevenLabs](https://elevenlabs.io). |
| `ELEVENLABS_VOICE_ID` | Voice ID from the ElevenLabs app (My Voices / library). |

Without these, the welcome speech is skipped (other actions may still run).

### Optional

| Variable | Purpose |
| -------- | ------- |
| `ELEVENLABS_MODEL_ID` | TTS model (default in code: `eleven_multilingual_v2`). |
| `ELEVENLABS_OUTPUT_FORMAT` | e.g. `pcm_24000` (must match playback expectations). |
| `ELEVENLABS_PCM_SAMPLE_RATE` | Override PCM sample rate if it differs from the format name. |
| `NOVA_WELCOME_CACHE_DIR` | Custom folder for cached welcome WAV (default: `.cache/NOVA_welcome/` under the project). |
| `CLAUDE_CODE_URL` | URL opened for Claude in Chrome (default: new chat). |
| `CHROME_NEW_WINDOW_WAIT_S` | Seconds to wait for a new Chrome window on Windows (default `25`). |
| `CHROME_WINDOW_WIDTH` / `CHROME_WINDOW_HEIGHT` | Windowed Chrome size when not fullscreen. |

Example `.env`:

```env
ELEVENLABS_API_KEY=your_key_here
ELEVENLABS_VOICE_ID=your_voice_id_here
```

## Run

```bash
python nova.py
```

Allow the microphone if Windows prompts you. Stop with **Ctrl+C**.

## Tuning

Edit the constants in `src/nova/config.py`:

| Constant                | Effect                                                               |
|------------------------ |----------------------------------------------------------------------|
| `SAMPLE_RATE`           | Microphone sample rate (default `44100`). Try `48000` if your device dislikes `44100`. |
| `BLOCK_MS`              | Audio block size in ms (default `40`). Larger = less CPU, slightly less timing precision. |
| `NOVA_WELCOME_ENABLED`  | Set `False` to disable the spoken welcome line.                     |
| `NOVA_AFTER_SONG_DELAY_S` | Seconds to wait after launching the song before speaking.          |

## Troubleshooting

- **Wrong or quiet mic:** On startup the script probes your default Windows input. If it is silent, it **auto-selects** the loudest working mic. To force a specific device, set `NOVA_INPUT_DEVICE` in `.env` (index or name substring from `sounddevice.query_devices()`).
- **PortAudio / audio errors:** Update audio drivers or try another `SAMPLE_RATE`.
- **Wake phrase not recognised:** Google Web Speech API requires an internet connection. Speak clearly; “hello nova” / “hey nova” must appear as whole words. Background noise can reduce accuracy.
- **Spam logs:** Adjust `BLOCK_MS` larger or verify only one instance runs.
- **No welcome speech:** Set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in `.env` and restart the terminal so variables load.
