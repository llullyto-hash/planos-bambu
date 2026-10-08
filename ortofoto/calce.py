"""Calce de la ortofoto con la topografia."""
import csv

import numpy as np


def afin_por_control(pares):
    """Ajuste por minimos cuadrados con pares ((col, fila), (este, norte)).

    Con 2 pares usa Helmert (escala + rotacion + traslacion); con 3 o mas, afin
    completa. Devuelve (afin [a,b,c,d,e,f], residuos en metros por par).
    """
    if len(pares) < 2:
        raise ValueError("Se necesitan al menos 2 puntos de control")
    px = np.array([p for p, _ in pares], float)
    te = np.array([t for _, t in pares], float)
    if len(pares) == 2:
        # Similitud con la fila hacia el sur: E = p*col + q*fila + tx ; N = q*col - p*fila + ty
        A, B = [], []
        for (c, r), (e, n) in zip(px, te):
            A += [[c, r, 1, 0], [-r, c, 0, 1]]
            B += [e, n]
        p, q, tx, ty = np.linalg.lstsq(np.array(A), np.array(B), rcond=None)[0]
        afin = np.array([p, q, tx, q, -p, ty])
    else:
        A = np.c_[px, np.ones(len(px))]
        ce = np.linalg.lstsq(A, te[:, 0], rcond=None)[0]
        cn = np.linalg.lstsq(A, te[:, 1], rcond=None)[0]
        afin = np.r_[ce, cn]
    a, b, c, d, e, f = afin
    pred = np.c_[a * px[:, 0] + b * px[:, 1] + c, d * px[:, 0] + e * px[:, 1] + f]
    return afin, np.hypot(*(pred - te).T)


def leer_control(ruta):
    """CSV con columnas: col, fila, este, norte (encabezado opcional)."""
    pares = []
    with open(ruta, encoding="utf-8-sig") as fh:
        for fila in csv.reader(fh):
            try:
                c, r, e, n = map(float, fila[:4])
            except (ValueError, IndexError):
                continue
            pares.append(((c, r), (e, n)))
    return pares


def calce_automatico(orto, puntos, radio=3.0, paso=None, max_puntos=800, semilla=0):
    """Busca el desplazamiento (dE, dN) que mejor apoya los puntos sobre bordes.

    Los puntos levantados en bordes (vereda, sardinel, fachada...) deben caer
    sobre cambios de color de la foto. Para cada punto se mide el borde en una
    grilla de desplazamientos alrededor (+-radio) y se promedia: el maximo de
    ese mapa es el calce. Devuelve (dE, dN, puntaje_final, puntaje_inicial); la
    correccion de la foto es orto.desplazar(dE, dN).
    """
    pts = np.array([(p.e, p.n) for p in puntos], float)
    if len(pts) < 5:
        return 0.0, 0.0, 0.0, 0.0
    if len(pts) > max_puntos:
        pts = pts[np.random.default_rng(semilla).choice(len(pts), max_puntos, replace=False)]
    # Ordenar por bloque de la foto para leer cada bloque una sola vez
    pts = pts[np.argsort([hash(orto.bloque_de(*p)) for p in pts], kind="stable")]
    paso = paso or max(orto.tam_pixel, 0.05)
    despl = np.arange(-radio, radio + 1e-9, paso)
    dE, dN = np.meshgrid(despl, despl, indexing="ij")
    mapa = np.zeros(dE.shape)
    for e, n in pts:
        mag, _, _ = orto.muestrear_bordes((e - dE).ravel(), (n - dN).ravel())
        mapa += np.minimum(mag, 1.0).reshape(dE.shape)
    mapa /= len(pts)
    i0 = len(despl) // 2
    k = np.unravel_index(np.argmax(mapa), mapa.shape)
    return float(dE[k]), float(dN[k]), float(mapa[k]), float(mapa[i0, i0])
