"""スキー場ごとのコースマップ用データ（OpenStreetMap のコース piste:type=downhill とリフト aerialway）を作る。

使い方:  cd <japan-latest.osm.pbf のフォルダ>  &&  python <このファイル> japan-latest.osm.pbf <ski.json> <出力フォルダ ski_course>
  （osmium は日本語を含むパスの .pbf を開けないので、.pbf のフォルダで相対パスで渡す）
出力: ski_course/<緯度1e5>_<経度1e5>.json（ski.json の各スキー場の2・3番目の値）
  {"p": [[難しさ, 名前, 閉じた面か, [dlat, dlon, ...]], ...], "l": [[種類, 名前, [dlat, dlon, ...]], ...]}
  座標は 1e-5 度の整数で、スキー場の中心からの差。難しさ: g=初級 r=中級 b=上級 f=非圧雪/フリーライド ""=不明
"""
import json, os, sys
import osmium, shapely
from shapely.geometry import LineString, Point, Polygon

PBF, SKIJ, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUT, exist_ok=True)
LIFTS = {"chair_lift", "gondola", "cable_car", "mixed_lift", "drag_lift", "t-bar", "j-bar", "platter", "rope_tow", "magic_carpet"}
DIFF = {"novice": "g", "easy": "g", "intermediate": "r", "advanced": "b", "expert": "b", "extreme": "b", "freeride": "f"}

ski = json.load(open(SKIJ, encoding="utf-8"))["s"]
geoms = []
for r in ski:
    c = (r[1] / 1e5, r[2] / 1e5); a = r[3]
    pts = [(c[1] + a[i + 1] / 1e5, c[0] + a[i] / 1e5) for i in range(0, len(a) - 1, 2)]
    g = Polygon(pts) if len(pts) >= 3 else Point(c[1], c[0])
    if not g.is_valid: g = g.buffer(0)
    geoms.append(g.buffer(0.004))   # 範囲から約400mまで
tree = shapely.STRtree(geoms)

def owner(line):
    mid = line.interpolate(0.5, normalized=True)
    hits = [i for i in tree.query(mid) if geoms[i].contains(mid)]
    if not hits: return None
    return min(hits, key=lambda i: Point(ski[i][2] / 1e5, ski[i][1] / 1e5).distance(mid))

data = {}
F = osmium.filter.KeyFilter("piste:type", "aerialway")
n = 0
for o in osmium.FileProcessor(PBF, osmium.osm.NODE | osmium.osm.WAY).with_locations().with_filter(F):
    if not isinstance(o, osmium.osm.Way): continue
    t = o.tags
    pt, aw = t.get("piste:type"), t.get("aerialway")
    if pt != "downhill" and aw not in LIFTS: continue
    try: pts = [(nd.location.lon, nd.location.lat) for nd in o.nodes]
    except Exception: continue
    if len(pts) < 2: continue
    line = LineString(pts)
    k = owner(line)
    if k is None: continue
    s = line.simplify(0.00004)   # 約4m
    r = ski[k]; c = (r[1] / 1e5, r[2] / 1e5)
    flat = []
    for lon, lat in s.coords: flat += [round((lat - c[0]) * 1e5), round((lon - c[1]) * 1e5)]
    name = t.get("piste:name") or t.get("name:ja") or t.get("name") or ""
    d = data.setdefault(k, {"p": [], "l": []})
    if pt == "downhill":
        closed = pts[0] == pts[-1] and t.get("area") == "yes"
        d["p"].append([DIFF.get(t.get("piste:difficulty", ""), ""), name, 1 if closed else 0, flat])
    else:
        d["l"].append([aw, name, flat])
    n += 1
    if n % 2000 == 0: print(n, file=sys.stderr, flush=True)
tot = 0
for k, d in data.items():
    r = ski[k]
    p = os.path.join(OUT, f"{r[1]}_{r[2]}.json")
    s = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    open(p, "w", encoding="utf-8").write(s); tot += len(s)
print("files", len(data), "コースあり", sum(1 for d in data.values() if d["p"]), "合計", tot // 1024, "KB", file=sys.stderr)
