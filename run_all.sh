#!/usr/bin/env bash
# =====================================================================
#  Script ÚNICO que repite el experimento del informe (P6 – Línea 16, Cuenca)
#  y regenera todas sus tablas y figuras.               [DATOS SINTÉTICOS]
#
#    bash run_all.sh            # experimento completo (46 corridas + comparación, varias horas)
#    bash run_all.sh --rapido   # prueba corta de todo el flujo (~30 min, sin tráfico de fondo)
#
#  Requiere: SUMO_HOME definido, data/cuenca_ciudad.net.xml y data/gtfs_3lineas.zip
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")"
: "${SUMO_HOME:?Define SUMO_HOME (p. ej. export SUMO_HOME=/usr/share/sumo)}"
RAPIDO=${1:-}
PROCESOS=${PROCESOS:-4}
for f in data/cuenca_ciudad.net.xml data/gtfs_3lineas.zip; do
  [ -f "$f" ] || { echo "Falta $f (ver README, sección Datos de entrada)"; exit 1; }
done
mkdir -p results models

echo "== Versiones ==" | tee results/versiones.txt
{ sumo --version | head -1; python --version
  pip freeze | grep -Ei "^(pandas|numpy|scikit-learn|scipy|streamlit|plotly|matplotlib|pyyaml|pyproj|rtree|joblib)=="
} | tee -a results/versiones.txt

echo "== 1-4: GTFS → SUMO → rutas → demanda =="
python scripts/01_preparar_l16.py                       # Tabla gtfs
bash   scripts/02_convertir_sumo.sh
python scripts/03_rutas_bus.py                          # map-matching guiado por GTFS (Tabla valid)
python scripts/04_demanda.py                            # data/demanda_parada_hora.csv (semilla 42)
[ -f data/fondo.rou.xml ] || bash scripts/00_trafico_fondo.sh 4.0 42   # 1 viaje / 4 s, semilla 42

echo "== 5: barrido usuarios × intervalos =="
if [ "$RAPIDO" == "--rapido" ]; then
  python scripts/05_barrido.py --rapido --procesos "$PROCESOS"
else
  python scripts/05_barrido.py --procesos "$PROCESOS"            # 40 corridas (config/default.yaml)
  # 6 corridas extra (intervalos 12/15/20 × demanda 1,5/2,5): se superponen temporalmente
  cp config/barrido_extra.yaml config/escenario.yaml
  trap 'rm -f config/escenario.yaml' EXIT
  python scripts/05_barrido.py --procesos "$PROCESOS"            # reanuda: solo corre las 6 nuevas
  rm -f config/escenario.yaml; trap - EXIT
fi                                                      # -> results/dataset_hora.csv (46 corridas)

echo "== 6: predicción de demanda, modelo sustituto y propuestas =="
python scripts/06b_prediccion_demanda.py                # models/demanda_manana.csv
python scripts/06_entrenar.py                           # objetivo 5 min -> models/propuesta.yaml (Tabla modelo)
python scripts/06_entrenar.py --espera-objetivo 6 --salida propuesta_6min.yaml   # E2 del informe

echo "== 7-10: comparación en SUMO, validación, mapa y exportación =="
if [ "$RAPIDO" == "--rapido" ]; then REPS=2; else REPS=3; fi
python scripts/07_comparar.py --reps $REPS --propuesta models/propuesta_6min.yaml   # Tablas comp y franja, Fig. espera
python scripts/08_validar.py                            # Tabla valid
python scripts/09_mapa_rutas.py                         # Fig. mapa
python scripts/10_exportar_sumo.py --propuesta models/propuesta_6min.yaml   # rutas SUMO por franja

echo "== 11: escenarios E1 (programado) y E2 (propuesto) para la web =="
python scripts/11_escenarios.py --todos --procesos 2

echo "Listo. Tablas y figuras en results/ y results/comparacion/   [DATOS SINTÉTICOS]"
echo "Panel web: python -m streamlit run app/app.py"
