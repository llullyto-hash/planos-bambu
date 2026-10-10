"""Laminas para plotear: el dibujo se divide en hojas A1 a 1:500 con el membrete de PETRO.

Cada lamina lleva (en su espacio papel):
- la ventana del dibujo (a la escala elegida, girada si se orienta segun el dibujo),
- el membrete copiado de PETRO con los datos del proyecto y su numero (D-01, D-02...),
- la leyenda con solo las partidas que aparecen en esa lamina (con su achurado),
- un plano clave con todas las laminas y la actual resaltada,
- el cuadro de areas y perimetros de esa lamina con el total por partida,
- las llamadas de empalme "VER LAMINA D-03" en los bordes que siguen en otra lamina.

En el modelo se dibujan los limites de cada lamina (capa LIMITE DE LAMINA).
"""
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .estilo import ESTILO_CUADRO, ESTILO_TEXTO, cargar_plantilla

# Zonas del espacio papel (mm), tomadas de la lamina D-01 de PETRO (A1 horizontal)
VENTANA_MM = (3.9, 7.9, 503.5, 584.2)
PANEL_MM = (507.5, 51.0, 824.5, 583.0)
SEPARADOR_MM = (505.0, 7.9, 505.0, 584.2)
CAPA_LIMITE = "LIMITE DE LAMINA"
CAPA_VENTANA = "VENTANAS LAMINA"
CAPA_PANEL = "0MENBRETE"
CAPA_CUADRO = "CUADRO DE AREAS"
ALTO_CUADRO = 2.0
RENGLON_CUADRO = 4.0
CONFIG_USUARIO = Path.home() / ".planos_bambu" / "membrete.json"

MEMBRETE_PETRO = {
    "proyecto": ('"MEJORAMIENTO DEL SERVICIO DE MOVILIDAD URBANA EN CUADRANTE DEL JR. ANTONIO MAYA DE BRITO, '
                 'JR. REVOLUCION, JR. PERU Y JR. COMANDANTE BARRERA, URB. PETRO PERU DISTRITO DE CALLERIA DE LA '
                 'PROVINCIA DE CORONEL PORTILLO DEL DEPARTAMENTO DE UCAYALI"'),
    "cui": "2665624",
    "entidad": "MUNICIPALIDAD PROVINCIAL DE CORONEL PORTILLO",
    "urbanizacion": "PETRO PERU",
    "distrito": "CALLERÍA",
    "provincia": "CORONEL PORTILLO",
    "region": "UCAYALI",
    "zona": "18L",
    "proyeccion": "UTM",
    "datum": "WGS 84",
    "plano": "PLANO DE DEMOLICIONES",
    "fecha": "JUNIO 2025",
    "profesional": "",
    "logo": "",  # imagen (PNG/JPG) que reemplaza al escudo de PETRO; vacio = escudo de PETRO; "-" = sin escudo
}
APP_MEMBRETE = "WAMBRI_MEMBRETE"  # XDATA que marca los textos del membrete para poder actualizarlos despues
CAJA_ESCUDO = (510.5, 13.2, 534.7, 42.1)  # mm en la lamina, donde va el escudo de PETRO
CAMPOS_MEMBRETE = [  # (clave, titulo en la ventana)
    ("proyecto", "Proyecto"), ("cui", "CUI"), ("entidad", "Entidad"), ("urbanizacion", "Urbanización"),
    ("distrito", "Distrito"), ("provincia", "Provincia"), ("region", "Región"), ("zona", "Zona UTM"),
    ("proyeccion", "Proyección"), ("datum", "Datum"), ("plano", "Nombre del plano"), ("fecha", "Fecha"),
    ("profesional", "Profesional (firma)"),
]


def leer_membrete(ruta):
    """Datos del membrete guardados en un archivo .json (completa con PETRO lo que falte)."""
    datos = dict(MEMBRETE_PETRO)
    datos.update(json.loads(Path(ruta).read_text(encoding="utf-8")))
    return datos


