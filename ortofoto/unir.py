"""Union de puntos topograficos en polilineas, guiada por los bordes de la ortofoto.

Idea: los puntos de un mismo codigo (VER, SAR, LP...) se levantan a lo largo
de un borde fisico. Se generan uniones candidatas entre vecinos cercanos y a
cada una se le da un costo = longitud x (1 + ALFA x (1 - apoyo)), donde
`apoyo` mide si en la foto hay un borde que corre paralelo a la union y que
no lo atraviesa otro borde. Luego se aceptan las uniones mas baratas cuidando
que cada punto tenga como maximo 2 vecinos, que no se crucen y que no haya
giros en horquilla. Una segunda pasada une extremos sueltos alineados (por
ejemplo bajo un arbol) y los marca para revisar.
"""
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree

ALFA = 4.0
APOYO_MIN = 0.12
ANGULO_MIN = 60.0  # grados; angulo interior minimo entre dos uniones de un punto


@dataclass
class Codigo:
    capa: str
    tipo: str = "linea"  # linea | contorno | punto
    separacion_max: float = 15.0
    color: int = 7
    tipo_linea: str = "Continuous"


def cargar_codigos(ruta):
    """Lee codigos.json -> ({codigo: Codigo}, {alias: codigo})."""
    import json

    datos = json.loads(open(ruta, encoding="utf-8").read())["codigos"]
    codigos, alias = {}, {}
    for cod, v in datos.items():
        if "alias" in v:
            alias[cod.upper()] = v["alias"].upper()
        else:
            codigos[cod.upper()] = Codigo(**v)
    return codigos, alias


@dataclass
class Union:
    i: int
    j: int
    largo: float
    apoyo: float
    costo: float
    revisar: bool = False


@dataclass
class Resultado:
    codigo: str
    puntos: list
    uniones: list = field(default_factory=list)
    cadenas: list = field(default_factory=list)  # listas de indices; cerradas si inicio == fin


def apoyo_imagen(orto, a, b, paso=0.1):
    """0..1: que tanto la foto muestra un borde a lo largo del segmento a-b."""
    v = b - a
    largo = float(np.hypot(*v))
    if largo < 1e-6:
        return 0.0
    t = np.linspace(0.12, 0.88, max(5, int(largo / paso)))
    pts = a + np.outer(t, v)
    mag, ge, gn = orto.muestrear_bordes(pts[:, 0], pts[:, 1])
    u = v / largo
    paralelo = np.minimum(np.abs(ge * -u[1] + gn * u[0]), 1.0)  # borde que acompana al segmento
    cruce = np.minimum(np.abs(ge * u[0] + gn * u[1]), 1.0)  # borde que lo atraviesa
    return float(np.clip(np.median(paralelo) - 0.5 * np.percentile(cruce, 95), 0.0, 1.0))


def _segmentos_cruzan(p1, p2, q1, q2):
    def orient(a, b, c):
        return np.sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))

    return (orient(p1, p2, q1) * orient(p1, p2, q2) < 0) and (orient(q1, q2, p1) * orient(q1, q2, p2) < 0)


def _angulo(p, a, b):
    """Angulo en p entre p->a y p->b, en grados."""
    u, v = a - p, b - p
    c = np.dot(u, v) / (np.hypot(*u) * np.hypot(*v) + 1e-12)
    return float(np.degrees(np.arccos(np.clip(c, -1, 1))))


