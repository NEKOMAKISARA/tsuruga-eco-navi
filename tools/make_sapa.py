"""全国のSA・PA（OpenStreetMap の highway=services / rest_area）と、その中の施設を取り出して sapa.json にする。

使い方:  python tools/make_sapa.py <japan-latest.osm.pbf> [出力先 sapa.json]
  日本全体のデータは https://download.geofabrik.de/asia/japan-latest.osm.pbf （約2.5GB）
  Windowsでは、日本語を含むパスの .pbf は開けない（osmium）。.pbf のあるフォルダに移って相対パスで渡す

ページは実行時に Overpass へ聞かず、このファイルを読む（Overpass は混むと504で全滅するため）。
1回目の読み込みでSA・PAの範囲を集め、2回目でその範囲の中にある施設（トイレ・駐車場・給油・EV充電・
食事・店・建物）を拾う。

出力の形（座標はすべて 1e-5 度の整数。範囲の線・施設の位置はSAの中心からの差）:
  {"v": "YYYY-MM-DD", "s": [[名前, 種類(0=SA/services 1=PA/rest_area), 緯度, 経度, 範囲の線, 施設の並び], ...]}
  範囲の線: [dlat, dlon, dlat, dlon, ...]（無い時は []、点だけのSA）
  施設: [記号, dlat, dlon, 名前, 形, 付加]
    記号  t=トイレ p=駐車場 h=大型車の駐車場 m=二輪の駐車場 f=給油 e=EV充電 r=食事 s=店 b=建物 i=案内所
    形    建物・駐車場の外形 [dlat, dlon, ...]（点の時は 0）
    付加  給油=ブランド、駐車場=台数 など（無い時は ""）
"""
import json
import sys
import datetime

import osmium
import shapely
import shapely.prepared
from shapely import wkb
from shapely.geometry import Point

PBF = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "sapa.json"
CELL = 0.02  # 範囲を探すための格子（度）
NODE_R = 0.0018  # 点だけのSAは半径約200mを範囲とみなす
BUF = 0.00015  # 範囲の線の外側も約15mまでは中とみなす（描き方の誤差）

SA_TAGS = osmium.filter.TagFilter(("highway", "services"), ("highway", "rest_area"))
wkbf = osmium.geom.WKBFactory()


def geom_of(o):
    """area / node から shapely の形"""
    if isinstance(o, osmium.osm.Node):
        return Point(o.location.lon, o.location.lat)
    return wkb.loads(wkbf.create_multipolygon(o), hex=True)


# ---- 1回目：SA・PAの範囲 ----
sas = []  # {name, ty, geom(緯度経度でなく lon,lat), id}
for o in osmium.FileProcessor(PBF).with_locations().with_areas(SA_TAGS).with_filter(SA_TAGS):
    if isinstance(o, osmium.osm.Way) or isinstance(o, osmium.osm.Relation):
        continue  # 形は area として来る
    if isinstance(o, osmium.osm.Node) and not o.location.valid():
        continue
    try:
        g = geom_of(o)
    except Exception:
        continue
    if g.is_empty:
        continue
    t = o.tags
    sas.append({
        "name": t.get("name", ""),
        "ty": 0 if t.get("highway") == "services" else 1,
        "node": isinstance(o, osmium.osm.Node),
        "g": g,
    })
print("SA・PA", len(sas), "か所", file=sys.stderr)

# 点だけのSAが、形のあるSAの中にあるなら重複なので捨てる
polys = [s for s in sas if not s["node"]]
ptree = shapely.STRtree([s["g"] for s in polys])
keep = []
for s in sas:
    if s["node"] and len(ptree.query(s["g"], predicate="intersects")):
        continue
    keep.append(s)
sas = keep
for s in sas:
    s["area"] = s["g"].buffer(NODE_R if s["node"] else BUF)
    s["prep"] = shapely.prepared.prep(s["area"])
    s["fac"] = []
    c = s["g"].representative_point() if not s["node"] else s["g"]
    s["c"] = (c.y, c.x)

