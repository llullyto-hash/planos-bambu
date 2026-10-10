"""Intercambio con la pagina colaborativa (Revision en linea).

exportar_proyecto(calc, ruta)      -> proyecto_web.json: areas, puntos, limites de propiedad y codigos,
                                      para subir a la pagina (una vez por proyecto).
importar_correcciones(calc, ruta)  -> reemplaza las areas del calculo por las corregidas en la pagina
                                      (correcciones_web.json); luego se exporta el DXF y el metrado.

Las coordenadas viajan en metros (UTM), redondeadas al milimetro.
"""
import json
from pathlib import Path

import numpy as np
from shapely.geometry import MultiPolygon, Polygon

from . import areas

VERSION_FORMATO = 1
COLORES = {"VER": "#e4572e", "ALC": "#2e86de", "PTA": "#8e44ad", "CNTA": "#16a085", "MAR": "#f39c12",
           "ACC": "#d35400", "CV": "#95a5a6"}
CODIGOS_PUNTO_VISIBLES = 12  # caracteres maximos de la descripcion de un punto


def _r(v):
    return round(float(v), 3)


def _coords(pol):
    return [[_r(x), _r(y)] for x, y in list(pol.exterior.coords)[:-1]]


def exportar_proyecto(calc, ruta, nombre=""):
    """Escribe el archivo que se sube a la pagina colaborativa."""
    met = calc.met
    usados = sorted({a.codigo for a in met.areas} | {k for k, c in calc.codigos.items()
                                                     if c.capa_area and c.tipo in ("franja", "contorno")})
    codigos = {}
    for k in usados:
        c = calc.codigos.get(k)
        if c is None:
            continue
        codigos[k] = {"nombre": c.nombre or k, "prefijo": c.prefijo or k, "color": COLORES.get(k, "#f1c40f"),
                      "largo": bool(getattr(c, "etiqueta_largo", False))}
    lista = []
    for k, a in enumerate(met.areas):
        lista.append({"id": f"a{k:04d}", "cod": a.codigo, "coords": _coords(a.poligono), "revisar": bool(a.revisar),
                      "nota": a.nota or "", "largo": _r(a.largo or 0), "ancho": _r(a.ancho or 0),
                      "origen": a.origen or ""})
    alias = calc.alias
    puntos = [[_r(p.e), _r(p.n), round(float(p.z), 2), str(p.num), str(p.desc)[:CODIGOS_PUNTO_VISIBLES],
               alias.get(p.codigo, p.codigo)] for p in calc.puntos]
    limites = []
    if calc.base is not None and not calc.base.vacio:
        for ln in calc.base.limites:
            c = np.asarray(ln.coords)[:, :2]
            limites.append([[_r(x), _r(y)] for x, y in c])
    # Laminas para plotear (si estan activadas): la pagina dibuja sus limites y dice en cual cae cada area
    laminas = []
    conf_lam = getattr(calc.op, "laminas", None)
    if conf_lam is not None and conf_lam.activar:
        from . import laminas as lammod

        for lam in lammod.dividir(met, conf_lam):
            laminas.append({"nombre": lam.nombre, "coords": _coords(lam.nucleo)})
    for d, a in zip(lista, met.areas):
        d["perimetro"] = _r(a.poligono.exterior.length)
    datos = {"formato": "planos-bambu/proyecto", "version": VERSION_FORMATO,
             "nombre": nombre or Path(calc.op.puntos).stem, "codigos": codigos, "areas": lista,
             "puntos": puntos, "limites": limites, "laminas": laminas}
    Path(ruta).write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return datos


def _poligono(coords):
    pol = Polygon(coords)
    if not pol.is_valid:
        pol = pol.buffer(0)
        if isinstance(pol, MultiPolygon):
            pol = max(pol.geoms, key=lambda g: g.area)
    return pol


def importar_correcciones(calc, ruta):
    """Reemplaza las areas del calculo por las de la pagina. Devuelve (n_areas, codigos_desconocidos)."""
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    if datos.get("formato") not in ("planos-bambu/correcciones", "planos-bambu/proyecto"):
        raise ValueError("El archivo no es de la pagina colaborativa (correcciones_web.json)")
    nuevas, desconocidos = [], set()
    for d in datos.get("areas", []):
        if d.get("borrado"):
            continue
        conf = calc.codigos.get(d.get("cod"))
        if conf is None:
            desconocidos.add(d.get("cod"))
            continue
        coords = d.get("coords") or []
        if len(coords) < 3:
            continue
        pol = _poligono([tuple(c) for c in coords])
        if pol.is_empty or pol.area < areas.AREA_MIN:
            continue
        largo = float(d.get("largo") or 0)
        if not largo:
            r = pol.minimum_rotated_rectangle
            c = np.asarray(r.exterior.coords)
            largo = float(max(np.hypot(*np.diff(c, axis=0).T)))
        nota = d.get("nota") or ""
        nuevas.append(areas.Area(d["cod"], conf, pol, d.get("origen") or "web", pol.area / max(largo, 1e-6), largo,
                                 bool(d.get("revisar")), nota=nota))
    calc.met.areas = nuevas
    areas._numerar(calc.met)
    # Notas de la pagina: se dibujan en el DXF (capa NOTAS DE REVISION)
    calc.met.notas = [{"x": float(n["x"]), "y": float(n["y"]), "texto": str(n.get("texto") or "")[:1000],
                       "hecha": bool(n.get("hecha"))}
                      for n in datos.get("notas", []) if isinstance(n, dict) and "x" in n and "y" in n]
    return len(nuevas), sorted(c for c in desconocidos if c)
