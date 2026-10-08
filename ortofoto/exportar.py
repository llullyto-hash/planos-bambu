"""Salida: DXF por capas (puntos, bordes, areas con achurado, etiquetas) y vista PNG."""
from pathlib import Path

import numpy as np

from .areas import punto_etiqueta

PREFIJO_PUNTOS = "PT-"  # una capa de puntos por codigo: PT-VER, PT-CNTA...
CAPA_REVISAR = "REVISAR UNION"
CAPA_REVISAR_AREA = "REVISAR AREA"
CAPA_SIN_PAREJA = "REVISAR BORDE SIN CERRAR"
CAPA_ETIQUETAS = "TEXTO METRADO"
CAPA_PUNTO_FOTO = "REVISAR PUNTO VS FOTO"
CAPA_ORTOFOTO = "ORTOFOTO"
ALTURA_TEXTO = 0.25


def _capa(doc, nombre, color=7, tipo_linea="Continuous", plantilla=None, apagada=False):
    if nombre in doc.layers:
        return doc.layers.get(nombre)
    lw = -3
    if plantilla is not None and nombre in plantilla.layers:
        ref = plantilla.layers.get(nombre)
        color, tipo_linea, lw = ref.dxf.color, ref.dxf.linetype, ref.dxf.lineweight
    if tipo_linea not in doc.linetypes:
        tipo_linea = "Continuous"
    capa = doc.layers.add(nombre, color=abs(color) or 7, linetype=tipo_linea, lineweight=lw)
    if apagada:
        capa.off()
    return capa


