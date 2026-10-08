# Zen Secciones — notas para seguir el desarrollo

Programa que compatibiliza las secciones transversales viales del Civil 3D con la planta general de diseño:
mide los anchos por progresiva desde las capas de la planta, toma la cota de rasante de las secciones del Civil,
dibuja la sección según la planta dentro del marco del Civil y exporta un DXF listo para el programa de cortes y rellenos.

## Archivos

| Carpeta | Archivo | Qué es |
|---|---|---|
| programa | ZenSecciones.html | Versión de escritorio completa (un solo HTML: estilos + JS + datos de ejemplo + licencia). Es la que va en el instalador. |
| instalador | Instalar.cmd, archivos/instalar.ps1, archivos/Desinstalar.cmd, LEEME.txt | Instalador Windows. Copia a %LOCALAPPDATA%\ZenSecciones, calcula el código de equipo y crea accesos directos que abren el HTML con `msedge --app=file:///...ZenSecciones.html#m=CODIGO --user-data-dir=...\perfil`. Para armar el .zip, copiar programa/ZenSecciones.html dentro de instalador/archivos/. |
| herramientas | ZenSecciones_GeneradorClaves.html | Generador de claves (solo para el dueño, NO distribuir). |
| herramientas | lic.js | SHA-256 + HMAC en JS puro y la función `zsClave(secreto, codigo)`. |
| web | plantilla_web.html | Misma app para la versión web (artifact de claude.ai). `__DATA__` se reemplaza por datos_ejemplo_contamana.json. Usa la capacidad `downloads` y JSZip por CDN. |
| web | version_web_publicada.html | La plantilla ya armada (lo que está publicado). |

La versión de escritorio se genera desde plantilla_web.html con estos cambios: título "Zen Secciones", sin JSZip (descarga .dxf directo con `<a download>`),
clave de localStorage `zen-proyecto`, y el bloque de licencia agregado al final del último `<script>`.

## Licencia

- Código de equipo (en instalar.ps1): SHA-256 de `'ZENSEC-' + MachineGuid` (HKLM\SOFTWARE\Microsoft\Cryptography), primeros 12 hex en mayúsculas, formato `XXXX-XXXX-XXXX`. Va en el hash de la URL (`#m=`).
- Clave: HMAC-SHA256(secreto, `'ZENSECCIONES|' + codigo_sin_guiones`), primeros 16 bytes → alfabeto `23456789ABCDEFGHJKLMNPQRSTUVWXYZ` (byte & 31), formato `XXXX-XXXX-XXXX-XXXX`.
- El secreto está ofuscado (XOR) en `_zk` dentro del programa y del generador. Si se cambia, hay que cambiarlo en los dos y regenerar las claves.
- La activación se guarda en localStorage `zen-licencia`. Protección básica (es HTML).

## Estructura del código (dentro del último `<script>`)

1. **Lector DXF ASCII** `parseDXF(text)` → `{ents, layers}`. Entidades: LWPOLYLINE/POLYLINE (con bulges, `dens()`), LINE, ARC, TEXT/MTEXT (texto limpio, `att` = punto de inserción MTEXT, `ang`), INSERT. Ignora espacio papel. No lee DXF binario ni DWG.
2. **Planta** (`ROLES`, `autoRoles`, `procesarPlanta`): asigna capas por nombre y por contenido (capa con más textos `0+020` = progresivas; con más `CA./JR./AV./C.` = nombres; capa cuyas polilíneas empiezan en un `0+000` = ejes). En cada progresiva traza una perpendicular de ±14 m y cruza con las capas (índice por celdas de 10 m). `side()` interpreta calzada / cuneta abierta o tapada / sardinel / franja / vereda / límite. `status()` marca OK, Intersección, Cuneta tapada, Revisar, Sin elementos. Nombre de calle: rótulo más cercano alineado con el eje (±20°).
3. **Secciones del Civil** (`leerSecciones`): títulos con progresiva (prefiere los que empiezan con ST/PROG), columnas de cotas → ajuste lineal y = ay·z + by; fila de distancias → x = ax·off + bx. Guarda marco, cuadrícula y textos (`grid`) y líneas dentro del marco (`polys`). Agrupa vistas vecinas y encadena láminas por progresiva consecutiva. `asignarGrupos` empareja grupo ↔ calle por la última progresiva (tolerancia 2.5 m). `zAt()` da la cota de una capa a una distancia del eje. `copiarRasante()` llena cota de eje y bordes (marcadas en `zc`).
4. **Geometría** `build(sd, stn)` → primitivas (pavimento/base/subbase, cuneta, sardinel, jardín con pendiente hacia la vereda, vereda, límite, muros, bloques). Es la misma para la vista y para el DXF.
5. **Vista** `drawSeccion()`: con marco del Civil usa su rango de distancias y proporción 1:1 (×1 por defecto); `rangoMarco()` amplía el marco centrado, de 2 en 2 m, si la sección llega al borde.
6. **Exportación** `buildDXF(ids)` → DXF R12 (AC1009): marco del Civil (original o reconstruido/ampliado), CIVIL-TERRENO, CIVIL-OTROS, SEC-* (contornos), SEC-RELLENO (SOLID con color), SEC-RASANTE y SEC-SUBRASANTE continuas.
7. **Estado** `S.streets[id].st[i]` = {st, s, L, R, read, z, zc, muro, bl, gen, fr}. Se guarda en localStorage (sin `polys`). "Guardar/Abrir proyecto" usa el mismo JSON.

## Archivos de prueba usados

- `Planta_Clave-Metrados-_Contamana_011set_ultimo.dxf` (planta, capas C-ROAD / PAV18 / PAV19 / PAV54 / PAV66 / MANZANAS / NCALLE) → 13 calles, 249 progresivas.
- `datos_civil_2.dxf` (Civil exportado a AutoCAD: C-ROAD-SCTN-VIEW, C-ROAD-SECT terreno, C-ROAD-SHAP/LINK/CORR/SCTN corredor) → 242 secciones, 12 grupos, todas emparejadas.
- `1.6._PLANO_CLAVE_-_METRADOS_-_PETRO.dxf` (ejes en EJE DE VIA con progresivas, nombres en capa "Texto") → 13 ejes con nombre.

## Pendientes conocidos

- Petro: faltan sus secciones del Civil para probar; dos ejes cortos (23.3 m y 11.4 m) sin 0+000 no se procesan.
- Errores de lectura de la planta de Contamana: Maracaná 0+480–0+520 (línea suelta en PAV19), Palestina 0+400 y Ecosol 0+220 (lecturas dudosas) → marcos ampliados a ±14/±16 m.
- Rellenos como SOLID (no HATCH editable); si el programa de cortes y rellenos necesita HATCH, generar DXF de versión mayor o usar una rutina LISP.
- Si el eje de la planta no coincide en largo con el alineamiento del Civil (> 2.5 m), el grupo queda "sin calle" y se asigna a mano.
- Instalador probado solo en navegador (no en Windows real).
