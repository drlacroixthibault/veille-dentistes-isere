#!/usr/bin/env python3
"""
Télécharge une fois (puis chaque mois) les grands axes routiers, les rivières et les
noms de communes autour de Grenoble depuis OpenStreetMap (API Overpass, © contributeurs
OpenStreetMap, licence ODbL), les simplifie et écrit docs/data/routes.json, lu par la
page privée « Mon réseau de confrères » pour habiller sa carte.
"""
import json
import os
import time
import urllib.parse
import urllib.request

BBOX = (44.75, 4.75, 45.95, 6.45)  # sud, ouest, nord, est
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
SORTIE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "data", "routes.json")

REQ = """[out:json][timeout:600];
(
  way["highway"~"^(motorway|trunk|primary|secondary)$"]({b});
  way["waterway"="river"]["name"~"Isère|Drac|Romanche|Rhône|Bourne|Guiers|Bréda"]({b});
  node["place"~"^(city|town|village)$"]({b});
);
out geom;""".format(b=",".join(map(str, BBOX)))


def appeler():
    data = urllib.parse.urlencode({"data": REQ}).encode()
    for essai in range(3):
        for url in OVERPASS:
            try:
                req = urllib.request.Request(url, data=data, headers={"User-Agent": "veille-dentistes-isere/1.0"})
                with urllib.request.urlopen(req, timeout=700) as r:
                    return json.load(r)
            except Exception as e:
                print(f"{url} : {e}")
                time.sleep(20 * (essai + 1))
    raise SystemExit("Overpass injoignable")


def rdp(pts, eps):
    """Simplification Douglas-Peucker (en degrés)."""
    if len(pts) < 3:
        return pts
    (ax, ay), (bx, by) = pts[0], pts[-1]
    dx, dy = bx - ax, by - ay
    n = (dx * dx + dy * dy) ** 0.5 or 1e-12
    dmax, idx = 0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        d = abs(dy * px - dx * py + bx * ay - by * ax) / n
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        return rdp(pts[: idx + 1], eps)[:-1] + rdp(pts[idx:], eps)
    return [pts[0], pts[-1]]


def main():
    d = appeler()
    roads, rivers, places = [], [], []
    eps = {"motorway": 0.0004, "trunk": 0.0004, "primary": 0.0005, "secondary": 0.0006}
    rang = {"city": 0, "town": 1, "village": 2}
    for el in d.get("elements", []):
        t = el.get("tags", {})
        if el["type"] == "node":
            if t.get("name"):
                places.append([t["name"], round(el["lat"], 4), round(el["lon"], 4), rang.get(t.get("place"), 2)])
            continue
        g = [(p["lat"], p["lon"]) for p in el.get("geometry") or []]
        if len(g) < 2:
            continue
        if "highway" in t:
            c = t["highway"]
            pts = rdp(g, eps.get(c, 0.0006))
            roads.append([c, [[round(a, 4), round(b, 4)] for a, b in pts]])
        elif "waterway" in t:
            pts = rdp(g, 0.0004)
            rivers.append([[round(a, 4), round(b, 4)] for a, b in pts])
    ordre = {"secondary": 0, "primary": 1, "trunk": 2, "motorway": 3}
    roads.sort(key=lambda r: ordre.get(r[0], 0))
    os.makedirs(os.path.dirname(SORTIE), exist_ok=True)
    with open(SORTIE, "w", encoding="utf-8") as f:
        json.dump({"source": "© contributeurs OpenStreetMap (ODbL)", "roads": roads, "rivers": rivers, "places": places},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(roads)} routes, {len(rivers)} rivières, {len(places)} lieux — {os.path.getsize(SORTIE)//1024} Ko")


if __name__ == "__main__":
    main()
