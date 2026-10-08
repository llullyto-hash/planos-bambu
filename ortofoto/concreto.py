"""Deteccion de veredas de concreto en la ortofoto, guiada por los puntos VER.

1. Los puntos VER dicen como se ve el concreto en ESTA foto: se toma el color
   (Lab) y la textura alrededor de cada punto y se arma un modelo.
2. Se busca la superficie conectada a esos puntos que se ve igual, solo en la
   franja de la calle junto al limite de propiedad (no entra a los lotes ni
   pasa del ancho maximo de vereda).
3. El contorno de esa superficie es la forma real de la vereda.
4. Cada punto VER se compara con ese contorno: si cae lejos, se avisa.
"""
from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi
from shapely.geometry import MultiPolygon, Point, Polygon, shape
from shapely.ops import unary_union

UMBRAL = 3.2  # distancia de Mahalanobis maxima al modelo de concreto
RADIO_MUESTRA = 0.15  # m alrededor de cada semilla para aprender el color
TOL_PUNTO = 0.6  # m: un punto de borde mas lejos que esto del contorno detectado se marca
# Como se ve el concreto expuesto en una ortofoto (L de 0 a 100, croma y textura en unidades Lab)
L_MIN = 60.0  # mas oscuro que esto es sombra o techo, no concreto a la vista
CROMA_MAX = 14.0
TEXTURA_MAX = 6.0
AREA_MIN_VISIBLE = 15.0  # m2: manchas menores no se proponen
BLOQUE_VIS = 2048


@dataclass
class VeredaFoto:
    poligono: Polygon
    puntos: list  # indices de los puntos VER usados
    lejos: list  # indices de puntos que no calzan con lo que se ve en la foto


