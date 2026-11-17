"""MODELO – sustituto (surrogate) entrenado con el barrido + optimización de frecuencias por franja.

1) Surrogate ML:  (demanda_h, intervalo, flota, hora) → espera, ocupación, bunching, no atendidos.
   Random Forest (por defecto) o XGBoost si está instalado. Partición por CORRIDA (sin fuga).
   Se compara contra el modelo analítico clásico espera = H/2 (Wilson, MIT 1.258).
2) Optimizador: para cada franja prueba los intervalos candidatos y elige
     criterio 'costo'   : min Σ demanda·espera·VdT + costo_bus·buses·horas
     criterio 'servicio': el mayor intervalo que cumple espera ≤ objetivo y ocupación_p95 ≤ objetivo
   sujeto a  buses = ⌈ciclo / H⌉ ≤ flota_max   y   no_atendidos ≤ 1 %.
"""
import json
import math

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupShuffleSplit

from common import franjas, hhmm, nombres_franja, p

X_COLS = ["demanda_h", "intervalo_min", "flota_lim", "hora", "carga_rel"]


def agregar_features(X, capacidad=None):
    """carga_rel = pasajeros que llegan a la línea entre dos buses / capacidad de un bus
    = demanda_h · H / (60 · capacidad). Es el grado de saturación: cuando supera cierto umbral los
    buses se llenan, la gente se queda sin subir y la espera crece de forma no lineal. Con esta
    variable el modelo reconoce la saturación aunque la combinación demanda×intervalo no se haya simulado."""
    if capacidad is None:
        from common import cargar_config
        capacidad = cargar_config()["bus"]["capacidad"]
    X = X.copy()
    X["carga_rel"] = X.demanda_h * X.intervalo_min / (60.0 * capacidad)
    return X
Y_COLS = ["espera_media_min", "espera_p95_min", "ocupacion_media", "ocupacion_p95",
          "bunching_pct", "no_atendidos_pct"]


