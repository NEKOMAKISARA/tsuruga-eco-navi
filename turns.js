/* ターンの左右の動きを描き足す。
   GPS(1秒に1回・誤差数m)だけだとターン1回に2〜3点しかなく、S字が見えない。
   そこでスマホの回転(縦軸まわり、1秒に10回)で「いつ・どれだけ曲がったか」を取り、
   ・曲がる向きと感度は、GPSで分かる大きな曲がりと照らし合わせて自動で合わせる(端末ごとの向きの違い・ポケットの中で回りにくい分)
   ・進む向きの基準と位置そのものは数秒ならしたGPSに合わせる(回転センサーのずれは残らない)
   ことで、細かい曲がりは回転センサー、大きな位置はGPS、という道を作る。

   記録の形 gy: [{ t: 最初の値の時刻ms, n: 入っている数, a: Int16Array(縦軸まわりの回転 度/秒×10, 0.1秒ごと) }, …]
   pt: [{ t, x, z }, …] (m、時刻順)
   戻り値: { t, x, z (Float64Array, 0.1秒ごと), gain, corr } か null(使えない時) */
export const GY_DT = 100, GY_N = 600;

export function fuseTurns(pt, gy, opt = {}) { const why = m => { fuseTurns.why = m; return null; };
  if (!gy || !gy.length || !pt || pt.length < 10) return why("データ無し");
  const dt = GY_DT / 1000, maxGap = opt.maxGap || 5000;
  // 1) 回転センサーの値を並べる(GPSが5秒以上とぎれた所・回転のとぎれ目で区切る)
  const T = [], W = [];
  for (const c of gy) for (let k = 0; k < c.n; k++) { T.push(c.t + k * GY_DT); W.push(c.a[k] / 10); }
  if (T.length < 100) return why("回転が少ない");
  const n = T.length, Gx = new Float64Array(n), Gz = new Float64Array(n), ok = new Uint8Array(n);
  let j = 0;
  for (let k = 0; k < n; k++) { const t = T[k]; while (j < pt.length - 2 && pt[j + 1].t <= t) j++;
    const a = pt[j], b = pt[j + 1]; if (t < a.t || t > b.t || b.t - a.t > maxGap) continue;
    const f = (t - a.t) / Math.max(1, b.t - a.t); Gx[k] = a.x + (b.x - a.x) * f; Gz[k] = a.z + (b.z - a.z) * f; ok[k] = 1; }
  // 続いている区間に分ける
  const segs = []; let s0 = -1;
  for (let k = 0; k <= n; k++) { const cont = k < n && ok[k] && (k === s0 || k === 0 || T[k] - T[k - 1] < GY_DT * 3);
    if (s0 >= 0 && !cont) { if (k - s0 >= 60) segs.push([s0, k]); s0 = -1; } if (k < n && ok[k] && s0 < 0) s0 = k; }
  if (!segs.length) return why("続いた区間無し");
  // 移動平均(区間内、前後 h 個)
  const smooth = (v, a, b, h) => { const o = new Float64Array(b - a), P = new Float64Array(b - a + 1); for (let i = a; i < b; i++) P[i - a + 1] = P[i - a] + v[i];
    for (let i = 0; i < b - a; i++) { const l = Math.max(0, i - h), r = Math.min(b - a, i + h + 1); o[i] = (P[r] - P[l]) / (r - l); } return o; };
  // 2) GPSの進む向き・速さ(前後1.5秒) と 向きの変わる速さ
  const H15 = 15, C = new Float64Array(n), S = new Float64Array(n);
  for (const [a, b] of segs) for (let k = a; k < b; k++) { const l = Math.max(a, k - H15), r = Math.min(b - 1, k + H15); const dx = Gx[r] - Gx[l], dz = Gz[r] - Gz[l], tt = (T[r] - T[l]) / 1000;
    C[k] = Math.atan2(dz, dx); S[k] = tt > 0 ? Math.hypot(dx, dz) / tt : 0; }
  const wrap = x => { while (x > Math.PI) x -= 2 * Math.PI; while (x < -Math.PI) x += 2 * Math.PI; return x; };
  // 3) 向きと感度を合わせる：前後5秒の「GPSの向きの変わり」と「回転の足し合わせ」を比べる(短いターンは混ざらない長さ)
  const H5 = 50; let sxy = 0, sxx = 0, syy = 0, sx = 0, sy = 0, cnt = 0;
  const Hr = new Float64Array(n);
  for (const [a, b] of segs) { for (let i = a + 1; i < b; i++) Hr[i] = Hr[i - 1] + W[i] * Math.PI / 180 * dt;
    const Hc = smooth(Hr, a, b, H15); // GPSの向き(前後1.5秒の弦)と同じ幅でならす
    for (let k = a + H5; k < b - H5; k += 2) { if (S[k - H5] < 3 || S[k + H5] < 3) continue; const y = wrap(C[k + H5] - C[k - H5]), x = Hc[k + H5 - a] - Hc[k - H5 - a]; if (Math.abs(y) > 2.6) continue;
      sxy += x * y; sxx += x * x; syy += y * y; sx += x; sy += y; cnt++; } }
  // 切片つき(回転センサーのずれ＝一定の回転を同時に推定)。自信あり＝相関0.5以上かつ比べた時間が5分以上
  let gain = null, bias = null, corr = null, sure = false;
  const vxx = sxx - sx * sx / Math.max(1, cnt), vyy = syy - sy * sy / Math.max(1, cnt), vxy = sxy - sx * sy / Math.max(1, cnt);
  if (cnt >= 50 && vxx > 0 && vyy > 0) { corr = vxy / Math.sqrt(vxx * vyy); const slope = vxy / vxx, icpt = (sy - slope * sx) / cnt;
    if (Math.abs(corr) >= (opt.minCorr || 0.3)) { gain = Math.sign(slope) * Math.min(3, Math.max(0.7, Math.abs(slope))); bias = -icpt / slope / (2 * H5 * dt) * 180 / Math.PI; sure = Math.abs(corr) >= 0.5 && cnt * 2 * dt >= 300; } }
  // 自信がない時は、前に自信を持って合わせた感度(opt.cal)を使う。ずれは全体の平均(長く滑れば曲がりは打ち消し合う)
  if (!sure && opt.cal && opt.cal.gain) { gain = opt.cal.gain; let sw = 0, c = 0; for (const [a, b] of segs) for (let k = a; k < b; k++) { sw += W[k]; c++; } bias = sw / c; }
  if (gain == null) return why(cnt < 50 ? "比べる所が少ない " + cnt : "相関が低い " + (corr == null ? "-" : corr.toFixed(2)));
  // 4) 向き：回転を足し合わせ、基準は前後3秒のGPSの向きに合わせる  5) 進む  6) 位置は前後2.5秒ならしたGPSとの差で直す
  const X = new Float64Array(n).fill(NaN), Z = new Float64Array(n).fill(NaN);
  const cs = new Float64Array(n), sn = new Float64Array(n), ex = new Float64Array(n), ez = new Float64Array(n);
  for (const [a, b] of segs) { const m = b - a, H = new Float64Array(m); for (let i = 1; i < m; i++) H[i] = H[i - 1] + gain * (W[a + i] - bias) * Math.PI / 180 * ((T[a + i] - T[a + i - 1]) / 1000);
    const Hs = smooth(H, 0, m, H15);
    for (let i = 0; i < m; i++) { const k = a + i, wgt = Math.min(1, S[k] / 3); const d = C[k] - Hs[i]; cs[k] = Math.cos(d) * wgt; sn[k] = Math.sin(d) * wgt; }
    const cS = smooth(cs, a, b, 30), sS = smooth(sn, a, b, 30), vS = smooth(S, a, b, 5);
    // GPSの速さは1.5秒の弦なので、くねった分だけ小さい → 同じ幅での向きのまとまり具合(1=まっすぐ)で割って戻す
    const hc = new Float64Array(m), hs = new Float64Array(m); for (let i = 0; i < m; i++) { hc[i] = Math.cos(H[i]); hs[i] = Math.sin(H[i]); }
    const hC = smooth(hc, 0, m, H15), hS = smooth(hs, 0, m, H15); for (let i = 0; i < m; i++) vS[i] /= Math.max(0.5, Math.hypot(hC[i], hS[i]));
    const Dx = new Float64Array(m), Dz = new Float64Array(m);
    for (let i = 1; i < m; i++) { const h = H[i] + Math.atan2(sS[i], cS[i]), st = vS[i] * (T[a + i] - T[a + i - 1]) / 1000; Dx[i] = Dx[i - 1] + Math.cos(h) * st; Dz[i] = Dz[i - 1] + Math.sin(h) * st; }
    for (let i = 0; i < m; i++) { ex[a + i] = Gx[a + i] - Dx[i]; ez[a + i] = Gz[a + i] - Dz[i]; }
    const eX = smooth(ex, a, b, 40), eZ = smooth(ez, a, b, 40);
    for (let i = 0; i < m; i++) { X[a + i] = Dx[i] + eX[i]; Z[a + i] = Dz[i] + eZ[i]; } }
  const keep = []; for (let k = 0; k < n; k++) if (!Number.isNaN(X[k])) keep.push(k);
  const o = { t: new Float64Array(keep.length), x: new Float64Array(keep.length), z: new Float64Array(keep.length), gain, corr, bias, sure };
  keep.forEach((k, i) => { o.t[i] = T[k]; o.x[i] = X[k]; o.z[i] = Z[k]; });
  return o;
}

