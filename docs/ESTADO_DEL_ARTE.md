# Estado del arte — punto de partida (≥ 5 artículos en inglés, 2019–2026)

> El rubro (PI 3.3) valora que el equipo **lea y entienda** cada artículo: qué problema resuelve, qué
> método usa, qué resultado obtiene y en qué se diferencia de la propuesta. Esta lista es un punto de
> partida verificado; cada integrante debe leer los artículos y completar el cuadro con sus palabras.

| # | Artículo | Problema | Método | Resultado | Diferencia con nuestra propuesta |
|---|---|---|---|---|---|
| 1 | Transit-Gym: A Simulation and Evaluation Engine for Analysis of Bus Transit Systems (arXiv 2107.00105, 2021) | Evaluar sistemas de buses en simulación | SUMO + GTFS para paradas y horarios; ML para energía | *(completar)* | Ellos evalúan energía/operación; nosotros optimizamos el intervalo por franja con demanda por parada |
| 2 | Headway variability in public transport: a review of metrics, determinants, effects for quality of service and control strategies (Transport Reviews 42(3), 2022) | Cómo medir la irregularidad del intervalo | Revisión de métricas (CV, EWT…) y estrategias de control | *(completar)* | Fuente de nuestras métricas (CV del intervalo, EWT, bunching) |
| 3 | Bus Travel Time Deviation and On-Time Accuracy Model / Travel Time Reliability Considering Bus Bunching, Xi'an (Sustainability 14(23):15583, 2022) | Fiabilidad del tiempo de viaje con bunching | CV del intervalo como grado de bunching, modelo OTA | *(completar)* | Usamos el CV y el umbral de bunching como indicador, no como objetivo |
| 4 | Single Agent Robust Deep Reinforcement Learning for Bus Fleet Control (arXiv 2508.20784, 2025) | Control de flota (holding) | DRL en simulador de eventos con demanda horaria OD sintética | *(completar)* | Ellos controlan en tiempo real; nosotros planificamos la frecuencia por franja. Similar forma de generar la demanda (matriz OD horaria) |
| 5 | AI-powered transit simulator: integration between microscopic simulation and machine learning (Rezazada et al., TRC-30, 2024) | Escalar la simulación de transporte público | Micro-simulación + ML/DL como sustituto | *(completar)* | Misma idea de surrogate; nosotros lo usamos para optimizar frecuencias en una línea de Cuenca |
| 6 | Data Driven synchronization strategies of a bus line in a transit network (Kolcheva, Legrain, Trépanier, WCTR 2023) | Control en línea de una línea de bus | Optimización arc-flow + simulación; datos generados con un conjunto de entrenamiento | *(completar)* | Ellos: holding/skip-stop; nosotros: frecuencia por franja |
| 7 | Predicción de pasajeros con ML + simulación multiagente (revistas.usal.es, verificar título exacto) | Predecir la ocupación de buses | ML para demanda + simulación multiagente para validar | *(completar)* | Cercano a nuestro 06b (predicción del día siguiente) + validación en SUMO |

Referencias clásicas para el modelo analítico de espera: E[W] = H/2·(1+CV²) (Wilson, MIT 1.258) y
Excess Wait Time (TfL). Agregar en BibTeX con estilo IEEE.
