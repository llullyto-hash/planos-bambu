# planos-bambu

> Para retomar el trabajo, lea primero **ESTADO_DEL_PROYECTO.md** (criterios acordados, pendientes y cómo continuar).

Herramientas para automatizar planos de topografía y demoliciones.

| Carpeta | Qué hace |
|---|---|
| [`ortofoto/`](ortofoto/README.md) | **Programa principal (Windows):** puntos topográficos (+ ortofoto) → puntos por capa, bordes unidos, áreas cerradas con achurado y metrado. Doble clic en `INSTALAR.bat` (una vez) y luego en `ABRIR_PROGRAMA.bat`. |
| [`demoliciones/`](demoliciones/README.md) | Revisa un plano de demoliciones DXF: etiquetas contra el dibujo, capas sin uso o duplicadas y geometría perdida (también desde la ventana, pestaña *Herramientas*). |
| `herramientas/` | `crear_plantilla.py`: regenera la plantilla de capas, estilos y membrete desde el plano PETRO. |
