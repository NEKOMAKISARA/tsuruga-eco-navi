"""全国の高速道路のIC（降り口・乗り口）を OpenStreetMap から取り出して ic.json にする。

使い方:  python tools/make_ic.py <japan-latest.osm.pbf> [出力先 ic.json]
  Windowsでは、日本語を含むパスの .pbf は開けない（osmium）。.pbf のあるフォルダに移って相対パスで渡す

ナビの「乗るIC・降りるICを変える」で使う。選んだICを必ず使うように、そのICのランプ（出入りの道）の上に
経由地を置いて経路を探し直すので、ICごと・向きごとに「ランプの上の点」と「本線の向き」を持つ。

  降り口: 本線の分かれ口（highway=motorway_junction、名前がIC・スマートIC）から出ていくランプの約150m先
  乗り口: 一般道から来て本線に合流するランプの、合流の約150m手前
          （ランプをさかのぼって本線から来ている物＝JCT・SA・PAから戻る道は除く）。名前は近くの同じ道路の降り口から

出力の形（座標は 1e-5 度の整数）:
  {"v": "YYYY-MM-DD", "x": [[名前, 道路, 種類(0=降り口 1=乗り口), 本線の点の緯度, 経度, ランプの点の緯度, 経度, ランプの向き, 本線の向き, スマートIC(0/1)], ...]}
  本線の点: 降り口は分かれ口、乗り口は合流点。向きは北から時計回りの度
"""
import json
import math
import re
import sys
import datetime

import osmium

PBF = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "ic.json"
VIA_M = 150  # ランプの上の点：本線から何m

IC_RE = re.compile(r"(IC|ＩＣ|インター|ｲﾝﾀｰ|スマート)")
NOT_RE = re.compile(r"(JCT|ＪＣＴ|ジャンクション|SA|ＳＡ|PA|ＰＡ|サービスエリア|パーキングエリア|料金所|TB|ランプ)")


def dist_m(a, b):
    r = math.pi / 180
    x = (b[1] - a[1]) * r * math.cos((a[0] + b[0]) / 2 * r)
    y = (b[0] - a[0]) * r
    return math.hypot(x, y) * 6371000


def bearing(a, b):
    r = math.pi / 180
    y = math.sin((b[1] - a[1]) * r) * math.cos(b[0] * r)
    x = math.cos(a[0] * r) * math.sin(b[0] * r) - math.sin(a[0] * r) * math.cos(b[0] * r) * math.cos((b[1] - a[1]) * r)
    return (math.atan2(y, x) / r + 360) % 360


def along(pts, m):
    """点の並びの先頭から m メートル進んだ点と、その所の向き"""
    acc = 0.0
    for i in range(1, len(pts)):
        d = dist_m(pts[i - 1], pts[i])
        if acc + d >= m and d > 0:
            t = (m - acc) / d
            p = (pts[i - 1][0] + t * (pts[i][0] - pts[i - 1][0]), pts[i - 1][1] + t * (pts[i][1] - pts[i - 1][1]))
            return p, bearing(pts[i - 1], pts[i])
        acc += d
    if len(pts) >= 2:
        return pts[-1], bearing(pts[-2], pts[-1])
    return None, None


SMART_RE = re.compile(r"スマート|ｽﾏｰﾄ|SIC")


def clean_name(nm):
    """名前をそろえる：「八王子 (第１出口)」→「八王子」、「三芳PA(下り),スマートIC」→「三芳スマートIC」。使わない名前（JCT・SA・PA）は "" """
    nm = nm.replace("ＩＣ", "IC").replace("I.C", "IC").replace("Ｉ.Ｃ", "IC").strip()
    if not nm:
        return ""
    if SMART_RE.search(nm):
        base = re.split(r"[\s　]*(?:PA|SA|ＰＡ|ＳＡ|パーキングエリア|サービスエリア|スマート|ｽﾏｰﾄ|SIC|[(（,;、・/])", nm)[0].strip()
        return base + "スマートIC" if base else ""
    nm = re.sub(r"[\s　]*[（(].*?[)）]", "", nm).strip()
    if NOT_RE.search(nm):
        return ""
    nm = re.sub(r"(出入口|出口|入口)$", "", nm).strip()
    nm = re.sub(r"(インターチェンジ|インター)$", "IC", nm)
    return nm if not nm or nm.endswith("IC") else nm + "IC"  # 「八王子」と「八王子IC」を同じに（都市高速の出入口はナビ側で IC を外す）


