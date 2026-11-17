"""Paso 6 – Entrena el surrogate con el barrido y propone frecuencias por franja.

  python scripts/06_entrenar.py                       # RF, demanda = día laborable típico
  python scripts/06_entrenar.py --modelo xgb --mult 1.5
  python scripts/06_entrenar.py --demanda manana      # usa la predicción del día siguiente (06b)
Salidas: models/surrogate.joblib, models/metricas_modelo.json,
         models/propuesta.yaml, models/evaluacion_franjas.csv, results/fig_pred_vs_real.png
"""
import argparse
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import yaml

import modelo
from common import cargar_config, p
from demanda import dia_tipico


def demanda_horaria(cfg, fuente="tipico", mult=1.0):
    if fuente == "manana":
        t = pd.read_csv(p(cfg, "modelos") / "demanda_manana.csv")
        return t.groupby("hora").usuarios_pred.sum() * mult
    dem = pd.read_csv(p(cfg, "demanda_csv"), dtype={"stop_id": str})
    return dia_tipico(dem).groupby("hora").usuarios.sum() * mult


def main():
    cfg = cargar_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", choices=["rf", "xgb"], default="rf")
    ap.add_argument("--mult", type=float, default=1.0)
    ap.add_argument("--flota", type=int)
    ap.add_argument("--criterio", choices=["costo", "servicio"])
    ap.add_argument("--demanda", choices=["tipico", "manana"], default="tipico")
    ap.add_argument("--espera-objetivo", type=float, help="nivel de servicio: espera media máx. (min)")
    ap.add_argument("--salida", default="propuesta.yaml", help="nombre del archivo de propuesta en models/")
    a = ap.parse_args()
    if a.espera_objetivo:
        cfg["metricas"]["espera_objetivo_min"] = a.espera_objetivo

    df = pd.read_csv(p(cfg, "resultados") / "dataset_hora.csv")
    m, info, te = modelo.entrenar(df, a.modelo)
    modelo.guardar(m, info, cfg)
    print(json.dumps(info["metricas"], indent=1))

    fig, ax = plt.subplots(1, 3, figsize=(12, 3.6))
    for k, c in enumerate(["espera_media_min", "ocupacion_p95", "bunching_pct"]):
        ax[k].scatter(te[c], te[f"pred_{c}"], s=6, alpha=.5)
        lim = [te[c].min(), te[c].max()]
        ax[k].plot(lim, lim, "k--", lw=1)
        ax[k].set(xlabel=f"SUMO: {c}", ylabel="predicho", title=f"R²={info['metricas'][c]['r2']:.3f}")
    fig.suptitle("Surrogate vs simulación (conjunto de prueba) – DATOS SINTÉTICOS")
    fig.tight_layout()
    fig.savefig(p(cfg, "resultados") / "fig_pred_vs_real.png", dpi=150)

    dem_h = demanda_horaria(cfg, a.demanda, a.mult)
    plan, ev = modelo.optimizar(m, dem_h, cfg, a.flota, a.criterio)
    ev.to_csv(p(cfg, "modelos") / "evaluacion_franjas.csv", index=False)
    with open(p(cfg, "modelos") / a.salida, "w", encoding="utf-8") as f:
        yaml.safe_dump({"intervalo_min": plan, "mult": a.mult, "demanda": a.demanda,
                        "flota_max": a.flota or cfg["servicio"]["flota_max"],
                        "criterio": a.criterio or cfg["optimizacion"]["criterio"]}, f, allow_unicode=True)
    base = cfg["servicio"]["intervalo_programado_min"]
    print("\nFrecuencias propuestas por franja (programado GTFS = %g min):" % base)
    for fr, h in plan.items():
        r = ev[(ev.franja == fr) & (ev.intervalo_min == h)].iloc[0]
        print(f"  {fr:12s} {h:4g} min  ({r.buses} buses, espera≈{r.espera_media_min:.1f} min, "
              f"ocup p95≈{100 * r.ocupacion_p95:.0f} %)")
    print(f"-> {p(cfg, 'modelos') / a.salida}  (validación: {info['validacion']}; "
          f"objetivo espera ≤ {cfg['metricas']['espera_objetivo_min']} min)")


if __name__ == "__main__":
    main()
