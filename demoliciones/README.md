# Plano de demoliciones — análisis (fase 1)

`analizar_plano.py` lee el DXF del plano de demoliciones y produce un diagnóstico:

```
pip install -r requirements.txt
python demoliciones/analizar_plano.py "1.2. PLANO DEMOLICIONES - PETRO.dxf" -o salida_analisis
```

Salida: `resumen.md`, `etiquetas.csv` (cada etiqueta VD/MT/CL/DPV/CAN D/SAR D comparada
con la geometría a la que apunta su flecha) y `vista_demoliciones.png`.

## Cómo está armado el plano PETRO (referencia para automatizar)

| Elemento | Dónde está |
|---|---|
| Vereda a demoler (VD-xx, m²) | Modelo, capa `Vereda a demoler` (polilíneas cerradas + achurado) |
| Martillo a demoler (MT-xx, m²) | Modelo, capa `Martillo a demoler` (achurado) |
| Corte lineal (CL-xx, m) | Modelo, capa `LINEA CORTE` (línea ACAD_ISO10W100) |
| Pavimento a demoler (DPV-xx, m²) | Modelo, capa `Pav. Existente a Demoler` |
| Canaleta a demoler (CAN D-xx, m³) | Modelo, capa `Canaleta a demoler` |
| Sardinel a demoler (SAR D-xx, m) | Sin geometría de demolición propia |
| Etiquetas | **Espacio papel** (lámina D-01), MTEXT + LEADER en capa `TEXTO EN MARTILLO`, recuadro en `LETRERO` |
| Base (planta de diseño) | Bloque `planta` insertado en capa `_ Alineamiento`, congelada en la ventana |
| Lámina | D-01, A1 594×841 mm, HP DesignJet T2600dr PDF, `monochrome.ctb`, ventana 1:500 |
| Membrete | Capa `0MENBRETE`, bloques `ESCUDO CORONEL PORTILLO`, `DECODECO` |
