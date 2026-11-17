"""MEDIDA – indicadores a partir de las salidas de SUMO (personinfo.xml, stops.xml).

Por franja horaria, hora y parada×hora:
  * espera_media_min, espera_p95_min      – tiempo de espera en parada (personinfo/ride waitingTime)
  * ewt_min  (Excess Wait Time)           – espera real − espera programada (H/2) [TfL; Wilson MIT]
  * no_atendidos_pct                      – pasajeros que no alcanzaron a subir al final del día
  * ocupacion_media / ocupacion_p95 / ocupacion_max – carga del bus al salir de cada parada / capacidad
  * hacinamiento_pct                      – salidas con ocupación > ocupacion_objetivo
  * cv_headway                            – coeficiente de variación del intervalo real (regularidad)
  * bunching_pct                          – intervalos reales < umbral × intervalo programado
  * buses_hora                            – horas-bus operadas (costo/flota)
"""
import json
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from common import franja_de, franjas


def _personas(archivo):
    filas = []
    for _, el in ET.iterparse(archivo, events=("end",)):
        if el.tag != "personinfo":
            continue
        ride = el.find("ride")
        if ride is not None:
            arr = float(ride.get("arrival", -1) or -1)
            veh = ride.get("vehicle", "")
            filas.append(dict(pid=el.get("id"), t=float(el.get("depart")),
                              espera=float(ride.get("waitingTime", 0)),
                              atendido=arr >= 0 and veh not in ("", "NULL")))
        el.clear()
    return pd.DataFrame(filas, columns=["pid", "t", "espera", "atendido"])


def _paradas_bus(archivo, capacidad):
    filas = [dict(bus=e.get("id"), parada=e.get("busStop"), ini=float(e.get("started")),
                  fin=float(e.get("ended", e.get("started"))),
                  suben=int(e.get("loadedPersons", 0)), bajan=int(e.get("unloadedPersons", 0)))
             for e in ET.parse(archivo).getroot().iter("stopinfo") if e.get("busStop")]
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    df = df.sort_values(["bus", "ini"])
    df["carga"] = (df.suben - df.bajan).groupby(df.bus).cumsum().clip(lower=0)
    df["ocupacion"] = df.carga / capacidad
    return df


def _headways(st, plan):
    st = st.sort_values(["parada", "ini"]).copy()
    st["headway"] = st.groupby("parada").ini.diff()
    st["h_prog"] = st.ini.apply(plan.intervalo_s)
    return st.dropna(subset=["headway"])


def _agregar(per, st, hw, clave_p, clave_s, cfg):
    m = cfg["metricas"]
    g_p = per.groupby(clave_p)
    a = pd.DataFrame({
        "pasajeros": g_p.size(),
        "espera_media_min": g_p.espera.mean() / 60,
        "espera_p95_min": g_p.espera.quantile(0.95) / 60,
        "no_atendidos_pct": 100 * (1 - g_p.atendido.mean()),
    })
    g_s = st.groupby(clave_s)
    b = pd.DataFrame({
        "ocupacion_media": g_s.ocupacion.mean(),
        "ocupacion_p95": g_s.ocupacion.quantile(0.95),
        "ocupacion_max": g_s.ocupacion.max(),
        "hacinamiento_pct": 100 * g_s.ocupacion.apply(lambda x: (x > m["ocupacion_objetivo"]).mean()),
        "buses_distintos": g_s.bus.nunique(),
    })
    g_h = hw.groupby(clave_s)
    c = pd.DataFrame({
        "headway_medio_min": g_h.headway.mean() / 60,
        "headway_prog_min": g_h.h_prog.mean() / 60,
        "cv_headway": g_h.headway.std() / g_h.headway.mean(),
        "bunching_pct": 100 * (hw.headway < m["umbral_bunching"] * hw.h_prog).groupby(hw[clave_s]).mean(),
    })
    out = a.join(b, how="outer").join(c, how="outer")
    out["ewt_min"] = out.espera_media_min - out.headway_prog_min / 2
    return out


