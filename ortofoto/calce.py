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


def calce_automatico(orto, puntos, radio=3.0, paso=None):
    """Busca el desplazamiento (dE, dN) que mejor apoya los puntos sobre bordes.

    Los puntos levantados en bordes (vereda, sardinel, lindero...) deben caer
    sobre cambios de color de la foto. Se prueba una grilla de desplazamientos
    y se queda con el que maximiza el gradiente medio en esos puntos.
    Devuelve (dE, dN, puntaje_final, puntaje_inicial); la correccion de la
    foto es orto.desplazar(dE, dN).
    """
    pts = np.array([(p.e, p.n) for p in puntos], float)
    if len(pts) < 5:
        return 0.0, 0.0, 0.0, 0.0
    paso = paso or max(orto.tam_pixel, 0.05)

    def puntaje(de, dn):
        mag, _, _ = orto.muestrear_bordes(pts[:, 0] - de, pts[:, 1] - dn)
        return float(np.mean(np.minimum(mag, 1.0)))

    inicial = puntaje(0.0, 0.0)
    mejor = (inicial, 0.0, 0.0)
    # Busqueda gruesa y luego fina alrededor del mejor
    for r, s in [(radio, max(paso * 4, radio / 15)), (paso * 6, paso)]:
        cen_e, cen_n = mejor[1], mejor[2]
        for de in np.arange(cen_e - r, cen_e + r + 1e-9, s):
            for dn in np.arange(cen_n - r, cen_n + r + 1e-9, s):
                v = puntaje(de, dn)
                if v > mejor[0]:
                    mejor = (v, float(de), float(dn))
    return mejor[1], mejor[2], mejor[0], inicial
