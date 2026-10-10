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

from . import areas, base as basemod, calce, exportar, laminas as lammod, topografia, unir
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
    muestras: bool = False  # exportar la ortofoto en cuadros (ZIP) para enviarla a revisar
    escala: float = 500.0  # escala de las laminas: tamano de carteles y textos
    cartel: str = "petro"  # petro: recuadro + flecha con area y perimetro | simple: texto suelto (como antes)
    corte_lineal: bool = True  # lineas de corte (CL) donde la vereda toca el limite de propiedad
    laminas: object = None  # laminas.ConfLaminas (None = sin laminas)
    carpeta_por_corrida: bool = False  # cada corrida en una subcarpeta nueva con fecha y hora
    numero_separa: bool = False  # VER1 y VER2 son lineas distintas (el numero del codigo separa bordes)
    codigos_control: bool = False  # respetar VER I (inicio), VER F (fin), MAR CLS (cerrar)


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


MUESTRA_LADO = 100.0  # m por cuadro
MUESTRA_PIXEL = 0.08  # m por pixel de las muestras
MUESTRA_ZIP_MB = 20.0  # tamano maximo de cada ZIP
MUESTRA_CODIGOS = ("VER", "ALC", "CSH", "MAR", "ACC", "CNTA", "PTA")


def exportar_muestras(orto, puntos, out, avisar=print, lado=MUESTRA_LADO, pixel=MUESTRA_PIXEL,
                      max_mb=MUESTRA_ZIP_MB):
    """Toda la ortofoto en cuadros de `lado` m (solo donde hay puntos de veredas, canales, etc.),
    a `pixel` m por pixel, en JPG con world file, agrupados en ZIP de hasta `max_mb` MB.

    Sirve para enviar la foto real completa a revisar sin subir el archivo original (varios GB).
    """
    import io
    import zipfile

    import numpy as np
    from PIL import Image

    sel = [p for p in puntos if p.codigo in MUESTRA_CODIGOS] or puntos
    celdas = sorted({(int(np.floor(p.e / lado)), int(np.floor(p.n / lado))) for p in sel})
    carpeta = Path(out) / "muestras_ortofoto"
    carpeta.mkdir(parents=True, exist_ok=True)
    zips, actual, tam, n = [], None, 0.0, 0
    for kx, ky in celdas:
        x0, y0 = kx * lado, ky * lado
        try:
            rec = orto.recortar(x0, y0, x0 + lado, y0 + lado)
        except ValueError:
            continue
        h, w = rec.rgb.shape[:2]
        if h < 10 or w < 10:
            continue
        img = Image.fromarray(rec.rgb)
        escala = rec.tam_pixel / pixel
        if escala < 1:  # la foto es mas fina que `pixel`: se reduce
            img = img.resize((max(1, round(w * escala)), max(1, round(h * escala))), Image.LANCZOS)
        a, b, c, d, e, f = rec.afin
        fx, fy = w / img.width, h / img.height
        a2, b2, d2, e2 = a * fx, b * fy, d * fx, e * fy
        c0, f0 = c + a2 * 0.5 + b2 * 0.5, f + d2 * 0.5 + e2 * 0.5  # centro del pixel superior izquierdo
        nombre = f"orto_{int(x0)}_{int(y0)}"
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        datos = buf.getvalue()
        jgw = "\n".join(f"{v:.10f}" for v in (a2, d2, b2, e2, c0, f0)) + "\n"
        mb = len(datos) / 1e6
        if actual is None or tam + mb > max_mb:
            if actual is not None:
                actual.close()
            ruta = carpeta / f"muestras_{len(zips) + 1:02d}.zip"
            zips.append(ruta)
            actual = zipfile.ZipFile(ruta, "w", zipfile.ZIP_STORED)
            tam = 0.0
        actual.writestr(nombre + ".jpg", datos)
        actual.writestr(nombre + ".jgw", jgw)
        tam += mb
        n += 1
    if actual is not None:
        actual.close()
    avisar(f"Muestras de la ortofoto: {n} cuadros de {lado:.0f} m a {pixel * 100:.0f} cm/pixel en "
           f"{len(zips)} ZIP (carpeta {carpeta.name}). Envie los ZIP para revisar con la foto real.")
    return zips