def calcular(carpeta, cfg, plan, paradas=None):
    cap = cfg["bus"]["capacidad"]
    per = _personas(carpeta / "personinfo.xml")
    pax = pd.read_csv(carpeta / "pasajeros.csv", dtype={"origen": str})
    # pasajeros que nunca aparecieron en personinfo (no llegaron a terminar) = no atendidos
    per = pax.merge(per.drop(columns="t"), on="pid", how="left").rename(columns={"origen": "parada"})
    per["atendido"] = per.atendido.fillna(False).astype(bool)
    st = _paradas_bus(carpeta / "stops.xml", cap)
    if per.empty or st.empty:
        raise RuntimeError(f"Simulación sin datos en {carpeta}: revisa paradas/rutas")
    for df, col in ((per, "t"), (st, "ini")):
        df["hora"] = (df[col] // 3600).astype(int)
        df["franja"] = df[col].apply(lambda t: franja_de(t, cfg))
    hw = _headways(st, plan)

    franja = _agregar(per, st, hw, "franja", "franja", cfg)
    franja = franja.drop(index="fuera", errors="ignore")
    hora = _agregar(per, st, hw, "hora", "hora", cfg)
    # parada × hora (para el panel)
    per_ph = per.groupby(["parada", "hora"]).agg(pasajeros=("pid", "size"),
                                                espera_media_min=("espera", lambda x: x.mean() / 60))
    st_ph = st.groupby(["parada", "hora"]).agg(ocupacion_media=("ocupacion", "mean"))
    parada_hora = per_ph.join(st_ph, how="outer").reset_index()

    # horas-bus por franja (desde el despacho hasta su última parada)
    desp = pd.read_csv(carpeta / "despachos.csv")
    fin_bus = st.groupby("bus").fin.max()
    desp["t_fin"] = desp.bus.map(fin_bus).fillna(desp.t)
    horas = {}
    for n, a, b in franjas(cfg):
        solape = (np.minimum(desp.t_fin, b) - np.maximum(desp.t, a)).clip(lower=0)
        horas[n] = horas.get(n, 0) + solape.sum() / 3600
    franja["horas_bus"] = pd.Series(horas)
    franja["buses_equivalentes"] = franja.horas_bus / pd.Series(
        {n: sum((b - a) for m_, a, b in franjas(cfg) if m_ == n) / 3600 for n in horas})
    franja["intervalo_plan_min"] = pd.Series(plan.por_franja)

    dc = desp[desp.ruta == "L16_ciclo"] if "ruta" in desp else desp
    ciclo = (dc.t_fin - dc.t)[dc.t_fin > dc.t]
    vdt, cbus = cfg["metricas"]["valor_tiempo_usd_h"], cfg["bus"]["costo_hora_bus_usd"]
    resumen = dict(
        pasajeros=int(len(per)),
        espera_media_min=round(per.espera.mean() / 60, 3),
        espera_p95_min=round(per.espera.quantile(0.95) / 60, 3),
        no_atendidos_pct=round(100 * (1 - per.atendido.mean()), 3),
        ocupacion_media=round(st.ocupacion.mean(), 4),
        ocupacion_p95=round(st.ocupacion.quantile(0.95), 4),
        hacinamiento_pct=round(100 * float((st.ocupacion > cfg["metricas"]["ocupacion_objetivo"]).mean()), 3),
        cv_headway=round(float(hw.headway.std() / hw.headway.mean()), 4),
        bunching_pct=round(100 * float((hw.headway < cfg["metricas"]["umbral_bunching"] * hw.h_prog).mean()), 3),
        despachos=int(len(desp)),
        horas_bus=round(float(franja.horas_bus.sum()), 2),
        ciclo_medio_min=round(float(ciclo.mean() / 60), 2) if len(ciclo) else None,
        costo_espera_usd=round(per.espera.sum() / 3600 * vdt, 1),
        costo_operacion_usd=round(float(franja.horas_bus.sum()) * cbus, 1),
    )
    resumen["costo_total_usd"] = round(resumen["costo_espera_usd"] + resumen["costo_operacion_usd"], 1)
    if paradas is not None:
        nom = paradas.drop_duplicates("stop_id").set_index("stop_id").nombre
        parada_hora["nombre"] = parada_hora.parada.map(nom)
    return dict(resumen=resumen, franja=franja.reset_index().rename(columns={"index": "franja"}),
                hora=hora.reset_index().rename(columns={"index": "hora"}), parada_hora=parada_hora)


def guardar(res, carpeta):
    with open(carpeta / "resumen.json", "w", encoding="utf-8") as f:
        json.dump(res["resumen"], f, indent=2, ensure_ascii=False)
    for k in ("franja", "hora", "parada_hora"):
        res[k].to_csv(carpeta / f"{k}.csv", index=False)
