"""Ortofoto georreferenciada: lectura, transformacion pixel <-> terreno y bordes."""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

EXT_MUNDO = {".tif": ".tfw", ".tiff": ".tfw", ".jpg": ".jgw", ".jpeg": ".jgw", ".png": ".pgw"}


class Ortofoto:
    """Imagen RGB + transformacion afin pixel (col, fila) -> (este, norte).

    E = a*col + b*fila + c
    N = d*col + e*fila + f
    (mismo orden que un world file: a, d, b, e, c, f)
    """

    def __init__(self, rgb, afin):
        self.rgb = rgb
        self.afin = np.asarray(afin, dtype=float)  # [a, b, c, d, e, f]
        self._bordes = None

    # ---------- lectura / escritura ----------
    @classmethod
    def abrir(cls, ruta):
        ruta = Path(ruta)
        try:
            import rasterio  # opcional, maneja GeoTIFF grandes y comprimidos

            with rasterio.open(ruta) as src:
                if src.transform.is_identity:
                    raise ValueError("sin georreferencia")
                rgb = np.moveaxis(src.read([1, 2, 3]), 0, -1)
                t = src.transform
                return cls(rgb, [t.a, t.b, t.c, t.d, t.e, t.f])
        except ImportError:
            pass
        img = Image.open(ruta)
        afin = _afin_de_world_file(ruta) or _afin_de_geotiff(img)
        if afin is None:
            raise ValueError(
                f"{ruta.name} no esta georreferenciada: agregue su world file "
                f"({EXT_MUNDO.get(ruta.suffix.lower(), '.wld')}) o use puntos de control (--control)."
            )
        return cls(np.asarray(img.convert("RGB")), afin)

    @classmethod
    def sin_georreferencia(cls, ruta):
        return cls(np.asarray(Image.open(ruta).convert("RGB")), [1, 0, 0, 0, -1, 0])

    def guardar(self, ruta):
        ruta = Path(ruta)
        Image.fromarray(self.rgb).save(ruta)
        a, b, c, d, e, f = self.afin
        # El world file referencia el centro del pixel superior izquierdo.
        c0, f0 = self.a_terreno(0.5, 0.5)
        mundo = ruta.with_suffix(EXT_MUNDO.get(ruta.suffix.lower(), ".wld"))
        mundo.write_text("\n".join(f"{v:.10f}" for v in (a, d, b, e, c0, f0)) + "\n")

    # ---------- geometria ----------
    @property
    def tam_pixel(self):
        a, b, _, d, e, _ = self.afin
        return float(np.sqrt(abs(a * e - b * d)))

    def a_terreno(self, col, fila):
        a, b, c, d, e, f = self.afin
        return a * col + b * fila + c, d * col + e * fila + f

    def a_pixel(self, este, norte):
        a, b, c, d, e, f = self.afin
        det = a * e - b * d
        x, y = np.asarray(este) - c, np.asarray(norte) - f
        return (e * x - b * y) / det, (-d * x + a * y) / det

    def desplazar(self, de, dn):
        """Corrige la georreferencia moviendo la foto (de, dn) metros."""
        self.afin[2] += de
        self.afin[5] += dn

    def recortar(self, xmin, ymin, xmax, ymax):
        """Nueva Ortofoto solo con la zona indicada (ahorra memoria)."""
        cs, fs = self.a_pixel(np.array([xmin, xmax, xmin, xmax]), np.array([ymin, ymin, ymax, ymax]))
        h, w = self.rgb.shape[:2]
        c0, c1 = int(max(0, np.floor(cs.min()))), int(min(w, np.ceil(cs.max())))
        f0, f1 = int(max(0, np.floor(fs.min()))), int(min(h, np.ceil(fs.max())))
        if c1 <= c0 or f1 <= f0:
            raise ValueError("La zona de los puntos no cae dentro de la ortofoto: revise el calce")
        a, b, c, d, e, f = self.afin
        e0, n0 = self.a_terreno(c0, f0)
        return Ortofoto(np.ascontiguousarray(self.rgb[f0:f1, c0:c1]), [a, b, e0, d, e, n0])

    def extension(self):
        h, w = self.rgb.shape[:2]
        es, ns = zip(*(self.a_terreno(c, f) for c, f in [(0, 0), (w, 0), (0, h), (w, h)]))
        return min(es), min(ns), max(es), max(ns)

    # ---------- bordes ----------
    @property
    def bordes(self):
        """Gradiente (gx, gy) en pixeles, suavizado, normalizado a ~[0, 1]."""
        if self._bordes is None:
            img = self.rgb.astype(np.float32) / 255.0
            sigma = max(1.0, 0.08 / self.tam_pixel)  # ~8 cm de suavizado
            gx = np.zeros(img.shape[:2], np.float32)
            gy = np.zeros(img.shape[:2], np.float32)
            for k in range(3):
                canal = ndimage.gaussian_filter(img[..., k], sigma)
                cx, cy = ndimage.sobel(canal, axis=1), ndimage.sobel(canal, axis=0)
                # Suma por canal con el signo del canal dominante (color, no solo brillo)
                mayor = np.hypot(cx, cy) > np.hypot(gx, gy)
                gx = np.where(mayor, cx, gx)
                gy = np.where(mayor, cy, gy)
            escala = np.percentile(np.hypot(gx, gy), 98) or 1.0
            self._bordes = (gx / escala, gy / escala)
        return self._bordes

    def muestrear_bordes(self, este, norte):
        """Magnitud del gradiente y su direccion (en terreno) en coordenadas dadas."""
        col, fila = self.a_pixel(este, norte)
        gx, gy = self.bordes
        coords = np.vstack([np.atleast_1d(fila), np.atleast_1d(col)])
        vx = ndimage.map_coordinates(gx, coords, order=1, mode="constant")
        vy = ndimage.map_coordinates(gy, coords, order=1, mode="constant")
        # Gradiente en pixeles -> direccion en terreno (la fila crece hacia el sur)
        a, b, _, d, e, _ = self.afin
        ge = a * vx + b * vy
        gn = d * vx + e * vy
        norma = np.hypot(ge, gn) + 1e-9
        mag = np.hypot(vx, vy)
        return mag, ge / norma * mag, gn / norma * mag

    def color(self, este, norte):
        col, fila = self.a_pixel(este, norte)
        coords = np.vstack([np.atleast_1d(fila), np.atleast_1d(col)])
        return np.stack(
            [ndimage.map_coordinates(self.rgb[..., k].astype(np.float32), coords, order=1, mode="nearest")
             for k in range(3)], axis=-1)