def escribir_membrete(ruta, datos):
    Path(ruta).write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def cargar_membrete():
    datos = dict(MEMBRETE_PETRO)
    try:
        datos.update(json.loads(CONFIG_USUARIO.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return datos


def guardar_membrete(datos):
    try:
        CONFIG_USUARIO.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_USUARIO.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


@dataclass
class ConfLaminas:
    activar: bool = True
    escala: float = 500.0
    traslape: float = 5.0  # m que se repiten entre laminas vecinas
    orientacion: str = "norte"  # norte: norte arriba | auto: girada segun la direccion principal del dibujo
    prefijo: str = "D-"
    inicio: int = 1
    numerar_por_lamina: bool = True
    membrete: dict = field(default_factory=lambda: dict(MEMBRETE_PETRO))
    vista_pdf: bool = True
    cantidad: int = 0  # 0: segun la escala elegida | N: la escala se ajusta para que salgan N laminas o menos


@dataclass
class Lamina:
    nombre: str
    fila: int
    col: int
    angulo: float  # rad: direccion del eje x de la lamina en el modelo
    nucleo: Polygon  # parte propia de la lamina (sin traslape), en el modelo
    marco: Polygon  # lo que muestra la ventana, en el modelo
    centro: tuple  # centro de la ventana, en el modelo
    vecinos: dict = field(default_factory=dict)  # izquierda/derecha/arriba/abajo -> nombre
    areas: list = field(default_factory=list)
    lineas: list = field(default_factory=list)


def _rot(x, y, ang):
    c, s = math.cos(ang), math.sin(ang)
    return x * c - y * s, x * s + y * c


def tamano_ventana(escala):
    """(ancho, alto) en m de modelo que cubre la ventana de la lamina."""
    s = escala / 1000.0
    return (VENTANA_MM[2] - VENTANA_MM[0]) * s, (VENTANA_MM[3] - VENTANA_MM[1]) * s


def angulo_principal(geoms):
    """Direccion del lado largo del rectangulo minimo que encierra todo, en (-90, 90] grados."""
    u = unary_union([g.convex_hull for g in geoms]).convex_hull
    r = u.minimum_rotated_rectangle
    c = np.asarray(r.exterior.coords)
    if len(c) < 3:
        return 0.0
    e = c[1] - c[0] if np.hypot(*(c[1] - c[0])) >= np.hypot(*(c[2] - c[1])) else c[2] - c[1]
    ang = math.atan2(e[1], e[0])
    while ang > math.pi / 2:
        ang -= math.pi
    while ang <= -math.pi / 2:
        ang += math.pi
    return ang


def con_metrado(linea):
    """Lineas que llevan etiqueta y metrado (sardinel, corte lineal), no bordes de areas."""
    return bool(linea.conf.prefijo) and linea.conf.tipo == "linea" and not linea.borde and not linea.sin_pareja


def _punto(g):
    return g.representative_point() if g.geom_type.endswith("Polygon") else g.interpolate(0.5, normalized=True)


def _mejor_corrimiento(puntos, x0, y1, cw, ch, pasos=10):
    """Corrimiento de la cuadricula (en fracciones de lamina) con el que se usan menos laminas."""
    xs = np.array([p.x for p in puntos])
    ys = np.array([p.y for p in puntos])
    mejor = None
    for fx in range(pasos):
        for fy in range(pasos):
            i = np.floor((xs - (x0 - fx / pasos * cw)) / cw).astype(int)
            j = np.floor(((y1 + fy / pasos * ch) - ys) / ch).astype(int)
            n = len(set(zip(i.tolist(), j.tolist())))
            if mejor is None or n < mejor[0]:
                mejor = (n, fx / pasos, fy / pasos)
    return mejor


def dividir(met, conf, asignar=True, ajustar=None):
    """Laminas que cubren las areas y lineas con metrado. Asigna cada elemento a una sola lamina.
    Con conf.cantidad > 0 primero cambia conf.escala para que salgan esas laminas (o menos), y la
    cuadricula se corre para que el dibujo use la menor cantidad de laminas (ajustar)."""
    cantidad = int(getattr(conf, "cantidad", 0) or 0)
    if ajustar is None:
        ajustar = cantidad > 0
    if cantidad and asignar:
        conf.escala = escala_para(met, conf, cantidad)
    elementos = list(met.areas) + [l for l in met.lineas if con_metrado(l)]
    geoms = [e.poligono if hasattr(e, "poligono") else e.linea for e in elementos]
    if not geoms:
        return []
    ang = angulo_principal(geoms) if conf.orientacion == "auto" else 0.0
    vw, vh = tamano_ventana(conf.escala)
    t = min(conf.traslape, vw / 4, vh / 4)
    cw, ch = vw - 2 * t, vh - 2 * t
    # todo en coordenadas de la lamina (giradas -ang alrededor del origen)
    girar = lambda g: affinity.rotate(g, -ang, origin=(0, 0), use_radians=True)  # noqa: E731
    marco_g = [girar(g) for g in geoms]
    x0, y0, x1, y1 = unary_union([g.envelope for g in marco_g]).bounds
    # centrar la cuadricula sobre el dibujo (o correrla para usar menos laminas)
    nc = max(1, math.ceil((x1 - x0) / cw))
    nf = max(1, math.ceil((y1 - y0) / ch))
    gx0 = (x0 + x1) / 2 - nc * cw / 2
    gy1 = (y0 + y1) / 2 + nf * ch / 2
    if ajustar:
        pts = [_punto(g) for g in marco_g]
        centrada = len({(int((p.x - gx0) // cw), int((gy1 - p.y) // ch)) for p in pts})
        n, fx, fy = _mejor_corrimiento(pts, x0, y1, cw, ch)
        if n < centrada:
            gx0, gy1 = x0 - fx * cw, y1 + fy * ch
            nc = max(1, math.ceil((x1 - gx0) / cw))
            nf = max(1, math.ceil((gy1 - y0) / ch))
    celdas = {}
    for g, el in zip(marco_g, elementos):
        p = _punto(g)
        i = min(max(int((p.x - gx0) // cw), 0), nc - 1)
        j = min(max(int((gy1 - p.y) // ch), 0), nf - 1)
        celdas.setdefault((j, i), []).append(el)
    laminas = []
    orden = sorted(celdas)
    for k, (j, i) in enumerate(orden):
        nx0, ny1 = gx0 + i * cw, gy1 - j * ch
        nucleo_l = box(nx0, ny1 - ch, nx0 + cw, ny1)
        marco_l = box(nx0 - t, ny1 - ch - t, nx0 + cw + t, ny1 + t)
        cx, cy = _rot(nx0 + cw / 2, ny1 - ch / 2, ang)
        devolver = lambda g: affinity.rotate(g, ang, origin=(0, 0), use_radians=True)  # noqa: E731
        lam = Lamina(f"{conf.prefijo}{conf.inicio + k:02d}", j, i, ang, devolver(nucleo_l), devolver(marco_l), (cx, cy))
        for el in celdas[(j, i)]:
            if not asignar:
                continue
            el.lamina = lam.nombre
            (lam.areas if hasattr(el, "poligono") else lam.lineas).append(el)
        laminas.append(lam)
    por_celda = {(l.fila, l.col): l for l in laminas}
    for l in laminas:
        for nombre, (dj, di) in (("izquierda", (0, -1)), ("derecha", (0, 1)), ("arriba", (-1, 0)), ("abajo", (1, 0))):
            v = por_celda.get((l.fila + dj, l.col + di))
            if v is not None:
                l.vecinos[nombre] = v.nombre
    return laminas


ESCALAS_NORMALES = (200, 250, 300, 400, 500, 600, 750, 800, 1000, 1250, 1500, 2000, 2500, 3000, 4000, 5000,
                    7500, 10000)


def escala_para(met, conf, cantidad):
    """La escala normal mas grande (mas detalle) con la que el dibujo entra en `cantidad` laminas o menos."""
    from dataclasses import replace

    for esc in ESCALAS_NORMALES:
        prueba = replace(conf, escala=float(esc), cantidad=0)
        if len(dividir(met, prueba, asignar=False, ajustar=True)) <= cantidad:
            return float(esc)
    return float(ESCALAS_NORMALES[-1])


def clave_orden(laminas):
    """Orden de numeracion: por lamina y dentro de cada una de arriba-izquierda a abajo-derecha."""
    indice = {l.nombre: k for k, l in enumerate(laminas)}
    ang = laminas[0].angulo if laminas else 0.0

    def clave(geom, elemento):
        p = geom.centroid
        x, y = _rot(p.x, p.y, -ang)
        return (indice.get(getattr(elemento, "lamina", ""), 999), -round(y / 20), x)

    return clave


# ---------------------------------------------------------------- DXF de las laminas

def _texto_campos(m, nombre, escala):
    esc = f"1/{int(escala)}"
    ubic = ("\\pxsm1.5,qc;URBANIZACIÓN{\\fArial|b1|i0|c0|p34; }" + m.get("urbanizacion", "") +
            "{\\fArial|b1|i0|c0|p34;\\P\\psm1,ql;Distrito^I:} " + m.get("distrito", "") +
            "\\P{\\fArial|b1|i0|c0|p34;Provincia^I:} " + m.get("provincia", "") +
            "\\P{\\fArial|b1|i0|c0|p34;Región^I:} " + m.get("region", "") +
            "\\P{\\fArial|b1|i0|c0|p34;Zona^I^I:} " + m.get("zona", "") +
            "\\P{\\fArial|b1|i0|c0|p34;Proyección :} " + m.get("proyeccion", "") +
            " \\P{\\fArial|b1|i0|c0|p34;Datum^I:} " + m.get("datum", "") +
            "\\P{\\fArial|b1|i0|c0|p34;Escala^I:} INDICADA")
    proyecto = "\\pxqc;" + m.get("proyecto", "")
    if m.get("cui"):
        proyecto += " \\PCUI: " + m["cui"]
    return {
        "%%TITULO%%": ("{\\fBodoni|b0|i0|c0|p18;" + m.get("plano", "PLANO DE DEMOLICIONES") +
                       " \\P\\fDutch801 XBd BT|b0|i0|c0|p18;\\H0.85455x;ESC. " + esc + "}"),
        "%%PROYECTO%%": proyecto,
        "%%ENTIDAD%%": "{\\fArial|b1|i0|c0|p34;" + m.get("entidad", "") + "}",
        "%%UBICACION%%": ubic,
        "%%PLANO%%": "\\pxqc;" + m.get("plano", ""),
        "%%FECHA%%": "\\pxqc;" + m.get("fecha", ""),
        "%%LAMINA%%": "{\\fArial|b1|i0|c0|p34;" + nombre + "}",
    }


def _copiar_impresion(dst_layout, tpl_layout):
    for k in ("plot_configuration_file", "paper_size", "left_margin", "bottom_margin", "right_margin", "top_margin",
              "paper_width", "paper_height", "plot_origin_x_offset", "plot_origin_y_offset", "plot_window_x1",
              "plot_window_y1", "plot_window_x2", "plot_window_y2", "scale_numerator", "scale_denominator",
              "plot_layout_flags", "plot_paper_units", "plot_rotation", "plot_type", "current_style_sheet",
              "standard_scale_type", "scale_factor", "limmin", "limmax", "extmin", "extmax"):
        if tpl_layout.dxf_layout.dxf.hasattr(k):
            dst_layout.dxf_layout.dxf.set(k, tpl_layout.dxf_layout.dxf.get(k))


def _nuevo_layout(doc, nombre, tpl):
    from ezdxf.addons import Importer

    base, n = nombre, 2
    while nombre in doc.layouts:
        nombre = f"{base} ({n})"
        n += 1
    lay = doc.layouts.new(nombre)
    if tpl is not None and "LAMINA" in tpl.layouts:
        tl = tpl.layouts.get("LAMINA")
        _copiar_impresion(lay, tl)
        imp = Importer(tpl, doc)
        imp.import_entities(list(tl), lay)
        imp.finalize()
    return lay


def _marcar(doc, e, campo, nombre, escala):
    if APP_MEMBRETE not in doc.appids:
        doc.appids.new(APP_MEMBRETE)
    e.set_xdata(APP_MEMBRETE, [(1000, campo), (1000, nombre), (1040, float(escala))])


def _logo(lay, ruta):
    """Cambia el escudo de PETRO por la imagen elegida ("-" lo quita; vacio lo deja)."""
    if not ruta:
        return
    doc = lay.doc
    for e in list(lay.query("INSERT")):
        if e.dxf.name.upper().startswith("ESCUDO"):
            lay.delete_entity(e)
    for e in list(lay.query("IMAGE")):
        if e.has_xdata(APP_MEMBRETE):
            lay.delete_entity(e)
    if ruta == "-" or not Path(ruta).exists():
        return
    from PIL import Image

    with Image.open(ruta) as im:
        w, h = im.size
    x0, y0, x1, y1 = CAJA_ESCUDO
    f = min((x1 - x0) / w, (y1 - y0) / h)
    ancho, alto = w * f, h * f
    idef = doc.add_image_def(filename=str(Path(ruta).resolve()), size_in_pixel=(w, h))
    img = lay.add_image(idef, insert=((x0 + x1 - ancho) / 2, (y0 + y1 - alto) / 2), size_in_units=(ancho, alto),
                        dxfattribs={"layer": CAPA_PANEL})
    if APP_MEMBRETE not in doc.appids:
        doc.appids.new(APP_MEMBRETE)
    img.set_xdata(APP_MEMBRETE, [(1000, "logo")])


def _llenar_membrete(lay, conf, nombre):
    campos = _texto_campos(conf.membrete, nombre, conf.escala)
    for e in lay.query("MTEXT"):
        t = e.text.strip()
        if t in campos:
            e.text = campos[t]
            _marcar(lay.doc, e, t, nombre, conf.escala)
    prof = lay.add_mtext("\\pxqc;" + conf.membrete.get("profesional", ""),
                         dxfattribs={"layer": CAPA_PANEL, "char_height": 2.0, "insert": (749.7, 13.5),
                                     "attachment_point": 8, "width": 40})
    _marcar(lay.doc, prof, "%%PROFESIONAL%%", nombre, conf.escala)
    _logo(lay, conf.membrete.get("logo", ""))


def actualizar_membrete(ruta_dxf, datos, salida=None, avisar=print):
    """Cambia los datos del membrete de un DXF ya generado, sin volver a procesar.

    Solo toca los textos del membrete (marcados al crear las laminas) y el escudo. Guarda una copia
    (`<nombre>_membrete.dxf`) y devuelve (ruta, cantidad de laminas actualizadas)."""
    import ezdxf
    from ezdxf import recover

    try:
        doc = ezdxf.readfile(ruta_dxf)
    except Exception:  # noqa: BLE001 - archivos guardados por AutoCAD con errores menores
        doc = recover.readfile(ruta_dxf)[0]
    hechas = 0
    for lay in doc.layouts:
        if lay.name == "Model":
            continue
        tocada = False
        for e in lay.query("MTEXT"):
            if not e.has_xdata(APP_MEMBRETE):
                continue
            x = e.get_xdata(APP_MEMBRETE)
            campo, nombre, escala = x[0].value, x[1].value, x[2].value
            if campo == "%%PROFESIONAL%%":
                e.text = "\\pxqc;" + datos.get("profesional", "")
            else:
                nuevo = _texto_campos(datos, nombre, escala).get(campo)
                if nuevo is not None:
                    e.text = nuevo
            tocada = True
        if tocada:
            _logo(lay, datos.get("logo", ""))
            hechas += 1
    if salida is None:
        p = Path(ruta_dxf)
        salida = p.with_name(p.stem + "_membrete.dxf")
    doc.saveas(salida)
    avisar(f"Membrete actualizado en {hechas} laminas: {Path(salida).name}")
    return str(salida), hechas


def _texto(lay, txt, x, y, alto, capa, adj=1, rot=0.0, estilo=ESTILO_TEXTO):
    lay.add_mtext(txt, dxfattribs={"layer": capa, "char_height": alto, "insert": (x, y), "attachment_point": adj,
                                   "style": estilo, "rotation": rot})


def _rect(lay, x0, y0, x1, y1, capa):
    lay.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": capa})


def _leyenda(lay, partidas, x0, ytop, ancho, s):
    """Leyenda como la de PETRO: nombre a la izquierda y muestra del achurado a la derecha."""
    fila = 8.2
    _rect(lay, x0, ytop - 8.7, x0 + ancho, ytop, CAPA_PANEL)
    _texto(lay, "{\\fArial|b1|i0|c0|p34;LEYENDA}", x0 + ancho / 2, ytop - 4.35, 3.5, CAPA_PANEL, adj=5)
    y = ytop - 8.7
    corte = x0 + ancho * 0.56
    for p in partidas:
        _rect(lay, x0, y - fila, x0 + ancho, y, CAPA_PANEL)
        lay.add_line((corte, y - fila), (corte, y), dxfattribs={"layer": CAPA_PANEL})
        nombre = p["nombre"].upper()
        alto = min(2.5, (corte - x0 - 3) / max(len(nombre) * 0.62, 1))
        _texto(lay, nombre, x0 + (corte - x0) / 2, y - fila / 2, alto, CAPA_PANEL, adj=5,
               estilo="TEXAMBIENTES" if "TEXAMBIENTES" in lay.doc.styles else ESTILO_TEXTO)
        mx0, mx1, my0, my1 = corte + 5, x0 + ancho - 5, y - fila + 2, y - 2
        if p["tipo"] == "area":
            pts = [(mx0, my0), (mx1, my0), (mx1, my1), (mx0, my1)]
            lay.add_lwpolyline(pts, close=True, dxfattribs={"layer": p["capa"]})
            h = lay.add_hatch(dxfattribs={"layer": p["capa"]})
            if p["patron"].upper() == "SOLID":
                h.set_solid_fill(color=256)
            else:
                h.set_pattern_fill(p["patron"], scale=min(max(p["escala"] / s, 0.15), 2.0), color=256)
            h.paths.add_polyline_path(pts, is_closed=True)
        else:
            lay.add_line((mx0, (my0 + my1) / 2), (mx1, (my0 + my1) / 2), dxfattribs={"layer": p["capa"]})
        y -= fila
    return y


def _plano_clave(lay, laminas, actual, x0, y0, x1, y1):
    """Todas las laminas en miniatura, con la actual rellena."""
    _rect(lay, x0, y0, x1, y1, CAPA_PANEL)
    _texto(lay, "{\\fArial|b1|i0|c0|p34;PLANO CLAVE}", (x0 + x1) / 2, y1 - 3.5, 3.0, CAPA_PANEL, adj=5)
    ang = laminas[0].angulo
    rects = [affinity.rotate(l.nucleo, -ang, origin=(0, 0), use_radians=True) for l in laminas]
    bx0, by0, bx1, by1 = unary_union(rects).bounds
    zx0, zy0, zx1, zy1 = x0 + 4, y0 + 4, x1 - 4, y1 - 8
    f = min((zx1 - zx0) / max(bx1 - bx0, 1e-6), (zy1 - zy0) / max(by1 - by0, 1e-6))
    ox = zx0 + ((zx1 - zx0) - (bx1 - bx0) * f) / 2
    oy = zy0 + ((zy1 - zy0) - (by1 - by0) * f) / 2
    for l, r in zip(laminas, rects):
        c = [(ox + (x - bx0) * f, oy + (y - by0) * f) for x, y in list(r.exterior.coords)[:-1]]
        lay.add_lwpolyline(c, close=True, dxfattribs={"layer": CAPA_PANEL})
        if l.nombre == actual:
            h = lay.add_hatch(color=8, dxfattribs={"layer": CAPA_PANEL})
            h.set_solid_fill(color=8)
            h.paths.add_polyline_path(c, is_closed=True)
        cx = sum(p[0] for p in c) / 4
        cy = sum(p[1] for p in c) / 4
        alto = max(min(2.0, f * (by1 - by0) / max(len({x.fila for x in laminas}), 1) / 4), 1.0)
        _texto(lay, l.nombre, cx, cy, alto, CAPA_PANEL, adj=5)


def filas_cuadro(lam):
    """Filas del cuadro: (etiqueta, area, perimetro, largo) y totales por partida."""
    filas = []
    totales = {}
    for a in sorted(lam.areas, key=lambda a: a.etiqueta):
        largo = a.largo if getattr(a.conf, "etiqueta_largo", False) else None
        filas.append((a.etiqueta, a.area, a.poligono.exterior.length, largo))
        pref = a.etiqueta.split(" - ")[0]
        t = totales.setdefault(pref, [0.0, 0.0, 0.0, "m2"])
        t[0] += a.area
        t[1] += a.poligono.exterior.length
        t[2] += largo or 0.0
    for l in sorted(lam.lineas, key=lambda l: l.etiqueta):
        filas.append((l.etiqueta, None, None, l.linea.length))
        pref = l.etiqueta.split(" - ")[0]
        t = totales.setdefault(pref, [0.0, 0.0, 0.0, "m"])
        t[2] += l.linea.length
    return filas, totales


def _num(v):
    return "" if v is None else f"{v:,.2f}"


def _cuadro(lay, filas, totales, x0, ytop, x1, ybot, titulo):
    """Dibuja el cuadro en columnas; devuelve las filas que no cupieron."""
    cols = (("ETIQUETA", 26), ("ÁREA (m²)", 22), ("PERÍM. (m)", 22), ("LONG. (m)", 20))
    ancho_g = sum(w for _, w in cols)
    sep = 6.0
    ngrupos = max(1, int((x1 - x0 + sep) // (ancho_g + sep)))
    _texto(lay, "{\\fArial|b1|i0|c0|p34;" + titulo + "}", x0, ytop, 3.0, CAPA_CUADRO, adj=1)
    ytop -= 6.0
    por_grupo = max(1, int((ytop - ybot) // RENGLON_CUADRO) - 1)
    resto = list(filas)
    for g in range(ngrupos):
        if not resto:
            break
        gx = x0 + g * (ancho_g + sep)
        parte, resto = resto[:por_grupo], resto[por_grupo:]
        y = ytop
        x = gx
        for nombre, w in cols:
            _rect(lay, x, y - RENGLON_CUADRO, x + w, y, CAPA_CUADRO)
            _texto(lay, "{\\fArial|b1|i0|c0|p34;" + nombre + "}", x + w / 2, y - RENGLON_CUADRO / 2, ALTO_CUADRO * 0.9,
                   CAPA_CUADRO, adj=5, estilo=ESTILO_CUADRO)
            x += w
        y -= RENGLON_CUADRO
        for fila in parte:
            x = gx
            for (nombre, w), v in zip(cols, (fila[0], _num(fila[1]), _num(fila[2]), _num(fila[3]))):
                _rect(lay, x, y - RENGLON_CUADRO, x + w, y, CAPA_CUADRO)
                _texto(lay, v, x + w / 2, y - RENGLON_CUADRO / 2, ALTO_CUADRO, CAPA_CUADRO, adj=5, estilo=ESTILO_CUADRO)
                x += w
            y -= RENGLON_CUADRO
    return resto


def _filas_totales(totales):
    out = []
    for pref, (area, per, largo, und) in sorted(totales.items()):
        if und == "m2":
            out.append((f"TOTAL {pref}", area, per, largo or None))
        else:
            out.append((f"TOTAL {pref}", None, None, largo))
    return out


def _empalmes(lay, lam):
    x0, y0, x1, y1 = VENTANA_MM
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    for lado, nombre in lam.vecinos.items():
        txt = "{\\fArial|b1|i0|c0|p34;VER LÁMINA " + nombre + "}"
        if lado == "derecha":
            _texto(lay, txt, x1 - 3, cy, 3.0, CAPA_PANEL, adj=8, rot=90)
        elif lado == "izquierda":
            _texto(lay, txt, x0 + 3, cy, 3.0, CAPA_PANEL, adj=8, rot=270)
        elif lado == "arriba":
            _texto(lay, txt, cx, y1 - 3, 3.0, CAPA_PANEL, adj=8)
        else:
            _texto(lay, txt, cx, y0 + 52, 3.0, CAPA_PANEL, adj=2)


def partidas_de(lam, estilo):
    vistas, out = set(), []
    for a in lam.areas:
        c = a.conf
        if c.capa_area in vistas:
            continue
        vistas.add(c.capa_area)
        estilo.capa(c.capa_area, c.color_area or c.color)
        out.append({"nombre": c.capa_area or ((c.nombre or a.codigo) + " a demoler"), "tipo": "area", "capa": c.capa_area,
                    "patron": c.patron, "escala": c.escala_patron})
    for l in lam.lineas:
        if l.conf.capa in vistas:
            continue
        vistas.add(l.conf.capa)
        estilo.capa(l.conf.capa, l.conf.color, l.conf.tipo_linea)
        nombre = l.conf.nombre or l.codigo
        if l.codigo != "CL" and "DEMOLER" not in nombre.upper():
            nombre += " a demoler"
        out.append({"nombre": nombre, "tipo": "linea", "capa": l.conf.capa})
    return out


def dibujar_laminas(doc, laminas, conf, estilo):
    """Crea un layout por lamina (con su continuacion si el cuadro no cabe)."""
    if not laminas:
        return []
    tpl = cargar_plantilla()
    msp = doc.modelspace()
    s = conf.escala / 1000.0
    estilo.capa(CAPA_LIMITE, 8, "DASHED" if "DASHED" in doc.linetypes else "Continuous")
    capa_v = estilo.capa(CAPA_VENTANA, 7)
    capa_v.dxf.plot = 0
    estilo.capa(CAPA_CUADRO, 7)
    estilo.capa(CAPA_PANEL, 7)
    vw, vh = tamano_ventana(conf.escala)
    creados = []
    for lam in laminas:
        # limite y nombre de la lamina en el modelo
        msp.add_lwpolyline(list(lam.nucleo.exterior.coords)[:-1], close=True, dxfattribs={"layer": CAPA_LIMITE})
        esq = list(lam.nucleo.exterior.coords)[2]  # arriba-izquierda
        msp.add_mtext("{\\fArial|b1|i0|c0|p34;LÁMINA " + lam.nombre + "}",
                      dxfattribs={"layer": CAPA_LIMITE, "char_height": 3.0 * s, "insert": esq, "attachment_point": 1,
                                  "rotation": math.degrees(lam.angulo), "style": ESTILO_TEXTO})
        lay = _nuevo_layout(doc, lam.nombre, tpl)
        _llenar_membrete(lay, conf, lam.nombre)
        x0, y0, x1, y1 = VENTANA_MM
        cx_l, cy_l = _rot(lam.centro[0], lam.centro[1], -lam.angulo)  # centro en coordenadas de la vista
        vp = lay.add_viewport(center=((x0 + x1) / 2, (y0 + y1) / 2), size=(x1 - x0, y1 - y0),
                              view_center_point=(cx_l, cy_l), view_height=vh, dxfattribs={"layer": CAPA_VENTANA})
        vp.dxf.view_twist_angle = (-math.degrees(lam.angulo)) % 360
        lay.add_line(SEPARADOR_MM[:2], SEPARADOR_MM[2:], dxfattribs={"layer": CAPA_PANEL})
        _empalmes(lay, lam)
        px0, py0, px1, py1 = PANEL_MM
        ancho_ley = 101.0
        y_ley = _leyenda(lay, partidas_de(lam, estilo), px0, py1, ancho_ley, s)
        alto_clave = max(py1 - y_ley, 60.0)
        _plano_clave(lay, laminas, lam.nombre, px0 + ancho_ley + 4, py1 - alto_clave, px1, py1)
        filas, totales = filas_cuadro(lam)
        filas += [("", None, None, None)] + _filas_totales(totales)
        resto = _cuadro(lay, filas, totales, px0, min(y_ley, py1 - alto_clave) - 6, px1, py0,
                        f"CUADRO DE ÁREAS Y PERÍMETROS - LÁMINA {lam.nombre}")
        creados.append(lay.name)
        k = 2
        while resto:
            cont = _nuevo_layout(doc, f"{lam.nombre} CUADRO {k}", tpl)
            _llenar_membrete(cont, conf, f"{lam.nombre}-{k}")
            resto = _cuadro(cont, resto, totales, 10, 575, 820, 55,
                            f"CUADRO DE ÁREAS Y PERÍMETROS - LÁMINA {lam.nombre} (CONTINUACIÓN)")
            creados.append(cont.name)
            k += 1
    return creados


def vista_pdf(doc, nombres, ruta, capas=None, avisar=print):
    """PDF con una pagina por lamina (vista previa para revisar antes de plotear)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from matplotlib.backends.backend_pdf import PdfPages

    capas = {c.upper() for c in capas} if capas else None

    def filtro(e):
        if capas is None or not e.dxf.hasattr("layer"):
            return True
        if e.dxf.owner != doc.modelspace().block_record_handle:
            return True
        return e.dxf.layer.upper() in capas

    cfg = Configuration(background_policy=2) if hasattr(Configuration, "__dataclass_fields__") else Configuration()
    with PdfPages(ruta) as pdf:
        for nombre in nombres:
            lay = doc.layouts.get(nombre)
            fig = plt.figure(figsize=(33.1, 23.4))  # A1 en pulgadas
            ax = fig.add_axes([0, 0, 1, 1])
            ctx = RenderContext(doc)
            ctx.set_current_layout(lay)
            try:
                Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(lay, finalize=True, filter_func=filtro)
            except TypeError:
                Frontend(ctx, MatplotlibBackend(ax)).draw_layout(lay, finalize=True)
            ax.set_xlim(0, 830)
            ax.set_ylim(0, 590)
            pdf.savefig(fig, dpi=60)
            plt.close(fig)
            avisar(f"  vista previa: {nombre}")