# ---- 1回目：分かれ口の点（名前・番号） ----
JN = {}  # id -> {name, ref, loc}
for o in osmium.FileProcessor(PBF, osmium.osm.NODE).with_filter(osmium.filter.TagFilter(("highway", "motorway_junction"))):
    nm = clean_name(o.tags.get("name:ja") or o.tags.get("name") or "")
    if not nm:
        continue
    JN[o.id] = {"name": nm, "loc": (o.location.lat, o.location.lon)}
print("junctions", len(JN), file=sys.stderr)

# ---- 2回目：ランプ（motorway_link）の形 ----
LINKS = []  # (ids, pts)
by_start = {}  # 最初の点の id -> [ランプの番号]
by_end = {}
LINK_TAGS = osmium.filter.TagFilter(("highway", "motorway_link"))
for o in osmium.FileProcessor(PBF, osmium.osm.NODE | osmium.osm.WAY).with_locations().with_filter(LINK_TAGS):
    if not isinstance(o, osmium.osm.Way):
        continue
    ids, pts = [], []
    try:
        for n in o.nodes:
            ids.append(n.ref)
            pts.append((n.location.lat, n.location.lon))
    except Exception:
        continue
    if len(ids) < 2:
        continue
    if o.tags.get("oneway") == "-1":
        ids.reverse()
        pts.reverse()
    k = len(LINKS)
    LINKS.append((ids, pts))
    by_start.setdefault(ids[0], []).append(k)
    by_end.setdefault(ids[-1], []).append(k)
print("links", len(LINKS), file=sys.stderr)

# ---- 3回目：本線（motorway）：分かれ口・ランプの端が本線のどこにあるか、その所の本線の向きと道路名 ----
watch = set(JN) | set(by_start) | set(by_end)
ON = {}  # id -> (道路, 本線の向き)
MW_TAGS = osmium.filter.TagFilter(("highway", "motorway"))
for o in osmium.FileProcessor(PBF, osmium.osm.NODE | osmium.osm.WAY).with_locations().with_filter(MW_TAGS):
    if not isinstance(o, osmium.osm.Way):
        continue
    try:
        ns = [(n.ref, (n.location.lat, n.location.lon)) for n in o.nodes]
    except Exception:
        continue
    if len(ns) < 2:
        continue
    if o.tags.get("oneway") == "-1":
        ns.reverse()
    road = o.tags.get("name") or o.tags.get("ref") or ""
    road = re.sub(r"[（(].*?[)）]", "", road).strip()
    for i, (nid, p) in enumerate(ns):
        if nid not in watch:
            continue
        a = ns[max(0, i - 1)][1]
        b = ns[min(len(ns) - 1, i + 1)][1]
        if a == b:
            continue
        if nid not in ON or (road and not ON[nid][0]):
            ON[nid] = (road, bearing(a, b))
print("on motorway", len(ON), file=sys.stderr)


def chain_fwd(k, limit=VIA_M + 50):
    """ランプを先へたどって点の並びにする（つながる次のランプが1本だけの間）"""
    ids, pts = LINKS[k]
    pts = list(pts)
    seen = {k}
    while sum(dist_m(pts[i - 1], pts[i]) for i in range(1, len(pts))) < limit:
        nx = [j for j in by_start.get(LINKS[k][0][-1], []) if j not in seen]
        if len(nx) != 1:
            break
        k = nx[0]
        seen.add(k)
        pts += LINKS[k][1][1:]
    return pts


