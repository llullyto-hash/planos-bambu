"""Capas, tipos de linea y estilos de texto copiados del plano de referencia (PETRO).

La plantilla `plantilla_petro.dxf` (creada con herramientas/crear_plantilla.py) trae las capas que
tienen contenido en PETRO con su color, tipo de linea, grosor y si se plotean, sus 34 estilos de
texto y el membrete. Si el usuario elige otra plantilla, esa manda y PETRO completa lo que falte.

Las capas se buscan sin importar mayusculas, espacios, guiones ni puntos, asi
"PAV41_HTCH_VRD-PRY" y "PAV41 HTCH-VRD PRY" son la misma capa.
"""
import re
from functools import lru_cache
from pathlib import Path

RUTA_PLANTILLA = Path(__file__).with_name("plantilla_petro.dxf")
ESTILO_TEXTO = "arial"  # estilo de PETRO para los carteles (Arial negrita va dentro del texto)
ESTILO_CUADRO = "Arial Narrow"


def normalizar(nombre):
    return re.sub(r"[^0-9A-Z]", "", str(nombre).upper().replace("Ñ", "N"))


@lru_cache(maxsize=4)
def _leer(ruta):
    import ezdxf
    from ezdxf import recover

    try:
        return ezdxf.readfile(ruta)
    except Exception:  # noqa: BLE001 - archivos de AutoCAD con errores menores
        return recover.readfile(ruta)[0]


def cargar_plantilla(ruta=None):
    """DXF de plantilla (por defecto la de PETRO incluida en el programa) o None si no existe."""
    ruta = Path(ruta) if ruta else RUTA_PLANTILLA
    if not ruta.exists():
        return None
    return _leer(str(ruta))


class Estilo:
    """Crea en `doc` las capas y estilos tal como estan en las plantillas."""

    def __init__(self, doc, plantillas=()):
        self.doc = doc
        self.plantillas = [p for p in plantillas if p is not None]
        self._indice = []
        for tpl in self.plantillas:
            self._indice.append({normalizar(c.dxf.name): c for c in tpl.layers})

    def buscar(self, nombre):
        """Capa de la plantilla con ese nombre (o None)."""
        clave = normalizar(nombre)
        for tpl, ind in zip(self.plantillas, self._indice):
            if clave in ind:
                return tpl, ind[clave]
        return None, None

    def tipo_linea(self, nombre):
        doc = self.doc
        if not nombre or nombre.upper() in ("BYLAYER", "BYBLOCK", "CONTINUOUS") or nombre in doc.linetypes:
            return nombre if nombre else "Continuous"
        for tpl in self.plantillas:
            if nombre in tpl.linetypes:
                from ezdxf.addons import Importer

                imp = Importer(tpl, doc)
                imp.import_table("linetypes", [nombre])
                imp.finalize()
                return nombre
        return nombre if nombre in doc.linetypes else "Continuous"

    def capa(self, nombre, color=7, tipo_linea="Continuous", apagada=False, grosor=-3):
        """Devuelve la capa `nombre`, creandola con las propiedades de la plantilla si las hay."""
        doc = self.doc
        if nombre in doc.layers:
            capa = doc.layers.get(nombre)
            if apagada:
                capa.off()
            return capa
        plot = 1
        _, ref = self.buscar(nombre)
        if ref is not None:
            color, tipo_linea, grosor = ref.dxf.color, ref.dxf.linetype, ref.dxf.lineweight
            plot = ref.dxf.get("plot", 1)
        tipo_linea = self.tipo_linea(tipo_linea)
        capa = doc.layers.add(nombre, color=abs(color) or 7, linetype=tipo_linea, lineweight=grosor)
        capa.dxf.plot = plot
        if ref is not None and ref.dxf.hasattr("true_color"):
            capa.dxf.true_color = ref.dxf.true_color
        if apagada:
            capa.off()
        return capa

    def estilos_texto(self):
        """Copia todos los estilos de texto de las plantillas que no esten en el dibujo."""
        from ezdxf.addons import Importer

        for tpl in self.plantillas:
            faltan = [s.dxf.name for s in tpl.styles if s.dxf.name and s.dxf.name not in self.doc.styles]
            if faltan:
                imp = Importer(tpl, self.doc)
                imp.import_table("styles", faltan)
                imp.finalize()
        if ESTILO_TEXTO not in self.doc.styles:
            self.doc.styles.add(ESTILO_TEXTO, font="arial.ttf")
        if ESTILO_CUADRO not in self.doc.styles:
            self.doc.styles.add(ESTILO_CUADRO, font="ARIALN.TTF")