@dataclass
class Calculo:
    """Resultado del procesamiento antes de exportar (se puede revisar y corregir en la ventana)."""
    op: object
    puntos: list
    resultados: list
    met: object
    orto: object
    codigos: dict
    alias: dict
    base: object
    log: list
    sin_conf: dict
    t0: float


def calcular(op, avisar=print):
    """Lee, calza, une y cierra areas. No escribe el DXF ni el metrado (ver exportar_calculo)."""
    t0 = time.time()
    if op.carpeta_por_corrida and not getattr(op, "_carpeta_creada", False):
        op.salida = str(Path(op.salida) / time.strftime("corrida_%Y-%m-%d_%H%M%S"))
        op._carpeta_creada = True
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
    if orto is not None and op.muestras:
        avisar("Exportando muestras de la ortofoto...")
        try:
            exportar_muestras(orto, puntos, out, avisar)
        except Exception as e:  # noqa: BLE001 - las muestras son opcionales
            avisar(f"(No se pudieron exportar las muestras: {e})")

    avisar("Uniendo puntos...")
    resultados, sin_conf = unir.unir_todo(puntos, codigos, orto, alias=alias, avisar=avisar,
                                         completar=op.completar, base=base,
                                         numero_separa=getattr(op, "numero_separa", False),
                                         control=getattr(op, "codigos_control", False))
    if sin_conf:
        sug = topografia.sugerir_alias(sin_conf, set(codigos) | set(alias))
        log.append("Codigos sin configurar: " + ", ".join(f"{k or '(vacio)'} ({v})" for k, v in
                                                          sorted(sin_conf.items(), key=lambda x: -x[1])))
        if sug:
            log.append("  Parecen errores de escritura: " + ", ".join(f"{k} -> {v}?" for k, v in sug.items()) +
                       " (agregarlos como alias en Codigos y capas)")
        avisar("\n".join(log[-2:] if sug else log[-1:]))
    avisar("Cerrando areas y calculando metrados...")
    met = areas.cerrar_areas(resultados, base, usar_foto=op.veredas_foto and orto is not None)
    if op.veredas_foto and orto is not None:
        avisar("Buscando concreto visible en la foto...")
        from .concreto import concreto_visible

        vis = concreto_visible(orto, base, [(p.e, p.n) for p in puntos], avisar=avisar)
        # Configurable en la tabla de codigos (codigo CV): capa, prefijo del metrado, achurado
        conf_cv = codigos.get("CV") or unir.Codigo(
            capa="CONCRETO EXISTENTE (FOTO)", tipo="contorno", capa_area="CONCRETO EXISTENTE (FOTO)", prefijo="CO",
            color=4, color_area=4, patron="ANSI37", escala_patron=0.1, nombre="Concreto (visto en la foto)")
        if conf_cv.activo:
            areas.agregar_concreto_visible(met, vis, conf_cv, [(p.e, p.n) for p in puntos])
            log.append(f"Concreto visto en la foto y respaldado por puntos: {sum(a.codigo == 'CV' for a in met.areas)} "
                       f"areas (capa {conf_cv.capa_area}, metrado {conf_cv.prefijo}); sin puntos en su borde: "
                       f"{len(met.sin_puntos)} (capa REVISAR CONCRETO SIN PUNTOS, sin metrado)")
    return Calculo(op, puntos, resultados, met, orto, codigos, alias, base, log, sin_conf, t0)


