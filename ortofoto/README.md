# Ortofoto + topografía → polilíneas (prototipo)

Calza la ortofoto con los puntos topográficos y une los puntos de cada código
(VER, LP, MAR, ACC…) en polilíneas, siguiendo los bordes que se ven en la foto.
Sale un DXF con cada elemento en su capa, la foto de fondo ya calzada y una
capa `REVISAR UNION` con las uniones dudosas.

```
pip install -r requirements.txt
```

## Uso

**Bambú (la foto ya está insertada en el plano de Civil 3D):** toma el calce de la IMAGE del DXF.
```
python -m ortofoto --orto "ORTF BAMBU.tif" --calce-dxf "1. PLANO TOP SECTOR BAMBU C3D.dxf" \
    --puntos puntos_bambu.csv -o salida_bambu/
```

**Foto georreferenciada** (GeoTIFF, o TIF/JPG/PNG con `.tfw/.jgw/.pgw`):
```
python -m ortofoto --orto ortofoto.tif --puntos puntos.csv -o salida/
```

**Foto sin coordenadas:** CSV con puntos de control `col,fila,este,norte` (mínimo 2; con 3 o más, afín completa).
```
python -m ortofoto --orto foto.jpg --control control.csv --puntos puntos.csv -o salida/
```

Opciones: `--ventana XMIN YMIN XMAX YMAX` (solo una zona), `--plantilla PLANO.dxf`
(copia colores y tipos de línea de las capas), `--codigos mis_codigos.json`,
`--sin-calce-auto`, `--radio-calce 3`.

**Puntos:** CSV PNEZD (punto, norte, este, cota, descripción), como lo exporta
Civil 3D, o un DXF con los puntos COGO como texto (capa `Texto Cogo`).

## Cómo trabaja

1. **Calce:** usa la georreferencia de la foto (o la del DXF, o los puntos de
   control) y después la afina sola: busca el desplazamiento que pone los puntos
   de borde (VER, LP, MAR, SAR…) sobre los cambios de color de la foto.
2. **Unión:** para cada código arma uniones candidatas entre vecinos y les pone
   un costo según su largo y según si en la foto hay un borde que corre paralelo a
   la unión. Acepta primero las más baratas: máximo 2 vecinos por punto, sin
   cruces y sin giros en horquilla. Los tramos tapados (por ejemplo por un árbol)
   se unen solo si siguen alineados, y quedan marcados en `REVISAR UNION`.
3. **Códigos y capas:** en `codigos.json` (capa, color, tipo `linea`, `contorno`
   o `punto`, separación máxima, alias como `ESQ → LP`).

## Prueba con ortofoto sintética (plano PETRO)

```
python -m ortofoto.prueba.sintetica PETRO.dxf --ventana 550115 9072645 550435 9072960 -o prueba/
python -m ortofoto.prueba.evaluar --orto prueba/orto_sintetica.png --puntos prueba/puntos.csv \
    --referencia PETRO.dxf --ventana 550115 9072645 550435 9072960 -o prueba/eval
```

Resultado (1,238 puntos; la foto se georreferenció con un error a propósito de +1.35 / −0.85 m):

- Calce automático: corrigió −1.30 / +0.95 m (queda ~10 cm).
- Uniones que coinciden con lo que dibujó el proyectista: **71 % solo con
  geometría → 92 % guiado por la foto** (VER 65 % → 91 %, LP 80 % → 95 %, MAR 72 % → 84 %).
- La foto sintética solo tiene lo que estaba dibujado; con una foto real deberían
  unirse más tramos.
