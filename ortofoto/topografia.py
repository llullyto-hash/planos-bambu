"""Lectura de puntos topograficos (numero, este, norte, cota, descripcion)."""
import csv
import difflib
import re
import unicodedata
from dataclasses import dataclass

# Codigos de control que el topografo puede escribir despues del codigo: "VER I", "LP FIN", "MAR CLS"
CONTROL = {
    "I": "inicio", "INI": "inicio", "INICIO": "inicio", "B": "inicio", "BEG": "inicio", "BEGIN": "inicio",
    "F": "fin", "FIN": "fin", "E": "fin", "END": "fin",
    "CLS": "cerrar", "CERRAR": "cerrar", "CIERRE": "cerrar", "CLOSE": "cerrar",
}


def _sin_tildes(texto):
    """'VERÁ' -> 'VERA'; la Ñ se conserva."""
    texto = texto.replace("Ñ", "\0").replace("ñ", "\1")
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return texto.replace("\0", "Ñ").replace("\1", "ñ")


def sugerir_alias(sin_conf, conocidos):
    """Codigos no reconocidos que parecen errores de escritura: {'VERD': 'VER', 'CHS': 'CSH'}."""
    conocidos = sorted(c for c in conocidos if c)
    out = {}
    for cod in sin_conf:
        if not cod or cod in conocidos:
            continue
        pref = [c for c in conocidos if len(c) >= 3 and cod.startswith(c) and len(cod) - len(c) <= 2]
        if pref:
            out[cod] = max(pref, key=len)
            continue
        letras = [c for c in conocidos if sorted(c) == sorted(cod)]  # letras cambiadas: CHS -> CSH
        if letras and len(cod) >= 3:
            out[cod] = letras[0]
            continue
        m = difflib.get_close_matches(cod, [c for c in conocidos if len(c) >= 3], n=1, cutoff=0.75)
        if m and len(cod) >= 3:
            out[cod] = m[0]
    return out


@dataclass
class Punto:
    num: str
    e: float
    n: float
    z: float
    desc: str

    @property
    def codigo(self):
        """Codigo de campo sin sufijos numericos ni espacios: 'VER 2' -> 'VER' (sin tildes: 'VÉR' -> 'VER')."""
        m = re.match(r"[A-Za-zÑñ]+", _sin_tildes(self.desc.strip()))
        return m.group(0).upper() if m else ""

    @property
    def numero(self):
        """Numero pegado al codigo: 'VER2' -> '2', 'VER 2' -> '2', 'VER' -> ''."""
        m = re.match(r"[A-Za-zÑñ]+[\s\-_]*(\d+)", _sin_tildes(self.desc.strip()))
        return m.group(1) if m else ""

    @property
    def control(self):
        """Codigo de control escrito despues del codigo: inicio, fin, cerrar o ''."""
        partes = re.split(r"[\s\-/_.]+", _sin_tildes(self.desc.strip()).upper())
        for p in partes[1:]:
            p = re.sub(r"\d+", "", p)
            if p in CONTROL:
                return CONTROL[p]
        return ""


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
