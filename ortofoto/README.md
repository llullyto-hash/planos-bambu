# WambriDemoliciones

## Topografía (+ ortofoto) → polilíneas, áreas con achurado y metrado

Lee los puntos topográficos y, si la tiene, la ortofoto. Con eso:

1. **Pone los puntos en capas separadas por código** (`PT-VER`, `PT-CNTA`, `PT-TN`…),
   para que pueda apagar las que no necesita y unir a mano sin confundirse.
2. **Une los puntos de cada código** en polilíneas (bordes de vereda, fachadas, lotes…).
3. **Cierra las áreas** de veredas, cunetas, pistas, martillos y accesos, con su achurado
   y su cartel como en el plano PETRO (recuadro, flecha, `VD - 01 / AREA= 54.24 M2 / PERIM= 31.20 M`),
   con las capas y estilos de texto de PETRO.
4. **Dibuja las líneas de corte (CL)** donde la vereda toca el límite de propiedad.
5. **Divide en láminas A1** con el membrete de PETRO, leyenda, plano clave y cuadro de metrados.
6. **Calcula el metrado** (`metrado.xlsx`: resumen, detalle por área con perímetro, y por lámina).

La ortofoto se lee **en su PC**: no importa que pese varios GB.

## Instalación en Windows (una sola vez)

1. Instale **Python 3.12** desde <https://www.python.org/downloads/> y, en el instalador,
   marque **"Add python.exe to PATH"**.
2. Descargue esta carpeta y haga doble clic en **`INSTALAR.bat`** (necesita internet, unos minutos).
3. Para usarlo: doble clic en **`ABRIR_PROGRAMA.bat`**.

## Uso (ventana)

**1. Archivos**
- **Puntos:** el CSV/TXT exportado de Civil 3D (*Points → Export Points → PNEZD comma delimited*).
- **Ortofoto (opcional):** TIF/JPG. Para el calce elija una opción:
  - la foto ya tiene coordenadas (GeoTIFF o `.tfw`/`.jgw`);
  - **tomarlo del plano de Civil 3D donde la foto está insertada** (el DXF): sirve aunque la foto se haya exportado a otro tamaño;
  - puntos de control (CSV: columna, fila, este, norte).
- **Afinar el calce automáticamente:** mueve la foto unos centímetros hasta que los puntos de borde
  caigan sobre los bordes de la foto (solo la mueve si la mejora es clara).
- **Resolución de trabajo:** 0 = la de la foto. Con poca memoria use 6–8 cm.
- **Plantilla de capas (opcional):** un DXF del cual copiar colores, tipos de línea y grosores.
- **Plano del proyecto (recomendado):** el DXF de Civil 3D con los lotes y las fachadas
  (se llena solo con el mismo DXF del calce). Con él:
  - el borde interior de cada vereda es la línea de **FACHADA** (límite de propiedad);
  - ningún área entra a los lotes y ninguna unión cruza un límite;
  - cada punto pertenece a la manzana de la fachada más cercana: nunca se une con la vereda de la otra cuadra;
  - `resultado.dxf` es una **copia de su plano** con todo lo original (lotes, fachadas, foto) más las capas nuevas.
  - En *Capas del límite de propiedad* indique qué capas son el límite (por defecto `FACHADA`).

**2. Códigos y capas**

Aquí se ven todos los códigos encontrados en los puntos y cuántos hay de cada uno.
- **Usar:** clic para activar o desactivar un código. Los desactivados no se unen ni generan áreas
  (sirve, por ejemplo, para que una pista no se superponga con una vereda).
- **Apagar en DXF:** clic para que sus capas salgan apagadas en el plano.
- Doble clic para editar: elemento, **tipo**, capas, prefijo del metrado, **separación máxima**
  entre puntos, **ancho mínimo/máximo** de la franja y **referencia** (códigos de la fachada o el lote).
- Los códigos en amarillo no están configurados: doble clic para configurarlos.
- **Guardar configuración como…** guarda todo en un `.json` para el próximo proyecto.

Tipos:

| Tipo | Para qué | Resultado |
|---|---|---|
| `franja` | vereda, cuneta, pista (dos bordes) | área cerrada + achurado + etiqueta (m²) |
| `contorno` | martillo, acceso (un borde que se cierra) | área cerrada + achurado + etiqueta (m²) |
| `linea` | fachada, lote, sardinel | polilínea (m si tiene prefijo) |
| `punto` | árboles, cajas, postes, terreno | solo puntos en su capa |

**5. Revisar y corregir (antes de exportar)**
- Los límites de propiedad (FACHADA) se ven en magenta; los vértices se pegan a los puntos y, si no hay
  punto cerca, al límite (a su esquina si está cerca). Un rombo verde marca el vértice que ya llegó al
  límite y un círculo verde aparece mientras se arrastra sobre él.
- **Exportar para la web**: guarda `proyecto_web.json` para la página colaborativa (revisión en línea
  entre varias personas). **Importar correcciones**: carga el `correcciones_web.json` que se baja de la
  página; luego EXPORTAR DXF Y METRADO. Ver `ESTADO_DEL_PROYECTO.md`, sección 8.

**3. Láminas y membrete**
- Tipo de cartel (PETRO o texto suelto como antes), líneas de corte, escala (1:500 por defecto).
- Láminas: norte arriba o giradas según las calles, traslape, prefijo (`D-`) y primer número,
  numerar las áreas lámina por lámina, PDF de vista previa.
- Datos del membrete (proyecto, CUI, entidad, ubicación, plano, fecha, profesional).
  **Guardar como predeterminado** los recuerda para la próxima vez.

**4. Procesar** → en la carpeta de resultados quedan:
- `resultado.dxf`: puntos por capa, bordes, áreas con achurado, etiquetas y la ortofoto de fondo
  (se enlaza la foto original, no se copia);
- `metrado.xlsx` / `metrado.csv`;
- `vista.png`: vista rápida;
- `laminas_vista_previa.pdf`: las láminas como saldrían al plotear;
- `revision_carteles.csv`: cada cartel comparado con su área;
- `resumen.md`: avisos, reglas aplicadas, carteles encimados y códigos que parecen mal escritos.

## Cómo decide qué unir (para que no se pegue a otro tramo)

- **Separación máxima por código:** dos puntos más lejos que eso nunca se unen.
- **Ancho mínimo y máximo:** una vereda solo se cierra entre bordes que estén a esa distancia.
- **Fachada como referencia:** cada punto de vereda se asigna a la fachada más cercana, así una
  vereda nunca se une con la de la otra cuadra.
- **Sin cruces:** ninguna unión puede cruzar otra ya hecha (de cualquier código).
- **Sin superposiciones:** cada área nueva se recorta contra las ya aceptadas.
- **Con foto:** primero se unen los tramos que la foto confirma (hay un borde a lo largo). Lo que la foto
  no confirma (sombra, árbol) se une igual pero queda en la capa `REVISAR UNION`. Si no quiere eso,
  desmarque la opción en *Archivos*.
- **Veredas rectangulares, por caras de la fachada:** la fachada se parte en caras rectas (cada lado
  de la casa, cada ochave). Cada punto VER se mide perpendicular a la cara que tiene enfrente; el
  borde exterior va paralelo a esa cara al ancho del punto más alejado de cada sección.
  - Cada sección cubre de su primer a su último punto; el ancho mayor no se estira hacia una vecina
    más angosta (salvo donde la foto muestra concreto: el borde de una losa sin punto). Los huecos
    entre secciones los rellena el ancho menor. Escalones rectos; cierre en escuadra en los extremos.
  - En una esquina u ochave la vereda dobla solo si hay puntos en las dos caras; cada cara conserva
    su ancho y la esquina exterior pasa por el punto de esquina.
  - Frente a un lote vacío (sin CSH y con pasto o tierra en la foto) no se rellena.
  - Un hueco de más de `hueco_max` m sin puntos se une (hasta 30 m) solo si los dos lados tienen el
    mismo ancho y la foto no ve suelo; queda en `REVISAR AREA`. Un punto suelto sale de 2 m, a revisar.
  - Si los CSH (fachada levantada) quedan detrás de la FACHADA del plano, la vereda llega hasta la
    fachada real.
  - Los canales y cunetas tienen prioridad: la vereda no los pisa.
