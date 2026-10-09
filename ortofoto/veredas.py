"""Veredas pegadas a la fachada, armadas por caras rectas: rectangulos con escalones rectos.

Criterios (todos vistos en planos reales de Bambu):

- La fachada se parte en caras rectas (cada lado de la casa, cada ochave). Cada punto VER se
  asigna a la cara que tiene enfrente y su ancho se mide perpendicular a ESA cara. Un punto de
  esquina (fuera del frente de las dos caras) cuenta para las dos.
- En cada cara los puntos se agrupan en secciones (puntos a menos de SECCION m a lo largo de la
  cara). El ancho de una seccion es la distancia de su punto mas alejado. Una seccion cubre solo
  de su primer a su ultimo punto: el ancho mayor no se estira hacia una vecina mas angosta (salvo
  donde la foto muestra concreto, p.ej. una losa cuyo borde no tiene punto). Los huecos entre
  secciones los rellena el ancho menor.
- Un hueco no se rellena si la foto muestra pasto o tierra a ras del suelo y no hay fachada
  levantada (CSH) en el: es un lote vacio. Un hueco largo (sin puntos en mas de hueco_max m) se une
  solo si los anchos de los dos lados coinciden y la foto no muestra pasto ni tierra (a revisar).
- Cada vereda termina en escuadra en su primer y ultimo punto. En una esquina de la fachada la
  vereda dobla solo si hay puntos en las dos caras; la esquina exterior pasa por el punto de esquina.
- Si los puntos CSH (fachada levantada en campo) quedan detras de la FACHADA del plano, la fachada
  del plano esta corrida hacia la calle: la vereda empieza en la fachada real (la de los CSH).
"""
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

TOL_CARA = 0.15  # m: una cara recta se aparta a lo mas esto de la fachada dibujada
SECCION = 1.5  # m a lo largo de la cara: puntos mas cercanos que esto son la misma seccion
ANCHO_NULO = 0.2  # m: una seccion con todos sus puntos pegados a la fachada no tiene ancho
UNIR_ANCHOS = 0.25  # m: secciones vecinas con anchos que difieren menos que esto llevan un solo ancho
LARGO_SUELTO = 2.0  # m de vereda para un tramo con una sola seccion (a revisar)
HUECO_LARGO = 30.0  # m: huecos sin puntos mas largos que esto nunca se unen
DIF_HUECO_LARGO = 0.5  # m: para unir un hueco largo, los anchos de los dos lados deben coincidir
SUELO_CORTA = 0.6  # fraccion de pasto/tierra en el hueco para no rellenarlo (lote vacio)
CONCRETO_LOTE = 0.25  # fraccion maxima de concreto a la vista en el frente de un lote vacio
SUELO_HUECO_LARGO = 0.3  # fraccion maxima de pasto/tierra para unir un hueco largo
PASO_LOSA = 0.25  # m: paso con que se busca en la foto el borde de una losa sin punto
CONCRETO_LOSA = 0.5  # fraccion de concreto visible para estirar una losa
MEDIO_LOSA_MIN = 0.5  # m: una losa de un solo punto ocupa al menos esto a cada lado (sin pasar vecinas)
TOL_CSH = 2.0  # m: puntos CSH a menos de esto de una cara del plano sirven para revisarla
CORRIDA = 0.1  # m: un CSH mas adentro que esto del lado del lote indica fachada del plano corrida


@dataclass
class Cara:
    p0: np.ndarray
    p1: np.ndarray
    u: np.ndarray  # direccion a lo largo de la cara
    nl: np.ndarray  # normal izquierda
    largo: float
    lado: int = 0  # +1/-1: de que lado (respecto de nl) esta la calle; 0 = aun no se sabe
    atras: float = 0.0  # m que la fachada real (CSH) esta detras de esta cara (fachada del plano corrida)
    puntos: list = field(default_factory=list)  # (t, d, indice, esquina)
    intervalos: list = field(default_factory=list)  # [t0, t1, ancho, revisar]

    def t_d(self, xy):
        v = np.asarray(xy, float) - self.p0
        return float(v @ self.u), float(v @ self.nl)

    def punto(self, t, d):
        return self.p0 + self.u * t + self.nl * self.lado * d

    def rect(self, t0, t1, d0, d1):
        return Polygon([tuple(self.punto(t0, d0)), tuple(self.punto(t1, d0)),
                        tuple(self.punto(t1, d1)), tuple(self.punto(t0, d1))])