def guardar_dxf(ruta, puntos, resultados, metrado, codigos, alias=None, orto=None, plantilla=None,
                capas_apagadas=(), base_dxf=None):
    """Guarda el resultado. Con `base_dxf` se trabaja sobre una copia del plano del proyecto:
    se conserva todo lo original (lotes, fachadas, ortofoto) y se agregan las capas nuevas."""
    import ezdxf

    alias = alias or {}
    if base_dxf:
        from ezdxf import recover

        doc, _ = recover.readfile(base_dxf)
    else:
        doc = ezdxf.new("R2018", setup=True)
        doc.header["$INSUNITS"] = 6  # metros
    tpl = None
    if plantilla:
        from ezdxf import recover

        tpl, _ = recover.readfile(plantilla)
    msp = doc.modelspace()
    for nombre, color in ((CAPA_REVISAR, 1), (CAPA_REVISAR_AREA, 1), (CAPA_SIN_PAREJA, 6), (CAPA_ETIQUETAS, 7)):
        _capa(doc, nombre, color, plantilla=tpl)

    # Puntos visibles: circulo con cruz de 25 cm (si no, AutoCAD los dibuja como un punto diminuto)
    doc.header["$PDMODE"] = 34
    doc.header["$PDSIZE"] = 0.25
    # Puntos: una capa por codigo, para poder apagarlos y unir a mano
    for p in puntos:
        cod = alias.get(p.codigo, p.codigo) or "SIN-CODIGO"
        conf = codigos.get(cod)
        capa = PREFIJO_PUNTOS + cod
        _capa(doc, capa, conf.color if conf else 8, apagada=capa in capas_apagadas)
        msp.add_point((p.e, p.n, p.z), dxfattribs={"layer": capa})
        msp.add_text(f"{p.num} {p.desc} {p.z:.2f}", height=0.1, dxfattribs={"layer": capa}).set_placement(
            (p.e + 0.08, p.n + 0.08))

    # Bordes unidos
    for r in resultados:
        conf = r.conf
        if conf.tipo == "punto":
            continue
        _capa(doc, conf.capa, conf.color, conf.tipo_linea, tpl, conf.capa in capas_apagadas)
        for cad in r.cadenas:
            cerrada = cad[0] == cad[-1]
            idx = cad[:-1] if cerrada else cad
            pl = msp.add_lwpolyline([(r.puntos[i].e, r.puntos[i].n) for i in idx], dxfattribs={"layer": conf.capa})
            pl.closed = cerrada
        for u in r.uniones:
            if u.revisar:
                a, b = r.puntos[u.i], r.puntos[u.j]
                msp.add_line((a.e, a.n), (b.e, b.n), dxfattribs={"layer": CAPA_REVISAR})

    # Bordes de franja que no encontraron su pareja: hay que cerrarlos a mano
    for ln in metrado.lineas:
        if ln.borde:
            msp.add_lwpolyline(list(ln.linea.coords), dxfattribs={"layer": ln.conf.capa})
        elif ln.sin_pareja:
            msp.add_lwpolyline(list(ln.linea.coords), dxfattribs={"layer": CAPA_SIN_PAREJA})
        elif ln.etiqueta:
            x, y = ln.linea.interpolate(0.5, normalized=True).coords[0]
            msp.add_mtext(f"{ln.etiqueta}\\PLONG={ln.linea.length:.2f}M",
                          dxfattribs={"layer": CAPA_ETIQUETAS, "char_height": ALTURA_TEXTO, "insert": (x, y),
                                      "attachment_point": 5})

    # Areas cerradas + achurado + etiqueta tipo PETRO
    for ar in metrado.areas:
        conf = ar.conf
        _capa(doc, conf.capa_area, conf.color_area or conf.color, plantilla=tpl,
              apagada=conf.capa_area in capas_apagadas)
        exterior = list(ar.poligono.exterior.coords)[:-1]
        attrs = {"layer": conf.capa_area}
        msp.add_lwpolyline(exterior, close=True, dxfattribs=attrs)
        h = msp.add_hatch(dxfattribs=attrs)
        if conf.patron.upper() == "SOLID":
            h.set_solid_fill(color=256)
            h.transparency = 0.5
        else:
            h.set_pattern_fill(conf.patron, scale=conf.escala_patron, color=256)
        h.paths.add_polyline_path(exterior, is_closed=True)
        for agujero in ar.poligono.interiors:
            h.paths.add_polyline_path(list(agujero.coords)[:-1], is_closed=True)
        x, y = punto_etiqueta(ar.poligono)
        msp.add_mtext(f"{ar.etiqueta}\\PAREA= {ar.area:.2f} M2",
                      dxfattribs={"layer": CAPA_ETIQUETAS, "char_height": ALTURA_TEXTO, "insert": (x, y),
                                  "attachment_point": 5})
        if ar.revisar:
            msp.add_lwpolyline(exterior, close=True, dxfattribs={"layer": CAPA_REVISAR_AREA, "lineweight": 50})

    # Puntos que no calzan con lo que se ve en la ortofoto
    if metrado.puntos_revisar:
        _capa(doc, CAPA_PUNTO_FOTO, 1)
        for x, y, motivo in metrado.puntos_revisar:
            msp.add_circle((x, y), 0.4, dxfattribs={"layer": CAPA_PUNTO_FOTO})
            msp.add_text(motivo, height=0.15, dxfattribs={"layer": CAPA_PUNTO_FOTO}).set_placement((x + 0.5, y + 0.2))

    # Concreto visto en la foto sin puntos topograficos que lo respalden (solo contorno, sin metrado)
    if metrado.sin_puntos:
        _capa(doc, "REVISAR CONCRETO SIN PUNTOS", 6)
        for g in metrado.sin_puntos:
            msp.add_lwpolyline(list(g.exterior.coords)[:-1], close=True,
                               dxfattribs={"layer": "REVISAR CONCRETO SIN PUNTOS"})

    # Ortofoto de fondo: el archivo original, con el calce corregido (no se copia).
    # Si se trabaja sobre el plano del proyecto, la foto ya esta insertada ahi.
    if orto is not None and orto.origen is not None and not base_dxf:
        _capa(doc, CAPA_ORTOFOTO, 7)
        w, h = orto.origen["tam"]
        a, b, c, d, e, f = orto.origen["afin"]
        idef = doc.add_image_def(filename=orto.origen["ruta"], size_in_pixel=(w, h))
        tam = float(np.hypot(a, d))
        img = msp.add_image(idef, insert=(b * h + c, e * h + f), size_in_units=(w * tam, h * tam),
                            dxfattribs={"layer": CAPA_ORTOFOTO})
        img.dxf.u_pixel = (a, d, 0)
        img.dxf.v_pixel = (-b, -e, 0)
        msp.set_redraw_order([(img.dxf.handle, "1")])
    doc.saveas(ruta)


