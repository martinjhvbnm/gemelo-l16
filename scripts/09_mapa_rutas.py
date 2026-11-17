"""Paso de validación visual – superpone el trazado GTFS (shapes.txt) y la ruta SUMO de la L16.

  python scripts/09_mapa_rutas.py
Salida: results/mapa_rutas.html (abrir en el navegador) + longitudes en pantalla.
La línea gruesa y translúcida es el GTFS; la delgada es la ruta que recorre el bus en SUMO.
Donde no se superponen hay un desvío (rulo) o un atajo.
"""
import io
import math
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd
import plotly.graph_objects as go

from common import cargar_config, p

import sumolib


def haversine_km(lat, lon):
    t = 0.0
    for a, b, c, d in zip(lat[:-1], lon[:-1], lat[1:], lon[1:]):
        p1, p2 = math.radians(a), math.radians(c)
        h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2
        t += 2 * 6371 * math.asin(math.sqrt(h))
    return t


def main():
    cfg = cargar_config()
    net = sumolib.net.readNet(str(p(cfg, "red")))
    z = zipfile.ZipFile(p(cfg, "gtfs_l16_zip"))
    sh = pd.read_csv(io.BytesIO(z.read("shapes.txt")), dtype=str)
    rutas = {r.get("id"): r.get("edges").split() for r in ET.parse(p(cfg, "rutas_bus")).getroot().iter("route")}
    par = pd.read_csv(p(cfg, "paradas_csv"), dtype={"stop_id": str})
    fig = go.Figure()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figp, axp = plt.subplots(figsize=(7, 8))
    for nombre, shape, rid, col in (("ida", "lr0f", "L16_ida", "red"), ("vuelta", "oum0", "L16_vuelta", "blue")):
        s = sh[sh.shape_id == shape].assign(q=lambda d: d.shape_pt_sequence.astype(int)).sort_values("q")
        la, lo = s.shape_pt_lat.astype(float).tolist(), s.shape_pt_lon.astype(float).tolist()
        dist_decl = float(s.shape_dist_traveled.astype(float).max()) / 1000
        print(f"{nombre}: GTFS shape_dist_traveled {dist_decl:.2f} km | polilínea GTFS medida {haversine_km(la, lo):.2f} km"
              f" | ruta SUMO {sum(net.getEdge(e).getLength() for e in rutas[rid]) / 1000:.2f} km")
        fig.add_scattermap(lat=la, lon=lo, mode="lines", name=f"GTFS {nombre}",
                              line=dict(width=9, color=col), opacity=0.3)
        lat, lon = [], []
        for e in rutas[rid]:
            for x, y in net.getEdge(e).getShape():
                g = net.convertXY2LonLat(x, y)
                lon.append(g[0])
                lat.append(g[1])
        fig.add_scattermap(lat=lat, lon=lon, mode="lines", name=f"SUMO {nombre}", line=dict(width=2, color=col))
        axp.plot(lo, la, color=col, lw=6, alpha=.25, label=f"GTFS {nombre}")
        axp.plot(lon, lat, color=col, lw=1.2, label=f"SUMO {nombre}")
        q = par[par.sentido == nombre]
        axp.scatter(q.lon, q.lat, s=10, color=col, zorder=3)
        fig.add_scattermap(lat=q.lat, lon=q.lon, mode="markers", name=f"paradas {nombre}",
                              marker=dict(size=6, color=col), text=q.orden.astype(str) + " " + q.nombre)
    fig.update_layout(map_style="open-street-map", map_zoom=12.5,
                      map_center=dict(lat=float(par.lat.mean()), lon=float(par.lon.mean())),
                      margin=dict(l=0, r=0, t=30, b=0), title="L16: trazado GTFS (grueso) vs ruta SUMO (delgado)")
    axp.set(xlabel="Longitud", ylabel="Latitud", title="Línea 16 Cuenca: trazado GTFS (grueso) y ruta SUMO")
    axp.set_aspect("equal")
    axp.legend(fontsize=8)
    figp.tight_layout()
    figp.savefig(p(cfg, "resultados") / "fig_mapa_l16.png", dpi=150)
    out = p(cfg, "resultados") / "mapa_rutas.html"
    fig.write_html(out)
    print(f"-> {out}")


if __name__ == "__main__":
    main()
