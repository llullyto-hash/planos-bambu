"""Punto de entrada del ejecutable de Windows (PyInstaller).

Sin argumentos abre la ventana. Con --prueba CARPETA corre una prueba sin
ventana (la usa la compilacion para verificar que el .exe funciona).
"""
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):  # ejecutado como script: usar el paquete del repositorio
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def prueba(carpeta):
    from ortofoto import laminas
    from ortofoto.__main__ import Opciones, procesar

    out = Path(carpeta)
    out.mkdir(parents=True, exist_ok=True)
    pts = out / "puntos.csv"
    with open(pts, "w", encoding="utf-8") as fh:
        n = 1
        for k in range(6):  # vereda por secciones junto a una fachada
            x = 1000 + k * 8
            for y, d in ((2000.0, "CSH"), (1999.9, "VER"), (1998.0, "VER")):
                fh.write(f"{n},{y},{x},100.0,{d}\n")
                n += 1
    # Foto de prueba con su world file: verifica que la lectura de imagenes funciona en el .exe
    import numpy as np
    from PIL import Image

    img = np.full((120, 1100, 3), 120, np.uint8)
    img[0:40, :] = 200  # franja clara = vereda (2 m a 5 cm/px)
    Image.fromarray(img).save(out / "foto.png")
    (out / "foto.pgw").write_text("0.05\n0\n0\n-0.05\n995.025\n1999.975\n")
    _, met, orto = procesar(Opciones(puntos=str(pts), salida=str(out / "salida"), orto=str(out / "foto.png"), calce_auto=False,
                                    laminas=laminas.ConfLaminas(vista_pdf=False)),
                            avisar=lambda *a: None)
    ok = orto is not None and len(met.areas) == 1 and (out / "salida" / "metrado.xlsx").exists() and (out / "salida" / "resultado.dxf").exists()
    if ok:  # la plantilla PETRO viaja dentro del .exe: capas, carteles y lamina con membrete
        import ezdxf

        doc = ezdxf.readfile(out / "salida" / "resultado.dxf")
        ok = "LETRERO" in doc.layers and "D-01" in doc.layouts.names()
    (out / ("PRUEBA_OK.txt" if ok else "PRUEBA_FALLO.txt")).write_text(f"areas={len(met.areas)}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--prueba":
        sys.exit(prueba(sys.argv[2]))
    from ortofoto.gui import main

    main()
