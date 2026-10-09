import numpy as np
from PIL import Image

from ortofoto import areas, calce, exportar, unir
from ortofoto.__main__ import CODIGOS_DEFECTO, Opciones, procesar
from ortofoto.imagen import Ortofoto, afin_desde_dxf
from ortofoto.topografia import Punto
from shapely.geometry import Point

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


def test_world_file_ida_y_vuelta(tmp_path):
    orto = Ortofoto(np.full((60, 80, 3), 128, np.uint8), AFIN)
    orto.guardar(tmp_path / "f.png")
    assert np.allclose(Ortofoto.cargar(tmp_path / "f.png").afin, AFIN, atol=1e-6)


def test_carga_por_ventana_resolucion_y_tamano_distinto(tmp_path):
    # Foto exportada a la mitad de tamano: el calce del DXF (hecho sobre el original) se reescala
    img = np.zeros((200, 400, 3), np.uint8)
    img[100:, 200:] = 255
    Image.fromarray(img).save(tmp_path / "f.png")
    afin_original = [0.025, 0, 1000.0, 0, -0.025, 2000.0]  # original de 800x400 px
    o = Ortofoto.cargar(tmp_path / "f.png", afin=afin_original, tam_ref=(800, 400),
                        ventana=(1004.0, 1996.0, 1006.0, 1998.0), resolucion=0.1)
    assert abs(o.tam_pixel - 0.1) < 0.005  # redondeo a pixeles enteros
    assert o.rgb.shape[:2] == (20, 20)
    assert np.allclose(o.a_terreno(0, 0), (1004.0, 1998.0), atol=0.05)
    assert o.origen["tam"] == (400, 200) and np.allclose(o.origen["afin"][0], 0.05)


def test_imagen_en_dxf_ida_y_vuelta(tmp_path):
    img = np.full((60, 80, 3), 128, np.uint8)
    Image.fromarray(img).save(tmp_path / "foto.png")
    orto = Ortofoto.cargar(tmp_path / "foto.png", afin=AFIN)
    pts = [Punto("1", 550116, 9072958, 150, "VER"), Punto("2", 550117, 9072958, 150, "VER")]
    codigos, alias = unir.cargar_codigos(CODIGOS_DEFECTO)
    res, _ = unir.unir_todo(pts, codigos, None, alias=alias, avisar=lambda *a: None)
    met = areas.cerrar_areas(res)
    exportar.guardar_dxf(tmp_path / "a.dxf", pts, res, met, codigos, alias, orto)
    afin, nombre, tam = afin_desde_dxf(tmp_path / "a.dxf")
    assert nombre == "foto.png" and tam == (80, 60)
    assert np.allclose(afin, AFIN, atol=1e-6)


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
    confirmadas = [u for u in r.uniones if not u.revisar]
    cruzan = [u for u in confirmadas if abs(pts[u.i].n - pts[u.j].n) > 0.5]
    assert not cruzan and len(confirmadas) == len(pts) - 2


def _vereda_por_secciones(x0=0.0, y0=0.0, n=6, paso=8.0, ancho=2.0, cod="VER"):
    """Vereda levantada por secciones (fachada -> sardinel) a lo largo del eje X."""
    pts = []
    for k in range(n):
        x = x0 + k * paso
        pts += [Punto(f"{cod}{k}a", x, y0 - 0.1, 0, cod), Punto(f"{cod}{k}b", x, y0 - ancho, 0, cod)]
    return pts


def test_vereda_por_secciones_con_fachada():
    codigos, alias = unir.cargar_codigos(CODIGOS_DEFECTO)
    fachada = [Punto(f"f{k}", x, 0.0, 0, "CSH") for k, x in enumerate(np.arange(-2, 45, 6))]
    # Vereda enfrente (otra cuadra, a 9 m): no debe unirse con la primera
    pts = fachada + _vereda_por_secciones() + _vereda_por_secciones(y0=-9.0, cod="VER")
    res, _ = unir.unir_todo(pts, codigos, None, alias=alias, avisar=lambda *a: None)
    met = areas.cerrar_areas(res)
    veredas = [a for a in met.areas if a.codigo == "VER"]
    assert len(veredas) == 2
    for a in veredas:
        assert abs(a.area - 1.9 * 40) < 1  # 1.9 m x 40 m (borde interior a 0.1 m de la fachada)
        assert a.poligono.bounds[3] - a.poligono.bounds[1] < 2.5  # no se pega con la otra cuadra
    assert {a.etiqueta for a in veredas} == {"VD - 01", "VD - 02"}