/* 記録中：devicemotion から縦軸まわりの回転を取り出して 0.1秒ごとに貯める */
export function makeGyroRec(store) {
  let gx = 0, gy0 = 0, gz = 0, gInit = false, last = 0, binT = 0, sum = 0, w = 0, cur = null, lastV = 0;
  const push = (t, v) => { if (!cur || cur.n >= GY_N || t - (cur.t + cur.n * GY_DT) > GY_DT * 3) { cur = { t, n: 0, a: new Int16Array(GY_N) }; store().push(cur); }
    cur.a[cur.n++] = Math.max(-32000, Math.min(32000, Math.round(v * 10))); };
  return e => { const a = e.accelerationIncludingGravity, r = e.rotationRate; if (!a || a.x == null || !r || r.alpha == null) return;
    const now = Date.now(), ds = last ? Math.min(0.2, (now - last) / 1000) : 0.016; last = now;
    // 重力の向き(1秒ならし)。ターン中の横向きの力は均される
    const k = ds / (ds + 1); if (!gInit) { gx = a.x; gy0 = a.y; gz = a.z; gInit = true; } else { gx += (a.x - gx) * k; gy0 += (a.y - gy0) * k; gz += (a.z - gz) * k; }
    const gl = Math.hypot(gx, gy0, gz); if (gl < 3) return;
    const yaw = (r.beta * gx + r.gamma * gy0 + r.alpha * gz) / gl; // 度/秒(向きの正負は端末で違うが後で合わせる)
    if (!binT) binT = now;
    if (now - binT > GY_DT * 3) { binT = now; sum = 0; w = 0; } // とぎれた
    sum += yaw * ds; w += ds;
    while (now - binT >= GY_DT) { if (w) lastV = sum / w; push(binT, lastV); binT += GY_DT; sum = 0; w = 0; } };
}