def guardar_vista(resultados, ruta, orto=None, referencia=None, metrado=None, max_px=4000, ventana=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    todos = np.array([(p.e, p.n) for r in resultados for p in r.puntos])
    if ventana is None:
        x0, y0 = todos.min(axis=0) - 5
        x1, y1 = todos.max(axis=0) + 5
    else:
        x0, y0, x1, y1 = ventana
    ancho = 16
    fig, ax = plt.subplots(figsize=(ancho, ancho * (y1 - y0) / max(x1 - x0, 1)))
    if orto is not None:
        cs, fs = orto.a_pixel(np.array([x0, x1]), np.array([y1, y0]))
        c0 = np.clip(np.sort(cs).astype(int), 0, orto.rgb.shape[1])
        f0 = np.clip(np.sort(fs).astype(int), 0, orto.rgb.shape[0])
        paso = max(1, int(max(c0[1] - c0[0], f0[1] - f0[0]) / max_px))
        rec = orto.rgb[f0[0]:f0[1]:paso, c0[0]:c0[1]:paso]
        e0, n0 = orto.a_terreno(c0[0], f0[0])
        e1, n1 = orto.a_terreno(c0[1], f0[1])
        ax.imshow(rec, extent=(e0, e1, n1, n0), interpolation="bilinear")
    if referencia:
        for linea in referencia:
            ax.plot(*np.array(linea).T, color="white", lw=2.2, alpha=0.6)
    paleta = plt.get_cmap("tab10")
    colores = {}
    for k, r in enumerate(resultados):
        col = colores.setdefault(r.codigo, paleta(k % 10))
        xy = np.array([(p.e, p.n) for p in r.puntos])
        ax.plot(xy[:, 0], xy[:, 1], "o", ms=1.8, color=col, mec="black", mew=0.2)
        for u in r.uniones:
            seg = xy[[u.i, u.j]]
            ax.plot(seg[:, 0], seg[:, 1], color="red" if u.revisar else col, lw=1.4 if u.revisar else 0.9,
                    ls="--" if u.revisar else "-")
        etiqueta = f"{r.codigo} ({len(r.puntos)} pts"
        etiqueta += f", {len(r.cadenas)} lineas)" if r.conf.tipo != "punto" else ")"
        ax.plot([], [], color=col, lw=3, label=etiqueta)
    if metrado is not None:
        for ar in metrado.areas:
            col = colores.get(ar.codigo, "gray")
            xs, ys = ar.poligono.exterior.xy
            ax.fill(xs, ys, color=col, alpha=0.35, lw=0)
            if ar.revisar:
                ax.plot(xs, ys, color="red", lw=1)
            x, y = punto_etiqueta(ar.poligono)
            ax.text(x, y, ar.etiqueta, fontsize=3.5, ha="center", va="center")
        for ln in metrado.lineas:
            if ln.sin_pareja:
                ax.plot(*ln.linea.xy, color="magenta", lw=1.2, ls=":")
        ax.plot([], [], color="magenta", ls=":", label="borde sin cerrar")
    ax.plot([], [], color="red", ls="--", label="union a revisar")
    ax.legend(loc="upper right", fontsize=7, framealpha=0.85)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.ticklabel_format(useOffset=False, style="plain")
    fig.savefig(ruta, dpi=170, bbox_inches="tight")
    plt.close(fig)
