"""Paso 7 – MEDIDA: programado (GTFS, 8 min) vs propuesto (por franja), con repeticiones.

Ambos escenarios usan las MISMAS semillas (demanda y tráfico idénticos → comparación pareada).
  python scripts/07_comparar.py [--reps 5] [--propuesta models/propuesta.yaml] [--mult 1.0]
Salidas (results/comparacion/): tabla_franjas.csv, tabla_franjas.tex, resumen.csv,
         fig_espera_franja.png, fig_ocupacion_franja.png, fig_flota_franja.png
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from common import cargar_config, nombres_franja, p
from sim import Plan, Simulacion

ETQ = "DATOS SINTÉTICOS"
IND = ["espera_media_min", "espera_p95_min", "ocupacion_media", "ocupacion_p95",
       "bunching_pct", "no_atendidos_pct", "buses_equivalentes", "horas_bus"]


def ic95(x):
    x = np.asarray(x, float)
    return 0.0 if len(x) < 2 else stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))


def main():
    cfg = cargar_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=cfg["simulacion"]["repeticiones"])
    ap.add_argument("--propuesta", default=str(p(cfg, "modelos") / "propuesta.yaml"))
    ap.add_argument("--mult", type=float, default=1.0)
    a = ap.parse_args()
    out = p(cfg, "resultados") / "comparacion"
    out.mkdir(parents=True, exist_ok=True)

    planes = {"programado": Plan.base(cfg), "propuesto": Plan.desde(a.propuesta, cfg)}
    franjas_l, resumenes, horas_l = [], [], []
    for esc, plan in planes.items():
        for s in range(1, a.reps + 1):
            d = out / f"{esc}_s{s}"
            res = Simulacion(cfg, plan, a.mult, s, d, etiqueta=f"{esc}_{s}").correr()
            franjas_l.append(res["franja"].assign(escenario=esc, semilla=s))
            horas_l.append(res["hora"].assign(escenario=esc, semilla=s))
            resumenes.append({**res["resumen"], "escenario": esc, "semilla": s})
            print(f"{esc} semilla {s}: espera {res['resumen']['espera_media_min']:.2f} min, "
                  f"horas-bus {res['resumen']['horas_bus']}")
    fr = pd.concat(franjas_l)
    rs = pd.DataFrame(resumenes)
    fr.to_csv(out / "franjas_todas.csv", index=False)
    rs.to_csv(out / "resumen.csv", index=False)

    # tabla por franja: media ± IC95 y diferencia pareada
    filas = []
    for f in nombres_franja(cfg):
        for ind in IND:
            b = fr[(fr.franja == f) & (fr.escenario == "programado")].sort_values("semilla")[ind].values
            q = fr[(fr.franja == f) & (fr.escenario == "propuesto")].sort_values("semilla")[ind].values
            pv = stats.ttest_rel(b, q).pvalue if len(b) > 1 and len(b) == len(q) else np.nan
            filas.append(dict(franja=f, indicador=ind, programado=b.mean(), ic_prog=ic95(b),
                              propuesto=q.mean(), ic_prop=ic95(q), cambio_pct=100 * (q.mean() - b.mean()) / b.mean()
                              if b.mean() else np.nan, p_valor=pv))
    t = pd.DataFrame(filas)
    t.to_csv(out / "tabla_franjas.csv", index=False)
    piv = t[t.indicador.isin(["espera_media_min", "ocupacion_p95", "buses_equivalentes"])]
    piv.assign(prog=lambda x: x.programado.round(2).astype(str) + " ± " + x.ic_prog.round(2).astype(str),
               prop=lambda x: x.propuesto.round(2).astype(str) + " ± " + x.ic_prop.round(2).astype(str))[
        ["franja", "indicador", "prog", "prop", "cambio_pct"]].to_latex(
        out / "tabla_franjas.tex", index=False, float_format="%.1f",
        caption=f"Programado vs propuesto por franja ({a.reps} repeticiones, IC 95\\%) -- {ETQ}")

    for ind, nombre, esc_y in (("espera_media_min", "fig_espera_franja.png", "Espera media (min)"),
                               ("ocupacion_p95", "fig_ocupacion_franja.png", "Ocupación p95"),
                               ("buses_equivalentes", "fig_flota_franja.png", "Buses en servicio")):
        x = t[t.indicador == ind]
        pos = np.arange(len(x))
        fig, ax = plt.subplots(figsize=(7, 3.6))
        ax.bar(pos - .2, x.programado, .4, yerr=x.ic_prog, label="Programado (GTFS)", capsize=3)
        ax.bar(pos + .2, x.propuesto, .4, yerr=x.ic_prop, label="Propuesto", capsize=3)
        ax.set_xticks(pos, x.franja)
        ax.set_ylabel(esc_y)
        ax.set_title(f"L16 – {esc_y} por franja ({a.reps} rep.) – {ETQ}", fontsize=10)
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / nombre, dpi=150)
        plt.close(fig)

    # resultados POR HORA (espera y ocupación), media de las repeticiones
    hh = pd.concat(horas_l)
    hh.to_csv(out / "horas_todas.csv", index=False)
    hm = hh.groupby(["escenario", "hora"])[["espera_media_min", "espera_p95_min", "ocupacion_media",
                                             "ocupacion_p95"]].mean().reset_index()
    hm.to_csv(out / "tabla_horas.csv", index=False)
    for cols, nombre, etq in ((["espera_media_min", "espera_p95_min"], "fig_espera_hora.png", "Espera (min)"),
                              (["ocupacion_media", "ocupacion_p95"], "fig_ocupacion_hora.png", "Ocupación")):
        fig, ax = plt.subplots(figsize=(8, 3.6))
        for esc, est in (("programado", "-"), ("propuesto", "--")):
            x = hm[hm.escenario == esc]
            for c, color in zip(cols, ("tab:blue", "tab:orange")):
                ax.plot(x.hora, x[c], est, color=color, marker="o", ms=3, label=f"{c} – {esc}")
        ax.set(xlabel="Hora del día", ylabel=etq)
        ax.set_title(f"L16 – {etq} por hora: programado (—) vs propuesto (--) – {ETQ}", fontsize=9)
        ax.legend(fontsize=7, ncol=2)
        fig.tight_layout()
        fig.savefig(out / nombre, dpi=150)
        plt.close(fig)

    g = rs.groupby("escenario")[["espera_media_min", "ocupacion_p95", "horas_bus", "costo_total_usd"]].mean()
    print("\n", g.round(3).to_string())
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
