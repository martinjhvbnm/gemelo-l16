"""Paso 11 – Escenarios de prueba "What-If" (definidos en config/escenarios.yaml).

  python scripts/11_escenarios.py --listar                 # ver los escenarios
  python scripts/11_escenarios.py --escenario E3           # correr uno (o varios: E1 E2)
  python scripts/11_escenarios.py --todos --procesos 3     # correr todos
  python scripts/11_escenarios.py --resumen                # tabla comparativa de lo ya corrido
Salidas: results/escenarios/<ID>/ (indicadores y plan usado) y results/escenarios/resumen.csv
"""
import argparse
import json
from multiprocessing import Pool
from pathlib import Path

import pandas as pd
import yaml

from common import ROOT, cargar_config, nombres_franja, p

ARCHIVO = ROOT / "config" / "escenarios.yaml"
COLS = ["espera_media_min", "espera_p95_min", "ocupacion_p95", "no_atendidos_pct", "cv_headway",
        "bunching_pct", "horas_bus", "max_buses_simultaneos", "retrasos_flota", "costo_total_usd"]


def cargar_escenarios():
    with open(ARCHIVO, encoding="utf-8") as f:
        return yaml.safe_load(f)["escenarios"]


def carpeta(cfg, eid):
    return p(cfg, "resultados") / "escenarios" / eid


def plan_de(esc, cfg):
    from sim import Plan
    pl = esc.get("plan", "base")
    if pl == "base":
        return Plan.base(cfg)
    if "constante" in pl:
        return Plan.constante(float(pl["constante"]), cfg)
    if "archivo" in pl:
        return Plan.desde(str(ROOT / pl["archivo"]), cfg)
    if "optimizar" in pl:
        import modelo
        from demanda import dia_tipico
        cfg["metricas"]["espera_objetivo_min"] = float(pl["optimizar"])
        dem = pd.read_csv(p(cfg, "demanda_csv"), dtype={"stop_id": str})
        dem_h = dia_tipico(dem).groupby("hora").usuarios.sum() * float(esc.get("mult", 1.0))
        plan, _ = modelo.optimizar(modelo.cargar(cfg), dem_h, cfg, esc.get("flota", 20) or None, "servicio")
        return Plan(plan, cfg)
    raise ValueError(f"plan no reconocido: {pl}")


def correr(eid):
    from sim import Simulacion
    cfg = cargar_config()
    esc = cargar_escenarios()[eid]
    plan = plan_de(esc, cfg)
    out = carpeta(cfg, eid)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "plan.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump({"intervalo_min": plan.to_dict(), "escenario": esc}, f, allow_unicode=True)
    res = Simulacion(cfg, plan, float(esc.get("mult", 1.0)), 1, out, int(esc.get("flota", 20)),
                     etiqueta=f"esc_{eid}", fondo=bool(esc.get("fondo", True))).correr()
    r = res["resumen"]
    print(f"\n=== {eid} · {esc['nombre']} ===\n{esc['pregunta']}")
    print(f"Plan (min por franja): {plan.to_dict()}")
    print(f"Pasajeros {r['pasajeros']} | espera {r['espera_media_min']:.2f} min (p95 {r['espera_p95_min']:.1f}) | "
          f"ocupación p95 {100 * r['ocupacion_p95']:.0f} % | no atendidos {r['no_atendidos_pct']:.1f} % | "
          f"buses máx {r['max_buses_simultaneos']} | retrasos por flota {r['retrasos_flota']} | "
          f"CV {r['cv_headway']:.2f} | bunching {r['bunching_pct']:.2f} % | horas-bus {r['horas_bus']}")
    print(f"Esperado: {esc['esperado']}")
    return eid


def resumen(cfg):
    escs = cargar_escenarios()
    filas = []
    for eid, esc in escs.items():
        f = carpeta(cfg, eid) / "resumen.json"
        if not f.exists():
            continue
        r = json.load(open(f, encoding="utf-8"))
        plan = yaml.safe_load(open(carpeta(cfg, eid) / "plan.yaml", encoding="utf-8"))["intervalo_min"]
        vals = sorted(set(plan.values()))
        filas.append({"id": eid, "nombre": esc["nombre"], "mult": esc.get("mult", 1.0),
                      "flota": esc.get("flota", 20) or "∞", "fondo": esc.get("fondo", True),
                      "intervalo_min": vals[0] if len(vals) == 1 else
                      "/".join(f"{plan[k]:g}" for k in nombres_franja(cfg) if k in plan),
                      "pasajeros": r["pasajeros"], **{c: r.get(c) for c in COLS}})
    df = pd.DataFrame(filas)
    if len(df):
        df.to_csv(p(cfg, "resultados") / "escenarios" / "resumen.csv", index=False)
    return df


def main():
    cfg = cargar_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--escenario", nargs="+")
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("--procesos", type=int, default=1)
    ap.add_argument("--resumen", action="store_true")
    a = ap.parse_args()
    escs = cargar_escenarios()
    if a.listar or not (a.escenario or a.todos or a.resumen):
        for eid, e in escs.items():
            hecho = "✓" if (carpeta(cfg, eid) / "resumen.json").exists() else " "
            print(f"[{hecho}] {eid:4s} {e['nombre']}\n        {e['pregunta']}")
        return
    ids = list(escs) if a.todos else (a.escenario or [])
    if ids:
        faltan = [i for i in ids if i not in escs]
        if faltan:
            raise SystemExit(f"No existen: {faltan}. Usa --listar")
        if a.procesos > 1 and len(ids) > 1:
            with Pool(a.procesos) as pool:
                list(pool.imap_unordered(correr, ids))
        else:
            for i in ids:
                correr(i)
    df = resumen(cfg)
    if len(df):
        pd.set_option("display.width", 220)
        print("\nResumen de escenarios corridos (DATOS SINTÉTICOS):")
        print(df[["id", "nombre", "intervalo_min", "mult", "flota", "espera_media_min", "espera_p95_min",
                  "ocupacion_p95", "no_atendidos_pct", "max_buses_simultaneos", "horas_bus"]].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
