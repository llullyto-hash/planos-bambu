# Estado del proyecto WambriDemoliciones: plano de demoliciones desde topografía + ortofoto

Versión publicada: **WambriDemoliciones 1.1.N** (instalador en GitHub → Releases → `instalador-v1.1.N` más reciente; antes 1.0.19).
Repositorio: `llullyto-hash/planos-bambu`, rama `claude/demolition-plans-automation-h0etwe`.

Este archivo resume todo lo necesario para retomar el trabajo (con Claude u otra persona) sin perder
lo acordado. Léalo junto con `README.md` y `ortofoto/README.md`.

---

## 1. Qué hace el programa

Entrada: puntos topográficos (CSV PNEZD exportado de Civil 3D), plano del proyecto (DXF con la capa
FACHADA), ortofoto (TIF/JPG, calce tomado del DXF donde está insertada).

Salida (sobre una copia del plano del proyecto):
- Áreas a demoler con achurado y **cartel tipo PETRO**: recuadro, flecha y `VD - 01 / AREA= x M2 / PERIM= y M`
  (canales con `LONG=`). Capas, tipos de línea y estilos de texto copiados de PETRO.
- **Líneas de corte (CL)** donde la vereda toca el límite de propiedad.
- **Láminas A1** (layouts `D-01`, `D-02`…) con el marco y membrete de PETRO, leyenda, plano clave y cuadro de metrados.
- Puntos en capas propias `PT-<código>` (para apagarlos y corregir a mano).
- Capas de revisión: `REVISAR AREA`, `REVISAR PUNTO VS FOTO`, `REVISAR UNION`, `REVISAR BORDE SIN CERRAR`.
- `metrado.xlsx` / `metrado.csv` (con perímetro, lámina y reglas aplicadas; hoja *Por lamina*), `resumen.md`,
  `vista.png`, `laminas_vista_previa.pdf`, `revision_carteles.csv`.

Flujo en la ventana: **1. Archivos → 2. Códigos y capas → 3. Láminas y membrete → 4. Procesar →
5. Revisar y corregir** (sobre la foto; nada se escribe hasta **EXPORTAR DXF Y METRADO**). Pestaña
*Herramientas*: revisar un plano DXF ya dibujado.

## 2. Cómo ejecutarlo

- Usuario final: instalar `Instalar_WambriDemoliciones.exe` (no necesita Python).
- Desde el código (Windows): `INSTALAR.bat` una vez, luego `ABRIR_PROGRAMA.bat`.
- Desde el código (cualquier sistema, Python 3.10+):
  ```
  pip install -r requirements.txt
  python -m ortofoto.gui            # ventana
  python -m ortofoto --help         # línea de comandos
  python -m pytest -q tests         # 35 pruebas automáticas (deben pasar todas)
  ```
- Instalador: cada `git push` a la rama dispara `.github/workflows/instalador-windows.yml`
  (pruebas → PyInstaller → prueba del .exe → Inno Setup → Release `instalador-v1.1.N`).

## 3. Mapa del código

| Archivo | Qué hace |
|---|---|
| `ortofoto/__main__.py` | `calcular()` (todo el proceso, sin escribir) y `exportar_calculo()`; `procesar()` = ambos; línea de comandos; `exportar_muestras()` (foto en cuadros ZIP) |
| `ortofoto/gui.py` | Ventana (pestañas 1–4 y Herramientas, ayudas y guía rápida) |
| `ortofoto/visor.py` | Pestaña 5: mapa con la foto, límites de propiedad, lista de áreas, corrección por tramos |
| `ortofoto/colaborativo.py` | `proyecto_web.json` (para la página colaborativa) y lectura de `correcciones_web.json` |
| `web/revision_colaborativa.html` | Copia de la página colaborativa publicada en claude.ai (ver sección 8) |
| `ortofoto/veredas.py` | **Veredas pegadas a la fachada, por caras** (la parte más ajustada) |
| `ortofoto/areas.py` | Cierre de áreas (canales, cunetas, contornos), regla de jardín, metrado, numeración |
| `ortofoto/unir.py` | Configuración de códigos y unión de puntos en polilíneas |
| `ortofoto/codigos.json` | Códigos de campo → capa, tipo, anchos, achurado, prefijo (VD, CAN D, …) y alias |
| `ortofoto/concreto.py` | Lectura de la foto: pasto, tierra, concreto, sombra (`fracciones_suelo`) |
| `ortofoto/base.py` | Lee el plano del proyecto (FACHADA → límites y manzanas) |
| `ortofoto/imagen.py`, `calce.py` | Carga de ortofotos grandes por ventanas; calce |
| `ortofoto/exportar.py` | DXF (capas, achurados, carteles, CL, láminas) y vista PNG |
| `ortofoto/estilo.py` | Capas y estilos de texto desde la plantilla (`plantilla_petro.dxf`) |
| `ortofoto/carteles.py` | Carteles tipo PETRO y su ubicación sin encimarse |
| `ortofoto/laminas.py` | División en láminas, membrete, leyenda, plano clave, cuadro, PDF de vista previa |
| `ortofoto/revisar_plano.py` | Revisión de un plano DXF (etiquetas contra el dibujo); `demoliciones/analizar_plano.py` lo llama |
| `herramientas/crear_plantilla.py` | Regenera `ortofoto/plantilla_petro.dxf` desde el plano PETRO |
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

