"""Modelo de DEMANDA por parada y hora del día (P6).

Dos capas, para que el dato sintético se pueda reemplazar por el real sin tocar código:

  Capa 1 – DATO  (data/demanda_parada_hora.csv)  columnas: stop_id,sentido,fecha,hora,usuarios
      * Hoy: generado aquí (sintético justificado).
      * Mañana: el archivo de usuarios por parada de la EMOV con el mismo formato.

      usuarios(parada, día, h) ~ Poisson( base × factor(parada) × perfil[h]/Σperfil
                                          × efecto_día_semana × ruido_día × multiplicador )

  Capa 2 – PASAJEROS para SUMO (personas con origen/destino/hora)
      Se toma un día (o el día típico) de la capa 1, se escala por el multiplicador y se
      sortea el destino de cada usuario: ∝ factor(destino)·(Δd/d̄)·exp(−Δd/d̄), aguas abajo.

El factor de cada parada NO es igualitario: lognormal + refuerzo por atractor (hospital, mall,
mercado, …) + refuerzo en extremos. Se guarda en data/l16_paradas.csv (columna 'factor').
"""
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import numpy as np
import pandas as pd

from common import hhmm, p


# =============================================================== factores
def calcular_factores(df, cfg, semilla=None):
    d = cfg["demanda"]
    rng = np.random.default_rng(d["semilla"] if semilla is None else semilla)
    f = rng.lognormal(np.log(d["factor_mediana"]), d["factor_sigma"], len(df))
    nombres = df["nombre"].astype(str).str.upper().values
    for palabra, k in d["refuerzos"].items():
        f = np.where([palabra.upper() in n for n in nombres], f * k, f)
    extremos = df.groupby("sentido")["orden"].transform(lambda o: (o <= 1) | (o >= o.max() - 1)).values
    f = np.where(extremos, f * d["extremo_ruta"], f)
    df = df.copy()
    df["factor"] = np.clip(f, d["factor_min"], d["factor_max"]).round(3)
    return df


def cargar_paradas(cfg, regenerar_factores=False):
    df = pd.read_csv(p(cfg, "paradas_csv"), dtype={"stop_id": str})
    if regenerar_factores or "factor" not in df.columns:
        df = calcular_factores(df, cfg)
        df.to_csv(p(cfg, "paradas_csv"), index=False)
    return df


def usuarios_dia_esperados(paradas, cfg, mult=1.0):
    d = cfg["demanda"]
    if d["modo"] == "total_linea":
        return d["base"] * mult * paradas["factor"] / paradas["factor"].sum()
    return d["base"] * mult * paradas["factor"]


def perfil_normalizado(cfg):
    perf = {int(h): float(w) for h, w in cfg["demanda"]["perfil_horario"].items()}
    tot = sum(perf.values())
    return {h: w / tot for h, w in perf.items()}


# =============================================================== capa 1 – dato
def generar_historico(paradas, cfg, dias=None, inicio="2023-01-02", semilla=None):
    """Dato SINTÉTICO de usuarios por parada y hora para varios días."""
    d = cfg["demanda"]
    rng = np.random.default_rng(d["semilla"] if semilla is None else semilla)
    dias = dias or d["dias_historico"]
    perf = perfil_normalizado(cfg)
    base = usuarios_dia_esperados(paradas, cfg, d["multiplicador_global"]).values
    efecto = {int(k): float(v) for k, v in d["efecto_dia_semana"].items()}
    t0 = date.fromisoformat(inicio)
    filas = []
    for k in range(dias):
        f = t0 + timedelta(days=k)
        mult_dia = efecto[f.weekday()] * rng.lognormal(0, d["ruido_dia_sigma"])
        for h, w in perf.items():
            n = rng.poisson(base * w * mult_dia)
            filas.append(pd.DataFrame({"stop_id": paradas.stop_id.values, "sentido": paradas.sentido.values,
                                       "fecha": f.isoformat(), "hora": h, "usuarios": n}))
    return pd.concat(filas, ignore_index=True)


