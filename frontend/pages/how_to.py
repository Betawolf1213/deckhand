"""HOW TO page: a short manual for voice control, editing and spoken questions."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from pages.base import Page

# (kind, text): kind is "h" (heading), "p" (paragraph), "say" (example phrase line)
SECTIONS: list[tuple[str, str]] = [
    ("h", "1. GET LISTENING"),
    ("p", "start.bat runs the voice backend as Administrator so its key presses reach Star Citizen, and opens "
          "this window. On VOICE press START LISTENING (or your listening hotkey — Ctrl+Shift+F12 "
          "unless you changed it on CUSTOMIZE). The status switches to LISTENING and the microphone meter moves "
          "when you talk. Pick a different microphone on CUSTOMIZE."),
    ("h", "2. SAY A COMMAND"),
    ("p", "Keep Star Citizen as the active window and say a phrase clearly, then pause briefly. Every phrase "
          "you say shows up in the HISTORY panel: HEARD is what the computer understood, COMMAND is the action it "
          "pressed, WARN means nothing matched. Examples:"),
    ("say", "landing gear"),
    ("say", "quantum drive"),
    ("say", "flight ready"),
    ("h", "3. MAKE IT YOURS"),
    ("p", "PHRASES — turn individual phrases on or off and add your own wording for any action.\n"
          "KEYBINDS — change which key or key combination each action presses so it matches your in-game "
          "bindings (combinations such as left alt+n or ctrl+shift+v work).\n"
          "CUSTOM WORDS — create brand-new voice actions: name, keybind, tap or hold, and one or more phrases.\n"
          "Changes are saved and sent to the backend immediately; no restart needed."),
    ("h", "4. ASK QUESTIONS"),
    ("p", "Start with where / what / which / how / show / find and the computer answers out loud instead of "
          "pressing a key. The full result opens on the matching page. Try:"),
    ("say", "where can I mine iron"),
    ("say", "where can I buy an Atlas component"),
    ("say", "where can I buy a Deadbolt five ship weapon"),
    ("say", "what is K bound to"),
    ("h", "5. TALK TO THE COMPUTER"),
    ("say", "computer turn off  — stops listening (say it, or press the hotkey, to go quiet)"),
    ("say", "robot stop talking  — interrupts a long spoken answer"),
    ("say", "thank you computer  — you'll get a friendly reply"),
    ("h", "TIPS"),
    ("p", "Speak at a normal volume a hand's width from the microphone. If phrases are missed, watch HEARD in "
          "the history to see what the computer thought you said and add that wording on PHRASES. Voice, "
          "volume and speed of the spoken replies are on CUSTOMIZE; STOP SPEAKING on VOICE silences it."),
]


class HowToPage(Page):
    title = "HOW TO"

    def build(self) -> None:
        ttk.Label(self, text="HOW TO", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="A quick guide to listening, commands, customising and spoken questions.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, wrap="word", padx=14, pady=10, font=("Segoe UI", 10), cursor="arrow")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.ctx.theme.style_text(self.text)
        self.text.bind("<<DeckhandTheme>>", lambda _e: self._color_tags())
        self._color_tags()
        for kind, line in SECTIONS:
            if kind == "h":
                self.text.insert("end", line + "\n", "h")
            elif kind == "say":
                self.text.insert("end", "  “" + line.split("  — ")[0] + "”", "say")
                if "  — " in line:
                    self.text.insert("end", "  — " + line.split("  — ", 1)[1], "p")
                self.text.insert("end", "\n")
            else:
                self.text.insert("end", line + "\n", "p")
        self.text.configure(state="disabled")

    def _color_tags(self) -> None:
        c = self.ctx.theme.colors
        self.text.tag_configure("h", foreground=c["accent"], font=("Segoe UI", 11, "bold"),
                                spacing1=12, spacing3=4)
        self.text.tag_configure("p", foreground=c["fg"], spacing3=4)
        self.text.tag_configure("say", foreground=c["accent"], font=("Segoe UI", 10, "italic"),
                                lmargin1=18)


PAGE_CLASS = HowToPage
