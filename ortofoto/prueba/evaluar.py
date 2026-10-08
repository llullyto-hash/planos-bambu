"""Compara las uniones generadas con las lineas que dibujo el proyectista.

Una union es CORRECTA si al menos el 80 % de su recorrido esta a menos de
`tol` metros de alguna linea del plano de referencia. Se evalua con y sin
ortofoto para medir cuanto ayuda la foto.

python -m ortofoto.prueba.evaluar --orto foto.png --puntos puntos.csv --referencia PLANO.dxf --ventana ...
"""
import argparse
import collections
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from .. import areas, calce, exportar, topografia, unir
from ..__main__ import CODIGOS_BORDE, CODIGOS_DEFECTO
from ..imagen import Ortofoto

NO_REFERENCIA = {"C-TOPO-MNR", "CURVA MENOR EXISTENTE", "CURVA MAYOR EXISTENTE", "Cuadricula Coordenadas",
                 "_ Alineamiento", "Corte Lineal", "LINEA CORTE", "JUNTA T1"}


def lineas_referencia(ruta, ventana):
    from ezdxf import bbox, recover
    from ezdxf import path as dxfpath

    doc, _ = recover.readfile(ruta)
    x0, y0, x1, y1 = ventana
    lineas = []
    for e in doc.modelspace().query("LWPOLYLINE LINE HATCH ARC"):
        if e.dxf.layer in NO_REFERENCIA:
            continue
        try:
            b = bbox.extents([e], fast=True)
        except Exception:
            continue
        if not b.has_data or b.extmax.x < x0 or b.extmin.x > x1 or b.extmax.y < y0 or b.extmin.y > y1:
            continue
        try:
            caminos = ([dxfpath.from_hatch_boundary_path(bp) for bp in e.paths] if e.dxftype() == "HATCH"
                       else [dxfpath.make_path(e)])
        except Exception:
            continue
        for c in caminos:
            v = [(p.x, p.y) for p in c.flattening(0.02)]
            if len(v) > 1:
                lineas.append(v)
    return lineas


def _densificar(lineas, paso=0.05):
    pts = []
    for v in lineas:
        v = np.asarray(v)
        for a, b in zip(v[:-1], v[1:]):
            n = max(2, int(np.hypot(*(b - a)) / paso))
            pts.append(a + np.outer(np.linspace(0, 1, n), b - a))
    return np.vstack(pts)


def evaluar(resultados, arbol, tol=0.3, revisar=None):
    """revisar=None: todas las uniones; False: solo las confirmadas; True: solo las marcadas."""
    por_codigo = {}
    for r in resultados:
        ok = tot = 0
        for u in r.uniones:
            if revisar is not None and u.revisar != revisar:
                continue
            a = np.array([r.puntos[u.i].e, r.puntos[u.i].n])
            b = np.array([r.puntos[u.j].e, r.puntos[u.j].n])
            m = np.linspace(0.05, 0.95, 15)
            d, _ = arbol.query(a + np.outer(m, b - a))
            tot += 1
            ok += np.mean(d < tol) >= 0.8
        if tot:
            por_codigo[r.codigo] = (ok, tot)
    return por_codigo


def areas_referencia(ruta, ventana, capas):
    """Poligonos dibujados por el proyectista en las capas de area (p.ej. 'Vereda a demoler')."""
    from ezdxf import recover
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    doc, _ = recover.readfile(ruta)
    zona = box(*ventana)
    pols = []
    for e in doc.modelspace().query("LWPOLYLINE"):
        if e.dxf.layer in capas and e.closed and len(e) > 2:
            p = Polygon([(x, y) for x, y in e.get_points("xy")]).buffer(0)
            if p.intersects(zona):
                pols.append(p)
    return unary_union(pols) if pols else None


def comparar_areas(met, ref):
    from shapely.ops import unary_union

    if ref is None or not met.areas:
        return None
    gen = unary_union([a.poligono for a in met.areas if a.conf.capa_area in CAPAS_AREA])
    if gen.is_empty:
        return None
    inter = gen.intersection(ref).area
    return inter / gen.area, inter / ref.area, gen.area, ref.area