class _Grafo:
    def __init__(self, xy):
        self.xy = xy
        self.vec = [[] for _ in range(len(xy))]
        self.padre = list(range(len(xy)))
        self.aceptadas = []

    def raiz(self, i):
        while self.padre[i] != i:
            self.padre[i] = self.padre[self.padre[i]]
            i = self.padre[i]
        return i

    def admite(self, i, j, permitir_cierre):
        if len(self.vec[i]) >= 2 or len(self.vec[j]) >= 2:
            return False
        if self.raiz(i) == self.raiz(j) and not (permitir_cierre and len(self.vec[i]) == 1 and len(self.vec[j]) == 1):
            return False
        for p, q in ((i, j), (j, i)):
            for k in self.vec[p]:
                if _angulo(self.xy[p], self.xy[k], self.xy[q]) < ANGULO_MIN:
                    return False
        a, b = self.xy[i], self.xy[j]
        for u in self.aceptadas:
            if len({u.i, u.j, i, j}) == 4 and _segmentos_cruzan(a, b, self.xy[u.i], self.xy[u.j]):
                return False
        return True

    def agregar(self, u):
        self.vec[u.i].append(u.j)
        self.vec[u.j].append(u.i)
        self.padre[self.raiz(u.i)] = self.raiz(u.j)
        self.aceptadas.append(u)

    def cadenas(self):
        vistos, res = set(), []
        extremos = [i for i in range(len(self.xy)) if len(self.vec[i]) == 1]
        for inicio in extremos + [i for i in range(len(self.xy)) if len(self.vec[i]) == 2]:
            if inicio in vistos:
                continue
            cad, prev, act = [inicio], None, inicio
            vistos.add(inicio)
            while True:
                sig = [k for k in self.vec[act] if k != prev]
                if not sig:
                    break
                if sig[0] == inicio:  # contorno cerrado
                    cad.append(inicio)
                    break
                if sig[0] in vistos:
                    break
                prev, act = act, sig[0]
                cad.append(act)
                vistos.add(act)
            if len(cad) > 1:
                res.append(cad)
        return res


def unir_codigo(codigo, puntos, conf, orto=None, vecinos=6):
    res = Resultado(codigo, puntos)
    if conf.tipo == "punto" or len(puntos) < 2:
        return res
    xy = np.array([(p.e, p.n) for p in puntos], float)
    arbol = cKDTree(xy)
    k = min(vecinos + 1, len(xy))
    dist, idx = arbol.query(xy, k=k)
    candidatos = {}
    for i in range(len(xy)):
        for d, j in zip(np.atleast_1d(dist[i])[1:], np.atleast_1d(idx[i])[1:]):
            if d <= conf.separacion_max and d > 1e-3:
                candidatos[(min(i, j), max(i, j))] = d
    uniones = []
    for (i, j), d in candidatos.items():
        s = apoyo_imagen(orto, xy[i], xy[j]) if orto is not None else 0.5
        uniones.append(Union(i, j, d, s, d * (1 + ALFA * (1 - s))))
    uniones.sort(key=lambda u: u.costo)

    g = _Grafo(xy)
    cierre = conf.tipo == "contorno"
    for u in uniones:
        if orto is not None and u.apoyo < APOYO_MIN:
            continue
        if g.admite(u.i, u.j, cierre):
            g.agregar(u)

    # Segunda pasada: extremos sueltos que siguen la direccion de su tramo
    if orto is not None:
        for u in sorted(uniones, key=lambda u: u.largo):
            if u.apoyo >= APOYO_MIN or u.largo > 0.6 * conf.separacion_max:
                continue
            if len(g.vec[u.i]) != 1 or len(g.vec[u.j]) != 1:
                continue
            ok = all(
                180 - _angulo(xy[p], xy[g.vec[p][0]], xy[q]) < 25 for p, q in ((u.i, u.j), (u.j, u.i))
            )
            if ok and g.admite(u.i, u.j, cierre):
                u.revisar = True
                g.agregar(u)

    res.uniones = g.aceptadas
    res.cadenas = g.cadenas()
    return res


def unir_todo(puntos, codigos, orto=None, solo=None, alias=None):
    alias = alias or {}
    grupos = {}
    for p in puntos:
        grupos.setdefault(alias.get(p.codigo, p.codigo), []).append(p)
    resultados = []
    for cod, pts in sorted(grupos.items()):
        if solo and cod not in solo:
            continue
        conf = codigos.get(cod)
        if conf is None:
            continue
        resultados.append(unir_codigo(cod, pts, conf, orto))
    return resultados, {c: len(v) for c, v in grupos.items() if c not in codigos}
