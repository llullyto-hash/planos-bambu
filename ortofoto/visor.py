"""Pestana de resultados: ver sobre la ortofoto lo que se va a exportar y corregirlo por tramos.

- Rueda del mouse: zoom donde esta el cursor. Boton derecho (o central) arrastrando: mover la vista.
- Clic en un area (o en la lista): seleccionarla. Arrastrar un vertice del area seleccionada: moverlo
  (se pega a los puntos topograficos cercanos).
- Cortar tramo: dos clics a traves del area; queda partida en pedazos (luego Borrar el que sobra).
- Dibujar area: clic en cada esquina (se pega a los puntos), doble clic o Enter para cerrar.
- Supr: borrar el area seleccionada. Ctrl+Z: deshacer. Esc: cancelar la herramienta.
Nada se escribe hasta apretar EXPORTAR.
"""
import copy
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.collections import PolyCollection
from matplotlib.figure import Figure
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import split

from . import areas

COLORES = {"VER": "#e4572e", "ALC": "#2e86de", "PTA": "#8e44ad", "CNTA": "#16a085", "MAR": "#f39c12",
           "ACC": "#d35400", "CV": "#95a5a6"}
COLOR_PUNTO = {"VER": "#ff9f1c", "CSH": "#3a86ff", "ALC": "#00d2ff", "OCHV": "#3a86ff", "LP": "#3a86ff"}
IMAN_PX = 12  # pixeles: un clic a menos de esto de un punto topografico se pega a el
VERTICE_PX = 9  # pixeles: distancia para agarrar un vertice
MAX_PX_FONDO = 2600  # pixeles de la foto de fondo en la vista general
ETIQUETAS_VISTA = 45.0  # m: con la vista mas angosta que esto se muestran los numeros de punto
AYUDA = {
    "sel": "Clic: seleccionar | arrastrar vertice: moverlo | doble clic en un borde: agregar vertice | "
           "Shift+clic en vertice: quitarlo | rueda: zoom | boton derecho: mover vista | Supr: borrar | Ctrl+Z",
    "cortar": "CORTAR TRAMO: clic a un lado del area y clic al otro lado (la linea la parte). Esc: cancelar",
    "dibujar": "DIBUJAR AREA: clic en cada esquina (se pega a los puntos). Doble clic o Enter: cerrar. "
               "Esc: cancelar",
}


