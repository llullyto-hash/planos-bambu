"""Analiza un plano de demoliciones (DXF) y genera un diagnostico.

Uso:
    python demoliciones/analizar_plano.py "PLANO DEMOLICIONES.dxf" -o salida/

Genera en la carpeta de salida:
    resumen.md        diagnostico de capas, bloques, layout y problemas
    etiquetas.csv     cada etiqueta (VD, MT, CL, DPV, CAN D, SAR D) contra
                      la geometria del modelo a la que apunta su flecha
    vista_demoliciones.png  vista rapida de los elementos a demoler
"""
import argparse
import collections
import csv
import re
from pathlib import Path

import ezdxf
from ezdxf import bbox, recover
from ezdxf import path as dxfpath
from ezdxf.math import Vec2, area, is_point_in_polygon_2d

# Prefijo de etiqueta -> capas del modelo donde debe estar su geometria.
CODIGOS = {
    "VD": ("Vereda a demoler", "Vereda a demoler Mz. 27"),
    "MT": ("Martillo a demoler",),
    "CL": ("LINEA CORTE", "Corte Lineal"),
    "DPV": ("Pav. Existente a Demoler",),
    "CAN D": ("Canaleta a demoler",),
    "SAR D": ("SARDINEL P", "SARDINEL PP"),
}
CAPAS_DEMOLICION = sorted({c for capas in CODIGOS.values() for c in capas} | {"Alc a demoler"})
CAPA_ETIQUETAS = "TEXTO EN MARTILLO"
RE_ETIQUETA = re.compile(
    r"\s*([A-Z ]+?)\s*-\s*([\d\-]+)\s+(AREA|LONG|VOL)\s*=\s*([\d.]+)\s*(M\d?)"
)
TOL_DISTANCIA = 2.0  # m entre la punta de la flecha y la geometria
TOL_RELATIVA = 0.02  # 2 % de diferencia en area/longitud


def capa(e):
    return e.dxf.layer if e.dxf.is_supported("layer") else "0"


def dist_segmento(p, a, b):
    ab = b - a
    if ab.magnitude == 0:
        return p.distance(a)
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab.magnitude**2))
    return p.distance(a + ab * t)


def geometria_demolicion(msp):
    """Lista de (capa, tipo, handle, puntos, magnitud) en capas de demolicion."""
    geo = []
    for e in msp.query("LWPOLYLINE LINE HATCH"):
        if e.dxf.layer not in CAPAS_DEMOLICION:
            continue
        h = e.dxf.handle
        if e.dxftype() == "LINE":
            pts = [Vec2(e.dxf.start), Vec2(e.dxf.end)]
            geo.append((e.dxf.layer, "linea", h, pts, pts[0].distance(pts[1])))
        elif e.dxftype() == "LWPOLYLINE":
            pts = [Vec2(p) for p in e.get_points("xy")]
            if e.closed or (len(pts) > 2 and pts[0].isclose(pts[-1], abs_tol=1e-3)):
                geo.append((e.dxf.layer, "poligono", h, pts, abs(area(pts))))
            else:
                largo = sum(pts[i].distance(pts[i + 1]) for i in range(len(pts) - 1))
                geo.append((e.dxf.layer, "polilinea", h, pts, largo))
        else:
            for bp in e.paths:
                try:
                    pts = [Vec2(v) for v in dxfpath.from_hatch_boundary_path(bp).flattening(0.01)]
                except Exception:
                    continue
                if len(pts) > 2:
                    geo.append((e.dxf.layer, "achurado", h, pts, abs(area(pts))))
    return geo


def viewport_principal(layout):
    vps = [v for v in layout.query("VIEWPORT") if v.dxf.id != 1]
    return max(vps, key=lambda v: v.dxf.width * v.dxf.height) if vps else None


def papel_a_modelo(vp):
    d = vp.dxf
    k = d.view_height / d.height
    base = Vec2(d.view_target_point) + Vec2(d.view_center_point)
    centro = Vec2(d.center)
    return k, lambda p: base + (Vec2(p) - centro) * k


