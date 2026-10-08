"""Cierre de areas (veredas, cunetas, pistas, martillos) y metrados.

Franja: un elemento con dos bordes levantados (p.ej. vereda: borde de
fachada/lote y borde de sardinel, ambos con codigo VER). Cada muestra de un
borde "vota" por el borde del mismo codigo mas cercano si esta a una distancia
entre ancho_min y ancho_max. Dos bordes que se votan mutuamente forman una
franja; el area se cierra solo en el tramo donde realmente son paralelos, asi
una vereda no se pega con el tramo de la otra cuadra.

Contorno: un borde que ya se cerro sobre si mismo (martillo, acceso).

Las areas no se superponen: cada nueva area se recorta contra las ya aceptadas.
"""
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree
from shapely import STRtree
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import substring, unary_union

PASO = 0.5  # m entre muestras de un borde
TRAMO_MIN = 1.0  # m minimos de borde paralelo para cerrar un area
CORTE_TRAMO = 2.0  # m sin pareja que separan un tramo en dos areas
AREA_MIN = 0.15  # m2


@dataclass
class Area:
    codigo: str
    conf: object
    poligono: Polygon
    origen: str  # franja | contorno
    ancho: float = 0.0
    largo: float = 0.0
    revisar: bool = False
    etiqueta: str = ""

    @property
    def area(self):
        return float(self.poligono.area)


@dataclass
class Linea:
    codigo: str
    conf: object
    linea: LineString
    etiqueta: str = ""
    sin_pareja: bool = False  # borde de franja que no se pudo cerrar
    borde: bool = False  # borde de un area armada por secciones (se dibuja en la capa del codigo)


@dataclass
class Metrado:
    areas: list = field(default_factory=list)
    lineas: list = field(default_factory=list)


def _bordes(res):
    abiertos, cerrados = [], []
    for cad in res.cadenas:
        xy = res.xy(cad)
        if cad[0] == cad[-1] and len(cad) >= 4:
            cerrados.append(xy)
        elif len(cad) >= 2:
            abiertos.append(LineString(xy))
    return abiertos, cerrados


def _tramos(posiciones):
    """Agrupa posiciones (m a lo largo del borde) en tramos continuos."""
    posiciones = np.sort(posiciones)
    cortes = np.where(np.diff(posiciones) > CORTE_TRAMO)[0]
    inicio = 0
    for c in list(cortes) + [len(posiciones) - 1]:
        yield posiciones[inicio], posiciones[c]
        inicio = c + 1


def _franjas(res, bordes):
    conf = res.conf
    if len(bordes) < 2:
        return [], set()
    arbol = STRtree(bordes)
    votos = {}  # (a, b) -> lista de (pos_en_a, distancia)
    for ia, a in enumerate(bordes):
        n = max(2, int(a.length / PASO) + 1)
        for pos in np.linspace(0, a.length, n):
            p = a.interpolate(pos)
            cercanos = arbol.query(p.buffer(conf.ancho_max))
            mejor = None
            for ib in cercanos:
                if ib == ia:
                    continue
                b = bordes[ib]
                d = b.distance(p)
                if mejor is None or d < mejor[1]:
                    mejor = (ib, d)
            if mejor and conf.ancho_min <= mejor[1] <= conf.ancho_max:
                b = bordes[mejor[0]]
                pb = b.project(p)
                # La pareja debe estar "enfrente", no pasado el extremo del otro borde
                if 0.05 < pb < b.length - 0.05 or b.distance(p) < conf.ancho_max * 0.8:
                    votos.setdefault((ia, mejor[0]), []).append((pos, mejor[1]))
    areas, usados = [], set()
    for (ia, ib), vs in votos.items():
        if ia > ib and (ib, ia) in votos:
            continue  # cada pareja una sola vez
        if (ib, ia) not in votos:
            continue  # el otro borde no la reconoce como pareja
        a, b = bordes[ia], bordes[ib]
        pos = np.array([v[0] for v in vs])
        for p0, p1 in _tramos(pos):
            if p1 - p0 < TRAMO_MIN:
                continue
            ta = substring(a, p0, p1)
            proy = [b.project(a.interpolate(x)) for x in np.linspace(p0, p1, 8)]
            q0, q1 = min(proy), max(proy)
            if q1 - q0 < TRAMO_MIN * 0.5:
                continue
            tb = substring(b, q0, q1)
            ca, cb = list(ta.coords), list(tb.coords)
            # Cerrar sin cruzar: el final de A se une con el extremo mas cercano de B
            if np.hypot(*np.subtract(ca[-1], cb[0])) > np.hypot(*np.subtract(ca[-1], cb[-1])):
                cb = cb[::-1]
            pol = Polygon(ca + cb)
            if not pol.is_valid:
                pol = pol.buffer(0)
                if isinstance(pol, MultiPolygon):
                    pol = max(pol.geoms, key=lambda g: g.area)
            if pol.is_empty or pol.area < AREA_MIN:
                continue
            ancho = float(np.median([v[1] for v in vs if p0 <= v[0] <= p1]))
            largo = (ta.length + tb.length) / 2
            # Forma coherente con un ancho y un largo; si no, a revisar
            revisar = not (0.6 < pol.area / max(ancho * largo, 1e-6) < 1.5)
            areas.append(Area(res.codigo, conf, pol, "franja", ancho, largo, revisar))
            usados.update((ia, ib))
    return areas, usados