CAPAS_AREA = {"Vereda a demoler"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orto", required=True)
    ap.add_argument("--puntos", required=True)
    ap.add_argument("--referencia", required=True)
    ap.add_argument("--ventana", type=float, nargs=4, required=True)
    ap.add_argument("-o", "--salida", default="evaluacion")
    args = ap.parse_args(argv)
    out = Path(args.salida)
    out.mkdir(parents=True, exist_ok=True)

    codigos, alias = unir.cargar_codigos(CODIGOS_DEFECTO)
    puntos = topografia.leer(args.puntos)
    ref = lineas_referencia(args.referencia, args.ventana)
    arbol = cKDTree(_densificar(ref))

    orto = Ortofoto.abrir(args.orto)
    borde = [p for p in puntos if alias.get(p.codigo, p.codigo) in CODIGOS_BORDE]
    de, dn, *_ = calce.calce_automatico(orto, borde)
    orto.desplazar(de, dn)

    filas = []
    totales = collections.Counter()
    res_sin, _ = unir.unir_todo(puntos, codigos, None, alias=alias)
    met_sin = areas.cerrar_areas(res_sin)
    res_con, _ = unir.unir_todo(puntos, codigos, orto, alias=alias)
    met_con = areas.cerrar_areas(res_con)
    ev_sin, ev_con = evaluar(res_sin, arbol), evaluar(res_con, arbol, revisar=False)
    ev_rev = evaluar(res_con, arbol, revisar=True)
    for cod in sorted(set(ev_sin) | set(ev_con)):
        s, c = ev_sin.get(cod, (0, 0)), ev_con.get(cod, (0, 0))
        totales["sin_ok"] += s[0]; totales["sin"] += s[1]; totales["con_ok"] += c[0]; totales["con"] += c[1]
        filas.append(f"| {cod} | {s[0]}/{s[1]} ({s[0] / max(s[1], 1):.0%}) | {c[0]}/{c[1]} ({c[0] / max(c[1], 1):.0%}) |")
    t = totales
    texto = "\n".join([
        f"Calce automatico: dE={de:+.2f} dN={dn:+.2f}",
        "",
        "| Codigo | Solo geometria (correctas/total) | Con ortofoto, confirmadas por la foto |",
        "|---|---|---|", *filas,
        f"| **Total** | **{t['sin_ok']}/{t['sin']} ({t['sin_ok'] / max(t['sin'], 1):.0%})** | "
        f"**{t['con_ok']}/{t['con']} ({t['con_ok'] / max(t['con'], 1):.0%})** |",
    ])
    ok_r, tot_r = (sum(v[0] for v in ev_rev.values()), sum(v[1] for v in ev_rev.values()))
    texto += (f"\n\nCon ortofoto, ademas se unieron {tot_r} tramos que la foto no confirma (capa REVISAR UNION); "
              f"de esos, {ok_r} ({ok_r / max(tot_r, 1):.0%}) coinciden con el dibujo.")
    ref_areas = areas_referencia(args.referencia, args.ventana, CAPAS_AREA)
    for nombre, met in (("solo geometria", met_sin), ("con ortofoto", met_con)):
        c = comparar_areas(met, ref_areas)
        if c:
            texto += (f"\n\nVeredas ({nombre}): {c[0]:.0%} del area generada coincide con lo dibujado; "
                      f"cubre {c[1]:.0%} de lo dibujado ({c[2]:.0f} m2 generados, {c[3]:.0f} m2 dibujados)")
    (out / "evaluacion.md").write_text(texto + "\n", encoding="utf-8")
    print(texto)
    exportar.guardar_vista(res_sin, out / "vista_sin_foto.png", orto, ref, met_sin)
    exportar.guardar_vista(res_con, out / "vista_con_foto.png", orto, ref, met_con)


if __name__ == "__main__":
    main()
