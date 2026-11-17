"""Map-matching de la ruta del bus guiado por el trazado del GTFS (shapes.txt)."""
import io, math, zipfile
import pandas as pd
from common import p


def shape_gtfs(cfg, stops):
    z = zipfile.ZipFile(p(cfg, "gtfs_l16_zip"))
    rd = lambda n: pd.read_csv(io.BytesIO(z.read(n)), dtype=str)
    trips, st, sh = rd("trips.txt"), rd("stop_times.txt"), rd("shapes.txt")
    mejor = None
    for _, t in trips[trips.service_id == "L-V"].iterrows():
        g = st[st.trip_id == t.trip_id].assign(q=lambda d: d.stop_sequence.astype(int)).sort_values("q")
        com = len(set(g.stop_id) & set(stops))
        if len(g) == len(stops) and (mejor is None or com > mejor[0]):
            mejor = (com, t.shape_id, g.shape_dist_traveled.astype(float).values)
    if mejor is None:
        return None, None
    s = sh[sh.shape_id == mejor[1]].assign(q=lambda d: d.shape_pt_sequence.astype(int)).sort_values("q")
    pts = list(zip(s.shape_pt_lon.astype(float), s.shape_pt_lat.astype(float), s.shape_dist_traveled.astype(float)))
    return pts, mejor[2]


def _angulo_edge(edge, x, y):
    shp = edge.getShape()
    mejor, ang = 1e18, 0.0
    for (x1, y1), (x2, y2) in zip(shp[:-1], shp[1:]):
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy or 1e-9
        u = max(0, min(1, ((x - x1) * dx + (y - y1) * dy) / L2))
        d = (x1 + u * dx - x) ** 2 + (y1 + u * dy - y) ** 2
        if d < mejor:
            mejor, ang = d, math.atan2(dy, dx)
    return ang


def map_matching_gtfs(stops, paradas, net, pts, d_stops, paso=80.0, radio=35.0):
    E = net.getEdge
    xy = [net.convertLonLat2XY(lo, la) for lo, la, _ in pts]
    dist = [d for _, _, d in pts]
    wps, prox = [], 0.0
    for k in range(len(xy) - 1):
        if dist[k] < prox:
            continue
        prox = dist[k] + paso
        (x, y), (x2, y2) = xy[k], xy[k + 1]
        rumbo = math.atan2(y2 - y, x2 - x)
        cand = []
        for e, dd in net.getNeighboringEdges(x, y, radio):
            if not e.allows("bus"):
                continue
            dif = abs((_angulo_edge(e, x, y) - rumbo + math.pi) % (2 * math.pi) - math.pi)
            if dif < math.radians(45):
                cand.append((dd + 20 * dif, e.getID()))
        if cand:
            wps.append((dist[k], 1, min(cand)[1]))
    for s, d in zip(stops, d_stops):
        wps.append((d, 0, paradas[s]["edge"]))
    wps = sorted(w for w in wps if d_stops[0] <= w[0] <= d_stops[-1])
    ruta, descartes, d_ant = [wps[0][2]], 0, wps[0][0]
    for d, tipo, e in wps[1:]:
        if e == ruta[-1]:
            d_ant = d
            continue
        path, _ = net.getShortestPath(E(ruta[-1]), E(e), vClass="bus")
        if path is None:
            descartes += 1
            continue
        largo = sum(x.getLength() for x in path[1:-1])
        if tipo == 1 and largo > 3 * (d - d_ant) + 300:
            descartes += 1
            continue
        ruta += [x.getID() for x in path[1:]]
        d_ant = d
    print(f"    {len(wps)} waypoints ({len(stops)} paradas), {descartes} descartados")
    return ruta
