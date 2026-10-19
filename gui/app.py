#!/usr/bin/env python3
"""
Modern-TK80-Inference GUI.

Simple Tkinter interface over the interconnector.
Shows die status, loads models, and runs generate for LLM / image / voice / agent.
"""

from __future__ import annotations

import json
import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Optional

from drivers.interconnector import Interconnector, InterconnectorError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("tk80.gui")


class TK80App:
    """future docstring"""
    def __init__(self, root: tk.Tk):
        """future docstring"""
        self.root = root
        self.root.title("Modern-TK80-Inference")
        self.root.geometry("900x720")

        self.ic: Optional[Interconnector] = None
        self._build_ui()
        self._connect()

    def _build_ui(self) -> None:
        """future docstring"""
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)

        ttk.Label(top, text="Modern-TK80-Inference", font=("TkDefaultFont", 14, "bold")).pack(side=tk.LEFT)
        ttk.Button(top, text="Refresh", command=self.refresh_status).pack(side=tk.RIGHT, padx=4)
        ttk.Button(top, text="Advertise", command=self.show_advertise).pack(side=tk.RIGHT, padx=4)

        # Status
        status_frame = ttk.LabelFrame(self.root, text="Dies", padding=8)
        status_frame.pack(fill=tk.BOTH, expand=False, padx=8, pady=4)
        self.status_text = scrolledtext.ScrolledText(status_frame, height=8, wrap=tk.WORD)
        self.status_text.pack(fill=tk.BOTH, expand=True)

        # Load controls
        load_frame = ttk.LabelFrame(self.root, text="Load model", padding=8)
        load_frame.pack(fill=tk.X, padx=8, pady=4)

        row1 = ttk.Frame(load_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Model").pack(side=tk.LEFT)
        self.model_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.model_var, width=50).pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(row1, text="Browse", command=self.browse_model).pack(side=tk.LEFT)

        row2 = ttk.Frame(load_frame)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Modality").pack(side=tk.LEFT)
        self.modality_var = tk.StringVar(value="llm")
        ttk.Combobox(row2, textvariable=self.modality_var, values=["llm", "image", "voice", "agent"], width=10, state="readonly").pack(side=tk.LEFT, padx=4)

        ttk.Label(row2, text="Backend").pack(side=tk.LEFT, padx=(12, 0))
        self.backend_var = tk.StringVar(value="llama")
        ttk.Combobox(row2, textvariable=self.backend_var, values=["llama", "pytorch"], width=10, state="readonly").pack(side=tk.LEFT, padx=4)

        ttk.Label(row2, text="Die").pack(side=tk.LEFT, padx=(12, 0))
        self.die_var = tk.StringVar(value="0")
        ttk.Entry(row2, textvariable=self.die_var, width=4).pack(side=tk.LEFT, padx=4)

        ttk.Label(row2, text="Split").pack(side=tk.LEFT, padx=(12, 0))
        self.split_var = tk.StringVar(value="single")
        ttk.Combobox(row2, textvariable=self.split_var, values=["single", "dual", "layer"], width=10, state="readonly").pack(side=tk.LEFT, padx=4)

        ttk.Button(row2, text="Load", command=self.load_model).pack(side=tk.RIGHT, padx=4)
        ttk.Button(row2, text="Unload", command=self.unload_model).pack(side=tk.RIGHT, padx=4)

        # Request
        req_frame = ttk.LabelFrame(self.root, text="Request", padding=8)
        req_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.prompt_text = scrolledtext.ScrolledText(req_frame, height=6, wrap=tk.WORD)
        self.prompt_text.pack(fill=tk.BOTH, expand=True)
        self.prompt_text.insert("1.0", "Hello from K80")

        opts = ttk.Frame(req_frame)
        opts.pack(fill=tk.X, pady=4)
        ttk.Label(opts, text="Max tokens").pack(side=tk.LEFT)
        self.max_tokens_var = tk.StringVar(value="128")
        ttk.Entry(opts, textvariable=self.max_tokens_var, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Label(opts, text="Temperature").pack(side=tk.LEFT, padx=(12, 0))
        self.temp_var = tk.StringVar(value="0.7")
        ttk.Entry(opts, textvariable=self.temp_var, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Button(opts, text="Generate", command=self.generate).pack(side=tk.RIGHT)

        # Output
        out_frame = ttk.LabelFrame(self.root, text="Output", padding=8)
        out_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.output_text = scrolledtext.ScrolledText(out_frame, height=10, wrap=tk.WORD)
        self.output_text.pack(fill=tk.BOTH, expand=True)

        self.status_bar = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _set_status(self, msg: str) -> None:
        """future docstring"""
        self.status_bar.config(text=msg)
        self.root.update_idletasks()

    def _connect(self) -> None:
        """future docstring"""
        try:
            self.ic = Interconnector()
            self._set_status("Connected to K80 dies")
            self.refresh_status()
        except InterconnectorError as e:
            self.ic = None
            self._set_status(f"Not connected: {e}")
            self.status_text.insert("1.0", f"No CUDA devices found.\n\n{e}\n\nInstall R470 driver + CUDA 11.8 and restart.")

    def browse_model(self) -> None:
        """future docstring"""
        path = filedialog.askopenfilename(
            title="Select model",
            filetypes=[("GGUF", "*.gguf"), ("All files", "*.*")],
        )
        if path:
            self.model_var.set(path)

    def refresh_status(self) -> None:
        """future docstring"""
        if self.ic is None:
            return
        try:
            data = self.ic.status()
            self.status_text.delete("1.0", tk.END)
            self.status_text.insert("1.0", json.dumps(data, indent=2))
            self._set_status("Status refreshed")
        except Exception as e:
            messagebox.showerror("Status", str(e))

    def show_advertise(self) -> None:
        """future docstring"""
        if self.ic is None:
            messagebox.showwarning("Advertise", "Not connected")
            return
        data = self.ic.advertise()
        messagebox.showinfo("Cluster advertisement", json.dumps(data, indent=2))

    def load_model(self) -> None:
        """future docstring"""
        if self.ic is None:
            messagebox.showwarning("Load", "Not connected")
            return
        model = self.model_var.get().strip()
        if not model:
            messagebox.showwarning("Load", "Enter a model path or HF id")
            return
        try:
            die = int(self.die_var.get())
        except ValueError:
            messagebox.showwarning("Load", "Die must be an integer")
            return

        self._set_status("Loading...")

        def work() -> None:
            """future docstring"""
            try:
                assert self.ic is not None
                self.ic.load(
                    model,
                    backend=self.backend_var.get(),
                    modality=self.modality_var.get(),
                    die=die,
                    split=self.split_var.get(),
                )
                self.root.after(0, self.refresh_status)
                self.root.after(0, lambda: self._set_status("Model loaded"))
            except Exception as exc:
                err = str(exc)

                def _show_load(msg: str = err) -> None:
                    """future docstring"""
                    messagebox.showerror("Load failed", msg)

                self.root.after(0, _show_load)
                self.root.after(0, lambda: self._set_status("Load failed"))

        threading.Thread(target=work, daemon=True).start()

    def unload_model(self) -> None:
        """future docstring"""
        if self.ic is None:
            return
        try:
            die = int(self.die_var.get())
            self.ic.unload(die)
            self.refresh_status()
            self._set_status(f"Unloaded die {die}")
        except Exception as e:
            messagebox.showerror("Unload", str(e))

    def generate(self) -> None:
        """future docstring"""
        if self.ic is None:
            messagebox.showwarning("Generate", "Not connected")
            return
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showwarning("Generate", "Enter a prompt")
            return
        try:
            die = int(self.die_var.get())
            max_tokens = int(self.max_tokens_var.get())
            temperature = float(self.temp_var.get())
        except ValueError:
            messagebox.showwarning("Generate", "Check die / max tokens / temperature")
            return

        modality = self.modality_var.get()
        if modality == "voice":
            request: Any = {"audio": prompt}
        elif modality == "agent":
            request = {"goal": prompt}
        else:
            request = {"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature}

        self._set_status("Generating...")
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", "Working...\n")

        def work() -> None:
            """future docstring"""
            try:
                assert self.ic is not None
                result = self.ic.generate(request, die=die)
                text = result if isinstance(result, str) else json.dumps(result, indent=2, default=str)
                self.root.after(0, lambda: self._show_result(text))
                self.root.after(0, lambda: self._set_status("Done"))
                self.root.after(0, self.refresh_status)
            except Exception as exc:
                err = str(exc)

                def _show_gen(msg: str = err) -> None:
                    """future docstring"""
                    messagebox.showerror("Generate failed", msg)

                self.root.after(0, _show_gen)
                self.root.after(0, lambda: self._set_status("Generate failed"))

        threading.Thread(target=work, daemon=True).start()

    def _show_result(self, text: str) -> None:
        """future docstring"""
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", text)


def main() -> None:
    """future docstring"""
    root = tk.Tk()
    TK80App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
