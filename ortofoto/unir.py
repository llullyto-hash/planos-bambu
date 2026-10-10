"""Union de puntos topograficos en polilineas, guiada (opcional) por la ortofoto.

Idea: los puntos de un mismo codigo (VER, CNTA, PTA...) se levantan a lo largo
de bordes fisicos. Se generan uniones candidatas entre vecinos cercanos y a
cada una se le da un costo = longitud x (1 + ALFA x (1 - apoyo)), donde
`apoyo` mide si en la foto hay un borde que corre paralelo a la union (sin
foto vale 0.5 para todas). Luego se aceptan las uniones mas baratas cuidando:
  - maximo 2 vecinos por punto (las lineas no se ramifican),
  - separacion maxima por codigo (no saltar a otro tramo),
  - sin giros en horquilla,
  - sin cruzar ninguna union ya aceptada (de cualquier codigo).
Una segunda pasada une extremos sueltos que siguen alineados (por ejemplo bajo
un arbol) y los marca para revisar.
"""
import json
from dataclasses import dataclass, field, fields

import numpy as np
from scipy.spatial import cKDTree

ALFA = 4.0
APOYO_MIN = 0.12
ANGULO_MIN = 60.0  # grados; angulo interior minimo entre dos uniones de un punto
TIPOS = ("linea", "franja", "contorno", "punto")


@dataclass
class Codigo:
    """Como se dibuja cada codigo de campo.

    tipo:
      linea    -> polilinea abierta (metrado en m)
      franja   -> dos bordes paralelos (vereda, cuneta, pista) que se cierran en un area
      contorno -> un solo borde que se cierra sobre si mismo (martillo, acceso)
      punto    -> solo puntos (arboles, cajas, postes)
    """
    capa: str
    tipo: str = "linea"
    separacion_max: float = 15.0
    color: int = 7
    tipo_linea: str = "Continuous"
    activo: bool = True
    ancho_min: float = 0.3  # franja: ancho minimo entre bordes (m)
    ancho_max: float = 4.0  # franja: ancho maximo entre bordes (m)
    capa_area: str = ""  # capa del area cerrada + achurado (vacio = no cerrar)
    prefijo: str = ""  # etiqueta del metrado: VD, MT, DPV...
    color_area: int = 0  # 0 = mismo color que la capa
    patron: str = "SOLID"
    escala_patron: float = 0.5
    nombre: str = ""  # descripcion legible para la ventana
    referencia: list = field(default_factory=list)  # franja: codigos del borde interior (fachada, lote)
    misma_manzana: bool = False  # con plano base: solo une puntos de la misma manzana
    hueco_max: float = 0.0  # franja: m sin puntos a lo largo de la fachada que cortan el area (0 = 10 m)
    etiqueta_largo: bool = False  # la etiqueta del area lleva tambien la longitud (canales)
    ancho_defecto: float = 0.0  # franja: ancho supuesto para tramos levantados solo por su eje (0 = no)
    corte_lineal: bool = False  # el borde del area contra el limite de propiedad lleva corte lineal (CL)


def cargar_codigos(ruta):
    """Lee codigos.json -> ({codigo: Codigo}, {alias: codigo})."""
    with open(ruta, encoding="utf-8") as fh:
        datos = json.load(fh)["codigos"]
    validos = {f.name for f in fields(Codigo)}
    codigos, alias = {}, {}
    for cod, v in datos.items():
        if "alias" in v:
            alias[cod.upper()] = v["alias"].upper()
        else:
            codigos[cod.upper()] = Codigo(**{k: val for k, val in v.items() if k in validos})
    return codigos, alias


def guardar_codigos(ruta, codigos, alias, comentario=""):
    datos = {}
    por_defecto = Codigo(capa="")
    for cod, c in codigos.items():
        d = {f.name: getattr(c, f.name) for f in fields(Codigo)
             if f.name == "capa" or getattr(c, f.name) != getattr(por_defecto, f.name)}
        datos[cod] = d
    for a, destino in alias.items():
        datos[a] = {"alias": destino}
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump({"_comentario": comentario, "codigos": datos}, fh, ensure_ascii=False, indent=1)


