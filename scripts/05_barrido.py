"""Paso 5 – Barrido usuarios × frecuencias (indicación 7) para generar el DATASET.

Cada corrida = un día simulado con intervalo constante, multiplicador de demanda, flota y semilla.
Se reanuda: las corridas ya hechas (resumen.json existente) no se repiten.

  python scripts/05_barrido.py                    # rejilla de config (barrido:)
  python scripts/05_barrido.py --rapido           # rejilla reducida y sin tráfico de fondo (pruebas)
Salidas: results/barrido/<corrida>/…, results/dataset_hora.csv, results/dataset_dia.csv
"""
import argparse
import itertools
import json
from multiprocessing import Pool
from pathlib import Path

import pandas as pd

from common import cargar_config, p

RAIZ = None


def correr(args):
    h, m, fl, s, fondo = args
    from sim import Plan, Simulacion
    cfg = cargar_config()
    nombre = f"h{h:g}_m{m:g}_f{fl or 0}_s{s}"
    out = Path(RAIZ) / nombre
    if (out / "resumen.json").exists():
        return nombre, "ya existía"
    try:
        Simulacion(cfg, Plan.constante(h, cfg), m, s, out, fl if fl else 0,
                   etiqueta=nombre, fondo=fondo).correr()
        return nombre, "ok"
    except Exception as e:  # una corrida fallida no detiene el barrido
        return nombre, f"ERROR {e}"


def consolidar(raiz, salida):
    filas_h, filas_d = [], []
    for d in sorted(Path(raiz).iterdir()):
        if not (d / "resumen.json").exists():
            continue
        r = json.load(open(d / "resumen.json", encoding="utf-8"))
        h = pd.read_csv(d / "hora.csv")
        intervalo = float(d.name.split("_")[0][1:])
        h = h.assign(corrida=d.name, intervalo_min=intervalo, mult=r["mult"], flota=r["flota"],
                     semilla=r["semilla"], demanda_h=h.pasajeros)
        filas_h.append(h)
        filas_d.append({"corrida": d.name, "intervalo_min": intervalo, **r})
    pd.concat(filas_h).to_csv(Path(salida) / "dataset_hora.csv", index=False)
    pd.DataFrame(filas_d).to_csv(Path(salida) / "dataset_dia.csv", index=False)
    print(f"Dataset: {sum(len(x) for x in filas_h)} filas hora, {len(filas_d)} corridas "
          f"-> {salida}/dataset_hora.csv  [DATOS SINTÉTICOS]")


def main():
    global RAIZ
    cfg = cargar_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--rapido", action="store_true")
    ap.add_argument("--procesos", type=int, default=cfg["barrido"]["procesos"])
    a = ap.parse_args()
    b = cfg["barrido"]
    RAIZ = str(p(cfg, "resultados") / "barrido")
    Path(RAIZ).mkdir(parents=True, exist_ok=True)
    if a.rapido:
        rej = list(itertools.product([4, 8, 12], [0.5, 1.0, 2.0], [20], [1], [False]))
    else:
        rej = list(itertools.product(b["intervalos_min"], b["multiplicadores"], b["flotas"],
                                     b["semillas"], [cfg["simulacion"]["trafico_fondo"]]))
    print(f"{len(rej)} corridas con {a.procesos} procesos…")
    with Pool(a.procesos, initializer=_init, initargs=(RAIZ,)) as pool:
        for k, (n, estado) in enumerate(pool.imap_unordered(correr, rej), 1):
            print(f"[{k}/{len(rej)}] {n}: {estado}", flush=True)
    consolidar(RAIZ, p(cfg, "resultados"))


def _init(raiz):
    global RAIZ
    RAIZ = raiz


if __name__ == "__main__":
    main()
