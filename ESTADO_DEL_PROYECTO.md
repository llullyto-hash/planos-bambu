# Estado del proyecto: plano de demoliciones desde topografía + ortofoto

Versión publicada: **1.0.17** (instalador en GitHub → Releases → `instalador-v1.0.17`).
Repositorio: `llullyto-hash/planos-bambu`, rama `claude/demolition-plans-automation-h0etwe`.

Este archivo resume todo lo necesario para retomar el trabajo (con Claude u otra persona) sin perder
lo acordado. Léalo junto con `README.md` y `ortofoto/README.md`.

---

## 1. Qué hace el programa

Entrada: puntos topográficos (CSV PNEZD exportado de Civil 3D), plano del proyecto (DXF con la capa
FACHADA), ortofoto (TIF/JPG, calce tomado del DXF donde está insertada).

Salida (sobre una copia del plano del proyecto):
- Áreas a demoler con achurado y etiqueta tipo PETRO (`VD - 01 / AREA= x M2`, canales con `LONG=`).
- Puntos en capas propias `PT-<código>` (para apagarlos y corregir a mano).
- Capas de revisión: `REVISAR AREA`, `REVISAR PUNTO VS FOTO`, `REVISAR UNION`, `REVISAR BORDE SIN CERRAR`.
- `metrado.xlsx` / `metrado.csv`, `resumen.md`, `vista.png`.

Flujo en la ventana: **1. Archivos → 2. Códigos y capas → 3. Procesar → 4. Resultados** (revisar y
corregir sobre la foto; nada se escribe hasta **EXPORTAR DXF Y METRADO**).

## 2. Cómo ejecutarlo

- Usuario final: instalar `Instalar_TopografiaMetrados.exe` (no necesita Python).
- Desde el código (Windows): `INSTALAR.bat` una vez, luego `ABRIR_PROGRAMA.bat`.
- Desde el código (cualquier sistema, Python 3.10+):
  ```
  pip install -r requirements.txt
  python -m ortofoto.gui            # ventana
  python -m ortofoto --help         # línea de comandos
  python -m pytest -q tests         # 28 pruebas automáticas (deben pasar todas)
  ```
- Instalador: cada `git push` a la rama dispara `.github/workflows/instalador-windows.yml`
  (pruebas → PyInstaller → prueba del .exe → Inno Setup → Release `instalador-v1.0.N`).

## 3. Mapa del código

| Archivo | Qué hace |
|---|---|
| `ortofoto/__main__.py` | `calcular()` (todo el proceso, sin escribir) y `exportar_calculo()`; `procesar()` = ambos; línea de comandos; `exportar_muestras()` (foto en cuadros ZIP) |
| `ortofoto/gui.py` | Ventana (pestañas 1–3) |
| `ortofoto/visor.py` | Pestaña 4: mapa con la foto, lista de áreas, corrección por tramos |
| `ortofoto/veredas.py` | **Veredas pegadas a la fachada, por caras** (la parte más ajustada) |
| `ortofoto/areas.py` | Cierre de áreas (canales, cunetas, contornos), regla de jardín, metrado, numeración |
| `ortofoto/unir.py` | Configuración de códigos y unión de puntos en polilíneas |
| `ortofoto/codigos.json` | Códigos de campo → capa, tipo, anchos, achurado, prefijo (VD, CAN D, …) y alias |
| `ortofoto/concreto.py` | Lectura de la foto: pasto, tierra, concreto, sombra (`fracciones_suelo`) |
| `ortofoto/base.py` | Lee el plano del proyecto (FACHADA → límites y manzanas) |
| `ortofoto/imagen.py`, `calce.py` | Carga de ortofotos grandes por ventanas; calce |
| `ortofoto/exportar.py` | DXF (capas, achurados, etiquetas) y vista PNG |
| `tests/test_ortofoto.py` | Pruebas de cada criterio (ver sección 4) |

## 4. Criterios acordados con el usuario (no cambiarlos sin consultar)

Veredas (`veredas.py`):
1. **Forma rectangular**: la fachada se parte en caras rectas (cada lado de la casa, cada ochave).
   Cada punto VER se mide **perpendicular a la cara** que tiene enfrente. El borde exterior va
   **paralelo a la fachada** al ancho del punto más alejado de cada sección; nunca en diagonal de
   punto a punto, sin zigzag, sin puntas, sin vacíos.
2. **Escalones rectos en el punto donde cambia el ancho**. El ancho mayor no se estira hacia una
   vecina más angosta (salvo donde la foto ve concreto: borde de una losa sin punto). Los huecos
   entre secciones los rellena el ancho menor.
