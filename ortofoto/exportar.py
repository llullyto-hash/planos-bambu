"""Salida: DXF con polilineas por capa y vista PNG para revision."""
from pathlib import Path

import numpy as np

CAPA_PUNTOS = "TOPO-PUNTOS"
CAPA_REVISAR = "REVISAR UNION"
CAPA_ORTOFOTO = "ORTOFOTO"


def _capa(doc, nombre, color=7, tipo_linea="Continuous", plantilla=None):
    if nombre in doc.layers:
        return
    if plantilla is not None and nombre in plantilla.layers:
        ref = plantilla.layers.get(nombre)
        color, tipo_linea = ref.dxf.color, ref.dxf.linetype
        lw = ref.dxf.lineweight
    else:
        lw = -3
    if tipo_linea not in doc.linetypes:
        tipo_linea = "Continuous"
    doc.layers.add(nombre, color=abs(color), linetype=tipo_linea, lineweight=lw)


def guardar_dxf(resultados, codigos, ruta, orto=None, ruta_imagen=None, plantilla=None, puntos=None):
    import ezdxf

    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 6  # metros
    tpl = ezdxf.readfile(plantilla) if plantilla else None
    msp = doc.modelspace()
    _capa(doc, CAPA_PUNTOS, 8)
    _capa(doc, CAPA_REVISAR, 1)
    # Todos los puntos, incluso los de codigos sin configurar
    for p in puntos if puntos is not None else [p for r in resultados for p in r.puntos]:
        msp.add_point((p.e, p.n, p.z), dxfattribs={"layer": CAPA_PUNTOS})
        msp.add_text(f"{p.num} {p.desc}", height=0.12,
                     dxfattribs={"layer": CAPA_PUNTOS}).set_placement((p.e + 0.1, p.n + 0.1))
    for r in resultados:
        conf = codigos[r.codigo]
        _capa(doc, conf.capa, conf.color, conf.tipo_linea, tpl)
        for cad in r.cadenas:
            cerrada = cad[0] == cad[-1]
            idx = cad[:-1] if cerrada else cad
            pl = msp.add_lwpolyline([(r.puntos[i].e, r.puntos[i].n) for i in idx],
                                    dxfattribs={"layer": conf.capa})
            pl.closed = cerrada
        for u in r.uniones:
            if u.revisar:
                a, b = r.puntos[u.i], r.puntos[u.j]
                msp.add_line((a.e, a.n), (b.e, b.n), dxfattribs={"layer": CAPA_REVISAR, "lineweight": 50})
    if orto is not None and ruta_imagen:
        # Foto de fondo con el calce ya corregido
        _capa(doc, CAPA_ORTOFOTO, 7)
        h, w = orto.rgb.shape[:2]
        a, b, c, d, e, f = orto.afin
        idef = doc.add_image_def(filename=str(ruta_imagen), size_in_pixel=(w, h))
        ins = (a * 0 + b * h + c, d * 0 + e * h + f)
        img = msp.add_image(idef, insert=ins, size_in_units=(w * orto.tam_pixel, h * orto.tam_pixel),
                            dxfattribs={"layer": CAPA_ORTOFOTO})
        img.dxf.u_pixel = (a, d, 0)
        img.dxf.v_pixel = (-b, -e, 0)
        # La imagen va al fondo
        msp.set_redraw_order([(img.dxf.handle, "1")])
    doc.saveas(ruta)


def guardar_vista(resultados, ruta, orto=None, referencia=None, max_px=5000, ventana=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    todos = np.array([(p.e, p.n) for r in resultados for p in r.puntos])
    if ventana is None:
        x0, y0 = todos.min(axis=0) - 5
        x1, y1 = todos.max(axis=0) + 5
    else:
        x0, y0, x1, y1 = ventana
    fig, ax = plt.subplots(figsize=(16, 16 * (y1 - y0) / max(x1 - x0, 1)))
    if orto is not None:
        c0, f0 = orto.a_pixel(np.array([x0, x1]), np.array([y1, y0]))
        c0 = np.clip(np.sort(c0).astype(int), 0, orto.rgb.shape[1])
        f0 = np.clip(np.sort(f0).astype(int), 0, orto.rgb.shape[0])
        paso = max(1, int(max(c0[1] - c0[0], f0[1] - f0[0]) / max_px))
        rec = orto.rgb[f0[0]:f0[1]:paso, c0[0]:c0[1]:paso]
        e0, n0 = orto.a_terreno(c0[0], f0[0])
        e1, n1 = orto.a_terreno(c0[1], f0[1])
        ax.imshow(rec, extent=(e0, e1, n1, n0), interpolation="bilinear")
    if referencia:
        for linea in referencia:
            ax.plot(*np.array(linea).T, color="white", lw=2.2, alpha=0.6)
    paleta = plt.get_cmap("tab10")
    for k, r in enumerate(resultados):
        col = paleta(k % 10)
        xy = np.array([(p.e, p.n) for p in r.puntos])
        ax.plot(xy[:, 0], xy[:, 1], "o", ms=2.5, color=col, mec="black", mew=0.3)
        for u in r.uniones:
            seg = xy[[u.i, u.j]]
            ax.plot(seg[:, 0], seg[:, 1], color="red" if u.revisar else col, lw=1.6 if u.revisar else 1.1,
                    ls="--" if u.revisar else "-")
        ax.plot([], [], color=col, lw=3, label=f"{r.codigo} ({len(r.puntos)} pts, {len(r.cadenas)} lineas)")
    ax.plot([], [], color="red", ls="--", label="union a revisar")
    if referencia:
        ax.plot([], [], color="white", lw=3, alpha=0.6, label="dibujo de referencia")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.ticklabel_format(useOffset=False, style="plain")
    fig.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close(fig)
