"""Ventana del programa: topografia (+ ortofoto) -> polilineas, areas con achurado, metrado y laminas.

python -m ortofoto.gui

La ventana esta ordenada en pasos (pestanas numeradas). Cada pestana explica arriba que se hace en
ella, los campos tienen ayuda al pasar el mouse y la barra de abajo dice que falta para procesar.
"""
import collections
import copy
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import laminas as lammod
from . import topografia, unir
from .__main__ import CODIGOS_DEFECTO, Opciones, calcular, exportar_calculo, procesar

TITULO = "WambriDemoliciones"
CONFIG_VENTANA = Path.home() / ".planos_bambu" / "ventana.json"
VERDE, VERDE_CLARO, GRIS = "#2e7d32", "#e8f5e9", "#666"
COLUMNAS = [  # (clave, titulo, ancho, editable)
    ("usar", "Usar", 45, False),
    ("codigo", "Codigo", 70, False),
    ("puntos", "Puntos", 60, False),
    ("nombre", "Elemento", 140, True),
    ("tipo", "Tipo", 75, True),
    ("capa", "Capa bordes", 170, True),
    ("capa_area", "Capa area + achurado", 170, True),
    ("prefijo", "Prefijo", 60, True),
    ("separacion_max", "Sep. max (m)", 85, True),
    ("ancho_min", "Ancho min", 70, True),
    ("ancho_max", "Ancho max", 70, True),
    ("referencia", "Referencia", 90, True),
    ("ancho_defecto", "Ancho supuesto", 95, True),
    ("apagar", "Apagar en DXF", 90, False),
]
AYUDA_TIPOS = ("linea: se une en polilinea abierta (metrado en m)\n"
               "franja: dos bordes que cierran un area (vereda, cuneta, pista)\n"
               "contorno: un borde que se cierra solo (martillo, acceso)\n"
               "punto: solo puntos (arboles, cajas, postes)")
ESCALAS = ("200", "250", "500", "750", "1000")
GUIA = """COMO USAR EL PROGRAMA (paso a paso)

1. ARCHIVOS
   Elija el archivo de puntos (Civil 3D: Points > Export Points > PNEZD).
   Si tiene el plano del proyecto (lotes, fachadas), agreguelo: las veredas se pegan al limite
   de propiedad y salen las lineas de corte (CL). La ortofoto es opcional.

2. CODIGOS Y CAPAS
   La tabla muestra cada codigo del levantamiento y como se dibuja. Los codigos en amarillo no
   estan configurados. Si el programa cree que es un error de escritura (p.ej. VERD en vez de VER)
   lo avisa arriba y con un clic lo agrega como alias.

3. LAMINAS Y MEMBRETE
   Escala, orientacion y numeracion de las laminas, y los datos del membrete (proyecto, entidad,
   ubicacion, fecha). Los datos se pueden guardar como predeterminados.

4. PROCESAR
   Pulse PROCESAR. Si marca "revisar antes de exportar", se abre la pestana 5 para ver y corregir
   el resultado sobre la ortofoto; luego EXPORTAR.

5. REVISAR Y CORREGIR
   Revise uniones dudosas y corrija por tramos antes de exportar.

RESULTADOS (en la carpeta elegida)
   resultado.dxf ............ polilineas, areas, carteles, laminas con membrete
   metrado.xlsx / .csv ...... areas, perimetros y longitudes por partida y por lamina
   laminas_vista_previa.pdf . como quedan las laminas
   vista.png ................ vista general
   resumen.md ............... avisos, reglas aplicadas y carteles para revisar
"""