def caras_de(ref, manzanas=None):
    """Caras rectas de un limite (cada cara se aparta a lo mas TOL_CARA m de la fachada dibujada).
    Si el limite es una manzana, la calle es el lado de afuera (los puntos pueden corregirlo)."""
    c = np.array(ref.simplify(TOL_CARA, preserve_topology=False).coords, float)[:, :2]
    if len(c) < 2:
        return []
    res = []
    for p0, p1 in zip(c[:-1], c[1:]):
        v = p1 - p0
        largo = float(np.hypot(*v))
        if largo < 0.05:
            continue
        u = v / largo
        cara = Cara(p0, p1, u, np.array([-u[1], u[0]]), largo)
        if manzanas is not None and ref.is_closed:
            medio = (p0 + p1) / 2 + cara.nl * 0.05
            cara.lado = -1 if manzanas.contains(Point(*medio)) else 1
        res.append(cara)
    return res


def _asignar(caras, i, xy, alcance):
    """Asigna el punto i a la cara que tiene enfrente; un punto de esquina va a las dos caras."""
    frente = []
    for cara in caras:
        t, d = cara.t_d(xy)
        if -0.3 <= t <= cara.largo + 0.3:
            frente.append((abs(d), cara, t, d))
    if frente:
        dist, cara, t, d = min(frente, key=lambda v: v[0])
        if dist <= alcance:
            cara.puntos.append((min(max(t, 0.0), cara.largo), d, i, False))
            return True
        return False
    ok = False
    for cara in caras:  # mas alla del extremo de las caras: punto de esquina
        t, d = cara.t_d(xy)
        extremo = cara.p0 if t < 0 else cara.p1
        if np.hypot(*(np.asarray(xy) - extremo)) <= alcance:
            cara.puntos.append((0.0 if t < 0 else cara.largo, d, i, True))
            ok = True
    return ok


def _fracciones(orto, pol):
    if orto is None or pol.is_empty or pol.area < 0.02:
        return None
    from .concreto import fracciones_suelo

    try:
        return fracciones_suelo(orto, pol)
    except Exception:  # la foto no alcanza
        return None


def _secciones(cara, xy, zz, orto, fuera):
    """Secciones de una cara: [(t0, t1, ancho)] con el filtro de jardin (areas._continua)."""
    from .areas import _continua

    pts = sorted(cara.puntos)
    grupos, actual = [], [pts[0]]
    for p in pts[1:]:
        if p[0] - actual[-1][0] > SECCION:
            grupos.append(actual)
            actual = []
        actual.append(p)
    grupos.append(actual)
    secs = []
    for g in grupos:
        g = sorted(g, key=lambda p: p[1])
        orden = [p[2] for p in g]
        dd = {p[2]: p[1] for p in g}
        guardados = [orden[0]]
        for k, j in enumerate(orden[1:], 1):
            motivo = _continua(guardados[-1], j, dd, zz, xy, orto)
            if motivo:
                fuera.update({o: motivo for o in orden[k:]})
                break
            guardados.append(j)
        g = [p for p in g if p[2] in guardados]
        ancho = max(p[1] for p in g)
        if ancho < ANCHO_NULO:
            continue
        secs.append([min(p[0] for p in g), max(p[0] for p in g), ancho])
    return secs


def _hay_csh(cara, t0, t1, csh):
    """Hay fachada levantada (CSH) DENTRO del tramo (no en sus extremos, que son las casas vecinas)."""
    for x, y in csh:
        t, d = cara.t_d((x, y))
        if t0 + 0.5 < t < t1 - 0.5 and abs(d) <= TOL_CSH:
            return True
    return False


def _frente_de_lote(cara, it, orto, csh):
    """Un tramo entero frente a un lote vacio: sin CSH dentro y la foto ve maleza o tierra (no
    concreto) en todo su frente. Solo si en la manzana se levantaron fachadas (hay CSH cerca)."""
    t0, t1, w, _ = it
    if t1 - t0 < 1.0 or _hay_csh(cara, t0, t1, csh):
        return False
    cerca = any(abs(cara.t_d(c)[1]) <= TOL_CSH and -5 <= cara.t_d(c)[0] <= cara.largo + 5 for c in csh)
    return cerca and _lote_vacio(_fracciones(orto, cara.rect(t0, t1, 0.0, w)))


