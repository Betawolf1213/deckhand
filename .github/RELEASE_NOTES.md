**Offline voice commands for Star Citizen.** You fly; Deckhand handles the switches.

### Install

1. Download **`Deckhand-v2.0.0.zip`** below and unzip it anywhere (for example `C:\Games\Deckhand`).
2. Install **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/) if you don't have it
   (tick *Add python.exe to PATH*).
3. Double-click **`start.bat`**. The first start installs the GUI's two Python packages; after that it opens
   in a couple of seconds.

No Zig and no extra downloads needed: the speech model and engine are inside the zip.

### Use it

- **Ctrl+Shift+F12** starts/stops listening (change it on CUSTOMIZE). **Ctrl+Shift+F11** stops speech.
- Say a command: "landing gear", "quantum drive", "shields front", "power to weapons"…
- Ask: "what is N bound to?", "where can I mine iron?", "what resource is eight thousand five hundred forty?",
  "where can I buy an Atlas component?"
- Edit phrases and keybinds on the PHRASES and KEYBINDS pages; changes apply instantly.

### What's in 2.0.0

- **Offline recognition** (Vosk): your voice never leaves your PC.
- **Native Zig voice engine**: results 4–9 ms after you stop speaking; in-process Windows voices with
  0–300 % volume and a choice of output device.
- **Echo guard** so Deckhand doesn't react to its own voice, plus a stop-speaking hotkey and button.
- **73 commands / 275 phrases**, spoken questions for keybinds, mining, shopping, prices and lore.
- 15 GUI pages, 6 themes, mishearing tolerance, and a launcher that explains any start-up problem.

### Verify the download (optional)

```powershell
Get-FileHash .\Deckhand-v2.0.0.zip -Algorithm SHA256
```

Compare with `SHA256.txt` attached to this release.

### Known limitations

English voice commands only (more languages are on the roadmap). Over speakers Deckhand can't hear you
while it is talking; a headset avoids that. If the game runs as administrator, Deckhand must too.

MIT licensed; the bundled Vosk engine and model are Apache 2.0 (see `THIRD_PARTY_NOTICES.md` in the zip).
Fan-made tool, not affiliated with or endorsed by Cloud Imperium Games.
