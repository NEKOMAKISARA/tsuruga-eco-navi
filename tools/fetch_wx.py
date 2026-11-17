"""全国のスキー場の天気予報（Open-Meteo）をまとめて取り、wx.json にする。GitHub Actions が3時間ごとに実行する。
ページ（ski.html）はこのファイルを読むので、開く人や回数が増えても Open-Meteo への問い合わせは増えない。

使い方: python tools/fetch_wx.py [出力先 wx.json]
地点はページと同じ: 山頂と山麓（差が80m未満なら山麓だけ）。ski.json の6番目の要素（make_ski_elev.py）を使う。
出力: {"t": 作った時刻(unix秒), "t0": 最初の時刻, "n": 時間数, "s": {id: [[地点名, 標高, 気温×10, 降雪cm×10, 雨mm×10, 天気コード, 風×10, 瞬間風×10, 積雪cm], ...]}}
"""
import json, os, sys, time, urllib.request, urllib.error
NDAY, PAST = 16, 2
ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "wx.json")
d = json.load(open(os.path.join(ROOT, "ski.json"), encoding="utf-8"))
pts = []
for r in d["s"]:
    e = r[5] if len(r) > 5 else None
    if not e: continue
    rid = f"{r[0]}@{r[1]},{r[2]}"
    top, base = (e[0] / 1e5, e[1] / 1e5, e[2]), (e[3] / 1e5, e[4] / 1e5, e[5])
    if top[2] - base[2] >= 80: pts.append((rid, "山頂", top))
    pts.append((rid, "山麓", base))
print("地点", len(pts), flush=True)
VARS = "temperature_2m,snowfall,rain,weather_code,wind_speed_10m,wind_gusts_10m,snow_depth"
out, t0, n = {}, None, None
for i in range(0, len(pts), 40):
    ch = pts[i:i + 40]
    u = ("https://api.open-meteo.com/v1/forecast?latitude=" + ",".join(f"{p[2][0]:.4f}" for p in ch)
         + "&longitude=" + ",".join(f"{p[2][1]:.4f}" for p in ch) + "&elevation=" + ",".join(str(p[2][2]) for p in ch)
         + f"&hourly={VARS}&past_days={PAST}&forecast_days={NDAY}&timezone=Asia%2FTokyo&timeformat=unixtime&wind_speed_unit=ms")
    for t in range(6):
        try:
            res = json.load(urllib.request.urlopen(u, timeout=60)); break
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")
            print("retry", e.code, msg[:120], flush=True)
            if "Hourly" in msg or "Daily" in msg: sys.exit("上限: " + msg)
            time.sleep(30 * (t + 1))
        except Exception as e:
            print("retry", e, flush=True); time.sleep(30 * (t + 1))
    else:
        sys.exit("取得できません")
    if not isinstance(res, list): res = [res]
    for (rid, nm, p), x in zip(ch, res):
        h = x["hourly"]
        if t0 is None: t0, n = h["time"][0], len(h["time"])
        q = lambda a, k=10: [None if v is None else round(v * k) for v in a]
        out.setdefault(rid, []).append([nm, p[2], q(h["temperature_2m"]), q(h["snowfall"]), q(h["rain"]), h["weather_code"],
                                        q(h["wind_speed_10m"]), q(h["wind_gusts_10m"]), q(h["snow_depth"], 100)])
    print(i + len(ch), "/", len(pts), flush=True)
    time.sleep(6)   # 1分あたりの上限（600）に当たらないように
json.dump({"t": int(time.time()), "t0": t0, "n": n, "s": out}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("書き出し", OUT, os.path.getsize(OUT) // 1024, "KB")