def _lote_vacio(f):
    """La foto del frente muestra suelo o maleza (no concreto): frente de un lote vacio."""
    return (f is not None and f["concreto"] < CONCRETO_LOTE and
            (f["suelo"] > SUELO_CORTA or f["vegetacion"] + f["tierra"] > SUELO_CORTA))


def _intervalos(cara, secs, conf, orto, csh):
    """Intervalos [t0, t1, ancho, revisar] de una cara a partir de sus secciones."""
    hueco = conf.hueco_max or 10.0
    if len(secs) == 1:
        t0, t1, w = secs[0]
        if t1 - t0 < 1.0:  # una sola seccion: un pedazo corto a revisar
            m = (t0 + t1) / 2
            return [[max(m - LARGO_SUELTO / 2, 0.0), min(m + LARGO_SUELTO / 2, cara.largo), w, True]]
        return [[t0, t1, w, False]]
    out = [[secs[0][0], secs[0][1], secs[0][2], False]]
    for (a0, a1, wa), (b0, b1, wb) in zip(secs, secs[1:]):
        gap = b0 - a1
        w = min(wa, wb)
        rellenar, revisar = True, False
        if gap > 0.05:
            f = _fracciones(orto, cara.rect(a1, b0, 0.0, w))
            if gap > hueco:
                # hueco largo: solo si los dos lados tienen el mismo ancho y la foto no ve suelo
                rellenar = (gap <= HUECO_LARGO and abs(wa - wb) <= DIF_HUECO_LARGO and
                            f is not None and f["suelo"] < SUELO_HUECO_LARGO)
                revisar = True
            elif (_lote_vacio(f) and _hay_csh(cara, -1e9, 1e9, csh)
                  and not _hay_csh(cara, a1, b0, csh)):
                # la fachada se levanto (hay CSH en la cara) pero no en este tramo
                rellenar = False  # frente de un lote vacio: no hay vereda
        if rellenar and gap > 0.05:
            # La seccion ancha se estira sobre el hueco solo mientras la foto muestre concreto
            ext_a = ext_b = 0.0
            if wa - wb > UNIR_ANCHOS:
                ext_a = _estirar(cara, a1, +1, gap, wb, wa, orto)
            elif wb - wa > UNIR_ANCHOS:
                ext_b = _estirar(cara, b0, -1, gap, wa, wb, orto)
            if ext_a:
                out[-1][1] = a1 + ext_a
            out.append([a1 + ext_a, b0 - ext_b, w, revisar])
            out.append([b0 - ext_b, b1, wb, False])
        else:
            out.append([b0, b1, wb, False])
    # Grupos aislados (entre huecos que no se rellenan) de menos de 1 m: un pedazo corto a revisar
    grupos, actual = [], [out[0]]
    for it in out[1:]:
        if it[0] - actual[-1][1] > 1e-6:
            grupos.append(actual)
            actual = []
        actual.append(it)
    grupos.append(actual)
    for g in grupos:
        if g[-1][1] - g[0][0] < 1.0:
            m = (g[0][0] + g[-1][1]) / 2
            w = max(it[2] for it in g)
            g[:] = [[max(m - LARGO_SUELTO / 2, 0.0), min(m + LARGO_SUELTO / 2, cara.largo), w, True]]
    out = [it for g in grupos for it in g]
    # Losas de un solo punto (seccion casi sin largo, mas ancha que sus vecinas): un minimo de largo
    for k, it in enumerate(out):
        vecinos = [out[m][2] for m in (k - 1, k + 1) if 0 <= m < len(out)]
        if it[1] - it[0] < 2 * MEDIO_LOSA_MIN and vecinos and it[2] > max(vecinos) + UNIR_ANCHOS:
            m = (it[0] + it[1]) / 2
            it[0], it[1] = max(min(it[0], m - MEDIO_LOSA_MIN), 0.0), min(max(it[1], m + MEDIO_LOSA_MIN), cara.largo)
    return _ajustar(out)


def _estirar(cara, t, sentido, gap, w_menor, w_mayor, orto):
    """Cuanto se estira una seccion ancha sobre el hueco: mientras la foto vea concreto."""
    if orto is None:
        return 0.0
    ext = 0.0
    while ext + PASO_LOSA <= gap - 0.05:
        a, b = sorted((t + sentido * ext, t + sentido * (ext + PASO_LOSA)))
        f = _fracciones(orto, cara.rect(a, b, w_menor, w_mayor))
        if f is None or f["concreto"] < CONCRETO_LOSA:
            break
        ext += PASO_LOSA
    return ext


