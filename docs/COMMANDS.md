# Command file format (v2)

Files: `config/commands.default.json` (shipped, never edited by the app) and
`config/commands.json` (written by the GUI; if present the backend uses it
instead of the default). The GUI writes the FULL effective list to
`commands.json`, so the backend only ever reads one file.

```json
{
  "version": 2,
  "commands": [
    {
      "id": "landing_gear",                 // unique, [a-z0-9_]+
      "label": "Landing Gear",              // human name (GUI)            — backend ignores
      "category": "Landing & ATC",          // grouping (GUI)              — backend ignores
      "phrases": ["landing gear", "gear"],  // ENABLED phrases; the backend builds its grammar from these
      "disabled_phrases": ["gear up"],      // turned off in the GUI       — backend ignores
      "custom": false,                      // created on CUSTOM WORDS     — backend ignores
      "action": { ... },
      "tts_ack": "gear"                     // optional spoken confirmation
    }
  ]
}
```

The backend MUST ignore unknown fields (`label`, `category`, `disabled_phrases`, `custom`, and any future ones).
A command with zero enabled phrases is kept in the file but never matched.

## Actions

| type | fields | notes |
|---|---|---|
| `tap` | `keys` | e.g. `"n"`, `"left alt+n"`, `"right alt+k"`, `"alt+f4"`, `"num 7"` |
| `press` / `release` | `keys` | |
| `hold` | `keys`, `duration_ms` | |
| `mouse` | `button` (`left`,`right`,`middle`,`x1`,`x2`), `kind` (`click`,`double`,`down`,`up`), optional **`keys`** | **new:** `keys` modifiers are held down around the click, e.g. ship zoom `{"type":"mouse","button":"right","kind":"click","keys":"left alt"}` |
| `scroll` | `direction` (`up`,`down`), `amount` | |
| `system` | `op`, optional `responses: [string]` | **new.** `op`: `stop_listening` (turn listening off, then speak `tts_ack`), `stop_speaking` (stop TTS), `say_random` (speak one random entry of `responses`) |

Key names: modifiers `ctrl`/`alt`/`shift` (either side) or `left ctrl`, `right alt`, … ; letters, digits,
`f1`–`f24`, `space`, `tab`, `enter`, `escape`, `backspace`, arrows, numpad keys written `numpad0`–`numpad9`
(the GUI's CommandStore converts `num 7` / `numpad 7` to `numpad7` when you type them), etc. —
the authoritative list is `backend/src/input/vk_map.zig`.

## Built-in system commands (in the default file)

| id | phrases | action |
|---|---|---|
| `voice_off` | computer turn off, computer off, computer stop listening, computer stop, computer disable | `system/stop_listening`, `tts_ack` "Voice protocol offline. Thank you for flying with me." |
| `stop_talking` | robot stop talking, robot shut up, robot stop speaking, stop talking robot, stop speaking robot | `system/stop_speaking` |
| `thanks_computer` | thank you computer, thanks computer, thank you robot, thanks robot | `system/say_random` with friendly `responses` |
