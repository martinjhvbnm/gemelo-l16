"""Página "🧪 Escenarios": correr uno por uno los escenarios de config/escenarios.yaml y compararlos."""
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common import cargar_config, p  # noqa: E402

esc_mod = importlib.import_module("11_escenarios")


def pag_escenarios():
    st.header("🧪 Escenarios de prueba (What-If)")
    st.caption("Cada escenario simula un día completo en SUMO (≈2–7 min). Lánzalos uno por uno y compáralos. "
               "⚠️ DATOS SINTÉTICOS")
    cfg = cargar_config()
    escs = esc_mod.cargar_escenarios()
    for eid, e in escs.items():
        out = esc_mod.carpeta(cfg, eid)
        hecho = (out / "resumen.json").exists()
        corriendo = (out / "log.txt").exists() and not hecho
        estado = "✅ listo" if hecho else ("⏳ corriendo…" if corriendo else "⚪ sin correr")
        with st.expander(f"{eid} · {e['nombre']}  —  {estado}", expanded=False):
            pl = e.get("plan", "base")
            st.markdown(f"**Pregunta:** {e['pregunta']}  \n"
                        f"**Configuración:** plan `{pl}` · demanda ×{e.get('mult', 1.0)} · "
                        f"flota {e.get('flota', 20) or 'ilimitada'} · tráfico de fondo {'sí' if e.get('fondo', True) else 'no'}  \n"
                        f"**Qué esperar:** {e['esperado']}")
            c1, c2 = st.columns([1, 3])
            if c1.button("▶️ Correr", key=f"run_{eid}", disabled=corriendo):
                out.mkdir(parents=True, exist_ok=True)
                subprocess.Popen([sys.executable, str(ROOT / "scripts" / "11_escenarios.py"), "--escenario", eid],
                                 stdout=open(out / "log.txt", "w"), stderr=subprocess.STDOUT, cwd=ROOT / "scripts")
                st.info("Simulación lanzada en segundo plano. Pulsa «Actualizar» en unos minutos.")
            if hecho:
                r = json.load(open(out / "resumen.json", encoding="utf-8"))
                k = c2.columns(5)
                k[0].metric("Espera media", f"{r['espera_media_min']:.1f} min")
                k[1].metric("Espera p95", f"{r['espera_p95_min']:.1f} min")
                k[2].metric("Ocupación p95", f"{100 * r['ocupacion_p95']:.0f} %")
                k[3].metric("Buses máx.", r["max_buses_simultaneos"])
                k[4].metric("No atendidos", f"{r['no_atendidos_pct']:.1f} %")
    st.button("🔄 Actualizar")

    df = esc_mod.resumen(cfg)
    if df.empty:
        st.info("Todavía no hay escenarios corridos.")
        return
    st.subheader("Comparación de escenarios")
    st.dataframe(df.round(3), hide_index=True, use_container_width=True)
    ind = st.selectbox("Indicador", ["espera_media_min", "espera_p95_min", "ocupacion_p95", "horas_bus",
                                     "max_buses_simultaneos", "no_atendidos_pct", "cv_headway", "bunching_pct"])
    st.plotly_chart(px.bar(df, x="id", y=ind, hover_name="nombre", text_auto=".2f",
                           title=f"{ind} por escenario"), use_container_width=True)