@dataclass
class Union:
    i: int
    j: int
    largo: float
    apoyo: float = 0.5
    costo: float = 0.0
    revisar: bool = False


@dataclass
class Resultado:
    codigo: str
    puntos: list
    conf: Codigo = None
    uniones: list = field(default_factory=list)
    cadenas: list = field(default_factory=list)  # listas de indices; cerradas si inicio == fin
    barreras: object = None
    orto: object = None
    completar: bool = True
    zonas: object = None  # manzana de cada punto (con plano base)

    def xy(self, cadena):
        return np.array([(self.puntos[i].e, self.puntos[i].n) for i in cadena])


def apoyo_imagen(orto, a, b, paso=0.1):
    """0..1: que tanto la foto muestra un borde a lo largo del segmento a-b."""
    v = b - a
    largo = float(np.hypot(*v))
    if largo < 1e-6:
        return 0.0
    t = np.linspace(0.12, 0.88, max(5, int(largo / max(paso, orto.tam_pixel))))
    pts = a + np.outer(t, v)
    _, ge, gn = orto.muestrear_bordes(pts[:, 0], pts[:, 1])
    u = v / largo
    paralelo = np.minimum(np.abs(ge * -u[1] + gn * u[0]), 1.0)  # borde que acompana al segmento
    cruce = np.minimum(np.abs(ge * u[0] + gn * u[1]), 1.0)  # borde que lo atraviesa
    return float(np.clip(np.median(paralelo) - 0.5 * np.percentile(cruce, 95), 0.0, 1.0))


def _orient(a, b, c):
    return np.sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def _segmentos_cruzan(p1, p2, q1, q2):
    return (_orient(p1, p2, q1) * _orient(p1, p2, q2) < 0) and (_orient(q1, q2, p1) * _orient(q1, q2, p2) < 0)


def _angulo(p, a, b):
    """Angulo en p entre p->a y p->b, en grados."""
    u, v = a - p, b - p
    c = np.dot(u, v) / (np.hypot(*u) * np.hypot(*v) + 1e-12)
    return float(np.degrees(np.arccos(np.clip(c, -1, 1))))