def _poligono_valido(coords):
    pol = Polygon(coords)
    if not pol.is_valid:
        pol = pol.buffer(0)
        if isinstance(pol, MultiPolygon):
            pol = max(pol.geoms, key=lambda g: g.area)
    return pol


def _franjas_por_secciones(res, referencias):
    """Franjas levantadas por secciones (fachada -> sardinel cada cierta distancia).

    Cada punto se asigna a la linea de referencia (fachada/lote) mas cercana:
    asi una vereda nunca se une con la de enfrente. A lo largo de esa linea,
    en cada zona se toma el punto mas cercano como borde interior y el mas
    lejano como borde exterior. Si en una zona solo hay un borde levantado, el
    borde interior es la propia fachada (se marca para revisar).
    Devuelve (areas, bordes, indices_usados).
    """
    conf = res.conf
    if not referencias:
        return [], [], set()
    xy = np.array([(p.e, p.n) for p in res.puntos])
    arbol = STRtree(referencias)
    asignados = {}
    for i, (x, y) in enumerate(xy):
        p = Point(x, y)
        k = arbol.nearest(p)
        ref = referencias[k]
        d = ref.distance(p)
        if d <= conf.ancho_max + 1.0:
            asignados.setdefault(k, []).append((ref.project(p), d, i))
    areas, bordes, usados = [], [], set()
    tol = max(0.25, conf.ancho_min * 0.4)
    ventana = max(4.0, conf.separacion_max / 2)
    for k, lista in asignados.items():
        ref = referencias[k]
        lista.sort()
        s = np.array([v[0] for v in lista])
        d = np.array([v[1] for v in lista])
        idx = [v[2] for v in lista]
        cortes = np.where(np.diff(s) > conf.separacion_max)[0]
        ini = 0
        for fin in list(cortes) + [len(s) - 1]:
            sel = slice(ini, fin + 1)
            ini = fin + 1
            ss, dd, ii = s[sel], d[sel], idx[sel]
            if len(ss) < 2 or ss[-1] - ss[0] < TRAMO_MIN:
                continue
            interior, exterior = [], []
            for j in range(len(ss)):
                cerca = np.abs(ss - ss[j]) <= ventana
                lmin, lmax = dd[cerca].min(), dd[cerca].max()
                pxy = tuple(xy[ii[j]])
                if lmax - lmin >= conf.ancho_min:
                    if dd[j] <= lmin + tol:
                        interior.append((ss[j], pxy))
                    elif dd[j] >= lmax - tol:
                        exterior.append((ss[j], pxy))
                elif dd[j] >= conf.ancho_min:
                    # Solo se levanto el borde exterior: el interior es la fachada
                    exterior.append((ss[j], pxy))
                    interior.append((ss[j], ref.interpolate(ss[j]).coords[0]))
                else:
                    interior.append((ss[j], pxy))
            if len(interior) < 2 or len(exterior) < 2:
                continue
            interior.sort()
            exterior.sort()
            ci = [c for _, c in interior]
            ce = [c for _, c in exterior]
            pol = _poligono_valido(ci + ce[::-1])
            if pol.is_empty or pol.area < AREA_MIN:
                continue
            largo = (LineString(ci).length + LineString(ce).length) / 2
            ancho = pol.area / max(largo, 1e-6)
            if not (conf.ancho_min * 0.5 <= ancho <= conf.ancho_max * 1.2):
                continue
            # A revisar si hubo que corregir la forma (bordes cruzados) o el ancho varia mucho
            anchos_ext = [referencias[k].distance(Point(c)) for c in ce]
            revisar = (not Polygon(ci + ce[::-1]).is_valid) or (max(anchos_ext) - min(anchos_ext) > conf.ancho_max * 0.6)
            areas.append(Area(res.codigo, conf, pol, "secciones", ancho, largo, revisar))
            bordes += [LineString(ci), LineString(ce)]
            usados.update(ii)
    return areas, bordes, usados