def _lab(rgb):
    c = rgb.astype(np.float32) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = c @ m.T / np.array([0.9505, 1.0, 1.089], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def _rasterizar(pol, afin, forma):
    from rasterio.features import rasterize
    from rasterio.transform import Affine

    t = Affine(*afin)
    return rasterize([(pol, 1)], out_shape=forma, transform=t, fill=0, dtype="uint8").astype(bool)


def _vectorizar(mask, afin):
    from rasterio.features import shapes
    from rasterio.transform import Affine

    t = Affine(*afin)
    pols = [shape(g) for g, v in shapes(mask.astype("uint8"), mask=mask, transform=t) if v == 1]
    return unary_union(pols) if pols else Polygon()


def detectar_franja(orto, zona, semillas_xy, tam_px=None):
    """Superficie de concreto dentro de `zona` conectada a los puntos `semillas_xy`.

    Devuelve un poligono (o MultiPolygon) en coordenadas de terreno.
    """
    if zona.is_empty or not len(semillas_xy):
        return Polygon()
    x0, y0, x1, y1 = zona.bounds
    sub = orto.recortar(x0, y0, x1, y1)
    rgb = sub.rgb
    if rgb.shape[0] < 5 or rgb.shape[1] < 5:
        return Polygon()
    tp = sub.tam_pixel
    lb = _lab(rgb)
    sig = max(1.0, 0.06 / tp)
    feats = [ndi.gaussian_filter(lb[..., k], sig) for k in range(3)]
    ventana = max(3, int(round(0.3 / tp)) | 1)
    L = lb[..., 0]
    textura = np.sqrt(np.maximum(ndi.uniform_filter(L * L, ventana) - ndi.uniform_filter(L, ventana) ** 2, 0))
    feat = np.dstack(feats + [textura])
    h, w = L.shape
    dentro = _rasterizar(zona, sub.afin, (h, w))
    cols, filas = sub.a_pixel(np.asarray(semillas_xy)[:, 0], np.asarray(semillas_xy)[:, 1])
    r = max(1, int(RADIO_MUESTRA / tp))
    muestras, pix = [], []
    for c, f in zip(cols, filas):
        c, f = int(round(c)), int(round(f))
        if 0 <= f < h and 0 <= c < w:
            muestras.append(feat[max(0, f - r):f + r + 1, max(0, c - r):c + r + 1].reshape(-1, 4))
            pix.append((f, c))
    if not muestras:
        return Polygon()
    m = np.vstack(muestras)
    # Modelo robusto: mediana y covarianza de las muestras mas tipicas
    med = np.median(m, 0)
    if med[0] < L_MIN or med[3] > TEXTURA_MAX:
        # Donde estan los puntos no se ve concreto (sombra, alero, techo): la foto no ayuda aqui
        return Polygon()
    d0 = np.abs(m - med).sum(1)
    tipicas = m[d0 <= np.percentile(d0, 70)]
    cov = np.cov(tipicas.T) + np.diag([4.0, 1.0, 1.0, 1.0])
    inv = np.linalg.inv(cov)
    dif = feat.reshape(-1, 4) - med
    maha = np.sqrt(np.einsum("ij,jk,ik->i", dif, inv, dif)).reshape(h, w)
    mask = (maha < UMBRAL) & dentro
    it = max(1, int(round(0.1 / tp)))
    mask = ndi.binary_opening(mask, iterations=it)
    mask = ndi.binary_closing(mask, iterations=it * 3) & dentro
    etq, _ = ndi.label(mask)
    ids = {etq[f, c] for f, c in pix if etq[f, c] > 0}
    if not ids:
        return Polygon()
    reg = ndi.binary_fill_holes(np.isin(etq, list(ids)))
    pol = _vectorizar(reg, sub.afin).buffer(0)
    return pol.simplify(max(tp, 0.05)).intersection(zona)


def veredas_desde_foto(orto, base, puntos_xy, conf, grupos):
    """Para cada limite de propiedad con puntos VER, la vereda vista en la foto.

    grupos: {indice_limite: [indices de puntos]} (puntos asignados a esa manzana).
    """
    res = []
    manzanas = base.union_manzanas()
    for k, idx in grupos.items():
        if len(idx) < 2:
            continue
        ref = base.limites[k]
        zona = ref.buffer(conf.ancho_max + 0.3, cap_style=2, join_style=2)
        if not manzanas.is_empty:
            zona = zona.difference(manzanas)
        # Solo la zona alrededor de los puntos de este tramo (no toda la manzana)
        cerca = unary_union([Point(puntos_xy[i]).buffer(conf.separacion_max * 0.75) for i in idx])
        zona = zona.intersection(cerca)
        # Los puntos VER estan SOBRE los bordes (fachada, sardinel): para aprender el color del
        # concreto se usa el punto medio entre cada punto de sardinel y la fachada, que cae dentro.
        semillas = []
        for i in idx:
            pt = Point(puntos_xy[i])
            if ref.distance(pt) >= conf.ancho_min:
                q = ref.interpolate(ref.project(pt))
                semillas.append(((pt.x + q.x) / 2, (pt.y + q.y) / 2))
        if not semillas:
            continue
        pol = detectar_franja(orto, zona, semillas)
        if pol.is_empty:
            continue
        # El suavizado de la foto deja el borde 1-2 pixeles adentro: recuperarlo, y pegar a la
        # fachada la franja angosta que quede entre el concreto detectado y el limite.
        pol = pol.buffer(2 * orto.tam_pixel, join_style=2)
        pol = unary_union([pol, pol.buffer(0.35).intersection(ref.buffer(0.35))]).intersection(zona)
        for p in getattr(pol, "geoms", [pol]):
            if not isinstance(p, Polygon) or p.area < 0.5:
                continue
            cerca_p = p.buffer(TOL_PUNTO)
            usados = [i for i in idx if cerca_p.contains(Point(puntos_xy[i]))]
            if len(usados) < 2:
                continue
            # 1) Puntos VER junto a la vereda que segun la foto no estan sobre concreto
            lejos = [i for i in idx if i not in usados and p.distance(Point(puntos_xy[i])) < 3.0]
            # 2) Puntos de sardinel (los mas alejados de la fachada en su zona) que no estan en el borde visible
            s_ = np.array([ref.project(Point(puntos_xy[i])) for i in usados])
            d_ = np.array([ref.distance(Point(puntos_xy[i])) for i in usados])
            for j, i in enumerate(usados):
                cerca = np.abs(s_ - s_[j]) <= 4.0
                es_borde = d_[j] >= conf.ancho_min and d_[j] >= d_[cerca].max() - 0.3
                if es_borde and p.exterior.distance(Point(puntos_xy[i])) > TOL_PUNTO:
                    lejos.append(i)
            res.append(VeredaFoto(p, usados, lejos))
    return res


def concreto_visible(orto, base, puntos_xy, area_min=AREA_MIN_VISIBLE, corredor=5.0, avisar=print):
    """Todo el concreto expuesto que se ve en la foto en las calles (fuera de las manzanas).

    Claro, sin color fuerte y liso (las calaminas tienen franjas, la tierra es mas coloreada).
    Solo dentro del corredor levantado (a menos de `corredor` m de algun punto topografico),
    para no confundir techos claros fuera de la zona de trabajo. Se procesa por bloques.
    """
    from shapely import STRtree

    h, w = orto.rgb.shape[:2]
    tp = orto.tam_pixel
    margen = 32
    manzanas = base.union_manzanas() if base is not None else Polygon()
    pts = [Point(x, y) for x, y in puntos_xy]
    arbol = STRtree(pts) if pts else None
    piezas = []
    bloques = [(f, c) for f in range(0, h, BLOQUE_VIS) for c in range(0, w, BLOQUE_VIS)]
    for k, (f0, c0) in enumerate(bloques):
        f1, c1 = min(h, f0 + BLOQUE_VIS), min(w, c0 + BLOQUE_VIS)
        fa, ca = max(0, f0 - margen), max(0, c0 - margen)
        fb, cb = min(h, f1 + margen), min(w, c1 + margen)
        sub = orto.rgb[fa:fb, ca:cb]
        if sub.size == 0:
            continue
        lb = _lab(sub)
        L = ndi.gaussian_filter(lb[..., 0], 1)
        C = np.hypot(ndi.gaussian_filter(lb[..., 1], 1), ndi.gaussian_filter(lb[..., 2], 1))
        v = max(3, int(0.5 / tp) | 1)
        tex = np.sqrt(np.maximum(ndi.uniform_filter(lb[..., 0] ** 2, v) - ndi.uniform_filter(lb[..., 0], v) ** 2, 0))
        mask = (L > L_MIN + 8) & (C < CROMA_MAX) & (tex < TEXTURA_MAX)
        it = max(1, int(round(0.2 / tp)))
        mask = ndi.binary_opening(mask, iterations=it)
        mask = ndi.binary_closing(mask, iterations=it + 1)
        mask[: f0 - fa, :] = False
        mask[f1 - fa:, :] = False
        mask[:, : c0 - ca] = False
        mask[:, c1 - ca:] = False
        if not mask.any():
            continue
        a, b, _, d, e, _ = orto.afin
        e0, n0 = orto.a_terreno(ca, fa)
        pol = _vectorizar(mask, [a, b, e0, d, e, n0])
        if not pol.is_empty:
            piezas.append(pol)
        if len(bloques) > 4 and k % 10 == 9:
            avisar(f"  concreto visible: bloque {k + 1}/{len(bloques)}")
    if not piezas:
        return []
    total = unary_union(piezas).buffer(tp, join_style=2).buffer(-tp, join_style=2)
    if not manzanas.is_empty:
        total = total.difference(manzanas.buffer(0.3))
    res = []
    for g in getattr(total, "geoms", [total]):
        if not isinstance(g, Polygon) or g.area < area_min:
            continue
        # Dentro del corredor levantado: al menos 3 puntos a menos de `corredor` m
        if arbol is not None and len(arbol.query(g.buffer(corredor))) < 3:
            continue
        res.append(g.simplify(max(tp, 0.05)))
    return res


ANCHO_CORTE = 0.8  # m: tierra/pasto mas angosto que esto no corta la vereda (ruido, bordes)


def cortar_por_foto(orto, pol):
    """Quita de una vereda los tramos donde la foto muestra tierra o pasto (no hay concreto).

    La sombra y los aleros (oscuros) NO cortan: la foto no sabe que hay debajo. Si lo quitado
    atraviesa la vereda, esta queda partida en pedazos, cada uno cerrado contra la fachada.
    Devuelve (lista_de_poligonos, area_quitada).
    """
    x0, y0, x1, y1 = pol.bounds
    try:
        sub = orto.recortar(x0, y0, x1, y1)
    except ValueError:
        return [pol], 0.0
    if sub.rgb.shape[0] < 5 or sub.rgb.shape[1] < 5:
        return [pol], 0.0
    tp = sub.tam_pixel
    lb = _lab(sub.rgb)
    L = ndi.gaussian_filter(lb[..., 0], 1)
    a = ndi.gaussian_filter(lb[..., 1], 1)
    b = ndi.gaussian_filter(lb[..., 2], 1)
    croma = np.hypot(a, b)
    dentro = _rasterizar(pol, sub.afin, L.shape)
    v = max(3, int(0.5 / tp) | 1)
    tex = np.sqrt(np.maximum(ndi.uniform_filter(lb[..., 0] ** 2, v) - ndi.uniform_filter(lb[..., 0], v) ** 2, 0))
    sombra = L < L_MIN - 15
    pasto = (a < -6) & ~sombra
    # Tierra: beige/amarilla (b mayor que a), lisa. Los techos (rojizos o corrugados) no cuentan:
    # sobre la vereda son aleros y debajo puede haber concreto.
    tierra = (croma > CROMA_MAX + 4) & (b > 8) & (a < 0.8 * b) & (tex < TEXTURA_MAX * 1.5) & ~sombra
    no_concreto = (pasto | tierra) & dentro
    r = max(1, int(round(ANCHO_CORTE / tp / 2)))
    no_concreto = ndi.binary_opening(no_concreto, structure=np.ones((2 * r + 1, 2 * r + 1)))
    if not no_concreto.any():
        return [pol], 0.0
    quitar = _vectorizar(no_concreto, sub.afin).buffer(tp)
    resto = pol.difference(quitar)
    piezas = [g for g in getattr(resto, "geoms", [resto]) if isinstance(g, Polygon) and g.area >= 1.0]
    return piezas, pol.area - sum(g.area for g in piezas)