def horas_validas(cfg=None):
    """Horas con servicio estable en AMBOS sentidos. Se excluyen la hora de arranque (antes de que
    el primer bus llegue a la otra terminal: esperas artificiales) y la hora parcial del cierre.
    Sin este filtro el modelo confunde 'poca demanda' con 'arranque del día' y predice esperas altas."""
    from common import cargar_config
    cfg = cfg or cargar_config()
    ini = hhmm(cfg["servicio"]["inicio"]) + 60 * cfg["servicio"].get("duracion_ida_min", 60)
    fin = hhmm(cfg["servicio"]["fin"])
    return list(range(math.ceil(ini / 3600), fin // 3600))


def preparar(df):
    df = df.copy()
    df["flota_lim"] = df.flota.replace(0, 999)
    df = agregar_features(df)
    df = df[df.hora.isin(horas_validas())]
    # Planes infactibles por flota: con H·flota < ciclo el despachador agota los buses y salen en
    # pelotón (p. ej. H=3 min con 20 buses → esperas de 25–36 min). No son planes operables y
    # contaminan el aprendizaje; el optimizador tampoco puede elegirlos.
    from common import cargar_config
    ciclo = ciclo_estimado(cargar_config())
    lim = df.flota_lim.where(df.flota_lim < 999)
    df = df[~(df.intervalo_min * lim < 0.85 * ciclo)]
    return df.dropna(subset=X_COLS + Y_COLS).reset_index(drop=True)


def crear_modelo(tipo="rf", **hp):
    if tipo == "xgb":
        from sklearn.multioutput import MultiOutputRegressor
        from xgboost import XGBRegressor
        return MultiOutputRegressor(XGBRegressor(n_estimators=hp.get("n_estimators", 400),
                                                 max_depth=hp.get("max_depth", 6),
                                                 learning_rate=hp.get("learning_rate", 0.05),
                                                 random_state=0))
    return RandomForestRegressor(n_estimators=hp.get("n_estimators", 300),
                                 max_depth=hp.get("max_depth"), min_samples_leaf=hp.get("min_samples_leaf", 2),
                                 random_state=0, n_jobs=-1)


def entrenar(df, tipo="rf", test=0.2, **hp):
    """Validación por NIVEL DE DEMANDA (leave-one-demand-level-out): en cada pliegue se retira una
    demanda intermedia completa (p. ej. 1×) y se predice con el resto. Así todos los intervalos están
    en el entrenamiento y se mide la capacidad de interpolar a demandas no vistas. (Una partición
    aleatoria por corrida, con una semilla por combinación, puede dejar un intervalo entero fuera
    del entrenamiento y obligar a extrapolar.) El modelo final se entrena con todos los datos."""
    df = preparar(df)
    niveles = sorted(df.mult.unique()) if "mult" in df else []
    if len(niveles) >= 3:
        pliegues = [(df.mult != m, df.mult == m) for m in niveles[1:-1]]
        esquema = f"leave-one-demand-level-out ({', '.join(f'{m:g}x' for m in niveles[1:-1])})"
    else:
        gss = GroupShuffleSplit(n_splits=1, test_size=test, random_state=0)
        itr, ite = next(gss.split(df, groups=df.corrida))
        mtr = df.index.isin(df.index[itr])
        pliegues = [(mtr, ~mtr)]
        esquema = "partición aleatoria por corrida"
    partes = []
    for mtr, mte in pliegues:
        tr, te = df[mtr], df[mte]
        mdl = crear_modelo(tipo, **hp).fit(tr[X_COLS], tr[Y_COLS])
        pr = pd.DataFrame(mdl.predict(te[X_COLS]), columns=[f"pred_{c}" for c in Y_COLS], index=te.index)
        partes.append(te.join(pr))
    te = pd.concat(partes)
    met = {}
    for c in Y_COLS:
        met[c] = dict(r2=round(r2_score(te[c], te[f"pred_{c}"]), 4),
                      mae=round(mean_absolute_error(te[c], te[f"pred_{c}"]), 4))
    met["analitico_H/2_espera_media"] = dict(r2=round(r2_score(te.espera_media_min, te.intervalo_min / 2), 4),
                                             mae=round(mean_absolute_error(te.espera_media_min, te.intervalo_min / 2), 4))
    if "mult" in te:
        met["mae_espera_por_nivel_retirado"] = {f"{k:g}x": round(float(v), 3) for k, v in
            te.groupby("mult").apply(lambda g: (g.pred_espera_media_min - g.espera_media_min).abs().mean()).items()}
    m = crear_modelo(tipo, **hp).fit(df[X_COLS], df[Y_COLS])
    imp = getattr(m, "feature_importances_", None)
    info = dict(tipo=tipo, hp=hp, validacion=esquema, n_total=len(df), n_test=len(te),
                corridas_test=int(te.corrida.nunique()) if "corrida" in te else 0,
                n_train=len(df) - len(te) // max(len(pliegues), 1),
                rango_intervalo=[float(df.intervalo_min.min()), float(df.intervalo_min.max())],
                metricas=met, importancia=dict(zip(X_COLS, map(float, imp))) if imp is not None else {})
    return m, info, te


def guardar(m, info, cfg):
    d = p(cfg, "modelos")
    d.mkdir(exist_ok=True)
    joblib.dump(m, d / "surrogate.joblib")
    json.dump(info, open(d / "metricas_modelo.json", "w"), indent=2, ensure_ascii=False)


def cargar(cfg):
    return joblib.load(p(cfg, "modelos") / "surrogate.joblib")


def ciclo_estimado(cfg):
    f = p(cfg, "resultados") / "dataset_dia.csv"
    if f.exists():
        c = pd.read_csv(f).ciclo_medio_min.dropna()
        if len(c):
            return float(c.median())
    return 126.0 + 10.0      # GTFS: 60.5 + 65 min ida+vuelta + 10 min de terminal


def predecir(m, demanda_h, intervalo, flota, horas):
    X = pd.DataFrame({"demanda_h": demanda_h, "intervalo_min": intervalo,
                      "flota_lim": flota or 999, "hora": horas})
    X = agregar_features(X)
    return pd.DataFrame(m.predict(X[X_COLS]), columns=Y_COLS)


def optimizar(m, demanda_por_hora, cfg, flota=None, criterio=None):
    """demanda_por_hora: Series índice=hora → usuarios/h (toda la línea).
    Devuelve (plan dict franja→min, tabla de evaluación por franja y candidato)."""
    flota = cfg["servicio"]["flota_max"] if flota is None else flota
    criterio = criterio or cfg["optimizacion"]["criterio"]
    mt, cbus = cfg["metricas"], cfg["bus"]["costo_hora_bus_usd"]
    ciclo = ciclo_estimado(cfg)
    # Solo intervalos dentro de lo que el modelo vio al entrenar (un Random Forest no extrapola)
    candidatos = cfg["optimizacion"]["intervalos_candidatos_min"]
    try:
        lo, hi = json.load(open(p(cfg, "modelos") / "metricas_modelo.json"))["rango_intervalo"]
        candidatos = [h for h in candidatos if lo <= h <= hi]
    except (FileNotFoundError, KeyError):
        pass
    tope = cfg["optimizacion"].get("intervalo_max_min")
    if tope:
        candidatos = [h for h in candidatos if h <= tope]
    filas = []
    for nombre in nombres_franja(cfg):
        horas, dur_h = [], 0.0
        for n, a, b in franjas(cfg):
            if n == nombre:
                horas += list(range(a // 3600, math.ceil(b / 3600)))
                dur_h += (b - a) / 3600
        validas = horas_validas(cfg)
        horas = sorted(set(h for h in horas if h in demanda_por_hora.index and h in validas)) or \
            sorted(set(h for h in horas if h in demanda_por_hora.index))
        dem = demanda_por_hora.reindex(horas).fillna(0).values
        for H in candidatos:
            pr = predecir(m, dem, H, flota, horas)
            w = dem / dem.sum() if dem.sum() > 0 else np.ones(len(dem)) / len(dem)
            agg = {c: float((pr[c] * w).sum()) for c in Y_COLS}
            agg["ocupacion_p95"] = float(pr.ocupacion_p95.max())
            buses = math.ceil(ciclo / H)
            costo = float((dem * pr.espera_media_min).sum() / 60 * mt["valor_tiempo_usd_h"]
                          * dur_h / max(len(horas), 1)) + cbus * buses * dur_h
            filas.append(dict(franja=nombre, intervalo_min=H, demanda_h=float(dem.mean()), buses=buses,
                              factible=bool(buses <= (flota or 999) and agg["no_atendidos_pct"] <= 1.0
                                            and agg["ocupacion_p95"] <= 1.0),
                              cumple_los=bool(agg["espera_media_min"] <= mt["espera_objetivo_min"]
                                              and agg["ocupacion_p95"] <= mt["ocupacion_objetivo"]),
                              costo_usd=round(costo, 1), **{k: round(v, 3) for k, v in agg.items()}))
    ev = pd.DataFrame(filas)
    plan = {}
    for nombre, g in ev.groupby("franja", sort=False):
        ok = g[g.factible]
        if criterio == "servicio" and ok.cumple_los.any():
            elegido = ok[ok.cumple_los].intervalo_min.max()
        elif criterio == "servicio" and len(ok):
            # ningún intervalo cumple el nivel de servicio: el que da menor espera (y entre
            # empates el más largo) en lugar de ahorrar buses
            m_ = ok.espera_media_min.min()
            elegido = ok[ok.espera_media_min <= m_ * 1.02].intervalo_min.max()
        elif len(ok):
            elegido = ok.loc[ok.costo_usd.idxmin(), "intervalo_min"]
        else:   # nada factible: el intervalo más corto que permite la flota
            dentro = g[g.buses <= (flota or 999)]
            elegido = dentro.intervalo_min.min() if len(dentro) else g.intervalo_min.max()
        plan[nombre] = float(elegido)
    ev["elegido"] = ev.apply(lambda r: plan[r.franja] == r.intervalo_min, axis=1)
    return plan, ev