def cerrar_areas(resultados, base=None):
    """Devuelve Metrado con areas (sin superposiciones) y lineas.

    base: PlanoBase con los limites de propiedad (fachadas) del plano del proyecto.
    """
    con_base = base is not None and not base.vacio
    met = Metrado()
    candidatas = []
    lineas_por_codigo = {}
    for res in resultados:
        lineas_por_codigo[res.codigo] = [LineString(res.xy(c)) for c in res.cadenas if len(c) >= 2]
    for res in resultados:
        conf = res.conf
        if conf.tipo == "franja" and conf.referencia:
            if con_base:
                # El borde interior es el limite de propiedad dibujado en el plano
                ars, bordes, usados = _franjas_contra_limite(res, base)
            else:
                refs = [ln for cod in conf.referencia for ln in lineas_por_codigo.get(cod, [])]
                ars, bordes, usados = _franjas_por_secciones(res, refs)
            resto = [i for i in range(len(res.puntos)) if i not in usados]
            ars2, bordes2, usados2 = _franjas_por_estaciones(res, resto, res.barreras)
            candidatas += ars + ars2
            met.lineas += [Linea(res.codigo, conf, b, borde=True) for b in bordes + bordes2]
            _unir_sobrantes(res, usados | usados2)
        if conf.tipo == "punto" or not res.cadenas:
            continue
        abiertos, cerrados = _bordes(res)
        if conf.tipo == "contorno" and conf.capa_area:
            # Contorno abierto (p.ej. martillo sin el lado del sardinel): cerrar si los extremos estan cerca
            quedan = []
            for ln in abiertos:
                c = list(ln.coords)
                if len(c) >= 3 and np.hypot(*np.subtract(c[0], c[-1])) <= conf.separacion_max:
                    cerrados.append(np.array(c + [c[0]]))
                else:
                    quedan.append(ln)
            abiertos = quedan
        if conf.tipo in ("franja", "contorno") and conf.capa_area:
            for xy in cerrados:
                pol = Polygon(xy)
                if not pol.is_valid:
                    pol = pol.buffer(0)
                    if isinstance(pol, MultiPolygon):
                        pol = max(pol.geoms, key=lambda g: g.area)
                if pol.area >= AREA_MIN:
                    candidatas.append(Area(res.codigo, conf, pol, "contorno", largo=pol.length / 2))
            usados = set()
            if conf.tipo == "franja":
                areas, usados = _franjas(res, abiertos)
                candidatas += areas
            for k, ln in enumerate(abiertos):
                met.lineas.append(Linea(res.codigo, conf, ln, sin_pareja=(conf.tipo == "franja" and k not in usados)))
        else:
            met.lineas += [Linea(res.codigo, conf, ln) for ln in abiertos]
            met.lineas += [Linea(res.codigo, conf, LineString(xy)) for xy in cerrados]

    if con_base:
        # Ningun area entra a los lotes
        recortadas = []
        for ar in candidatas:
            pol = base.recortar(ar.poligono)
            if isinstance(pol, Polygon) and pol.area >= AREA_MIN:
                ar.poligono = pol
                recortadas.append(ar)
        candidatas = recortadas
    # Sin superposiciones: primero las mas confiables (contornos, luego franjas grandes)
    candidatas.sort(key=lambda a: (a.revisar, a.origen != "contorno", -a.area))
    ocupado = None
    for ar in candidatas:
        pol = ar.poligono
        if ocupado is not None and pol.intersects(ocupado):
            resto = pol.difference(ocupado)
            if resto.area < 0.5 * pol.area:
                continue  # es practicamente un duplicado
            if isinstance(resto, MultiPolygon):
                resto = max(resto.geoms, key=lambda g: g.area)
            if resto.area < AREA_MIN or not isinstance(resto, Polygon):
                continue
            ar.poligono = resto
        met.areas.append(ar)
        ocupado = ar.poligono if ocupado is None else unary_union([ocupado, ar.poligono])
    _numerar(met)
    return met


def _tramo_de_limite(ref, s0, s1):
    """Tramo del limite entre las posiciones s0 y s1 (si el limite es cerrado, puede pasar por el inicio)."""
    largo = ref.length
    if s0 <= s1:
        return list(substring(ref, s0, s1).coords)
    return list(substring(ref, s0, largo).coords) + list(substring(ref, 0, s1).coords)[1:]


