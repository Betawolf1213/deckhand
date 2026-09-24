# Deckhand named-pipe protocol (v2)

Pipe: `\\.\pipe\deckhand`, message mode, one UTF-8 JSON object per message.
Both sides MUST peek (`PeekNamedPipe`) before `ReadFile` — a blocking read on
the shared synchronous handle stalls writes on the other thread.

Unknown message types are ignored (backend replies `log` level `warn`).
Unknown fields are ignored by both sides.

## GUI → backend (Inbound)

| type | fields | effect / reply |
|---|---|---|
| `ping` | — | replays `mic_ready`, `status`, `hotkey_status`, then `pong` |
| `set_listening` | `enabled: bool` | toggles listening; replies `status` |
| `set_tts_enabled` | `enabled: bool` | command acks on/off |
| `set_tts_voice` | `id: string` | registry token path, `""` = Windows default |
| `set_tts_volume` | `volume: int 0..300` | |
| `set_tts_rate` | `rate: int -10..10` | |
| `speak_text` | `text: string` | speaks even if TTS acks are off (answers, Test voice) |
| `stop_speaking` | — | **new** — stops current speech immediately, drops queued speech |
| `trigger_command` | `id: string` | fires a command as if spoken (bypasses cooldown) |
| `reload_config` | — | **new behaviour** — reload commands (`config/commands.json`, else `config/commands.default.json`), rebuild grammar + recognizer without restarting. Replies `config_reloaded` or `log` error (old config stays active on failure) |
| `reload_grammar` | — | alias of `reload_config` |
| `list_audio_devices` | — | **new** — replies `audio_devices` |
| `set_audio_device` | `id: string` | **new** — WASAPI endpoint id, `""` = Windows default capture device. Reopens capture; replies `mic_ready` (new device) or `log` error and keeps the old device |
| `set_hotkey` | `chord: string` | **new** — e.g. `"ctrl+shift+f12"`, `"f8"`, `"alt+f10"`; `""` disables. Replies `hotkey_status` |
| `set_stop_hotkey` | `chord: string` | **new** — dedicated stop-speaking chord (e.g. `"ctrl+shift+f11"`); `""` disables. Fires `stopSpeaking()` bypassing the echo guard — practical workaround for the "robot stop talking" phrase being swallowed when TTS plays over speakers. Replies `stop_hotkey_status` |
| `list_tts_output_devices` | — | **new** — replies `tts_output_devices` enumerating render endpoints |
| `set_tts_output_device` | `id: string` | **new** — WASAPI render endpoint id for TTS; `""` = Windows default. An id that is not an active render endpoint is rejected (`tts_output_device` with `ok:false, error:"NoDevice"`) and the previous device is kept. No-op when backend started with `--tts-legacy` (replies `tts_output_device` with `ok:false`) |

## Backend → GUI (Outbound)

| type | fields |
|---|---|
| `status` | `listening: bool, elevated: bool, engine: string` |
| `mic_ready` | `sample_rate: int, channels: int, device_id: string, device_name: string` (**device fields new**) |
| `audio_level` | `peak: float 0..1` (~20 Hz) |
| `transcript_partial` | `text: string` |
| `transcript_final` | `text: string, confidence: float` |
| `command_fired` | `id: string` |
| `no_match` | `text: string` |
| `question` | **new** — `text: string` free-form transcript that starts with a question lead (see below). The GUI answers it; the backend does NOT fire a command for this utterance |
| `system_action` | **new** — `op: string` (`stop_listening`, `stop_speaking`, `say_random`), `id: string` command id — informational, emitted after the backend performed it |
| `audio_devices` | **new** — `devices: [{id: string, name: string, is_default: bool}], current_id: string` |
| `hotkey_status` | **new** — `chord: string, ok: bool, error: string` (`""` when ok; e.g. `"already in use"`) |
| `stop_hotkey_status` | **new** — same shape as `hotkey_status`, for the dedicated stop-speaking chord |
| `tts_output_devices` | **new** — `devices: [{id: string, name: string, is_default: bool}], current_id: string, mode: "wasapi"|"legacy"` |
| `tts_output_device` | **new** — ack for `set_tts_output_device`. `id: string, name: string, ok: bool, error: string` |
| `config_reloaded` | **new** — `commands: int, phrases: int, path: string` |
| `log` | `level: "info"|"warn"|"error", msg: string` |
| `pong` | — |

## Recognition rules (backend)

1. Each utterance is decoded by the grammar recognizer (command phrases only) **and** a free-form
   recognizer on the same Vosk model.
2. If the free-form text starts with a question lead — `what`, `where`, `which`, `who`, `how`,
   `list`, `show`, `tell`, `find` — emit `question{text}` (plus `transcript_final`) and fire nothing.
3. Otherwise the grammar result is matched to a command as before.
4. **Cooldown:** the same command id cannot fire again from voice within 1500 ms (GUI `trigger_command` bypasses).
5. **Echo guard:** while TTS is queued/playing (+500 ms) mic audio is ignored, except that an utterance
   matching a `system` command with `op: "stop_speaking"` is still acted on.
6. Max utterance length is 4000 ms (was 30000).

Implementation notes (as built):
- Both recognizers are fed audio **while the user is speaking** (streaming), so the extra free-form
  decode costs ~5–45 ms after speech ends instead of 100–400 ms.
- 250 ms of pre-roll audio is kept before VAD speech start (otherwise the first word, e.g. "what", gets clipped).
- While no GUI is connected the pipe server drops outbound events instead of queueing them; the GUI
  pings on connect to get current state.
- Test/diagnostic CLI flags: `--replay-wav <wav>` (repeatable; feeds 16 kHz WAVs through the full voice
  path once a client connects), `--decode-wav <wav>...` (offline decode + latency), `--device <id>`.
- TTS playback flags: `--tts-legacy` routes TTS through the pre-2.1 `PlaySoundW` path (Windows default
  device only); default is WASAPI render (device-selectable via `--tts-output <id>` or the IPC
  `set_tts_output_device` message).
- Stop-speaking hotkey: `--stop-hotkey <chord>` at startup, or `set_stop_hotkey` over IPC at runtime.
  Bypasses the echo guard so it works while TTS is playing over speakers.

## GUI-internal messages

The shell also delivers `{"type": "_connection", "connected": bool}` to every page's
`on_backend_message` when the pipe connects/disconnects. It never goes over the pipe.
