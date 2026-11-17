"""Paso 1 – Filtra el GTFS para quedarse solo con la línea 16.

Uso:  python scripts/01_preparar_l16.py [--gtfs data/gtfs_3lineas.zip] [--linea L16]
Salida: data/gtfs_l16.zip (GTFS válido, solo L16) + resumen en pantalla.
"""
import argparse
import io
import zipfile
from pathlib import Path

import pandas as pd

from common import cargar_config, p


def leer_gtfs(origen: Path):
    tablas = {}
    if origen.is_dir():
        for f in origen.glob("*.txt"):
            tablas[f.name] = pd.read_csv(f, dtype=str, keep_default_na=False)
    else:
        with zipfile.ZipFile(origen) as z:
            for n in z.namelist():
                if n.endswith(".txt"):
                    tablas[Path(n).name] = pd.read_csv(z.open(n), dtype=str, keep_default_na=False)
    return tablas


def main():
    cfg = cargar_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--gtfs", default=str(p(cfg, "gtfs_zip")))
    ap.add_argument("--linea", default=cfg["linea"]["route_id"])
    ap.add_argument("--salida", default=str(p(cfg, "gtfs_l16_zip")))
    a = ap.parse_args()

    t = leer_gtfs(Path(a.gtfs))
    rutas = t["routes.txt"]
    if a.linea not in set(rutas.route_id):
        raise SystemExit(f"{a.linea} no está en routes.txt. Disponibles: {sorted(rutas.route_id)}")

    r = rutas[rutas.route_id == a.linea]
    trips = t["trips.txt"][t["trips.txt"].route_id == a.linea]
    ids = set(trips.trip_id)
    st = t["stop_times.txt"][t["stop_times.txt"].trip_id.isin(ids)]
    out = {
        "agency.txt": t["agency.txt"][t["agency.txt"].agency_id.isin(r.agency_id)],
        "routes.txt": r,
        "trips.txt": trips,
        "stop_times.txt": st,
        "stops.txt": t["stops.txt"][t["stops.txt"].stop_id.isin(st.stop_id)],
        "shapes.txt": t["shapes.txt"][t["shapes.txt"].shape_id.isin(trips.shape_id)],
        "frequencies.txt": t["frequencies.txt"][t["frequencies.txt"].trip_id.isin(ids)],
        "calendar.txt": t["calendar.txt"][t["calendar.txt"].service_id.isin(trips.service_id)],
    }
    # gtfs2pt exige calendar_dates.txt aunque esté vacío (este feed no lo trae)
    out["calendar_dates.txt"] = t.get("calendar_dates.txt",
                                      pd.DataFrame(columns=["service_id", "date", "exception_type"]))
    for extra in ("feed_info.txt", "fare_attributes.txt"):
        if extra in t:
            out[extra] = t[extra]

    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(a.salida, "w", zipfile.ZIP_DEFLATED) as z:
        for n, df in out.items():
            buf = io.StringIO()
            df.to_csv(buf, index=False)
            z.writestr(n, buf.getvalue())

    print(f"OK -> {a.salida}")
    print(f"  {a.linea}: {r.route_long_name.iloc[0]}")
    f = out["frequencies.txt"].merge(trips[["trip_id", "service_id", "shape_id"]], on="trip_id")
    for _, x in f.sort_values(["service_id", "shape_id"]).iterrows():
        n = (st.trip_id == x.trip_id).sum()
        print(f"  {x.service_id:8s} shape {x.shape_id}: {x.start_time}-{x.end_time} "
              f"cada {int(x.headway_secs)//60} min, {n} paradas")


if __name__ == "__main__":
    main()
