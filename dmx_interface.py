#------- INTERFAZ DMX A USB BASADA EN EL MICROCONTROLADOR ESP32 ---------
#------- ESPINO MARCA MARY ISABEL ---------------------------------------

import tkinter as tk
from tkinter import ttk, colorchooser, messagebox
import serial
import serial.tools.list_ports
import threading
import math
try:
    from PIL import Image, ImageTk
    PIL_DISPONIBLE = True
except ImportError:
    PIL_DISPONIBLE = False

FONDO               = "#f0f0f0"
FONDO_BLANCO        = "#ffffff"
BOTON_GRIS          = "#d0d0d0"
BOTON_AZUL          = "#5588bb"
BOTON_AZUL_ACTIVO   = "#2255aa"
DORADO              = "#e8a020"
BOTON_NEGRO         = "#111111"
VERDE_ESCENA        = "#44aa55"
ROJO_BORRAR         = "#cc5500"
TEXTO               = "#000000"
TEXTO_BLANCO        = "#ffffff"
FADER_SURCO         = "#b0b0b0"
FADER_FONDO         = "#e0e0e0"

ALTURA_FADER = 380   # altura fader canal
ALTURA_MAESTRO = 440   # altura fader maestro

# 9 faders modo 7 canales
REGULADORES_7 = [
    ("RED",  1,  "R",   ""),   # Canal 1 = Rojo
    ("GRN",  2,  "G",   ""),   # Canal 2 = Verde
    ("BLU",  3,  "B",   ""),   # Canal 3 = Azul
    ("STR",  4,  "Str", ""),   # Canal 4 = Estrobo
    ("PRG",  5,  "Prg", ""),   # Canal 5 = Programa automático
    ("VEL",  6,  "Vel", ""),   # Canal 6 = Velocidad programa auto
    ("",    -1,  "g1",  ""),   # Secuencia G1
    ("",    -2,  "g2",  ""),   # Secuencia G2
    ("",     0,  "T",   ""),   # Fader velocidad de secuencia
]

# 9 faders modo 23 canales
REGULADORES_23 = [
    ("C2", 2,  "C2", ""),   # Canal 2 = Programa automático
    ("C3", 3,  "C3", ""),   # Canal 3 = Velocidad programa auto
    ("C4", 4,  "C4", ""),   # Canal 4 = Estrobo
    ("",   -1, "g1", ""),   # Secuencia G1
    ("",   -2, "g2", ""),   # Secuencia G2  
    ("",   -3, "g3", ""),   # Secuencia G3
    ("",   -4, "g4", ""),   # Secuencia G4
    ("",   -5, "g5", ""),   # Secuencia G5
    ("",   0,  "T",  ""),   # Fader velocidad de secuencia
]

class DMXApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Control DMX - ESP32")
        self.configure(bg=FONDO)
        self.geometry("1280x700")
        self.resizable(True, True)

        self.puerto_serial          = None
        self.conectado              = False
        self.apagon_activo          = False
        self.modo                   = tk.StringVar(value="7 canales")
        self.valores_dmx            = [0] * 513
        self.vars_fader             = {}
        self.botones_escena         = {}
        self.escena_guardada        = {}
        self.fixture_escena         = {}   # escena_num -> fixture (1, 2, o 0=AMBOS)
        self.botones_secuencia      = {}
        self.var_maestro            = tk.IntVar(value=255)
        self.desplazamiento_fixture = 0
        self._foto_fixture          = None
        self._fixture_activo_num    = 1   # fixture activo actual (para dimmer)
        self._cursor_rueda          = None  # cursor visual en la rueda de color
        self._buffer_estado         = []      # guarda temporalmente las líneas de estado que envía el ESP32
        self._leyendo_estado        = False   # True mientras se está recibiendo el estado

        self._apply_style()
        self._build_ui()
        self._refresh_ports()
        self._rebuild_channels()

    # ────────────────────────────────────────────
    def _apply_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TCombobox", fieldbackground=FONDO_BLANCO,
                    background=BOTON_GRIS, foreground=TEXTO,
                    font=("Segoe UI", 12))
        s.map("TCombobox", fieldbackground=[("readonly", FONDO_BLANCO)])

    # ────────────────────────────────────────────
    #  Interfaz grafica principal
    # ────────────────────────────────────────────
    def _build_ui(self):
        # Barra superior
        top = tk.Frame(self, bg=FONDO, pady=6, padx=8)
        top.pack(fill="x")

        tk.Label(top, text="Puerto:", bg=FONDO, fg=TEXTO,
                 font=("Segoe UI", 12)).pack(side="left")
        self.var_puerto = tk.StringVar()
        self.combo_puerto  = ttk.Combobox(top, textvariable=self.var_puerto,
                                     width=15, state="readonly",
                                     font=("Segoe UI", 12))
        self.combo_puerto.pack(side="left", padx=(4, 8))
        self._btn(top, "Actualizar", self._refresh_ports,
                  bg=DORADO, fg=TEXTO,
                  font=("Segoe UI", 12, "bold")).pack(side="left", padx=2)
        self.boton_conectar = self._btn(top, "Conectar", self._toggle_connect,
                                  bg=BOTON_GRIS, fg=TEXTO,
                                  font=("Segoe UI", 12, "bold"))
        self.boton_conectar.pack(side="left", padx=2)

        self.combo_modo = ttk.Combobox(top, textvariable=self.modo,
                                    values=["7 canales", "23 canales"],
                                    width=13, state="readonly",
                                    font=("Segoe UI", 12))
        self.combo_modo.pack(side="right", padx=8)
        self.combo_modo.bind("<<ComboboxSelected>>",
                          lambda e: self._on_modo_change())

        # Cuerpo
        body = tk.Frame(self, bg=FONDO)
        body.pack(fill="both", expand=True, padx=6, pady=4)

        # ── Canales (se reconstruye al cambiar modo) ──
        self.panel_izquierdo = tk.Frame(body, bg=FONDO)
        self.panel_izquierdo.pack(side="left", fill="y", anchor="n")

        # ── Consola (centro) ──
        cen = tk.Frame(body, bg=FONDO)
        cen.pack(side="left", fill="both", expand=True, padx=8)

        # Consola (más grande)
        tk.Label(cen, text="Consola:", bg=FONDO, fg=TEXTO,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x")
        self.consola = tk.Text(cen, bg=FONDO_BLANCO, fg=TEXTO,
                               font=("Courier New", 8),
                               state="disabled", relief="solid", bd=1,
                               height=28)
        self.consola.pack(fill="x")

        # Mitad inferior: imagen + botones WASH FX centrados
        bot_cen = tk.Frame(cen, bg=FONDO)
        bot_cen.pack(fill="both", expand=True, pady=(6, 0))

        # Frame interior centrado horizontalmente
        inner = tk.Frame(bot_cen, bg=FONDO)
        inner.place(relx=0.5, rely=0.5, anchor="center")

        # Imagen fixture (cambia según modo)
        self.etiqueta_imagen = tk.Label(inner, bg=FONDO, cursor="hand2")
        self.etiqueta_imagen.pack(side="left", padx=(0, 30))

        # Botones WASH FX 1 y WASH FX 2 — centrados verticalmente con la imagen
        btns_frame = tk.Frame(inner, bg=FONDO)
        btns_frame.pack(side="left", fill="y")

        tk.Frame(btns_frame, bg=FONDO).pack(expand=True, fill="y")

        # Botones WASH FX con estado activo/inactivo
        self._fx_activo = {1: False, 2: False}
        self._botones_fx   = {}

        for fx_num in [1, 2]:
            b = tk.Button(btns_frame,
                          text=f"WASH FX {fx_num}\n[ inactivo ]",
                          bg="#555555", fg="#aaaaaa",
                          font=("Segoe UI", 10, "bold"),
                          width=14, relief="flat",
                          activebackground="#2277cc",
                          command=lambda n=fx_num: self._toggle_fixture(n))
            b.pack(pady=6, ipady=10)
            self._botones_fx[fx_num] = b

        tk.Frame(btns_frame, bg=FONDO).pack(expand=True, fill="y")

        # Cargar imagen inicial / panel de zonas
        self._load_fixture_image()
        self._zona_activa = None   # zona seleccionada actualmente

        # ── Regulador maestro (extremo derecho, altura completa) ──
        master_col = tk.Frame(body, bg=FONDO)
        master_col.pack(side="right", fill="y", padx=(2, 4))

        tk.Scale(master_col, from_=255, to=0, orient="vertical",
                 variable=self.var_maestro, bg=FONDO,
                 troughcolor=FADER_SURCO, highlightthickness=0,
                 length=580, width=30, showvalue=True,
                 command=self._on_master).pack(expand=True, fill="y")
        tk.Label(master_col, text="Regulador\nmaestro", bg=FONDO, fg=TEXTO,
                 font=("Segoe UI", 7), justify="center").pack()
        tk.Label(master_col, text="M. I. E. M.", bg=FONDO, fg=TEXTO,
                 font=("Segoe UI", 7, "bold"), justify="center").pack(pady=(4, 0))

        # ── Panel derecho ──
        right = tk.Frame(body, bg=FONDO, width=230)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        self._build_right(right)

    # ────────────────────────────────────────────
    #  Panel derecho
    # ────────────────────────────────────────────
    def _build_right(self, p):
        # Rueda de color 
        tk.Label(p, text="Elegir color  →  click en la rueda",
                 bg=FONDO, fg="#555555",
                 font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(0,2))
        wheel_frame = tk.Frame(p, bg=FONDO)
        wheel_frame.pack(fill="x")
        self.rueda_color = tk.Canvas(wheel_frame, width=210, height=210,
                                bg=FONDO, highlightthickness=0, cursor="crosshair")
        self.rueda_color.pack(anchor="center")
        self._centro_x_rueda = 105
        self._centro_y_rueda = 105
        self._radio_rueda  = 98
        self._draw_wheel(self.rueda_color, self._centro_x_rueda, self._centro_y_rueda, self._radio_rueda)
        self.rueda_color.bind("<Button-1>",        self._on_wheel_click)
        self.rueda_color.bind("<B1-Motion>",       self._on_wheel_click)
        # Indicador de color seleccionado
        self._indicador_color = tk.Label(wheel_frame,
                                         text="  Sin color  ",
                                         bg=FONDO, fg=TEXTO,
                                         font=("Segoe UI", 8),
                                         relief="flat", width=18)
        self._indicador_color.pack(pady=(2,0))

        row = tk.Frame(p, bg=FONDO)
        row.pack(fill="x", pady=6)
        self._btn(row, "Full ON", self._full_on,
                  bg=DORADO, fg=TEXTO,
                  font=("Segoe UI", 9, "bold")).pack(side="left", padx=2, expand=True, fill="x", ipady=4)
        self.boton_borrar = self._btn(row, "BORRAR", self._toggle_blackout,
                                bg=BOTON_NEGRO, fg=TEXTO_BLANCO,
                                font=("Segoe UI", 9, "bold"))
        self.boton_borrar.pack(side="left", padx=2, expand=True, fill="x", ipady=4)

        tk.Label(p, text="Escenas:", bg=FONDO, fg=TEXTO,
                 font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
        sc_f = tk.Frame(p, bg=FONDO)
        sc_f.pack(fill="x")
        self.botones_escena = {}
        for i in range(1, 25):
            key = f"S{i}"
            self.escena_guardada[key] = False
            r, c = divmod(i - 1, 6)
            b = tk.Button(sc_f, text=key, width=4, height=2,
                          bg=VERDE_ESCENA, fg=TEXTO_BLANCO,
                          font=("Segoe UI", 9, "bold"), relief="flat",
                          command=lambda k=key, n=i: self._scene_action(k, n))
            b.grid(row=r, column=c, padx=1, pady=2, sticky="ew")
            self.botones_escena[key] = b
        for c in range(6):
            sc_f.columnconfigure(c, weight=1)

        gf = tk.Frame(p, bg=FONDO)
        gf.pack(fill="x", pady=(10, 2))
        self.entrada_g = tk.Entry(gf, font=("Segoe UI", 10),
                                relief="solid", bd=1)
        self.entrada_g.insert(0, "G1: S1, S2, S3")
        self.entrada_g.pack(side="left", padx=(0, 4), ipady=6, expand=True, fill="x")
        self._btn(gf, "Guardar G", self._guardar_g,
                  bg=VERDE_ESCENA, fg=TEXTO_BLANCO,
                  font=("Segoe UI", 10, "bold")).pack(side="right", ipady=6)

        bf = tk.Frame(p, bg=FONDO)
        bf.pack(fill="x", pady=4)
        self._btn(bf, "Borrar todo", self._borrar_todo,
                  bg=ROJO_BORRAR, fg=TEXTO_BLANCO,
                  font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0,2), ipady=6, expand=True, fill="x")
        self._btn(bf, "Detener secuencia", self._detener,
                  bg=BOTON_NEGRO, fg=TEXTO_BLANCO,
                  font=("Segoe UI", 10, "bold")).pack(side="left", padx=2, ipady=6, expand=True, fill="x")

    # ────────────────────────────────────────────
    #  Área de canales
    # ────────────────────────────────────────────
    def _on_modo_change(self):
        self._rebuild_channels()
        self._load_fixture_image()
        # Notificar modo al ESP32
        cmd = "MODE7" if self.modo.get() == "7 canales" else "MODE23"
        self._send(cmd)

    def _load_fixture_image(self):

        # Limpiar contenido anterior del img_label
        for w in self.etiqueta_imagen.winfo_children():
            w.destroy()
        self.etiqueta_imagen.config(image="", text="")

        if self.modo.get() == "23 canales":
            self._build_zona_panel(self.etiqueta_imagen)
        else:
            # Modo 7 canales: imagen normal
            if not PIL_DISPONIBLE:
                self.etiqueta_imagen.config(
                    text="Instala Pillow:\npip install Pillow",
                    font=("Segoe UI", 9), fg="#888888")
                return
            try:
                import os
                base  = os.path.dirname(os.path.abspath(__file__))
                path  = os.path.join(base, "WASH_FX.png")
                img   = Image.open(path).resize((320, 200), Image.LANCZOS)
                self._foto_fixture = ImageTk.PhotoImage(img)
                self.etiqueta_imagen.config(image=self._foto_fixture)
            except Exception:
                self.etiqueta_imagen.config(text="[WASH_FX.png no encontrada]",
                                      font=("Segoe UI", 9), fg="#888888")

    # Mapeo zona → canales RGB
    ZONA_CANALES = {
        1: (6,  7,  8),
        2: (9,  10, 11),
        3: (12, 13, 14),
        4: (15, 16, 17),
        5: (18, 19, 20),
        6: (21, 22, 23),
    }
    # Color representativo de cada zona
    ZONA_COLOR = {
        1: "#cccccc",   # blanco
        2: "#ddaa00",   # amarillo
        3: "#cc3300",   # rojo
        4: "#cc44cc",   # magenta
        5: "#4488ff",   # azul
        6: "#44bb44",   # verde
    }

    def _build_zona_panel(self, parent):
        parent.config(bg=FONDO)

        # Fila de control superior
        ctrl = tk.Frame(parent, bg=FONDO)
        ctrl.pack(fill="x", padx=4, pady=(4, 2))

        tk.Label(ctrl, text="Zonas:", bg=FONDO, fg="#333",
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0,4))

        self._btn(ctrl, "Todas", self._zonas_todas,
                  bg="#2277cc", fg=TEXTO_BLANCO,
                  font=("Segoe UI", 8, "bold")).pack(side="left", padx=2)
        self._btn(ctrl, "Ninguna", self._zonas_ninguna,
                  bg=BOTON_GRIS, fg=TEXTO,
                  font=("Segoe UI", 8, "bold")).pack(side="left", padx=2)

        # Grid de zonas
        grid = tk.Frame(parent, bg="#111111", padx=6, pady=6)
        grid.pack()

        self._botones_zona    = {}
        self._zonas_activas = set()   # zonas seleccionadas (puede ser >1)

        layout = [
            [4, 5, 6],
            [3, 2, 1],
        ]

        for row, zonas in enumerate(layout):
            for col, z in enumerate(zonas):
                btn = tk.Button(
                    grid,
                    text=str(z),
                    width=6, height=3,
                    bg=self.ZONA_COLOR[z],
                    fg="#ffffff",
                    font=("Segoe UI", 14, "bold"),
                    relief="raised", bd=3,
                    activebackground=self.ZONA_COLOR[z],
                    command=lambda n=z: self._toggle_zona(n)
                )
                btn.grid(row=row, column=col, padx=4, pady=4)
                self._botones_zona[z] = btn

        # Indicador
        self._etiqueta_zona = tk.Label(parent,
                                    text="Ninguna zona seleccionada — click para seleccionar",
                                    bg=FONDO, fg="#555",
                                    font=("Segoe UI", 8))
        self._etiqueta_zona.pack(pady=(4, 2))

    def _toggle_zona(self, zona):
        """Activa/desactiva una zona. Permite múltiples zonas activas."""
        if not hasattr(self, "_zonas_activas"):
            self._zonas_activas = set()

        btn = self._botones_zona[zona]
        if zona in self._zonas_activas:
            # Deseleccionar
            self._zonas_activas.discard(zona)
            btn.config(relief="raised", bd=3, highlightthickness=0)
        else:
            # Seleccionar
            self._zonas_activas.add(zona)
            btn.config(relief="sunken", bd=4,
                       highlightbackground="#ffffff",
                       highlightthickness=3)

        # Actualizar zona_activa (compatibilidad con código anterior)
        self._zona_activa = next(iter(self._zonas_activas), None)

        # Actualizar indicador
        self._update_zona_label()

    def _update_zona_label(self):
        if not hasattr(self, "_zonas_activas") or not self._zonas_activas:
            self._etiqueta_zona.config(
                text="Ninguna zona seleccionada — click para seleccionar",
                fg="#555")
        elif len(self._zonas_activas) == 1:
            z = next(iter(self._zonas_activas))
            chs = self.ZONA_CANALES[z]
            self._etiqueta_zona.config(
                text=f"Zona {z}  →  ch R={chs[0]} G={chs[1]} B={chs[2]}",
                fg="#222")
        else:
            zonas_ord = sorted(self._zonas_activas)
            self._etiqueta_zona.config(
                text=f"{len(zonas_ord)} zonas seleccionadas: {zonas_ord}  →  elige color",
                fg="#2277cc")

    def _zonas_todas(self):
        #Selecciona las 6 zonas
        if not hasattr(self, "_zonas_activas"):
            self._zonas_activas = set()
        self._zonas_activas = set(range(1, 7))
        for z, btn in self._botones_zona.items():
            btn.config(relief="sunken", bd=4,
                       highlightbackground="#ffffff",
                       highlightthickness=3)
        self._zona_activa = 1
        self._update_zona_label()
        self._log("Todas las zonas seleccionadas")

    def _zonas_ninguna(self):
        #Deselecciona todas las zonas
        if not hasattr(self, "_zonas_activas"):
            self._zonas_activas = set()
        self._zonas_activas = set()
        self._zona_activa   = None
        for btn in self._botones_zona.values():
            btn.config(relief="raised", bd=3, highlightthickness=0)
        self._update_zona_label()

    def _seleccionar_zona(self, zona):
        #Compatibilidad: selecciona una sola zona
        self._zonas_ninguna()
        self._toggle_zona(zona)

    def _toggle_fixture(self, num):
        """
        Cada botón es un interruptor independiente:
          - solo WASH FX 1 activo  → controla F1
          - solo WASH FX 2 activo  → controla F2
          - ambos activos          → controla AMBOS (envía F0)
          - ninguno                → no controla nada
        """
        btns = getattr(self, "_fx_btns", {})
        active = getattr(self, "_fx_active", {1: False, 2: False})

        active[num] = not active.get(num, False)
        if num in btns:
            if active[num]:
                btns[num].config(bg="#2277cc", fg="#ffffff",
                                 text=f"WASH FX {num}\n[ ✓ ACTIVO ]")
                self._log(f"✅ WASH FX {num} activado")
            else:
                btns[num].config(bg="#555555", fg="#aaaaaa",
                                 text=f"WASH FX {num}\n[ inactivo ]")
                self._log(f"⭕ WASH FX {num} desactivado")

        self._fx_activo = active
        self._sync_fixture_selection()

    def _current_fixture(self):
        """Devuelve el fixture controlado ahora: 1, 2, o 0 (AMBOS)."""
        return getattr(self, "_fixture_activo_num", 1)

    def _sync_fixture_selection(self):
        """Envía F0/F1/F2 al ESP32 según qué botones WASH FX estén activos."""
        a = getattr(self, "_fx_active", {1: False, 2: False})
        a1, a2 = a.get(1, False), a.get(2, False)
        if a1 and a2:
            self.desplazamiento_fixture      = 0
            self._fixture_activo_num = 0          # 0 = AMBOS
            self._send("F0")
            self._log("Controlando AMBOS (WASH FX 1 + 2)")
        elif a1:
            self._select_fixture(1)
        elif a2:
            self._select_fixture(2)
        else:
            # Ninguno activo: dejamos F1 como destino por defecto sin reenviar
            self._fixture_activo_num = 1
            self._log("⭕ Ningún WASH FX activo (destino por defecto: F1)")

    def _select_fixture(self, num):
        #Selecciona qué fixture controlar — envía F{num} al ESP32
        self.desplazamiento_fixture      = num - 1
        self._fixture_activo_num = num
        self._send(f"F{num}")
        self._log(f"🎯 Controlando WASH FX {num}")

    # ────────────────────────────────────────────
    def _rebuild_channels(self):
        for w in self.panel_izquierdo.winfo_children():
            w.destroy()
        self.vars_fader.clear()
        if self.modo.get() == "7 canales":
            self._build_channel_buttons(7)
            self._build_faders(REGULADORES_7, show_names=False)
        else:
            self._build_channel_buttons(23)
            self._build_faders(REGULADORES_23, show_names=True)

    def _build_channel_buttons(self, n):
        #Botones C1..Cn arriba. Click → canal a 255, doble click → 0
        if n <= 12:
            row = tk.Frame(self.panel_izquierdo, bg=FONDO)
            row.pack(anchor="w", padx=4, pady=(4, 2))
            for i in range(1, n + 1):
                canal = i
                b = tk.Button(row, text=f"C{i}", bg=BOTON_GRIS, fg=TEXTO,
                              font=("Segoe UI", 9, "bold"), width=4,
                              height=1, relief="raised", bd=1,
                              command=lambda c=canal: self._canal_full(c))
                b.bind("<Double-Button-1>",
                       lambda e, c=canal: self._canal_zero(c))
                b.pack(side="left", padx=2, pady=1)
        else:
            for start, end in [(1, 12), (13, n)]:
                row = tk.Frame(self.panel_izquierdo, bg=FONDO)
                row.pack(anchor="w", padx=4, pady=(1, 0))
                for i in range(start, end + 1):
                    canal = i
                    b = tk.Button(row, text=f"C{i}", bg=BOTON_GRIS, fg=TEXTO,
                                  font=("Segoe UI", 9, "bold"), width=4,
                                  height=1, relief="raised", bd=1,
                                  command=lambda c=canal: self._canal_full(c))
                    b.bind("<Double-Button-1>",
                           lambda e, c=canal: self._canal_zero(c))
                    b.pack(side="left", padx=2, pady=1)

    def _canal_full(self, canal):
        if canal in self.vars_fader:
            self.vars_fader[canal].set(255)
        self._send(f"{canal},255")

    def _canal_zero(self, canal):
        if canal in self.vars_fader:
            self.vars_fader[canal].set(0)
        self._send(f"{canal},0")

    def _build_faders(self, faders, show_names):
        
        container = tk.Frame(self.panel_izquierdo, bg=FONDO)
        container.pack(anchor="w", padx=4, pady=(2, 2))

        n_cols = max(len(faders), 9)
        for c in range(n_cols):
            container.columnconfigure(c, minsize=52, uniform="col")

        is_7ch = not show_names   # modo 7 canales = sin nombres

        for i, (lbl_top, canal, lbl_bot, nombre) in enumerate(faders):
            # En modo 7ch, g1→slot G1 fixture F1, g2→slot G1 fixture F2
            # g_slot: en modo 7ch = g1,g2; en modo 23ch = g1..g5 (canal negativo)
            is_g_slot = (lbl_bot in ("g1","g2") and is_7ch) or (canal < 0)
            is_t_slot = lbl_bot == "T"
            # Extraer número del slot g (g1→1, g2→2, g3→3, ...)
            g_num = int(lbl_bot[1:]) if lbl_bot.startswith("g") else 1
            # fixture asociado: en modo 7ch g1=F1,g2=F2; en modo 23ch gN=FN
            f_num = g_num

            # El fader T usa escala 100-10000 ms; los demás 0-255
            if is_t_slot:
                var = tk.IntVar(value=3000)
            elif is_g_slot:
                var = tk.IntVar(value=0)     # slot de secuencia, arranca en 0
            else:
                var = tk.IntVar(value=0)
            if canal > 0:
                self.vars_fader[canal] = var
            # Para g-slots (canal negativo) registramos con clave "gN_dim"
            if is_g_slot:
                self.vars_fader[f"g{g_num}_dim"] = var

            # ── Fila 0: nombre o espacio ──────────────────────────
            if show_names:
                tk.Label(container, text=nombre, bg=FONDO, fg="#555555",
                         font=("Segoe UI", 6), wraplength=46,
                         justify="center"
                         ).grid(row=0, column=i, padx=1, sticky="n")
            elif is_g_slot:
                tk.Label(container, text="", bg=FONDO,
                         font=("Segoe UI", 6)
                         ).grid(row=0, column=i)
            else:
                tk.Label(container, text="", bg=FONDO,
                         font=("Segoe UI", 6)
                         ).grid(row=0, column=i)

            # ── Fila 1: slider vertical ───────────────────────────
            if is_t_slot:
                # Fader T: controla velocidad de secuencia (100ms - 10000ms)
                s = tk.Scale(container, from_=10000, to=100, orient="vertical",
                             variable=var,
                             bg=FADER_FONDO, troughcolor=FADER_SURCO,
                             highlightthickness=0,
                             length=ALTURA_FADER, width=28,
                             showvalue=False,
                             resolution=100,
                             command=self._on_tempo_slider)
            elif is_g_slot:
                # Fader g1/g2: velocidad/intensidad de la secuencia del slot
                # No controla un fixture fijo — respeta el fixture activo al ejecutar
                s = tk.Scale(container, from_=255, to=0, orient="vertical",
                             variable=var,
                             bg=FADER_FONDO, troughcolor=FADER_SURCO,
                             highlightthickness=0,
                             length=ALTURA_FADER, width=28,
                             showvalue=False,
                             command=lambda v, gn=g_num: self._on_g_slot_fader(gn, v))
            else:
                s = tk.Scale(container, from_=255, to=0, orient="vertical",
                             variable=var,
                             bg=FADER_FONDO, troughcolor=FADER_SURCO,
                             highlightthickness=0,
                             length=ALTURA_FADER, width=28,
                             showvalue=False,
                             command=lambda v, c=canal: self._on_slider(c, v))
            s.grid(row=1, column=i, padx=1)

            # ── Fila 2: valor numérico (ms para T, normal para otros) ──
            if is_t_slot:
                # Mostrar valor en ms con etiqueta dinámica
                ms_lbl = tk.Label(container, textvariable=var, bg=FONDO, fg=TEXTO,
                                  font=("Segoe UI", 7))
                ms_lbl.grid(row=2, column=i)
                tk.Label(container, text="ms", bg=FONDO, fg="#888",
                         font=("Segoe UI", 6)).grid(row=2, column=i, sticky="e", padx=2)
            else:
                tk.Label(container, textvariable=var, bg=FONDO, fg=TEXTO,
                         font=("Segoe UI", 8)
                         ).grid(row=2, column=i)

            # ── Fila 3: etiqueta / botón ejecutar secuencia ───────
            if is_t_slot:
                # Fila 3: etiqueta T (velocidad)
                tk.Label(container, text="Veloc.", bg=BOTON_GRIS, fg=TEXTO,
                         font=("Segoe UI", 7), relief="flat", height=2
                         ).grid(row=3, column=i, padx=1, pady=(2,4), sticky="ew")
            elif is_g_slot:
                # Fila 3: un solo botón G# — primer clic guarda, siguientes ejecutan
                b = tk.Button(container,
                              text=f"G{g_num}",
                              bg=BOTON_AZUL, fg=TEXTO_BLANCO,
                              font=("Segoe UI", 8, "bold"),
                              relief="flat", height=2,
                              activebackground=BOTON_AZUL_ACTIVO,
                              command=lambda n=g_num: self._g_slot_action(n))
                b.grid(row=3, column=i, padx=1, pady=(2,4), sticky="ew")
                self.botones_secuencia[f"g_slot_{g_num}"] = b
            else:
                tk.Label(container, text=lbl_bot, bg=BOTON_GRIS, fg=TEXTO,
                         font=("Segoe UI", 8), relief="flat", height=2
                         ).grid(row=3, column=i, padx=1, pady=(2, 4), sticky="ew")

        # ── Filas 4-5: botones G extra (los que no tienen fader) ──────────
        # Modo 7ch:  G1,G2 tienen fader  → botones desde G3  hasta G20
        # Modo 23ch: G1-G5 tienen fader  → botones desde G6  hasta G23
        # Modo 7ch:  G3-G20  (2 filas de 9)
        # Modo 23ch: G6-G23  (2 filas de 9)
        g_start = 3 if is_7ch else 6
        g_end   = 21 if is_7ch else 24   # range() excluye el límite
        g_all   = list(range(g_start, g_end))
        g_row0  = g_all[:9]
        g_row1  = g_all[9:]
        for row_idx, g_range in enumerate([g_row0, g_row1]):
            for col_idx, g_num in enumerate(g_range):
                key = f"g_slot_{g_num}"   # misma key que botones con fader
                b = tk.Button(container, text=f"G{g_num}",
                              bg=BOTON_AZUL, fg=TEXTO_BLANCO,
                              font=("Segoe UI", 8), relief="flat",
                              height=2,
                              activebackground=BOTON_AZUL_ACTIVO,
                              command=lambda n=g_num: self._g_slot_action(n))
                b.grid(row=4 + row_idx, column=col_idx,
                       padx=1, pady=2, sticky="ew")
                self.botones_secuencia[key] = b

    def _guardar_g_slot(self, g_num):
        # Guarda la secuencia para el slot Gn usando el formato combinado:
        _, scene_nums = self._parse_g_entry(self.entrada_g.get())
        if not scene_nums:
            from tkinter.simpledialog import askstring
            raw = askstring(f"Guardar G{g_num}",
                            f"Escenas para G{g_num} (ej: 1,2,3,4):")
            if not raw:
                return
            scene_nums = self._scene_list(raw)
        if not scene_nums:
            return

        cmd = self._format_seq_cmd(g_num, self._build_seq_steps(scene_nums))
        self._send(cmd)
        # Marcar como guardado
        if not hasattr(self, "g_slot_saved"):
            self.slot_g_guardado = {}
        self.slot_g_guardado[g_num] = True
        # Actualizar el botón correcto 
        btn_key = f"g_slot_{g_num}"
        if btn_key in self.botones_secuencia:
            self.botones_secuencia[btn_key].config(bg=VERDE_ESCENA, text=f"G{g_num} ✓")
        self._log(f"💾 G{g_num} guardada: {cmd}")
    def _ejecutar_g_slot(self, g_num):
        
        #Ejecuta G{g_num} desde los slots del panel de faders
        self._launch_seq(g_num, btn_key=f"g_slot_{g_num}")

    def _g_slot_action(self, g_num):
        
        #El guardado se hace desde el campo 'Guardar G'

        self._launch_seq(g_num, btn_key=f"g_slot_{g_num}")

    def _launch_seq(self, num, btn_key=None):
        
        #Lanza la secuencia G{num} de forma inmediata
        
        self._send("H")
        # Establecer fixture activo en el ESP32
        fx = self._current_fixture()
        if fx == 0:
            self._send("F0")
        elif fx in (1, 2):
            self._send(f"F{fx}")
        else:
            self._send("F1")
        # Lanzar nueva secuencia
        self._send(f"G{num}")

        # Actualizar visual de TODOS los botones G — mismo comportamiento
        for k, b in self.botones_secuencia.items():
            is_active = (k == btn_key) or (k == f"g{num}") or (k == f"g_slot_{num}")
            # Obtener número del slot para restaurar texto
            if k.startswith("g_slot_"):
                slot_n = k.replace("g_slot_", "")
            else:
                slot_n = k.replace("g", "")
            if is_active:
                b.config(bg=BOTON_AZUL_ACTIVO, text=f"▶ G{slot_n} ▶")
            else:
                # Restaurar texto: verde con ✓ si guardado, azul normal si no
                saved = getattr(self, "g_slot_saved", {})
                try:
                    sn = int(slot_n)
                except ValueError:
                    sn = 0
                if saved.get(sn, False):
                    b.config(bg=VERDE_ESCENA, text=f"G{slot_n} ✓")
                else:
                    b.config(bg=BOTON_AZUL, text=f"G{slot_n}")

        dest = "AMBOS (F1+F2)" if fx == 0 else f"WASH FX {fx if fx in (1, 2) else 1}"
        self._log(f"▶ G{num} activa → {dest}")

    def _on_g_slot_fader(self, g_num, value):
        
        val = int(float(value))
        fx = self._current_fixture()
        target = 0 if fx == 0 else (fx if fx in (1, 2) else 1)
        if self.puerto_serial and self.conectado:
            try:
                self.puerto_serial.write((f"D{target},{val}\n").encode())
            except Exception as e:
                self._log(f"⚠️ g_slot_fader: {e}")

    def _on_tempo_slider(self, value):
        #Fader T: controla la velocidad de la secuencia activa (T#### en ms)
        ms = int(float(value))
        # Redondear a múltiplos de 100ms
        ms = max(100, min(10000, round(ms / 100) * 100))
        if self.puerto_serial and self.conectado:
            try:
                self.puerto_serial.write(("T" + str(ms) + "\n").encode())
            except Exception as e:
                self._log(f"⚠️ tempo: {e}")

    def _g_row(self, parent, start, end):
        f = tk.Frame(parent, bg=FONDO)
        f.pack(anchor="w", padx=4, pady=1)
        for i in range(start, end + 1):
            key = f"g{i}"
            b = tk.Button(f, text=key, bg=BOTON_AZUL, fg=TEXTO_BLANCO,
                          font=("Segoe UI", 8), relief="flat",
                          width=4, height=1,
                          activebackground=BOTON_AZUL_ACTIVO,
                          command=lambda k=key, n=i: self._seq_action(k, n))
            b.pack(side="left", ipadx=6, padx=2)
            self.botones_secuencia[key] = b

    # ────────────────────────────────────────────
    #  Rueda de color
    #  Dibuja la rueda HSV con sectores rellenos para mayor precisión al hacer click
    # ────────────────────────────────────────────
    def _draw_wheel(self, canvas, cx, cy, r):
        import colorsys
        # Dibujar líneas radiales para cada ángulo con gradiente de saturación
        for angle in range(360):
            rad = math.radians(angle)
            h = angle / 360.0
            # Línea desde el centro (blanco) hasta el borde (color saturado)
            for dist_pct in range(5, 101, 5):
                sat = dist_pct / 100.0
                rv, gv, bv = colorsys.hsv_to_rgb(h, sat, 1.0)
                color = f"#{int(rv*255):02x}{int(gv*255):02x}{int(bv*255):02x}"
                r1 = (dist_pct - 5) / 100.0 * r
                r2 = dist_pct / 100.0 * r
                x1 = cx + r1 * math.cos(rad)
                y1 = cy + r1 * math.sin(rad)
                x2 = cx + r2 * math.cos(rad)
                y2 = cy + r2 * math.sin(rad)
                canvas.create_line(x1, y1, x2, y2, fill=color, width=4)
        # Punto central blanco
        canvas.create_oval(cx-5, cy-5, cx+5, cy+5, fill="white", outline="")
        # Guardar referencia al cursor de selección
        self._cursor_rueda = None

    def _on_wheel_click(self, event):
        #Calcula el color HSV del punto clickeado y lo envía
        import colorsys
        cx, cy, r = self._centro_x_rueda, self._centro_y_rueda, self._radio_rueda
        dx = event.x - cx
        dy = event.y - cy
        dist = math.sqrt(dx*dx + dy*dy)

        if dist > r:
            return   # fuera de la rueda

        # Calcular H y S desde las coordenadas polares
        angle = math.degrees(math.atan2(dy, dx)) % 360
        h = angle / 360.0
        s = min(dist / r, 1.0)
        rv, gv, bv = colorsys.hsv_to_rgb(h, s, 1.0)
        red   = int(rv * 255)
        green = int(gv * 255)
        blue  = int(bv * 255)
        hex_color = f"#{red:02x}{green:02x}{blue:02x}"

        # Mover cursor visual en la rueda
        if self._cursor_rueda:
            self.rueda_color.delete(self._cursor_rueda)
        self._cursor_rueda = self.rueda_color.create_oval(
            event.x - 6, event.y - 6,
            event.x + 6, event.y + 6,
            outline="black", width=2, fill=""
        )

        # Actualizar indicador de color
        self._indicador_color.config(
            bg=hex_color,
            fg="#ffffff" if (red*0.299 + green*0.587 + blue*0.114) < 128 else "#000000",
            text=f" R:{red}  G:{green}  B:{blue} "
        )

        # Enviar color según el modo
        self._apply_color(red, green, blue)

    # ────────────────────────────────────────────
    #  FUnciones auxiliares
    # ────────────────────────────────────────────
    def _btn(self, parent, text, cmd, bg=BOTON_GRIS, fg=TEXTO,
             font=("Segoe UI", 9), width=None, relief="flat", **kw):
        kwargs = dict(text=text, command=cmd, bg=bg, fg=fg, font=font,
                      relief=relief, bd=0,
                      activebackground=self._dk(bg),
                      activeforeground=fg, cursor="hand2",
                      padx=6, pady=3)
        if width: kwargs["width"] = width
        kwargs.update(kw)
        return tk.Button(parent, **kwargs)

    @staticmethod
    def _dk(h):
        try:
            r = max(int(h[1:3], 16) - 30, 0)
            g = max(int(h[3:5], 16) - 30, 0)
            b = max(int(h[5:7], 16) - 30, 0)
            return f"#{r:02x}{g:02x}{b:02x}"
        except: return h

    def _log(self, msg):
        self.consola.config(state="normal")
        self.consola.insert("end", msg + "\n")
        self.consola.see("end")
        self.consola.config(state="disabled")

    # ────────────────────────────────────────────
    #  Serial
    # ────────────────────────────────────────────
    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.combo_puerto["values"] = ports
        if ports: self.var_puerto.set(ports[0])

    def _toggle_connect(self):
        if self.conectado:
            self.conectado = False
            if self.puerto_serial: self.puerto_serial.close(); self.puerto_serial = None
            self.boton_conectar.config(text="Conectar", bg=BOTON_GRIS, fg=TEXTO)
            self._log("⛔ Desconectado.")
        else:
            port = self.var_puerto.get()
            if not port:
                messagebox.showerror("Error", "Selecciona un puerto."); return
            try:
                self.puerto_serial = serial.Serial(port, 115200, timeout=1)
                self.conectado = True
                self.boton_conectar.config(text="Desconectar", bg="#cc3333", fg=TEXTO_BLANCO)
                self._log(f"✅ Conectado a {port}")
                self._buffer_estado = []
                self._leyendo_estado = False
                threading.Thread(target=self._read_loop, daemon=True).start()
                # Pedir estado guardado en EEPROM tras 1.5s (dar tiempo al ESP32)
                self.after(1500, lambda: self._send("GETSTATE"))
            except Exception as e:
                messagebox.showerror("Error de conexión", str(e))

    def _send(self, cmd):
        if self.puerto_serial and self.conectado:
            try:
                self.puerto_serial.write((cmd + "\n").encode())
                self._log(f"→ {cmd}")
            except Exception as e:
                self._log(f"⚠️ {e}")
        else:
            self._log(f"[sin conexión] {cmd}")

    def _read_loop(self):
        # Lee líneas del ESP32 y procesa el bloque STATE
        while self.conectado and self.puerto_serial:
            try:
                line = self.puerto_serial.readline().decode(errors="replace").strip()
                if not line:
                    continue
                if line == "STATE_BEGIN":
                    self._buffer_estado  = []
                    self._leyendo_estado = True
                elif line == "STATE_END":
                    self._leyendo_estado = False
                    self.after(0, self._restore_state, list(self._buffer_estado))
                elif self._leyendo_estado:
                    self._buffer_estado.append(line)
                else:
                    self.after(0, self._log, f"← {line}")
            except:
                break

    def _restore_state(self, lines):
        # Restaura el interfaz de usuario completo desde el bloque STATE del ESP32
        self._log("📥 Restaurando estado desde EEPROM...")
        for line in lines:
            try:
                key, val = line.split("=", 1)

                if key == "MODO":
                    canales = int(val)
                    self.modo.set("7 canales" if canales == 7 else "23 canales")
                    self._rebuild_channels()
                    self._load_fixture_image()

                elif key == "BASE":
                    b1, b2 = val.split(",")
                    self._log(f"📍 F1=canal {b1}  F2=canal {b2}")

                elif key == "T":
                    self._log(f"⏱ Tiempo por escena: {val}ms")

                elif key == "ESCENA":
                    num = int(val)
                    k   = f"S{num}"
                    if k in self.botones_escena:
                        self.escena_guardada[k] = True
                        self.botones_escena[k].config(bg="#3377bb")

                elif key == "SEQ":
                    
                    parts = val.split(",")
                    gnum  = parts[0].lstrip("Gg")
                    scene_list = []
                    for step in parts[1:]:
                        for seg in step.split("+"):
                            if seg.startswith("F") and ":" in seg:
                                fpart, spart = seg.split(":", 1)
                                fnum = int(fpart[1:])
                                snum = int(spart.lstrip("Ss"))
                                scene_list.append(snum)
                                self.fixture_escena[snum] = fnum
                    self._log(f"🔧 G{gnum} → {len(scene_list)} escena(s) restauradas")
                    # Reconstruir el campo en el formato que entiende la UI
                    self.entrada_g.delete(0, "end")
                    self.entrada_g.insert(0, f"G{gnum}: " +
                        ", ".join(f"S{s}" for s in scene_list))

                elif key == "FSTATE":
                    parts  = val.split(",")
                    fnum   = int(parts[0])
                    valores = [int(v) for v in parts[1:]]
                    # Restaurar sliders si corresponde al fixture activo
                    if fnum == 1:
                        for i, v in enumerate(valores):
                            canal = i + 1
                            if canal in self.vars_fader:
                                self.vars_fader[canal].set(v)

            except Exception as e:
                self._log(f"⚠️ Error restaurando '{line}': {e}")

        self._log("✅ Estado restaurado desde EEPROM.")

    # ────────────────────────────────────────────
    #  Acciones DMX
    # ────────────────────────────────────────────
    def _on_slider(self, canal, value):
        # Si ambos fixtures activos, asegurar F0 antes del cambio de canal
        fx = self._current_fixture()
        if fx == 0:
            self._send("F0")
        self._send(f"{canal},{int(value)}")

    def _on_master(self, value):
        """
        Regulador maestro = dimmer global (ambos fixtures).
          - 7 canales : el ESP32 escala R,G,B de cada fixture
          - 23 canales: el ESP32 fija el canal 1 (dimmer real) de cada fixture
        """
        val = int(value)
        if self.puerto_serial and self.conectado:
            try:
                self.puerto_serial.write((f"D0,{val}\n").encode())
            except Exception as e:
                self._log(f"⚠️ maestro: {e}")

    def _scene_action(self, key, num):
        btn = self.botones_escena[key]
        if not self.escena_guardada[key]:
            # Guardar escena: el ESP32 guarda el estado del fixture activo
            self._send(f"S{num}")
            self.escena_guardada[key] = True
            fx = self._current_fixture()
            self.fixture_escena[num] = fx
            dest = "AMBOS" if fx == 0 else f"WASH FX {fx}"
            self._log(f"💾 Escena {num} guardada para {dest}")
            btn.config(bg="#3377bb")
        else:
            # Reproducir: enviar F0 si ambos activos para aplicar a los dos
            fx = self._current_fixture()
            if fx == 0:
                self._send("F0")
            self._send(f"P{num}")

    def _seq_action(self, key, num):
        # Ejecuta G{num} desde los botones g3-g20
        self._launch_seq(num, btn_key=key)

    def _scene_list(self, txt):
        nums = []
        for tok in txt.replace(" ", "").split(","):
            tok = tok.lstrip("Ss")
            if tok.isdigit():
                nums.append(int(tok))
        return nums

    def _parse_g_entry(self, txt):
        #Parsea 'G1: S1, S2, S3' -> (gnum:int, [1,2,3]). Devuelve (None,[]) si falla
        try:
            t = txt.replace(" ", "")
            head, body = t.split(":", 1)
            gnum = int(head.lstrip("Gg"))
            return gnum, self._scene_list(body)
        except Exception:
            return None, []

    def _build_seq_steps(self, scene_nums):
        fx = self._current_fixture()  # 0 = AMBOS, 1 o 2
        if fx != 0:
            # Un solo fixture activo: pasos simples
            return [{fx: s} for s in scene_nums]

        # Modo AMBOS: agrupar escenas por fixture para construir pasos multi-fixture
        # Primero detectar qué fixture tiene cada escena
        steps = []
        i = 0
        while i < len(scene_nums):
            s = scene_nums[i]
            fx_s = self.fixture_escena.get(s, 1)  # fixture de esta escena (default F1)
            paso = {fx_s: s}
            # Buscar si la siguiente escena es de un fixture distinto para unirlas en un paso
            if i + 1 < len(scene_nums):
                s2 = scene_nums[i + 1]
                fx_s2 = self.fixture_escena.get(s2, 2)
                if fx_s2 != fx_s:
                    # Escenas de fixtures distintos → mismo paso (simultáneo)
                    paso[fx_s2] = s2
                    i += 2
                    steps.append(paso)
                    continue
            steps.append(paso)
            i += 1
        return steps

    def _format_seq_cmd(self, gnum, steps):
        parts = []
        for step in steps:
            segs = [f"F{fx}:S{esc}" for fx, esc in sorted(step.items())]
            parts.append("+".join(segs))
        return f"G{gnum}=" + ",".join(parts)

    def _guardar_g(self):
        gnum, scene_nums = self._parse_g_entry(self.entrada_g.get())
        if gnum is None or not scene_nums:
            self._log("⚠️ Formato inválido. Usa por ej.  G1: S1, S2")
            return
        steps = self._build_seq_steps(scene_nums)
        cmd = self._format_seq_cmd(gnum, steps)
        self._send(cmd)
        # Marcar botón de la secuencia como guardada
        for key in [f"g{gnum}", f"g_slot_{gnum}"]:
            if key in self.botones_secuencia:
                self.botones_secuencia[key].config(bg=VERDE_ESCENA)
        self._log(f"💾 G{gnum} guardada: {cmd}")

    def _full_on(self):
        """
        Blanco total:
          - Modo 7 canales : canales 1,2,3 (R,G,B) al máximo.
          - Modo 23 canales: canales 6 al 23 (las 6 zonas RGB) al máximo.
        Se respeta el fixture activo (F0 = ambos, F1 o F2).
        """
        if self.modo.get() == "23 canales":
            canales = list(range(6, 24))   # 6,7,...,23
        else:
            canales = [1, 2, 3]

        cmd = ":".join(f"{ch},255" for ch in canales)
        self._send(cmd)

        for ch in canales:
            if ch in self.vars_fader:
                self.vars_fader[ch].set(255)

        # Si hay panel de zonas activo, pintar todos los botones de blanco
        if hasattr(self, "_zona_btns"):
            for btn in self._botones_zona.values():
                btn.config(bg="#ffffff", activebackground="#ffffff")
            if hasattr(self, "_color_indicator"):
                self._indicador_color.config(bg="#ffffff", fg="#000000",
                                             text=" R:255  G:255  B:255 ")

        self._log(f"⚪ Full ON → blanco (canales {canales[0]}-{canales[-1]} = 255)")

    def _toggle_blackout(self):
        self.apagon_activo = not self.apagon_activo
        if self.apagon_activo:
            self._send("B")
            for var in self.vars_fader.values():
                var.set(0)
            self.boton_borrar.config(bg="#cc0000", text="◼ BORRAR")
        else:
            self.boton_borrar.config(bg=BOTON_NEGRO, text="BORRAR")

    def _borrar_todo(self):
        from tkinter import messagebox
        resp = messagebox.askyesnocancel(
            "Borrar todo",
            "¿También borrar lo guardado en la memoria EEPROM?\n\n"
            "  • SÍ  → Pone canales a 0 Y borra escenas/secuencias de la EEPROM\n"
            "  • NO  → Solo pone canales a 0 (EEPROM sin cambios)\n"
            "  • Cancelar → No hace nada"
        )
        if resp is None:        # Cancelar
            return
        # Siempre: blackout de canales
        self._send("B")
        for var in self.vars_fader.values():
            var.set(0)
        if resp:                # SÍ → borrar EEPROM también
            self._send("CLEAREEPROM")
            # Resetear botones de escenas en la UI
            for key, btn in self.botones_escena.items():
                self.escena_guardada[key] = False
                btn.config(bg=VERDE_ESCENA)
            # Resetear botones de secuencias
            for btn in self.botones_secuencia.values():
                btn.config(bg=BOTON_AZUL)
            self.entrada_g.delete(0, "end")
            self.entrada_g.insert(0, "G1: S1, S2, S3")
            self._log("🗑️ EEPROM borrada y canales a 0.")

    def _undo(self):    self._send("V")
    def _detener(self): self._send("H")

    def _pick_color(self):
        #Abre el selector de color del sistema (solo como alternativa)
        color = colorchooser.askcolor(title="Elegir color DMX")
        if color and color[0]:
            r, g, b = (int(x) for x in color[0])
            self._apply_color(r, g, b)

    def _apply_color(self, r, g, b):
        hex_color = f"#{r:02x}{g:02x}{b:02x}"

        if self.modo.get() == "23 canales":
            zonas = getattr(self, "_zonas_activas", set())
            if not zonas:
                if hasattr(self, "_color_indicator"):
                    self._indicador_color.config(
                        bg=hex_color,
                        fg="#ffffff" if (r*0.299+g*0.587+b*0.114)<128 else "#000000",
                        text="⚠ Selecciona una zona"
                    )
                return
            # Construir comando con todos los canales de todas las zonas activas
            cmd_parts = []
            for zona in sorted(zonas):
                chs = self.ZONA_CANALES[zona]
                cmd_parts += [f"{chs[0]},{r}", f"{chs[1]},{g}", f"{chs[2]},{b}"]
                # Actualizar color del botón
                if hasattr(self, "_zona_btns") and zona in self._botones_zona:
                    self._botones_zona[zona].config(bg=hex_color,
                                                 activebackground=hex_color)
            self._send(":".join(cmd_parts))
            n = len(zonas)
            self._log(f"🎨 {n} zona(s) {sorted(zonas)} → RGB({r},{g},{b})")
        else:
            # Modo 7ch: R→canal1, G→canal2, B→canal3
            # Asegurar que el fixture correcto esté activo en el ESP32
            fx = self._current_fixture()
            if fx == 0:
                self._send("F0")
            self._send(f"1,{r}:2,{g}:3,{b}")
            for canal, val in [(1, r), (2, g), (3, b)]:
                if canal in self.vars_fader:
                    self.vars_fader[canal].set(val)


if __name__ == "__main__":
    app = DMXApp()
    app.mainloop()