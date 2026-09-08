import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from typing import Optional, Callable, List, Dict, Any
from pathlib import Path
import threading
import queue
import time


class GameComboBox(ttk.Combobox):
    """ComboBox con búsqueda para seleccionar juegos."""

    def __init__(self, parent, games: List[Dict], on_select: Callable = None, **kwargs):
        self.games = games
        self.on_select = on_select
        self.game_map = {f"{g['name']} ({g['launcher'].capitalize()})": g for g in games}
        self.display_names = list(self.game_map.keys())

        super().__init__(parent, values=self.display_names, state="readonly", **kwargs)
        self.bind('<<ComboboxSelected>>', self._on_select)
        self.bind('<KeyRelease>', self._on_keyrelease)

    def _on_select(self, event=None):
        if self.on_select:
            name = self.get()
            game = self.game_map.get(name)
            if game:
                self.on_select(game)

    def _on_keyrelease(self, event=None):
        """Filtrar lista mientras se escribe."""
        typed = self.get().lower()
        if not typed:
            self['values'] = self.display_names
        else:
            filtered = [n for n in self.display_names if typed in n.lower()]
            self['values'] = filtered

    def update_games(self, games: List[Dict]):
        self.games = games
        self.game_map = {f"{g['name']} ({g['launcher'].capitalize()})": g for g in games}
        self.display_names = list(self.game_map.keys())
        self['values'] = self.display_names

    def get_selected_game(self) -> Optional[Dict]:
        name = self.get()
        return self.game_map.get(name)

    def set_game(self, game_id: str):
        for name, game in self.game_map.items():
            if game['id'] == game_id:
                self.set(name)
                return True
        return False


class TrainerFilePicker(ttk.Frame):
    """Widget para seleccionar archivo .exe del trainer."""

    def __init__(self, parent, on_change: Callable = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_change = on_change
        self.trainer_path = tk.StringVar()

        self.entry = ttk.Entry(self, textvariable=self.trainer_path, width=50)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        self.btn = tb.Button(self, text="📁 Examinar", command=self._browse, bootstyle="secondary")
        self.btn.pack(side=tk.LEFT)

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Seleccionar Trainer (.exe)",
            filetypes=[("Ejecutables", "*.exe"), ("Todos", "*.*")]
        )
        if path:
            self.trainer_path.set(path)
            if self.on_change:
                self.on_change(path)

    def get_path(self) -> str:
        return self.trainer_path.get()

    def set_path(self, path: str):
        self.trainer_path.set(path)


