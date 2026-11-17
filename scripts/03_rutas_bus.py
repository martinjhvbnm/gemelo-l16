"""Paso 3 – A partir de la salida de gtfs2pt construye:
  * data/l16_rutas.add.xml : vType del bus + rutas L16_ida, L16_vuelta y L16_ciclo (ida+vuelta)
  * data/l16_paradas.csv   : paradas ordenadas por sentido, distancia acumulada y coordenadas.

Uso: python scripts/03_rutas_bus.py [--modo hibrido|paradas|gtfs2pt]
  hibrido (por defecto): en cada tramo entre paradas elige, entre el tramo de gtfs2pt y el camino
           más corto para bus, el que más se acerca a la distancia del GTFS (shape_dist_traveled).
  paradas: siempre el camino más corto entre paradas (puede tomar atajos que el bus no hace).
  gtfs2pt: recorrido tal como lo mapeó gtfs2pt (tracemapper).
"""
import argparse
import io
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

from common import cargar_config, edge_de_lane, p

try:
    import sumolib
except ImportError:
    raise SystemExit("No encuentro sumolib: define SUMO_HOME")


def leer_paradas(add_file):
    paradas = {}
    for bs in ET.parse(add_file).getroot().iter("busStop"):
        paradas[bs.get("id")] = dict(
            stop_id=bs.get("id"), nombre=(bs.get("name") or bs.get("id")).upper(),
            lane=bs.get("lane"), edge=edge_de_lane(bs.get("lane")),
            startPos=float(bs.get("startPos", 0)), endPos=float(bs.get("endPos", 0)))
    return paradas


def candidatos(*archivos):
    root = ET.Element("todo")
    for a in archivos:
        try:
            root.extend(list(ET.parse(a).getroot()))
        except (ET.ParseError, FileNotFoundError):
            pass
    rutas = {}
    for r in root.findall("route"):
        rutas[r.get("id")] = (r.get("edges").split(), [s.get("busStop") for s in r.findall("stop") if s.get("busStop")])
    cands = {}
    for v in root.iter("vehicle"):
        emb = v.find("route")
        if emb is not None:
            edges = emb.get("edges").split()
            stops = [s.get("busStop") for s in emb.findall("stop") if s.get("busStop")]
        elif v.get("route") in rutas:
            edges, stops = rutas[v.get("route")]
        else:
            continue
        stops = stops + [s.get("busStop") for s in v.findall("stop") if s.get("busStop")]
        if stops:
            cands[tuple(edges)] = (edges, stops)
    for edges, stops in rutas.values():
        if stops:
            cands.setdefault(tuple(edges), (edges, stops))
    return sorted(cands.values(), key=lambda x: -len(x[1]))


def ordenar_y_medir(edges, stops, paradas, net):
    cum, acc = [], 0.0
    for e in edges:
        cum.append(acc)
        acc += net.getEdge(e).getLength()
    filas, idx = [], 0
    for s in stops:
        ps = paradas[s]
        try:
            i = edges.index(ps["edge"], idx)
        except ValueError:
            print(f"  aviso: parada {s} ({ps['edge']}) fuera de la ruta, se omite")
            continue
        idx = i
        lane = net.getLane(ps["lane"])
        if ps["endPos"] <= 0:
            ps["endPos"] = lane.getLength() + ps["endPos"]
        x, y = sumolib.geomhelper.positionAtShapeOffset(lane.getShape(), ps["endPos"])
        lon, lat = net.convertXY2LonLat(x, y)
        filas.append({**ps, "dist_m": round(cum[i] + ps["endPos"], 1), "lat": lat, "lon": lon})
    return filas, acc


def camino_corto(pa, pb, net):
    E = net.getEdge
    L = lambda es: sum(E(e).getLength() for e in es)
    a, b = pa["edge"], pb["edge"]
    if a == b and pb["endPos"] >= pa["endPos"]:
        return [a]
    inicios = [x.getID() for x in E(a).getOutgoing()] if a == b else [a]
    mejor = None
    for s in inicios:
        path, _ = net.getShortestPath(E(s), E(b), vClass="bus")
        if path:
            c = ([a] if a == b else []) + [x.getID() for x in path]
            if mejor is None or L(c) < L(mejor):
                mejor = c
    return mejor


