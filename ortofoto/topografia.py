"""Lectura de puntos topograficos (numero, este, norte, cota, descripcion)."""
import csv
import re
from dataclasses import dataclass


@dataclass
class Punto:
    num: str
    e: float
    n: float
    z: float
    desc: str

    @property
    def codigo(self):
        """Codigo de campo sin sufijos numericos ni espacios: 'VER 2' -> 'VER'."""
        m = re.match(r"[A-Za-zÑñ]+", self.desc.strip())
        return m.group(0).upper() if m else ""


def leer_csv(ruta):
    """CSV/TXT en formato PNEZD (punto, norte, este, cota, descripcion).

    Acepta coma, punto y coma o tabulador como separador y omite encabezados.
    """
    with open(ruta, encoding="utf-8-sig", errors="replace") as fh:
        muestra = fh.read(4096)
        fh.seek(0)
        sep = max([",", ";", "\t"], key=muestra.count)
        puntos = []
        for fila in csv.reader(fh, delimiter=sep):
            if len(fila) < 4:
                continue
            try:
                n, e, z = float(fila[1]), float(fila[2]), float(fila[3])
            except ValueError:
                continue
            desc = fila[4].strip() if len(fila) > 4 else ""
            puntos.append(Punto(fila[0].strip(), e, n, z, desc))
    return puntos


def leer_dxf(ruta, capa="Texto Cogo", ventana=None):
    """Puntos COGO exportados de Civil 3D como tres MTEXT por punto.

    Cada punto trae {\\C1;numero}, {\\C2;cota} y {\\C3;descripcion} apilados
    sobre la ubicacion del punto. Se agrupan por cercania al texto del numero.
    `ventana` = (xmin, ymin, xmax, ymax) para leer solo una zona.
    """
    from ezdxf import recover

    doc, _ = recover.readfile(ruta)
    textos = {"1": [], "2": [], "3": []}
    for t in doc.modelspace().query(f'MTEXT[layer=="{capa}"]'):
        m = re.match(r"\{\\C(\d);(.*)\}$", t.text.strip(), re.S)
        if not m or m.group(1) not in textos:
            continue
        p = t.dxf.insert
        if ventana and not (ventana[0] <= p.x <= ventana[2] and ventana[1] <= p.y <= ventana[3]):
            continue
        textos[m.group(1)].append((p.x, p.y, p.z, m.group(2).strip()))
    return _agrupar(textos)


def _agrupar(textos, radio=0.6):
    from scipy.spatial import cKDTree

    puntos = []
    arboles = {k: (cKDTree([(x, y) for x, y, *_ in v]), v) for k, v in textos.items() if v}
    for x, y, z, num in textos["1"]:
        cota, desc = z, ""
        if "2" in arboles:
            d, i = arboles["2"][0].query((x, y))
            if d < radio:
                try:
                    cota = float(arboles["2"][1][i][3])
                except ValueError:
                    pass
        if "3" in arboles:
            d, i = arboles["3"][0].query((x, y))
            if d < radio:
                desc = arboles["3"][1][i][3]
        puntos.append(Punto(num, x, y, cota, desc))
    return puntos


def leer(ruta, **kw):
    return leer_dxf(ruta, **kw) if str(ruta).lower().endswith(".dxf") else leer_csv(ruta)