class Ayuda:
    """Globo de ayuda que aparece al pasar el mouse sobre un control."""

    def __init__(self, widget, texto):
        self.widget, self.texto, self.top = widget, texto, None
        widget.bind("<Enter>", self._mostrar, add="+")
        widget.bind("<Leave>", self._ocultar, add="+")

    def _mostrar(self, _=None):
        if self.top or not self.texto:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.top = tk.Toplevel(self.widget)
        self.top.wm_overrideredirect(True)
        self.top.wm_geometry(f"+{x}+{y}")
        tk.Label(self.top, text=self.texto, justify="left", background="#ffffe0", relief="solid", borderwidth=1,
                 wraplength=420, padx=6, pady=4).pack()

    def _ocultar(self, _=None):
        if self.top:
            self.top.destroy()
            self.top = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        try:
            from ._version import VERSION
        except ImportError:
            VERSION = "desarrollo"
        self.title(f"{TITULO}  (version {VERSION})")
        self.geometry("1280x860")
        self.minsize(1000, 680)
        self.cola = queue.Queue()
        self.codigos, self.alias = unir.cargar_codigos(CODIGOS_DEFECTO)
        self.ruta_codigos = str(CODIGOS_DEFECTO)
        self.conteo = {}
        self.conteo_crudo = {}
        self.sugerencias = {}
        self.apagar = set()
        self.ultima_salida = ""
        self.var = {k: tk.StringVar() for k in ("puntos", "orto", "calce_dxf", "control", "plantilla", "salida",
                                                "plano_base")}
        self.capas_limite = tk.StringVar(value="FACHADA")
        self.var["salida"].set(str(Path.home() / "Documents" / "resultado_topografia"))
        self.calce = tk.StringVar(value="foto")
        self.calce_auto = tk.BooleanVar(value=True)
        self.completar = tk.BooleanVar(value=True)
        self.veredas_foto = tk.BooleanVar(value=False)
        self.muestras = tk.BooleanVar(value=False)
        self.radio = tk.StringVar(value="3")
        self.resolucion = tk.StringVar(value="0")
        self.revisar_antes = tk.BooleanVar(value=True)
        # opciones nuevas (los valores por defecto dan el mismo resultado que antes mas carteles y laminas)
        self.numero_separa = tk.BooleanVar(value=False)
        self.codigos_control = tk.BooleanVar(value=False)
        self.cartel = tk.StringVar(value="petro")
        self.corte_lineal = tk.BooleanVar(value=True)
        self.escala = tk.StringVar(value="500")
        self.lam_activar = tk.BooleanVar(value=True)
        self.lam_orientacion = tk.StringVar(value="norte")
        self.lam_traslape = tk.StringVar(value="5")
        self.lam_prefijo = tk.StringVar(value="D-")
        self.lam_inicio = tk.StringVar(value="1")
        self.lam_numerar = tk.BooleanVar(value=True)
        self.lam_pdf = tk.BooleanVar(value=True)
        self.carpeta_por_corrida = tk.BooleanVar(value=False)
        self.verificar = tk.BooleanVar(value=True)
        self.membrete = lammod.cargar_membrete()
        self.var_membrete = {}
        self._cargar_ventana()
        self._armar()
        self._llenar_tabla()
        for v in list(self.var.values()) + [self.calce, self.cartel, self.corte_lineal, self.escala, self.lam_activar,
                                            self.lam_orientacion, self.lam_prefijo, self.carpeta_por_corrida]:
            v.trace_add("write", lambda *_: self._actualizar_estado())
        self._actualizar_estado()
        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.after(150, self._leer_cola)

    # ---------- preferencias de la ventana ----------
    def _preferencias(self):
        return {"var": {k: v.get() for k, v in self.var.items()}, "capas_limite": self.capas_limite.get(),
                "calce": self.calce.get(), "escala": self.escala.get(), "cartel": self.cartel.get(),
                "orientacion": self.lam_orientacion.get(), "traslape": self.lam_traslape.get(),
                "prefijo": self.lam_prefijo.get(), "revisar_antes": self.revisar_antes.get()}

    def _cargar_ventana(self):
        try:
            d = json.loads(CONFIG_VENTANA.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k, v in d.get("var", {}).items():
            if k in self.var and v:
                self.var[k].set(v)
        for clave, var in (("capas_limite", self.capas_limite), ("calce", self.calce), ("escala", self.escala),
                           ("cartel", self.cartel), ("orientacion", self.lam_orientacion),
                           ("traslape", self.lam_traslape), ("prefijo", self.lam_prefijo)):
            if d.get(clave):
                var.set(d[clave])
        if "revisar_antes" in d:
            self.revisar_antes.set(bool(d["revisar_antes"]))

    def _cerrar(self):
        try:
            CONFIG_VENTANA.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_VENTANA.write_text(json.dumps(self._preferencias(), ensure_ascii=False, indent=1),
                                      encoding="utf-8")
        except OSError:
            pass
        self.destroy()

    # ---------- interfaz ----------
    def _armar(self):
        estilo = ttk.Style(self)
        if "vista" in estilo.theme_names():
            estilo.theme_use("vista")
        estilo.configure("Grande.TButton", font=("Segoe UI", 12, "bold"), padding=8)
        estilo.configure("Paso.TLabel", font=("Segoe UI", 11, "bold"))
        cab = tk.Frame(self, bg=VERDE)
        cab.pack(fill="x")
        tk.Label(cab, text="WambriDemoliciones", bg=VERDE, fg="white",
                 font=("Segoe UI", 14, "bold")).pack(side="left", padx=12, pady=6)
        tk.Label(cab, text="Planos de demolicion desde la topografia", bg=VERDE, fg="#c8e6c9",
                 font=("Segoe UI", 10)).pack(side="left", padx=4)
        tk.Label(cab, text="Siga las pestanas en orden: 1 > 2 > 3 > 4 > 5", bg=VERDE, fg="#c8e6c9",
                 font=("Segoe UI", 10)).pack(side="left", padx=8)
        tk.Button(cab, text="Guia rapida", command=self._guia, bg="white", relief="flat").pack(side="right", padx=10)
        self.barra_estado = tk.Label(self, anchor="w", bg="#f1f1f1", padx=8, font=("Segoe UI", 9))
        self.barra_estado.pack(side="bottom", fill="x")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.nb = nb
        nb.add(self._pestana_archivos(nb), text="1. Archivos")
        nb.add(self._pestana_codigos(nb), text="2. Codigos y capas")
        nb.add(self._pestana_laminas(nb), text="3. Laminas y membrete")
        nb.add(self._pestana_proceso(nb), text="4. Procesar")
        from .visor import Visor

        self.visor = Visor(nb, self._exportar)
        nb.add(self.visor, text="5. Revisar y corregir")
        nb.add(self._pestana_herramientas(nb), text="Herramientas")
        nb.bind("<<NotebookTabChanged>>", lambda _: self._al_cambiar())

    def _intro(self, padre, titulo, texto):
        caja = tk.Frame(padre, bg=VERDE_CLARO, highlightbackground="#a5d6a7", highlightthickness=1)
        tk.Label(caja, text=titulo, bg=VERDE_CLARO, fg=VERDE, font=("Segoe UI", 11, "bold"),
                 anchor="w").pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(caja, text=texto, bg=VERDE_CLARO, justify="left", anchor="w", wraplength=1150).pack(
            fill="x", padx=8, pady=(0, 6))
        return caja

    def _siguiente(self, padre, indice, texto):
        b = ttk.Button(padre, text=f"Siguiente paso: {texto}  >", command=lambda: self.nb.select(indice))
        return b

    def _guia(self):
        top = tk.Toplevel(self)
        top.title("Guia rapida")
        top.geometry("760x620")
        t = tk.Text(top, wrap="word", font=("Consolas", 10), padx=10, pady=10)
        t.insert("1.0", GUIA)
        t.config(state="disabled")
        t.pack(fill="both", expand=True)
        ttk.Button(top, text="Cerrar", command=top.destroy).pack(pady=6)

    def _fila_archivo(self, padre, fila, texto, clave, tipos, carpeta=False, ayuda=""):
        ttk.Label(padre, text=texto).grid(row=fila, column=0, sticky="w", pady=3)
        ent = ttk.Entry(padre, textvariable=self.var[clave], width=90)
        ent.grid(row=fila, column=1, sticky="we", padx=4)

        def elegir():
            if carpeta:
                r = filedialog.askdirectory()
            else:
                r = filedialog.askopenfilename(filetypes=tipos)
            if r:
                self.var[clave].set(r)
                if clave == "puntos":
                    self._contar_puntos()
                # El plano de Civil 3D sirve para el calce y como plano base (lotes, fachadas)
                if clave == "calce_dxf" and not self.var["plano_base"].get():
                    self.var["plano_base"].set(r)
                if clave == "plano_base" and not self.var["calce_dxf"].get():
                    self.var["calce_dxf"].set(r)

        ttk.Button(padre, text="Examinar...", command=elegir).grid(row=fila, column=2)
        marca = ttk.Label(padre, width=3)
        marca.grid(row=fila, column=3, padx=(4, 0))
        self._marcas = getattr(self, "_marcas", {})
        self._marcas[clave] = marca
        if ayuda:
            ttk.Label(padre, text=ayuda, foreground=GRIS).grid(row=fila + 1, column=1, sticky="w", padx=4)
            Ayuda(ent, ayuda)

    def _pestana_archivos(self, nb):
        f = ttk.Frame(nb, padding=12)
        f.columnconfigure(1, weight=1)
        self._intro(f, "Paso 1: elija sus archivos",
                    "Solo los puntos y la carpeta de resultados son obligatorios (*). Con el plano del proyecto "
                    "las veredas respetan el limite de propiedad y se dibujan las lineas de corte (CL). Con la "
                    "ortofoto las uniones siguen los bordes reales. Pase el mouse sobre un campo para ver ayuda."
                    ).grid(row=0, column=0, columnspan=4, sticky="we", pady=(0, 8))
        self._fila_archivo(f, 1, "Puntos topograficos *", "puntos",
                           [("Puntos PNEZD", "*.csv *.txt"), ("DXF con puntos COGO", "*.dxf"), ("Todos", "*.*")],
                           ayuda="Civil 3D: Points > Export Points > PNEZD (comma delimited)")
        base = ttk.LabelFrame(f, text="Plano del proyecto (recomendado)", padding=8)
        base.grid(row=3, column=0, columnspan=4, sticky="we", pady=8)
        base.columnconfigure(1, weight=1)
        self._fila_archivo(base, 0, "Plano base (DXF)", "plano_base", [("DXF", "*.dxf")],
                           ayuda="Con lotes y fachadas: las veredas se pegan al limite de propiedad, nunca entran a "
                                 "los lotes ni se unen con la otra cuadra. El resultado se agrega sobre una copia.")
        fila_c = ttk.Frame(base)
        fila_c.grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Label(fila_c, text="Capas del limite de propiedad:").pack(side="left")
        e = ttk.Entry(fila_c, textvariable=self.capas_limite, width=40)
        e.pack(side="left", padx=4)
        Ayuda(e, "Nombre de las capas del plano base que marcan el limite de propiedad. En PETRO es "
                 "LINEA DE LOTE. Se buscan sin importar mayusculas ni guiones.")
        ttk.Label(fila_c, text="(separadas por coma, p.ej. FACHADA, LINEA DE LOTE)", foreground=GRIS).pack(side="left")
        self._fila_archivo(f, 4, "Ortofoto (opcional)", "orto",
                           [("Imagenes", "*.tif *.tiff *.jpg *.jpeg *.png *.ecw"), ("Todos", "*.*")],
                           ayuda="Sin foto, une solo por geometria. Con foto, sigue los bordes reales.")
        cal = ttk.LabelFrame(f, text="Calce de la ortofoto (solo si eligio una foto)", padding=8)
        cal.grid(row=6, column=0, columnspan=4, sticky="we", pady=8)
        cal.columnconfigure(1, weight=1)
        ttk.Radiobutton(cal, text="La foto ya tiene coordenadas (GeoTIFF o .tfw/.jgw)", variable=self.calce,
                        value="foto").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(cal, text="Tomar el calce del plano de Civil 3D donde esta insertada (DXF):",
                        variable=self.calce, value="dxf").grid(row=1, column=0, columnspan=3, sticky="w")
        self._fila_archivo(cal, 2, "   Plano DXF", "calce_dxf", [("DXF", "*.dxf")])
        ttk.Radiobutton(cal, text="Puntos de control (CSV: columna, fila, este, norte):", variable=self.calce,
                        value="control").grid(row=3, column=0, columnspan=3, sticky="w")
        self._fila_archivo(cal, 4, "   Puntos de control", "control", [("CSV", "*.csv *.txt")])
        fila = ttk.Frame(cal)
        fila.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(fila, text="Afinar el calce automaticamente, buscando hasta", variable=self.calce_auto
                        ).pack(side="left")
        ttk.Entry(fila, textvariable=self.radio, width=5).pack(side="left", padx=4)
        ttk.Label(fila, text="m de desplazamiento").pack(side="left")
        fila2 = ttk.Frame(cal)
        fila2.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(fila2, text="Resolucion de trabajo (cm por pixel, 0 = la de la foto):").pack(side="left")
        ttk.Entry(fila2, textvariable=self.resolucion, width=6).pack(side="left", padx=4)
        ttk.Label(fila2, text="Con fotos muy grandes y poca memoria use 6 a 8.", foreground=GRIS).pack(side="left")
        ttk.Checkbutton(cal, text="Con foto: unir tambien lo que la foto no confirma (queda en la capa REVISAR UNION)",
                        variable=self.completar).grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(cal, text="Dibujar las veredas con la forma del concreto visible en la foto "
                                  "(EN PRUEBA; requiere el plano del proyecto)",
                        variable=self.veredas_foto).grid(row=8, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(cal, text="Exportar la ortofoto en cuadros de 100 m (ZIP de hasta 20 MB) para enviarla "
                                  "a revisar (carpeta muestras_ortofoto)",
                        variable=self.muestras).grid(row=9, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._fila_archivo(f, 7, "Plantilla de capas (opcional)", "plantilla", [("DXF", "*.dxf")],
                           ayuda="DXF del cual copiar colores, tipos de linea y grosores. Vacio = capas y estilos de PETRO.")
        self._fila_archivo(f, 9, "Carpeta de resultados *", "salida", None, carpeta=True)
        self._siguiente(f, 1, "revisar codigos").grid(row=20, column=0, columnspan=4, sticky="e", pady=10)
        return f

    def _pestana_codigos(self, nb):
        f = ttk.Frame(nb, padding=8)
        self._intro(f, "Paso 2: revise como se dibuja cada codigo",
                    "Cada fila es un codigo del levantamiento. Doble clic en una celda para editarla; clic en "
                    "'Usar' o 'Apagar' para cambiarlo. Los codigos sin usar no se unen ni generan areas. Las filas "
                    "amarillas son codigos que el programa no conoce.").pack(fill="x", pady=(0, 6))
        self.banner = tk.Frame(f, bg="#fff3cd", highlightbackground="#ffcc80", highlightthickness=1)
        self.lbl_banner = tk.Label(self.banner, bg="#fff3cd", justify="left", anchor="w", wraplength=950)
        self.lbl_banner.pack(side="left", fill="x", expand=True, padx=8, pady=4)
        tk.Button(self.banner, text="Agregar como alias", command=self._agregar_sugerencias).pack(
            side="right", padx=8, pady=4)
        botones = ttk.Frame(f)
        botones.pack(fill="x", pady=4)
        self.botones_codigos = botones
        ttk.Button(botones, text="Abrir configuracion...", command=self._abrir_config).pack(side="left")
        ttk.Button(botones, text="Guardar configuracion como...", command=self._guardar_config).pack(side="left", padx=4)
        ttk.Button(botones, text="Usar todos", command=lambda: self._marcar_todos(True)).pack(side="left", padx=4)
        ttk.Button(botones, text="Ninguno", command=lambda: self._marcar_todos(False)).pack(side="left")
        ttk.Button(botones, text="Ayuda: tipos", command=lambda: messagebox.showinfo("Tipos", AYUDA_TIPOS)
                   ).pack(side="left", padx=4)
        opc = ttk.Frame(f)
        opc.pack(fill="x", pady=(0, 4))
        c1 = ttk.Checkbutton(opc, text="El numero del codigo separa bordes (VER1 y VER2 son lineas distintas)",
                             variable=self.numero_separa)
        c1.pack(side="left")
        Ayuda(c1, "Apagado (como antes): VER1 y VER2 son el mismo codigo VER. Encendido: los puntos VER1 solo se "
                  "unen con VER1 y los VER2 con VER2, util cuando el topografo numera cada borde.")
        c2 = ttk.Checkbutton(opc, text="Respetar codigos de control (VER I = inicio, VER F = fin, MAR CLS = cerrar)",
                             variable=self.codigos_control)
        c2.pack(side="left", padx=12)
        Ayuda(c2, "Apagado (como antes): se ignoran. Encendido: una linea empieza o termina donde el topografo lo "
                  "indico con I/F, y CLS cierra el contorno.")
        marco = ttk.Frame(f)
        marco.pack(fill="both", expand=True)
        self.tabla = ttk.Treeview(marco, columns=[c[0] for c in COLUMNAS], show="headings", selectmode="browse")
        for clave, titulo, ancho, _ in COLUMNAS:
            self.tabla.heading(clave, text=titulo)
            self.tabla.column(clave, width=ancho, anchor="center" if ancho < 100 else "w")
        sb = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=sb.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tabla.tag_configure("off", foreground="#999")
        self.tabla.tag_configure("nuevo", background="#fff6d5")
        self.tabla.bind("<Button-1>", self._clic_tabla)
        self.tabla.bind("<Double-1>", self._editar_celda)
        self.lbl_alias = ttk.Label(f, foreground=GRIS, wraplength=1200, justify="left")
        self.lbl_alias.pack(fill="x", pady=4)
        self._siguiente(f, 2, "laminas y membrete").pack(anchor="e", pady=4)
        return f

    def _pestana_laminas(self, nb):
        f = ttk.Frame(nb, padding=12)
        self._intro(f, "Paso 3: carteles, laminas y membrete",
                    "El dibujo se divide en laminas A1 con el membrete del plano PETRO, leyenda, plano clave y "
                    "cuadro de metrados. Las areas llevan un cartel con area y perimetro. Aqui elige la escala, "
                    "como se numeran y los datos del membrete.").pack(fill="x", pady=(0, 8))
        cuerpo = ttk.Frame(f)
        cuerpo.pack(fill="both", expand=True)
        izq = ttk.LabelFrame(cuerpo, text="Dibujo", padding=8)
        izq.pack(side="left", fill="y", padx=(0, 8))
        r = 0
        ttk.Label(izq, text="Carteles de las areas:").grid(row=r, column=0, sticky="w")
        ttk.Radiobutton(izq, text="Recuadro con flecha, area y perimetro (PETRO)", variable=self.cartel,
                        value="petro").grid(row=r + 1, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(izq, text="Texto suelto (como antes)", variable=self.cartel,
                        value="simple").grid(row=r + 2, column=0, columnspan=2, sticky="w")
        r += 3
        c = ttk.Checkbutton(izq, text="Lineas de corte (CL) en el limite de propiedad", variable=self.corte_lineal)
        c.grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        Ayuda(c, "Donde la vereda a demoler toca la linea de lote se dibuja la linea de corte CL con su longitud, "
                 "como en PETRO. Necesita el plano base.")
        r += 1
        ttk.Label(izq, text="Escala 1:").grid(row=r, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(izq, textvariable=self.escala, values=ESCALAS, width=8).grid(row=r, column=1, sticky="w",
                                                                                pady=(8, 0))
        r += 1
        ttk.Separator(izq).grid(row=r, column=0, columnspan=2, sticky="we", pady=8)
        r += 1
        ttk.Checkbutton(izq, text="Dividir en laminas con membrete", variable=self.lam_activar).grid(
            row=r, column=0, columnspan=2, sticky="w")
        r += 1
        ttk.Label(izq, text="Orientacion:").grid(row=r, column=0, sticky="w")
        ttk.Radiobutton(izq, text="Norte arriba", variable=self.lam_orientacion, value="norte").grid(
            row=r, column=1, sticky="w")
        r += 1
        rb = ttk.Radiobutton(izq, text="Girada segun las calles", variable=self.lam_orientacion, value="auto")
        rb.grid(row=r, column=1, sticky="w")
        Ayuda(rb, "Las laminas se giran para seguir la direccion principal del proyecto: menos laminas cuando "
                  "las calles van en diagonal. El norte se indica en cada lamina.")
        r += 1
        for texto, var, ayuda in (("Traslape (m):", self.lam_traslape, "Metros que se repiten entre laminas vecinas."),
                                  ("Prefijo:", self.lam_prefijo, "Las laminas se llaman prefijo + numero: D-01, D-02"),
                                  ("Primer numero:", self.lam_inicio, "Numero de la primera lamina.")):
            ttk.Label(izq, text=texto).grid(row=r, column=0, sticky="w", pady=2)
            e = ttk.Entry(izq, textvariable=var, width=8)
            e.grid(row=r, column=1, sticky="w")
            Ayuda(e, ayuda)
            r += 1
        c = ttk.Checkbutton(izq, text="Numerar las areas lamina por lamina", variable=self.lam_numerar)
        c.grid(row=r, column=0, columnspan=2, sticky="w", pady=(4, 0))
        Ayuda(c, "VD-1, VD-2... siguen el orden de las laminas, asi en cada lamina los numeros van seguidos.")
        r += 1
        ttk.Checkbutton(izq, text="Hacer PDF de vista previa de las laminas", variable=self.lam_pdf).grid(
            row=r, column=0, columnspan=2, sticky="w")
        der = ttk.LabelFrame(cuerpo, text="Datos del membrete", padding=8)
        der.pack(side="left", fill="both", expand=True)
        der.columnconfigure(1, weight=1)
        for i, (clave, titulo) in enumerate(lammod.CAMPOS_MEMBRETE):
            ttk.Label(der, text=titulo + ":").grid(row=i, column=0, sticky="nw", pady=2)
            if clave == "proyecto":
                w = tk.Text(der, height=3, wrap="word", font=("Segoe UI", 9))
                w.insert("1.0", self.membrete.get(clave, ""))
                w.grid(row=i, column=1, sticky="we", pady=2)
                self.var_membrete[clave] = w
            else:
                v = tk.StringVar(value=self.membrete.get(clave, ""))
                ttk.Entry(der, textvariable=v).grid(row=i, column=1, sticky="we", pady=2)
                self.var_membrete[clave] = v
        bot = ttk.Frame(der)
        bot.grid(row=len(lammod.CAMPOS_MEMBRETE), column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(bot, text="Guardar como predeterminado", command=self._guardar_membrete).pack(side="left")
        ttk.Button(bot, text="Restaurar datos de PETRO", command=self._restaurar_membrete).pack(side="left", padx=6)
        self._siguiente(f, 3, "procesar").pack(anchor="e", pady=8)
        return f

    def _pestana_proceso(self, nb):
        f = ttk.Frame(nb, padding=8)
        self._intro(f, "Paso 4: procesar",
                    "Revise el plan de abajo y pulse PROCESAR. Si marco revisar antes de exportar, al terminar se "
                    "abre la pestana 5 para ver el resultado sobre la ortofoto y corregirlo.").pack(fill="x")
        botones = ttk.Frame(f)
        botones.pack(fill="x", pady=6)
        self.btn = ttk.Button(botones, text="PROCESAR", command=self._procesar, style="Grande.TButton")
        self.btn.pack(side="left")
        opc = ttk.Frame(botones)
        opc.pack(side="left", padx=10)
        ttk.Checkbutton(opc, text="Revisar y corregir en pantalla antes de exportar",
                        variable=self.revisar_antes).pack(anchor="w")
        ttk.Checkbutton(opc, text="Guardar cada corrida en una subcarpeta nueva (con fecha y hora)",
                        variable=self.carpeta_por_corrida).pack(anchor="w")
        c = ttk.Checkbutton(opc, text="Verificar carteles al exportar (etiquetas repetidas, areas encimadas)",
                            variable=self.verificar)
        c.pack(anchor="w")
        Ayuda(c, "Despues de exportar se lee el DXF y se compara cada cartel con su area. Lo que no cuadra "
                 "queda en resumen.md y en revision_carteles.csv.")
        der = ttk.Frame(botones)
        der.pack(side="right")
        self.barra = ttk.Progressbar(der, mode="indeterminate", length=240)
        self.barra.pack(anchor="e")
        self.lbl_paso = ttk.Label(der, text="", style="Paso.TLabel")
        self.lbl_paso.pack(anchor="e")
        self.plan = tk.Label(f, justify="left", anchor="w", bg="#fafafa", relief="groove", padx=8, pady=4)
        self.plan.pack(fill="x")
        res = ttk.LabelFrame(f, text="Resultados", padding=4)
        res.pack(fill="x", pady=6)
        for texto, archivo in (("Abrir carpeta de resultados", None), ("DXF", "resultado.dxf"),
                               ("Metrado (Excel)", "metrado.xlsx"), ("Laminas (PDF)", "laminas_vista_previa.pdf"),
                               ("Vista", "vista.png"), ("Resumen", "resumen.md")):
            ttk.Button(res, text=texto, command=lambda a=archivo: self._abrir_salida(a)).pack(side="left", padx=3)
        self.log = tk.Text(f, wrap="word", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, pady=6)
        self._escribir("1) Elija los puntos (y la ortofoto si la tiene).\n"
                       "2) Revise en 'Codigos y capas' que se usa y como.\n"
                       "3) Ajuste laminas y membrete.\n"
                       "4) Procesar. Resultados: resultado.dxf, metrado.xlsx, laminas_vista_previa.pdf, vista.png, "
                       "resumen.md\n")
        return f

    def _pestana_herramientas(self, nb):
        f = ttk.Frame(nb, padding=12)
        self._intro(f, "Herramientas",
                    "Revisar un plano ya dibujado (por ejemplo uno hecho a mano o el resultado corregido en "
                    "AutoCAD): suma los metrados segun los carteles y avisa los que no coinciden con el dibujo."
                    ).pack(fill="x", pady=(0, 8))
        fila = ttk.Frame(f)
        fila.pack(fill="x")
        self.var_revisar = tk.StringVar()
        ttk.Label(fila, text="Plano DXF:").pack(side="left")
        ttk.Entry(fila, textvariable=self.var_revisar, width=80).pack(side="left", padx=4, fill="x", expand=True)
        ttk.Button(fila, text="Examinar...", command=lambda: self.var_revisar.set(
            filedialog.askopenfilename(filetypes=[("DXF", "*.dxf")]) or self.var_revisar.get())).pack(side="left")
        self.btn_revisar = ttk.Button(fila, text="Revisar plano", command=self._revisar_plano)
        self.btn_revisar.pack(side="left", padx=6)
        ttk.Label(f, text="El informe (resumen.md y CSV) queda en una carpeta 'analisis' junto al plano.",
                  foreground=GRIS).pack(anchor="w", pady=4)
        t = tk.Text(f, wrap="word", font=("Consolas", 10), height=24)
        t.insert("1.0", GUIA)
        t.config(state="disabled")
        t.pack(fill="both", expand=True, pady=8)
        return f

    # ---------- estado y ayudas ----------
    def _faltantes(self):
        falta = []
        if not self.var["puntos"].get():
            falta.append("elegir los puntos (paso 1)")
        if not self.var["salida"].get():
            falta.append("elegir la carpeta de resultados (paso 1)")
        if self.var["orto"].get():
            if self.calce.get() == "dxf" and not self.var["calce_dxf"].get():
                falta.append("elegir el plano DXF del calce")
            if self.calce.get() == "control" and not self.var["control"].get():
                falta.append("elegir los puntos de control")
        return falta

    def _actualizar_estado(self):
        for clave, marca in getattr(self, "_marcas", {}).items():
            ruta = self.var[clave].get()
            if not ruta:
                marca.config(text="")
            elif Path(ruta).exists() or clave == "salida":
                marca.config(text="✔", foreground=VERDE)
            else:
                marca.config(text="✖", foreground="#c62828")
        falta = self._faltantes()
        if falta:
            self.barra_estado.config(text="✖ Falta: " + "; ".join(falta), fg="#c62828")
        else:
            extra = []
            if not self.var["plano_base"].get():
                extra.append("sin plano base: no habra lineas de corte (CL)")
            if not self.var["orto"].get():
                extra.append("sin ortofoto: une solo por geometria")
            self.barra_estado.config(text="✔ Listo para procesar" + (" (" + "; ".join(extra) + ")" if extra else ""),
                                     fg=VERDE)
        if hasattr(self, "plan"):
            self.plan.config(text=self._texto_plan())

    def _texto_plan(self):
        n = sum(1 for c in self.codigos.values() if c.activo)
        lin = ["Lo que va a pasar:",
               f"  • Leer {Path(self.var['puntos'].get()).name or '(sin puntos)'}"
               + (f" ({sum(self.conteo.values())} puntos)" if self.conteo else "") + f" y unir {n} codigos activos",
               "  • " + ("Pegar las veredas al limite de propiedad del plano base"
                         if self.var["plano_base"].get() else "Sin plano base"),
               "  • " + ("Seguir los bordes de la ortofoto" if self.var["orto"].get() else "Sin ortofoto"),
               "  • Carteles " + ("con area y perimetro (PETRO)" if self.cartel.get() == "petro" else "simples")
               + (" y lineas de corte CL" if self.corte_lineal.get() else "")]
        if self.lam_activar.get():
            lin.append(f"  • Laminas A1 a 1:{self.escala.get()} con membrete, prefijo {self.lam_prefijo.get()}"
                       + (", giradas segun las calles" if self.lam_orientacion.get() == "auto" else ", norte arriba"))
        lin.append("  • Guardar en " + (self.var["salida"].get() or "(sin carpeta)")
                   + (" \\ corrida_fecha_hora" if self.carpeta_por_corrida.get() else ""))
        return "\n".join(lin)

    def _al_cambiar(self):
        self._actualizar_estado()

    # ---------- membrete ----------
    def _leer_membrete(self):
        datos = {}
        for clave, w in self.var_membrete.items():
            datos[clave] = w.get("1.0", "end").strip() if isinstance(w, tk.Text) else w.get().strip()
        return datos

    def _guardar_membrete(self):
        lammod.guardar_membrete(self._leer_membrete())
        messagebox.showinfo("Membrete", "Datos guardados. Se usaran la proxima vez que abra el programa.")

    def _restaurar_membrete(self):
        for clave, w in self.var_membrete.items():
            valor = lammod.MEMBRETE_PETRO.get(clave, "")
            if isinstance(w, tk.Text):
                w.delete("1.0", "end")
                w.insert("1.0", valor)
            else:
                w.set(valor)

    def _conf_laminas(self):
        if not self.lam_activar.get():
            return None
        return lammod.ConfLaminas(
            activar=True, escala=self._numero(self.escala.get(), 500), traslape=self._numero(self.lam_traslape.get(), 5),
            orientacion=self.lam_orientacion.get(), prefijo=self.lam_prefijo.get(),
            inicio=int(self._numero(self.lam_inicio.get(), 1)), numerar_por_lamina=self.lam_numerar.get(),
            membrete=self._leer_membrete(), vista_pdf=self.lam_pdf.get())

    @staticmethod
    def _numero(texto, defecto):
        try:
            return float(str(texto).replace(",", ".")) if str(texto).strip() else defecto
        except ValueError:
            raise ValueError(f"'{texto}' no es un numero") from None

    # ---------- tabla de codigos ----------
    def _llenar_tabla(self):
        self.tabla.delete(*self.tabla.get_children())
        cods = set(self.codigos) | set(self.conteo)
        for cod in sorted(cods, key=lambda c: (-self.conteo.get(c, 0), c)):
            c = self.codigos.get(cod)
            n = self.conteo.get(cod, "")
            if c is None:
                sug = self.sugerencias.get(cod)
                valores = ["", cod, n, f"(sin configurar{'; parece ' + sug if sug else ''})", "", "", "", "", "", "",
                           "", "", "", ""]
                self.tabla.insert("", "end", iid=cod, values=valores, tags=("nuevo",))
                continue
            valores = ["si" if c.activo else "no", cod, n, c.nombre, c.tipo, c.capa, c.capa_area, c.prefijo,
                       c.separacion_max if c.tipo != "punto" else "", c.ancho_min if c.tipo == "franja" else "",
                       c.ancho_max if c.tipo == "franja" else "", " ".join(c.referencia),
                       c.ancho_defecto or "",
                       "si" if cod in self.apagar else ""]
            self.tabla.insert("", "end", iid=cod, values=valores, tags=() if c.activo else ("off",))
        if self.alias:
            grupos = collections.defaultdict(list)
            for a, d in sorted(self.alias.items()):
                grupos[d].append(a)
            self.lbl_alias.config(text="Alias (se unen con otro codigo): " +
                                  "; ".join(f"{', '.join(v)} -> {k}" for k, v in sorted(grupos.items())))
        self._mostrar_banner()
        if hasattr(self, "plan"):
            self.plan.config(text=self._texto_plan())

    def _mostrar_banner(self):
        if self.sugerencias:
            self.lbl_banner.config(text="Posibles errores de escritura en los codigos: " + ", ".join(
                f"{k} -> {v} ({self.conteo.get(k, 0)} pts)" for k, v in sorted(self.sugerencias.items()))
                + ". Si es correcto, agreguelos como alias para que se unan con su codigo.")
            self.banner.pack(fill="x", pady=(0, 4), before=self.botones_codigos)
        else:
            self.banner.pack_forget()

    def _agregar_sugerencias(self):
        if not self.sugerencias:
            return
        texto = "\n".join(f"{k} -> {v}" for k, v in sorted(self.sugerencias.items()))
        if not messagebox.askyesno("Agregar alias", f"Se agregaran estos alias:\n\n{texto}\n\nContinuar?"):
            return
        self.alias.update(self.sugerencias)
        self._recontar()

    def _recontar(self):
        self.conteo = collections.Counter()
        for cod, n in self.conteo_crudo.items():
            self.conteo[self.alias.get(cod, cod)] += n
        sin_conf = [c for c in self.conteo if c not in self.codigos]
        self.sugerencias = topografia.sugerir_alias(sin_conf, set(self.codigos) | set(self.alias)) if sin_conf else {}
        self._llenar_tabla()

    def _clic_tabla(self, ev):
        if self.tabla.identify("region", ev.x, ev.y) != "cell":
            return
        fila, col = self.tabla.identify_row(ev.y), self.tabla.identify_column(ev.x)
        clave = COLUMNAS[int(col[1:]) - 1][0]
        if clave == "usar" and fila in self.codigos:
            self.codigos[fila].activo = not self.codigos[fila].activo
            self._llenar_tabla()
        elif clave == "apagar" and fila in self.codigos:
            self.apagar ^= {fila}
            self._llenar_tabla()

    def _editar_celda(self, ev):
        fila, col = self.tabla.identify_row(ev.y), self.tabla.identify_column(ev.x)
        if not fila:
            return
        clave, _, _, editable = COLUMNAS[int(col[1:]) - 1]
        if not editable:
            return
        if fila not in self.codigos:
            if not messagebox.askyesno("Codigo nuevo", f"Configurar el codigo {fila}?"):
                return
            self.codigos[fila] = unir.Codigo(capa=f"TOPO-{fila}", tipo="punto", nombre=fila)
            self.sugerencias.pop(fila, None)
            self._llenar_tabla()
        x, y, w, h = self.tabla.bbox(fila, col)
        conf = self.codigos[fila]
        actual = getattr(conf, clave)
        if clave == "referencia":
            actual = " ".join(actual)
        if clave == "tipo":
            ed = ttk.Combobox(self.tabla, values=unir.TIPOS, state="readonly")
        else:
            ed = ttk.Entry(self.tabla)
        ed.place(x=x, y=y, width=max(w, 120), height=h)
        ed.insert(0, str(actual)) if clave != "tipo" else ed.set(actual)
        ed.focus_set()

        def guardar(_=None):
            valor = ed.get().strip()
            ed.destroy()
            try:
                if clave in ("separacion_max", "ancho_min", "ancho_max", "ancho_defecto"):
                    valor = float(valor.replace(",", "."))
                elif clave == "referencia":
                    valor = [v.upper() for v in valor.replace(",", " ").split()]
                setattr(conf, clave, valor)
            except ValueError:
                messagebox.showerror("Valor invalido", f"'{valor}' no es un numero")
            self._llenar_tabla()

        ed.bind("<Return>", guardar)
        ed.bind("<FocusOut>", guardar)
        ed.bind("<Escape>", lambda _: (ed.destroy()))
        if clave == "tipo":
            ed.bind("<<ComboboxSelected>>", guardar)

    def _marcar_todos(self, valor):
        for c in self.codigos.values():
            c.activo = valor
        self._llenar_tabla()

    def _abrir_config(self):
        r = filedialog.askopenfilename(filetypes=[("Configuracion", "*.json")])
        if r:
            self.codigos, self.alias = unir.cargar_codigos(r)
            self.ruta_codigos = r
            self._recontar()

    def _guardar_config(self):
        r = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Configuracion", "*.json")])
        if r:
            unir.guardar_codigos(r, self.codigos, self.alias, "Configuracion guardada desde la ventana")
            self.ruta_codigos = r

    def _contar_puntos(self):
        ruta = self.var["puntos"].get()
        if not ruta or ruta.lower().endswith(".dxf"):
            return
        try:
            pts = topografia.leer(ruta)
        except Exception as e:  # noqa: BLE001 - se muestra al usuario
            messagebox.showerror("No se pudo leer", str(e))
            return
        self.conteo_crudo = collections.Counter(p.codigo for p in pts)
        self._recontar()
        self._escribir(f"{len(pts)} puntos leidos de {Path(ruta).name}; {len(self.conteo)} codigos distintos.\n")
        if self.sugerencias:
            self._escribir("Posibles errores de escritura: " +
                           ", ".join(f"{k} -> {v}?" for k, v in sorted(self.sugerencias.items())) +
                           " (ver pestana 2)\n")

    # ---------- proceso ----------
    def _opciones(self):
        if not self.var["puntos"].get():
            raise ValueError("Falta elegir el archivo de puntos")
        if not self.var["salida"].get():
            raise ValueError("Falta elegir la carpeta de resultados")
        orto = self.var["orto"].get()
        modo = self.calce.get()
        if orto and modo == "dxf" and not self.var["calce_dxf"].get():
            raise ValueError("Elija el plano DXF del cual tomar el calce")
        if orto and modo == "control" and not self.var["control"].get():
            raise ValueError("Elija el archivo de puntos de control")
        capas_apagadas = set()
        for cod in self.apagar:
            c = self.codigos.get(cod)
            if c:
                capas_apagadas |= {c.capa, c.capa_area, "PT-" + cod} - {""}
        return Opciones(
            puntos=self.var["puntos"].get(), salida=self.var["salida"].get(), orto=orto,
            calce_dxf=self.var["calce_dxf"].get() if modo == "dxf" else "",
            control=self.var["control"].get() if modo == "control" else "",
            calce_auto=self.calce_auto.get(), radio_calce=self._numero(self.radio.get(), 3),
            resolucion=self._numero(self.resolucion.get(), 0) / 100,
            plantilla=self.var["plantilla"].get(), capas_apagadas=capas_apagadas, completar=self.completar.get(),
            plano_base=self.var["plano_base"].get(), veredas_foto=self.veredas_foto.get(), muestras=self.muestras.get(),
            capas_limite=tuple(c.strip() for c in self.capas_limite.get().split(",") if c.strip()) or ("FACHADA",),
            codigos_editados=(copy.deepcopy(self.codigos), dict(self.alias)),
            escala=self._numero(self.escala.get(), 500), cartel=self.cartel.get(),
            corte_lineal=self.corte_lineal.get(), laminas=self._conf_laminas(),
            carpeta_por_corrida=self.carpeta_por_corrida.get(), numero_separa=self.numero_separa.get(),
            codigos_control=self.codigos_control.get(), verificar=self.verificar.get())

    def _procesar(self):
        try:
            op = self._opciones()
        except ValueError as e:
            messagebox.showwarning("Faltan datos", str(e))
            return
        self.nb.select(3)
        self.btn.config(state="disabled")
        self.barra.start(12)
        self.lbl_paso.config(text="Procesando...")
        self._escribir("\n=== Procesando... ===\n")
        self._op_actual = op

        revisar = self.revisar_antes.get()

        def trabajo():
            try:
                avisar = lambda t: self.cola.put(str(t) + "\n")  # noqa: E731
                if revisar:
                    calc = calcular(op, avisar=avisar)
                    self.cola.put(("CALCULO", calc))
                else:
                    procesar(op, avisar=avisar)
                    self.cola.put(("FIN", None))
            except Exception as e:  # noqa: BLE001 - se muestra al usuario
                self.cola.put(traceback.format_exc())
                self.cola.put(("FIN", str(e)))

        threading.Thread(target=trabajo, daemon=True).start()

    def _leer_cola(self):
        try:
            while True:
                m = self.cola.get_nowait()
                if isinstance(m, tuple) and m[0] == "CALCULO":
                    self.barra.stop()
                    self.btn.config(state="normal")
                    self.lbl_paso.config(text="Listo para revisar")
                    self.ultima_salida = m[1].op.salida
                    self._escribir("\n=== Listo para revisar: pestana 5. Revisar y corregir ===\n")
                    self.visor.cargar(m[1])
                    self.nb.select(4)
                elif isinstance(m, tuple):
                    self.barra.stop()
                    self.visor.btn_exportar.config(state="normal")
                    self.btn.config(state="normal")
                    if getattr(self, "_op_actual", None) is not None:
                        self.ultima_salida = self._op_actual.salida
                    if m[1]:
                        self.lbl_paso.config(text="Error")
                        messagebox.showerror("Error", m[1])
                    else:
                        self.lbl_paso.config(text="✔ Terminado")
                        self._escribir("\n=== Listo ===\n")
                        if messagebox.askyesno("Listo", "Proceso terminado. Abrir la carpeta de resultados?"):
                            self._abrir_salida()
                else:
                    self._escribir(m)
                    linea = m.strip().splitlines()[-1] if m.strip() else ""
                    if linea and not linea.startswith(("Traceback", " ")):
                        self.lbl_paso.config(text=linea[:70])
        except queue.Empty:
            pass
        self.after(150, self._leer_cola)

    def _exportar(self, calc):
        """Escribe el DXF y el metrado del calculo revisado (con las correcciones hechas a mano)."""
        self.visor.btn_exportar.config(state="disabled")
        self.barra.start(12)
        self.lbl_paso.config(text="Exportando...")
        self._escribir("\n=== Exportando lo revisado... ===\n")
        self._op_actual = calc.op

        def trabajo():
            try:
                exportar_calculo(calc, avisar=lambda t: self.cola.put(str(t) + "\n"))
                self.cola.put(("FIN", None))
            except Exception as e:  # noqa: BLE001 - se muestra al usuario
                self.cola.put(traceback.format_exc())
                self.cola.put(("FIN", str(e)))

        threading.Thread(target=trabajo, daemon=True).start()

    def _revisar_plano(self):
        ruta = self.var_revisar.get()
        if not ruta or not Path(ruta).exists():
            messagebox.showwarning("Revisar plano", "Elija un plano DXF")
            return
        self.btn_revisar.config(state="disabled")
        self.nb.select(3)
        self.barra.start(12)
        self._escribir(f"\n=== Revisando {Path(ruta).name}... ===\n")
        salida = str(Path(ruta).with_name("analisis"))
        self._op_actual = None

        def trabajo():
            try:
                from . import revisar_plano

                revisar_plano.analizar(ruta, salida, avisar=lambda t: self.cola.put(str(t) + "\n"))
                self.ultima_salida = salida
                self.cola.put(f"Informe en {salida}\n")
                self.cola.put(("FIN", None))
            except Exception as e:  # noqa: BLE001 - se muestra al usuario
                self.cola.put(traceback.format_exc())
                self.cola.put(("FIN", str(e)))
            finally:
                self.after(0, lambda: self.btn_revisar.config(state="normal"))

        threading.Thread(target=trabajo, daemon=True).start()

    def _escribir(self, texto):
        self.log.insert("end", texto)
        self.log.see("end")

    def _abrir_salida(self, archivo=None):
        ruta = self.ultima_salida or self.var["salida"].get()
        if not ruta or not Path(ruta).exists():
            ruta = self.var["salida"].get()
        if not ruta or not Path(ruta).exists():
            messagebox.showinfo("Resultados", "Todavia no hay resultados en la carpeta elegida.")
            return
        if archivo:
            if not (Path(ruta) / archivo).exists():
                messagebox.showinfo("Resultados", f"No se encontro {archivo} en {ruta}.")
                return
            ruta = str(Path(ruta) / archivo)
        if sys.platform.startswith("win"):
            os.startfile(ruta)  # noqa: S606 - abre el explorador de Windows
        else:
            subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", ruta])


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