def test_vereda_por_secciones_sin_referencia():
    codigos, alias = unir.cargar_codigos(CODIGOS_DEFECTO)
    pts = _vereda_por_secciones(n=5, paso=10)
    res, _ = unir.unir_todo(pts, codigos, None, alias=alias, avisar=lambda *a: None)
    met = areas.cerrar_areas(res)
    assert len(met.areas) == 1 and abs(met.areas[0].area - 1.9 * 40) < 3


def test_martillo_abierto_se_cierra_y_desactivar_codigo(tmp_path):
    codigos, alias = unir.cargar_codigos(CODIGOS_DEFECTO)
    mar = [Punto(str(i), x, y, 0, "MRTLLO") for i, (x, y) in enumerate([(0, 0), (0, 3), (3, 4), (6, 3), (6, 0)])]
    res, _ = unir.unir_todo(mar, codigos, None, alias=alias, avisar=lambda *a: None)
    met = areas.cerrar_areas(res)
    assert len(met.areas) == 1 and met.areas[0].etiqueta == "MT - 01" and met.areas[0].area > 15
    # Desactivado desde la ventana / linea de comandos: no se une ni genera areas
    with open(tmp_path / "p.csv", "w") as fh:
        for p in mar:
            fh.write(f"{p.num},{p.n},{p.e},{p.z},{p.desc}\n")
    _, met2, _ = procesar(Opciones(puntos=str(tmp_path / "p.csv"), salida=str(tmp_path / "s"),
                                   desactivados={"MAR"}), avisar=lambda *a: None)
    assert not met2.areas
    assert (tmp_path / "s" / "metrado.xlsx").exists() and (tmp_path / "s" / "resultado.dxf").exists()


def test_capas_de_puntos_por_codigo(tmp_path):
    import ezdxf

    pts = _vereda_por_secciones(n=3) + [Punto("t", 5, 5, 1, "TN")]
    _, met, _ = procesar(Opciones(puntos=_csv(tmp_path, pts), salida=str(tmp_path / "s"),
                                  capas_apagadas={"PT-TN"}), avisar=lambda *a: None)
    doc = ezdxf.readfile(tmp_path / "s" / "resultado.dxf")
    assert "PT-VER" in doc.layers and "PT-TN" in doc.layers
    assert doc.layers.get("PT-TN").is_off() and not doc.layers.get("PT-VER").is_off()
    assert len(doc.modelspace().query('HATCH[layer=="Vereda a demoler"]')) == len(met.areas) == 1


def _csv(tmp_path, pts):
    ruta = tmp_path / "pts.csv"
    with open(ruta, "w") as fh:
        for p in pts:
            fh.write(f"{p.num},{p.n},{p.e},{p.z},{p.desc}\n")
    return str(ruta)


def _plano_base(tmp_path):
    """Dos manzanas (FACHADA cerrada) separadas por una calle de 8 m, con lotes dentro."""
    import ezdxf

    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (40, 0), (40, 30), (0, 30)], close=True, dxfattribs={"layer": "FACHADA"})
    msp.add_lwpolyline([(0, -38), (40, -38), (40, -8), (0, -8)], close=True, dxfattribs={"layer": "FACHADA"})
    for x in range(5, 40, 5):
        msp.add_lwpolyline([(x, 0), (x, 30)], dxfattribs={"layer": "lotes"})
    ruta = tmp_path / "base.dxf"
    doc.saveas(ruta)
    return str(ruta)


