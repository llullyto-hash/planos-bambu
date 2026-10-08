import numpy as np

from ortofoto import calce, exportar, unir
from ortofoto.imagen import Ortofoto, afin_desde_dxf
from ortofoto.topografia import Punto

AFIN = [0.05, 0.0, 550115.0, 0.0, -0.05, 9072960.0]


def _pares(afin, pixeles):
    o = Ortofoto(np.zeros((10, 10, 3), np.uint8), afin)
    return [((c, f), o.a_terreno(c, f)) for c, f in pixeles]


def test_control_afin_y_helmert():
    pares = _pares(AFIN, [(0, 0), (6400, 0), (0, 6300), (3000, 2000)])
    afin, res = calce.afin_por_control(pares)
    assert np.allclose(afin, AFIN, atol=1e-6) and res.max() < 1e-6
    afin2, res2 = calce.afin_por_control(pares[:2])
    assert np.allclose(afin2, AFIN, atol=1e-6) and res2.max() < 1e-6


def test_imagen_en_dxf_ida_y_vuelta(tmp_path):
    orto = Ortofoto(np.full((60, 80, 3), 128, np.uint8), AFIN)
    pts = [Punto("1", 550116, 9072958, 150, "VER"), Punto("2", 550117, 9072958, 150, "VER")]
    codigos, alias = unir.cargar_codigos("ortofoto/codigos.json")
    res, _ = unir.unir_todo(pts, codigos, None, alias=alias)
    exportar.guardar_dxf(res, codigos, tmp_path / "a.dxf", orto, "foto.jpg")
    afin, nombre, tam = afin_desde_dxf(tmp_path / "a.dxf")
    assert nombre == "foto.jpg" and tam == (80, 60)
    assert np.allclose(afin, AFIN, atol=1e-6)


def test_world_file_ida_y_vuelta(tmp_path):
    orto = Ortofoto(np.full((60, 80, 3), 128, np.uint8), AFIN)
    orto.guardar(tmp_path / "f.png")
    assert np.allclose(Ortofoto.abrir(tmp_path / "f.png").afin, AFIN, atol=1e-6)


def test_union_sigue_borde_de_la_foto():
    # Vereda de 2 m de ancho: puntos en ambos bordes; la foto muestra los bordes.
    img = np.full((200, 400, 3), 140, np.uint8)
    img[80:120, :] = 210  # franja clara = vereda (filas 80-120 -> 2 m)
    orto = Ortofoto(img, [0.05, 0, 0, 0, -0.05, 10])
    n_sup, n_inf = 10 - 80 * 0.05, 10 - 120 * 0.05
    pts = [Punto(str(i), x, n_sup, 0, "VER") for i, x in enumerate(np.arange(1, 19, 2.5))]
    pts += [Punto(str(100 + i), x + 1.2, n_inf, 0, "VER") for i, x in enumerate(np.arange(1, 17, 2.5))]
    conf = unir.Codigo("VEREDA EXIS.", separacion_max=4)
    r = unir.unir_codigo("VER", pts, conf, orto)
    cruzan = [u for u in r.uniones if abs(pts[u.i].n - pts[u.j].n) > 0.5]
    assert not cruzan and len(r.cadenas) == 2
