"""PHRASES page: edit each command's phrases and action; saves via CommandStore (backend reload)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from pages.base import Page
from pages.keybind_widget import ActionEditor, report_error, store_is_editable
from services.command_store import CUSTOM_CATEGORY, describe_action, key_display, normalize_phrase, validate_action


class PhrasesPage(Page):
    title = "PHRASES"

    def build(self) -> None:
        self.store = self.ctx.commands
        self.read_only = not store_is_editable(self.store)
        self.current_id: str | None = None
        self.visible_ids: list[str] = []
        self.phrase_rows: list[tuple[str, tk.BooleanVar]] = []

        ttk.Label(self, text="PHRASES", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, style="Muted.TLabel", wraplength=900, text=(
            "Choose a group and a command. Untick a phrase to stop listening for it without deleting it. "
            "Edit the keybind, then SAVE — the voice engine reloads automatically.")).pack(anchor="w", pady=(2, 8))

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="GROUP").pack(side="left", padx=(0, 6))
        self.group_var = tk.StringVar()
        self.group_combo = ttk.Combobox(top, textvariable=self.group_var, state="readonly", width=28)
        self.group_combo.pack(side="left")
        self.group_combo.bind("<<ComboboxSelected>>", lambda _e: self.select_group(self.group_var.get()))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=(8, 0))

        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        self.command_list = tk.Listbox(left, width=38, height=18, exportselection=False, activestyle="none")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.command_list.yview)
        self.command_list.configure(yscrollcommand=sb.set)
        self.command_list.pack(side="left", fill="y")
        sb.pack(side="left", fill="y")
        self.ctx.theme.style_listbox(self.command_list)
        self.command_list.bind("<<ListboxSelect>>", self._on_list_select)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.cmd_title = ttk.Label(right, text="", style="Title.TLabel")
        self.cmd_title.pack(anchor="w")
        self.cmd_info = ttk.Label(right, text="", style="Muted.TLabel")
        self.cmd_info.pack(anchor="w", pady=(0, 6))

        pbox = ttk.LabelFrame(right, text="PHRASES (ticked = listening)", style="Card.TLabelframe", padding=6)
        pbox.pack(fill="both", expand=True)
        holder = ttk.Frame(pbox)
        holder.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(holder, height=150, highlightthickness=0, bd=0)
        csb = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=csb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        csb.pack(side="left", fill="y")
        self.rows_frame = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>",
                             lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        # mouse wheel scrolls the phrase list only while the pointer is over it
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all(
            "<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))
        addrow = ttk.Frame(pbox)
        addrow.pack(fill="x", pady=(6, 0))
        self.new_phrase_var = tk.StringVar()
        self.new_phrase_entry = ttk.Entry(addrow, textvariable=self.new_phrase_var)
        self.new_phrase_entry.pack(side="left", fill="x", expand=True)
        self.new_phrase_entry.bind("<Return>", lambda _e: self.add_phrase())
        self.add_btn = ttk.Button(addrow, text="ADD PHRASE", command=self.add_phrase)
        self.add_btn.pack(side="left", padx=(6, 0))

        abox = ttk.LabelFrame(right, text="ACTION", style="Card.TLabelframe", padding=6)
        abox.pack(fill="x", pady=(8, 0))
        self.action_editor = ActionEditor(abox, on_change=self.update_preview)
        self.action_editor.pack(fill="x")

        self.preview_var = tk.StringVar()
        ttk.Label(right, textvariable=self.preview_var, style="Muted.TLabel",
                  wraplength=560).pack(anchor="w", pady=(8, 4))

        btns = ttk.Frame(right)
        btns.pack(fill="x")
        self.save_btn = ttk.Button(btns, text="SAVE PHRASES + KEYBIND", style="Accent.TButton", command=self.save)
        self.save_btn.pack(side="left")
        self.reset_btn = ttk.Button(btns, text="RESET TO DEFAULT", command=self.reset_to_default)
        self.reset_btn.pack(side="left", padx=(8, 0))
        if self.read_only:
            for b in (self.save_btn, self.reset_btn, self.add_btn):
                b.state(["disabled"])
            self.preview_var.set("Read-only: the command store cannot be edited in this session.")

        self.store.add_listener(self._on_store_saved)
        self.refresh()
        load_error = getattr(self.store, "load_error", None)
        if load_error:
            self.ctx.history(load_error, "warn")

    # ------------------------------------------------------------ hooks

    def on_show(self) -> None:
        self.canvas.configure(bg=self.ctx.theme.colors.get("panel", "#171d24"))
        self.refresh()

    def _on_store_saved(self) -> None:
        try:
            if self.winfo_exists():
                self.refresh()
        except tk.TclError:
            pass

    # ------------------------------------------------------------ lists

    def refresh(self) -> None:
        cats = self.store.categories()
        self.group_combo["values"] = cats
        group = self.group_var.get()
        if group not in cats:
            group = cats[0] if cats else ""
        self.select_group(group, keep=self.current_id)

    def _in_group(self, c: dict, group: str) -> bool:
        if c.get("custom"):
            return group == CUSTOM_CATEGORY
        return c.get("category") == group

    def select_group(self, group: str, keep: str | None = None) -> None:
        self.group_var.set(group)
        cmds = [c for c in self.store.all() if self._in_group(c, group)]
        self.visible_ids = [c["id"] for c in cmds]
        modified = getattr(self.store, "is_modified", lambda _i: False)
        self.command_list.delete(0, "end")
        for c in cmds:
            mark = " *" if modified(c["id"]) else ""
            keys = key_display(c.get("action", {}))
            self.command_list.insert("end", f"{c.get('label', c['id'])}{mark}" + (f"   [{keys}]" if keys else ""))
        target = keep if keep in self.visible_ids else (self.visible_ids[0] if self.visible_ids else None)
        if target:
            self.select_command(target)
        else:
            self.current_id = None
            self._load_rows([], [])

    def _on_list_select(self, _e=None) -> None:
        sel = self.command_list.curselection()
        if sel:
            self.select_command(self.visible_ids[sel[0]])

    def select_command(self, command_id: str) -> None:
        c = self.store.get(command_id)
        if c is None:
            return
        self.current_id = command_id
        if command_id in self.visible_ids:
            i = self.visible_ids.index(command_id)
            self.command_list.selection_clear(0, "end")
            self.command_list.selection_set(i)
            self.command_list.see(i)
        self.cmd_title.configure(text=c.get("label", command_id))
        modified = getattr(self.store, "is_modified", lambda _i: False)(command_id)
        kind = "custom command" if c.get("custom") else ("modified" if modified else "default")
        self.cmd_info.configure(text=f"{c.get('category', '')}  ·  id: {command_id}  ·  {kind}")
        self._load_rows(c.get("phrases", []), c.get("disabled_phrases", []))
        self.action_editor.set_action(c.get("action", {"type": "tap", "keys": ""}))
        if not self.read_only:
            self.reset_btn.state(["!disabled"] if not c.get("custom") else ["disabled"])
        self.update_preview()

    # ------------------------------------------------------------ phrase rows

    def _load_rows(self, enabled: list[str], disabled: list[str]) -> None:
        self.phrase_rows = [(p, tk.BooleanVar(value=True)) for p in enabled]
        self.phrase_rows += [(p, tk.BooleanVar(value=False)) for p in disabled]
        self._render_rows()

    def _render_rows(self) -> None:
        for w in self.rows_frame.winfo_children():
            w.destroy()
        for phrase, var in self.phrase_rows:
            row = ttk.Frame(self.rows_frame)
            row.pack(fill="x", anchor="w")
            ttk.Checkbutton(row, text=phrase, variable=var, command=self.update_preview).pack(side="left")
            rm = ttk.Button(row, text="REMOVE", width=8, command=lambda p=phrase: self.remove_phrase(p))
            rm.pack(side="right", padx=(8, 0))
            if self.read_only:
                rm.state(["disabled"])
        self.update_preview()

    def add_phrase(self) -> None:
        phrase = normalize_phrase(self.new_phrase_var.get())
        if not phrase or self.current_id is None:
            return
        if phrase in [p for p, _ in self.phrase_rows]:
            report_error(self, self.ctx, "Phrases", f"'{phrase}' is already in the list.")
            return
        self.phrase_rows.append((phrase, tk.BooleanVar(value=True)))
        self.new_phrase_var.set("")
        self._render_rows()

    def remove_phrase(self, phrase: str) -> None:
        self.phrase_rows = [(p, v) for p, v in self.phrase_rows if p != phrase]
        self._render_rows()

    # ------------------------------------------------------------ preview / save

    def _current_lists(self) -> tuple[list[str], list[str]]:
        enabled = [p for p, v in self.phrase_rows if v.get()]
        disabled = [p for p, v in self.phrase_rows if not v.get()]
        return enabled, disabled

    def update_preview(self) -> None:
        if not hasattr(self, "preview_var") or self.read_only:
            return
        enabled, _ = self._current_lists()
        try:
            what = describe_action(validate_action(self.action_editor.get_action()))
        except ValueError as e:
            what = f"(incomplete: {e})"
        said = ", ".join(f'"{p}"' for p in enabled) or "(no phrase enabled — this command will never trigger)"
        self.preview_var.set(f"{said}  →  {what}")

    def save(self) -> None:
        if self.read_only or self.current_id is None:
            return
        cid = self.current_id
        enabled, disabled = self._current_lists()
        try:
            action = self.action_editor.get_action()
            with self.store.transaction():
                self.store.set_action(cid, action)
                self.store.set_phrases(cid, enabled, disabled)
                self.store.save()
        except ValueError as e:
            report_error(self, self.ctx, "Phrases", e)
            return
        except OSError as e:
            report_error(self, self.ctx, "Phrases", f"Could not write the commands file: {e}")
            return
        c = self.store.get(cid) or {}
        self.ctx.history(
            f"Saved {len(c.get('phrases', []))} phrase(s) and '{key_display(c.get('action', {})) or describe_action(c.get('action', {}))}' "
            f"for {c.get('label', cid)}.", "info")
        self.select_command(cid)

    def reset_to_default(self) -> None:
        if self.read_only or self.current_id is None:
            return
        cid = self.current_id
        try:
            with self.store.transaction():
                self.store.reset_command(cid)
                self.store.save()
        except ValueError as e:
            report_error(self, self.ctx, "Reset", e)
            return
        except OSError as e:
            report_error(self, self.ctx, "Reset", f"Could not write the commands file: {e}")
            return
        c = self.store.get(cid) or {}
        self.ctx.history(f"Reset {c.get('label', cid)} to its default phrases and keybind.", "info")
        self.select_command(cid)


PAGE_CLASS = PhrasesPage