def distancias_gtfs(cfg, stops):
    z = zipfile.ZipFile(p(cfg, "gtfs_l16_zip"))
    rd = lambda n: pd.read_csv(io.BytesIO(z.read(n)), dtype=str)
    trips, st = rd("trips.txt"), rd("stop_times.txt")
    mejor, sol = -1, None
    for tid in trips[trips.service_id == "L-V"].trip_id:
        g = st[st.trip_id == tid].assign(q=lambda d: d.stop_sequence.astype(int)).sort_values("q")
        com = len(set(g.stop_id) & set(stops))
        if com > mejor and len(g) == len(stops):
            mejor, sol = com, g.shape_dist_traveled.astype(float).values
    return sol


def reconstruir(edges_orig, stops, paradas, net, d_gtfs=None):
    """d_gtfs=None -> siempre camino corto; con d_gtfs -> híbrido (el más cercano al GTFS)."""
    E = net.getEdge
    L = lambda es: sum(E(e).getLength() for e in es)

    def largo(tr, pa, pb):
        if len(tr) == 1:
            return pb["endPos"] - pa["endPos"]
        return L(tr) - pa["endPos"] - (E(tr[-1]).getLength() - pb["endPos"])

    ruta, idx, n_corto, n_orig = [paradas[stops[0]]["edge"]], 0, 0, 0
    for k, (s1, s2) in enumerate(zip(stops, stops[1:])):
        pa, pb = paradas[s1], paradas[s2]
        i = edges_orig.index(pa["edge"], idx)
        j = edges_orig.index(pb["edge"], i + (1 if pa["edge"] == pb["edge"] and pb["endPos"] < pa["endPos"] else 0))
        idx = j
        t_orig = edges_orig[i:j + 1]
        t_corto = camino_corto(pa, pb, net)
        if d_gtfs is None:
            usar_corto = t_corto is not None
        else:
            obj = d_gtfs[k + 1] - d_gtfs[k]
            usar_corto = t_corto is not None and abs(largo(t_corto, pa, pb) - obj) < abs(largo(t_orig, pa, pb) - obj)
        if usar_corto:
            t, n_corto = t_corto, n_corto + 1
        else:
            t, n_orig = t_orig, n_orig + 1
        ruta += t[1:] if t[0] == ruta[-1] else t
    print(f"    tramos: {n_orig} de gtfs2pt, {n_corto} con camino más corto")
    return ruta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["gtfs", "hibrido", "paradas", "gtfs2pt"], default="gtfs")
    modo = ap.parse_args().modo
    cfg = cargar_config()
    net = sumolib.net.readNet(str(p(cfg, "red")))
    paradas = leer_paradas(p(cfg, "paradas_add"))
    cands = candidatos(p(cfg, "pt_rou"), p(cfg, "paradas_add"))
    if len(cands) < 2:
        raise SystemExit("gtfs2pt no generó dos sentidos con paradas; revisa el paso 2.")

    print("Rutas candidatas encontradas (las 2 con más paradas se usan):")
    for e, s in cands[:4]:
        print(f"  {len(s):3d} paradas  {paradas[s[0]]['nombre']}  →  {paradas[s[-1]]['nombre']}")
    a, b = cands[0], next(c for c in cands[1:] if c[1][0] != cands[0][1][0])
    clave = cfg["linea"]["palabra_inicio_ida"].upper()
    ida, vuelta = (a, b) if clave in paradas[a[1][0]]["nombre"] or clave not in paradas[b[1][0]]["nombre"] else (b, a)

    if modo == "gtfs":
        from mapmatch_gtfs import shape_gtfs, map_matching_gtfs
        nuevas = []
        for nombre, (edges, stops) in (("ida", ida), ("vuelta", vuelta)):
            print(f"  {nombre}:")
            pts, d_st = shape_gtfs(cfg, stops)
            r = map_matching_gtfs(stops, paradas, net, pts, d_st) if pts else edges
            print(f"    gtfs2pt {sum(net.getEdge(e).getLength() for e in edges) / 1000:.2f} km -> "
                  f"gtfs {sum(net.getEdge(e).getLength() for e in r) / 1000:.2f} km")
            nuevas.append((r, stops))
        ida, vuelta = nuevas
        modo = "gtfs2pt"   # ya reconstruido: salta el bloque de los otros modos

    if modo != "gtfs2pt":
        nuevas = []
        for nombre, (edges, stops) in (("ida", ida), ("vuelta", vuelta)):
            d_g = distancias_gtfs(cfg, stops) if modo == "hibrido" else None
            if modo == "hibrido" and d_g is None:
                print(f"  {nombre}: no pude emparejar con el GTFS; uso el recorrido de gtfs2pt")
                nuevas.append((edges, stops))
                continue
            print(f"  {nombre}:")
            r = reconstruir(edges, stops, paradas, net, d_g)
            lo = sum(net.getEdge(e).getLength() for e in edges) / 1000
            ln = sum(net.getEdge(e).getLength() for e in r) / 1000
            print(f"    gtfs2pt {lo:.2f} km -> {modo} {ln:.2f} km")
            nuevas.append((r, stops))
        ida, vuelta = nuevas

    def tramo_intermedio(e1, e2):
        path, _ = net.getShortestPath(net.getEdge(e1), net.getEdge(e2), vClass="bus")
        if path is None:
            raise SystemExit(f"No hay camino para bus entre {e1} y {e2}. Revisa la red.")
        return [x.getID() for x in path[1:-1]]

    fin_ida, ini_vta = ida[0][-1], vuelta[0][0]
    ciclo_edges = ida[0] + vuelta[0][1:] if fin_ida == ini_vta else ida[0] + tramo_intermedio(fin_ida, ini_vta) + vuelta[0]

    filas_i, len_i = ordenar_y_medir(ida[0], ida[1], paradas, net)
    filas_v, len_v = ordenar_y_medir(vuelta[0], vuelta[1], paradas, net)
    df = pd.concat([pd.DataFrame(filas_i).assign(sentido="ida"), pd.DataFrame(filas_v).assign(sentido="vuelta")])
    df["orden"] = df.groupby("sentido").cumcount()
    df.to_csv(p(cfg, "paradas_csv"), index=False)

    b_cfg = cfg["bus"]
    root = ET.Element("additional")
    ET.SubElement(root, "vType", id="bus_l16", vClass="bus", guiShape="bus", length="12",
                  personCapacity=str(b_cfg["capacidad"]), boardingDuration=str(b_cfg["t_abordaje_s"]),
                  maxSpeed=str(b_cfg["vel_max_ms"]), color="174,118,179")
    dur = str(b_cfg["parada_min_s"])
    for rid, edges, filas in (("L16_ida", ida[0], filas_i), ("L16_vuelta", vuelta[0], filas_v),
                              ("L16_ciclo", ciclo_edges, filas_i + filas_v)):
        r = ET.SubElement(root, "route", id=rid, edges=" ".join(edges))
        for f in filas:
            ET.SubElement(r, "stop", busStop=f["stop_id"], duration=dur)
    ET.indent(root)
    ET.ElementTree(root).write(p(cfg, "rutas_bus"), encoding="utf-8", xml_declaration=True)

    ref = {"ida": 20.35, "vuelta": 21.99}
    for nom, fl in (("Ida", filas_i), ("Vuelta", filas_v)):
        km = (fl[-1]["dist_m"] - fl[0]["dist_m"]) / 1000
        g = ref[nom.lower()]
        print(f"{nom:6s}: {len(fl)} paradas, primera→última {km:.2f} km (GTFS {g} km, {100 * (km - g) / g:+.1f} %)")
    print(f"OK -> {p(cfg, 'rutas_bus')} y {p(cfg, 'paradas_csv')}")


if __name__ == "__main__":
    main()