# 格子：セル → SAの番号
grid = {}
for i, s in enumerate(sas):
    x0, y0, x1, y1 = s["area"].bounds
    for gx in range(int(x0 // CELL), int(x1 // CELL) + 1):
        for gy in range(int(y0 // CELL), int(y1 // CELL) + 1):
            grid.setdefault((gx, gy), []).append(i)


def near(lon, lat):
    return grid.get((int(lon // CELL), int(lat // CELL)), ())


def kind(t):
    a = t.get("amenity", "")
    if a == "toilets" or t.get("toilets") == "yes" and t.get("building"):
        return "t"
    if a in ("parking", "parking_space"):
        if a == "parking_space":
            return None
        if t.get("hgv") in ("designated", "only") or "大型" in t.get("name", ""):
            return "h"
        return "p"
    if a == "motorcycle_parking":
        return "m"
    if a == "fuel":
        return "f"
    if a == "charging_station":
        return "e"
    if a in ("restaurant", "fast_food", "food_court", "cafe", "ice_cream"):
        return "r"
    if t.get("tourism") == "information" and t.get("information") == "office":
        return "i"
    if t.get("shop"):
        return "s"
    if t.get("building"):
        return "b"
    return None


FAC_TAGS = osmium.filter.KeyFilter("amenity", "shop", "building", "tourism")

# ---- 2回目：範囲の中の施設 ----
n = 0
for o in osmium.FileProcessor(PBF).with_locations().with_areas(FAC_TAGS).with_filter(FAC_TAGS):
    n += 1
    if n % 5_000_000 == 0:
        print(n, file=sys.stderr)
    if isinstance(o, osmium.osm.Way) or isinstance(o, osmium.osm.Relation):
        continue
    t = o.tags
    k = kind(t)
    if not k:
        continue
    # 大まかな位置で先にふるう（全国の建物の形を全部作ると遅いので）
    if isinstance(o, osmium.osm.Node):
        if not o.location.valid():
            continue
        lon, lat = o.location.lon, o.location.lat
    else:
        try:
            ring = next(iter(o.outer_rings()))
            loc = ring[0].location
            lon, lat = loc.lon, loc.lat
        except Exception:
            continue
    cand = near(lon, lat)
    if not cand:
        continue
    try:
        g = geom_of(o)
    except Exception:
        continue
    if g.is_empty:
        continue
    p = g.representative_point()
    for i in cand:
        s = sas[i]
        if not s["prep"].contains(p):
            continue
        if s["g"].equals(g):
            break  # SAそのもの
        name = t.get("name", "")
        extra = ""
        if k == "f":
            extra = t.get("brand", "") or t.get("operator", "")
        elif k in ("p", "h", "m"):
            extra = t.get("capacity", "")
        shape = None
        if k in ("b", "p", "h", "t", "r", "s") and g.geom_type in ("Polygon", "MultiPolygon"):
            gg = g if g.geom_type == "Polygon" else max(g.geoms, key=lambda q: q.area)
            shape = gg.simplify(0.00002).exterior.coords
        s["fac"].append((k, p.y, p.x, name, shape, extra))
        break

print("施設", sum(len(s["fac"]) for s in sas), file=sys.stderr)


# ---- 書き出し ----
def q(v):
    return round(v * 1e5)


def rel(coords, c):
    out = []
    for x, y in coords:
        out += [q(y) - q(c[0]), q(x) - q(c[1])]
    return out


rows = []
for s in sas:
    c = s["c"]
    if s["node"]:
        line = []
    else:
        g = s["g"] if s["g"].geom_type == "Polygon" else max(s["g"].geoms, key=lambda x: x.area)
        line = rel(g.simplify(0.00003).exterior.coords, c)
    fac = []
    for k, la, lo, name, shape, extra in s["fac"]:
        # 名前のない建物で小さいもの（物置など）は省く
        if k == "b" and not name and shape is not None:
            if shapely.Polygon(shape).area < 2.5e-8:  # 約300㎡未満
                continue
        fac.append([k, q(la) - q(c[0]), q(lo) - q(c[1]), name, rel(shape, c) if shape else 0, extra])
    rows.append([s["name"], s["ty"], q(c[0]), q(c[1]), line, fac])
rows.sort(key=lambda r: (r[2], r[3]))
with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"v": datetime.date.today().isoformat(), "s": rows}, f, ensure_ascii=False, separators=(",", ":"))
print("書き出し", OUT, len(rows), "か所", file=sys.stderr)
