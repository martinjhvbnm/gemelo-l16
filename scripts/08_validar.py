"""Paso 8 – VALIDACIÓN del dato sintético y del escenario contra datos reales parciales.

1) Tiempos de recorrido SUMO vs GTFS (stop_times.txt): ida y vuelta de la L16.
2) Intervalo real de salida vs frequencies.txt (480 s).
3) Demanda total sintética vs cifra publicada (≈245 000 personas/día en 35 líneas → ≈7 000/línea).
4) Figuras del dato: perfil horario y mapa de calor parada × hora.
  python scripts/08_validar.py [--corrida results/comparacion/programado_s1]
"""
import argparse
import io
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from common import cargar_config, p
from demanda import cargar_paradas, dia_tipico


def gtfs_tiempos(cfg):
    z = zipfile.ZipFile(p(cfg, "gtfs_l16_zip"))
    rd = lambda n: pd.read_csv(io.BytesIO(z.read(n)), dtype=str)
    trips, st = rd("trips.txt"), rd("stop_times.txt")
    t = trips[trips.service_id == "L-V"]
    out = {}
    for _, r in t.iterrows():
        x = st[st.trip_id == r.trip_id]
        seg = pd.to_timedelta(x.arrival_time).dt.total_seconds()
        out[r.shape_id] = seg.max() / 60
    return out


def main():
    cfg = cargar_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--corrida", default=str(p(cfg, "resultados") / "comparacion" / "programado_s1"))
    a = ap.parse_args()
    paradas = cargar_paradas(cfg)
    filas = []

    # 1-2) recorrido e intervalo
    from metricas import _paradas_bus
    st = _paradas_bus(f"{a.corrida}/stops.xml", cfg["bus"]["capacidad"])
    ida = paradas[paradas.sentido == "ida"].stop_id
    vta = paradas[paradas.sentido == "vuelta"].stop_id
    g = gtfs_tiempos(cfg)
    for nombre, sids, shape in (("ida", ida, "lr0f"), ("vuelta", vta, "oum0")):
        x = st[st.parada.isin(sids)]
        x = x[x.parada.isin([sids.iloc[0], sids.iloc[-1]])]
        tt = x.groupby("bus").ini.agg(lambda s: s.max() - s.min()) / 60
        tt = tt[tt > 0]
        filas.append(dict(indicador=f"recorrido_{nombre}_min", sumo=tt.mean(), real_gtfs=g.get(shape),
                          fuente="GTFS stop_times.txt (L-V)"))
    prim = st[st.parada == ida.iloc[0]].sort_values("ini")
    hw = prim.ini.diff().dropna()
    hw = hw[(prim.ini.iloc[1:] > 7 * 3600).values]
    filas.append(dict(indicador="intervalo_salida_s", sumo=hw.median(), real_gtfs=480,
                      fuente="GTFS frequencies.txt"))
    # 3) demanda
    dem = pd.read_csv(p(cfg, "demanda_csv"), dtype={"stop_id": str})
    tip = dia_tipico(dem)
    filas.append(dict(indicador="usuarios_dia_linea", sumo=tip.usuarios.sum(),
                      real_gtfs=cfg["demanda"]["objetivo_validacion_dia"],
                      fuente="El Mercurio 9-jun-2026: 245 000/día ÷ 35 líneas"))
    v = pd.DataFrame(filas)
    v["error_pct"] = 100 * (v.sumo - v.real_gtfs) / v.real_gtfs
    v.to_csv(p(cfg, "resultados") / "validacion.csv", index=False)
    print(v.round(2).to_string(index=False))

    # 4) figuras del dato
    por_h = tip.groupby("hora").usuarios.sum()
    fig, ax = plt.subplots(figsize=(7, 3))
    ax.bar(por_h.index, por_h.values, color="#AE76B3")
    for f in cfg["franjas"]:
        ax.axvline(int(f["desde"][:2]) + int(f["desde"][3:]) / 60 - .5, color="k", lw=.5, ls=":")
    ax.set(xlabel="Hora", ylabel="Usuarios/h", title="L16 – demanda horaria (día laborable) – DATOS SINTÉTICOS")
    fig.tight_layout()
    fig.savefig(p(cfg, "resultados") / "fig_perfil_horario.png", dpi=150)

    mat = tip.merge(paradas[["stop_id", "sentido", "orden"]], on=["stop_id", "sentido"])
    fig, axs = plt.subplots(1, 2, figsize=(10, 5), sharey=False)
    for ax, s in zip(axs, ["ida", "vuelta"]):
        m = mat[mat.sentido == s].pivot_table(index="orden", columns="hora", values="usuarios")
        im = ax.imshow(m.values, aspect="auto", cmap="viridis")
        ax.set(title=f"{s}: parada × hora", xlabel="Hora", ylabel="Orden de parada")
        ax.set_xticks(range(len(m.columns)), m.columns, fontsize=7)
    fig.colorbar(im, ax=axs, label="usuarios")
    fig.suptitle("Demanda por parada y hora – DATOS SINTÉTICOS")
    fig.savefig(p(cfg, "resultados") / "fig_calor_parada_hora.png", dpi=150)
    print(f"-> {p(cfg, 'resultados')}/validacion.csv y figuras")


if __name__ == "__main__":
    main()
