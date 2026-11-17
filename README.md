# P6 · Herramienta de frecuencias de buses y paradas — Línea 16, Cuenca

Examen Interciclo · Redes Vehiculares y Heterogéneas · Universidad de Cuenca (sep 2026 – feb 2027)
Autores: Martin Bravo, Mateo Dután, Sebastián Placencia, Josué Román

**Problema en una frase:** ¿con qué intervalo debe salir la L16 en cada franja del día para que la espera
y la ocupación cumplan el nivel de servicio usando la menor cantidad de buses posible (flota ≤ 20)?

> ⚠️ **DATOS SINTÉTICOS.** La demanda por parada y hora es sintética justificada (ver `docs/SUPUESTOS.md`).
> Los resultados no son medidas de campo. El dato real de la EMOV se carga con el mismo formato.

## Lazo dato → modelo → acción → medida → visualización

| Etapa | Qué hace | Dónde |
|---|---|---|
| **Dato** | GTFS de la L16 (rutas, paradas, `frequencies.txt` = 480 s) + usuarios por parada y hora: base 200 × factor por parada (lognormal) × perfil horario, calibrado a ≈ 8 500 usuarios/día | `01`, `04_demanda.py`, `demanda.py` |
| **Modelo** | Barrido usuarios × intervalos en SUMO (46 corridas) → modelo sustituto Random Forest (demanda, intervalo, flota, hora, carga relativa → espera, ocupación, bunching). Optimización del intervalo por franja con flota ≤ 20. Predicción de la demanda del día siguiente | `05`, `06`, `06b`, `modelo.py` |
| **Acción** | Despachador TraCI (`traci.vehicle.add`) con el intervalo de cada franja y límite de flota; exportación a rutas SUMO por franja (`<flow period=…>`) | `sim.py`, `10` |
| **Medida** | Espera media/p95, EWT, ocupación media/p95, CV del intervalo, bunching, horas-bus. Programado (E1) vs. propuesto (E2), 3 repeticiones pareadas, IC 95 % | `metricas.py`, `07` |
| **Visualización** | Panel web Streamlit: Frecuencia × Usuarios (What-If), escenarios, mapa, demanda, simulación en vivo, entrenamiento, optimización e indicadores por línea/parada/hora | `app/` |

## Versiones con las que se obtuvieron los resultados

| Software | Versión |
|---|---|
| Eclipse SUMO | 1.12.0 |
| Python | 3.10 |
| pandas · scikit-learn | 2.3.3 · 1.7.2 |
| Streamlit · plotly | 1.65 · 7.1 |
| pyproj | 3.7.1 |

La lista exacta queda en `results/versiones.txt` (la escribe `run_all.sh`).

### Arreglos para SUMO 1.12 (ya incluidos)

- `gtfs2pt.py` de SUMO 1.12 usa `DataFrame.append`/`iteritems`, que no existen en pandas 2 → `scripts/gtfs2pt_compat.py` los reemplaza sin tocar SUMO.
- `gtfs2pt` pide `calendar_dates.txt` → `01_preparar_l16.py` agrega uno vacío.
- SUMO 1.12 no tiene `--personinfo-output` → se usa `--tripinfo-output` (incluye `personinfo`).
- Las paradas que exporta `gtfs2pt` traen rutas inválidas → `sim.py` escribe solo los `busStop` (`data/l16_busstops.add.xml`).
- `gtfs2pt` enruta por el camino más corto (+23 % en la ida) → `03_rutas_bus.py` hace map-matching guiado por el trazado GTFS.

## Instalación

