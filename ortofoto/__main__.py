"""Programa: topografia (+ ortofoto) -> bordes unidos, areas cerradas con achurado y metrado.

Ventana (recomendado):
  python -m ortofoto.gui

Linea de comandos:
  # Calce tomado de la imagen insertada en el plano de Civil 3D
  python -m ortofoto --puntos CVS.txt --orto "ORTF BAMBU.tif" --calce-dxf "PLANO TOP.dxf" -o salida/

  # Foto georreferenciada (GeoTIFF o world file) o sin foto (solo geometria)
  python -m ortofoto --puntos puntos.csv --orto ortofoto.tif -o salida/
  python -m ortofoto --puntos puntos.csv -o salida/

  # Foto sin coordenadas: puntos de control (col, fila, este, norte)
  python -m ortofoto --puntos puntos.csv --orto foto.jpg --control control.csv -o salida/
"""
import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import areas, base as basemod, calce, exportar, topografia, unir
from .imagen import Ortofoto, afin_desde_dxf

CODIGOS_DEFECTO = Path(__file__).with_name("codigos.json")
# Compatibilidad: codigos de borde usados para el calce en la prueba sintetica
CODIGOS_BORDE = {"VER", "LP", "MAR", "ACC", "SAR", "ESQ", "VERMA", "CA", "PAV", "CSH", "CNTA", "PTA"}


@dataclass
class Opciones:
    puntos: str
    salida: str = "salida_ortofoto"
    orto: str = ""
    calce_dxf: str = ""
    control: str = ""
    calce_auto: bool = True
    radio_calce: float = 3.0
    resolucion: float = 0.0  # m por pixel de trabajo; 0 = la de la foto
    codigos: str = str(CODIGOS_DEFECTO)
    plantilla: str = ""
    ventana: tuple = None
    desactivados: set = field(default_factory=set)  # codigos que no se procesan
    capas_apagadas: set = field(default_factory=set)  # capas que salen apagadas en el DXF
    completar: bool = True  # con foto: unir tambien lo que la foto no confirma (queda para revisar)
    plano_base: str = ""  # DXF del proyecto (lotes, fachadas): el resultado se agrega sobre una copia
    capas_limite: tuple = basemod.CAPAS_LIMITE  # capas del limite de propiedad en el plano base
    veredas_foto: bool = False  # forma de las veredas segun el concreto visible en la ortofoto
    codigos_editados: tuple = None  # (codigos, alias) ya cargados desde la ventana


def ruta_libre(ruta, avisar=print):
    """Si el archivo esta abierto en otro programa (AutoCAD, Excel), usa nombre_2, nombre_3..."""
    ruta = Path(ruta)
    candidata, n = ruta, 1
    while True:
        try:
            if candidata.exists():
                with open(candidata, "a+b"):
                    pass
            if candidata != ruta:
                avisar(f"AVISO: {ruta.name} esta abierto en otro programa; se guarda como {candidata.name}")
            return candidata
        except PermissionError:
            n += 1
            candidata = ruta.with_name(f"{ruta.stem}_{n}{ruta.suffix}")


