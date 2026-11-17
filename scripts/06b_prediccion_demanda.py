"""Paso 6b – Predicción de la demanda del DÍA SIGUIENTE por parada y hora (componente esperado P6).

Features: hora, día de la semana, factor de la parada, rezagos (mismo parada-hora hace 1 y 7
días) y media móvil de 7 días. Modelo: HistGradientBoosting. Validación temporal: últimas 2
semanas como prueba. Referencias ingenuas: 'igual que hace 7 días' y 'media histórica'.

  python scripts/06b_prediccion_demanda.py [--fecha 2023-02-27]
Salida: models/metricas_prediccion.json, models/demanda_manana.csv
"""
import argparse
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

from common import cargar_config, p
from demanda import cargar_paradas

F = ["hora", "dow", "factor", "lag1", "lag7", "media7"]


def features(dem, paradas):
    d = dem.merge(paradas[["stop_id", "sentido", "factor"]], on=["stop_id", "sentido"], how="left")
    d["fecha"] = pd.to_datetime(d.fecha)
    d["dow"] = d.fecha.dt.weekday
    d = d.sort_values(["stop_id", "sentido", "hora", "fecha"])
    g = d.groupby(["stop_id", "sentido", "hora"]).usuarios
    d["lag1"] = g.shift(1)
    d["lag7"] = g.shift(7)
    d["media7"] = g.transform(lambda x: x.shift(1).rolling(7).mean())
    return d


def main():
    cfg = cargar_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha", help="día a predecir (por defecto: el siguiente al histórico)")
    a = ap.parse_args()
    paradas = cargar_paradas(cfg)
    dem = pd.read_csv(p(cfg, "demanda_csv"), dtype={"stop_id": str})
    d = features(dem, paradas).dropna(subset=F)
    corte = d.fecha.max() - pd.Timedelta(days=14)
    tr, te = d[d.fecha <= corte], d[d.fecha > corte]
    m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=0).fit(tr[F], tr.usuarios)
    pred = np.clip(m.predict(te[F]), 0, None)
    met = {"modelo_MAE": mean_absolute_error(te.usuarios, pred),
           "ingenuo_lag7_MAE": mean_absolute_error(te.usuarios, te.lag7),
           "media7_MAE": mean_absolute_error(te.usuarios, te.media7),
           "total_dia_error_pct": float(100 * (pred.sum() - te.usuarios.sum()) / te.usuarios.sum()),
           "n_test": int(len(te)), "origen_dato": str(dem.get("origen", pd.Series(["?"])).iloc[0])}
    json.dump(met, open(p(cfg, "modelos") / "metricas_prediccion.json", "w"), indent=2)
    print(json.dumps(met, indent=2))

    # día siguiente
    ultimo = pd.to_datetime(dem.fecha).max().date()
    objetivo = date.fromisoformat(a.fecha) if a.fecha else ultimo + timedelta(days=1)
    full = features(dem, paradas)
    h = full.groupby(["stop_id", "sentido", "hora"])
    nxt = h.agg(factor=("factor", "first"), lag1=("usuarios", "last")).reset_index()
    nxt["lag7"] = h.usuarios.apply(lambda x: x.iloc[-7] if len(x) >= 7 else x.mean()).values
    nxt["media7"] = h.usuarios.apply(lambda x: x.iloc[-7:].mean()).values
    nxt["dow"] = objetivo.weekday()
    nxt["usuarios_pred"] = np.clip(m.predict(nxt[F]), 0, None).round(2)
    nxt["fecha"] = objetivo.isoformat()
    nxt.to_csv(p(cfg, "modelos") / "demanda_manana.csv", index=False)
    print(f"Demanda prevista {objetivo}: {nxt.usuarios_pred.sum():.0f} usuarios -> models/demanda_manana.csv")


if __name__ == "__main__":
    main()
