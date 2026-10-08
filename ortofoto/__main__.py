"""Programa: ortofoto + topografia -> polilineas por capa.

Ejemplos:
  # Foto con world file (.tfw/.jgw) o GeoTIFF, puntos en CSV PNEZD
  python -m ortofoto --orto ORTF.tif --puntos puntos.csv -o salida/

  # Calce tomado de la imagen insertada en el plano de Civil 3D
  python -m ortofoto --orto "ORTF BAMBU.tif" --calce-dxf "PLANO TOP.dxf" --puntos puntos.csv -o salida/

  # Foto sin coordenadas: puntos de control (col, fila, este, norte)
  python -m ortofoto --orto foto.jpg --control control.csv --puntos puntos.csv -o salida/
"""
import argparse
import collections
from pathlib import Path

from . import calce, exportar, topografia, unir
from .imagen import Ortofoto, afin_desde_dxf

CODIGOS_DEFECTO = Path(__file__).with_name("codigos.json")
# Codigos levantados sobre bordes: sirven para el calce automatico
CODIGOS_BORDE = {"VER", "LP", "MAR", "ACC", "SAR", "ESQ", "VERMA", "CA", "PAV"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ortofoto", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--puntos", required=True, help="CSV PNEZD o DXF con puntos COGO")
    ap.add_argument("--orto", help="Ortofoto (GeoTIFF, o TIF/JPG/PNG con world file)")
    ap.add_argument("--calce-dxf", help="DXF donde la ortofoto ya esta insertada (toma su georreferencia)")
    ap.add_argument("--control", help="CSV de puntos de control: col, fila, este, norte")
    ap.add_argument("--sin-calce-auto", action="store_true", help="No ajustar el desplazamiento automaticamente")
    ap.add_argument("--radio-calce", type=float, default=3.0, help="Busqueda del calce automatico (m)")
    ap.add_argument("--codigos", default=str(CODIGOS_DEFECTO), help="Configuracion de codigos y capas")
    ap.add_argument("--plantilla", help="DXF del cual copiar colores/tipos de linea de las capas")
    ap.add_argument("--ventana", type=float, nargs=4, metavar=("XMIN", "YMIN", "XMAX", "YMAX"),
                    help="Procesar solo esta zona")
    ap.add_argument("-o", "--salida", default="salida_ortofoto")
    args = ap.parse_args(argv)

    out = Path(args.salida)
    out.mkdir(parents=True, exist_ok=True)
    codigos, alias = unir.cargar_codigos(args.codigos)

    kw = {"ventana": args.ventana} if args.puntos.lower().endswith(".dxf") else {}
    puntos = topografia.leer(args.puntos, **kw)
    if args.ventana:
        x0, y0, x1, y1 = args.ventana
        puntos = [p for p in puntos if x0 <= p.e <= x1 and y0 <= p.n <= y1]
    print(f"Puntos leidos: {len(puntos)}")
    if not puntos:
        raise SystemExit("No hay puntos en la zona")

    orto = None
    log = []
    if args.orto:
        if args.control:
            orto = Ortofoto.sin_georreferencia(args.orto)
            afin, res = calce.afin_por_control(calce.leer_control(args.control))
            orto.afin = afin
            log.append(f"Calce por {len(res)} puntos de control: error medio {res.mean():.3f} m, maximo {res.max():.3f} m")
        elif args.calce_dxf:
            orto = Ortofoto.sin_georreferencia(args.orto)
            afin, nombre, (w, h) = afin_desde_dxf(args.calce_dxf, args.orto)
            hh, ww = orto.rgb.shape[:2]
            if (ww, hh) != (w, h):  # la foto se exporto a otra resolucion
                f = w / ww
                afin = [afin[0] * f, afin[1] * f, afin[2], afin[3] * f, afin[4] * f, afin[5]]
            orto.afin = afin
            log.append(f"Calce tomado de la IMAGE '{nombre}' del DXF")
        else:
            orto = Ortofoto.abrir(args.orto)
            log.append("Calce tomado de la georreferencia de la foto")
        xs = [p.e for p in puntos]
        ys = [p.n for p in puntos]
        orto = orto.recortar(min(xs) - 20, min(ys) - 20, max(xs) + 20, max(ys) + 20)
        log.append(f"Ortofoto: {orto.rgb.shape[1]}x{orto.rgb.shape[0]} px de {orto.tam_pixel * 100:.1f} cm")
        if not args.sin_calce_auto:
            borde = [p for p in puntos if alias.get(p.codigo, p.codigo) in CODIGOS_BORDE]
            de, dn, fin, ini = calce.calce_automatico(orto, borde, radio=args.radio_calce)
            orto.desplazar(de, dn)
            log.append(f"Calce automatico: foto movida dE={de:+.2f} m, dN={dn:+.2f} m "
                       f"(apoyo de bordes {ini:.2f} -> {fin:.2f}, con {len(borde)} puntos de borde)")
        nombre_foto = out / "ortofoto_calzada.jpg"
        orto.guardar(nombre_foto)

    resultados, sin_conf = unir.unir_todo(puntos, codigos, orto, alias=alias)
    exportar.guardar_dxf(resultados, codigos, out / "polilineas.dxf", orto,
                         "ortofoto_calzada.jpg" if orto is not None else None, args.plantilla, puntos)
    exportar.guardar_vista(resultados, out / "vista.png", orto)

    lineas = ["# Resultado ortofoto + topografia", ""] + [f"- {l}" for l in log] + ["", "| Codigo | Capa | Puntos | Polilineas | Uniones | A revisar |", "|---|---|---|---|---|---|"]
    for r in resultados:
        c = codigos[r.codigo]
        lineas.append(f"| {r.codigo} | {c.capa} | {len(r.puntos)} | {len(r.cadenas)} | {len(r.uniones)} | "
                      f"{sum(u.revisar for u in r.uniones)} |")
    if sin_conf:
        lineas += ["", "Codigos sin configurar (no se dibujaron): " +
                   ", ".join(f"{k or '(vacio)'} ({v})" for k, v in sorted(sin_conf.items(), key=lambda x: -x[1]))]
    (out / "resumen.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas))
    return resultados, orto


if __name__ == "__main__":
    main()
