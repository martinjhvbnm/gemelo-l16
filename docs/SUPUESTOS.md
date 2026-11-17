# Datos sintéticos justificados (anexo del informe)

El rubro de P6 pide **generador documentado, parámetros con fuente, validación y transición**.

## 1. Generador

`scripts/demanda.py` → `generar_historico()`:

```
usuarios(parada, día, h) ~ Poisson( base · factor(parada) · perfil[h]/Σperfil · efecto_día · ε_día )
ε_día ~ LogNormal(0, 0.08)
factor(parada) = clip( LogNormal(ln 0.20, 0.6) · refuerzo_atractor · refuerzo_extremo , 0.05, 2.0 )
destino ∝ factor(destino) · (Δd/d̄)·exp(−Δd/d̄),  d̄ = 5 km,  mínimo 2 paradas aguas abajo
```

Semilla 42. Dataset: 56 días (8 semanas), columnas `stop_id,sentido,fecha,hora,usuarios,origen`.

## 2. Parámetros y fuente

| Parámetro | Valor | Fuente / justificación |
|---|---|---|
| Rutas, paradas, longitud, tiempos | GTFS | `gtfs_3lineas.zip` (DGM–GAD Cuenca), shapes `lr0f`/`oum0` |
| Intervalo programado | 480 s, 05:45–21:30 | GTFS `frequencies.txt` (L-V) |
| Usuarios/día de la línea | ≈ 7 000 | El Mercurio (9-jun-2026): los buses movilizan > 245 000 personas/día en Cuenca; ÷ 35 líneas (GTFS) |
| Base por parada | 200 personas/día | Indicación del docente (sesión 15-nov-2026) |
| Factor mediana 0.20, σ 0.6 | — | Calibrado para que el día típico ≈ 7 000 (comprobado en `08_validar.py`) |
| Refuerzo atractores | hospital ×3, mall/mercado ×2.5 … | Supuesto: polos generadores de viaje (documentar con observación propia) |
| Perfil horario | picos 6:30–8:30, 12–14, 17–19 | Supuesto a validar con conteo manual en parada por franja |
| Viaje medio d̄ | 5 km | El Mercurio: desplazamiento medio ≈ 34 min en Cuenca |
| Capacidad bus | 80 pax | Bus urbano 12 m (≈ 40 sentados + 40 de pie) |
| Abordaje | 2 s/pax | TCQSM 3ª ed. (pago a bordo) |
| Flota | 20 buses | Restricción del proyecto (indicación del docente) |
| Valor del tiempo / costo bus-h | 2.5 / 25 USD | Supuestos; análisis de sensibilidad en el informe |
| Tráfico de fondo | randomTrips, periodo 4 s (≈15 700 vehículos), semilla 42 | Ajustado para reproducir la velocidad comercial del GTFS (≈ 20 km/h) |

## 3. Validación (dato real parcial)

`08_validar.py` compara:
1. Tiempo de recorrido ida/vuelta en SUMO vs GTFS `stop_times.txt` (60.5 y 65 min).
2. Intervalo de salida simulado vs `frequencies.txt` (480 s).
3. Usuarios/día sintéticos vs ≈ 7 000 (cifra publicada).
4. **Recomendado:** conteo manual de subidas en 2–3 paradas de la L16 en una franja pico y una valle,
   comparado con la columna `usuarios` de esas paradas.

## 4. Transición al dato real

El código solo lee `data/demanda_parada_hora.csv`. Con el dato de la EMOV:
`python scripts/04_demanda.py --real archivo_emov.csv` (o cargarlo desde la página *Demanda* de la app).
Para otro GTFS basta reemplazar `data/gtfs_3lineas.zip` y repetir los pasos 1–3.
