"""全国のスキー場（OpenStreetMap の landuse=winter_sports）と、その中のリフトの両端を取り出して ski.json にする。

使い方:  python tools/make_ski.py <japan-latest.osm.pbf> [出力先 ski.json]
  Windowsでは、日本語を含むパスの .pbf は開けない（osmium）。.pbf のあるフォルダに移って相対パスで渡す

ナビは目的地がスキー場の範囲（の近く）にある時に「ゲレンデ情報」を出す。山頂・山麓の高さはリフトの両端の標高
（ナビが Open-Meteo の標高データで調べる）の一番高い所・低い所。

出力の形（座標は 1e-5 度の整数。範囲の線・リフトの端は中心からの差）:
  {"v": "YYYY-MM-DD", "s": [[名前, 緯度, 経度, 範囲の線 [dlat, dlon, ...], リフトの端 [dlat, dlon, ...]], ...]}
"""
import json
import sys
import datetime

import osmium
import shapely
from shapely import wkb
from shapely.geometry import Point

PBF = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "ski.json"
LIFTS = {"chair_lift", "gondola", "cable_car", "mixed_lift", "drag_lift", "t-bar", "j-bar", "platter", "rope_tow"}

wkbf = osmium.geom.WKBFactory()
SKI = osmium.filter.TagFilter(("landuse", "winter_sports"))

# ---- 1回目：スキー場の範囲 ----
areas = []
for o in osmium.FileProcessor(PBF).with_locations().with_areas(SKI).with_filter(SKI):
    if not isinstance(o, osmium.osm.Area):
        continue
    try:
        g = wkb.loads(wkbf.create_multipolygon(o), hex=True)
    except Exception:
        continue
    if g.is_empty or g.area < 1e-6:
        continue
    t = o.tags
    areas.append({"name": t.get("name:ja") or t.get("name") or "", "g": g})
print("areas", len(areas), file=sys.stderr)

# ---- 2回目：リフトの両端 ----
ends = []
AER = osmium.filter.KeyFilter("aerialway")
for o in osmium.FileProcessor(PBF, osmium.osm.NODE | osmium.osm.WAY).with_locations().with_filter(AER):
    if not isinstance(o, osmium.osm.Way) or o.tags.get("aerialway") not in LIFTS:
        continue
    try:
        a, b = o.nodes[0].location, o.nodes[-1].location
        ends.append(((a.lat, a.lon), (b.lat, b.lon), o.tags.get("name", "")))
    except Exception:
        continue
print("lifts", len(ends), file=sys.stderr)

tree = shapely.STRtree([x["g"] for x in areas])
for x in areas:
    x["lifts"] = []
for a, b, _ in ends:
    mid = Point((a[1] + b[1]) / 2, (a[0] + b[0]) / 2)
    hits = tree.query(mid.buffer(0.003))  # 範囲から約300mまで
    if len(hits) == 0:
        continue
    k = min(hits, key=lambda i: areas[i]["g"].distance(mid))
    areas[k]["lifts"] += [a, b]

out = []
for x in areas:
    g = x["g"]
    if not x["name"] and not x["lifts"]:
        continue  # 名前もリフトも無い（そり遊び場など）
    c = g.representative_point()
    clat, clon = c.y, c.x
    poly = max(getattr(g, "geoms", [g]), key=lambda p: p.area).simplify(0.0004)
    line = []
    for lon, lat in list(poly.exterior.coords)[:-1]:
        line += [round((lat - clat) * 1e5), round((lon - clon) * 1e5)]
    lf = []
    for lat, lon in x["lifts"][:60]:
        lf += [round((lat - clat) * 1e5), round((lon - clon) * 1e5)]
    out.append([x["name"], round(clat * 1e5), round(clon * 1e5), line, lf])

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"v": datetime.date.today().isoformat(), "s": out}, f, ensure_ascii=False, separators=(",", ":"))
print("written", len(out), file=sys.stderr)