def _franjas_contra_limite(res, base):
    """Veredas pegadas al limite de propiedad del plano base.

    Cada punto se asigna al limite (manzana) mas cercano. A lo largo de ese
    limite se agrupan en tramos (se corta donde no hay puntos en mas de
    separacion_max) y en cada zona se toma el punto mas alejado del limite como
    borde exterior (sardinel). El area es: limite de propiedad -> borde exterior.
    """
    conf = res.conf
    xy = np.array([(p.e, p.n) for p in res.puntos])
    por_limite = {}
    for i, (x, y) in enumerate(xy):
        k = base.limite_de(x, y, dist=conf.ancho_max + 1.0)
        if k >= 0:
            ref = base.limites[k]
            p = Point(x, y)
            por_limite.setdefault(k, []).append((ref.project(p), ref.distance(p), i))
    areas, bordes, usados = [], [], set()
    tol = max(0.3, conf.ancho_min * 0.5)
    ventana = max(4.0, conf.separacion_max / 2)
    for k, lista in por_limite.items():
        ref = base.limites[k]
        largo = ref.length
        cerrado = ref.is_closed
        s = np.array([v[0] for v in lista])
        d = np.array([v[1] for v in lista])
        idx = np.array([v[2] for v in lista])
        # En un limite cerrado, empezar a contar despues del mayor hueco sin puntos
        corte = 0.0
        if cerrado and len(s) > 1:
            orden = np.sort(s)
            huecos = np.diff(np.r_[orden, orden[0] + largo])
            corte = orden[(np.argmax(huecos) + 1) % len(orden)]
        sr = (s - corte) % largo if cerrado else s
        o = np.argsort(sr)
        sr, d, idx, s = sr[o], d[o], idx[o], s[o]
        cortes = np.where(np.diff(sr) > conf.separacion_max)[0]
        ini = 0
        for fin in list(cortes) + [len(sr) - 1]:
            sel = slice(ini, fin + 1)
            ini = fin + 1
            ss, dd, ii, s_real = sr[sel], d[sel], idx[sel], s[sel]
            exterior = []
            for j in range(len(ss)):
                cerca = np.abs(ss - ss[j]) <= ventana
                if dd[j] >= conf.ancho_min * 0.8 and dd[j] >= dd[cerca].max() - tol:
                    exterior.append(j)
            if len(exterior) < 2 or ss[exterior[-1]] - ss[exterior[0]] < TRAMO_MIN:
                continue
            ce = [tuple(xy[ii[j]]) for j in exterior]
            ci = _tramo_de_limite(ref, s_real[exterior[0]], s_real[exterior[-1]])
            if len(ci) < 2:
                continue
            pol = _poligono_valido(ci + ce[::-1])
            if pol.is_empty or pol.area < AREA_MIN:
                continue
            largo_tramo = LineString(ci).length
            ancho = pol.area / max(largo_tramo, 1e-6)
            if ancho > conf.ancho_max * 1.2:
                continue
            anchos = dd[exterior]
            revisar = (not Polygon(ci + ce[::-1]).is_valid) or (anchos.max() - anchos.min() > conf.ancho_max * 0.6)
            areas.append(Area(res.codigo, conf, pol, "limite", float(np.median(anchos)), largo_tramo, revisar))
            bordes.append(LineString(ce))
            usados.update(int(i) for i in ii)
    return areas, bordes, usados


