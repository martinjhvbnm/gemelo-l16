"""Utilidades comunes: configuración, rutas y acceso a las herramientas de SUMO."""
import copy
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CFG_DEFAULT = ROOT / "config" / "default.yaml"
CFG_ESCENARIO = ROOT / "config" / "escenario.yaml"

# Herramientas de SUMO (traci, sumolib)
if "SUMO_HOME" in os.environ:
    sys.path.append(os.path.join(os.environ["SUMO_HOME"], "tools"))


def _merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def cargar_config(extra=None, archivo=None):
    """default.yaml  <-  escenario.yaml (si existe)  <-  archivo  <-  extra (dict)."""
    with open(CFG_DEFAULT, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for ruta in (CFG_ESCENARIO, archivo):
        if ruta and Path(ruta).exists():
            with open(ruta, encoding="utf-8") as f:
                cfg = _merge(cfg, yaml.safe_load(f) or {})
    if extra:
        cfg = _merge(cfg, extra)
    return cfg


def guardar_escenario(cfg):
    with open(CFG_ESCENARIO, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def p(cfg, clave):
    """Ruta absoluta de cfg['rutas'][clave]."""
    r = Path(cfg["rutas"][clave])
    return r if r.is_absolute() else ROOT / r


def hhmm(s):
    h, m = str(s).split(":")[:2]
    return int(h) * 3600 + int(m) * 60


def fmt_hora(t):
    t = int(t)
    return f"{t // 3600:02d}:{(t % 3600) // 60:02d}"


def edge_de_lane(lane_id):
    return lane_id.rsplit("_", 1)[0]


# ---------------------------------------------------------------- franjas
def franjas(cfg):
    """Lista de (nombre, t_ini, t_fin) en segundos."""
    return [(f["nombre"], hhmm(f["desde"]), hhmm(f["hasta"])) for f in cfg["franjas"]]


def franja_de(t, cfg):
    for n, a, b in franjas(cfg):
        if a <= t < b:
            return n
    return "fuera"


def nombres_franja(cfg):
    out = []
    for f in cfg["franjas"]:
        if f["nombre"] not in out:
            out.append(f["nombre"])
    return out
