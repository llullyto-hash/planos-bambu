"""Ventana del programa: topografia (+ ortofoto) -> polilineas, areas con achurado y metrado.

python -m ortofoto.gui
"""
import collections
import copy
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import topografia, unir
from .__main__ import CODIGOS_DEFECTO, Opciones, procesar

TITULO = "Topografia -> polilineas, areas y metrados"
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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        try:
            from ._version import VERSION
        except ImportError:
            VERSION = "desarrollo"
        self.title(f"{TITULO}  (version {VERSION})")
        self.geometry("1280x820")
        self.minsize(1000, 640)
        self.cola = queue.Queue()
        self.codigos, self.alias = unir.cargar_codigos(CODIGOS_DEFECTO)
        self.ruta_codigos = str(CODIGOS_DEFECTO)
        self.conteo = {}
        self.apagar = set()
        self.var = {k: tk.StringVar() for k in ("puntos", "orto", "calce_dxf", "control", "plantilla", "salida",
                                                "plano_base")}
        self.capas_limite = tk.StringVar(value="FACHADA")
        self.var["salida"].set(str(Path.home() / "Documents" / "resultado_topografia"))
        self.calce = tk.StringVar(value="foto")
        self.calce_auto = tk.BooleanVar(value=True)
        self.completar = tk.BooleanVar(value=True)
        self.veredas_foto = tk.BooleanVar(value=False)
        self.radio = tk.StringVar(value="3")
        self.resolucion = tk.StringVar(value="0")
        self._armar()
        self._llenar_tabla()
        self.after(150, self._leer_cola)

    # ---------- interfaz ----------
    def _armar(self):
        estilo = ttk.Style(self)
        if "vista" in estilo.theme_names():
            estilo.theme_use("vista")
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        nb.add(self._pestana_archivos(nb), text="1. Archivos")
        nb.add(self._pestana_codigos(nb), text="2. Codigos y capas")
        nb.add(self._pestana_proceso(nb), text="3. Procesar")
        self.nb = nb

    def _fila_archivo(self, padre, fila, texto, clave, tipos, carpeta=False, ayuda=""):
        ttk.Label(padre, text=texto).grid(row=fila, column=0, sticky="w", pady=3)
        ttk.Entry(padre, textvariable=self.var[clave], width=90).grid(row=fila, column=1, sticky="we", padx=4)

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
        if ayuda:
            ttk.Label(padre, text=ayuda, foreground="#666").grid(row=fila + 1, column=1, sticky="w", padx=4)

    def _pestana_archivos(self, nb):
        f = ttk.Frame(nb, padding=12)
        f.columnconfigure(1, weight=1)
        self._fila_archivo(f, 0, "Puntos topograficos *", "puntos",
                           [("Puntos PNEZD", "*.csv *.txt"), ("DXF con puntos COGO", "*.dxf"), ("Todos", "*.*")],
                           ayuda="Civil 3D: Points > Export Points > PNEZD (comma delimited)")
        base = ttk.LabelFrame(f, text="Plano del proyecto (recomendado)", padding=8)
        base.grid(row=10, column=0, columnspan=3, sticky="we", pady=8)
        base.columnconfigure(1, weight=1)
        self._fila_archivo(base, 0, "Plano base (DXF)", "plano_base", [("DXF", "*.dxf")],
                           ayuda="Con lotes y fachadas: las veredas se pegan al limite de propiedad, nunca entran a "
                                 "los lotes ni se unen con la otra cuadra. El resultado se agrega sobre una copia.")
        fila_c = ttk.Frame(base)
        fila_c.grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Label(fila_c, text="Capas del limite de propiedad:").pack(side="left")
        ttk.Entry(fila_c, textvariable=self.capas_limite, width=40).pack(side="left", padx=4)
        ttk.Label(fila_c, text="(separadas por coma, p.ej. FACHADA, LINEA DE LOTE)", foreground="#666").pack(side="left")
        self._fila_archivo(f, 2, "Ortofoto (opcional)", "orto",
                           [("Imagenes", "*.tif *.tiff *.jpg *.jpeg *.png *.ecw"), ("Todos", "*.*")],
                           ayuda="Sin foto, une solo por geometria. Con foto, sigue los bordes reales.")
        cal = ttk.LabelFrame(f, text="Calce de la ortofoto", padding=8)
        cal.grid(row=4, column=0, columnspan=3, sticky="we", pady=8)
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
        ttk.Label(fila2, text="Con fotos muy grandes y poca memoria use 6 a 8.", foreground="#666").pack(side="left")
        ttk.Checkbutton(cal, text="Con foto: unir tambien lo que la foto no confirma (queda en la capa REVISAR UNION)",
                        variable=self.completar).grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(cal, text="Dibujar las veredas con la forma del concreto visible en la foto "
                                  "(EN PRUEBA; requiere el plano del proyecto)",
                        variable=self.veredas_foto).grid(row=8, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._fila_archivo(f, 5, "Plantilla de capas (opcional)", "plantilla", [("DXF", "*.dxf")],
                           ayuda="DXF del cual copiar colores, tipos de linea y grosores (p.ej. el plano PETRO)")
        self._fila_archivo(f, 7, "Carpeta de resultados *", "salida", None, carpeta=True)
        return f

    def _pestana_codigos(self, nb):
        f = ttk.Frame(nb, padding=8)
        arriba = ttk.Frame(f)
        arriba.pack(fill="x")
        ttk.Label(arriba, text="Doble clic en una celda para editarla. Clic en 'Usar' o 'Apagar' para cambiarlo. "
                               "Los codigos sin usar no se unen ni generan areas.").pack(side="left")
        botones = ttk.Frame(f)
        botones.pack(fill="x", pady=4)
        ttk.Button(botones, text="Abrir configuracion...", command=self._abrir_config).pack(side="left")
        ttk.Button(botones, text="Guardar configuracion como...", command=self._guardar_config).pack(side="left", padx=4)
        ttk.Button(botones, text="Usar todos", command=lambda: self._marcar_todos(True)).pack(side="left", padx=4)
        ttk.Button(botones, text="Ninguno", command=lambda: self._marcar_todos(False)).pack(side="left")
        ttk.Button(botones, text="Ayuda: tipos", command=lambda: messagebox.showinfo("Tipos", AYUDA_TIPOS)
                   ).pack(side="left", padx=4)
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
        self.lbl_alias = ttk.Label(f, foreground="#666", wraplength=1200, justify="left")
        self.lbl_alias.pack(fill="x", pady=4)
        return f

    def _pestana_proceso(self, nb):
        f = ttk.Frame(nb, padding=8)
        botones = ttk.Frame(f)
        botones.pack(fill="x")
        self.btn = ttk.Button(botones, text="PROCESAR", command=self._procesar)
        self.btn.pack(side="left")
        ttk.Button(botones, text="Abrir carpeta de resultados", command=self._abrir_salida).pack(side="left", padx=6)
        self.barra = ttk.Progressbar(botones, mode="indeterminate", length=240)
        self.barra.pack(side="left", padx=6)
        self.log = tk.Text(f, wrap="word", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, pady=6)
        self._escribir("1) Elija los puntos (y la ortofoto si la tiene).\n"
                       "2) Revise en 'Codigos y capas' que se usa y como.\n"
                       "3) Procesar. Resultados: resultado.dxf, metrado.xlsx, vista.png, resumen.md\n")
        return f

    # ---------- tabla de codigos ----------
    def _llenar_tabla(self):
        self.tabla.delete(*self.tabla.get_children())
        cods = set(self.codigos) | set(self.conteo)
        for cod in sorted(cods, key=lambda c: (-self.conteo.get(c, 0), c)):
            c = self.codigos.get(cod)
            n = self.conteo.get(cod, "")
            if c is None:
                valores = ["", cod, n, "(sin configurar)", "", "", "", "", "", "", "", "", "", ""]
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
            self._llenar_tabla()

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
        self.conteo = collections.Counter(self.alias.get(p.codigo, p.codigo) for p in pts)
        self._llenar_tabla()
        self._escribir(f"{len(pts)} puntos leidos de {Path(ruta).name}; {len(self.conteo)} codigos distintos.\n")

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
            calce_auto=self.calce_auto.get(), radio_calce=float(self.radio.get().replace(",", ".") or 3),
            resolucion=float(self.resolucion.get().replace(",", ".") or 0) / 100,
            plantilla=self.var["plantilla"].get(), capas_apagadas=capas_apagadas, completar=self.completar.get(),
            plano_base=self.var["plano_base"].get(), veredas_foto=self.veredas_foto.get(),
            capas_limite=tuple(c.strip() for c in self.capas_limite.get().split(",") if c.strip()) or ("FACHADA",),
            codigos_editados=(copy.deepcopy(self.codigos), dict(self.alias)))

    def _procesar(self):
        try:
            op = self._opciones()
        except ValueError as e:
            messagebox.showwarning("Faltan datos", str(e))
            return
        self.nb.select(2)
        self.btn.config(state="disabled")
        self.barra.start(12)
        self._escribir("\n=== Procesando... ===\n")

        def trabajo():
            try:
                procesar(op, avisar=lambda t: self.cola.put(str(t) + "\n"))
                self.cola.put(("FIN", None))
            except Exception as e:  # noqa: BLE001 - se muestra al usuario
                self.cola.put(traceback.format_exc())
                self.cola.put(("FIN", str(e)))

        threading.Thread(target=trabajo, daemon=True).start()

    def _leer_cola(self):
        try:
            while True:
                m = self.cola.get_nowait()
                if isinstance(m, tuple):
                    self.barra.stop()
                    self.btn.config(state="normal")
                    if m[1]:
                        messagebox.showerror("Error", m[1])
                    else:
                        self._escribir("\n=== Listo ===\n")
                        if messagebox.askyesno("Listo", "Proceso terminado. Abrir la carpeta de resultados?"):
                            self._abrir_salida()
                else:
                    self._escribir(m)
        except queue.Empty:
            pass
        self.after(150, self._leer_cola)

    def _escribir(self, texto):
        self.log.insert("end", texto)
        self.log.see("end")

    def _abrir_salida(self):
        ruta = self.var["salida"].get()
        if not ruta or not Path(ruta).exists():
            return
        if sys.platform.startswith("win"):
            os.startfile(ruta)  # noqa: S606 - abre el explorador de Windows
        else:
            subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", ruta])


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
