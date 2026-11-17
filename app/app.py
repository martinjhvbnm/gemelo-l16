"""Panel web – P6 Herramienta de frecuencias de buses y paradas (Línea 16, Cuenca).

  streamlit run app/app.py

Páginas:
  1. Línea y GTFS          – mapa de paradas, frecuencias programadas
  2. Demanda               – base, multiplicador, factor por parada (editable), perfil horario,
                             carga del dato real (mismo formato)
  3. Simulación en vivo    – SUMO+TraCI corriendo; sliders de intervalo, demanda y flota EN VIVO
  4. Barrido y entrenamiento – genera el dataset y entrena el modelo (menú de entrenamiento)
  5. Optimización          – frecuencias por franja propuestas y verificación en SUMO
  6. Panel de indicadores  – por línea, franja, hora y parada (programado vs propuesto)
Todo lo calculado con el generador sintético se etiqueta como DATOS SINTÉTICOS.
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import cargar_config, guardar_escenario, nombres_franja, p, fmt_hora  # noqa: E402
from demanda import calcular_factores, dia_tipico, generar_historico  # noqa: E402

st.set_page_config(page_title="L16 Cuenca – Frecuencias", layout="wide", page_icon="🚌")
ETQ = "⚠️ DATOS SINTÉTICOS (generador documentado)"


def cfg():
    return cargar_config()


def leer_paradas():
    f = p(cfg(), "paradas_csv")
    return pd.read_csv(f, dtype={"stop_id": str}) if f.exists() else None


def leer_demanda():
    f = p(cfg(), "demanda_csv")
    return pd.read_csv(f, dtype={"stop_id": str}) if f.exists() else None


def etiqueta_origen(dem):
    if dem is not None and "origen" in dem and dem.origen.iloc[0] == "real":
        return "✅ Dato real"
    return ETQ


# =================================================================== controlador en vivo
class ControladorVivo:
    """Corre la simulación en un hilo; la UI solo lee el estado y cambia parámetros."""

    def __init__(self):
        self.sim, self.hilo, self.lock = None, None, threading.Lock()
        self.corriendo, self.pausa = False, False
        self.velocidad = 60.0          # segundos simulados por segundo real
        self.historia, self.ultimo, self.error = [], None, None

    def iniciar(self, plan, mult, flota, gui, fondo):
        from sim import Simulacion
        self.detener()
        self.historia, self.error = [], None
        self.sim = Simulacion(cfg(), plan, mult, 1, p(cfg(), "resultados") / "vivo", flota,
                              gui=gui, modo="traci", etiqueta=f"vivo{int(time.time())}", fondo=fondo).iniciar()
        self.corriendo = True
        self.hilo = threading.Thread(target=self._bucle, daemon=True)
        self.hilo.start()

    def _bucle(self):
        try:
            while self.corriendo and not self.sim.terminado():
                if self.pausa:
                    time.sleep(0.2)
                    continue
                t0 = time.time()
                with self.lock:
                    self.sim.avanzar(self.sim.t + max(10, self.velocidad * 0.5))
                    e = self.sim.estado()
                self.ultimo = e
                self.historia.append(dict(t=e["t"], hora=fmt_hora(e["t"]), esperando=e["total_esperando"],
                                          buses=e["n_buses"], intervalo=e["intervalo_min"],
                                          bunching=e["pares_bunching"],
                                          a_bordo=sum(b["pasajeros"] for b in e["buses"])))
                time.sleep(max(0, 0.5 - (time.time() - t0)))
            with self.lock:
                self.resultado = self.sim.cerrar()
        except Exception as ex:   # noqa: BLE001
            self.error = str(ex)
        self.corriendo = False

    def detener(self):
        self.corriendo = False
        if self.hilo and self.hilo.is_alive():
            self.hilo.join(timeout=10)

    def cambiar(self, fn):
        if self.sim:
            with self.lock:
                fn(self.sim)


@st.cache_resource
def controlador():
    return ControladorVivo()


# =================================================================== páginas
def pag_linea():
    st.header("Línea 16 · Pan de Azúcar – Hospital del Río")
    par = leer_paradas()
    if par is None:
        st.warning("Falta data/l16_paradas.csv: corre los pasos 1–3 (ver README).")
        return
    c1, c2 = st.columns([2, 1])
    with c1:
        fig = px.scatter_map(par, lat="lat", lon="lon", color="sentido", hover_name="nombre",
                                color_discrete_map={"ida": "#d62728", "vuelta": "#1f77b4"},
                                hover_data=["orden", "stop_id"], zoom=12, height=520,
                                center=dict(lat=float(par.lat.mean()), lon=float(par.lon.mean())))
        fig.update_layout(map_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        c = cfg()
        st.metric("Paradas ida / vuelta", f"{(par.sentido == 'ida').sum()} / {(par.sentido == 'vuelta').sum()}")
        st.metric("Longitud ida / vuelta", f"{par[par.sentido == 'ida'].dist_m.max() / 1000:.1f} / "
                                           f"{par[par.sentido == 'vuelta'].dist_m.max() / 1000:.1f} km")
        st.metric("Programado (GTFS, L-V)", f"cada {c['servicio']['intervalo_programado_min']} min")
        st.metric("Servicio", f"{c['servicio']['inicio']} – {c['servicio']['fin']}")
        st.dataframe(pd.DataFrame(c["franjas"]), hide_index=True)


def pag_demanda():
    st.header("Demanda por parada y hora del día")
    c = cfg()
    par, dem = leer_paradas(), leer_demanda()
    if par is None:
        st.warning("Faltan las paradas (pasos 1–3).")
        return
    st.caption(etiqueta_origen(dem))
    with st.expander("⚙️ Parámetros del generador (base × factor × perfil horario)", expanded=True):
        a, b, d = st.columns(3)
        modo = a.selectbox("Modo", ["por_parada", "total_linea"], index=0 if c["demanda"]["modo"] == "por_parada" else 1,
                           help="por_parada: cada parada genera base×factor/día · total_linea: base repartida")
        base = b.number_input("Base (personas/día)", 10, 100000, int(c["demanda"]["base"]), 10)
        mult = d.slider("Multiplicador global", 0.1, 3.0, float(c["demanda"]["multiplicador_global"]), 0.05)
        perf = pd.DataFrame({"hora": list(map(int, c["demanda"]["perfil_horario"].keys())),
                             "peso": list(c["demanda"]["perfil_horario"].values())})
        perf = st.data_editor(perf, hide_index=True, num_rows="fixed", key="perfil")
    st.subheader("Factor multiplicativo por parada (editable)")
    col1, col2 = st.columns([3, 1])
    if col2.button("🎲 Re-sortear factores"):
        par = calcular_factores(par, c, semilla=int(time.time()) % 10000)
    if "factor" not in par:
        par = calcular_factores(par, c)
    par_ed = col1.data_editor(par[["sentido", "orden", "stop_id", "nombre", "factor"]], hide_index=True,
                              disabled=["sentido", "orden", "stop_id", "nombre"], height=300, key="fac")
    if col2.button("💾 Guardar y regenerar el dato", type="primary"):
        par["factor"] = par_ed["factor"].values
        par.to_csv(p(c, "paradas_csv"), index=False)
        c["demanda"].update(modo=modo, base=base, multiplicador_global=mult,
                            perfil_horario={int(h): float(w) for h, w in zip(perf.hora, perf.peso)})
        guardar_escenario({"demanda": c["demanda"]})
        dem = generar_historico(par, cargar_config()).assign(origen="sintetico")
        dem.to_csv(p(c, "demanda_csv"), index=False)
        st.success(f"Guardado. Día típico: {dia_tipico(dem).usuarios.sum():.0f} usuarios/día")
    up = col2.file_uploader("Cargar dato real (stop_id,sentido,fecha,hora,usuarios)", type="csv")
    if up is not None:
        real = pd.read_csv(up, dtype={"stop_id": str}).assign(origen="real")
        real.to_csv(p(c, "demanda_csv"), index=False)
        st.success("Dato real cargado: el resto del flujo no cambia.")
        dem = real
    if dem is None:
        return
    tip = dia_tipico(dem).merge(par[["stop_id", "sentido", "orden", "nombre"]], on=["stop_id", "sentido"])
    st.metric("Usuarios en un día laborable típico", f"{tip.usuarios.sum():,.0f}",
              f"referencia ≈ {c['demanda']['objetivo_validacion_dia']:,}/línea")
    g1, g2 = st.columns(2)
    g1.plotly_chart(px.bar(tip.groupby("hora").usuarios.sum().reset_index(), x="hora", y="usuarios",
                           title="Perfil horario (línea completa)"), use_container_width=True)
    sentido = g2.radio("Sentido", ["ida", "vuelta"], horizontal=True)
    m = tip[tip.sentido == sentido].pivot_table(index="nombre", columns="hora", values="usuarios", sort=False)
    g2.plotly_chart(px.imshow(m, aspect="auto", title="Parada × hora", height=500), use_container_width=True)


def pag_vivo():
    st.header("Simulación en vivo (SUMO + TraCI)")
    from sim import Plan
    c = cfg()
    ctl = controlador()
    with st.sidebar:
        st.subheader("Controles en vivo")
        fuente = st.radio("Frecuencias", ["Constante (slider)", "Programado GTFS", "Propuesta por franja"])
        intervalo = st.slider("Intervalo (min)", 2.0, 20.0, float(c["servicio"]["intervalo_programado_min"]), 0.5)
        mult = st.slider("Demanda × (multiplicador)", 0.1, 3.0, 1.0, 0.05)
        ilimitada = st.checkbox("Flota ilimitada", value=False)
        flota = None if ilimitada else st.number_input("Flota máxima", 1, 60, int(c["servicio"]["flota_max"]))
        ctl.velocidad = st.slider("Velocidad (s simulados / s)", 10, 600, 120, 10)
        gui = st.checkbox("Abrir sumo-gui", value=False)
        fondo = st.checkbox("Tráfico de fondo", value=bool(c["simulacion"]["trafico_fondo"]))

    def plan_actual():
        if fuente == "Programado GTFS":
            return Plan.base(c)
        if fuente == "Propuesta por franja" and (p(c, "modelos") / "propuesta.yaml").exists():
            return Plan.desde(str(p(c, "modelos") / "propuesta.yaml"), c)
        return Plan.constante(intervalo, c)

    b1, b2, b3, b4 = st.columns(4)
    if b1.button("▶️ Iniciar día", type="primary", disabled=ctl.corriendo):
        ctl.iniciar(plan_actual(), mult, 0 if ilimitada else flota, gui, fondo)
    if b2.button("⏸️ Pausa / seguir", disabled=not ctl.corriendo):
        ctl.pausa = not ctl.pausa
    if b3.button("⏹️ Detener"):
        ctl.detener()
    if b4.button("🔁 Aplicar cambios en vivo", disabled=not ctl.corriendo):
        pl, m_, fl = plan_actual(), mult, (0 if ilimitada else flota)
        ctl.cambiar(lambda s: (s.set_plan(pl), s.set_multiplicador(m_), s.set_flota(fl)))
        st.toast("Parámetros aplicados en la simulación")
    if ctl.error:
        st.error(ctl.error)
    panel_vivo()


@st.fragment(run_every=1.0)
def panel_vivo():
    ctl = controlador()
    e = ctl.ultimo
    if not e:
        st.info("Pulsa ▶️ para simular un día (los pasajeros se generan minuto a minuto según la demanda).")
        return
    par = leer_paradas()
    k = st.columns(6)
    k[0].metric("Hora simulada", fmt_hora(e["t"]), e["franja"])
    k[1].metric("Intervalo vigente", f"{e['intervalo_min']:.1f} min")
    k[2].metric("Buses en servicio", f"{e['n_buses']}" + (f" / {e['flota']}" if e["flota"] else ""),
                f"{e['retrasos']} salidas retrasadas por flota", delta_color="inverse")
    k[3].metric("Pasajeros esperando", e["total_esperando"])
    k[4].metric("A bordo", sum(b["pasajeros"] for b in e["buses"]))
    k[5].metric("Pares en bunching", e["pares_bunching"], delta_color="inverse")
    c1, c2 = st.columns([3, 2])
    esp = par.drop_duplicates("stop_id").assign(esperando=lambda d: d.stop_id.map(e["esperando"]).fillna(0))
    bus = pd.DataFrame(e["buses"])
    fig = px.scatter_map(esp, lat="lat", lon="lon", size=esp.esperando + 1, color="esperando",
                            hover_name="nombre", zoom=12, height=480, color_continuous_scale="Reds",
                            center=dict(lat=float(esp.lat.mean()), lon=float(esp.lon.mean())))
    if len(bus):
        fig.add_scattermap(lat=bus.lat, lon=bus.lon, mode="markers+text", text=bus.pasajeros.astype(str),
                              marker=dict(size=16, color="#5B2C83"), name="buses")
    fig.update_layout(map_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
    c1.plotly_chart(fig, use_container_width=True)
    h = pd.DataFrame(ctl.historia)
    if len(h):
        c2.plotly_chart(px.line(h, x="hora", y=["esperando", "a_bordo"], height=230,
                                title="Pasajeros esperando / a bordo"), use_container_width=True)
        c2.plotly_chart(px.line(h, x="hora", y=["buses", "bunching"], height=230,
                                title="Buses activos y bunching"), use_container_width=True)
    if len(bus):
        st.dataframe(bus.assign(ocupacion_pct=lambda d: (100 * d.pasajeros / cfg()["bus"]["capacidad"]).round(0))
                     [["bus", "pasajeros", "ocupacion_pct", "vel_kmh", "recorrido_m"]], hide_index=True)
    st.caption(ETQ + " · al terminar el día los indicadores se guardan en results/vivo/")


def pag_entrenamiento():
    st.header("Barrido de escenarios y entrenamiento del modelo")
    c = cfg()
    st.subheader("1. Barrido usuarios × frecuencias (genera el dataset)")
    b = c["barrido"]
    st.write(f"Rejilla actual: intervalos {b['intervalos_min']} min · multiplicadores {b['multiplicadores']} · "
             f"flotas {b['flotas']} · semillas {b['semillas']}")
    rapido = st.checkbox("Modo rápido (9 corridas, sin tráfico de fondo)")
    if st.button("🚀 Lanzar barrido (en segundo plano)"):
        log = open(p(c, "resultados") / "barrido.log", "w")
        subprocess.Popen([sys.executable, str(ROOT / "scripts/05_barrido.py")] + (["--rapido"] if rapido else []),
                         stdout=log, stderr=subprocess.STDOUT, cwd=ROOT / "scripts")
        st.info("Barrido lanzado; el registro está en results/barrido.log")
    logf = p(c, "resultados") / "barrido.log"
    if logf.exists():
        st.code("".join(open(logf).readlines()[-8:]) or "…")
    ds = p(c, "resultados") / "dataset_hora.csv"
    if not ds.exists():
        st.warning("Todavía no hay dataset (results/dataset_hora.csv).")
        return
    df = pd.read_csv(ds)
    st.caption(f"{len(df)} filas · {df.corrida.nunique()} corridas · {ETQ}")
    st.plotly_chart(px.scatter(df, x="intervalo_min", y="espera_media_min", color="demanda_h",
                               title="Espera media vs intervalo (cada punto = hora de una corrida)",
                               opacity=.5), use_container_width=True)
    st.subheader("2. Menú de entrenamiento")
    import modelo
    a, b_, c_, d = st.columns(4)
    tipo = a.selectbox("Modelo", ["rf", "xgb"], format_func={"rf": "Random Forest", "xgb": "XGBoost"}.get)
    n_est = b_.slider("Árboles", 50, 1000, 300, 50)
    prof = c_.slider("Profundidad máx. (0 = libre)", 0, 30, 0)
    test = d.slider("Proporción de prueba", 0.1, 0.4, 0.2, 0.05)
    if st.button("🧠 Entrenar", type="primary"):
        hp = dict(n_estimators=n_est, max_depth=prof or None)
        with st.spinner("Entrenando…"):
            m, info, te = modelo.entrenar(df, tipo, test, **hp)
            modelo.guardar(m, info, c)
        st.success(f"Modelo guardado ({info['n_train']} filas de entrenamiento, {info['corridas_test']} corridas de prueba)")
        st.dataframe(pd.DataFrame(info["metricas"]).T, use_container_width=True)
        var = st.selectbox("Variable", modelo.Y_COLS)
        st.plotly_chart(px.scatter(te, x=var, y=f"pred_{var}", opacity=.5, title="Predicho vs SUMO"),
                        use_container_width=True)
        if info["importancia"]:
            st.bar_chart(pd.Series(info["importancia"]))


def pag_optimizacion():
    st.header("Optimización de frecuencias por franja horaria")
    c = cfg()
    import modelo
    if not (p(c, "modelos") / "surrogate.joblib").exists():
        st.warning("Entrena primero el modelo.")
        return
    m = modelo.cargar(c)
    a, b, d, e = st.columns(4)
    mult = a.slider("Demanda ×", 0.25, 3.0, 1.0, 0.05)
    flota = b.number_input("Flota máxima", 1, 60, int(c["servicio"]["flota_max"]))
    crit = d.selectbox("Criterio", ["costo", "servicio"],
                       format_func={"costo": "Mínimo costo generalizado", "servicio": "Máx. intervalo con nivel de servicio"}.get)
    fuente = e.selectbox("Demanda", ["tipico", "manana"],
                         format_func={"tipico": "Día laborable típico", "manana": "Predicción día siguiente"}.get)
    dem = leer_demanda()
    if fuente == "manana" and (p(c, "modelos") / "demanda_manana.csv").exists():
        dem_h = pd.read_csv(p(c, "modelos") / "demanda_manana.csv").groupby("hora").usuarios_pred.sum() * mult
    else:
        dem_h = dia_tipico(dem).groupby("hora").usuarios.sum() * mult
    plan, ev = modelo.optimizar(m, dem_h, c, flota, crit)
    base = c["servicio"]["intervalo_programado_min"]
    comp = []
    for fr in nombres_franja(c):
        r_p = ev[(ev.franja == fr) & (ev.intervalo_min == plan[fr])].iloc[0]
        r_b = ev[(ev.franja == fr) & (ev.intervalo_min == base)]   # programado (debe estar en candidatos)
        r_b = r_b.iloc[0] if len(r_b) else None
        comp.append(dict(franja=fr, demanda_h=round(r_p.demanda_h), programado_min=base, propuesto_min=plan[fr],
                         buses_prog=r_b.buses if r_b is not None else None, buses_prop=r_p.buses,
                         espera_prog=r_b.espera_media_min if r_b is not None else None,
                         espera_prop=r_p.espera_media_min,
                         ocup95_prog=r_b.ocupacion_p95 if r_b is not None else None, ocup95_prop=r_p.ocupacion_p95))
    comp = pd.DataFrame(comp)
    st.dataframe(comp, hide_index=True, use_container_width=True)
    st.caption("Predicción del modelo (surrogate). Verifícala en SUMO abajo. " + ETQ)
    fr_sel = st.selectbox("Curva de una franja", nombres_franja(c))
    g = ev[ev.franja == fr_sel]
    st.plotly_chart(px.line(g, x="intervalo_min", y=["espera_media_min", "buses", "costo_usd"], markers=True,
                            title=f"{fr_sel}: efecto del intervalo"), use_container_width=True)
    import yaml
    if st.button("💾 Guardar como propuesta"):
        with open(p(c, "modelos") / "propuesta.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump({"intervalo_min": plan, "mult": mult, "flota_max": flota, "criterio": crit,
                            "demanda": fuente}, f, allow_unicode=True)
        st.success("Guardado en models/propuesta.yaml")
    reps = st.slider("Repeticiones para verificar", 1, 10, 2)
    if st.button("🔬 Verificar en SUMO (programado vs propuesto)"):
        log = open(p(c, "resultados") / "comparacion.log", "w")
        subprocess.Popen([sys.executable, str(ROOT / "scripts/07_comparar.py"), "--reps", str(reps),
                          "--mult", str(mult)], stdout=log, stderr=subprocess.STDOUT, cwd=ROOT / "scripts")
        st.info("Corriendo en segundo plano; mira el Panel de indicadores al terminar.")


def pag_panel():
    st.header("Panel de indicadores · línea, franja, hora y parada")
    c = cfg()
    comp = p(c, "resultados") / "comparacion" / "tabla_franjas.csv"
    if comp.exists():
        t = pd.read_csv(comp)
        st.subheader("Programado vs propuesto (verificado en SUMO)")
        ind = st.selectbox("Indicador", t.indicador.unique())
        x = t[t.indicador == ind].melt(id_vars="franja", value_vars=["programado", "propuesto"])
        st.plotly_chart(px.bar(x, x="franja", y="value", color="variable", barmode="group", title=ind),
                        use_container_width=True)
        st.dataframe(t[t.indicador == ind].round(3), hide_index=True)
        st.caption(ETQ)
    corridas = sorted([d for d in (p(c, "resultados")).rglob("resumen.json")], key=lambda f: f.stat().st_mtime)
    if not corridas:
        st.info("Aún no hay simulaciones.")
        return
    sel = st.selectbox("Corrida", [str(f.parent.relative_to(p(c, "resultados"))) for f in corridas][::-1])
    d = p(c, "resultados") / sel
    import json
    r = json.load(open(d / "resumen.json"))
    k = st.columns(5)
    k[0].metric("Espera media", f"{r['espera_media_min']:.2f} min")
    k[1].metric("Espera p95", f"{r['espera_p95_min']:.2f} min")
    k[2].metric("Ocupación p95", f"{100 * r['ocupacion_p95']:.0f} %")
    k[3].metric("Bunching", f"{r['bunching_pct']:.1f} %")
    k[4].metric("Horas-bus", r["horas_bus"])
    h = pd.read_csv(d / "hora.csv")
    a, b = st.columns(2)
    a.plotly_chart(px.bar(h, x="hora", y="espera_media_min", title="Espera media por hora"), use_container_width=True)
    b.plotly_chart(px.bar(h, x="hora", y="ocupacion_p95", title="Ocupación p95 por hora"), use_container_width=True)
    ph = pd.read_csv(d / "parada_hora.csv", dtype={"parada": str})
    m = ph.pivot_table(index="nombre", columns="hora", values="espera_media_min")
    st.plotly_chart(px.imshow(m, aspect="auto", title="Espera media (min) por parada y hora", height=700),
                    use_container_width=True)
    st.dataframe(pd.read_csv(d / "franja.csv").round(3), hide_index=True)


from whatif import pag_whatif  # noqa: E402
from escenarios import pag_escenarios  # noqa: E402

PAGINAS = {"🎚️ Frecuencia × Usuarios": pag_whatif, "🧪 Escenarios": pag_escenarios, "📍 Línea y GTFS": pag_linea, "👥 Demanda": pag_demanda, "▶️ Simulación en vivo": pag_vivo,
           "🧪 Barrido y entrenamiento": pag_entrenamiento, "🎯 Optimización": pag_optimizacion,
           "📊 Panel de indicadores": pag_panel}
st.sidebar.title("🚌 L16 Cuenca · P6")
PAGINAS[st.sidebar.radio("Página", list(PAGINAS))]()