def afin_desde_dxf(ruta_dxf, nombre_imagen=None):
    """Georreferencia de una imagen insertada en un DXF (entidad IMAGE).

    Es el calce que ya hizo el dibujante en AutoCAD/Civil 3D: con esto la
    ortofoto queda en las mismas coordenadas del plano sin world file.
    Devuelve (afin, nombre_archivo, (ancho_px, alto_px)).
    """
    from ezdxf import recover

    doc, _ = recover.readfile(ruta_dxf)
    for im in doc.modelspace().query("IMAGE"):
        idef = doc.entitydb.get(im.dxf.image_def_handle)
        archivo = idef.dxf.filename.replace("\\", "/").split("/")[-1] if idef else ""
        if nombre_imagen and archivo.lower() != Path(nombre_imagen).name.lower():
            continue
        w, h = im.dxf.image_size.x, im.dxf.image_size.y
        ins, u, v = im.dxf.insert, im.dxf.u_pixel, im.dxf.v_pixel
        # Insercion = esquina inferior izquierda; v apunta hacia arriba (fila hacia abajo)
        afin = [u.x, -v.x, ins.x + h * v.x, u.y, -v.y, ins.y + h * v.y]
        return afin, archivo, (int(w), int(h))
    raise ValueError(f"No hay una IMAGE {nombre_imagen or ''} en {ruta_dxf}")


def _afin_de_world_file(ruta):
    for ext in {EXT_MUNDO.get(ruta.suffix.lower(), ".wld"), ".wld"}:
        mundo = ruta.with_suffix(ext)
        if mundo.exists():
            a, d, b, e, c0, f0 = [float(v) for v in mundo.read_text().split()[:6]]
            # c0, f0 son el centro del pixel (0,0): pasar a la esquina
            return [a, b, c0 - 0.5 * a - 0.5 * b, d, e, f0 - 0.5 * d - 0.5 * e]
    return None


def _afin_de_geotiff(img):
    tags = getattr(img, "tag_v2", None)
    if not tags or 33550 not in tags or 33922 not in tags:
        return None
    sx, sy = tags[33550][:2]
    i, j, _, x, y, _ = tags[33922][:6]
    return [sx, 0.0, x - i * sx, 0.0, -sy, y + j * sy]