def revisar_etiquetas(layout, geo):
    vp = viewport_principal(layout)
    if vp is None:
        return []
    _, a_modelo = papel_a_modelo(vp)
    flechas = [
        (Vec2(l.vertices[0]), Vec2(l.vertices[-1]))
        for l in layout.query("LEADER")
        if l.dxf.layer == CAPA_ETIQUETAS
    ]
    filas = []
    for t in layout.query("MTEXT"):
        if t.dxf.layer != CAPA_ETIQUETAS:
            continue
        texto = t.plain_text().replace("\n", " ").strip()
        m = RE_ETIQUETA.match(texto)
        if not m:
            filas.append({"etiqueta": texto, "estado": "NO SE PUDO LEER"})
            continue
        codigo, num, tipo, valor, unidad = m.groups()
        codigo, valor = codigo.strip(), float(valor)
        fila = {"etiqueta": f"{codigo}-{num}", "tipo": tipo, "valor_etiqueta": valor, "unidad": unidad}
        if tipo == "VOL" and unidad != "M3":
            fila["observacion"] = f"Volumen con unidad {unidad}"
        if not flechas:
            fila["estado"] = "SIN FLECHA"
            filas.append(fila)
            continue
        ins = Vec2(t.dxf.insert)
        punta = a_modelo(min(flechas, key=lambda f: f[1].distance(ins))[0])
        fila["x"], fila["y"] = round(punta.x, 3), round(punta.y, 3)
        if tipo == "VOL":
            fila["estado"] = "NO VERIFICABLE (falta espesor)"
            filas.append(fila)
            continue
        mejor = None
        for lay, tg, h, pts, mag in geo:
            if lay not in CODIGOS.get(codigo, CAPAS_DEMOLICION):
                continue
            if tipo == "AREA" and tg in ("poligono", "achurado"):
                dentro = is_point_in_polygon_2d(punta, pts) >= 0
                d = 0.0 if dentro else min(
                    dist_segmento(punta, pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))
                )
            elif tipo == "LONG" and tg in ("linea", "polilinea"):
                d = min(dist_segmento(punta, pts[i], pts[i + 1]) for i in range(len(pts) - 1))
            else:
                continue
            # Entre las cercanas gana la de magnitud parecida; si ninguna esta cerca, la mas proxima.
            lejos = d > TOL_DISTANCIA
            clave = (lejos, d if lejos else abs(mag - valor))
            if mejor is None or clave < mejor[0]:
                mejor = (clave, d, mag, lay, tg, h)
        if mejor is None:
            fila["estado"] = "SIN GEOMETRIA"
        else:
            _, d, mag, lay, tg, h = mejor
            fila.update(valor_dibujo=round(mag, 2), diferencia=round(mag - valor, 2),
                        distancia_m=round(d, 2), capa=lay, entidad=tg, handle=h)
            ok_d = d <= TOL_DISTANCIA
            ok_v = abs(mag - valor) <= TOL_RELATIVA * max(valor, 1) + 0.01
            fila["estado"] = "OK" if ok_d and ok_v else ("REVISAR VALOR" if ok_d else "SIN GEOMETRIA CERCA")
        filas.append(fila)
    # Etiquetas que apuntan a la misma entidad
    usos = collections.Counter(f.get("handle") for f in filas if f.get("handle"))
    for f in filas:
        if f.get("handle") and usos[f["handle"]] > 1 and f["estado"] != "OK":
            f["observacion"] = (f.get("observacion", "") + " Entidad compartida con otra etiqueta").strip()
    return filas


