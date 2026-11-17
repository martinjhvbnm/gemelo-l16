"""Paso 4 – DATO de demanda por parada y hora.

  python scripts/04_demanda.py                        # genera el histórico SINTÉTICO (8 semanas)
  python scripts/04_demanda.py --regenerar-factores   # vuelve a sortear los factores por parada
  python scripts/04_demanda.py --real ruta.csv        # usa el dato real (mismo formato)

Formato (sintético o real):  stop_id,sentido,fecha,hora,usuarios
Salida: data/demanda_parada_hora.csv  +  columna 'factor' en data/l16_paradas.csv
"""
import argparse

import pandas as pd

from common import cargar_config, p
from demanda import cargar_paradas, dia_tipico, generar_historico

COLUMNAS = ["stop_id", "sentido", "fecha", "hora", "usuarios"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regenerar-factores", action="store_true")
    ap.add_argument("--real", help="CSV real de usuarios por parada con marca de hora")
    ap.add_argument("--dias", type=int)
    a = ap.parse_args()

    cfg = cargar_config()
    paradas = cargar_paradas(cfg, a.regenerar_factores)
    if a.real:
        dem = pd.read_csv(a.real, dtype={"stop_id": str})
        faltan = set(COLUMNAS) - set(dem.columns)
        if faltan:
            raise SystemExit(f"Al CSV real le faltan columnas: {faltan}")
        dem["origen"] = "real"
    else:
        dem = generar_historico(paradas, cfg, a.dias)
        dem["origen"] = "sintetico"
    dem.to_csv(p(cfg, "demanda_csv"), index=False)

    tip = dia_tipico(dem)
    tot = tip.usuarios.sum()
    obj = cfg["demanda"]["objetivo_validacion_dia"]
    print(f"OK -> {p(cfg, 'demanda_csv')}  ({dem.fecha.nunique()} días, origen {dem.origen.iloc[0]})")
    print(f"Día laborable típico: {tot:.0f} usuarios/día  (referencia Cuenca ≈ {obj}/línea → "
          f"desvío {100 * (tot - obj) / obj:+.1f} %)")
    por_h = tip.groupby("hora").usuarios.sum()
    print("Usuarios por hora:", " ".join(f"{h}h:{v:.0f}" for h, v in por_h.items()))
    top = tip.groupby(["stop_id", "sentido"]).usuarios.sum().sort_values(ascending=False).head(8)
    nombres = paradas.set_index(["stop_id", "sentido"]).nombre
    print("\nParadas con más usuarios/día:")
    for k, v in top.items():
        print(f"  {k[1]:6s} {nombres.get(k, k[0])[:40]:40s} {v:6.0f}")


if __name__ == "__main__":
    main()