1. **Lote vacío 7888–7893 (Bambú)**: la unión de esquinas ahora revisa la regla de lote vacío (1.1);
   falta probarlo con el plano y la ortofoto de Bambú.
2. **Jardín 7480/7474**: la foto ve concreto en 7480→7473 y 7543→7542 y sombra en 7485→7488; falta
   que el usuario indique el borde real.
3. **Pasaje VD-203 (puntos 1083…)** y fachadas del plano con quiebres raros: formas torcidas.
4. Códigos sin configurar en Bambú: FD, MRTE, PM, LD, IE, LC, GA (falta que el usuario diga qué son).
6. Carteles encimados en zonas muy densas (Bambú sin plano base: 26 de ~800): quedan en la capa
   `REVISAR CARTEL ENCIMADO` (no se plotea) para moverlos a mano.
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

## 8. Página colaborativa (revisión en línea, hasta 4 personas)

Página publicada en claude.ai (privada; el dueño la comparte desde su menú *Compartir*):
https://claude.ai/artifact/JE4cjrT7tKMN1zgjYr7Ap1 — fuente en `web/revision_colaborativa.html`.

Flujo:
1. Programa → Procesar → pestaña 4 → **Exportar para la web** → `proyecto_web.json`
   (áreas, puntos, límites de propiedad, códigos). Con *Exportar la ortofoto en cuadros* salen los ZIP de foto.
2. Página → pestaña Proyecto → **Cargar proyecto…** (solo el dueño): `proyecto_web.json` + los ZIP.
3. Cada persona entra con su cuenta de Claude. El dueño dibuja **zonas** y las asigna; todos pueden
   corregir todo (mover/agregar/quitar vértices, cortar, dibujar, borrar, revisado, deshacer). Los
   cambios se guardan solos y se ven en vivo, con el área y el metrado recalculados al instante.
4. **Descargar correcciones_web.json** → en el programa, pestaña 4 → **Importar correcciones** →
   EXPORTAR DXF Y METRADO.

Datos de la página (base de datos de la página): `proyecto/info` (nombre, foto en cuadros, puntos y límites
como archivo), áreas en colecciones `<pref><k>` (una por cada 800) y `<pref>x` (las nuevas), `zonas/*`,
`personas/*`. Reglas: solo el dueño escribe `proyecto`, `zonas` y `personas` (cada uno escribe su propia
ficha en `personas`); las áreas las escribe cualquier invitado con permiso de edición. Invitados de fuera
de la organización: invitarlos por correo como **Editor** y sin enlace público.

## 9. Mejoras 1.1 (octubre 2026)

Todo lo anterior sigue igual; lo nuevo se puede apagar y entonces el resultado es el de antes.

| Mejora | Dónde | Cómo apagarla |
|---|---|---|
| Capas, tipos de línea y 34 estilos de texto de PETRO | `estilo.py`, `plantilla_petro.dxf` | elegir otra plantilla (manda ella) |
| Cartel PETRO: recuadro + flecha + AREA + PERIM, sin encimarse, hacia la calle | `carteles.py` | ventana 3 / `--cartel simple` |
| Líneas de corte CL sobre el límite de propiedad (o CSH/LP sin plano base) | `areas.cortes_lineales` | ventana 3 / `--sin-corte-lineal` |
| Láminas A1 con membrete, leyenda, plano clave, cuadro, "VER LÁMINA", PDF | `laminas.py` | ventana 3 / sin `--laminas` |
| Membrete: llenarlo en la ventana, escudo/logo propio, guardar/abrir por proyecto (.json) y **aplicarlo a un DXF ya generado** sin reprocesar (`laminas.actualizar_membrete`) | `laminas.py`, `gui.py` | — |
| Numeración por lámina (VD-1… siguen el orden de las láminas) | `laminas.dividir` | ventana 3 |
| Metrado con perímetro, lámina, reglas aplicadas y hoja *Por lamina* (columnas nuevas al final) | `areas.guardar_metrado` | — |
| Verificación: etiquetas repetidas, áreas que se tocan, cartel vs. área (`revision_carteles.csv`) | `__main__.verificar`, `revisar_plano.py` | ventana 4 |
| Sugerencia de alias para códigos mal escritos (VERD→VER, CHS→CSH) | `topografia.sugerir_alias` | — |
| VER1/VER2 como bordes distintos; códigos de control I/F/CLS | `unir.py`, `topografia.py` | apagados por defecto |
| Cada corrida en su subcarpeta con fecha y hora | `__main__.calcular` | apagado por defecto |
| Página colaborativa: perímetro y límites de lámina | `web/revision_colaborativa.html` | casilla "ver láminas" |
| Ventana didáctica: pasos, ayudas, guía, barra de estado, botones de resultados | `gui.py` | — |

Línea de comandos nueva: `--escala`, `--cartel`, `--sin-corte-lineal`, `--laminas`, `--orientacion norte|auto`,
`--traslape`, `--prefijo-lamina`, `--membrete datos.json`, `--sin-vista-pdf`, `--carpeta-por-corrida`,
`--numero-separa`, `--codigos-control`.

Programa, instalador y página colaborativa se llaman **WambriDemoliciones**. La página publicada (mismo enlace) ya tiene la versión 1.1.
