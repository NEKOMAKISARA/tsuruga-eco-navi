"""ski.json にスキー場名の読み（カタカナ）を足す。「はくば」「なえば」のように読みでも探せるように。
make_ski.py・make_ski_elev.py の後に実行する。読みは SudachiPy（辞書 core）で付ける（当て字などは外れることがある）。
各スキー場の7番目の要素: 読み（カタカナ。名前と同じなら空文字）
"""
import json, os
from sudachipy import dictionary, tokenizer
P = os.path.join(os.path.dirname(__file__), "..", "ski.json")
d = json.load(open(P, encoding="utf-8"))
tk = dictionary.Dictionary().create(); M = tokenizer.Tokenizer.SplitMode.C
# 辞書の読みが地名として違うもの（見つけたら足す）
FIX = {"水上": "ミナカミ", "鹿島槍": "カシマヤリ", "車山": "クルマヤマ", "岩原": "イワッパラ", "八海山": "ハッカイサン", "八海": "ハッカイ",
       "岩鞍": "イワクラ", "西館山": "ニシタテヤマ", "館山": "タテヤマ", "峰の原": "ミネノハラ", "高原": "コウゲン", "スキー場": "スキージョウ"}
import re
FIX_RE = re.compile("|".join(sorted(map(re.escape, FIX), key=len, reverse=True)))
def yomi0(text):
    out = []
    for m in tk.tokenize(text, M):
        if m.part_of_speech()[0] in ("補助記号", "空白"): continue   # 記号・空白は読まない（「キゴウ」になる）
        out.append(m.reading_form())
    return "".join(out)
def yomi(name):
    # 直す言葉は名前の文字のまま切り出して置き換え、残りを辞書で読む
    out, k = [], 0
    for m in FIX_RE.finditer(name):
        if m.start() > k: out.append(yomi0(name[k:m.start()]))
        out.append(FIX[m.group()]); k = m.end()
    if k < len(name): out.append(yomi0(name[k:]))
    return "".join(out)
for r in d["s"]:
    y = yomi(r[0])
    while len(r) < 6: r.append(None)
    r[6:] = [y if y != r[0] else ""]
json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(len(d["s"]), "件")
