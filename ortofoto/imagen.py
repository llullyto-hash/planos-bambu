"""Ortofoto georreferenciada: lectura, transformacion pixel <-> terreno y bordes.

Pensado para ortofotos grandes (GB): solo se lee la zona de trabajo, se puede
bajar la resolucion al leer, y los bordes se calculan por bloques a medida que
se necesitan, asi la memoria no depende del tamano del archivo.
"""
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

EXT_MUNDO = {".tif": ".tfw", ".tiff": ".tfw", ".jpg": ".jgw", ".jpeg": ".jgw", ".png": ".pgw"}
BLOQUE = 1024  # pixeles por lado de cada bloque de bordes
MARGEN = 16  # pixeles extra alrededor del bloque para que el filtro no corte
BLOQUES_EN_MEMORIA = 48


class Ortofoto:
    """Imagen RGB + transformacion afin pixel (col, fila) -> (este, norte).

    E = a*col + b*fila + c
    N = d*col + e*fila + f
    `origen` guarda el archivo original (ruta, afin, tamano) para insertarlo
    tal cual en el DXF de salida, sin copiar la foto.
    """

    def __init__(self, rgb, afin, origen=None):
        self.rgb = rgb
        self.afin = np.asarray(afin, dtype=float)  # [a, b, c, d, e, f]
        self.origen = origen
        self._bloques = OrderedDict()
        self._escala = None

    # ---------- lectura / escritura ----------
    @classmethod
    def cargar(cls, ruta, afin=None, tam_ref=None, ventana=None, resolucion=None):
        """Lee la foto (o solo `ventana` = (xmin, ymin, xmax, ymax) en metros).

        afin: georreferencia del archivo completo si viene de fuera (DXF o
              puntos de control); si no, se toma del GeoTIFF o world file.
        tam_ref: (ancho, alto) de la imagen a la que se refiere `afin`; si el
              archivo se exporto a otro tamano, se ajusta la escala.
        resolucion: tamano de pixel de trabajo en metros (None = original).
        """
        ruta = Path(ruta)
        lector = _LectorRasterio(ruta) if _hay_rasterio() else _LectorPIL(ruta)
        w, h = lector.tam
        if afin is None:
            afin = lector.afin
            if afin is None:
                raise ValueError(
                    f"{ruta.name} no esta georreferenciada: agregue su world file "
                    f"({EXT_MUNDO.get(ruta.suffix.lower(), '.wld')}), use el DXF donde esta insertada "
                    "o puntos de control."
                )
        afin = np.asarray(afin, float)
        if tam_ref and tuple(tam_ref) != (w, h):
            fx, fy = tam_ref[0] / w, tam_ref[1] / h
            afin = np.array([afin[0] * fx, afin[1] * fy, afin[2], afin[3] * fx, afin[4] * fy, afin[5]])
        completa = cls(None, afin)

        c0, f0, c1, f1 = 0, 0, w, h
        if ventana is not None:
            x0, y0, x1, y1 = ventana
            cs, fs = completa.a_pixel(np.array([x0, x1, x0, x1]), np.array([y0, y0, y1, y1]))
            c0, c1 = int(max(0, np.floor(cs.min()))), int(min(w, np.ceil(cs.max())))
            f0, f1 = int(max(0, np.floor(fs.min()))), int(min(h, np.ceil(fs.max())))
            if c1 <= c0 or f1 <= f0:
                raise ValueError("Los puntos no caen dentro de la ortofoto: revise el calce o el archivo")
        factor = max(1.0, (resolucion or 0) / completa.tam_pixel)
        ow, oh = max(1, int(round((c1 - c0) / factor))), max(1, int(round((f1 - f0) / factor)))
        rgb = lector.leer(c0, f0, c1, f1, ow, oh)
        sx, sy = (c1 - c0) / ow, (f1 - f0) / oh
        a, b, _, d, e, _ = afin
        e0, n0 = completa.a_terreno(c0, f0)
        origen = {"ruta": str(ruta.resolve()), "afin": afin.copy(), "tam": (w, h)}
        return cls(rgb, [a * sx, b * sy, e0, d * sx, e * sy, n0], origen)

    @classmethod
    def abrir(cls, ruta):
        return cls.cargar(ruta)

    @staticmethod
    def tamano(ruta):
        ruta = Path(ruta)
        return (_LectorRasterio(ruta) if _hay_rasterio() else _LectorPIL(ruta)).tam

    def guardar(self, ruta):
        ruta = Path(ruta)
        Image.fromarray(self.rgb).save(ruta, quality=90) if ruta.suffix.lower() in (".jpg", ".jpeg") \
            else Image.fromarray(self.rgb).save(ruta)
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
        if self.origen is not None:
            self.origen["afin"][2] += de
            self.origen["afin"][5] += dn

    def recortar(self, xmin, ymin, xmax, ymax):
        """Nueva Ortofoto solo con la zona indicada."""
        cs, fs = self.a_pixel(np.array([xmin, xmax, xmin, xmax]), np.array([ymin, ymin, ymax, ymax]))
        h, w = self.rgb.shape[:2]
        c0, c1 = int(max(0, np.floor(cs.min()))), int(min(w, np.ceil(cs.max())))
        f0, f1 = int(max(0, np.floor(fs.min()))), int(min(h, np.ceil(fs.max())))
        if c1 <= c0 or f1 <= f0:
            raise ValueError("La zona de los puntos no cae dentro de la ortofoto: revise el calce")
        a, b, c, d, e, f = self.afin
        e0, n0 = self.a_terreno(c0, f0)
        return Ortofoto(np.ascontiguousarray(self.rgb[f0:f1, c0:c1]), [a, b, e0, d, e, n0], self.origen)

    def extension(self):
        h, w = self.rgb.shape[:2]
        es, ns = zip(*(self.a_terreno(c, f) for c, f in [(0, 0), (w, 0), (0, h), (w, h)]))
        return min(es), min(ns), max(es), max(ns)

    # ---------- bordes por bloques ----------
    def _bloque(self, bi, bj):
        clave = (bi, bj)
        if clave in self._bloques:
            self._bloques.move_to_end(clave)
            return self._bloques[clave]
        h, w = self.rgb.shape[:2]
        f0, c0 = bi * BLOQUE - MARGEN, bj * BLOQUE - MARGEN
        f1, c1 = (bi + 1) * BLOQUE + MARGEN, (bj + 1) * BLOQUE + MARGEN
        sub = self.rgb[max(0, f0):min(h, f1), max(0, c0):min(w, c1)].astype(np.float32) / 255.0
        # Rellenar si el bloque toca el borde de la imagen, para indexar siempre igual
        sub = np.pad(sub, ((max(0, -f0), max(0, f1 - h)), (max(0, -c0), max(0, c1 - w)), (0, 0)), mode="edge")
        sigma = max(1.0, 0.08 / self.tam_pixel)  # ~8 cm de suavizado
        gx = np.zeros(sub.shape[:2], np.float32)
        gy = np.zeros(sub.shape[:2], np.float32)
        for k in range(3):
            canal = ndimage.gaussian_filter(sub[..., k], sigma)
            cx, cy = ndimage.sobel(canal, axis=1), ndimage.sobel(canal, axis=0)
            # Por pixel, el canal con mas contraste: detecta bordes de color, no solo de brillo
            mayor = cx * cx + cy * cy > gx * gx + gy * gy
            gx = np.where(mayor, cx, gx)
            gy = np.where(mayor, cy, gy)
        self._bloques[clave] = (gx, gy)
        if len(self._bloques) > BLOQUES_EN_MEMORIA:
            self._bloques.popitem(last=False)
        return gx, gy

    def _escala_bordes(self):
        """Percentil 98 del gradiente en una muestra de bloques (para normalizar)."""
        if self._escala is None:
            h, w = self.rgb.shape[:2]
            nb_f, nb_c = -(-h // BLOQUE), -(-w // BLOQUE)
            filas = np.unique(np.linspace(0, nb_f - 1, min(nb_f, 3)).astype(int))
            cols = np.unique(np.linspace(0, nb_c - 1, min(nb_c, 3)).astype(int))
            mags = []
            for bi in filas:
                for bj in cols:
                    gx, gy = self._bloque(bi, bj)
                    mags.append(np.hypot(gx, gy)[MARGEN:-MARGEN:2, MARGEN:-MARGEN:2].ravel())
            self._escala = float(np.percentile(np.concatenate(mags), 98)) or 1.0
        return self._escala

    def muestrear_bordes(self, este, norte):
        """Magnitud del gradiente (~0..1) y sus componentes en terreno (este, norte)."""
        col, fila = self.a_pixel(np.atleast_1d(este), np.atleast_1d(norte))
        col, fila = np.asarray(col, float).ravel(), np.asarray(fila, float).ravel()
        h, w = self.rgb.shape[:2]
        vx = np.zeros(col.size, np.float32)
        vy = np.zeros(col.size, np.float32)
        dentro = (col >= 0) & (col < w - 1) & (fila >= 0) & (fila < h - 1)
        if dentro.any():
            bi = (fila // BLOQUE).astype(int)
            bj = (col // BLOQUE).astype(int)
            clave = np.where(dentro, bi * 100000 + bj, -1)
            for k in np.unique(clave[dentro]):
                m = clave == k
                gx, gy = self._bloque(k // 100000, k % 100000)
                coords = np.vstack([fila[m] - (k // 100000) * BLOQUE + MARGEN,
                                    col[m] - (k % 100000) * BLOQUE + MARGEN])
                vx[m] = ndimage.map_coordinates(gx, coords, order=1, mode="nearest")
                vy[m] = ndimage.map_coordinates(gy, coords, order=1, mode="nearest")
        esc = self._escala_bordes()
        vx /= esc
        vy /= esc
        # Gradiente en pixeles -> direccion en terreno (la fila crece hacia el sur)
        a, b, _, d, e, _ = self.afin
        ge = a * vx + b * vy
        gn = d * vx + e * vy
        norma = np.hypot(ge, gn) + 1e-9
        mag = np.hypot(vx, vy)
        return mag, ge / norma * mag, gn / norma * mag

    def bloque_de(self, este, norte):
        """Clave del bloque de bordes donde cae una coordenada (para ordenar trabajo)."""
        col, fila = self.a_pixel(este, norte)
        return int(fila // BLOQUE), int(col // BLOQUE)


# ---------- lectores ----------
def _hay_rasterio():
    try:
        import rasterio  # noqa: F401

        return True
    except ImportError:
        return False


class _LectorRasterio:
    """Lee solo la ventana pedida y remuestrea al leer (GeoTIFF grandes, JPG, etc.)."""

    def __init__(self, ruta):
        import rasterio

        self.ruta = ruta
        with rasterio.open(ruta) as src:
            self.tam = (src.width, src.height)
            t = src.transform
            self.afin = None if t.is_identity else [t.a, t.b, t.c, t.d, t.e, t.f]
        if self.afin is None:
            self.afin = _afin_de_world_file(ruta)

    def leer(self, c0, f0, c1, f1, ow, oh):
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.windows import Window

        rgb = np.empty((oh, ow, 3), np.uint8)
        with rasterio.open(self.ruta) as src:
            bandas = [1, 2, 3] if src.count >= 3 else [1, 1, 1]
            for k, banda in enumerate(bandas):  # banda por banda: menos memoria
                datos = src.read(banda, window=Window(c0, f0, c1 - c0, f1 - f0), out_shape=(oh, ow),
                                 resampling=Resampling.average)
                if datos.dtype != np.uint8:  # fotos de 16 bits
                    datos = (datos / max(1, np.percentile(datos[::8, ::8], 99.5)) * 255).clip(0, 255)
                rgb[..., k] = datos
                del datos
        return rgb


class _LectorPIL:
    def __init__(self, ruta):
        self.ruta = ruta
        with Image.open(ruta) as img:
            self.tam = img.size
            self.afin = _afin_de_world_file(ruta) or _afin_de_geotiff(img)

    def leer(self, c0, f0, c1, f1, ow, oh):
        with Image.open(self.ruta) as img:
            sub = img.crop((c0, f0, c1, f1)).convert("RGB")
            if (ow, oh) != sub.size:
                sub = sub.resize((ow, oh), Image.BOX)
            return np.asarray(sub)


def afin_desde_dxf(ruta_dxf, nombre_imagen=None):
    """Georreferencia de una imagen insertada en un DXF (entidad IMAGE).

    Es el calce que ya hizo el dibujante en AutoCAD/Civil 3D: con esto la
    ortofoto queda en las mismas coordenadas del plano sin world file.
    Devuelve (afin, nombre_archivo, (ancho_px, alto_px)).
    """
    from ezdxf import recover

    doc, _ = recover.readfile(ruta_dxf)
    imagenes = []
    for im in doc.modelspace().query("IMAGE"):
        idef = doc.entitydb.get(im.dxf.image_def_handle)
        archivo = idef.dxf.filename.replace("\\", "/").split("/")[-1] if idef else ""
        w, h = im.dxf.image_size.x, im.dxf.image_size.y
        ins, u, v = im.dxf.insert, im.dxf.u_pixel, im.dxf.v_pixel
        # Insercion = esquina inferior izquierda; v apunta hacia arriba (fila hacia abajo)
        afin = [u.x, -v.x, ins.x + h * v.x, u.y, -v.y, ins.y + h * v.y]
        imagenes.append((afin, archivo, (int(w), int(h))))
    if not imagenes:
        raise ValueError(f"No hay ninguna imagen insertada en {Path(ruta_dxf).name}")
    if nombre_imagen:
        nombre = Path(nombre_imagen).stem.lower()
        for im in imagenes:
            if Path(im[1]).stem.lower() == nombre:
                return im
    # Una sola imagen (o ninguna con el mismo nombre, p.ej. si se exporto a JPG): la mas grande
    return max(imagenes, key=lambda im: im[2][0] * im[2][1])


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