def test_veredas_pegadas_al_limite_y_sin_cruzar_la_calle(tmp_path):
    import ezdxf

    from ortofoto import base as basemod

    ruta_base = _plano_base(tmp_path)
    pts = []
    for k, x in enumerate(np.arange(2, 39, 6)):
        # Vereda de la manzana norte (fachada y=0): puntos a 0.2 m y 1.8 m de la fachada
        pts += [Punto(f"n{k}a", x, -0.2, 0, "VER"), Punto(f"n{k}b", x + 0.3, -1.8, 0, "VER")]
        # Vereda de la manzana sur (fachada y=-8): puntos a 0.2 m y 1.5 m
        pts += [Punto(f"s{k}a", x + 1, -7.8, 0, "VER"), Punto(f"s{k}b", x + 1.2, -6.5, 0, "VER")]
    _, met, _ = procesar(Opciones(puntos=_csv(tmp_path, pts), salida=str(tmp_path / "s"), plano_base=ruta_base),
                         avisar=lambda *a: None)
    base = basemod.leer_base(ruta_base)
    veredas = [a for a in met.areas if a.codigo == "VER"]
    assert len(veredas) == 2
    for a in veredas:
        # pegada a la fachada de su manzana y sin entrar a ninguna manzana
        assert min(l.distance(a.poligono) for l in base.limites) < 1e-6
        assert a.poligono.intersection(base.union_manzanas()).area < 1e-6
        # no cruza la calle: todo el area esta a menos de 2 m de una sola fachada
        ys = [y for _, y in a.poligono.exterior.coords]
        assert max(ys) - min(ys) < 2.2
    # El resultado conserva el plano original (lotes) y agrega las areas
    doc = ezdxf.readfile(tmp_path / "s" / "resultado.dxf")
    assert len(doc.modelspace().query('LWPOLYLINE[layer=="lotes"]')) == 7
    assert len(doc.modelspace().query('HATCH[layer=="Vereda a demoler"]')) == 2


def test_union_no_junta_manzanas_distintas(tmp_path):
    from ortofoto import base as basemod

    base = basemod.leer_base(_plano_base(tmp_path))
    codigos, alias = unir.cargar_codigos(CODIGOS_DEFECTO)
    # Bordes de sardinel enfrentados a 3 m, cada uno de una manzana distinta
    pts = [Punto(f"a{k}", x, -2.5, 0, "SAR") for k, x in enumerate(range(2, 30, 6))]
    pts += [Punto(f"b{k}", x + 3, -5.5, 0, "SAR") for k, x in enumerate(range(2, 30, 6))]
    res, _ = unir.unir_todo(pts, codigos, None, alias=alias, avisar=lambda *a: None, base=base)
    r = [r for r in res if r.codigo == "SAR"][0]
    assert r.uniones and all(abs(r.puntos[u.i].n - r.puntos[u.j].n) < 0.1 for u in r.uniones)


def test_archivo_abierto_se_guarda_con_otro_nombre(tmp_path, monkeypatch):
    from ortofoto import __main__ as m

    bloqueado = tmp_path / "resultado.dxf"
    bloqueado.write_text("abierto en AutoCAD")
    real_open = open

    def open_falso(ruta, *a, **k):
        if str(ruta) == str(bloqueado):
            raise PermissionError(13, "Permission denied")
        return real_open(ruta, *a, **k)

    monkeypatch.setattr("builtins.open", open_falso)
    avisos = []
    assert m.ruta_libre(bloqueado, avisos.append) == tmp_path / "resultado_2.dxf"
    assert avisos and "resultado_2.dxf" in avisos[0]


def test_vereda_con_la_forma_de_la_foto(tmp_path):
    """La foto muestra una vereda que se angosta; los puntos (cada 8 m) no lo ven. Con la foto, la forma sigue lo real."""
    import ezdxf
    from PIL import ImageDraw
    from shapely.geometry import Polygon as P

    from ortofoto import base as basemod

    ruta_base = _plano_base(tmp_path)
    gsd = 0.05
    x0, y0, x1, y1 = -5.0, -12.0, 45.0, 5.0
    w, h = int((x1 - x0) / gsd), int((y1 - y0) / gsd)
    rng = np.random.default_rng(1)
    img = Image.new("RGB", (w, h), (150, 120, 90))  # tierra
    dr = ImageDraw.Draw(img)
    px = lambda pts: [((x - x0) / gsd, (y1 - y) / gsd) for x, y in pts]
    dr.polygon(px([(0, 0), (40, 0), (40, 5), (0, 5)]), fill=(140, 60, 50))  # techos
    # Vereda real: 2 m de ancho, pero entre x=14 y x=22 solo 0.8 m (tramo angosto)
    real = P([(0, 0), (14, 0), (14, 0), (22, 0), (40, 0), (40, -2), (22, -2), (22, -0.8), (14, -0.8), (14, -2), (0, -2)])
    dr.polygon(px(list(real.exterior.coords)), fill=(195, 192, 185))
    arr = np.asarray(img).astype(float) + rng.normal(0, 5, (h, w, 3))
    Image.fromarray(arr.clip(0, 255).astype(np.uint8)).save(tmp_path / "foto.png")
    (tmp_path / "foto.pgw").write_text(f"{gsd}\n0\n0\n{-gsd}\n{x0 + gsd / 2}\n{y1 - gsd / 2}\n")
    pts = []
    for k, x in enumerate(np.arange(2, 39, 8)):
        pts += [Punto(f"v{k}a", x, -0.2, 0, "VER"), Punto(f"v{k}b", x, -1.95, 0, "VER")]
    op = dict(puntos=_csv(tmp_path, pts), plano_base=ruta_base, orto=str(tmp_path / "foto.png"), calce_auto=False)
    _, met_p, _ = procesar(Opciones(salida=str(tmp_path / "p"), **op), avisar=lambda *a: None)
    _, met_f, _ = procesar(Opciones(salida=str(tmp_path / "f"), veredas_foto=True, **op), avisar=lambda *a: None)
    vp = unary([a.poligono for a in met_p.areas if a.codigo == "VER"])
    vf = unary([a.poligono for a in met_f.areas if a.codigo == "VER"])
    iou = lambda a, b: a.intersection(b).area / a.union(b).area
    from shapely.geometry import box

    tramo = box(2, -3, 34, 1)  # solo donde hay puntos levantados
    real, vf, vp = real.intersection(tramo), vf.intersection(tramo), vp.intersection(tramo)
    assert iou(vf, real) > 0.85
    assert iou(vf, real) > iou(vp, real) + 0.05  # la foto mejora la forma


