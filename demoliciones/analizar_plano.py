"""Analiza un plano de demoliciones (DXF) y genera un diagnostico.

Uso:
    python demoliciones/analizar_plano.py "PLANO DEMOLICIONES.dxf" -o salida/

El codigo esta en ortofoto/revisar_plano.py (tambien se usa desde la ventana del programa,
pestana Herramientas, y para verificar los carteles al exportar).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ortofoto.revisar_plano import main  # noqa: E402

if __name__ == "__main__":
    main()
