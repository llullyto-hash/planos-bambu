"""Carteles de area y perimetro con el formato del plano PETRO.

Cada cartel es: un recuadro (capa LETRERO), el texto en Arial negrita centrado de 2.5 mm en papel
(capa TEXTO EN MARTILLO) y una flecha (LEADER) que apunta al area:

    VD - 35
    AREA= 8.14 M2
    PERIM= 12.40 M

En PETRO los carteles estan en el espacio papel; aqui van en el modelo a la escala de la lamina
(2.5 mm a 1:500 = 1.25 m), asi no se desfasan si se mueve la ventana. El cartel se coloca fuera
del area, hacia la calle, sin tapar otros carteles ni flechas; si el area es grande y el cartel
cabe adentro, va adentro sin flecha.
"""
import math
from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Point, box
from shapely.ops import nearest_points

from .estilo import ESTILO_TEXTO

CAPA_RECUADRO = "LETRERO"
CAPA_TEXTO = "TEXTO EN MARTILLO"
CAPA_ENCIMADO = "REVISAR CARTEL ENCIMADO"  # no se plotea: marca los carteles que hay que mover a mano
COLOR_FLECHA = 140
ESTILO_COTA = "CARTEL PETRO"
ALTO_MM = 2.5  # alto del texto en la lamina
ANCHO_LETRA = 0.68  # ancho medio de una letra Arial negrita, en altos de texto
MARGEN_MM = 1.5
RENGLON_MM = 2.9
DISTANCIAS_MM = (6, 10, 15, 21, 28, 36, 46, 58)
DIRECCIONES = 16
CELDA = 25.0  # m, indice de cajas y flechas ya colocadas


def texto_petro(etiqueta, filas):
    """MTEXT con el mismo formato de PETRO. filas: [("AREA=", "8.14 M2"), ("PERIM=", "12.40 M")]."""
    s = "\\pxqc;{\\fArial|b1|i0|c0|p34;\\C256;\\c0;" + etiqueta
    for k, (nombre, valor) in enumerate(filas):
        alto = "\\H0.91667x;" if k == 0 else ""
        s += (f"\\P\\fCalibri|b1|i0|c0|p34;{alto}\\C256;{nombre}\\fArial|b1|i0|c0|p34;\\H1.09091x;\\C256;\\c0; "
              f"\\fCalibri|b1|i0|c0|p34;\\H0.91667x;\\C256;{valor}")
    return s + "}"


def filas_area(area, perimetro, largo=None):
    filas = []
    if largo:
        filas.append(("LONG=", f"{largo:,.2f} M"))
    filas.append(("AREA=", f"{area:,.2f} M2"))
    if perimetro is not None:
        filas.append(("PERIM=", f"{perimetro:,.2f} M"))
    return filas


def punto_interior(pol):
    """Punto bien adentro del area (polo de inaccesibilidad), para la punta de la flecha."""
    try:
        from shapely.ops import polylabel

        p = polylabel(pol, tolerance=0.05)
        if pol.contains(p):
            return p
    except Exception:  # noqa: BLE001 - poligonos raros
        pass
    return pol.representative_point()


@dataclass
class Colocado:
    caja: object
    centro: tuple
    punta: tuple
    enganche: tuple
    flecha: bool
    encimado: bool


