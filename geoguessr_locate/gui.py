from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dotenv import load_dotenv
from PIL import Image, ImageTk, ImageGrab
import webbrowser
import folium

from .model_client import analyze_image, DEFAULT_MODEL, DEFAULT_PROVIDER, GEMINI_DEFAULT_MODEL, OPENAI_DEFAULT_MODEL
from .analysis import rank_and_finalize
from .cache import Cache
from .utils import get_cache_dir


class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=12)
        self.master.title("GeoGuessr Locate")
        self.grid(sticky=tk.NSEW)
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        # Base font sizing for better readability
        try:
            default_font = tk.font.nametofont("TkDefaultFont")
            default_font.configure(size=12)
        except Exception:
            pass
        # Controls
        self.image_path = tk.StringVar()
        self.model_name = tk.StringVar(value=DEFAULT_MODEL)
        self.top_k = tk.IntVar(value=5)
        self.provider = tk.StringVar(value=DEFAULT_PROVIDER)
        self.do_reverse = tk.BooleanVar(value=True)
        # Status variable early so provider change binding can reference it
        self.status = tk.StringVar(value="Ready")

        row = 0
        ttk.Label(self, text="Image:").grid(row=row, column=0, sticky=tk.W)
        path_entry = ttk.Entry(self, textvariable=self.image_path, width=60)
        path_entry.grid(row=row, column=1, sticky=tk.EW)
        btns = ttk.Frame(self)
        btns.grid(row=row, column=2, padx=6, sticky=tk.W)
        ttk.Button(btns, text="Browse", command=self._browse).pack(side=tk.LEFT)
        ttk.Button(btns, text="Paste", command=self._paste_image).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(btns, text="Capture", command=self._capture_screen).pack(side=tk.LEFT, padx=(6,0))
        self.columnconfigure(1, weight=1)

        row += 1
        ttk.Label(self, text="Model:").grid(row=row, column=0, sticky=tk.W)
        model_frame = ttk.Frame(self)
        model_frame.grid(row=row, column=1, columnspan=2, sticky=tk.W)
        ttk.Entry(model_frame, textvariable=self.model_name, width=24).pack(side=tk.LEFT)
        # Preset models
        preset_values = [
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ]
        preset_cb = ttk.Combobox(model_frame, width=16, values=preset_values, state="readonly")
        preset_cb.pack(side=tk.LEFT, padx=(4,0))
        ttk.Label(model_frame, text="Provider:").pack(side=tk.LEFT, padx=(8,2))
        prov_cb = ttk.Combobox(
            model_frame,
            textvariable=self.provider,
            width=8,
            values=["gemini", "openai"],
            state="readonly",
        )
        prov_cb.pack(side=tk.LEFT)
        # Provider change handler
        def _on_provider_change(_e=None):
            prov = self.provider.get()
            if prov == "openai" and self.model_name.get().startswith("gemini"):
                self.model_name.set(OPENAI_DEFAULT_MODEL)
            elif prov == "gemini" and self.model_name.get().startswith("gpt"):
                self.model_name.set(GEMINI_DEFAULT_MODEL)
            self.status.set(f"Provider: {prov}")
        prov_cb.bind("<<ComboboxSelected>>", _on_provider_change)
        # Apply preset after provider widgets exist so we can update provider automatically
        def _apply_preset(_e=None):
            sel = preset_cb.get()
            if not sel:
                return
            self.model_name.set(sel)
            if sel.startswith("gpt"):
                if self.provider.get() != "openai":
                    self.provider.set("openai")
                    _on_provider_change()
            elif sel.startswith("gemini"):
                if self.provider.get() != "gemini":
                    self.provider.set("gemini")
                    _on_provider_change()
            self.status.set(f"Model: {sel} ({self.provider.get()})")
        preset_cb.bind("<<ComboboxSelected>>", _apply_preset)

        row += 1
        ttk.Label(self, text="Top K:").grid(row=row, column=0, sticky=tk.W)
        ttk.Spinbox(self, from_=1, to=10, textvariable=self.top_k, width=6).grid(row=row, column=1, sticky=tk.W)
        ttk.Checkbutton(self, text="Reverse geocode", variable=self.do_reverse).grid(row=row, column=2, sticky=tk.W)

        row += 1
        self.run_btn = ttk.Button(self, text="Analyze", command=self._run)
        self.run_btn.grid(row=row, column=0, pady=(8, 8))
        self.save_btn = ttk.Button(self, text="Save JSON…", command=self._save_json, state=tk.DISABLED)
        self.save_btn.grid(row=row, column=1, pady=(8, 8), sticky=tk.W)
        self.copy_btn = ttk.Button(self, text="Copy JSON", command=self._copy_json, state=tk.DISABLED)
        self.copy_btn.grid(row=row, column=2, pady=(8, 8), sticky=tk.W)

        row += 1
        ttk.Label(self, textvariable=self.status).grid(row=row, column=0, columnspan=2, sticky=tk.W)
        self.pb = ttk.Progressbar(self, mode="indeterminate")
        self.pb.grid(row=row, column=2, sticky=tk.EW)

        row += 1
        # Preview and results area
        preview_frame = ttk.LabelFrame(self, text="Preview")
        preview_frame.grid(row=row, column=0, columnspan=3, sticky=tk.EW, pady=(8,4))
        self.preview_label = ttk.Label(preview_frame)
        self.preview_label.pack(anchor=tk.W, padx=6, pady=6)
        self._preview_photo = None

        row += 1
        # Results table
        self.tree = ttk.Treeview(self, columns=("rank","conf","country","region","city","lat","lon"), show="headings", height=10)
        for col, text in [
            ("rank","Rank"),("conf","Conf"),("country","Country"),("region","Region"),("city","City"),("lat","Lat"),("lon","Lon")
        ]:
            self.tree.heading(col, text=text)
            self.tree.column(col, stretch=True, width=100 if col not in ("rank","conf") else 60)
        self.tree.grid(row=row, column=0, columnspan=3, sticky=tk.NSEW, pady=(4,0))
        self.rowconfigure(row, weight=1)

        # Clues panel for primary guess
        row += 1
        clues_frame = ttk.LabelFrame(self, text="Primary clues")
        clues_frame.grid(row=row, column=0, columnspan=3, sticky=tk.EW, pady=(6,4))
        self.clues_text = tk.Text(clues_frame, height=6, wrap="word")
        self.clues_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.clues_text.configure(state=tk.DISABLED)

        # Bindings
        self.image_path.trace_add("write", lambda *_: self._load_preview())
        master.bind("<Return>", lambda _e: self._run())
        # macOS paste
        master.bind("<Command-v>", lambda _e: self._paste_image())
        # Windows/Linux
        master.bind("<Control-v>", lambda _e: self._paste_image())
        # Capture screen hotkeys (app-focused)
        master.bind("<F9>", lambda _e: self._capture_screen())
        master.bind("<Control-Shift-s>", lambda _e: self._capture_screen())

        # Global hotkeys (work even when minimized)
        self._hotkey_listener = None
        self._maybe_start_global_hotkeys()

        self._last_result = None
        self._primary_coords = None
        # Add Copy Coords alongside control buttons for convenience
        self.copy_coords_btn = ttk.Button(self, text="Copy coords", command=self._copy_coords, state=tk.DISABLED)
        self.copy_coords_btn.grid(row=3, column=2, pady=(8, 8), sticky=tk.E)

    def _browse(self):
        path = filedialog.askopenfilename(filetypes=[("Images","*.png *.jpg *.jpeg *.webp")])
        if path:
            self.image_path.set(path)

    def _paste_image(self):
        # Try to pull image or file path from the clipboard
        try:
            data = ImageGrab.grabclipboard()
        except Exception as e:
            messagebox.showerror("Paste failed", f"Cannot read clipboard: {e}")
            return
        if data is None:
            messagebox.showinfo("Paste", "Clipboard does not contain an image or image file path")
            return
        if isinstance(data, Image.Image):
            # Save to a temp file under cache dir
            cache_dir = get_cache_dir()
            cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix="pasted_", suffix=".png", dir=cache_dir, delete=False) as tmp:
                data.convert("RGB").save(tmp.name, format="PNG")
                self.image_path.set(tmp.name)
        elif isinstance(data, list) and data:
            # List of file paths
            self.image_path.set(str(data[0]))
        else:
            messagebox.showinfo("Paste", "Clipboard does not contain a supported image")

    def _capture_screen(self):
        # Capture the entire screen (all monitors if supported) and run analysis
        try:
            try:
                im = ImageGrab.grab(all_screens=True)
            except TypeError:
                # all_screens not available in older Pillow versions; fall back to primary screen
                im = ImageGrab.grab()
        except Exception as e:
            messagebox.showerror("Capture failed", f"Cannot capture screen: {e}")
            return
        try:
            cache_dir = get_cache_dir()
            cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix="capture_", suffix=".png", dir=cache_dir, delete=False) as tmp:
                im.convert("RGB").save(tmp.name, format="PNG")
                self.image_path.set(tmp.name)
        except Exception as e:
            messagebox.showerror("Capture failed", f"Cannot save capture: {e}")
            return
        # Automatically run analysis
        self._run()

    def _load_preview(self):
        path = self.image_path.get().strip()
        if not path or not Path(path).exists():
            self.preview_label.configure(image="", text="")
            self._preview_photo = None
            return
        try:
            im = Image.open(path)
            im = im.convert("RGB")
            im.thumbnail((720, 280))
            self._preview_photo = ImageTk.PhotoImage(im)
            self.preview_label.configure(image=self._preview_photo)
        except Exception as e:
            self.preview_label.configure(text=f"Preview error: {e}")
            self._preview_photo = None

    def _toggle_busy(self, busy: bool):
        if busy:
            self.run_btn.configure(state=tk.DISABLED)
            self.pb.start(10)
        else:
            self.run_btn.configure(state=tk.NORMAL)
            self.pb.stop()

    def _run(self):
        path = self.image_path.get().strip()
        if not path:
            messagebox.showerror("Missing image","Please choose an image file or paste one")
            return
        p = Path(path)
        if not p.exists():
            messagebox.showerror("File not found", f"{path}")
            return

        self._toggle_busy(True)
        self.status.set("Running analysis…")
        self.tree.delete(*self.tree.get_children())
        self._last_result = None

        def worker():
            try:
                cache = Cache()
                raw = analyze_image(
                    str(p),
                    top_k=int(self.top_k.get()),
                    model_name=self.model_name.get(),
                    cache=cache,
                    provider=self.provider.get(),
                )
                final = rank_and_finalize(str(p), self.model_name.get(), raw, top_k=int(self.top_k.get()), do_reverse=bool(self.do_reverse.get()))
                payload = json.loads(final.model_dump_json())
                self.master.after(0, lambda: self._display_result(payload))
            except Exception as e:
                # capture e in default arg so it remains bound when lambda runs
                self.master.after(0, lambda err=e: self._error(err))
        threading.Thread(target=worker, daemon=True).start()

    def _display_result(self, payload):
        self._last_result = payload
        self.status.set("Done")
        self.save_btn.configure(state=tk.NORMAL)
        self.copy_btn.configure(state=tk.NORMAL)
        # Render map for primary guess if we have coordinates
        pg = payload.get("primary_guess", {})
        lat = pg.get("latitude")
        lon = pg.get("longitude")
        self._primary_coords = (lat, lon) if lat is not None and lon is not None else None
        if self._primary_coords:
            self.copy_coords_btn.configure(state=tk.NORMAL)
            # Automatically open interactive map
            self._open_interactive_map()
        else:
            self.copy_coords_btn.configure(state=tk.DISABLED)
        for c in payload.get("top_k", []):
            self.tree.insert("", tk.END, values=(
                c.get("rank"),
                f"{c.get('confidence',0):.2f}",
                c.get("country_name") or "?",
                c.get("admin1") or "?",
                c.get("nearest_city") or "?",
                ("{:.3f}".format(c.get("latitude")) if c.get("latitude") is not None else "?"),
                ("{:.3f}".format(c.get("longitude")) if c.get("longitude") is not None else "?"),
            ))
        # Update clues panel for primary
        clues_txt = self._format_cues_text(pg.get("cues"))
        reasons = pg.get("reasons")
        if reasons:
            clues_txt = clues_txt + ("\n\nReasoning:\n" + reasons)
        self.clues_text.configure(state=tk.NORMAL)
        self.clues_text.delete("1.0", tk.END)
        self.clues_text.insert("1.0", clues_txt)
        self.clues_text.configure(state=tk.DISABLED)
        self._toggle_busy(False)

    def _error(self, e: Exception):
        self._toggle_busy(False)
        self.status.set("Error")
        # Unwrap tenacity RetryError to root cause if present
        root = e
        try:
            from tenacity import RetryError  # type: ignore
            if isinstance(e, RetryError) and e.last_attempt and e.last_attempt.exception():
                root = e.last_attempt.exception()
        except Exception:
            pass
        messagebox.showerror("Error", f"{type(root).__name__}: {root}")

    def _save_json(self):
        if not self._last_result:
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._last_result, f, ensure_ascii=False, indent=2)
            self.status.set(f"Saved to {path}")

    def _copy_json(self):
        if not self._last_result:
            return
        txt = json.dumps(self._last_result, ensure_ascii=False, indent=2)
        self.master.clipboard_clear()
        self.master.clipboard_append(txt)
        self.status.set("JSON copied to clipboard")

    def _maybe_start_global_hotkeys(self):
        # Try to start a global hotkey listener so capture works when minimized
        try:
            from pynput import keyboard as kb  # type: ignore
        except Exception:
            # Dependency not installed; continue without global hotkeys
            return
        try:
            # Use GlobalHotKeys so it works system-wide
            self._hotkey_listener = kb.GlobalHotKeys({
                '<f9>': lambda: self.master.after(0, self._capture_screen),
                '<ctrl>+<shift>+s': lambda: self.master.after(0, self._capture_screen),
            })
            self._hotkey_listener.daemon = True
            self._hotkey_listener.start()
            self.status.set("Global hotkeys active: F9 or Ctrl+Shift+S")
        except Exception as e:
            # If something goes wrong, just disable global hotkeys
            self._hotkey_listener = None

    def _open_interactive_map(self):
        if not self._last_result:
            return
        pg = self._last_result.get("primary_guess", {})
        lat = pg.get("latitude")
        lon = pg.get("longitude")
        if lat is None or lon is None:
            return
        # Build a Folium map with primary + alternatives
        zoom = 6
        m = folium.Map(location=[lat, lon], zoom_start=zoom, tiles="OpenStreetMap", control_scale=True)
        folium.Marker([lat, lon], tooltip="Primary", icon=folium.Icon(color="red", icon="flag")).add_to(m)
        radius_km = pg.get("confidence_radius_km")
        if radius_km:
            folium.Circle([lat, lon], radius=radius_km * 1000, color="#d23", fill=True, fill_opacity=0.15).add_to(m)
        for c in self._last_result.get("top_k", [])[1:]:
            la, lo = c.get("latitude"), c.get("longitude")
            if la is None or lo is None:
                continue
            folium.Marker([la, lo], tooltip=f"#{c.get('rank')} {c.get('country_name') or ''}", icon=folium.Icon(color="blue")).add_to(m)
        tmp = tempfile.NamedTemporaryFile(prefix="geolocate_map_", suffix=".html", delete=False)
        m.save(tmp.name)
        webbrowser.open(f"file://{tmp.name}")

    def _copy_coords(self):
        if not self._primary_coords:
            return
        lat, lon = self._primary_coords
        self.master.clipboard_clear()
        self.master.clipboard_append(f"{lat:.6f},{lon:.6f}")
        self.status.set("Coordinates copied to clipboard")

    def _format_cues_text(self, cues) -> str:
        if not cues:
            return "—"
        parts = []
        ds = cues.get("driving_side")
        if ds:
            parts.append(f"Driving: {ds}")
        langs = cues.get("languages_seen")
        if isinstance(langs, list) and langs:
            try:
                parts.append("Languages: " + ", ".join(str(x) for x in langs))
            except Exception:
                pass
        sf = cues.get("signage_features")
        if sf:
            parts.append(f"Signage: {sf}")
        rm = cues.get("road_markings")
        if rm:
            parts.append(f"Road: {rm}")
        vc = cues.get("vegetation_climate")
        if vc:
            parts.append(f"Env: {vc}")
        ei = cues.get("electrical_infrastructure")
        if ei:
            parts.append(f"Infra: {ei}")
        oc = cues.get("other_cues")
        if oc:
            parts.append(f"Other: {oc}")
        return "\n".join(parts) or "—"


def main():
    load_dotenv()  # load GOOGLE_API_KEY if present
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    app = App(root)
    root.minsize(820, 600)
    root.mainloop()