def dia_tipico(dem, fecha=None, laborable=True):
    """Usuarios esperados por parada y hora para UN día: una fecha concreta o el promedio
    de los días laborables (L-V) del histórico."""
    dem = dem.copy()
    if fecha:
        x = dem[dem.fecha == str(fecha)]
    else:
        wd = pd.to_datetime(dem.fecha).dt.weekday
        x = dem[wd < 5] if laborable else dem
    return x.groupby(["stop_id", "sentido", "hora"], as_index=False)["usuarios"].mean()


# =============================================================== capa 2 – pasajeros
class Generador:
    """Convierte la tabla parada×hora en pasajeros con origen, destino y hora."""

    def __init__(self, paradas, tabla_hora, cfg, mult=1.0, semilla=None):
        self.df = paradas.reset_index(drop=True)
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg["demanda"]["semilla"] if semilla is None else semilla)
        self.ini, self.fin = hhmm(cfg["servicio"]["inicio"]), hhmm(cfg["servicio"]["fin"])
        idx = {(s, t): i for i, (s, t) in enumerate(zip(self.df.stop_id, self.df.sentido))}
        self.tasa = np.zeros((len(self.df), 30))          # usuarios esperados [parada, hora]
        for r in tabla_hora.itertuples():
            i = idx.get((str(r.stop_id), r.sentido))
            if i is not None:
                self.tasa[i, int(r.hora)] += r.usuarios
        self.mult = mult
        dm, kmin = cfg["demanda"]["dist_media_viaje_m"], cfg["demanda"]["min_paradas_viaje"]
        self.destinos = {}
        for _, g in self.df.groupby("sentido"):
            ii, dist, fac, ordn = g.index.values, g.dist_m.values, g.factor.values, g.orden.values
            for k, i in enumerate(ii):
                ok = ordn >= ordn[k] + kmin
                if ok.any():
                    dd = np.maximum(dist[ok] - dist[k], 1.0) / dm
                    w = fac[ok] * dd * np.exp(-dd)
                    self.destinos[i] = (ii[ok], w / w.sum())

        # Quien sube en una terminal toma el bus en el sentido contrario
        self.alt = {}
        por_nombre = self.df.groupby("nombre").groups
        for i in range(len(self.df)):
            if i not in self.destinos:
                for j in por_nombre.get(self.df.nombre[i], []):
                    if j != i and j in self.destinos:
                        self.alt[i] = int(j)
                        break

    def set_multiplicador(self, mult):
        self.mult = mult

    def intervalo(self, t0, t1):
        """Pasajeros que llegan a sus paradas en [t0, t1): lista ordenada (t, i_orig, i_dest)."""
        out = []
        t0, t1 = max(t0, self.ini), min(t1, self.fin)
        while t0 < t1:
            h = int(t0 // 3600)
            fin_h = min(t1, (h + 1) * 3600)
            n = self.rng.poisson(self.tasa[:, h] * self.mult * (fin_h - t0) / 3600)
            for i in np.nonzero(n)[0]:
                o = self.alt.get(int(i), int(i))
                if o in self.destinos:
                    cand, pr = self.destinos[o]
                    for _ in range(n[i]):
                        out.append((float(self.rng.uniform(t0, fin_h)), o, int(self.rng.choice(cand, p=pr))))
            t0 = fin_h
        out.sort()
        return out


def escribir_personas(gen, archivo, linea="L16"):
    """Escribe personas.rou.xml y devuelve la tabla de pasajeros (pid, t, origen, destino)."""
    viajes = gen.intervalo(0, 30 * 3600)
    df = gen.df
    root = ET.Element("routes")
    for k, (t, o, d) in enumerate(viajes):
        so, sd = df.loc[o], df.loc[d]
        per = ET.SubElement(root, "person", id=f"p{k}", depart=f"{t:.1f}",
                            departPos=f"{max(0.0, so.startPos - 3):.1f}")
        ET.SubElement(per, "walk", edges=so.edge, busStop=str(so.stop_id))
        ET.SubElement(per, "ride", busStop=str(sd.stop_id), lines=linea)
    ET.ElementTree(root).write(archivo, encoding="utf-8", xml_declaration=True)
    return pd.DataFrame([(f"p{k}", t, df.stop_id[o], df.sentido[o], df.stop_id[d])
                         for k, (t, o, d) in enumerate(viajes)],
                        columns=["pid", "t", "origen", "sentido", "destino"])