3. **Extremos en escuadra** en el primer y último punto. En una **esquina** la vereda dobla solo si hay
   puntos en las dos caras; la esquina exterior pasa por el punto de esquina; en quiebres abiertos
   con anchos distintos se cierra con el ancho menor (sin puntas).
4. **Mandan los puntos VER**: árboles, palmeras, aleros, sombra o polvo **no** cortan la vereda.
5. **Bajo los techos sí se demuele**: la vereda llega hasta la FACHADA del plano aunque esté bajo el alero.
6. Si los **CSH quedan detrás de la FACHADA del plano** (fachada dibujada hacia la calle), la vereda
   llega hasta la fachada real (CSH).
7. Si la FACHADA del plano está más lejos que el ancho máximo, se cierra contra la fachada levantada (CSH/LP).
8. **Jardín**: un punto VER de afuera se excluye solo si entre él y el anterior la foto ve vegetación
   (≥60 %) **y** hay un desnivel brusco (>0.30 m, pendiente >25 %). Queda en `REVISAR PUNTO VS FOTO`.
9. **Lote vacío**: un hueco o tramo sin CSH dentro, con maleza/tierra y casi sin concreto en la foto,
   no es vereda (solo si en esa manzana se levantaron fachadas).
10. Hueco largo sin puntos (hasta 30 m) se une solo si los dos lados tienen el mismo ancho y la foto no
    ve suelo; queda a revisar. Un punto suelto sale como pedazo de 2 m, a revisar.
11. **Canales y cunetas tienen prioridad**: la vereda no los pisa. Nunca cruzar límites de lote.

Canal (ALC): cajas por sus esquinas, secciones, o por el eje con ancho supuesto 0.80 m; capa
`CANAL EXISTENTE A DEMOLER`, etiqueta con LONG y AREA (formato del plano del colega).

## 5. Pendientes conocidos

1. **Lote vacío 7888–7893 (Bambú)**: sigue saliendo vereda; el frente del lote es una cara corta de la
   FACHADA y la vereda llega por la unión de esquinas (la regla de lote vacío no revisa esa unión).
2. **Jardín 7480/7474**: la foto ve concreto en 7480→7473 y 7543→7542 y sombra en 7485→7488; falta
   que el usuario indique el borde real.
3. **Pasaje VD-203 (puntos 1083…)** y fachadas del plano con quiebres raros: formas torcidas.
4. Códigos sin configurar en Bambú: FD, MRTE, PM, LD, IE, LC, GA.
5. El modo "EN PRUEBA" (veredas con la forma de la foto) todavía recorta píxel por píxel: dejarlo
   desmarcado.

## 6. Cómo probar con datos reales

- Puntos de Bambú: `CVS.txt` (9,659 puntos PNEZD); plano: `1. PLANO TOP SECTOR BAMBU C3D.dxf`.
- Ortofoto: la original (`ORTF BAMBU.tif`, 4 cm) o los cuadros que genera la opción *Exportar la
  ortofoto en cuadros de 100 m* (`muestras_01.zip`, `muestras_02.zip`: 47 cuadros a 8 cm con `.jgw`).
  Para usar los cuadros como una sola foto, unirlos en un mosaico (cada `.jgw` da su posición).
- Zonas usadas para ajustar los criterios (números de punto): 7480/7474 (jardín), 7531/7536 (árbol),
  9303/9322 (palmera), 1107–1129 (palmeras), 5143–5147 (losa), 7179–7193 (zigzag), 7686 (punta),
  7719–7742 (fachada lejana), 7220–7229 (casas elevadas), 7576–7587 (fachada corrida), 7888–7893
  (lote vacío), 6380/6381 y OCHV 6346 (esquinas), 6398/6399 y 6112–6116 (escalones/losas),
  6514–6517 y VD-83 (final de vereda), 9442–9443/9427 (vereda junto al canal), 5519–5522 (hueco largo).

## 7. Para retomar con Claude (copiar y pegar)

> Estoy desarrollando un programa en Python para generar planos de demoliciones (veredas, canales)
> desde topografía + ortofoto + el plano DXF del proyecto. Te adjunto el código fuente. Lee primero
> `ESTADO_DEL_PROYECTO.md` (criterios acordados y pendientes), luego `ortofoto/README.md`. Respeta los
> criterios de la sección 4; corre `python -m pytest -q tests` antes y después de cada cambio. Quiero
> seguir con: [describir lo siguiente, p.ej. los pendientes de la sección 5].