class Barreras:
    """Indice espacial de segmentos aceptados (de todos los codigos) para evitar cruces."""

    def __init__(self, celda=10.0):
        self.celda = celda
        self.grilla = {}

    def _celdas(self, a, b):
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        for i in range(int(x0 // self.celda), int(x1 // self.celda) + 1):
            for j in range(int(y0 // self.celda), int(y1 // self.celda) + 1):
                yield i, j

    def agregar(self, a, b):
        seg = (tuple(a), tuple(b))
        for c in self._celdas(a, b):
            self.grilla.setdefault(c, []).append(seg)

    def cruza(self, a, b):
        vistos = set()
        for c in self._celdas(a, b):
            for p, q in self.grilla.get(c, ()):
                if (p, q) in vistos:
                    continue
                vistos.add((p, q))
                # Compartir un extremo no es cruzar
                if min(np.hypot(*(np.subtract(p, x))) for x in (a, b)) < 1e-6 or \
                        min(np.hypot(*(np.subtract(q, x))) for x in (a, b)) < 1e-6:
                    continue
                if _segmentos_cruzan(a, b, np.array(p), np.array(q)):
                    return True
        return False


class _Grafo:
    def __init__(self, xy, barreras, grado_max=None, cierre=None):
        self.xy = xy
        self.vec = [[] for _ in range(len(xy))]
        # Codigos de control del topografo: un punto de inicio/fin de linea admite un solo vecino,
        # un punto "cerrar" permite cerrar la figura aunque el codigo sea una linea.
        self.grado_max = grado_max if grado_max is not None else [2] * len(xy)
        self.cierre = cierre if cierre is not None else [False] * len(xy)
        self.padre = list(range(len(xy)))
        self.aceptadas = []
        self.barreras = barreras

    def raiz(self, i):
        while self.padre[i] != i:
            self.padre[i] = self.padre[self.padre[i]]
            i = self.padre[i]
        return i

    def admite(self, i, j, permitir_cierre):
        if len(self.vec[i]) >= self.grado_max[i] or len(self.vec[j]) >= self.grado_max[j]:
            return False
        permitir_cierre = permitir_cierre or self.cierre[i] or self.cierre[j]
        if self.raiz(i) == self.raiz(j) and not (permitir_cierre and len(self.vec[i]) == 1 and len(self.vec[j]) == 1):
            return False
        for p, q in ((i, j), (j, i)):
            for k in self.vec[p]:
                if _angulo(self.xy[p], self.xy[k], self.xy[q]) < ANGULO_MIN:
                    return False
        return not self.barreras.cruza(self.xy[i], self.xy[j])

    def agregar(self, u):
        self.vec[u.i].append(u.j)
        self.vec[u.j].append(u.i)
        self.padre[self.raiz(u.i)] = self.raiz(u.j)
        self.aceptadas.append(u)
        self.barreras.agregar(self.xy[u.i], self.xy[u.j])

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


def _candidatos(xy, conf, vecinos=6, zonas=None):
    """Uniones posibles entre vecinos. `zonas`: manzana de cada punto (-1 = ninguna)."""
    if len(xy) < 2:
        return []
    arbol = cKDTree(xy)
    k = min(vecinos + 1, len(xy))
    dist, idx = arbol.query(xy, k=k)
    cand = {}
    for i in range(len(xy)):
        for d, j in zip(np.atleast_1d(dist[i])[1:], np.atleast_1d(idx[i])[1:]):
            if 1e-3 < d <= conf.separacion_max:
                if zonas is not None and zonas[i] != zonas[j]:
                    continue  # puntos de manzanas distintas (p.ej. veredas de cuadras opuestas)
                cand[(min(i, j), max(i, j))] = d
    return [Union(i, j, d) for (i, j), d in cand.items()]


def _resolver(res, xy, uniones, con_foto, barreras, completar=True):
    conf = res.conf
    for u in uniones:
        u.costo = u.largo * (1 + ALFA * (1 - u.apoyo))
    uniones.sort(key=lambda u: u.costo)
    usar = getattr(res, "usar_control", False) and len(res.puntos) == len(xy)
    controles = [getattr(p, "control", "") for p in res.puntos] if usar else [""] * len(xy)
    g = _Grafo(xy, barreras, [1 if c in ("inicio", "fin") else 2 for c in controles],
               [c == "cerrar" for c in controles])
    cierre = conf.tipo == "contorno"
    for u in uniones:
        if con_foto and u.apoyo < APOYO_MIN:
            continue
        if g.admite(u.i, u.j, cierre):
            g.agregar(u)
    if con_foto:
        # Extremos sueltos que siguen la direccion de su tramo (borde tapado por un arbol, auto...)
        for u in sorted(uniones, key=lambda u: u.largo):
            if u.apoyo >= APOYO_MIN or u.largo > 0.6 * conf.separacion_max:
                continue
            if len(g.vec[u.i]) != 1 or len(g.vec[u.j]) != 1:
                continue
            ok = all(180 - _angulo(xy[p], xy[g.vec[p][0]], xy[q]) < 25 for p, q in ((u.i, u.j), (u.j, u.i)))
            if ok and g.admite(u.i, u.j, cierre):
                u.revisar = True
                g.agregar(u)
        # Lo que la foto no respalda (sombra, poco contraste) se une igual por geometria,
        # marcado para revisar: con foto nunca se pierde nada respecto a no usarla.
        for u in sorted(uniones, key=lambda u: u.largo) if completar else ():
            if g.admite(u.i, u.j, cierre):
                u.revisar = True
                g.agregar(u)
    res.uniones = g.aceptadas
    res.cadenas = g.cadenas()
    return res


def unir_codigo(codigo, puntos, conf, orto=None, barreras=None):
    res = Resultado(codigo, puntos, conf)
    if conf.tipo == "punto" or len(puntos) < 2:
        return res
    xy = np.array([(p.e, p.n) for p in puntos], float)
    uniones = _candidatos(xy, conf)
    if orto is not None:
        for u in uniones:
            u.apoyo = apoyo_imagen(orto, xy[u.i], xy[u.j])
    return _resolver(res, xy, uniones, orto is not None, barreras or Barreras())


def agrupar(puntos, codigos, alias=None):
    """{codigo: [puntos]} usando alias; devuelve tambien los codigos sin configurar."""
    alias = alias or {}
    grupos, sin_conf = {}, {}
    for p in puntos:
        cod = alias.get(p.codigo, p.codigo)
        if cod in codigos:
            grupos.setdefault(cod, []).append(p)
        else:
            sin_conf[cod] = sin_conf.get(cod, 0) + 1
    return grupos, sin_conf


def zonas_de(xy, base):
    """Manzana (indice de limite) mas cercana de cada punto, o -1."""
    return np.array([base.limite_de(x, y) for x, y in xy], int)


def unir_todo(puntos, codigos, orto=None, solo=None, alias=None, avisar=print, completar=True, base=None,
              numero_separa=False, control=False):
    """Une todos los codigos activos. Devuelve (resultados, {codigo_sin_configurar: n}).

    numero_separa: el numero pegado al codigo separa lineas (VER1 y VER2 nunca se unen entre si).
    control: respetar los codigos de control del topografo (VER I = inicio, VER F = fin, MAR CLS = cerrar)."""
    grupos, sin_conf = agrupar(puntos, codigos, alias)
    preparados = []
    for cod, pts in sorted(grupos.items()):
        conf = codigos[cod]
        if (solo and cod not in solo) or not conf.activo:
            continue
        xy = np.array([(p.e, p.n) for p in pts], float)
        zonas = zonas_de(xy, base) if base is not None and not base.vacio and conf.misma_manzana else None
        grupos_union = zonas
        if numero_separa:
            nums = [getattr(p, "numero", "") for p in pts]
            if len(set(nums)) > 1:
                base_z = zonas if zonas is not None else [0] * len(pts)
                grupos_union = np.array([f"{z}|{n}" for z, n in zip(base_z, nums)], dtype=object)
        uniones = _candidatos(xy, conf, zonas=grupos_union) if conf.tipo != "punto" else []
        res = Resultado(cod, pts, conf)
        res.zonas = zonas
        res.usar_control = control
        preparados.append((res, xy, uniones))

    if orto is not None:
        # Apoyo de la foto para todas las uniones, recorriendo la foto por bloques
        todas = [(orto.bloque_de(*(xy[u.i] + xy[u.j]) / 2), u, xy) for _, xy, us in preparados for u in us]
        todas.sort(key=lambda t: t[0])
        for k, (_, u, xy) in enumerate(todas):
            u.apoyo = apoyo_imagen(orto, xy[u.i], xy[u.j])
            if k % 5000 == 0 and k:
                avisar(f"  apoyo de la foto: {k}/{len(todas)} uniones")

    # Primero contornos y lineas (fachadas, lotes: sirven de referencia), luego franjas.
    # Las franjas con referencia se resuelven al cerrar areas (areas.py), no aqui.
    orden = {"contorno": 0, "linea": 1, "franja": 2, "punto": 3}
    preparados.sort(key=lambda t: (orden.get(t[0].conf.tipo, 9), t[0].codigo))
    barreras = Barreras()
    if base is not None:
        # Ninguna union puede cruzar un limite de propiedad
        for ln in base.limites:
            c = np.asarray(ln.coords)
            for a, b in zip(c[:-1], c[1:]):
                barreras.agregar(a, b)
    resultados = []
    for res, xy, uniones in preparados:
        # Las franjas (veredas, canales, cunetas) se arman por secciones al cerrar areas (areas.py)
        if res.conf.tipo not in ("punto", "franja"):
            _resolver(res, xy, uniones, orto is not None, barreras, completar)
        resultados.append(res)
    resultados.sort(key=lambda r: r.codigo)
    for r in resultados:
        r.barreras = barreras
        r.orto = orto
        r.completar = completar
    return resultados, sin_conf