def exportar_calculo(c, avisar=print):
    """Escribe metrado (xlsx/csv), DXF, vista y resumen de un Calculo (corregido o no)."""
    op, puntos, resultados, met, orto = c.op, c.puntos, c.resultados, c.met, c.orto
    codigos, alias, log, sin_conf, t0 = c.codigos, c.alias, list(c.log), c.sin_conf, c.t0
    out = Path(op.salida)
    out.mkdir(parents=True, exist_ok=True)
    xs, ys = [p.e for p in puntos], [p.n for p in puntos]
    if getattr(op, "corte_lineal", False):
        cortes = areas.cortes_lineales(met, c.base, resultados)
        avisar(f"Lineas de corte (CL): {len(cortes)} tramos, {sum(l.linea.length for l in cortes):,.2f} m")
    conf_lam = getattr(op, "laminas", None)
    lams = lammod.dividir(met, conf_lam) if conf_lam is not None and conf_lam.activar else []
    if lams and conf_lam.numerar_por_lamina:
        areas._numerar(met, lammod.clave_orden(lams))
    else:
        areas._numerar(met)
    if lams:
        log.append(f"Laminas: {len(lams)} a escala 1/{int(conf_lam.escala)} "
                   f"({', '.join(l.nombre for l in lams)})")
        avisar(log[-1])
    avisos = verificar(met)
    resumen = areas.guardar_metrado(met, ruta_libre(out / "metrado.xlsx", avisar), ruta_libre(out / "metrado.csv", avisar),
                                    laminas=lams)
    avisar("Guardando DXF...")
    ruta_dxf = ruta_libre(out / "resultado.dxf", avisar)
    doc, creados, encimados = exportar.guardar_dxf(
        ruta_dxf, puntos, resultados, met, codigos, alias, orto, op.plantilla or None, op.capas_apagadas,
        base_dxf=op.plano_base or None, escala=getattr(op, "escala", 500.0), cartel=getattr(op, "cartel", "petro"),
        laminas=lams, conf_laminas=conf_lam, base=c.base)
    if encimados:
        avisos.append(f"{encimados} carteles no encontraron un lugar libre y quedaron encimados: moverlos a mano "
                      "(marcados en la capa REVISAR CARTEL ENCIMADO, que no se plotea)")
    if creados and conf_lam.vista_pdf:
        avisar("Vista previa de las laminas (PDF)...")
        try:
            # Se dibuja una copia liviana (sin el plano base ni los puntos) para que sea rapida
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                lim = c.base.limites if c.base is not None and not c.base.vacio else None
                previa, nombres, _ = exportar.guardar_dxf(
                    Path(tmp) / "previa.dxf", [], resultados, met, codigos, alias, None, op.plantilla or None, (),
                    escala=getattr(op, "escala", 500.0), cartel=getattr(op, "cartel", "petro"), laminas=lams,
                    conf_laminas=conf_lam, base=c.base, limites=lim)
                lammod.vista_pdf(previa, nombres, ruta_libre(out / "laminas_vista_previa.pdf", avisar), avisar=avisar)
        except Exception as e:  # noqa: BLE001 - la vista previa es opcional
            avisar(f"(No se pudo crear la vista previa de las laminas: {e})")
    del doc
    exportar.guardar_vista(resultados, ruta_libre(out / "vista.png", avisar), orto, metrado=met,
                           ventana=(min(xs) - 5, min(ys) - 5, max(xs) + 5, max(ys) + 5))
    c.avisos, c.laminas = avisos, lams
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
    if lams:
        lineas += ["", "## Laminas", "", "| Lamina | Areas | Lineas |", "|---|---|---|"]
        lineas += [f"| {l.nombre} | {len(l.areas)} | {len(l.lineas)} |" for l in lams]
    if avisos:
        lineas += ["", "## Revision antes de plotear", ""] + [f"- {a}" for a in avisos]
    reglas = {}
    for a in met.areas:
        for r in getattr(a, "reglas", []):
            reglas[r] = reglas.get(r, 0) + 1
    if reglas:
        lineas += ["", "## Reglas aplicadas (cuantas areas)", ""] + [f"- {k}: {v}" for k, v in sorted(reglas.items())]
    if sin_conf:
        sugerencias = topografia.sugerir_alias(sin_conf, set(codigos) | set(alias))
        lineas += ["", "Codigos sin configurar (solo puntos, capa PT-codigo): " +
                   ", ".join(f"{k or '(vacio)'} ({v})" for k, v in sorted(sin_conf.items(), key=lambda x: -x[1]))]
        if sugerencias:
            lineas += ["Posibles errores de escritura: " + ", ".join(f"{k} -> {v}?" for k, v in sugerencias.items())]
    lineas.append(f"\nTiempo: {time.time() - t0:.0f} s")
    texto = "\n".join(lineas) + "\n"
    ruta_libre(out / "resumen.md", avisar).write_text(texto, encoding="utf-8")
    avisar(texto)
    return resultados, met, orto