def diagnostico_capas(doc):
    usados = collections.Counter()
    for contenedor in list(doc.layouts) + list(doc.blocks):
        for e in contenedor:
            usados[capa(e)] += 1
    sin_uso = sorted(l.dxf.name for l in doc.layers if usados[l.dxf.name] == 0)
    apagadas = [(l.dxf.name, usados[l.dxf.name]) for l in doc.layers
                if (l.is_off() or l.is_frozen()) and usados[l.dxf.name]]
    norm = lambda n: re.sub(r"[^a-z0-9]", "", n.lower().replace("proy", "pry"))
    grupos = collections.defaultdict(list)
    for l in doc.layers:
        grupos[norm(l.dxf.name)].append(l.dxf.name)
    duplicadas = [g for g in grupos.values() if len(g) > 1]
    return usados, sin_uso, apagadas, duplicadas


def entidades_fuera_de_zona(msp, margen=10000.0):
    """Entidades lejos de la mediana del dibujo (rompen el Zoom Extents)."""
    centros = []
    cajas = []
    for e in msp:
        try:
            b = bbox.extents([e], fast=True)
        except Exception:
            continue
        if b.has_data:
            cajas.append((e, b))
            centros.append(b.center)
    if not centros:
        return [], None
    xs = sorted(c.x for c in centros)
    ys = sorted(c.y for c in centros)
    med = Vec2(xs[len(xs) // 2], ys[len(ys) // 2])
    fuera = [e for e, b in cajas if Vec2(b.center).distance(med) > margen]
    return fuera, med


def vista_rapida(geo, filas, destino, ventana=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colores = {}
    fig, ax = plt.subplots(figsize=(16, 16))
    paleta = plt.get_cmap("tab10")
    for lay, tg, _, pts, _ in geo:
        c = colores.setdefault(lay, paleta(len(colores) % 10))
        xs, ys = [p.x for p in pts], [p.y for p in pts]
        if tg in ("poligono", "achurado"):
            ax.fill(xs, ys, color=c, alpha=0.35, lw=0.3)
        else:
            ax.plot(xs, ys, color=c, lw=0.8)
    for f in filas:
        if "x" in f:
            color = "green" if f["estado"] == "OK" else "red"
            ax.plot(f["x"], f["y"], "o", ms=3, color=color)
            ax.annotate(f["etiqueta"], (f["x"], f["y"]), fontsize=4, color=color)
    for lay, c in colores.items():
        ax.plot([], [], color=c, lw=6, label=lay)
    ax.legend(loc="upper right", fontsize=8)
    if ventana:
        (x0, y0), (x1, y1) = ventana
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.set_title("Elementos a demoler (verde = etiqueta OK, rojo = revisar)")
    fig.savefig(destino, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dxf")
    ap.add_argument("-o", "--salida", default="salida_analisis")
    ap.add_argument("--layout", default=None, help="Nombre de la lamina (por defecto la primera)")
    args = ap.parse_args()

    out = Path(args.salida)
    out.mkdir(parents=True, exist_ok=True)
    doc, auditor = recover.readfile(args.dxf)
    msp = doc.modelspace()
    layouts = [l for l in doc.layouts if l.name != "Model"]
    layout = doc.layouts.get(args.layout) if args.layout else layouts[0]

    geo = geometria_demolicion(msp)
    filas = revisar_etiquetas(layout, geo)
    usados, sin_uso, apagadas, duplicadas = diagnostico_capas(doc)
    fuera, mediana = entidades_fuera_de_zona(msp)

    campos = ["etiqueta", "tipo", "valor_etiqueta", "unidad", "valor_dibujo", "diferencia",
              "distancia_m", "capa", "entidad", "handle", "x", "y", "estado", "observacion"]
    with open(out / "etiquetas.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, campos)
        w.writeheader()
        w.writerows(filas)
    ventana = None
    vp_ = viewport_principal(layout)
    if vp_ is not None:
        k_, a_modelo = papel_a_modelo(vp_)
        c_ = Vec2(vp_.dxf.center)
        mitad = Vec2(vp_.dxf.width / 2, vp_.dxf.height / 2)
        ventana = (a_modelo(c_ - mitad), a_modelo(c_ + mitad))
    vista_rapida(geo, filas, out / "vista_demoliciones.png", ventana)

    estados = collections.Counter(f["estado"] for f in filas)
    tipos = collections.Counter(e.dxftype() for e in msp)
    ref = collections.Counter()
    for c in list(doc.layouts) + list(doc.blocks):
        for e in c.query("INSERT"):
            ref[e.dxf.name] += 1
    bloques_sin_uso = [b.name for b in doc.blocks if not b.name.startswith("*") and ref[b.name] == 0]
    totales = collections.defaultdict(float)
    for f in filas:
        if "valor_etiqueta" in f:
            totales[(f["etiqueta"].split("-")[0], f["unidad"])] += f["valor_etiqueta"]

    vp = viewport_principal(layout)
    L = []
    L.append(f"# Analisis: {Path(args.dxf).name}\n")
    L.append(f"- Version DXF: {doc.dxfversion}, unidades $INSUNITS={doc.header.get('$INSUNITS')}")
    L.append(f"- Entidades en modelo: {len(msp)} ({', '.join(f'{k} {v}' for k, v in tipos.most_common(8))})")
    L.append(f"- Capas: {len(doc.layers)} (sin uso: {len(sin_uso)}); bloques sin uso: {len(bloques_sin_uso)}")
    L.append(f"- Laminas: {', '.join(l.name for l in layouts)}")
    if vp is not None:
        k, _ = papel_a_modelo(vp)
        lay_dxf = layout.dxf_layout.dxf
        L.append(f"- Lamina {layout.name}: papel {lay_dxf.get('paper_width')}x{lay_dxf.get('paper_height')} mm, "
                 f"plotter '{lay_dxf.get('plot_configuration_file')}', estilo '{lay_dxf.get('current_style_sheet')}', "
                 f"escala ventana 1:{round(k * 1000)}, capas congeladas en ventana: {list(vp.frozen_layers)}")
    L.append("\n## Metrados segun etiquetas\n")
    for (cod, und), v in sorted(totales.items()):
        L.append(f"- {cod}: {v:,.2f} {und}")
    L.append("\n## Verificacion de etiquetas contra el dibujo\n")
    for k_, v in estados.most_common():
        L.append(f"- {k_}: {v}")
    L.append("\nDetalle de las que no estan OK:\n")
    L.append("| Etiqueta | Valor etiqueta | Valor dibujo | Dif. | Dist. (m) | Capa | Estado | Obs. |")
    L.append("|---|---|---|---|---|---|---|---|")
    for f in filas:
        if f["estado"] != "OK":
            L.append(f"| {f['etiqueta']} | {f.get('valor_etiqueta', '')} {f.get('unidad', '')} | "
                     f"{f.get('valor_dibujo', '')} | {f.get('diferencia', '')} | {f.get('distancia_m', '')} | "
                     f"{f.get('capa', '')} | {f['estado']} | {f.get('observacion', '')} |")
    L.append("\n## Capas\n")
    L.append(f"- Apagadas/congeladas con contenido: {apagadas}")
    L.append(f"- Nombres casi duplicados: {duplicadas}")
    L.append(f"- Sin uso ({len(sin_uso)}): {', '.join(sin_uso)}")
    L.append("\n## Geometria fuera de la zona del proyecto\n")
    zona = collections.Counter((e.dxftype(), capa(e)) for e in fuera)
    L.append(f"- Centro del dibujo aprox.: {mediana}; entidades a mas de 10 km: {len(fuera)}")
    for (t, c), n in zona.most_common(15):
        L.append(f"  - {t} en '{c}': {n}")
    L.append(f"\n- Correcciones aplicadas al leer el archivo: {len(auditor.fixes)}")
    (out / "resumen.md").write_text("\n".join(L), encoding="utf-8")
    print(f"Listo: {out}/resumen.md, etiquetas.csv, vista_demoliciones.png")
    print(dict(estados))


if __name__ == "__main__":
    main()