def _franjas_por_estaciones(res, indices, barreras=None):
    """Franjas levantadas por secciones sin linea de referencia cerca.

    1) Seccion = grupo de 2 a 5 puntos vecinos cuyo ancho (los dos mas
       alejados) esta entre ancho_min y ancho_max.
    2) Se encadenan secciones vecinas (hasta separacion_max) solo si se avanza
       de forma perpendicular a ambas secciones (una vereda avanza a lo largo,
       sus secciones la cruzan) y con anchos parecidos.
    3) Cada cadena de 2 o mas secciones se cierra uniendo un extremo con el
       otro a lo largo de toda la cadena.
    Devuelve (areas, bordes, indices_usados).
    """
    from . import unir

    conf = res.conf
    if len(indices) < 4:
        return [], [], set()
    xy = np.array([(res.puntos[i].e, res.puntos[i].n) for i in indices])
    arbol = cKDTree(xy)
    k = min(4, len(xy))
    _, vec = arbol.query(xy, k=k)
    padre = list(range(len(xy)))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for i in range(len(xy)):
        for j in vec[i][1:3]:
            if i in vec[j][1:3] and np.hypot(*(xy[i] - xy[j])) <= conf.ancho_max:
                padre[raiz(i)] = raiz(j)
    grupos = {}
    for i in range(len(xy)):
        grupos.setdefault(raiz(i), []).append(i)
    secciones = []  # (p, q, centro, eje, ancho, miembros)
    for miembros in grupos.values():
        if not 2 <= len(miembros) <= 5:
            continue
        m = xy[miembros]
        dist = np.hypot(*(m[:, None, :] - m[None, :, :]).transpose(2, 0, 1))
        a, b = np.unravel_index(np.argmax(dist), dist.shape)
        ancho = dist[a, b]
        if not conf.ancho_min <= ancho <= conf.ancho_max:
            continue
        p, q = m[a], m[b]
        secciones.append((p, q, (p + q) / 2, (q - p) / ancho, ancho, miembros))
    if len(secciones) < 2:
        return [], [], set()

    centros = np.array([s_[2] for s_ in secciones])
    zona_sec = None
    if getattr(res, "zonas", None) is not None:
        zona_sec = [int(np.bincount(np.asarray(res.zonas)[[indices[m] for m in s_[5]]] + 1).argmax()) - 1
                    for s_ in secciones]
    arbol_c = cKDTree(centros)
    cand = []
    for i, j in arbol_c.query_pairs(conf.separacion_max * 1.25):
        v = centros[j] - centros[i]
        largo = np.hypot(*v)
        u = v / largo
        ci, cj = abs(np.dot(secciones[i][3], u)), abs(np.dot(secciones[j][3], u))
        ratio = max(secciones[i][4], secciones[j][4]) / min(secciones[i][4], secciones[j][4])
        if ci < 0.5 and cj < 0.5 and ratio < 2.5:
            if zona_sec is not None and zona_sec[i] != zona_sec[j]:
                continue  # secciones de manzanas distintas
            if barreras is not None and barreras.cruza(centros[i], centros[j]):
                continue  # cruzaria un limite de propiedad u otra union
            cand.append((largo * (1 + ci + cj + 0.3 * (ratio - 1)), i, j))
    cand.sort()
    grafo = unir._Grafo(centros, barreras or unir.Barreras())
    for costo, i, j in cand:
        if len(grafo.vec[i]) < 2 and len(grafo.vec[j]) < 2 and grafo.raiz(i) != grafo.raiz(j):
            # recto: en cada seccion el giro entre tramos debe ser suave (> 120 grados)
            ok = all(unir._angulo(centros[a], centros[c], centros[b]) >= 120
                     for a, b in ((i, j), (j, i)) for c in grafo.vec[a])
            if ok:
                grafo.vec[i].append(j)
                grafo.vec[j].append(i)
                grafo.padre[grafo.raiz(i)] = grafo.raiz(j)
    areas, bordes, usados = [], [], set()
    for cadena in grafo.cadenas():
        if len(cadena) < 2 or cadena[0] == cadena[-1]:
            continue
        lado1, lado2 = [secciones[cadena[0]][0]], [secciones[cadena[0]][1]]
        for idx in cadena[1:]:
            p, q = secciones[idx][0], secciones[idx][1]
            # orientar la seccion para que los lados no se crucen
            if np.hypot(*(lado1[-1] - p)) + np.hypot(*(lado2[-1] - q)) > \
                    np.hypot(*(lado1[-1] - q)) + np.hypot(*(lado2[-1] - p)):
                p, q = q, p
            lado1.append(p)
            lado2.append(q)
        coords = [tuple(c) for c in lado1] + [tuple(c) for c in lado2[::-1]]
        pol = _poligono_valido(coords)
        if pol.is_empty or pol.area < AREA_MIN:
            continue
        largo = (LineString(lado1).length + LineString(lado2).length) / 2
        anchos = [secciones[i][4] for i in cadena]
        revisar = not Polygon(coords).is_valid
        areas.append(Area(res.codigo, conf, pol, "estaciones", float(np.median(anchos)), largo, revisar))
        bordes += [LineString(lado1), LineString(lado2)]
        for i in cadena:
            usados.update(indices[m] for m in secciones[i][5])
    return areas, bordes, usados