```bash
sudo apt install sumo sumo-tools            # o la versión del contenedor del curso
export SUMO_HOME=/usr/share/sumo
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Datos de entrada (no se versionan)

Copiar a `data/`:
- `cuenca_ciudad.net.xml`: red de Cuenca (OSM → `netconvert`)
- `gtfs_3lineas.zip`: GTFS entregado por el docente (calendario vencido: se simula el miércoles 2023-03-15)

## Reproducir el experimento del informe

```bash
bash run_all.sh --rapido     # prueba corta de todo el flujo (~30 min)
bash run_all.sh              # experimento completo del informe (varias horas; PROCESOS=4 por defecto)
python -m streamlit run app/app.py --server.port 8090    # panel web
```

`run_all.sh` hace exactamente lo siguiente:

| Paso | Comando | Salida | En el informe |
|---|---|---|---|
| 1 | `01_preparar_l16.py` | `data/gtfs_l16.zip` | Tabla GTFS |
| 2 | `02_convertir_sumo.sh` | `data/l16_stops.add.xml`, `data/l16_pt.rou.xml` | — |
| 3 | `03_rutas_bus.py` | `data/l16_rutas.add.xml`, `data/l16_paradas.csv` | Tabla validación |
| 4 | `04_demanda.py` | `data/demanda_parada_hora.csv` (56 días, semilla 42) | Anexo datos sintéticos |
| 0 | `00_trafico_fondo.sh 4.0 42` | `data/fondo.rou.xml` (≈ 15 700 autos) | Sec. escenario |
| 5 | `05_barrido.py` (40 corridas) + `config/barrido_extra.yaml` (6) | `results/dataset_hora.csv` | — |
| 6b | `06b_prediccion_demanda.py` | `models/demanda_manana.csv` | Sec. predicción |
| 6 | `06_entrenar.py` y `06_entrenar.py --espera-objetivo 6 --salida propuesta_6min.yaml` | `models/surrogate.joblib`, `models/propuesta*.yaml`, `models/metricas_modelo.json` | Tabla modelo |
| 7 | `07_comparar.py --reps 3 --propuesta models/propuesta_6min.yaml` | `results/comparacion/` | Tablas comparación y franja, Fig. espera/ocupación por hora |
| 8 | `08_validar.py` | `results/validacion.csv`, `fig_calor_parada_hora.png`, `fig_perfil_horario.png` | Tabla validación, Fig. calor |
| 9 | `09_mapa_rutas.py` | `results/fig_mapa_l16.png`, `results/mapa_rutas.html` | Fig. mapa |
| 10 | `10_exportar_sumo.py --propuesta models/propuesta_6min.yaml` | `results/sumo_export/` (flows por franja + `.sumocfg`) | Sec. exportación |
| 11 | `11_escenarios.py --todos` | `results/escenarios/E1`, `E2` | Página 🧪 Escenarios |

Escenarios adicionales para la presentación: `config/escenarios_extra.yaml` (E3–E10).

## Semillas

- Factores por parada y demanda: 42 · Tráfico de fondo: 42
- Barrido: semilla 1 · Comparación: semillas 1–3 (E1 y E2 usan las mismas → comparación pareada)
- Modelos: `random_state = 0`; validación dejando fuera un nivel de demanda completo

## Configuración

Todo está en `config/default.yaml` (franjas, flota, capacidad, base de 200 personas, factores, perfil
horario, rejilla del barrido, objetivos de servicio). La app guarda cambios en `config/escenario.yaml`,
que se superpone al archivo por defecto (no se versiona).

## Cargar datos reales

```bash
python scripts/04_demanda.py --real usuarios_emov.csv   # columnas: stop_id,sentido,fecha,hora,usuarios
```
El resto del flujo no cambia.

## Supuestos y limitaciones

Ver `docs/SUPUESTOS.md` (fuentes de cada parámetro) y `docs/ESTADO_DEL_ARTE.md`.
- La línea 100 no está en el GTFS; el proyecto se limita a la L16 (indicación del docente).
- Todos los buses salen de Estancia San José y hacen ida+vuelta (ruta ciclo); de 06:00 a la primera
  salida se despachan buses de calentamiento desde Hospital del Río.
- El modelo sustituto no extrapola fuera del rango entrenado y no predice bien la espera en saturación.
