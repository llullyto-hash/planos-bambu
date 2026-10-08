"""Genera una ortofoto SINTETICA a partir de un plano dibujado, para probar.

No reemplaza a una foto real: pinta los achurados y bordes existentes del
plano con colores de concreto/asfalto/tierra, agrega ruido, iluminacion
irregular, arboles que tapan bordes y sombras, y guarda la foto con un error
de georreferencia conocido para comprobar el calce automatico.

python -m ortofoto.prueba.sintetica PLANO.dxf --ventana X0 Y0 X1 Y1 -o prueba/ --error 1.35 -0.85
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from ..imagen import Ortofoto

MATERIALES = {
    "VEREDA EXIS.": (202, 199, 190), "Vereda a demoler": (202, 199, 190), "BLOQUE VEREDA": (202, 199, 190),
    "MARTILLO": (184, 179, 170), "Martillo a demoler": (184, 179, 170),
    "ACCESOS": (176, 166, 152),
    "PAVIMENTO TAHIZ": (78, 78, 82), "Pav. Existente a Demoler": (78, 78, 82), "PAV. EXIS.": (78, 78, 82),
    "CANALETA EXISTENTE": (118, 116, 108), "Canaleta a demoler": (118, 116, 108),
    "ALCANTARILLA TUBULAR DE CONCRETO": (125, 122, 115), "Alc a demoler": (125, 122, 115),
    "AREA VERDE": (82, 122, 62), "BERMA EXIST.": (92, 128, 70),
    "COLUMNAS DE CONCRETO": (215, 214, 208), "SARDINEL P": (190, 188, 182),
}
BORDES = {  # capa: (color, ancho en m)
    "LINEA DE LOTE": ((96, 84, 74), 0.25), "SARDINEL PP": ((205, 203, 196), 0.15), "0": ((120, 112, 100), 0.10),
}
SUELO = np.array([148, 122, 92], float)


def _rasterizar(doc, ventana, gsd):
    from ezdxf import bbox
    from ezdxf import path as dxfpath

    x0, y0, x1, y1 = ventana
    w, h = int((x1 - x0) / gsd), int((y1 - y0) / gsd)
    img = Image.new("RGB", (w, h), tuple(int(v) for v in SUELO))
    dib = ImageDraw.Draw(img)
    px = lambda pts: [((x - x0) / gsd, (y1 - y) / gsd) for x, y in pts]
    rellenos, lineas = [], []
    for e in doc.modelspace().query("HATCH LWPOLYLINE LINE"):
        capa = e.dxf.layer
        if capa not in MATERIALES and capa not in BORDES:
            continue
        try:
            b = bbox.extents([e], fast=True)
        except Exception:
            continue
        if not b.has_data or b.extmax.x < x0 or b.extmin.x > x1 or b.extmax.y < y0 or b.extmin.y > y1:
            continue
        if e.dxftype() == "HATCH" and capa in MATERIALES:
            for bp in e.paths:
                try:
                    v = [(p.x, p.y) for p in dxfpath.from_hatch_boundary_path(bp).flattening(0.02)]
                except Exception:
                    continue
                if len(v) > 2:
                    rellenos.append((abs(b.size.x * b.size.y), capa, v))
        else:
            v = [(p.x, p.y) for p in dxfpath.make_path(e).flattening(0.02)]
            if e.dxftype() == "LWPOLYLINE" and e.closed and capa in MATERIALES:
                rellenos.append((abs(b.size.x * b.size.y), capa, v))
            lineas.append((capa, v))
    for _, capa, v in sorted(rellenos, key=lambda r: -r[0]):  # grandes primero
        dib.polygon(px(v), fill=MATERIALES[capa])
    for capa, v in lineas:
        color, ancho = BORDES.get(capa, ((105, 100, 92), 0.08))
        dib.line(px(v), fill=color, width=max(1, int(ancho / gsd)))
    return np.asarray(img).astype(np.float32)


def _ruido(forma, sigma, rng):
    return ndimage.gaussian_filter(rng.standard_normal(forma).astype(np.float32), sigma)


def generar(doc, ventana, gsd, arboles, rng):
    img = _rasterizar(doc, ventana, gsd)
    h, w = img.shape[:2]
    x0, y0, x1, y1 = ventana
    # Variacion del suelo y de iluminacion (manchas grandes)
    luz = _ruido((h, w), 15 / gsd, rng)
    luz = 1 + 0.08 * luz / (luz.std() + 1e-9)
    manchas = _ruido((h, w), 0.6 / gsd, rng)
    img += (manchas / (manchas.std() + 1e-6) * 9)[..., None]
    img *= np.clip(luz, 0.8, 1.2)[..., None]
    # Arboles con sombra: tapan bordes como en una foto real
    for e, n in arboles:
        c, f = (e - x0) / gsd, (y1 - n) / gsd
        r = rng.uniform(1.5, 3.2) / gsd
        sl = (slice(max(0, int(f - 2 * r)), min(h, int(f + 2 * r))), slice(max(0, int(c - 2 * r)), min(w, int(c + 2 * r))))
        dy, dx = np.ogrid[sl[0], sl[1]]
        dy, dx = np.broadcast_arrays(dy - f, dx - c)
        sombra = ((dx - 0.6 * r) ** 2 + (dy - 0.4 * r) ** 2) < r ** 2
        img[sl][sombra] *= 0.55
        copa = dx ** 2 + dy ** 2 < (r * (1 + 0.15 * np.sin(np.arctan2(dy, dx) * 7))) ** 2
        verde = np.array([52, 88, 40], np.float32) * (0.75 + 0.5 * rng.random(copa.sum()))[:, None]
        img[sl][copa] = verde
    img += rng.normal(0, 6, img.shape).astype(np.float32)
    img = ndimage.gaussian_filter(img, (0.8, 0.8, 0))
    return np.clip(img, 0, 255).astype(np.uint8)


def main(argv=None):
    import ezdxf  # noqa: F401
    from ezdxf import recover

    from .. import topografia

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dxf")
    ap.add_argument("--ventana", type=float, nargs=4, required=True)
    ap.add_argument("--gsd", type=float, default=0.05, help="Tamano de pixel (m)")
    ap.add_argument("--error", type=float, nargs=2, default=(1.35, -0.85), help="Error de georreferencia (m)")
    ap.add_argument("-o", "--salida", default="prueba_sintetica")
    ap.add_argument("--semilla", type=int, default=7)
    args = ap.parse_args(argv)

    out = Path(args.salida)
    out.mkdir(parents=True, exist_ok=True)
    doc, _ = recover.readfile(args.dxf)
    puntos = topografia.leer_dxf(args.dxf, ventana=args.ventana)
    arboles = [(p.e, p.n) for p in puntos if p.codigo == "ARB"]
    rgb = generar(doc, args.ventana, args.gsd, arboles, np.random.default_rng(args.semilla))
    x0, y0, x1, y1 = args.ventana
    orto = Ortofoto(rgb, [args.gsd, 0, x0, 0, -args.gsd, y1])
    orto.desplazar(*args.error)  # georreferencia "mal" a proposito
    orto.guardar(out / "orto_sintetica.png")
    with open(out / "puntos.csv", "w", encoding="utf-8") as fh:
        for p in puntos:
            fh.write(f"{p.num},{p.n:.4f},{p.e:.4f},{p.z:.3f},{p.desc}\n")
    print(f"Ortofoto sintetica {rgb.shape[1]}x{rgb.shape[0]} px, {len(puntos)} puntos, error introducido {args.error}")


if __name__ == "__main__":
    main()
