"""Crea ortofoto/plantilla_petro.dxf a partir del plano de demoliciones PETRO.

La plantilla es liviana (sin dibujo): estilos de texto, tipos de linea, las capas que tienen
contenido en PETRO (con color, tipo de linea, grosor y si se plotea), los bloques del membrete y
un espacio papel "LAMINA" con el marco y el membrete. Los textos que cambian en cada lamina
quedan marcados como %%CAMPO%% (ver ortofoto/laminas.py).

Uso (una sola vez, o cuando cambie el plano de referencia):
  python herramientas/crear_plantilla.py "1.2. PLANO DEMOLICIONES - PETRO.dxf"
"""
import sys
from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf import bbox, recover
from ezdxf.addons import Importer

DESTINO = Path(__file__).resolve().parent.parent / "ortofoto" / "plantilla_petro.dxf"
LAYOUT = "D-01"
# Capas que siempre van aunque esten vacias en PETRO (las usa el programa)
SIEMPRE = {"LETRERO", "TEXTO EN MARTILLO", "LINEA CORTE", "0MENBRETE", "Vereda a demoler", "Martillo a demoler",
           "Pav. Existente a Demoler", "Canaleta a demoler", "SARDINEL PP", "ACCESOS", "MARTILLO"}
# Textos del membrete que se reemplazan por campos (se busca el texto dentro del MTEXT)
CAMPOS = [
    ("MEJORAMIENTO DEL SERVICIO", "%%PROYECTO%%"),
    ("MUNICIPALIDAD PROVINCIAL", "%%ENTIDAD%%"),
    ("URBANIZACI", "%%UBICACION%%"),
    ("\\pxqc;PLANO DE DEMOLICIONES", "%%PLANO%%"),
    ("JUNIO 2025", "%%FECHA%%"),
    ("D-01}", "%%LAMINA%%"),
    ("ESC. 1/500", "%%TITULO%%"),
]
LAMINA_PAPEL = {  # zonas del espacio papel de PETRO (mm)
    "marco": (2.9, 6.9, 827.0, 585.2),
    "ventana": (3.9, 7.9, 565.3, 584.2),
    "membrete": (505.7, 9.8, 826.0, 48.4),
}


def contar_capas(doc):
    usos = Counter()
    for lay in doc.layouts:
        for e in lay:
            if e.dxf.hasattr("layer"):
                usos[e.dxf.layer] += 1
    for blk in doc.blocks:
        if blk.name.startswith("*"):
            continue
        for e in blk:
            if e.dxf.hasattr("layer"):
                usos[e.dxf.layer] += 1
    return usos


def es_membrete(e):
    """Lo que se copia del espacio papel: marco, membrete y titulo (no carteles, ventanas ni leyenda)."""
    t = e.dxftype()
    if t in ("VIEWPORT", "LEADER", "OLE2FRAME") or e.dxf.layer in ("LETRERO", "TEXTO EN MARTILLO", "JUNTA T1"):
        return False
    b = bbox.extents([e])
    if not b.has_data:
        return False
    x0, y0, x1, y1 = b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y
    if y1 < 0:
        return False
    if 455 < x0 and x1 < 570 and 70 < y0 and y1 < 135:  # leyenda (se arma sola en cada lamina)
        return False
    if e.dxf.layer == "0MENBRETE" or e.dxf.layer == "CODO VERT 11.25":
        return True
    if t == "MTEXT" and "ESC." in e.text:  # titulo PLANO DE DEMOLICIONES / ESC.
        return True
    return t == "LWPOLYLINE" and e.dxf.layer == "0" and y1 < 9  # linea inferior del marco


def main(ruta):
    src, _ = recover.readfile(ruta)
    usos = contar_capas(src)
    dst = ezdxf.new("R2018")
    dst.header["$INSUNITS"] = 6
    imp = Importer(src, dst)
    imp.import_tables(("linetypes", "styles"))
    capas = [c.dxf.name for c in src.layers if usos[c.dxf.name] > 0 or c.dxf.name in SIEMPRE]
    imp.import_table("layers", capas)
    lay_src = src.layouts.get(LAYOUT)
    lay_dst = dst.layouts.new("LAMINA")
    imp.import_entities([e for e in lay_src if es_membrete(e)], lay_dst)
    imp.finalize()
    # Configuracion de impresion de la lamina (plotter, papel, estilo de ploteo)
    for k in ("plot_configuration_file", "paper_size", "left_margin", "bottom_margin", "right_margin", "top_margin",
              "paper_width", "paper_height", "plot_origin_x_offset", "plot_origin_y_offset", "plot_window_x1",
              "plot_window_y1", "plot_window_x2", "plot_window_y2", "scale_numerator", "scale_denominator",
              "plot_layout_flags", "plot_paper_units", "plot_rotation", "plot_type", "current_style_sheet",
              "standard_scale_type", "shade_plot_mode", "shade_plot_resolution_level", "shade_plot_custom_dpi",
              "scale_factor", "paper_image_origin_x", "paper_image_origin_y", "limmin", "limmax", "extmin", "extmax"):
        if lay_src.dxf_layout.dxf.hasattr(k):
            lay_dst.dxf_layout.dxf.set(k, lay_src.dxf_layout.dxf.get(k))
    # Marca los textos variables
    puestos = set()
    for e in lay_dst.query("MTEXT"):
        for clave, campo in CAMPOS:
            if clave in e.text and campo not in puestos:
                e.text = campo
                puestos.add(campo)
                break
    falta = {c for _, c in CAMPOS} - puestos
    if falta:
        print("AVISO: no se encontraron los campos", falta)
    # Borra el layout de ejemplo que trae ezdxf.new
    for nombre in list(dst.layouts.names()):
        if nombre not in ("Model", "LAMINA"):
            dst.layouts.delete(nombre)
    dst.saveas(DESTINO)
    print(f"Plantilla: {DESTINO} ({DESTINO.stat().st_size / 1e3:.0f} kB), {len(capas)} capas, "
          f"{len(dst.styles)} estilos, {len(lay_dst)} entidades de membrete")


if __name__ == "__main__":
    main(sys.argv[1])