def guardar_muestra(orto, puntos, out, avisar=print, lado=150.0):
    """Recorte de la ortofoto (lado x lado m, con world file) en la zona con mas veredas.

    Sirve para enviar una muestra pequena de la foto real sin subir el archivo completo.
    """
    import numpy as np

    ver = np.array([(p.e, p.n) for p in puntos if p.codigo == "VER"] or [(p.e, p.n) for p in puntos])
    # Centro: la celda de lado x lado con mas puntos de vereda
    celdas = {}
    for x, y in ver:
        k = (int(x // (lado / 2)), int(y // (lado / 2)))
        celdas[k] = celdas.get(k, 0) + 1
    kx, ky = max(celdas, key=celdas.get)
    cx, cy = (kx + 1) * lado / 2, (ky + 1) * lado / 2
    rec = orto.recortar(cx - lado / 2, cy - lado / 2, cx + lado / 2, cy + lado / 2)
    Path(out).mkdir(parents=True, exist_ok=True)
    ruta = ruta_libre(Path(out) / "muestra_ortofoto.jpg", avisar)
    rec.guardar(ruta)
    avisar(f"Muestra de la ortofoto guardada: {ruta.name} ({ruta.stat().st_size / 1e6:.1f} MB, "
           f"{rec.rgb.shape[1]}x{rec.rgb.shape[0]} px, centro {cx:.0f} E, {cy:.0f} N)")


def procesar(op, avisar=print):
    t0 = time.time()
    out = Path(op.salida)
    out.mkdir(parents=True, exist_ok=True)
    codigos, alias = op.codigos_editados or unir.cargar_codigos(op.codigos)
    for cod in op.desactivados:
        if cod in codigos:
            codigos[cod].activo = False

    kw = {"ventana": op.ventana} if op.puntos.lower().endswith(".dxf") else {}
    puntos = topografia.leer(op.puntos, **kw)
    if op.ventana:
        x0, y0, x1, y1 = op.ventana
        puntos = [p for p in puntos if x0 <= p.e <= x1 and y0 <= p.n <= y1]
    avisar(f"Puntos leidos: {len(puntos)}")
    if not puntos:
        raise ValueError("No hay puntos en la zona")
    xs, ys = [p.e for p in puntos], [p.n for p in puntos]
    zona = (min(xs) - 20, min(ys) - 20, max(xs) + 20, max(ys) + 20)

    orto, log = None, []
    base = None
    if op.plano_base:
        avisar("Leyendo el plano base (limites de propiedad)...")
        base = basemod.leer_base(op.plano_base, op.capas_limite)
        log.append(f"Plano base {Path(op.plano_base).name}: {len(base.limites)} limites de propiedad "
                   f"({len(base.manzanas)} manzanas cerradas) en capas {', '.join(op.capas_limite)}")
        if base.vacio:
            log.append("  AVISO: no se encontraron limites en esas capas; las veredas se arman sin limite")
        avisar(log[-1])
    if op.orto:
        avisar("Leyendo la ortofoto (solo la zona de los puntos)...")
        if op.control:
            afin, res = calce.afin_por_control(calce.leer_control(op.control))
            orto = Ortofoto.cargar(op.orto, afin=afin, ventana=zona, resolucion=op.resolucion or None)
            log.append(f"Calce por {len(res)} puntos de control: error medio {res.mean():.3f} m, maximo {res.max():.3f} m")
        elif op.calce_dxf:
            afin, nombre, tam = afin_desde_dxf(op.calce_dxf, op.orto)
            orto = Ortofoto.cargar(op.orto, afin=afin, tam_ref=tam, ventana=zona, resolucion=op.resolucion or None)
            log.append(f"Calce tomado de la imagen '{nombre}' insertada en {Path(op.calce_dxf).name}")
        else:
            orto = Ortofoto.cargar(op.orto, ventana=zona, resolucion=op.resolucion or None)
            log.append("Calce tomado de la georreferencia de la foto")
        log.append(f"Ortofoto de trabajo: {orto.rgb.shape[1]}x{orto.rgb.shape[0]} px de {orto.tam_pixel * 100:.1f} cm")
        avisar(log[-1])
        try:
            guardar_muestra(orto, puntos, out, avisar)
        except Exception as e:  # noqa: BLE001 - la muestra es opcional
            avisar(f"(No se pudo guardar la muestra de la ortofoto: {e})")
        if op.calce_auto:
            avisar("Calce automatico...")
            borde = [p for p in puntos
                     if (c := codigos.get(alias.get(p.codigo, p.codigo))) and c.activo and c.tipo != "punto"]
            de, dn, fin, ini = calce.calce_automatico(orto, borde, radio=op.radio_calce)
            if fin > ini * 1.10:
                orto.desplazar(de, dn)
                log.append(f"Calce automatico: foto movida dE={de:+.2f} m, dN={dn:+.2f} m "
                           f"(apoyo de bordes {ini:.2f} -> {fin:.2f}, con {len(borde)} puntos de borde)")
            else:
                log.append(f"Calce automatico: el calce original ya es el mejor (apoyo {ini:.2f}); no se movio la foto")
            avisar(log[-1])

    avisar("Uniendo puntos...")
    resultados, sin_conf = unir.unir_todo(puntos, codigos, orto, alias=alias, avisar=avisar,
                                         completar=op.completar, base=base)
    avisar("Cerrando areas y calculando metrados...")
    met = areas.cerrar_areas(resultados, base, usar_foto=op.veredas_foto and orto is not None)
    resumen = areas.guardar_metrado(met, ruta_libre(out / "metrado.xlsx", avisar), ruta_libre(out / "metrado.csv", avisar))
    avisar("Guardando DXF...")
    exportar.guardar_dxf(ruta_libre(out / "resultado.dxf", avisar), puntos, resultados, met, codigos, alias, orto,
                         op.plantilla or None, op.capas_apagadas, base_dxf=op.plano_base or None)
    exportar.guardar_vista(resultados, ruta_libre(out / "vista.png", avisar), orto, metrado=met,
                           ventana=(min(xs) - 5, min(ys) - 5, max(xs) + 5, max(ys) + 5))

    lineas = ["# Resultado: topografia -> polilineas, areas y metrado", ""] + [f"- {l}" for l in log]
    lineas += ["", "| Codigo | Tipo | Capa | Puntos | Polilineas | Uniones a revisar |", "|---|---|---|---|---|---|"]
    for r in resultados:
        c = r.conf
        lineas.append(f"| {r.codigo} | {c.tipo} | {c.capa} | {len(r.puntos)} | {len(r.cadenas)} | "
                      f"{sum(u.revisar for u in r.uniones)} |")
    lineas += ["", "## Metrado", "", "| Codigo | Elemento | Cantidad | Total |", "|---|---|---|---|"]
    for (pref, nombre, und), (n, tot) in sorted(resumen.items()):
        lineas.append(f"| {pref} | {nombre} | {n} | {tot:,.2f} {und} |")
    sin_pareja = sum(l.sin_pareja for l in met.lineas)
    revisar = sum(a.revisar for a in met.areas)
    lineas += ["", f"- Areas cerradas: {len(met.areas)} ({revisar} marcadas en capa REVISAR AREA)",
               f"- Bordes que no se pudieron cerrar (capa REVISAR BORDE SIN CERRAR): {sin_pareja}"]
    if sin_conf:
        lineas += ["", "Codigos sin configurar (solo puntos, capa PT-codigo): " +
                   ", ".join(f"{k or '(vacio)'} ({v})" for k, v in sorted(sin_conf.items(), key=lambda x: -x[1]))]
    lineas.append(f"\nTiempo: {time.time() - t0:.0f} s")
    texto = "\n".join(lineas) + "\n"
    ruta_libre(out / "resumen.md", avisar).write_text(texto, encoding="utf-8")
    avisar(texto)
    return resultados, met, orto


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ortofoto", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--puntos", required=True, help="CSV/TXT PNEZD o DXF con puntos COGO")
    ap.add_argument("--orto", default="", help="Ortofoto (GeoTIFF, o TIF/JPG/PNG con world file)")
    ap.add_argument("--calce-dxf", default="", help="DXF donde la ortofoto ya esta insertada (toma su calce)")
    ap.add_argument("--control", default="", help="CSV de puntos de control: col, fila, este, norte")
    ap.add_argument("--sin-calce-auto", action="store_true", help="No ajustar el desplazamiento automaticamente")
    ap.add_argument("--radio-calce", type=float, default=3.0, help="Busqueda del calce automatico (m)")
    ap.add_argument("--resolucion", type=float, default=0.0, help="Pixel de trabajo en m (0 = original)")
    ap.add_argument("--codigos", default=str(CODIGOS_DEFECTO), help="Configuracion de codigos y capas")
    ap.add_argument("--plantilla", default="", help="DXF del cual copiar colores/tipos de linea de las capas")
    ap.add_argument("--plano-base", default="",
                    help="DXF del proyecto con lotes/fachadas: veredas pegadas al limite y resultado sobre una copia")
    ap.add_argument("--capas-limite", nargs="*", default=list(basemod.CAPAS_LIMITE),
                    help="Capas del limite de propiedad en el plano base (por defecto FACHADA)")
    ap.add_argument("--desactivar", nargs="*", default=[], help="Codigos que no se procesan (p.ej. PTA CNTA)")
    ap.add_argument("--apagar", nargs="*", default=[], help="Capas que salen apagadas en el DXF")
    ap.add_argument("--veredas-foto", action="store_true",
                    help="Dibujar las veredas con la forma del concreto visible en la ortofoto (requiere plano base)")
    ap.add_argument("--solo-confirmadas", action="store_true",
                    help="Con foto: no unir lo que la foto no confirma (por defecto se une y se marca a revisar)")
    ap.add_argument("--ventana", type=float, nargs=4, metavar=("XMIN", "YMIN", "XMAX", "YMAX"))
    ap.add_argument("-o", "--salida", default="salida_ortofoto")
    a = ap.parse_args(argv)
    op = Opciones(puntos=a.puntos, salida=a.salida, orto=a.orto, calce_dxf=a.calce_dxf, control=a.control,
                  calce_auto=not a.sin_calce_auto, radio_calce=a.radio_calce, resolucion=a.resolucion,
                  codigos=a.codigos, plantilla=a.plantilla, ventana=tuple(a.ventana) if a.ventana else None,
                  desactivados={c.upper() for c in a.desactivar}, capas_apagadas=set(a.apagar),
                  completar=not a.solo_confirmadas, plano_base=a.plano_base,
                  capas_limite=tuple(a.capas_limite), veredas_foto=a.veredas_foto)
    return procesar(op)


if __name__ == "__main__":
    main()
