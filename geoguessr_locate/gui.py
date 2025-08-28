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

from .model_client import analyze_image, DEFAULT_MODEL
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
        self.do_reverse = tk.BooleanVar(value=True)

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
        ttk.Entry(self, textvariable=self.model_name, width=30).grid(row=row, column=1, sticky=tk.W)

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
        self.status = tk.StringVar(value="Ready")
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
                raw = analyze_image(str(p), top_k=int(self.top_k.get()), model_name=self.model_name.get(), cache=cache)
                final = rank_and_finalize(str(p), self.model_name.get(), raw, top_k=int(self.top_k.get()), do_reverse=bool(self.do_reverse.get()))
                payload = json.loads(final.model_dump_json())
                self.master.after(0, lambda: self._display_result(payload))
            except Exception as e:
                self.master.after(0, lambda: self._error(e))
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
        self._toggle_busy(False)

    def _error(self, e: Exception):
        self._toggle_busy(False)
        self.status.set("Error")
        messagebox.showerror("Error", str(e))

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

