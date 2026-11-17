#!/usr/bin/env bash
# Paso 0 – Tráfico de fondo de Cuenca (sintético justificado, reproducible con semilla).
# randomTrips genera viajes de autos sobre la red; el periodo controla la intensidad.
# Justificación del periodo: ajustar para que la velocidad media de los buses en hora pico
# se acerque a la del GTFS (L16 ida: 20.35 km en 60.5 min ≈ 20 km/h).  -> ver 07_validar.py
set -euo pipefail
cd "$(dirname "$0")/.."
: "${SUMO_HOME:?Define SUMO_HOME}"
PERIODO=${1:-4.0}      # s entre viajes generados (menor = más tráfico)
SEMILLA=${2:-42}
python "$SUMO_HOME/tools/randomTrips.py" -n data/cuenca_ciudad.net.xml \
  -b 18000 -e 81000 -p "$PERIODO" --seed "$SEMILLA" --fringe-factor 5 \
  --min-distance 1000 --validate --vehicle-class passenger --prefix fondo_ \
  -o data/fondo.trips.xml -r data/fondo.rou.xml
echo "OK -> data/fondo.rou.xml (periodo $PERIODO s, semilla $SEMILLA)"
