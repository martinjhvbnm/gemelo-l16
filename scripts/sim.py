"""Núcleo de simulación SUMO + TraCI de la Línea 16 durante UN día.

ACCIÓN (TraCI): un despachador crea los buses en la terminal con el intervalo de la franja
horaria vigente (traci.vehicle.add) y respeta la flota máxima. El intervalo se puede cambiar
en vivo (set_plan / set_intervalo), igual que la demanda (set_multiplicador).

Modos de pasajeros:
  'archivo' : se escribe un personas.rou.xml (rápido; barrido y comparación)
  'traci'   : los pasajeros se inyectan minuto a minuto (permite cambiar la demanda en vivo)

Uso directo (una corrida):
  python scripts/sim.py --plan base                  # GTFS: 8 min todo el día
  python scripts/sim.py --plan models/propuesta.yaml # frecuencias propuestas por franja
  python scripts/sim.py --intervalo 5 --mult 1.5 --flota 0 --gui
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from common import cargar_config, franja_de, franjas, hhmm, nombres_franja, p
from demanda import Generador, cargar_paradas, dia_tipico, escribir_personas
import metricas

try:
    import traci
except ImportError:
    traci = None


def paradas_limpias(cfg):
    """Copia solo los <busStop> de gtfs2pt (en SUMO 1.12 el archivo trae <route> con ids inválidos)."""
    import xml.etree.ElementTree as ET
    src = p(cfg, "paradas_add")
    dst = src.with_name("l16_busstops.add.xml")
    root = ET.Element("additional")
    for bs in ET.parse(src).getroot().iter("busStop"):
        bs.attrib.pop("lines", None)
        root.append(bs)
    ET.ElementTree(root).write(dst, encoding="utf-8", xml_declaration=True)
    return dst


# ------------------------------------------------------------------ plan de frecuencias
class Plan:
    """Intervalo (min) por franja horaria."""

    def __init__(self, por_franja, cfg):
        self.cfg = cfg
        self.por_franja = {k: float(v) for k, v in por_franja.items()}

    @classmethod
    def constante(cls, minutos, cfg):
        return cls({n: minutos for n in nombres_franja(cfg)}, cfg)

    @classmethod
    def base(cls, cfg):
        return cls.constante(cfg["servicio"]["intervalo_programado_min"], cfg)

    @classmethod
    def desde(cls, x, cfg):
        if x in (None, "base"):
            return cls.base(cfg)
        with open(x, encoding="utf-8") as f:
            return cls(yaml.safe_load(f)["intervalo_min"], cfg)

    def intervalo_s(self, t):
        f = franja_de(t, self.cfg)
        return 60 * self.por_franja.get(f, self.cfg["servicio"]["intervalo_programado_min"])

    def to_dict(self):
        return dict(self.por_franja)


# ------------------------------------------------------------------ simulación
class Simulacion:
    def __init__(self, cfg, plan, mult=1.0, semilla=1, salida=None, flota=None,
                 gui=False, modo="archivo", etiqueta="sim", fondo=None):
        if traci is None:
            raise SystemExit("No encuentro traci: define SUMO_HOME")
        self.cfg, self.plan, self.mult, self.semilla = cfg, plan, mult, semilla
        self.flota = cfg["servicio"]["flota_max"] if flota is None else (flota or None)
        self.gui, self.modo, self.etiqueta = gui, modo, etiqueta
        self.fondo = cfg["simulacion"]["trafico_fondo"] if fondo is None else fondo
        self.salida = Path(salida or p(cfg, "resultados") / etiqueta)
        self.salida.mkdir(parents=True, exist_ok=True)
        self.ini = hhmm(cfg["servicio"]["inicio"])
        self.fin_despacho = hhmm(cfg["servicio"]["fin"])
        self.fin = self.fin_despacho + 60 * cfg["servicio"]["margen_fin_min"]
        self.paradas = cargar_paradas(cfg)
        dem = pd.read_csv(p(cfg, "demanda_csv"), dtype={"stop_id": str})
        self.gen = Generador(self.paradas, dia_tipico(dem), cfg, mult, semilla)
        self.t = 0
        self.prox = self.ini
        self.n_bus = 0
        self.buses = set()
        self.despachos = []          # (bus, t, franja, intervalo_s)
        self.retrasos = 0            # despachos aplazados por falta de flota
        self.n_pax = 0
        self.max_activos = 0
        self.tabla_pax = None
        self.ini_vuelta = hhmm(cfg["servicio"].get("inicio_vuelta", "06:00"))
        self.fin_vuelta = self.ini + 60 * cfg["servicio"].get("duracion_ida_min", 60)
        self.prox_v = self.ini_vuelta
        self._pax_vivo = []          # pasajeros inyectados por TraCI

    # --------------------------------------------------------- arranque
    def _cmd(self):
        c = self.cfg
        binario = "sumo-gui" if self.gui else c["simulacion"]["sumo_bin"]
        rou = []
        if self.modo == "archivo":
            per = self.salida / "personas.rou.xml"
            self.tabla_pax = escribir_personas(self.gen, per)
            self.n_pax = len(self.tabla_pax)
            rou.append(str(per))
        if self.fondo and p(c, "fondo_rou").exists():
            rou.append(str(p(c, "fondo_rou")))
        cmd = [binario, "-n", str(p(c, "red")),
               "-a", f"{paradas_limpias(c)},{p(c, 'rutas_bus')}",
               "--begin", str(self.ini - 300), "--end", str(self.fin),
               "--step-length", str(c["simulacion"]["paso_s"]),
               "--seed", str(self.semilla),
               "--time-to-teleport", str(c["simulacion"]["teleport_s"]),
               "--pedestrian.model", "nonInteracting",
               "--ignore-route-errors", "true",
               "--no-step-log", "true", "--no-warnings", "true",
               "--stop-output", str(self.salida / "stops.xml"),
               "--tripinfo-output", str(self.salida / "personinfo.xml"),
               "--tripinfo-output.write-unfinished", "true"]
        if rou:
            cmd += ["-r", ",".join(rou)]
        if self.gui:
            cmd += ["--start", "--delay", "0"]
        return cmd

    def iniciar(self):
        traci.start(self._cmd(), label=self.etiqueta)
        self.con = traci.getConnection(self.etiqueta)
        self.t = self.con.simulation.getTime()
        if self.modo == "traci":
            self._t_pax = self.t
        return self

    # --------------------------------------------------------- control en vivo
    def set_plan(self, plan):
        self.plan = plan
        self.prox = min(self.prox, self.t + plan.intervalo_s(self.t))

    def set_intervalo(self, minutos):
        self.set_plan(Plan.constante(minutos, self.cfg))

    def set_multiplicador(self, mult):
        self.mult = mult
        self.gen.set_multiplicador(mult)

    def set_flota(self, flota):
        self.flota = flota or None

    # --------------------------------------------------------- lógica
    def _activos(self):
        vivos = set(self.con.vehicle.getIDList())
        self.buses &= vivos
        return len(self.buses)

    def _despachar(self):
        if self.t < self.prox or self.t > self.fin_despacho:
            return
        n = self._activos()
        if self.flota and n >= self.flota:
            self.retrasos += 1
            self.prox = self.t + 30          # se reintenta cuando vuelva un bus
            return
        vid = f"bus_{self.n_bus}"
        self.n_bus += 1
        self.con.vehicle.add(vid, "L16_ciclo", typeID="bus_l16", depart="now", line="L16")
        self.buses.add(vid)
        h = self.plan.intervalo_s(self.t)
        self.despachos.append((vid, self.t, franja_de(self.t, self.cfg), h, "L16_ciclo"))
        self.max_activos = max(self.max_activos, n + 1)
        self.prox = self.t + h

    def _despachar_vuelta(self):
        if not (self.ini_vuelta <= self.t < self.fin_vuelta) or self.t < self.prox_v:
            return
        n = self._activos()
        if self.flota and n >= self.flota:
            self.prox_v = self.t + 30
            return
        vid = f"bus_{self.n_bus}"
        self.n_bus += 1
        self.con.vehicle.add(vid, "L16_vuelta", typeID="bus_l16", depart="now", line="L16")
        self.buses.add(vid)
        h = self.plan.intervalo_s(self.t)
        self.despachos.append((vid, self.t, franja_de(self.t, self.cfg), h, "L16_vuelta"))
        self.max_activos = max(self.max_activos, n + 1)
        self.prox_v = self.t + h

    def _inyectar_pasajeros(self, hasta):
        df = self.paradas
        for t, o, d in self.gen.intervalo(self._t_pax, hasta):
            so, sd = df.loc[o], df.loc[d]
            pid = f"p{self.n_pax}"
            self.n_pax += 1
            self._pax_vivo.append((pid, t, so.stop_id, so.sentido, sd.stop_id))
            try:
                self.con.person.add(pid, so.edge, max(0.0, so.startPos - 3), depart=max(t, self.t + 1))
                self.con.person.appendWalkingStage(pid, [so.edge], so.endPos, stopID=str(so.stop_id))
                self.con.person.appendDrivingStage(pid, sd.edge, "L16", stopID=str(sd.stop_id))
            except traci.TraCIException:
                pass
        self._t_pax = hasta

    def avanzar(self, hasta):
        hasta = min(hasta, self.fin)
        while self.t < hasta:
            if self.modo == "traci" and self._t_pax < min(self.t + 60, self.fin_despacho):
                self._inyectar_pasajeros(min(self.t + 60, self.fin_despacho))
            objetivo = min(hasta, max(self.prox, self.t + 1)) if self.t <= self.fin_despacho else hasta
            if self.t < self.fin_vuelta:
                objetivo = min(objetivo, max(self.prox_v, self.t + 1))
            if self.modo == "traci":
                objetivo = min(objetivo, self.t + 60)
            self.con.simulationStep(objetivo)
            self.t = self.con.simulation.getTime()
            self._despachar()
            self._despachar_vuelta()
        return self.t

    def terminado(self):
        return self.t >= self.fin

    # --------------------------------------------------------- estado en vivo (panel)
    def estado(self):
        c = self.con
        espera = []
        for s in self.paradas.stop_id.unique():
            try:
                espera.append((s, c.busstop.getPersonCount(s)))
            except traci.TraCIException:
                pass
        buses = []
        for v in sorted(self.buses & set(c.vehicle.getIDList()), key=lambda x: int(x.split("_")[1])):
            x, y = c.vehicle.getPosition(v)
            lon, lat = c.simulation.convertGeo(x, y)
            buses.append(dict(bus=v, lat=lat, lon=lon, pasajeros=c.vehicle.getPersonNumber(v),
                              recorrido_m=c.vehicle.getDistance(v), vel_kmh=3.6 * c.vehicle.getSpeed(v)))
        # bunching en vivo: separación entre buses consecutivos sobre la ruta ciclo
        bun = 0
        if len(buses) > 1:
            d = np.sort([b["recorrido_m"] for b in buses])
            vel = 4.5   # m/s comercial aproximada → separación esperada = intervalo × vel
            esperado = self.plan.intervalo_s(self.t) * vel
            bun = int(np.sum(np.diff(d) < self.cfg["metricas"]["umbral_bunching"] * esperado))
        return dict(t=self.t, franja=franja_de(self.t, self.cfg),
                    intervalo_min=self.plan.intervalo_s(self.t) / 60,
                    buses=buses, n_buses=len(buses), flota=self.flota,
                    esperando=dict(espera), total_esperando=sum(n for _, n in espera),
                    pares_bunching=bun, despachos=len(self.despachos), retrasos=self.retrasos,
                    pasajeros_generados=self.n_pax)

    # --------------------------------------------------------- cierre
    def cerrar(self):
        try:
            self.con.close()
        except Exception:
            pass
        pd.DataFrame(self.despachos, columns=["bus", "t", "franja", "intervalo_s", "ruta"]).to_csv(
            self.salida / "despachos.csv", index=False)
        pax = self.tabla_pax if self.tabla_pax is not None else pd.DataFrame(
            self._pax_vivo, columns=["pid", "t", "origen", "sentido", "destino"])
        pax.to_csv(self.salida / "pasajeros.csv", index=False)
        res = metricas.calcular(self.salida, self.cfg, self.plan, self.paradas)
        res["resumen"].update(dict(mult=self.mult, semilla=self.semilla, flota=self.flota or 0,
                                   pasajeros_generados=self.n_pax, retrasos_flota=self.retrasos,
                                   max_buses_simultaneos=self.max_activos,
                                   plan=json.dumps(self.plan.to_dict())))
        metricas.guardar(res, self.salida)
        return res

    def correr(self):
        self.iniciar()
        self.avanzar(self.fin)
        return self.cerrar()


def exportar_flujos(plan, cfg, archivo):
    """Exporta el plan como rutas de buses SUMO por franja (<flow> con period), equivalente a
    ptlines con frecuencia por franja. Útil para correr sin TraCI (flota ilimitada, ind. 11)."""
    import xml.etree.ElementTree as ET
    root = ET.Element("routes")
    for k, (n, a, b) in enumerate(franjas(cfg)):
        ET.SubElement(root, "flow", id=f"L16_{k}_{n}", type="bus_l16", route="L16_ciclo", line="L16",
                      begin=str(a), end=str(b), period=str(60 * plan.por_franja[n]))
    ET.indent(root)
    ET.ElementTree(root).write(archivo, encoding="utf-8", xml_declaration=True)


def main():
    cfg = cargar_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="base", help="'base' (GTFS) o YAML con intervalo_min por franja")
    ap.add_argument("--intervalo", type=float, help="intervalo constante (min), ignora --plan")
    ap.add_argument("--mult", type=float, default=1.0)
    ap.add_argument("--semilla", type=int, default=1)
    ap.add_argument("--flota", type=int, help="0 = ilimitada")
    ap.add_argument("--sin-fondo", action="store_true")
    ap.add_argument("--gui", action="store_true")
    ap.add_argument("--salida")
    a = ap.parse_args()
    plan = Plan.constante(a.intervalo, cfg) if a.intervalo else Plan.desde(a.plan, cfg)
    sim = Simulacion(cfg, plan, a.mult, a.semilla, a.salida, a.flota, a.gui,
                     fondo=False if a.sin_fondo else None)
    res = sim.correr()
    print(json.dumps(res["resumen"], indent=2, ensure_ascii=False))
    print(res["franja"].to_string(index=False))


if __name__ == "__main__":
    main()
