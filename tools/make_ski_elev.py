"""ski.json に山頂・山麓（リフトの端で一番高い所・低い所）の標高を足す。
make_ski.py の後に実行する。標高は Open-Meteo の標高API（無料・キー不要）。回数制限があるので少しずつ。
各スキー場の6番目の要素: [山頂緯度, 山頂経度, 山頂標高m, 山麓緯度, 山麓経度, 山麓標高m]（緯度経度は1e5倍の整数）
"""
import json, time, urllib.request, sys, os
P = os.path.join(os.path.dirname(__file__), "..", "ski.json")
d = json.load(open(P, encoding="utf-8"))
ends = []
for j, r in enumerate(d["s"]):
    c = (r[1], r[2]); L = r[4]
    pts = [(c[0] + L[i], c[1] + L[i + 1]) for i in range(0, len(L) - 1, 2)] or [c]
    st = max(1, len(pts) // 8)
    for p in pts[::st][:8]:
        ends.append((j, p))
el = [None] * len(ends)
for i in range(0, len(ends), 100):
    ch = ends[i:i + 100]
    u = ("https://api.open-meteo.com/v1/elevation?latitude=" + ",".join(f"{p[0]/1e5:.5f}" for _, p in ch)
         + "&longitude=" + ",".join(f"{p[1]/1e5:.5f}" for _, p in ch))
    for t in range(6):
        try:
            res = json.load(urllib.request.urlopen(u, timeout=60)); break
        except Exception as e:
            print("retry", i, e, flush=True); time.sleep(30 * (t + 1))
    else:
        sys.exit("failed")
    for k, e in enumerate(res["elevation"]): el[i + k] = e
    print(i + len(ch), "/", len(ends), flush=True)
    time.sleep(15)
for j, r in enumerate(d["s"]):
    es = [(el[k], p) for k, (jj, p) in enumerate(ends) if jj == j and el[k] is not None]
    if not es: continue
    hi = max(es, key=lambda x: x[0]); lo = min(es, key=lambda x: x[0])
    v = [hi[1][0], hi[1][1], round(hi[0]), lo[1][0], lo[1][1], round(lo[0])]
    if len(r) > 5: r[5] = v
    else: r.append(v)
json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("exit 0")