- **Mandan los puntos:** árboles, palmeras, aleros, sombra o polvo sobre el concreto no cortan la vereda.
  Solo se excluye un punto en un caso claro de jardín: vegetación a la vista entre los puntos **y** un
  desnivel brusco respecto del punto anterior (queda marcado en `REVISAR PUNTO VS FOTO`).
- **Fachada lejana:** si el límite del plano está a más del ancho máximo (p.ej. dibujado bajo el techo),
  la vereda se cierra contra la fachada levantada en campo (CSH/LP).

**Revisar y corregir antes de exportar (pestaña 4. Resultados):** con la casilla *Revisar y corregir en
pantalla antes de exportar* (marcada por defecto), al procesar no se escribe nada: se abre el mapa con
la ortofoto, las áreas y los puntos, y la lista de áreas con su metrado.

| Acción | Cómo |
|---|---|
| Zoom / mover la vista | rueda del mouse / arrastrar con el botón derecho; *Ver todo* |
| Ir a un área | clic en la lista (las marcadas a revisar salen en rojo; filtro *solo a revisar*) |
| Mover un vértice | seleccionar el área y arrastrar el vértice (se pega a los puntos topográficos) |
| Agregar / quitar vértice | doble clic sobre un borde / Shift + clic sobre el vértice |
| Cortar un tramo | *Cortar tramo*: dos clics a través del área; luego clic en el pedazo que sobra y *Borrar* |
| Dibujar un área que no salió | elegir el código, *Dibujar área*, clic en cada esquina, doble clic o Enter |
| Borrar / deshacer | Supr / Ctrl+Z |
| Dar por revisada | *Revisado* |

Al final, **EXPORTAR DXF Y METRADO** escribe el DXF, el Excel y el resumen con las correcciones.

**Enviar la ortofoto a revisar:** marque *Exportar la ortofoto en cuadros de 100 m* en la pestaña
*Archivos*. El programa guarda en `muestras_ortofoto/` la foto (ya calzada) en cuadros de 100 m a 8 cm
por píxel, solo donde hay puntos de veredas, canales o fachadas, cada uno con su `.jgw`, en archivos
`muestras_01.zip`, `muestras_02.zip`, … de hasta 20 MB. Envíe esos ZIP.

Capas para revisar a mano:

| Capa | Qué tiene |
|---|---|
| `REVISAR UNION` | uniones que la foto no confirmó |
| `REVISAR AREA` | áreas con forma corregida o ancho muy variable |
| `REVISAR BORDE SIN CERRAR` | bordes de vereda/cuneta que no encontraron su pareja: cerrarlos a mano |

Las veredas se arman de estas formas, en este orden:
0. **Contra el límite de propiedad del plano base** (si lo eligió): fachada → punto VER más alejado (sardinel).
1. **Por secciones con referencia:** puntos levantados de la fachada al sardinel, cada cierta distancia (Bambú).
2. **Por secciones sin referencia:** pares de puntos que cruzan la vereda, sin fachada cerca (PETRO).
3. **Borde por borde:** puntos que siguen cada borde de forma continua.

## Línea de comandos

```
python -m ortofoto --puntos CVS.txt --orto "ORTF BAMBU.tif" --calce-dxf "PLANO TOP.dxf" -o salida/
python -m ortofoto --puntos CVS.txt -o salida/ --desactivar PTA --apagar PT-TN
python -m ortofoto --puntos CVS.txt --plano-base "PLANO TOP.dxf" -o salida/ --laminas --orientacion auto --membrete datos.json
python -m ortofoto.gui
```

## Pruebas

- `python -m pytest tests`
- Ortofoto sintética a partir del plano PETRO (sin foto real):
  `python -m ortofoto.prueba.sintetica` y `python -m ortofoto.prueba.evaluar`.
- Con una foto de prueba del mismo tamaño que la de Bambú (25440×21696 px, 4 cm) y los 9,659 puntos:
  unos 4 minutos y 3.4 GB de memoria como máximo.