class LogView(ttk.Frame):
    """Visor de log con colores, auto-scroll y opciones de copiar/guardar."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.log_queue = queue.Queue()

        # Toolbar con botones
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, pady=(0, 5))

        tb.Button(toolbar, text="📋 Copiar log", command=self._copy_log, bootstyle="secondary-outline", width=15).pack(side=tk.LEFT, padx=2)
        tb.Button(toolbar, text="💾 Guardar log", command=self._save_log, bootstyle="secondary-outline", width=15).pack(side=tk.LEFT, padx=2)
        tb.Button(toolbar, text="🗑️ Limpiar", command=self.clear, bootstyle="secondary-outline", width=12).pack(side=tk.LEFT, padx=2)

        # Text widget con scroll
        text_frame = ttk.Frame(self)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.text = tk.Text(
            text_frame,
            wrap=tk.WORD,
            font=("Monospace", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
            relief=tk.FLAT,
            padx=5,
            pady=5
        )
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.configure(yscrollcommand=scrollbar.set)

        # Tags para colores
        self.text.tag_configure("info", foreground="#4ec9b0")
        self.text.tag_configure("success", foreground="#4ec9b0")
        self.text.tag_configure("warning", foreground="#dcdcaa")
        self.text.tag_configure("error", foreground="#f44747")
        self.text.tag_configure("debug", foreground="#9cdcfe")
        self.text.tag_configure("timestamp", foreground="#6a9955")

        self.text.configure(state=tk.DISABLED)

        # Procesar cola periódicamente
        self._process_queue()

    def _copy_log(self):
        """Copia el log completo al portapapeles."""
        self.text.configure(state=tk.NORMAL)
        content = self.text.get(1.0, tk.END)
        self.text.configure(state=tk.DISABLED)
        self.clipboard_clear()
        self.clipboard_append(content)
        # Feedback visual temporal
        # Opcional: mostrar toast o cambiar botón temporalmente

    def _save_log(self):
        """Guarda el log en un archivo."""
        from tkinter import filedialog
        from datetime import datetime
        self.text.configure(state=tk.NORMAL)
        content = self.text.get(1.0, tk.END)
        self.text.configure(state=tk.DISABLED)
        
        default_name = f"fling-trainer-log-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        path = filedialog.asksaveasfilename(
            title="Guardar log",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")]
        )
        if path:
            try:
                Path(path).write_text(content, encoding='utf-8')
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo guardar: {e}")

    def log(self, message: str, level: str = "info"):
        """Añade mensaje al log (thread-safe)."""
        self.log_queue.put((message, level))

    def _process_queue(self):
        """Procesa mensajes de la cola."""
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                self._append_message(message, level)
        except queue.Empty:
            pass
        self.after(100, self._process_queue)

    def _append_message(self, message: str, level: str):
        self.text.configure(state=tk.NORMAL)
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.text.insert(tk.END, f"[{timestamp}] ", "timestamp")
        self.text.insert(tk.END, f"{message}\n", level)
        self.text.see(tk.END)
        self.text.configure(state=tk.DISABLED)

    def clear(self):
        self.text.configure(state=tk.NORMAL)
        self.text.delete(1.0, tk.END)
        self.text.configure(state=tk.DISABLED)


class ProgressDialog:
    """Diálogo modal con barra de progreso y log."""

    def __init__(self, parent: tk.Tk, title: str = "Progreso"):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.geometry("500x400")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Centrar
        self.dialog.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 250
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 200
        self.dialog.geometry(f"500x400+{x}+{y}")

        # Progress bar
        self.progress = tb.Progressbar(self.dialog, mode='indeterminate', bootstyle="info-striped")
        self.progress.pack(fill=tk.X, padx=20, pady=15)
        self.progress.start(10)

        # Status label
        self.status_var = tk.StringVar(value="Iniciando...")
        ttk.Label(self.dialog, textvariable=self.status_var, wraplength=460).pack(padx=20, pady=5)

        # Log view
        self.log_view = LogView(self.dialog)
        self.log_view.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 15))

        # Botón cerrar (deshabilitado hasta completar)
        self.close_btn = tb.Button(
            self.dialog, text="Cerrar", command=self._close,
            bootstyle="success", state=tk.DISABLED
        )
        self.close_btn.pack(pady=(0, 15))

        self.completed = False
        self.success = False

    def update_status(self, message: str):
        self.status_var.set(message)

    def log(self, message: str, level: str = "info"):
        self.log_view.log(message, level)

    def finish(self, success: bool, message: str = ""):
        self.completed = True
        self.success = success
        self.progress.stop()
        self.progress.configure(mode='determinate', value=100)
        self.close_btn.configure(state=tk.NORMAL)
        if message:
            self.log(message, "success" if success else "error")

    def _close(self):
        self.dialog.destroy()

    def wait(self):
        """Espera a que se cierre el diálogo procesando eventos."""
        while not self.completed:
            self.dialog.update()
            time.sleep(0.05)
        self.dialog.wait_window()
        return self.success


class SudoPasswordDialog:
    """Diálogo para pedir contraseña de sudo."""

    def __init__(self, parent: tk.Tk, message: str = "Se requiere autenticación"):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Autenticación requerida")
        self.dialog.geometry("400x150")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Centrar
        self.dialog.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 200
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - 75
        self.dialog.geometry(f"400x150+{x}+{y}")

        ttk.Label(self.dialog, text=message, wraplength=380, justify=tk.LEFT).pack(pady=15, padx=20)

        self.entry = ttk.Entry(self.dialog, show="*", font=("Sans", 11))
        self.entry.pack(pady=5, padx=20, fill=tk.X)
        self.entry.focus_set()

        btn_frame = ttk.Frame(self.dialog)
        btn_frame.pack(pady=15)
        tb.Button(btn_frame, text="Aceptar", command=self._ok, bootstyle="success", width=12).pack(side=tk.LEFT, padx=5)
        tb.Button(btn_frame, text="Cancelar", command=self._cancel, bootstyle="secondary", width=12).pack(side=tk.LEFT, padx=5)

        self.dialog.bind('<Return>', lambda e: self._ok())
        self.dialog.bind('<Escape>', lambda e: self._cancel())

    def _ok(self):
        self.result = self.entry.get()
        self.dialog.destroy()

    def _cancel(self):
        self.result = None
        self.dialog.destroy()

    def show(self) -> Optional[str]:
        self.dialog.wait_window()
        return self.result