def chain_back(k, limit=VIA_M + 50):
    ids, pts = LINKS[k]
    pts = list(pts)
    seen = {k}
    while sum(dist_m(pts[i - 1], pts[i]) for i in range(1, len(pts))) < limit:
        pv = [j for j in by_end.get(LINKS[k][0][0], []) if j not in seen]
        if len(pv) != 1:
            break
        k = pv[0]
        seen.add(k)
        pts = LINKS[k][1][:-1] + pts
    return pts


def from_motorway(k, depth=12):
    """このランプをさかのぼると本線から来ているか（JCT・SA・PAから戻る道）"""
    todo, seen = [k], set()
    while todo and depth > 0:
        depth -= 1
        k = todo.pop()
        if k in seen:
            continue
        seen.add(k)
        s = LINKS[k][0][0]
        if s in ON:
            return True
        todo += by_end.get(s, [])
    return False


def to_motorway(k, depth=12):
    """このランプを先へたどると本線に入るか（JCT）"""
    todo, seen = [k], set()
    while todo and depth > 0:
        depth -= 1
        k = todo.pop()
        if k in seen:
            continue
        seen.add(k)
        e = LINKS[k][0][-1]
        if e in ON:
            return True
        todo += by_start.get(e, [])
    return False


out = []
smart = lambda n: 1 if SMART_RE.search(n) else 0
# 降り口
exits = []
for jid, j in JN.items():
    nm = j["name"]
    if jid not in ON:
        continue
    road, mb = ON[jid]
    for k in by_start.get(jid, []):
        if to_motorway(k):
            continue  # JCTへ行くランプ
        pts = chain_fwd(k)
        p, h = along(pts, VIA_M)
        if p is None:
            continue
        exits.append((nm, road, j["loc"], p, h, mb))
        out.append([nm, road, 0, round(j["loc"][0] * 1e5), round(j["loc"][1] * 1e5), round(p[0] * 1e5), round(p[1] * 1e5), round(h), round(mb), smart(nm)])
print("exits", len(exits), file=sys.stderr)

# SA・PAの中から本線に戻る道は乗り口ではない（スマートICはSA・PAの中を通るので残す）
try:
    import os
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sapa.json"), encoding="utf-8") as f:
        SAC = [(s[2] / 1e5, s[3] / 1e5) for s in json.load(f)["s"]]
except Exception:
    SAC = []


def near_sa(p, r=500):
    return any(abs(p[0] - c[0]) < 0.01 and abs(p[1] - c[1]) < 0.012 and dist_m(p, c) < r for c in SAC)


# 乗り口：名前は近く（3km）の同じ道路の降り口の名前
for k, (ids, pts) in enumerate(LINKS):
    e = ids[-1]
    if e not in ON or from_motorway(k):
        continue
    road, mb = ON[e]
    m = pts[-1]
    best, bd = None, 3000
    for ex in exits:
        if ex[1] != road:
            continue
        d = dist_m(m, ex[2])
        if d < bd:
            best, bd = ex, d
    if not best:
        continue
    back = chain_back(k)
    if not smart(best[0]) and (near_sa(m, 700) or near_sa(back[0], 500)):
        continue  # SA・PAから本線に戻る道
    tot = sum(dist_m(back[i - 1], back[i]) for i in range(1, len(back)))
    p, _ = along(back, max(0, tot - VIA_M))
    if p is None:
        continue
    # ランプの向き：その点のあたりの進む向き
    q, h = along(back, min(tot, max(0, tot - VIA_M) + 20))
    if h is None:
        continue
    out.append([best[0], road, 1, round(m[0] * 1e5), round(m[1] * 1e5), round(p[0] * 1e5), round(p[1] * 1e5), round(h), round(mb), smart(best[0])])
print("entries", sum(1 for x in out if x[2] == 1), file=sys.stderr)

# 同じ所（ランプが細切れで重複）は1つに
seen, uniq = set(), []
for x in out:
    key = (x[0], x[2], x[5] // 20, x[6] // 20)
    if key in seen:
        continue
    seen.add(key)
    uniq.append(x)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"v": datetime.date.today().isoformat(), "x": uniq}, f, ensure_ascii=False, separators=(",", ":"))
print("written", len(uniq), file=sys.stderr)
