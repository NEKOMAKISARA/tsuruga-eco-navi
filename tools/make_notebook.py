# 声のパックを作るColabのノートブック（tools/make_voicepack.ipynb）を作る
import json,os
cells=[]
def md(t):cells.append({"cell_type":"markdown","metadata":{},"source":t})
def code(t):cells.append({"cell_type":"code","metadata":{},"execution_count":None,"outputs":[],"source":t})

md("""# エコ巡航ナビ：好きな声のパックを作る
RVCの声のモデル（`.pth` と `.index`）から、ナビがしゃべる言葉（約1100語）を全部その声で作り、アプリに読み込む **zip** にします。

1. メニュー「ランタイム」→「ランタイムのタイプを変更」→ **T4 GPU**
2. 上から順に ▶ を押す（全部で30〜60分くらい）
3. できた `navivoice_pack.zip` を iPhone に落として、アプリの設定「好きな声で案内」→「読み込む」

元の声は Microsoft の読み上げ（Applio にも入っている edge-tts）で作り、それをRVCで好きな声に変えます。""")

code("""# @title ① Googleドライブをつなぐ
from google.colab import drive
drive.mount('/content/drive')""")

code("""# @title ② Applio（RVC）を入れる（5〜10分）
%cd /content
!git clone -q https://github.com/IAHispano/Applio
%cd /content/Applio
!apt -qq update -y >/dev/null && apt -qq install -y portaudio19-dev ffmpeg >/dev/null
!curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
!/root/.local/bin/uv venv .venv --python 3.12 --seed -q
!/root/.local/bin/uv pip install -q -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match --python /content/Applio/.venv/bin/python
!/content/Applio/.venv/bin/python -c "from core import run_prerequisites_script as r; r(pretraineds_hifigan=False, models=True, exe=True)"
print("できました")""")

code("""# @title ③ 設定（声のモデルの場所など）
PTH = "/content/drive/MyDrive/ApplioBackup/navivoice/navivoice.pth"  # @param {type:"string"}
INDEX = "/content/drive/MyDrive/ApplioBackup/navivoice/navivoice.index"  # @param {type:"string"}
NAME = "好きな声"  # @param {type:"string"}
# 元にする声：好きな声が女性なら Nanami、男性なら Keita が自然になりやすい
BASE_VOICE = "ja-JP-NanamiNeural"  # @param ["ja-JP-NanamiNeural","ja-JP-KeitaNeural"]
# 高さの調整（半音）。元の声と好きな声の高さが違う時に（女→男は -12、男→女は +12 くらい）
PITCH = 0  # @param {type:"integer"}
# 読む速さ（元の声）
RATE = "+5%"  # @param {type:"string"}
import os
print("pth:", os.path.exists(PTH), "index:", os.path.exists(INDEX))
if not os.path.exists(INDEX):
    import glob
    print("indexの候補:", glob.glob(os.path.dirname(INDEX) + "/*.index"))""")

code("""# @title ④ 言葉の一覧を取ってきて、元の声で全部読む（5〜10分）
import json, urllib.request, os, subprocess
URL = "https://raw.githubusercontent.com/NEKOMAKISARA/tsuruga-eco-navi/main/tools/voice_phrases.json"
phrases = json.load(urllib.request.urlopen(URL))
print(len(phrases), "語")
os.makedirs("/content/vp/base", exist_ok=True)
json.dump(phrases, open("/content/vp/phrases.json", "w"), ensure_ascii=False)
script = '''
import asyncio, json, os, edge_tts, sys
P = json.load(open("/content/vp/phrases.json"))
voice, rate = sys.argv[1], sys.argv[2]
sem = asyncio.Semaphore(8)
async def one(p):
    out = f"/content/vp/base/{p['id']}.mp3"
    if os.path.exists(out) and os.path.getsize(out) > 1000: return
    async with sem:
        for t in range(4):
            try:
                await edge_tts.Communicate(p["text"], voice, rate=rate).save(out); return
            except Exception as e:
                await asyncio.sleep(2 + t * 3)
        print("失敗:", p["text"])
async def main(): await asyncio.gather(*[one(p) for p in P])
asyncio.run(main())
'''
open("/content/vp/tts.py", "w").write(script)
subprocess.run(["/content/Applio/.venv/bin/python", "/content/vp/tts.py", BASE_VOICE, RATE], check=False)
# RVCに渡すためにWAV（モノラル）へ
os.makedirs("/content/vp/wav", exist_ok=True)
for p in phrases:
    src = f"/content/vp/base/{p['id']}.mp3"; dst = f"/content/vp/wav/{p['id']}.wav"
    if os.path.exists(src) and not os.path.exists(dst):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-ac", "1", "-ar", "40000", dst])
print("元の声:", len(os.listdir("/content/vp/wav")), "個")""")

code("""# @title ⑤ 好きな声に変える（RVC、10〜20分）
import subprocess, os
os.makedirs("/content/vp/rvc", exist_ok=True)
%cd /content/Applio
subprocess.run(["/content/Applio/.venv/bin/python", "core.py", "batch-infer",
  "--input-folder", "/content/vp/wav", "--output-folder", "/content/vp/rvc",
  "--pth-path", PTH, "--index-path", INDEX, "--pitch", str(PITCH),
  "--f0-method", "rmvpe", "--index-rate", "0.5", "--protect", "0.4", "--export-format", "WAV"], check=False)
print("変換:", len([f for f in os.listdir("/content/vp/rvc") if f.endswith(".wav")]), "個")""")

code("""# @title ⑥ 前後の無音を切って音量をそろえ、zipにする
import os, json, subprocess, zipfile, glob
os.makedirs("/content/vp/mp3", exist_ok=True)
phrases = json.load(open("/content/vp/phrases.json"))
clips = {}
AF = "silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,loudnorm=I=-16:TP=-1.5:LRA=11"
for p in phrases:
    cand = glob.glob(f"/content/vp/rvc/{p['id']}*.wav")
    if not cand: continue
    out = f"/content/vp/mp3/{p['id']}.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", cand[0], "-af", AF, "-ac", "1", "-ar", "24000", "-b:a", "64k", out])
    if os.path.exists(out): clips[p["text"]] = p["id"] + ".mp3"
zp = "/content/navivoice_pack.zip"
with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:  # アプリは無圧縮のzipを読む
    z.writestr("manifest.json", json.dumps({"name": NAME, "clips": clips}, ensure_ascii=False))
    for t, f in clips.items(): z.write(f"/content/vp/mp3/{f}", f)
dst = "/content/drive/MyDrive/navivoice_pack.zip"
subprocess.run(["cp", zp, dst])
print(len(clips), "語 / ", round(os.path.getsize(zp) / 1e6, 1), "MB  →", dst)""")

code("""# @title ⑦ 試しに聞く
from IPython.display import Audio, display
import random, json
clips = json.load(open("/content/vp/phrases.json"))
for p in [x for x in clips if x["text"] in ("案内を開始します", "1キロ先", "左方向", "出口です", "左車線を走行してください")]:
    print(p["text"]); display(Audio(f"/content/vp/mp3/{p['id']}.mp3"))""")

nb={"nbformat":4,"nbformat_minor":0,"metadata":{"colab":{"provenance":[],"gpuType":"T4"},"kernelspec":{"name":"python3","display_name":"Python 3"},"accelerator":"GPU"},"cells":cells}
json.dump(nb,open(os.path.join(os.path.dirname(__file__),"make_voicepack.ipynb"),"w"),ensure_ascii=False,indent=1)
print("ok")
