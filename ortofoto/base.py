"""Plano base del proyecto (DXF de Civil 3D/AutoCAD): limites de propiedad y manzanas.

Las lineas de las capas de limite (por defecto FACHADA) son el borde interior
de las veredas, y sus contornos cerrados son las manzanas: ningun area puede
entrar a una manzana y ninguna union puede juntar puntos de manzanas distintas.
"""
from dataclasses import dataclass, field

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

CAPAS_LIMITE = ("FACHADA",)
DIST_MANZANA = 8.0  # m: un punto mas lejos que esto de todo limite no se asigna a ninguna manzana


@dataclass
class PlanoBase:
    ruta: str = ""
    limites: list = field(default_factory=list)  # LineString de cada limite (cerrado o abierto)
    manzanas: list = field(default_factory=list)  # Polygon de los limites cerrados
    _arbol: object = None
    _union: object = None

    @property
    def vacio(self):
        return not self.limites

    def arbol(self):
        if self._arbol is None and self.limites:
            self._arbol = STRtree(self.limites)
        return self._arbol

    def union_manzanas(self):
        if self._union is None:
            self._union = unary_union(self.manzanas) if self.manzanas else Polygon()
        return self._union

    def limite_de(self, x, y, dist=DIST_MANZANA):
        """Indice del limite mas cercano a (x, y) o -1 si esta a mas de `dist` m."""
        arbol = self.arbol()
        if arbol is None:
            return -1
        p = Point(x, y)
        k = int(arbol.nearest(p))
        return k if self.limites[k].distance(p) <= dist else -1

    def recortar(self, pol):
        """Quita de un area todo lo que entre a una manzana (lotes)."""
        if not self.manzanas:
            return pol
        resto = pol.difference(self.union_manzanas())
        if isinstance(resto, MultiPolygon):
            resto = max(resto.geoms, key=lambda g: g.area)
        return resto


def leer_base(ruta, capas=CAPAS_LIMITE):
    from ezdxf import recover

    doc, _ = recover.readfile(ruta)
    capas = {c.upper() for c in capas}
    base = PlanoBase(ruta=str(ruta))
    for e in doc.modelspace().query("LWPOLYLINE POLYLINE LINE"):
        if e.dxf.layer.upper() not in capas:
            continue
        if e.dxftype() == "LINE":
            pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            cerrada = False
        elif e.dxftype() == "LWPOLYLINE":
            pts = [(x, y) for x, y in e.get_points("xy")]
            cerrada = e.closed
        else:
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
            cerrada = e.is_closed
        if len(pts) < 2:
            continue
        if len(pts) > 2 and np.hypot(*np.subtract(pts[0], pts[-1])) < 0.01:
            cerrada, pts = True, pts[:-1]
        if cerrada and len(pts) >= 3:
            pol = Polygon(pts).buffer(0)
            if isinstance(pol, MultiPolygon):
                pol = max(pol.geoms, key=lambda g: g.area)
            if pol.area > 1.0:
                base.manzanas.append(pol)
            base.limites.append(LineString(list(pts) + [pts[0]]))
        else:
            base.limites.append(LineString(pts))
    return base