def verificar(met):
    """Revision antes de plotear: etiquetas repetidas, areas del mismo codigo que se tocan o pisan."""
    avisos = []
    vistas = {}
    for a in met.areas:
        if a.etiqueta in vistas:
            avisos.append(f"La etiqueta {a.etiqueta} esta repetida")
        vistas[a.etiqueta] = a
    from shapely import STRtree

    if met.areas:
        arbol = STRtree([a.poligono for a in met.areas])
        for i, a in enumerate(met.areas):
            for j in arbol.query(a.poligono):
                j = int(j)
                if j <= i:
                    continue
                b = met.areas[j]
                inter = a.poligono.intersection(b.poligono)
                if inter.area > 0.05:
                    avisos.append(f"{a.etiqueta} y {b.etiqueta} se pisan ({inter.area:.2f} m2)")
                elif a.codigo == b.codigo and inter.length > 0.5:
                    avisos.append(f"{a.etiqueta} y {b.etiqueta} se tocan en {inter.length:.1f} m: "
                                  "revisar si son una sola area (una polilinea por etiqueta)")
    return avisos


def procesar(op, avisar=print):
    return exportar_calculo(calcular(op, avisar), avisar)




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
    ap.add_argument("--muestras", action="store_true",
                    help="Exportar la ortofoto en cuadros de 100 m (ZIP) para enviarla a revisar")
    ap.add_argument("--solo-confirmadas", action="store_true",
                    help="Con foto: no unir lo que la foto no confirma (por defecto se une y se marca a revisar)")
    ap.add_argument("--ventana", type=float, nargs=4, metavar=("XMIN", "YMIN", "XMAX", "YMAX"))
    ap.add_argument("--escala", type=float, default=500.0, help="Escala de las laminas y carteles (500 = 1/500)")
    ap.add_argument("--cartel", choices=("petro", "simple"), default="petro",
                    help="petro: recuadro + flecha con area y perimetro; simple: texto suelto como antes")
    ap.add_argument("--sin-corte-lineal", action="store_true", help="No generar las lineas de corte (CL)")
    ap.add_argument("--laminas", action="store_true", help="Dividir en laminas A1 con membrete (layouts)")
    ap.add_argument("--orientacion", choices=("norte", "auto"), default="norte",
                    help="Laminas con el norte arriba o giradas segun la direccion principal del dibujo")
    ap.add_argument("--traslape", type=float, default=5.0, help="m que se repiten entre laminas vecinas")
    ap.add_argument("--prefijo-lamina", default="D-", help="Prefijo del numero de lamina (D-01, D-02...)")
    ap.add_argument("--membrete", default="", help="JSON con los datos del membrete (proyecto, fecha, ...)")
    ap.add_argument("--sin-vista-pdf", action="store_true", help="No crear el PDF de vista previa de las laminas")
    ap.add_argument("--carpeta-por-corrida", action="store_true", help="Guardar cada corrida en una subcarpeta nueva")
    ap.add_argument("--numero-separa", action="store_true",
                    help="El numero pegado al codigo separa lineas (VER1 y VER2 no se unen entre si)")
    ap.add_argument("--codigos-control", action="store_true",
                    help="Respetar codigos de control: VER I (inicio), VER F (fin), MAR CLS (cerrar)")
    ap.add_argument("-o", "--salida", default="salida_ortofoto")
    a = ap.parse_args(argv)
    conf_lam = None
    if a.laminas:
        membrete = lammod.cargar_membrete()
        if a.membrete:
            import json

            membrete.update(json.loads(Path(a.membrete).read_text(encoding="utf-8")))
        conf_lam = lammod.ConfLaminas(escala=a.escala, traslape=a.traslape, orientacion=a.orientacion,
                                      prefijo=a.prefijo_lamina, membrete=membrete, vista_pdf=not a.sin_vista_pdf)
    op = Opciones(puntos=a.puntos, salida=a.salida, orto=a.orto, calce_dxf=a.calce_dxf, control=a.control,
                  calce_auto=not a.sin_calce_auto, radio_calce=a.radio_calce, resolucion=a.resolucion,
                  codigos=a.codigos, plantilla=a.plantilla, ventana=tuple(a.ventana) if a.ventana else None,
                  desactivados={c.upper() for c in a.desactivar}, capas_apagadas=set(a.apagar),
                  completar=not a.solo_confirmadas, plano_base=a.plano_base,
                  capas_limite=tuple(a.capas_limite), veredas_foto=a.veredas_foto, muestras=a.muestras,
                  escala=a.escala, cartel=a.cartel, corte_lineal=not a.sin_corte_lineal, laminas=conf_lam,
                  carpeta_por_corrida=a.carpeta_por_corrida, numero_separa=a.numero_separa,
                  codigos_control=a.codigos_control)
    return procesar(op)


if __name__ == "__main__":
    main()