def _ajustar(intervalos):
    """Sin solapes (donde dos se pisan, manda el mas ancho) y juntando anchos casi iguales."""
    out = sorted(([*v] for v in intervalos if v[1] - v[0] > -1e-6), key=lambda v: (v[0], v[1]))
    for k in range(len(out) - 1):
        a, b = out[k], out[k + 1]
        if a[1] > b[0]:
            if a[2] >= b[2]:
                b[0] = min(a[1], b[1])
            else:
                a[1] = b[0]
    res, pendiente = [], 0.0
    for t0, t1, w, rev in out:
        if t1 - t0 < 1e-6:
            # seccion sin largo (un punto): su ancho pasa al vecino de ancho parecido
            if res and abs(res[-1][1] - t0) < 1e-6 and abs(res[-1][2] - w) <= UNIR_ANCHOS:
                res[-1][2] = max(res[-1][2], w)
            else:
                pendiente = max(pendiente, w)
            continue
        if pendiente and abs(pendiente - w) <= UNIR_ANCHOS:
            w = max(w, pendiente)
        pendiente = 0.0
        if res and abs(res[-1][1] - t0) < 1e-6 and abs(res[-1][2] - w) <= UNIR_ANCHOS:
            res[-1][1] = t1
            res[-1][2] = max(res[-1][2], w)
            res[-1][3] = res[-1][3] or rev
        else:
            res.append([t0, t1, w, rev])
    return res


def _esquina(f, g, hueco):
    """Une la vereda de dos caras seguidas (esquina o quiebre) si las dos tienen puntos y entre los
    ultimos de una y los primeros de la otra no hay mas de `hueco` m. Cada cara conserva su ancho
    (medido perpendicular a ella); el borde exterior dobla donde se cruzan los dos bordes.
    Devuelve el poligono que cierra la esquina (o None)."""
    if not f.intervalos or not g.intervalos or np.hypot(*(f.p1 - g.p0)) > 1e-6:
        return None
    a, b = f.intervalos[-1], g.intervalos[0]
    if (f.largo - a[1]) + b[0] > hueco:
        return None
    a[1], b[0] = f.largo, 0.0
    v = f.p1
    m = np.array([f.u, -g.u]).T
    if abs(np.linalg.det(m)) < 1e-6:
        return None  # sin quiebre: los rectangulos ya se tocan
    for wa, wb in ((a[2], b[2]), (min(a[2], b[2]),) * 2):
        pa, pb = f.punto(f.largo, wa), g.punto(0.0, wb)
        s_ = np.linalg.solve(m, pb - pa)
        if s_[0] < -1e-6:
            return None  # esquina hacia adentro: los rectangulos ya se cubren
        x = pa + f.u * s_[0]
        # La esquina exterior no se aleja del vertice mas que la diagonal de los dos anchos: en un
        # quiebre abierto con anchos distintos se cierra con el ancho menor (sin puntas)
        if np.hypot(*(x - v)) <= np.hypot(wa, wb) * 1.05 + 0.01:
            pol = Polygon([tuple(v), tuple(pa), tuple(x), tuple(pb)])
            return pol if pol.is_valid and pol.area > 0 else None
    return None