class Colocador:
    """Ubica carteles evitando que se tapen entre si, con las flechas sin cruzarse."""

    def __init__(self, escala=500, obstaculos=(), manzanas=None, angulo=0.0):
        self.s = escala / 1000.0  # m de modelo por mm de lamina
        self.angulo = angulo  # rad: carteles alineados con laminas giradas
        self.indice = {}
        self.obstaculos = [self._a_local(g) for g in obstaculos]
        if manzanas is not None:
            manzanas = self._a_local(manzanas)
        self._arbol = None
        if self.obstaculos:
            from shapely import STRtree

            self._arbol = STRtree(self.obstaculos)
        self.manzanas = manzanas
        self.encimados = 0

    # --- giro: se trabaja en coordenadas de la lamina y se devuelve al modelo ---
    def _a_local(self, g):
        return affinity.rotate(g, -self.angulo, origin=(0, 0), use_radians=True) if self.angulo else g

    def _a_modelo(self, g):
        return affinity.rotate(g, self.angulo, origin=(0, 0), use_radians=True) if self.angulo else g

    def _pt_modelo(self, xy):
        if not self.angulo:
            return tuple(xy)
        c, s_ = math.cos(self.angulo), math.sin(self.angulo)
        return (xy[0] * c - xy[1] * s_, xy[0] * s_ + xy[1] * c)

    # --- indice espacial simple por celdas ---
    def _celdas(self, geom):
        x0, y0, x1, y1 = geom.bounds
        for i in range(int(math.floor(x0 / CELDA)), int(math.floor(x1 / CELDA)) + 1):
            for j in range(int(math.floor(y0 / CELDA)), int(math.floor(y1 / CELDA)) + 1):
                yield i, j

    def _agregar(self, geom):
        for c in self._celdas(geom):
            self.indice.setdefault(c, []).append(geom)

    def _choca(self, geom):
        vistos = set()
        for c in self._celdas(geom):
            for g in self.indice.get(c, ()):
                if id(g) in vistos:
                    continue
                vistos.add(id(g))
                if g.intersects(geom):
                    return True
        return False

    def _tapa(self, caja):
        """Fraccion de la caja que tapa areas a demoler."""
        if self._arbol is None:
            return 0.0
        tapado = 0.0
        for k in self._arbol.query(caja):
            tapado += self.obstaculos[int(k)].intersection(caja).area
        return tapado / max(caja.area, 1e-9)

    def tamano(self, lineas):
        """(ancho, alto) del recuadro en m de modelo."""
        n = max(len(t) for t in lineas)
        ancho = (n * ANCHO_LETRA * ALTO_MM + 2 * MARGEN_MM) * self.s
        alto = (len(lineas) * RENGLON_MM + MARGEN_MM) * self.s
        return ancho, alto

    def _preferida(self, punta, geom):
        """Direccion preferida: hacia la calle (lejos de la manzana) o perpendicular al elemento."""
        if self.manzanas is not None and not self.manzanas.is_empty:
            a, _ = nearest_points(self.manzanas, punta)
            v = np.array([punta.x - a.x, punta.y - a.y])
            if np.hypot(*v) > 1e-6:
                return v / np.hypot(*v)
        r = geom.minimum_rotated_rectangle
        c = np.asarray(r.exterior.coords if hasattr(r, "exterior") else r.coords)
        if len(c) >= 3:
            e = c[1] - c[0] if np.hypot(*(c[1] - c[0])) >= np.hypot(*(c[2] - c[1])) else c[2] - c[1]
            if np.hypot(*e) > 1e-9:
                n = np.array([-e[1], e[0]]) / np.hypot(*e)
                return n
        return np.array([0.0, 1.0])

    def colocar(self, geom, lineas, punta=None):
        """Coloca un cartel para `geom` (poligono o linea). Devuelve Colocado (en el modelo)."""
        c = self._colocar(self._a_local(geom), lineas, None if punta is None else self._a_local(punta))
        if not self.angulo:
            return c
        return Colocado(self._a_modelo(c.caja), self._pt_modelo(c.centro), self._pt_modelo(c.punta),
                        self._pt_modelo(c.enganche), c.flecha, c.encimado)

    def _colocar(self, geom, lineas, punta=None):
        ancho, alto = self.tamano(lineas)
        if punta is None:
            punta = punto_interior(geom) if geom.geom_type.endswith("Polygon") else geom.interpolate(0.5, normalized=True)
        px, py = punta.x, punta.y
        # Adentro, sin flecha, si el area es grande y el cartel cabe completo
        if geom.geom_type.endswith("Polygon"):
            caja = box(px - ancho / 2, py - alto / 2, px + ancho / 2, py + alto / 2)
            if geom.buffer(-0.1 * self.s).contains(caja) and not self._choca(caja):
                self._agregar(caja)
                return Colocado(caja, (px, py), (px, py), (px, py), False, False)
        pref = self._preferida(punta, geom)
        mejor, mejor_costo = None, float("inf")
        for k in range(DIRECCIONES):
            ang = 2 * math.pi * k / DIRECCIONES
            u = np.array([math.cos(ang), math.sin(ang)])
            desvio = math.acos(float(np.clip(u @ pref, -1, 1)))
            # distancia del centro de la caja al borde de la caja en la direccion u
            borde = min(ancho / 2 / max(abs(u[0]), 1e-9), alto / 2 / max(abs(u[1]), 1e-9))
            for d_mm in DISTANCIAS_MM:
                d = d_mm * self.s
                cx, cy = px + u[0] * (d + borde), py + u[1] * (d + borde)
                caja = box(cx - ancho / 2, cy - alto / 2, cx + ancho / 2, cy + alto / 2)
                eng = self._enganche(caja, px, py)
                flecha = LineString([(px, py), eng])
                choca = self._choca(caja) or self._choca(flecha)
                costo = d_mm + 12 * desvio + 40 * self._tapa(caja) + (1e4 if choca else 0)
                if costo < mejor_costo:
                    mejor, mejor_costo = (caja, (cx, cy), eng, choca), costo
            if mejor_costo < DISTANCIAS_MM[0] + 1:
                break
        caja, centro, eng, choca = mejor
        if choca:
            self.encimados += 1
        self._agregar(caja)
        self._agregar(LineString([(px, py), eng]))
        return Colocado(caja, centro, (px, py), eng, True, choca)

    @staticmethod
    def _enganche(caja, px, py):
        """Punto medio del lado de la caja que mira hacia la punta (como en PETRO)."""
        x0, y0, x1, y1 = caja.bounds
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy = px - cx, py - cy
        if abs(dy) * (x1 - x0) >= abs(dx) * (y1 - y0):
            return (cx, y0 if dy < 0 else y1)
        return (x0 if dx < 0 else x1, cy)


