"""Página What-If: FRECUENCIA × USUARIOS (las dos perillas del docente).

Usa el modelo entrenado (surrogate) para responder al instante cómo cambian la espera, la
ocupación y los buses necesarios al mover el intervalo y la cantidad de usuarios por día.
Cualquier punto se puede verificar en SUMO con un botón.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import modelo  # noqa: E402
from common import cargar_config, p  # noqa: E402
from demanda import dia_tipico  # noqa: E402

ETQ = "⚠️ DATOS SINTÉTICOS · predicción del modelo entrenado con simulaciones SUMO"


@st.cache_resource
def _modelo(mtime):
    return modelo.cargar(cargar_config())


@st.cache_data
def _base_horaria(mtime_dem, mtime_ds):
    """Usuarios por hora del día típico, ajustados a los pasajeros que realmente viajan en SUMO."""
    cfg = cargar_config()
    dem = pd.read_csv(p(cfg, "demanda_csv"), dtype={"stop_id": str})
    base = dia_tipico(dem).groupby("hora").usuarios.sum()
    calib = 1.0
    ds = p(cfg, "resultados") / "dataset_hora.csv"
    if ds.exists():
        d = pd.read_csv(ds)
        d1 = d[d.mult == 1.0]
        if len(d1):
            calib = float(d1.groupby("corrida").pasajeros.sum().mean() / base.sum())
    return base * calib


def malla(m, base_h, intervalos, usuarios, flota):
    """Predice indicadores diarios para cada combinación (intervalo, usuarios/día)."""
    tot = base_h.sum()
    validas = modelo.horas_validas()            # sin arranque ni cierre parcial del servicio
    filas = [(d * u / tot, H, flota or 999, h, H, u)
             for H in intervalos for u in usuarios for h, d in base_h.items() if h in validas]
    X = pd.DataFrame(filas, columns=["demanda_h", "intervalo_min", "flota_lim", "hora", "H", "U"])
    X = modelo.agregar_features(X)
    pr = pd.DataFrame(m.predict(X[modelo.X_COLS]), columns=modelo.Y_COLS)
    X = pd.concat([X.reset_index(drop=True), pr], axis=1)
    for c in ("espera_media_min", "espera_p95_min", "ocupacion_media", "no_atendidos_pct"):
        X[c + "_w"] = X[c] * X.demanda_h
    g = X.groupby(["H", "U"])
    out = pd.DataFrame({c: g[c + "_w"].sum() / g.demanda_h.sum()
                        for c in ("espera_media_min", "espera_p95_min", "ocupacion_media", "no_atendidos_pct")})
    out["ocupacion_p95"] = g.ocupacion_p95.max()
    return out.reset_index()


def pag_whatif():
    st.header("¿Cómo se afectan la frecuencia y la cantidad de usuarios?")
    cfg = cargar_config()
    fmod = p(cfg, "modelos") / "surrogate.joblib"
    if not fmod.exists():
        st.warning("Primero genera el dataset y entrena el modelo (página Barrido y entrenamiento).")
        return
    m = _modelo(fmod.stat().st_mtime)
    dsf = p(cfg, "resultados") / "dataset_hora.csv"
    base_h = _base_horaria(p(cfg, "demanda_csv").stat().st_mtime, dsf.stat().st_mtime if dsf.exists() else 0)
    usuarios_base = int(round(base_h.sum()))
    ciclo = modelo.ciclo_estimado(cfg)
    prog = cfg["servicio"]["intervalo_programado_min"]
    mt = cfg["metricas"]
    try:
        lo, hi = json.load(open(p(cfg, "modelos") / "metricas_modelo.json"))["rango_intervalo"]
    except Exception:  # noqa: BLE001
        lo, hi = 3.0, 20.0

    # ------------------------------------------------------------ perillas
    c1, c2, c3 = st.columns([2, 2, 1])
    H = c1.slider("🚌 Frecuencia: un bus cada … minutos", 3.0, 20.0,
                  float(cfg["servicio"]["intervalo_programado_min"]), 0.5)
    U = c2.slider("👥 Usuarios por día en la línea", 500, max(25000, 3 * usuarios_base),
                  usuarios_base, 250, help=f"Día laborable típico ≈ {usuarios_base:,} usuarios")
    flota = c3.number_input("Flota máx.", 1, 60, int(cfg["servicio"]["flota_max"]))
    if not lo <= H <= hi:
        st.warning(f"El modelo se entrenó con intervalos de {lo:g} a {hi:g} min: fuera de ese rango "
                   "la predicción no es confiable (amplía el barrido).")

    pt = malla(m, base_h, [H, cfg["servicio"]["intervalo_programado_min"]], [U], flota)
    act = pt[pt.H == H].iloc[0]
    ref = pt[pt.H == cfg["servicio"]["intervalo_programado_min"]].iloc[0]
    buses = math.ceil(ciclo / H)
    cumple = act.espera_media_min <= mt["espera_objetivo_min"] and act.ocupacion_p95 <= mt["ocupacion_objetivo"]

    k = st.columns(5)
    k[0].metric("Espera media", f"{act.espera_media_min:.1f} min",
                (f"{act.espera_media_min - ref.espera_media_min:+.1f} vs {prog:g} min" if abs(act.espera_media_min - ref.espera_media_min) >= 0.05 else None), delta_color="inverse")
    k[1].metric("Espera p95", f"{act.espera_p95_min:.1f} min")
    k[2].metric("Ocupación p95", f"{100 * act.ocupacion_p95:.0f} %",
                (f"{100 * (act.ocupacion_p95 - ref.ocupacion_p95):+.0f} pts vs {prog:g} min" if abs(act.ocupacion_p95 - ref.ocupacion_p95) >= 0.005 else None), delta_color="inverse")
    k[3].metric("Buses necesarios", f"{buses} / {flota}",
                "⚠️ supera la flota" if buses > flota else "dentro de la flota",
                delta_color="off" if buses <= flota else "inverse")
    k[4].metric("Nivel de servicio", "✅ cumple" if cumple else "❌ no cumple",
                f"espera ≤ {mt['espera_objetivo_min']} min y ocupación ≤ {100 * mt['ocupacion_objetivo']:.0f} %",
                delta_color="off")

    # ------------------------------------------------------------ mapa de calor
    intervalos = [h for h in np.arange(3, 20.5, 1.0)]
    usuarios = np.linspace(500, max(25000, 3 * usuarios_base), 25).round(-2)
    g = malla(m, base_h, intervalos, list(usuarios), flota)
    h_min_flota = ciclo / flota

    var = st.radio("Mostrar", ["Espera media (min)", "Ocupación p95 (%)", "Espera p95 (min)"], horizontal=True)
    col = {"Espera media (min)": "espera_media_min", "Ocupación p95 (%)": "ocupacion_p95",
           "Espera p95 (min)": "espera_p95_min"}[var]
    z = g.pivot(index="H", columns="U", values=col)
    if col == "ocupacion_p95":
        z = z * 100
    fig = go.Figure(go.Heatmap(z=z.values, x=z.columns, y=z.index, colorscale="RdYlGn_r",
                               colorbar=dict(title=var)))
    # zona de servicio aceptable
    # Frontera limpia: para cada cantidad de usuarios, el intervalo MÁS LARGO que cumple el nivel
    # de servicio y es operable con la flota (debajo de la línea se cumple).
    cumple = ((g.espera_media_min <= mt["espera_objetivo_min"]) &
              (g.ocupacion_p95 <= mt["ocupacion_objetivo"]) & (g.H >= ciclo / flota))
    front = g[cumple].groupby("U").H.max().reindex(sorted(g.U.unique()))
    fig.add_scatter(x=front.index, y=front.values, mode="lines", connectgaps=False, hoverinfo="skip",
                    line=dict(color="black", width=3, shape="hv"), name="intervalo máximo que cumple")
    fig.add_hrect(y0=2.5, y1=h_min_flota, fillcolor="rgba(128,128,128,0.75)", line_width=0, layer="above",
                  annotation_text=f"necesita > {flota} buses", annotation_position="top left")
    fig.add_scatter(x=[U], y=[H], mode="markers", marker=dict(size=16, color="white",
                    line=dict(color="black", width=2), symbol="x"), name="escenario actual")
    fig.update_layout(height=480, xaxis_title="Usuarios por día", yaxis_title="Intervalo entre buses (min)",
                      margin=dict(t=30), legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Línea negra = intervalo más largo que cumple el nivel de servicio (por debajo se cumple). "
               "Franja gris = intervalos que exigen más buses que la flota. " + ETQ)

    # ------------------------------------------------------------ cortes
    a, b = st.columns(2)
    gH = malla(m, base_h, intervalos, [U], flota)
    fa = go.Figure()
    fa.add_scatter(x=gH.H, y=gH.espera_media_min, name="Espera media (min)", mode="lines+markers")
    fa.add_scatter(x=gH.H, y=100 * gH.ocupacion_p95, name="Ocupación p95 (%)", yaxis="y2", mode="lines+markers")
    fa.add_vline(x=H, line_dash="dot")
    fa.update_layout(title=f"Efecto de la FRECUENCIA con {U:,} usuarios/día", xaxis_title="Intervalo (min)",
                     yaxis=dict(title="min"), yaxis2=dict(title="%", overlaying="y", side="right"),
                     height=360, legend=dict(orientation="h", y=-0.25))
    a.plotly_chart(fa, use_container_width=True)
    gU = malla(m, base_h, [H], list(usuarios), flota)
    fb = go.Figure()
    fb.add_scatter(x=gU.U, y=gU.espera_media_min, name="Espera media (min)", mode="lines+markers")
    fb.add_scatter(x=gU.U, y=100 * gU.ocupacion_p95, name="Ocupación p95 (%)", yaxis="y2", mode="lines+markers")
    fb.add_vline(x=U, line_dash="dot")
    fb.update_layout(title=f"Efecto de los USUARIOS con un bus cada {H:g} min", xaxis_title="Usuarios por día",
                     yaxis=dict(title="min"), yaxis2=dict(title="%", overlaying="y", side="right"),
                     height=360, legend=dict(orientation="h", y=-0.25))
    b.plotly_chart(fb, use_container_width=True)

    # ------------------------------------------------------------ recomendación
    cand = gH.assign(buses=np.ceil(ciclo / gH.H))
    validos = cand[(cand.espera_media_min <= mt["espera_objetivo_min"]) &
                   (cand.ocupacion_p95 <= mt["ocupacion_objetivo"]) & (cand.buses <= flota)]
    if len(validos):
        r = validos.sort_values("H").iloc[-1]
        st.success(f"Con **{U:,} usuarios/día**, el intervalo más largo que mantiene el nivel de servicio es "
                   f"**{r.H:g} min** ({int(r.buses)} buses, espera ≈ {r.espera_media_min:.1f} min, "
                   f"ocupación p95 ≈ {100 * r.ocupacion_p95:.0f} %).")
    else:
        st.error(f"Con {U:,} usuarios/día ningún intervalo cumple el nivel de servicio con {flota} buses.")

    # ------------------------------------------------------------ verificar en SUMO
    st.subheader("Verificar este punto en SUMO")
    mult = U / base_h.sum()
    carpeta = p(cfg, "resultados") / "whatif" / f"h{H:g}_u{U}"
    sin_fondo = st.checkbox("Sin tráfico de fondo (más rápido)", value=True)
    if st.button(f"🔬 Simular un día con un bus cada {H:g} min y {U:,} usuarios (×{mult:.2f})"):
        carpeta.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(ROOT / "scripts" / "sim.py"), "--intervalo", str(H), "--mult", f"{mult:.4f}",
               "--flota", str(flota), "--salida", str(carpeta)] + (["--sin-fondo"] if sin_fondo else [])
        subprocess.Popen(cmd, stdout=open(carpeta / "log.txt", "w"), stderr=subprocess.STDOUT, cwd=ROOT / "scripts")
        st.info("Simulando en segundo plano (≈ 1–2 min). Vuelve a pulsar «Actualizar» para ver el resultado.")
    st.button("🔄 Actualizar")
    filas = []
    for f in sorted((p(cfg, "resultados") / "whatif").glob("*/resumen.json")):
        r = json.load(open(f))
        Hf, Uf = float(f.parent.name.split("_")[0][1:]), int(f.parent.name.split("_u")[1])
        pr = malla(m, base_h, [Hf], [Uf], r["flota"] or None).iloc[0]
        filas.append({"intervalo_min": Hf, "usuarios_dia": Uf,
                      "espera_SUMO": r["espera_media_min"], "espera_modelo": round(pr.espera_media_min, 2),
                      "ocup_p95_SUMO": r["ocupacion_p95"], "ocup_p95_modelo": round(pr.ocupacion_p95, 3),
                      "buses_max_SUMO": r["max_buses_simultaneos"], "no_atendidos_%": r["no_atendidos_pct"]})
    if filas:
        st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)
        st.caption("Comparación modelo vs simulación: sirve como validación del surrogate en el informe.")