def veredas_contra_fachada(res, limites, manzanas=None, csh=(), indices=None, revisar=None, alcance=None):
    """Veredas por caras. Devuelve (areas, bordes, usados).

    limites: lineas de fachada (del plano o levantadas); manzanas: union de manzanas del plano (para
    saber de que lado esta la calle y detectar una fachada corrida); csh: puntos CSH levantados.
    """
    from shapely import STRtree

    from .areas import AREA_MIN, Area

    conf = res.conf
    revisar = [] if revisar is None else revisar
    alcance = conf.ancho_max + 1.0 if alcance is None else alcance
    xy_all = np.array([(p.e, p.n) for p in res.puntos])
    zz_all = np.array([p.z for p in res.puntos])
    orto = getattr(res, "orto", None)
    if not limites:
        return [], [], set()
    arbol = STRtree(limites)
    caras_lim = {}
    usados = set()
    for i in (range(len(xy_all)) if indices is None else indices):
        p = Point(*xy_all[i])
        k = int(arbol.nearest(p))
        if limites[k].distance(p) > alcance:
            continue
        if k not in caras_lim:
            caras_lim[k] = caras_de(limites[k], manzanas)
        if _asignar(caras_lim[k], i, xy_all[i], alcance):
            usados.add(i)
    csh = [tuple(c) for c in csh]
    areas, bordes = [], []
    for k, caras in caras_lim.items():
        for cara in caras:
            if not cara.puntos:
                continue
            # La calle es el lado donde estan los puntos VER (la mayoria); el plano solo desempata
            votos = sum(np.sign(p[1]) for p in cara.puntos if abs(p[1]) > 0.05)
            if votos:
                cara.lado = 1 if votos > 0 else -1
            elif cara.lado == 0:
                cara.lado = 1
            if manzanas is not None:
                # Fachada del plano corrida hacia la calle: los CSH quedan detras (dentro del lote)
                cerca = [cara.t_d(c) for c in csh]
                cerca = [d * cara.lado for t, d in cerca if 0 <= t <= cara.largo and abs(d) <= TOL_CSH]
                adentro = [-d for d in cerca if d < -CORRIDA]
                if len(adentro) >= 2 and len(adentro) >= 0.6 * len(cerca):
                    cara.atras = float(np.median(adentro))
            cara.puntos = [(t, max(d * cara.lado, 0.0), i, esq) for t, d, i, esq in cara.puntos]
            fuera = {}
            secs = _secciones(cara, xy_all, zz_all, orto, fuera)
            for j, motivo in fuera.items():
                p = res.puntos[j]
                revisar.append((p.e, p.n, f"{p.num} {p.desc}: fuera de la vereda ({motivo})"))
            if secs:
                cara.intervalos = _intervalos(cara, secs, conf, orto, csh)
                if orto is not None:
                    cara.intervalos = [it for it in cara.intervalos if not _frente_de_lote(cara, it, orto, csh)]
        # Esquinas entre caras seguidas (y la ultima con la primera en una manzana cerrada)
        piezas = []
        pares = list(zip(caras, caras[1:]))
        if limites[k].is_closed and len(caras) > 2:
            pares.append((caras[-1], caras[0]))
        for f, g in pares:
            e = _esquina(f, g, conf.hueco_max or 10.0)
            if e is not None:
                piezas.append((e, False))
        permitido = []
        for cara in caras:
            for t0, t1, w, rev in cara.intervalos:
                if t1 - t0 > 1e-6 and w > 0:
                    piezas.append((cara.rect(t0, t1, -cara.atras, w), rev))
                    if cara.atras:
                        permitido.append(cara.rect(t0, t1, -cara.atras - 0.01, 0.01))
        if not piezas:
            continue
        if manzanas is not None:
            # Ninguna vereda entra a los lotes, salvo la franja entre la fachada del plano y la real
            lotes = manzanas.difference(unary_union(permitido)) if permitido else manzanas
            piezas = [(g.difference(lotes), r) for g, r in piezas]
            piezas = [(g, r) for g, r in piezas if not g.is_empty and g.area > 1e-4]
        union = unary_union([g.buffer(0.001, join_style=2) for g, _ in piezas]).buffer(-0.001, join_style=2)
        for comp in getattr(union, "geoms", [union]):
            if not isinstance(comp, Polygon) or comp.area < AREA_MIN:
                continue
            comp = Polygon(comp.exterior)  # sin huecos
            de_aqui = [(g, r) for g, r in piezas if g.intersects(comp)]
            largo = sum(max(t1 - t0, 0) for cara in caras for t0, t1, w, _ in cara.intervalos
                        if cara.rect(t0, t1, 0.0, max(w, 0.01)).intersects(comp))
            largo = largo or comp.length / 2
            dudoso = sum(g.intersection(comp).area for g, r in de_aqui if r)
            areas.append(Area(res.codigo, conf, comp, "fachada", comp.area / max(largo, 1e-6), largo,
                              dudoso > 0.5 * comp.area,
                              nota="tramo sin puntos suficientes: largo o union supuestos" if dudoso else ""))
            borde = comp.exterior.difference(limites[k].buffer(0.02))
            bordes += [g for g in getattr(borde, "geoms", [borde]) if isinstance(g, LineString) and g.length > 0.1]
    return areas, bordes, usados
