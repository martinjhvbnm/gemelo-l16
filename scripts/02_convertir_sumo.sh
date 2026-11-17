#!/usr/bin/env bash
# Paso 2 – Convierte el GTFS de la L16 a paradas/rutas SUMO con gtfs2pt.py
# Uso: bash scripts/02_convertir_sumo.sh
# Revisa las opciones de tu versión:  python $SUMO_HOME/tools/import/gtfs/gtfs2pt.py --help
set -euo pipefail
cd "$(dirname "$0")/.."
: "${SUMO_HOME:?Define SUMO_HOME (ej. export SUMO_HOME=/usr/share/sumo)}"

NET=data/cuenca_ciudad.net.xml
GTFS=data/gtfs_l16.zip
FECHA=20230315        # miércoles (servicio L-V) dentro de calendar.txt

python scripts/gtfs2pt_compat.py "$SUMO_HOME/tools/import/gtfs/gtfs2pt.py" \
  -n "$NET" \
  --gtfs "$GTFS" \
  --date "$FECHA" \
  --modes bus \
  --additional-output data/l16_stops.add.xml \
  --route-output data/l16_pt.rou.xml \
  --vtype-output data/l16_vtypes.xml \
  --warn-unmapped \
  --repair

echo
echo "Paradas generadas: $(grep -c '<busStop' data/l16_stops.add.xml || true)"
echo "Siguiente: python scripts/03_rutas_bus.py"
# Si alguna parada no se mapeó (warning), la red no cubre esa zona o el carril no admite buses:
# vuelve a exportar la red con margen alrededor del trazado de la L16.