def _unir_sobrantes(res, usados):
    """Los puntos que no entraron en ninguna seccion se unen borde a borde (metodo PETRO)."""
    from . import unir

    resto = [i for i in range(len(res.puntos)) if i not in usados]
    if len(resto) < 2:
        return
    xy = np.array([(res.puntos[i].e, res.puntos[i].n) for i in resto])
    zonas = None if getattr(res, "zonas", None) is None else np.asarray(res.zonas)[resto]
    uniones = unir._candidatos(xy, res.conf, zonas=zonas)
    if res.orto is not None:
        for u in uniones:
            u.apoyo = unir.apoyo_imagen(res.orto, xy[u.i], xy[u.j])
    sub = unir.Resultado(res.codigo, [res.puntos[i] for i in resto], res.conf)
    unir._resolver(sub, xy, uniones, res.orto is not None, res.barreras or unir.Barreras(), res.completar)
    res.uniones = [unir.Union(resto[u.i], resto[u.j], u.largo, u.apoyo, u.costo, u.revisar) for u in sub.uniones]
    res.cadenas = [[resto[i] for i in c] for c in sub.cadenas]


def _numerar(met):
    """VD - 01, VD - 02... ordenadas de norte a sur y de oeste a este."""
    por_prefijo = {}
    for ar in met.areas:
        por_prefijo.setdefault(ar.conf.prefijo or ar.codigo, []).append(ar)
    for pref, lista in por_prefijo.items():
        lista.sort(key=lambda a: (-round(a.poligono.centroid.y / 20), a.poligono.centroid.x))
        for k, ar in enumerate(lista, 1):
            ar.etiqueta = f"{pref} - {k:02d}"
    por_prefijo = {}
    for ln in met.lineas:
        if ln.conf.prefijo and ln.conf.tipo == "linea":
            por_prefijo.setdefault(ln.conf.prefijo, []).append(ln)
    for pref, lista in por_prefijo.items():
        lista.sort(key=lambda l: (-round(l.linea.centroid.y / 20), l.linea.centroid.x))
        for k, ln in enumerate(lista, 1):
            ln.etiqueta = f"{pref} - {k:02d}"


def punto_etiqueta(pol):
    """Punto dentro del poligono para poner el texto."""
    p = pol.representative_point()
    return p.x, p.y


def guardar_metrado(met, ruta_xlsx, ruta_csv=None):
    """Planilla de metrados (Excel) y CSV."""
    filas = []
    for ar in met.areas:
        x, y = punto_etiqueta(ar.poligono)
        filas.append([ar.etiqueta, ar.conf.nombre or ar.codigo, ar.conf.capa_area, "m2", round(ar.area, 2),
                      round(ar.largo, 2), round(ar.ancho, 2), "SI" if ar.revisar else "", round(x, 3), round(y, 3)])
    for ln in met.lineas:
        if not ln.etiqueta:
            continue
        x, y = ln.linea.interpolate(0.5, normalized=True).coords[0]
        filas.append([ln.etiqueta, ln.conf.nombre or ln.codigo, ln.conf.capa, "m", round(ln.linea.length, 2),
                      round(ln.linea.length, 2), "", "", round(x, 3), round(y, 3)])
    cab = ["Etiqueta", "Elemento", "Capa", "Unidad", "Metrado", "Largo (m)", "Ancho medio (m)", "Revisar",
           "Este", "Norte"]
    resumen = {}
    for f in filas:
        clave = (f[0].split(" - ")[0], f[1], f[3])
        n, tot = resumen.get(clave, (0, 0.0))
        resumen[clave] = (n + 1, tot + f[4])
    if ruta_csv:
        import csv

        with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(cab)
            w.writerows(filas)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        return resumen
    wb = Workbook()
    hoja = wb.active
    hoja.title = "Resumen"
    hoja.append(["Codigo", "Elemento", "Unidad", "Cantidad", "Metrado total"])
    for (pref, nombre, und), (n, tot) in sorted(resumen.items()):
        hoja.append([pref, nombre, und, n, round(tot, 2)])
    det = wb.create_sheet("Detalle")
    det.append(cab)
    for f in filas:
        det.append(f)
    amarillo = PatternFill("solid", fgColor="FFF2CC")
    for h in (hoja, det):
        for c in h[1]:
            c.font = Font(bold=True)
        for col in h.columns:
            h.column_dimensions[col[0].column_letter].width = max(10, max(len(str(c.value or "")) for c in col) + 2)
    for fila in det.iter_rows(min_row=2):
        if fila[7].value == "SI":
            for c in fila:
                c.fill = amarillo
    wb.save(ruta_xlsx)
    return resumen