def preparar_estilo_cota(doc, escala):
    """Estilo de cota para las flechas de los carteles (punta de 2.5 mm en la lamina)."""
    s = escala / 1000.0
    nombre = f"{ESTILO_COTA} 1-{int(escala)}"
    if nombre not in doc.dimstyles:
        ds = doc.dimstyles.new(nombre)
        ds.dxf.dimasz = 2.5 * s
        ds.dxf.dimscale = 1.0
        ds.dxf.dimgap = 0.5 * s
        ds.dxf.dimtxt = ALTO_MM * s
    return nombre


def dibujar(msp, colocado, texto_mtext, lineas, escala, estilo_cota, capa_recuadro=CAPA_RECUADRO,
            capa_texto=CAPA_TEXTO, angulo=0.0):
    """Dibuja recuadro, texto y flecha de un cartel ya colocado."""
    s = escala / 1000.0
    esquinas = list(colocado.caja.exterior.coords)[:-1]
    msp.add_lwpolyline(esquinas, close=True, dxfattribs={"layer": capa_recuadro})
    msp.add_mtext(texto_mtext, dxfattribs={"layer": capa_texto, "style": ESTILO_TEXTO, "char_height": ALTO_MM * s,
                                           "insert": colocado.centro, "attachment_point": 5,
                                           "rotation": math.degrees(angulo)})
    if colocado.encimado:
        msp.add_lwpolyline(esquinas, close=True, dxfattribs={"layer": CAPA_ENCIMADO, "color": 1})
    if colocado.flecha:
        msp.add_leader([colocado.punta, colocado.enganche], dimstyle=estilo_cota,
                       dxfattribs={"layer": capa_texto, "color": COLOR_FLECHA})