class Visor(ttk.Frame):
    def __init__(self, master, al_exportar):
        super().__init__(master, padding=4)
        self.al_exportar = al_exportar
        self.calc = None
        self.modo = "sel"
        self.sel = None  # Area seleccionada
        self.deshacer_pila = []
        self.temp = []  # vertices de la herramienta en curso
        self.arrastre = None  # (indice de vertice) o ("pan", x, y, xlim, ylim)
        self._fondo_pendiente = None
        self._armar()

    # ---------- interfaz ----------
    def _armar(self):
        barra = ttk.Frame(self)
        barra.pack(fill="x")
        self.btn_modo = {}
        for clave, texto in (("sel", "Seleccionar / mover vertices"), ("cortar", "Cortar tramo"),
                             ("dibujar", "Dibujar area")):
            b = ttk.Button(barra, text=texto, command=lambda c=clave: self._herramienta(c))
            b.pack(side="left", padx=2)
            self.btn_modo[clave] = b
        ttk.Label(barra, text="  codigo:").pack(side="left")
        self.cod_nuevo = ttk.Combobox(barra, width=8, state="readonly")
        self.cod_nuevo.pack(side="left")
        ttk.Button(barra, text="Borrar (Supr)", command=self._borrar).pack(side="left", padx=(10, 2))
        ttk.Button(barra, text="Revisado", command=self._marcar_revisado).pack(side="left", padx=2)
        ttk.Button(barra, text="Deshacer (Ctrl+Z)", command=self._deshacer).pack(side="left", padx=2)
        ttk.Button(barra, text="Ver todo", command=self._ver_todo).pack(side="left", padx=2)
        self.btn_exportar = tk.Button(barra, text="  EXPORTAR DXF Y METRADO  ", bg="#2e7d32", fg="white",
                                      font=("Segoe UI", 10, "bold"), command=self._exportar)
        self.btn_exportar.pack(side="right", padx=4)
        self.lbl_ayuda = ttk.Label(self, text=AYUDA["sel"], foreground="#555")
        self.lbl_ayuda.pack(fill="x", pady=(2, 2))

        cuerpo = ttk.PanedWindow(self, orient="horizontal")
        cuerpo.pack(fill="both", expand=True)
        mapa = ttk.Frame(cuerpo)
        lado = ttk.Frame(cuerpo, padding=(6, 0, 0, 0))
        cuerpo.add(mapa, weight=4)
        cuerpo.add(lado, weight=1)

        self.fig = Figure(figsize=(8, 6), dpi=100)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_axis_off()
        self.canvas = FigureCanvasTkAgg(self.fig, master=mapa)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.lbl_coord = ttk.Label(mapa, text="", foreground="#555")
        self.lbl_coord.pack(fill="x")
        c = self.canvas
        c.mpl_connect("scroll_event", self._rueda)
        c.mpl_connect("button_press_event", self._presionar)
        c.mpl_connect("motion_notify_event", self._mover)
        c.mpl_connect("button_release_event", self._soltar)
        w = c.get_tk_widget()
        for tecla, fn in (("<Delete>", lambda e: self._borrar()), ("<Control-z>", lambda e: self._deshacer()),
                          ("<Escape>", lambda e: self._herramienta("sel")), ("<Return>", lambda e: self._cerrar_dibujo())):
            w.bind(tecla, fn)
        w.bind("<Enter>", lambda e: w.focus_set())

        filtro = ttk.Frame(lado)
        filtro.pack(fill="x")
        ttk.Label(filtro, text="Ver:").pack(side="left")
        self.filtro_cod = ttk.Combobox(filtro, width=10, state="readonly")
        self.filtro_cod.pack(side="left", padx=4)
        self.filtro_cod.bind("<<ComboboxSelected>>", lambda e: self._llenar_lista())
        self.solo_revisar = tk.BooleanVar(value=False)
        ttk.Checkbutton(filtro, text="solo a revisar", variable=self.solo_revisar,
                        command=self._llenar_lista).pack(side="left")
        cols = (("etq", "Area", 80), ("m2", "m2", 60), ("ml", "Largo", 55), ("rev", "Revisar", 55))
        marco = ttk.Frame(lado)
        marco.pack(fill="both", expand=True, pady=4)
        self.lista = ttk.Treeview(marco, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for k, t, wd in cols:
            self.lista.heading(k, text=t)
            self.lista.column(k, width=wd, anchor="center")
        sb = ttk.Scrollbar(marco, orient="vertical", command=self.lista.yview)
        self.lista.configure(yscrollcommand=sb.set)
        self.lista.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lista.tag_configure("rev", foreground="#c62828")
        self.lista.bind("<<TreeviewSelect>>", self._elegir_en_lista)
        self.lbl_nota = ttk.Label(lado, text="", wraplength=260, justify="left", foreground="#333")
        self.lbl_nota.pack(fill="x")
        self.lbl_resumen = ttk.Label(lado, text="", justify="left", font=("Consolas", 9))
        self.lbl_resumen.pack(fill="x", pady=(6, 0))

    # ---------- datos ----------
    def cargar(self, calc):
        """Muestra un Calculo (de __main__.calcular)."""
        self.calc = calc
        self.sel = None
        self.deshacer_pila = []
        self.temp = []
        met = calc.met
        self.puntos_xy = np.array([(p.e, p.n) for p in calc.puntos]) if calc.puntos else np.zeros((0, 2))
        self.arbol = cKDTree(self.puntos_xy) if len(self.puntos_xy) else None
        cods = sorted({a.codigo for a in met.areas})
        self.filtro_cod["values"] = ["Todos"] + cods
        self.filtro_cod.set("Todos")
        con_area = sorted(k for k, c in calc.codigos.items() if c.capa_area and c.tipo in ("franja", "contorno"))
        self.cod_nuevo["values"] = con_area
        self.cod_nuevo.set("VER" if "VER" in con_area else (con_area[0] if con_area else ""))
        self.ax.clear()
        self.ax.set_axis_off()
        self.ax.set_aspect("equal")
        xs, ys = self.puntos_xy[:, 0], self.puntos_xy[:, 1]
        self.extension = (xs.min() - 10, ys.min() - 10, xs.max() + 10, ys.max() + 10)
        self.img = None
        self._fondo_general()
        self.coleccion = PolyCollection([], zorder=2)
        self.ax.add_collection(self.coleccion)
        self.marco_sel = PolyCollection([], facecolors="none", edgecolors="#ffff00", linewidths=2.2, zorder=4)
        self.ax.add_collection(self.marco_sel)
        self.vertices, = self.ax.plot([], [], "o", ms=5, mfc="#ffff00", mec="black", zorder=5)
        self.linea_temp, = self.ax.plot([], [], "-o", color="#00ff66", ms=4, lw=1.5, zorder=6)
        self._dibujar_puntos()
        self.textos_pt = []
        self.textos_area = []
        self._redibujar_areas()
        self._ver_todo()
        self._llenar_lista()

    def _fondo_general(self):
        orto = self.calc.orto
        if orto is None:
            return
        h, w = orto.rgb.shape[:2]
        paso = max(1, int(np.ceil(max(h, w) / MAX_PX_FONDO)))
        self.fondo_paso = paso
        e0, n0 = orto.a_terreno(0, 0)
        e1, n1 = orto.a_terreno(w, h)
        self.img = self.ax.imshow(orto.rgb[::paso, ::paso], extent=(e0, e1, n1, n0), zorder=0,
                                  interpolation="bilinear")
        self.fondo_general = (orto.rgb[::paso, ::paso], (e0, e1, n1, n0))

    def _dibujar_puntos(self):
        cods = [p.codigo for p in self.calc.puntos]
        alias = self.calc.alias
        colores = [COLOR_PUNTO.get(alias.get(c, c), "#bbbbbb") for c in cods]
        tam = [9 if alias.get(c, c) in COLOR_PUNTO else 3 for c in cods]
        self.ax.scatter(self.puntos_xy[:, 0], self.puntos_xy[:, 1], s=tam, c=colores, edgecolors="black",
                        linewidths=0.2, zorder=3)
        rev = [(x, y) for x, y, m in self.calc.met.puntos_revisar]
        if rev:
            r = np.array(rev)
            self.ax.plot(r[:, 0], r[:, 1], "x", color="#ff00ff", ms=8, mew=2, zorder=3)

    def _indice(self, a):
        """Posicion del area en la lista (por identidad: dos pedazos pueden ser iguales)."""
        return next((i for i, x in enumerate(self.calc.met.areas) if x is a), -1)

    def _color(self, a):
        return COLORES.get(a.codigo, "#f1c40f")

    def _redibujar_areas(self):
        met = self.calc.met
        polys, caras, bordes = [], [], []
        for a in met.areas:
            polys.append(np.array(a.poligono.exterior.coords))
            col = self._color(a)
            caras.append(col + "55")
            bordes.append("#ff1744" if a.revisar else col)
        self.coleccion.set_verts(polys)
        self.coleccion.set_facecolors(caras)
        self.coleccion.set_edgecolors(bordes)
        self.coleccion.set_linewidths([1.6 if a.revisar else 0.9 for a in met.areas])
        self._marcar_sel()
        self._resumen()
        self._etiquetas()
        self.canvas.draw_idle()

    def _marcar_sel(self):
        if self.sel is not None and self._indice(self.sel) >= 0:
            c = np.array(self.sel.poligono.exterior.coords)
            self.marco_sel.set_verts([c])
            self.vertices.set_data(c[:-1, 0], c[:-1, 1])
            a = self.sel
            nota = f"{a.etiqueta}  ({a.conf.nombre or a.codigo})\nArea {a.area:.2f} m2"
            if a.largo:
                nota += f"   largo {a.largo:.2f} m"
            if a.nota:
                nota += f"\n{a.nota}"
            if a.revisar:
                nota += "\n(a revisar)"
            self.lbl_nota.config(text=nota)
        else:
            self.sel = None
            self.marco_sel.set_verts([])
            self.vertices.set_data([], [])
            self.lbl_nota.config(text="")

    def _resumen(self):
        tot = {}
        for a in self.calc.met.areas:
            k = a.conf.prefijo or a.codigo
            n, s, rv = tot.get(k, (0, 0.0, 0))
            tot[k] = (n + 1, s + a.area, rv + a.revisar)
        filas = [f"{k:<6}{n:>4} areas {s:>10,.2f} m2" + (f"  ({rv} a revisar)" if rv else "")
                 for k, (n, s, rv) in sorted(tot.items())]
        self.lbl_resumen.config(text="METRADO\n" + "\n".join(filas))

    def _llenar_lista(self):
        self.lista.delete(*self.lista.get_children())
        cod = self.filtro_cod.get()
        orden = sorted(enumerate(self.calc.met.areas), key=lambda ka: (ka[1].codigo, ka[1].etiqueta))
        for k, a in orden:
            if cod not in ("", "Todos") and a.codigo != cod:
                continue
            if self.solo_revisar.get() and not a.revisar:
                continue
            self.lista.insert("", "end", iid=str(k), tags=("rev",) if a.revisar else (),
                              values=(a.etiqueta, f"{a.area:.2f}", f"{a.largo:.2f}" if a.largo else "",
                                      "si" if a.revisar else ""))

    # ---------- vista ----------
    def _ver_todo(self):
        x0, y0, x1, y1 = self.extension
        self._vista(x0, y0, x1, y1)

    def _vista(self, x0, y0, x1, y1):
        w, h = self.canvas.get_tk_widget().winfo_width() or 800, self.canvas.get_tk_widget().winfo_height() or 600
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
        if dx / dy < w / h:
            dx = dy * w / h
        else:
            dy = dx * h / w
        self.ax.set_xlim(cx - dx / 2, cx + dx / 2)
        self.ax.set_ylim(cy - dy / 2, cy + dy / 2)
        self._vista_cambio()

    def _vista_cambio(self):
        if self._fondo_pendiente:
            self.after_cancel(self._fondo_pendiente)
        self._fondo_pendiente = self.after(200, self._fondo_detalle)
        self.canvas.draw_idle()

    def _fondo_detalle(self):
        """Al acercarse, la foto se vuelve a leer con mas detalle solo en la zona visible."""
        self._fondo_pendiente = None
        self._etiquetas()
        orto = self.calc.orto if self.calc else None
        if orto is None or self.img is None:
            self.canvas.draw_idle()
            return
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        ancho_px = max(self.canvas.get_tk_widget().winfo_width(), 400)
        paso = max(1, int((x1 - x0) / orto.tam_pixel / ancho_px))
        if paso >= self.fondo_paso:
            rgb, ext = self.fondo_general
            self.img.set_data(rgb)
            self.img.set_extent(ext)
        else:
            try:
                sub = orto.recortar(x0, y0, x1, y1)
            except ValueError:
                self.canvas.draw_idle()
                return
            h, w = sub.rgb.shape[:2]
            e0, n0 = sub.a_terreno(0, 0)
            e1, n1 = sub.a_terreno(w, h)
            self.img.set_data(sub.rgb[::paso, ::paso])
            self.img.set_extent((e0, e1, n1, n0))
        self.canvas.draw_idle()

    def _etiquetas(self):
        for t in self.textos_pt + self.textos_area:
            t.remove()
        self.textos_pt, self.textos_area = [], []
        if self.calc is None:
            return
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        vista = Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        visibles = [a for a in self.calc.met.areas if a.poligono.intersects(vista)]
        if len(visibles) <= 60:
            for a in visibles:
                x, y = areas.punto_etiqueta(a.poligono)
                self.textos_area.append(self.ax.text(x, y, f"{a.etiqueta}\n{a.area:.2f} m2", fontsize=7,
                                                     ha="center", va="center", color="white", zorder=7,
                                                     bbox=dict(boxstyle="round,pad=0.15", fc="#00000088", ec="none")))
        if x1 - x0 <= ETIQUETAS_VISTA:
            for p in self.calc.puntos:
                if x0 <= p.e <= x1 and y0 <= p.n <= y1 and len(self.textos_pt) < 400:
                    self.textos_pt.append(self.ax.text(p.e + 0.08, p.n + 0.08, f"{p.num} {p.desc}", fontsize=6,
                                                       color="white", zorder=6))

    def _rueda(self, ev):
        if ev.xdata is None:
            return
        f = 1 / 1.3 if ev.button == "up" else 1.3
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        self.ax.set_xlim(ev.xdata - (ev.xdata - x0) * f, ev.xdata + (x1 - ev.xdata) * f)
        self.ax.set_ylim(ev.ydata - (ev.ydata - y0) * f, ev.ydata + (y1 - ev.ydata) * f)
        self._vista_cambio()

    def _m_por_px(self):
        x0, x1 = self.ax.get_xlim()
        return (x1 - x0) / max(self.canvas.get_tk_widget().winfo_width(), 1)

    def _iman(self, x, y):
        """El clic se pega al punto topografico mas cercano si esta a menos de IMAN_PX pixeles."""
        if self.arbol is None:
            return x, y
        d, i = self.arbol.query((x, y))
        if d <= IMAN_PX * self._m_por_px():
            return tuple(self.puntos_xy[i])
        return x, y

    # ---------- raton ----------
    def _presionar(self, ev):
        if self.calc is None or ev.xdata is None:
            return
        if ev.button in (2, 3):
            self.arrastre = ("pan", ev.x, ev.y, self.ax.get_xlim(), self.ax.get_ylim())
            return
        if self.modo == "dibujar":
            if ev.dblclick:
                self._cerrar_dibujo()
                return
            self.temp.append(self._iman(ev.xdata, ev.ydata))
            self._mostrar_temp()
            return
        if self.modo == "cortar":
            self.temp.append((ev.xdata, ev.ydata))
            self._mostrar_temp()
            if len(self.temp) == 2:
                self._cortar(*self.temp)
                self.temp = []
                self._mostrar_temp()
            return
        # seleccionar, agarrar / quitar un vertice o agregar uno en un borde
        if self.sel is not None:
            c = np.array(self.sel.poligono.exterior.coords)[:-1]
            pix = self.ax.transData.transform(c)
            d = np.hypot(pix[:, 0] - ev.x, pix[:, 1] - ev.y)
            k = int(np.argmin(d))
            if d[k] <= VERTICE_PX:
                if ev.key == "shift":
                    if len(c) > 3:
                        self._guardar_estado()
                        self._reemplazar(self.sel, [Polygon(np.delete(c, k, axis=0))], "vertice quitado a mano")
                    return
                self.arrastre = ("vertice", k, c.copy())
                return
            if ev.dblclick:
                borde = self._borde_cercano(c, ev)
                if borde is not None:
                    k, punto = borde
                    self._guardar_estado()
                    self._reemplazar(self.sel, [Polygon(np.insert(c, k + 1, punto, axis=0))],
                                     "vertice agregado a mano")
                    return
        p = Point(ev.xdata, ev.ydata)
        bajo = [a for a in self.calc.met.areas if a.poligono.contains(p)]
        self._seleccionar(min(bajo, key=lambda a: a.area) if bajo else None)

    def _mover(self, ev):
        if ev.xdata is not None:
            self.lbl_coord.config(text=f"E {ev.xdata:,.2f}   N {ev.ydata:,.2f}")
        if not self.arrastre:
            if self.modo in ("dibujar", "cortar") and self.temp and ev.xdata is not None:
                self._mostrar_temp((ev.xdata, ev.ydata))
            return
        if self.arrastre[0] == "pan":
            _, x, y, xl, yl = self.arrastre
            m = (xl[1] - xl[0]) / max(self.canvas.get_tk_widget().winfo_width(), 1)
            dx, dy = (ev.x - x) * m, (ev.y - y) * m
            self.ax.set_xlim(xl[0] - dx, xl[1] - dx)
            self.ax.set_ylim(yl[0] - dy, yl[1] - dy)
            self.canvas.draw_idle()
            return
        if self.arrastre[0] == "vertice" and ev.xdata is not None:
            _, k, c = self.arrastre
            c = c.copy()
            c[k] = self._iman(ev.xdata, ev.ydata)
            cerrado = np.vstack([c, c[:1]])
            self.marco_sel.set_verts([cerrado])
            self.vertices.set_data(c[:, 0], c[:, 1])
            self.arrastre = ("vertice", k, self.arrastre[2], c)
            self.canvas.draw_idle()

    def _borde_cercano(self, c, ev):
        """(indice del lado, punto sobre el lado) si el clic esta a menos de VERTICE_PX de un borde."""
        p = np.array([ev.xdata, ev.ydata])
        tol = VERTICE_PX * self._m_por_px()
        mejor = None
        for k in range(len(c)):
            a, b = c[k], c[(k + 1) % len(c)]
            v = b - a
            t = float(np.clip((p - a) @ v / max(v @ v, 1e-12), 0, 1))
            q = a + v * t
            dist = float(np.hypot(*(p - q)))
            if dist <= tol and (mejor is None or dist < mejor[0]):
                mejor = (dist, k, q)
        return None if mejor is None else (mejor[1], mejor[2])

    def _soltar(self, ev):
        a = self.arrastre
        self.arrastre = None
        if not a:
            return
        if a[0] == "pan":
            self._vista_cambio()
            return
        if a[0] == "vertice" and len(a) == 4:
            pol = Polygon(a[3])
            if not pol.is_valid:
                pol = pol.buffer(0)
                if isinstance(pol, MultiPolygon):
                    pol = max(pol.geoms, key=lambda g: g.area)
            if pol.is_empty or pol.area < areas.AREA_MIN:
                self._redibujar_areas()
                return
            self._guardar_estado()
            self._reemplazar(self.sel, [pol], "vertices movidos a mano")

    # ---------- herramientas ----------
    def _herramienta(self, modo):
        self.modo = modo
        self.temp = []
        self._mostrar_temp()
        self.lbl_ayuda.config(text=AYUDA[modo])
        for k, b in self.btn_modo.items():
            b.state(["pressed"] if k == modo else ["!pressed"])

    def _mostrar_temp(self, extra=None):
        pts = list(self.temp) + ([extra] if extra else [])
        if pts:
            c = np.array(pts)
            self.linea_temp.set_data(c[:, 0], c[:, 1])
        else:
            self.linea_temp.set_data([], [])
        self.canvas.draw_idle()

    def _guardar_estado(self):
        met = self.calc.met
        self.deshacer_pila.append([copy.copy(a) for a in met.areas])
        self.deshacer_pila = self.deshacer_pila[-60:]

    def _deshacer(self):
        if not self.deshacer_pila:
            return
        self.calc.met.areas = self.deshacer_pila.pop()
        self.sel = None
        self._despues_de_cambio()

    def _despues_de_cambio(self):
        areas._numerar(self.calc.met)
        self._redibujar_areas()
        self._llenar_lista()

    def _nueva(self, base, pol, nota):
        a = copy.copy(base)
        a.poligono = pol
        a.largo = base.largo * pol.area / max(base.area, 1e-6) if base.largo else 0.0
        a.ancho = pol.area / a.largo if a.largo else base.ancho
        a.origen = "manual"
        a.revisar = False
        a.nota = nota
        return a

    def _reemplazar(self, viejo, poligonos, nota):
        met = self.calc.met
        i = self._indice(viejo)
        nuevas = [self._nueva(viejo, g, nota) for g in poligonos]
        met.areas[i:i + 1] = nuevas
        self.sel = nuevas[0] if len(nuevas) == 1 else None
        self._despues_de_cambio()

    def _borrar(self):
        if self.sel is None:
            return
        self._guardar_estado()
        del self.calc.met.areas[self._indice(self.sel)]
        self.sel = None
        self._despues_de_cambio()

    def _marcar_revisado(self):
        if self.sel is None:
            return
        self._guardar_estado()
        self.sel.revisar = not self.sel.revisar
        self._redibujar_areas()
        self._llenar_lista()

    def _cortar(self, p, q):
        p, q = np.array(p), np.array(q)
        v = q - p
        n = np.hypot(*v)
        if n < 1e-6:
            return
        v = v / n
        linea = LineString([tuple(p - v * 2.0), tuple(q + v * 2.0)])  # un poco mas larga que los clics
        objetivo = [self.sel] if self.sel is not None and self.sel.poligono.intersects(linea) else \
            [a for a in self.calc.met.areas if a.poligono.intersects(linea)]
        cortadas = False
        for a in objetivo:
            piezas = [g for g in split(a.poligono, linea).geoms if isinstance(g, Polygon) and g.area >= 0.01]
            if len(piezas) > 1:
                if not cortadas:
                    self._guardar_estado()
                cortadas = True
                self._reemplazar(a, piezas, "cortada a mano")
        if not cortadas:
            messagebox.showinfo("Cortar tramo", "La linea no atraviesa ningun area de lado a lado.")
            return
        self.lbl_ayuda.config(text="Area partida. Clic en el pedazo que sobra y Borrar (Supr). "
                                   "Otro corte: dos clics mas. Esc: terminar.")

    def _cerrar_dibujo(self):
        if self.modo != "dibujar" or len(self.temp) < 3:
            return
        pol = Polygon(self.temp)
        if not pol.is_valid:
            pol = pol.buffer(0)
            if isinstance(pol, MultiPolygon):
                pol = max(pol.geoms, key=lambda g: g.area)
        self.temp = []
        self._mostrar_temp()
        cod = self.cod_nuevo.get()
        conf = self.calc.codigos.get(cod)
        if conf is None or pol.is_empty or pol.area < areas.AREA_MIN:
            return
        self._guardar_estado()
        r = pol.minimum_rotated_rectangle
        lados = sorted(np.hypot(*np.diff(np.array(r.exterior.coords), axis=0).T))
        largo = float(lados[-1]) if len(lados) else 0.0
        nueva = areas.Area(cod, conf, pol, "manual", pol.area / max(largo, 1e-6), largo, False, nota="dibujada a mano")
        self.calc.met.areas.append(nueva)
        self.sel = nueva
        self._despues_de_cambio()

    # ---------- lista ----------
    def _seleccionar(self, a, centrar=False):
        self.sel = a
        self._marcar_sel()
        if a is not None:
            iid = str(self._indice(a))
            if self.lista.exists(iid) and self.lista.selection() != (iid,):
                self.lista.selection_set(iid)
                self.lista.see(iid)
            if centrar:
                x0, y0, x1, y1 = a.poligono.bounds
                self._vista(x0 - 8, y0 - 8, x1 + 8, y1 + 8)
        self.canvas.draw_idle()

    def _elegir_en_lista(self, _ev):
        s = self.lista.selection()
        if not s:
            return
        a = self.calc.met.areas[int(s[0])]
        if a is not self.sel:
            self._seleccionar(a, centrar=True)

    # ---------- exportar ----------
    def _exportar(self):
        if self.calc is None:
            return
        areas._numerar(self.calc.met)
        self.al_exportar(self.calc)
