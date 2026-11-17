"""スキー場ごとのコースマップ用データ（OpenStreetMap のコース piste:type=downhill とリフト aerialway）を作る。

使い方:  cd <japan-latest.osm.pbf のフォルダ>  &&  python <このファイル> japan-latest.osm.pbf <ski.json> <出力フォルダ ski_course>
  （osmium は日本語を含むパスの .pbf を開けないので、.pbf のフォルダで相対パスで渡す）
出力: ski_course/<緯度1e5>_<経度1e5>.json（ski.json の各スキー場の2・3番目の値）
  {"p": [[難しさ, 名前, 閉じた面か, [dlat, dlon, ...]], ...], "l": [[種類, 名前, [dlat, dlon, ...]], ...], "f": [[施設, 名前, dlat, dlon], ...]}
  施設: P=駐車場 H=センターハウス等
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

FAC_RE = __import__("re").compile("センター|ハウス|ベース|ヒュッテ|レストハウス|休憩所")
INN_RE = __import__("re").compile("ホテル|ゲストハウス|ペンション|民宿|旅館|ロッジ|ハウス.*[0-9０-９]号|コテージ|山荘|宿")   # 宿は除く
def fac_kind(t):
    a, sh = t.get("amenity"), t.get("shop")
    nm = t.get("name:ja") or t.get("name") or ""
    if a == "parking" and t.get("access") not in ("private", "no") and t.get("parking") != "underground": return "P"
    if nm and FAC_RE.search(nm) and not INN_RE.search(nm) and t.get("tourism") not in ("hotel", "guest_house", "hostel", "motel", "apartment", "chalet")             and (t.get("building") or a in ("restaurant", "cafe", "food_court", "shelter", "information") or t.get("tourism") == "information"): return "H"
    return None   # 食事・ショップは印が多すぎて見づらいので出さない

def owner(line):
    mid = line.interpolate(0.5, normalized=True)
    hits = [i for i in tree.query(mid) if geoms[i].contains(mid)]
    if not hits: return None
    return min(hits, key=lambda i: Point(ski[i][2] / 1e5, ski[i][1] / 1e5).distance(mid))

data = {}
F = osmium.filter.KeyFilter("piste:type", "aerialway", "amenity", "shop", "name")
fgeoms = [g.buffer(0.004) for g in geoms]   # 駐車場は範囲から少し離れていることがあるので広め（約800m）
ftree = shapely.STRtree(fgeoms)
fseen = {}
n = 0
for o in osmium.FileProcessor(PBF, osmium.osm.NODE | osmium.osm.WAY).with_locations().with_filter(F):
    t = o.tags
    fk = fac_kind(t)
    if fk:
        try:
            if isinstance(o, osmium.osm.Way):
                ll = [(nd.location.lon, nd.location.lat) for nd in o.nodes]
                pt = Point(sum(x for x, _ in ll) / len(ll), sum(y for _, y in ll) / len(ll))
            else:
                pt = Point(o.location.lon, o.location.lat)
        except Exception:
            pt = None
        if pt is not None:
            hits = [i for i in ftree.query(pt) if fgeoms[i].contains(pt)]
            if hits:
                k = min(hits, key=lambda i: Point(ski[i][2] / 1e5, ski[i][1] / 1e5).distance(pt))
                r = ski[k]; c = (r[1] / 1e5, r[2] / 1e5)
                nm = t.get("name:ja") or t.get("name") or ""
                key = (k, fk, nm, round(pt.y, 3), round(pt.x, 3))
                if key not in fseen:
                    fseen[key] = 1
                    data.setdefault(k, {"p": [], "l": []}).setdefault("f", []).append([fk, nm, round((pt.y - c[0]) * 1e5), round((pt.x - c[1]) * 1e5)])
    if not isinstance(o, osmium.osm.Way): continue
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
print("files", len(data), "コースあり", sum(1 for d in data.values() if d["p"]), "施設あり", sum(1 for d in data.values() if d.get("f")), "合計", tot // 1024, "KB", file=sys.stderr)
