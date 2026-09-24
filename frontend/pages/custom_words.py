"""CUSTOM WORDS page: create/edit custom commands (name, subcategory, keybind, phrases)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from pages.base import Page
from pages.keybind_widget import KeybindEditor, report_error, store_is_editable
from services.command_store import CUSTOM_CATEGORY, describe_action, normalize_phrase


class CustomWordsPage(Page):
    title = "CUSTOM WORDS"

    def build(self) -> None:
        self.store = self.ctx.commands
        self.read_only = not store_is_editable(self.store)
        self.editing_id: str | None = None
        self.existing_ids: list[str] = []
        self.phrase_rows: list[tuple[tk.BooleanVar, tk.StringVar, ttk.Frame]] = []
        self._sel_id: str | None = None
        self._sel_phrases: list[str] = []

        ttk.Label(self, text="CUSTOM WORDS", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, style="Muted.TLabel", wraplength=900, text=(
            "Create your own voice command: name it, choose the key it presses and the phrases that trigger it. "
            "Untick a phrase row to keep it without listening for it.")).pack(anchor="w", pady=(2, 8))

        form = ttk.LabelFrame(self, text="NEW / EDIT COMMAND", style="Card.TLabelframe", padding=8)
        form.pack(fill="x")
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(2, weight=1)
        for col, text in enumerate(("ACTION NAME", "SUBCATEGORY", "KEYBIND")):
            ttk.Label(form, text=text, style="Muted.TLabel").grid(row=0, column=col, sticky="w", padx=4)
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var).grid(row=1, column=0, sticky="new", padx=4)
        self.subcat_var = tk.StringVar()
        self.subcat_combo = ttk.Combobox(form, textvariable=self.subcat_var)
        self.subcat_combo.grid(row=1, column=1, sticky="new", padx=4)
        self.key_editor = KeybindEditor(form)
        self.key_editor.grid(row=1, column=2, sticky="new", padx=4)

        trow = ttk.Frame(form)
        trow.grid(row=2, column=0, columnspan=3, sticky="w", padx=4, pady=(8, 0))
        ttk.Label(trow, text="ACTION TYPE", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.type_var = tk.StringVar(value="Tap")
        ttk.Combobox(trow, textvariable=self.type_var, values=["Tap", "Hold"], state="readonly",
                     width=6).pack(side="left")
        ttk.Label(trow, text="HOLD SECONDS", style="Muted.TLabel").pack(side="left", padx=(12, 6))
        self.hold_var = tk.StringVar(value="1.0")
        ttk.Spinbox(trow, textvariable=self.hold_var, from_=0.1, to=60, increment=0.1,
                    width=6).pack(side="left")

        ph = ttk.LabelFrame(form, text="TRIGGER PHRASES (ticked = listening)", style="Card.TLabelframe", padding=6)
        ph.grid(row=3, column=0, columnspan=3, sticky="ew", padx=4, pady=(8, 0))
        self.rows_frame = ttk.Frame(ph)
        self.rows_frame.pack(fill="x")
        self.add_row_btn = ttk.Button(ph, text="ADD PHRASE", command=self.add_phrase_row)
        self.add_row_btn.pack(anchor="w", pady=(6, 0))

        btns = ttk.Frame(form)
        btns.grid(row=4, column=0, columnspan=3, sticky="w", padx=4, pady=(8, 0))
        self.save_btn = ttk.Button(btns, text="CREATE CUSTOM COMMAND", style="Accent.TButton", command=self.save)
        self.save_btn.pack(side="left")
        ttk.Button(btns, text="CLEAR FORM / NEW", command=self.clear_form).pack(side="left", padx=(8, 0))
        self.mode_var = tk.StringVar()
        ttk.Label(btns, textvariable=self.mode_var, style="Muted.TLabel").pack(side="left", padx=(12, 0))

        lower = ttk.Frame(self)
        lower.pack(fill="both", expand=True, pady=(10, 0))
        lbox = ttk.LabelFrame(lower, text="EXISTING CUSTOM COMMANDS", style="Card.TLabelframe", padding=6)
        lbox.pack(side="left", fill="both", expand=True)
        self.existing_list = tk.Listbox(lbox, height=9, exportselection=False, activestyle="none")
        self.ctx.theme.style_listbox(self.existing_list)
        self.existing_list.pack(fill="both", expand=True)
        self.existing_list.bind("<<ListboxSelect>>", self._on_existing_select)
        self.delete_cmd_btn = ttk.Button(lbox, text="DELETE CUSTOM COMMAND", command=self.delete_custom_command)
        self.delete_cmd_btn.pack(anchor="w", pady=(6, 0))

        pbox = ttk.LabelFrame(lower, text="PHRASES IN SELECTED COMMAND", style="Card.TLabelframe", padding=6)
        pbox.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.selected_phrases_list = tk.Listbox(pbox, height=9, exportselection=False, activestyle="none")
        self.ctx.theme.style_listbox(self.selected_phrases_list)
        self.selected_phrases_list.pack(fill="both", expand=True)
        self.delete_phrase_btn = ttk.Button(pbox, text="DELETE SELECTED PHRASE", command=self.delete_selected_phrase)
        self.delete_phrase_btn.pack(anchor="w", pady=(6, 0))

        if self.read_only:
            for b in (self.save_btn, self.delete_cmd_btn, self.delete_phrase_btn, self.add_row_btn):
                b.state(["disabled"])
            self.mode_var.set("Read-only: the command store cannot be edited in this session.")

        self.store.add_listener(self._on_store_saved)
        self.clear_form()
        self.refresh()

    # ------------------------------------------------------------ hooks

    def on_show(self) -> None:
        self.refresh()

    def _on_store_saved(self) -> None:
        try:
            if self.winfo_exists():
                self.refresh()
        except tk.TclError:
            pass

    def refresh(self) -> None:
        customs = [c for c in self.store.all() if c.get("custom")]
        self.existing_ids = [c["id"] for c in customs]
        self.existing_list.delete(0, "end")
        for c in customs:
            sub = c.get("category", "")
            sub = "" if sub == CUSTOM_CATEGORY else f"  ({sub})"
            self.existing_list.insert("end", f"{c.get('label', c['id'])}{sub}   →  {describe_action(c.get('action', {}))}")
        subcats = []
        for c in customs:
            cat = c.get("category", "")
            if cat and cat != CUSTOM_CATEGORY and cat not in subcats:
                subcats.append(cat)
        self.subcat_combo["values"] = subcats
        if self._sel_id not in self.existing_ids:
            self._sel_id = None
        self._show_selected(self._sel_id)
        if self.editing_id and self.editing_id not in self.existing_ids:
            self.clear_form()

    # ------------------------------------------------------------ phrase rows

    def add_phrase_row(self, text: str = "", enabled: bool = True) -> None:
        en = tk.BooleanVar(value=enabled)
        tv = tk.StringVar(value=text)
        row = ttk.Frame(self.rows_frame)
        row.pack(fill="x", pady=1)
        ttk.Checkbutton(row, variable=en).pack(side="left")
        ttk.Entry(row, textvariable=tv).pack(side="left", fill="x", expand=True)
        entry = (en, tv, row)
        ttk.Button(row, text="REMOVE", width=8,
                   command=lambda: self.remove_phrase_row(self._row_index(entry))).pack(side="left", padx=(6, 0))
        self.phrase_rows.append(entry)

    def _row_index(self, entry) -> int:
        return next(i for i, r in enumerate(self.phrase_rows) if r is entry)

    def remove_phrase_row(self, index: int) -> None:
        if 0 <= index < len(self.phrase_rows):
            _, _, frame = self.phrase_rows.pop(index)
            frame.destroy()
        if not self.phrase_rows:
            self.add_phrase_row()

    def _set_rows(self, rows: list[tuple[str, bool]]) -> None:
        for *_, frame in self.phrase_rows:
            frame.destroy()
        self.phrase_rows = []
        for text, enabled in rows:
            self.add_phrase_row(text, enabled)
        if not self.phrase_rows:
            self.add_phrase_row()

    # ------------------------------------------------------------ form

    def clear_form(self) -> None:
        self.editing_id = None
        self.name_var.set("")
        self.subcat_var.set("")
        self.key_editor.set("")
        self.type_var.set("Tap")
        self.hold_var.set("1.0")
        self._set_rows([])
        self.save_btn.configure(text="CREATE CUSTOM COMMAND")
        if not self.read_only:
            self.mode_var.set("Creating a new command.")

    def load_form(self, command_id: str) -> None:
        c = self.store.get(command_id)
        if c is None or not c.get("custom"):
            return
        self.editing_id = command_id
        self.name_var.set(c.get("label", ""))
        cat = c.get("category", "")
        self.subcat_var.set("" if cat == CUSTOM_CATEGORY else cat)
        action = c.get("action", {})
        self.key_editor.set(action.get("keys", ""))
        if action.get("type") == "hold":
            self.type_var.set("Hold")
            self.hold_var.set(f"{action.get('duration_ms', 1000) / 1000:g}")
        else:
            self.type_var.set("Tap")
        self._set_rows([(p, True) for p in c.get("phrases", [])] +
                       [(p, False) for p in c.get("disabled_phrases", [])])
        self.save_btn.configure(text="UPDATE CUSTOM COMMAND")
        self.mode_var.set(f"Editing '{c.get('label', command_id)}'. CLEAR FORM / NEW to create another.")

    def _form_action(self) -> dict:
        keys = self.key_editor.get()
        if not keys:
            raise ValueError("Enter a keybind.")
        if self.type_var.get() == "Hold":
            try:
                secs = float(self.hold_var.get().replace(",", "."))
            except ValueError:
                raise ValueError("Hold seconds must be a positive number.") from None
            if not 0 < secs <= 60:
                raise ValueError("Hold seconds must be between 0 and 60.")
            return {"type": "hold", "keys": keys, "duration_ms": int(round(secs * 1000))}
        return {"type": "tap", "keys": keys}

    def save(self) -> None:
        if self.read_only:
            return
        enabled = [normalize_phrase(t.get()) for e, t, _ in self.phrase_rows if e.get() and t.get().strip()]
        disabled = [normalize_phrase(t.get()) for e, t, _ in self.phrase_rows if not e.get() and t.get().strip()]
        label = self.name_var.get().strip()
        sub = self.subcat_var.get().strip()
        try:
            if not label:
                raise ValueError("Enter an action name.")
            action = self._form_action()
            if not enabled:
                raise ValueError("Add and tick at least one phrase.")
            with self.store.transaction():
                if self.editing_id is None:
                    cid = self.store.create_custom(label, sub, enabled, action, disabled_phrases=disabled)
                else:
                    cid = self.editing_id
                    self.store.update_custom(cid, label=label, category=sub)
                    self.store.set_action(cid, action)
                    self.store.set_phrases(cid, enabled, disabled)
                self.store.save()
        except ValueError as e:
            report_error(self, self.ctx, "Custom Words", e)
            return
        except OSError as e:
            report_error(self, self.ctx, "Custom Words", f"Could not write the commands file: {e}")
            return
        verb = "Created" if self.editing_id is None else "Updated"
        c = self.store.get(cid) or {}
        self.ctx.history(f"{verb} custom command '{c.get('label', cid)}' "
                         f"({describe_action(c.get('action', {}))}, {len(enabled)} phrase(s)).", "info")
        if self.editing_id is None:
            self.clear_form()
        else:
            self.load_form(cid)
        self._show_selected(cid)

    # ------------------------------------------------------------ existing list

    def _on_existing_select(self, _e=None) -> None:
        sel = self.existing_list.curselection()
        if sel:
            self.select_existing(self.existing_ids[sel[0]])

    def select_existing(self, command_id: str) -> None:
        self._show_selected(command_id)
        self.load_form(command_id)

    def _show_selected(self, command_id: str | None) -> None:
        self._sel_id = command_id
        self.selected_phrases_list.delete(0, "end")
        self._sel_phrases = []
        if command_id is None:
            self.existing_list.selection_clear(0, "end")
            return
        if command_id in self.existing_ids:
            i = self.existing_ids.index(command_id)
            self.existing_list.selection_clear(0, "end")
            self.existing_list.selection_set(i)
            self.existing_list.see(i)
        c = self.store.get(command_id) or {}
        for p in c.get("phrases", []):
            self._sel_phrases.append(p)
            self.selected_phrases_list.insert("end", p)
        for p in c.get("disabled_phrases", []):
            self._sel_phrases.append(p)
            self.selected_phrases_list.insert("end", f"{p} (off)")

    def delete_selected_phrase(self) -> None:
        if self.read_only:
            return
        cid = self._sel_id
        sel = self.selected_phrases_list.curselection()
        if cid is None:
            report_error(self, self.ctx, "Custom Words", "Select a custom command first.")
            return
        if not sel:
            report_error(self, self.ctx, "Custom Words", "Select a phrase to delete.")
            return
        phrase = self._sel_phrases[sel[0]]
        c = self.store.get(cid) or {}
        if len(c.get("phrases", [])) + len(c.get("disabled_phrases", [])) <= 1:
            report_error(self, self.ctx, "Custom Words",
                         f"'{c.get('label', cid)}' must keep at least one phrase. "
                         "Delete the whole command instead.")
            return
        if not messagebox.askyesno("Delete phrase", f"Delete the phrase '{phrase}'?", parent=self):
            return
        try:
            with self.store.transaction():
                self.store.remove_phrase(cid, phrase)
                self.store.save()
        except (ValueError, OSError) as e:
            report_error(self, self.ctx, "Custom Words", e)
            return
        self.ctx.history(f"Deleted phrase '{phrase}' from '{c.get('label', cid)}'.", "info")
        self._show_selected(cid)
        if self.editing_id == cid:
            self.load_form(cid)

    def delete_custom_command(self) -> None:
        if self.read_only:
            return
        cid = self._sel_id
        if cid is None:
            report_error(self, self.ctx, "Custom Words", "Select a custom command to delete.")
            return
        label = (self.store.get(cid) or {}).get("label", cid)
        if not messagebox.askyesno("Delete custom command", f"Delete '{label}' and all its phrases?", parent=self):
            return
        try:
            with self.store.transaction():
                self.store.delete_custom(cid)
                self.store.save()
        except (ValueError, OSError) as e:
            report_error(self, self.ctx, "Custom Words", e)
            return
        self.ctx.history(f"Deleted custom command '{label}'.", "info")
        if self.editing_id == cid:
            self.clear_form()
        self._show_selected(None)


PAGE_CLASS = CustomWordsPage