def unary(pols):
    from shapely.ops import unary_union

    return unary_union(pols)


def test_puntos_visibles_en_el_dxf(tmp_path):
    import ezdxf

    pts = _vereda_por_secciones(n=3)
    procesar(Opciones(puntos=_csv(tmp_path, pts), salida=str(tmp_path / "s")), avisar=lambda *a: None)
    doc = ezdxf.readfile(tmp_path / "s" / "resultado.dxf")
    assert doc.header["$PDMODE"] == 34 and doc.header["$PDSIZE"] == 0.25
    assert len(doc.modelspace().query('POINT[layer=="PT-VER"]')) == len(pts)


def test_concreto_de_la_foto_coherente_con_los_puntos():
    from shapely.geometry import box

    codigos, _ = unir.cargar_codigos(CODIGOS_DEFECTO)
    met = areas.Metrado()
    losa = box(0, 0, 10, 3)  # lo que se ve en la foto
    sin_respaldo = box(20, 0, 26, 3)
    # Puntos levantados en el borde de la losa (uno 0.2 m afuera: el borde debe pasar por el)
    pts = [(2, 0.05), (5, -0.2), (8, 0.0), (10.1, 1.5), (4, 3.0)]
    areas.agregar_concreto_visible(met, [losa, sin_respaldo], codigos["CV"], pts)
    assert len(met.areas) == 1 and len(met.sin_puntos) == 1
    borde = met.areas[0].poligono.exterior
    assert all(borde.distance(Point(p)) < 1e-6 for p in pts)
    assert met.areas[0].etiqueta == "CO - 01"


def test_vereda_se_corta_donde_la_foto_muestra_tierra():
    from shapely.geometry import box

    from ortofoto.concreto import cortar_por_foto

    gsd = 0.05
    img = np.full((60, 600, 3), (190, 188, 182), np.uint8)  # concreto 30 m x 3 m
    img[:, 260:340] = (176, 146, 102)  # 4 m de tierra beige atravesando la vereda
    img[:, 100:140] = (60, 55, 50)  # sombra de alero: NO debe cortar
    orto = Ortofoto(img, [gsd, 0, 0, 0, -gsd, 3.0])
    piezas, quitado = cortar_por_foto(orto, box(0, 0, 30, 3))
    assert len(piezas) == 2 and 10 < quitado < 14
    assert all(p.bounds[1] < 0.01 and p.bounds[3] > 2.99 for p in piezas)  # cada pedazo cerrado de lado a lado


def test_vegetacion_en_sombra_corta_la_vereda():
    from shapely.geometry import box

    from ortofoto.concreto import cortar_por_foto

    img = np.full((60, 600, 3), (190, 188, 182), np.uint8)  # concreto 30 m x 3 m
    img[:, 200:400] = (45, 70, 35)  # 10 m de plantas en sombra (oscuras pero verdes)
    img[:, 60:100] = (55, 52, 50)  # sombra gris de alero: no corta
    piezas, quitado = cortar_por_foto(Ortofoto(img, [0.05, 0, 0, 0, -0.05, 3.0]), box(0, 0, 30, 3))
    assert len(piezas) == 2 and 27 < quitado < 33
