"""Paso 10 – EXPORTACIÓN a SUMO por franja horaria (escenario independiente, sin TraCI).

Para el plan programado (GTFS) y el propuesto escribe:
  results/sumo_export/l16_<plan>_buses.rou.xml   <flow> por franja con period = intervalo (equivale a
                                                 ptlines con frecuencia por franja)
  results/sumo_export/l16_<plan>.sumocfg          escenario listo:  sumo-gui -c <archivo>
  results/sumo_export/l16_personas.rou.xml       pasajeros del día típico (mismos para ambos planes)
y además:
  results/sumo_export/frecuencias_franja.csv     intervalo y buses/h por franja: programado vs propuesto
  results/fig_frecuencias_franja.png             figura para la presentación

  python scripts/10_exportar_sumo.py [--propuesta models/propuesta.yaml]
"""
import argparse
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import cargar_config, franjas, hhmm, nombres_franja, p
from demanda import Generador, cargar_paradas, dia_tipico, escribir_personas
from sim import Plan, paradas_limpias


def flujos(plan, cfg, archivo):
    root = ET.Element("routes")
    # arranque del día: buses desde Hospital del Río (solo vuelta) hasta que llega el primero de la ida
    ini_v = hhmm(cfg["servicio"].get("inicio_vuelta", "06:00"))
    fin_v = hhmm(cfg["servicio"]["inicio"]) + 60 * cfg["servicio"].get("duracion_ida_min", 60)
    ET.SubElement(root, "flow", id="L16_arranque_vuelta", type="bus_l16", route="L16_vuelta", line="L16",
                  begin=str(ini_v), end=str(fin_v), period=str(plan.intervalo_s(ini_v)))
    for k, (n, a, b) in enumerate(franjas(cfg)):
        ET.SubElement(root, "flow", id=f"L16_{k}_{n}", type="bus_l16", route="L16_ciclo", line="L16",
                      begin=str(a), end=str(b), period=str(60 * plan.por_franja[n]))
    ET.indent(root)
    ET.ElementTree(root).write(archivo, encoding="utf-8", xml_declaration=True)


def sumocfg(archivo, cfg, buses, personas, salida_prefijo):
    adds = f"{paradas_limpias(cfg)},{p(cfg, 'rutas_bus')}"
    rutas = [str(buses), str(personas)]
    if cfg["simulacion"]["trafico_fondo"] and p(cfg, "fondo_rou").exists():
        rutas.append(str(p(cfg, "fondo_rou")))
    root = ET.Element("configuration")
    inp = ET.SubElement(root, "input")
    ET.SubElement(inp, "net-file", value=str(p(cfg, "red")))
    ET.SubElement(inp, "additional-files", value=adds)
    ET.SubElement(inp, "route-files", value=",".join(rutas))
    t = ET.SubElement(root, "time")
    ET.SubElement(t, "begin", value=str(hhmm(cfg["servicio"]["inicio"]) - 300))
    ET.SubElement(t, "end", value=str(hhmm(cfg["servicio"]["fin"]) + 60 * cfg["servicio"]["margen_fin_min"]))
    out = ET.SubElement(root, "output")
    ET.SubElement(out, "tripinfo-output", value=f"{salida_prefijo}_tripinfo.xml")
    ET.SubElement(out, "stop-output", value=f"{salida_prefijo}_stops.xml")
    pr = ET.SubElement(root, "processing")
    ET.SubElement(pr, "ignore-route-errors", value="true")
    ET.SubElement(pr, "time-to-teleport", value=str(cfg["simulacion"]["teleport_s"]))
    ET.SubElement(pr, "pedestrian.model", value="nonInteracting")
    ET.indent(root)
    ET.ElementTree(root).write(archivo, encoding="utf-8", xml_declaration=True)


def main():
    cfg = cargar_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--propuesta", default=str(p(cfg, "modelos") / "propuesta.yaml"))
    a = ap.parse_args()
    out = p(cfg, "resultados") / "sumo_export"
    out.mkdir(parents=True, exist_ok=True)

    paradas = cargar_paradas(cfg)
    dem = pd.read_csv(p(cfg, "demanda_csv"), dtype={"stop_id": str})
    per = out / "l16_personas.rou.xml"
    n = len(escribir_personas(Generador(paradas, dia_tipico(dem), cfg, 1.0, 1), per))

    planes = {"programado": Plan.base(cfg)}
    try:
        planes["propuesto"] = Plan.desde(a.propuesta, cfg)
    except FileNotFoundError:
        print("  (no hay propuesta: corre 06_entrenar.py; se exporta solo el programado)")
    for nombre, plan in planes.items():
        rb = out / f"l16_{nombre}_buses.rou.xml"
        flujos(plan, cfg, rb)
        sumocfg(out / f"l16_{nombre}.sumocfg", cfg, rb, per, out / nombre)
        print(f"  {nombre}: {rb.name} + l16_{nombre}.sumocfg")

    # tabla y figura de frecuencias por franja
    ciclo = 122.0
    try:
        import modelo
        ciclo = modelo.ciclo_estimado(cfg)
    except Exception:  # noqa: BLE001
        pass
    filas = []
    for fr in nombres_franja(cfg):
        fila = {"franja": fr}
        for nombre, plan in planes.items():
            h = plan.por_franja[fr]
            fila[f"intervalo_{nombre}_min"] = h
            fila[f"buses_hora_{nombre}"] = round(60 / h, 1)
            fila[f"flota_{nombre}"] = int(np.ceil(ciclo / h))
        filas.append(fila)
    t = pd.DataFrame(filas)
    t.to_csv(out / "frecuencias_franja.csv", index=False)
    print(t.to_string(index=False))

    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    x = np.arange(len(t))
    ax.bar(x - .2, t.buses_hora_programado, .4, label="Programado (GTFS)")
    if "buses_hora_propuesto" in t:
        ax.bar(x + .2, t.buses_hora_propuesto, .4, label="Propuesto")
    ax.set_xticks(x, t.franja)
    ax.set_ylabel("Buses por hora (frecuencia)")
    for i, r in t.iterrows():
        ax.text(i - .2, r.buses_hora_programado + .1, f"{r.intervalo_programado_min:g}'", ha="center", fontsize=8)
        if "intervalo_propuesto_min" in t:
            ax.text(i + .2, r.buses_hora_propuesto + .1, f"{r.intervalo_propuesto_min:g}'", ha="center", fontsize=8)
    ax.set_title("L16 – frecuencia estimada vs programada por franja (DATOS SINTÉTICOS)", fontsize=10)
    ax.legend()
    fig.tight_layout()
    fig.savefig(p(cfg, "resultados") / "fig_frecuencias_franja.png", dpi=150)
    print(f"Pasajeros exportados: {n}\nAbrir:  sumo-gui -c {out / 'l16_propuesto.sumocfg'}")


if __name__ == "__main__":
    main()
