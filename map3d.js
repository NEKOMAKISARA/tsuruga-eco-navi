/* 3D ゲレンデマップ（滑走ログ ride.html が使う。カワサキサーチ ski.html の3D表示と同じ作り）
   山の形 = 国土地理院の標高タイル(dem_png)。地形の絵 = 国土地理院の航空写真を雪景色に変えた物（暗い所＝森、明るい所＝雪）。
   コース・リフト・施設 = ski_course/<緯度>_<経度>.json（tools/make_ski_course.py、OpenStreetMap）。
   座標：スキー場の中心からの m。x=東、z=南。 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
export { THREE };
export const PC = { g: "#1e8e3e", r: "#d93025", b: "#202124", f: "#e8710a", "": "#9aa0a6" };
export const DN = { g: "初級", r: "中級", b: "上級", f: "非圧雪" };
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const LS = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { } } };

// 中心 c=[緯度,経度] からの m 座標
export function makeProj(c) {
  const k = Math.cos(c[0] * Math.PI / 180);
  const M = (dlat, dlon) => [dlon * 1.1132 * k, -dlat * 1.1054];          // 1e-5 度の差 → m
  return { k, M, fromLL: (la, lo) => M((la - c[0]) * 1e5, (lo - c[1]) * 1e5), toLL: (x, z) => [c[0] - z / 110540, c[1] + x / (111320 * k)] };
}
const loadImg = u => new Promise((ok, ng) => { const i = new Image(); i.crossOrigin = "anonymous"; i.onload = () => ok(i); i.onerror = () => ng(new Error("tile")); i.src = u; });
const tgx = (lon, z) => (lon + 180) / 360 * 256 * 2 ** z, tgy = (lat, z) => (1 - Math.log(Math.tan(lat * Math.PI / 180) + 1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2 * 256 * 2 ** z;
async function tileMosaic(nw, se, z, maxT, url) {
  let tx0, tx1, ty0, ty1; for (; ;) { tx0 = Math.floor(tgx(nw[1], z) / 256); tx1 = Math.floor(tgx(se[1], z) / 256); ty0 = Math.floor(tgy(nw[0], z) / 256); ty1 = Math.floor(tgy(se[0], z) / 256); if ((tx1 - tx0 + 1) * (ty1 - ty0 + 1) <= maxT || z <= 8) break; z--; }
  const cv = document.createElement("canvas"); cv.width = (tx1 - tx0 + 1) * 256; cv.height = (ty1 - ty0 + 1) * 256; const g = cv.getContext("2d", { willReadFrequently: true }); let n = 0;
  const jobs = []; for (let ty = ty0; ty <= ty1; ty++)for (let tx = tx0; tx <= tx1; tx++)jobs.push(loadImg(url(z, tx, ty)).then(im => { g.drawImage(im, (tx - tx0) * 256, (ty - ty0) * 256); n++; }).catch(() => { }));
  await Promise.all(jobs);
  return { cv, g, z, tx0, ty0, n, all: jobs.length, px: (lat, lon) => [tgx(lon, z) - tx0 * 256, tgy(lat, z) - ty0 * 256] };
}
// 標高：範囲（北西・南東の緯度経度）の高さ(m)を返す関数
export async function loadDem(nw, se, z = 14, maxT = 30) {
  const m = await tileMosaic(nw, se, z, maxT, (z, x, y) => `https://cyberjapandata.gsi.go.jp/xyz/dem_png/${z}/${x}/${y}.png`);
  const mw = m.cv.width, mh = m.cv.height, px = m.g.getImageData(0, 0, mw, mh).data, H = new Float32Array(mw * mh); let hs = 0, hn = 0;
  for (let i = 0; i < mw * mh; i++) { const v = px[i * 4] * 65536 + px[i * 4 + 1] * 256 + px[i * 4 + 2]; const h = px[i * 4 + 3] === 0 || v === 8388608 ? NaN : (v < 8388608 ? v : v - 16777216) * 0.01; H[i] = h; if (h === h) { hs += h; hn++; } }
  if (hn < mw * mh * 0.2) throw new Error("標高が取れません");
  const hAvg = hs / hn; for (let i = 0; i < H.length; i++)if (H[i] !== H[i]) H[i] = hAvg;
  return (lat, lon) => {
    let [u, v] = m.px(lat, lon); u = Math.max(0, Math.min(mw - 1.001, u - 0.5)); v = Math.max(0, Math.min(mh - 1.001, v - 0.5));
    const i = Math.floor(u), j = Math.floor(v), fu = u - i, fv = v - j, a = H[j * mw + i], b = H[j * mw + i + 1], c = H[(j + 1) * mw + i], e = H[(j + 1) * mw + i + 1]; return (a * (1 - fu) + b * fu) * (1 - fv) + (c * (1 - fu) + e * fu) * fv;
  };
}
const tint = t => { t = Math.pow(Math.max(0, Math.min(1, t)), 1.4); return [96 + (236 - 96) * t, 122 + (242 - 122) * t, 112 + (247 - 112) * t]; };
export const segDist = (p, a, b) => { const dx = b[0] - a[0], dz = b[1] - a[1], l = dx * dx + dz * dz; let t = l ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / l : 0; t = Math.max(0, Math.min(1, t)); return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dz); };
// コース・リフトを m 座標に
export function courseXZ(d, proj) {
  const pl = a => { const o = []; for (let i = 0; i + 1 < a.length; i += 2)o.push(proj.M(a[i], a[i + 1])); return o; };
  return { P: d.p.map(([c, nm, cl, a]) => ({ c, nm, cl, q: pl(a) })), Lf: d.l.map(([t, nm, a]) => ({ nm, q: pl(a) })) };
}

/* box に3Dのゲレンデマップを作る。
   opt: c=[中心緯度,経度], d=コースのデータ, elev={top:[緯度,経度,m],base:[…]}|null, extra=[[x,z],…]（範囲に含めたい点＝滑った跡）, alive()=まだ表示してよいか
   戻り値: 描き直し draw()、片付け dispose()、地形の高さ Y(x,z)、地形の絵へ描く paint(fn) など */
export async function build3D(box, opt) {
  const { c, d, elev } = opt, proj = makeProj(c), { M, toLL } = proj;
  const { P, Lf } = courseXZ(d, proj);
  let x0 = 1e9, z0 = 1e9, x1 = -1e9, z1 = -1e9; const ext = ([x, z]) => { x0 = Math.min(x0, x); z0 = Math.min(z0, z); x1 = Math.max(x1, x); z1 = Math.max(z1, z); };
  for (const o of [...P, ...Lf]) o.q.forEach(ext); (opt.extra || []).forEach(ext);
  { const m = Math.max(x1 - x0, z1 - z0) * 0.22 + 300, cx = (x0 + x1) / 2, cz = (z0 + z1) / 2, hw = (x1 - x0) / 2 + m, hd = (z1 - z0) / 2 + m; x0 = cx - hw; x1 = cx + hw; z0 = cz - hd; z1 = cz + hd; }
  const W = x1 - x0, D = z1 - z0, S2 = Math.max(W, D), CX = (x0 + x1) / 2, CZ = (z0 + z1) / 2;
  const FAR = 3.2, fnw = toLL(CX - S2 * FAR, CZ - S2 * FAR), fse = toLL(CX + S2 * FAR, CZ + S2 * FAR);
  const TW = S2 > 3000 ? 4096 : 2048, TH = Math.max(512, Math.round(Math.min(4096, TW * D / W)));
  let pz = 17; while (pz > 13 && (W / (156543 * proj.k / 2 ** pz)) > TW * 1.3) pz--;
  const [hNear, hFar, photo] = await Promise.all([
    loadDem(toLL(x0, z0), toLL(x1, z1), 14, 30),
    loadDem(fnw, fse, 11, 16).catch(() => null),
    tileMosaic(toLL(x0, z0), toLL(x1, z1), pz, 64, (z, x, y) => `https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/${z}/${x}/${y}.jpg`).catch(() => null)]);
  if (opt.alive && !opt.alive()) return null;
  const hAt = (x, z) => { const [la, lo] = toLL(x, z); return hNear(la, lo); };
  // 地形の網
  const SX = Math.max(60, Math.min(240, Math.round(W / 12))), SZ = Math.max(20, Math.round(SX * D / W)), EX = 1.15;
  const geo = new THREE.PlaneGeometry(W, D, SX, SZ); geo.rotateX(-Math.PI / 2);
  const pos = geo.attributes.position; let hmin = 1e9, hmax = -1e9; const hv = new Float32Array(pos.count);
  for (let i = 0; i < pos.count; i++) { const X = pos.getX(i) + CX, Z = pos.getZ(i) + CZ, h = hAt(X, Z); hv[i] = h; hmin = Math.min(hmin, h); hmax = Math.max(hmax, h); pos.setX(i, X); pos.setZ(i, Z); }
  for (let i = 0; i < pos.count; i++)pos.setY(i, (hv[i] - hmin) * EX);
  geo.computeVertexNormals();
  const Y = (x, z) => (hAt(x, z) - hmin) * EX;
  // 地形に貼る絵
  const tc = document.createElement("canvas"); tc.width = TW; tc.height = TH; const g = tc.getContext("2d", { willReadFrequently: true });
  { const lo = document.createElement("canvas"); lo.width = SX + 1; lo.height = SZ + 1; const lg = lo.getContext("2d"), li = lg.createImageData(SX + 1, SZ + 1);
    for (let j = 0; j <= SZ; j++)for (let i = 0; i <= SX; i++) { const cc = tint((hv[j * (SX + 1) + i] - hmin) / Math.max(1, hmax - hmin)), o = (j * (SX + 1) + i) * 4; li.data[o] = cc[0]; li.data[o + 1] = cc[1]; li.data[o + 2] = cc[2]; li.data[o + 3] = 255; }
    lg.putImageData(li, 0, 0); g.imageSmoothingEnabled = true; g.drawImage(lo, 0, 0, TW, TH); }
  if (photo && photo.n > photo.all * 0.5) {
    const [a, b] = photo.px(...toLL(x0, z0)), [cc, e] = photo.px(...toLL(x1, z1));
    const sm = document.createElement("canvas"); sm.width = TW / 4; sm.height = Math.round(TH / 4); const sg = sm.getContext("2d"); sg.imageSmoothingEnabled = true; sg.imageSmoothingQuality = "high";
    sg.drawImage(photo.cv, a, b, cc - a, e - b, 0, 0, sm.width, sm.height); g.imageSmoothingQuality = "high"; g.drawImage(sm, 0, 0, TW, TH);
    const im = g.getImageData(0, 0, TW, TH), q = im.data;
    for (let i = 0; i < q.length; i += 4) { const R = q[i], G = q[i + 1], B = q[i + 2], l = 0.3 * R + 0.59 * G + 0.11 * B;
      let t = (118 - l) / 40; if (G > R + 6 && G > B + 4) t += 0.15; t = t < 0 ? 0 : t > 1 ? 1 : t;
      const dl = (l - 110) * 0.06, sr = 240 + dl, sgg = 244 + dl, sb = 249 + dl, fr = 88 + l * 0.14, fg = 112 + l * 0.14, fb = 100 + l * 0.14;
      q[i] = sr + (fr - sr) * t; q[i + 1] = sgg + (fg - sgg) * t; q[i + 2] = sb + (fb - sb) * t; }
    g.putImageData(im, 0, 0);
  }
  const T = ([x, z]) => [(x - x0) / W * TW, (z - z0) / D * TH], ppm = TW / W, lw = v => Math.max(v * ppm, 1), sc = TW / 2048;
  const stroke = (q, col, w, dash) => { g.beginPath(); q.forEach((p, i) => { const [a, b] = T(p); i ? g.lineTo(a, b) : g.moveTo(a, b); }); g.strokeStyle = col; g.lineWidth = w; g.lineCap = "round"; g.lineJoin = "round"; g.setLineDash(dash || []); g.stroke(); };
  for (const o of P.filter(o => o.cl)) { g.beginPath(); o.q.forEach((p, i) => { const [a, b] = T(p); i ? g.lineTo(a, b) : g.moveTo(a, b); }); g.closePath(); g.fillStyle = "rgba(255,255,255,.5)"; g.fill(); }
  const lines = P.filter(o => !o.cl).sort((a, b) => "fgrb".indexOf(a.c) - "fgrb".indexOf(b.c));
  const wW = Math.max(15 * sc, lw(30)), wC = Math.max(9 * sc, lw(13));
  const dim = opt.dimCourse ? 0.55 : 1;   // 滑った跡を目立たせる時はコースを少し薄く
  g.globalAlpha = dim;
  for (const o of lines) stroke(o.q, "rgba(255,255,255,.95)", wW);
  for (const o of lines) stroke(o.q, "rgba(20,30,40,.45)", wC + 3 * sc);
  for (const o of lines) stroke(o.q, PC[o.c] || PC[""], wC, o.c === "f" ? [wC * 2.2, wC * 1.6] : null);
  g.globalAlpha = 1;
  for (const o of Lf) stroke(o.q, "rgba(30,40,50,.3)", Math.max(2 * sc, lw(5)));
  const tex = new THREE.CanvasTexture(tc); tex.colorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const terr = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ map: tex })); terr.castShadow = terr.receiveShadow = true; scene.add(terr);
  if (hFar) { const FW = S2 * FAR * 2, FS = 160, fgeo = new THREE.PlaneGeometry(FW, FW, FS, FS); fgeo.rotateX(-Math.PI / 2);
    const fp = fgeo.attributes.position, col = new Float32Array(fp.count * 3); let fmax = hmax;
    const fh = new Float32Array(fp.count); for (let i = 0; i < fp.count; i++) { const X = fp.getX(i) + CX, Z = fp.getZ(i) + CZ, [la, lo] = toLL(X, Z), h = hFar(la, lo); fh[i] = h; fmax = Math.max(fmax, h); fp.setX(i, X); fp.setZ(i, Z); }
    for (let i = 0; i < fp.count; i++) { const X = fp.getX(i), Z = fp.getZ(i), inside = X > x0 && X < x1 && Z > z0 && Z < z1; fp.setY(i, (fh[i] - hmin) * EX - (inside ? S2 * 0.02 : S2 * 0.002));
      const cc = tint((fh[i] - hmin + 300) / Math.max(800, fmax - hmin + 300)); col[i * 3] = cc[0] / 255; col[i * 3 + 1] = cc[1] / 255; col[i * 3 + 2] = cc[2] / 255; }
    fgeo.setAttribute("color", new THREE.BufferAttribute(col, 3)); fgeo.computeVertexNormals();
    const far = new THREE.Mesh(fgeo, new THREE.MeshLambertMaterial({ vertexColors: true })); far.receiveShadow = true; scene.add(far); }
  // リフト（地面から離して張る）
  const rr = S2 / 1400, lm = new THREE.MeshLambertMaterial({ color: 0x263238 });
  const L3 = [], CL = Math.max(14, rr * 7) * EX;
  for (const o of Lf) { const a = o.q[0], b = o.q[o.q.length - 1], L = Math.hypot(b[0] - a[0], b[1] - a[1]); if (L < 5) continue;
    const n = Math.max(4, Math.ceil(L / 25)), xs = [], gh = []; for (let i = 0; i <= n; i++) { const t = i / n, x = a[0] + (b[0] - a[0]) * t, z = a[1] + (b[1] - a[1]) * t; xs.push([x, z]); gh.push(Y(x, z)); }
    const hA = gh[0] + CL, hB = gh[n] + CL, hc = gh.map((h, i) => Math.max(hA + (hB - hA) * i / n, h + CL));
    for (let it = 0; it < 3; it++)for (let i = 1; i < n; i++)hc[i] = Math.max(gh[i] + CL, (hc[i - 1] + hc[i] * 2 + hc[i + 1]) / 4);
    const pts = xs.map(([x, z], i) => new THREE.Vector3(x, hc[i], z));
    scene.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), n * 3, rr * 0.9, 5, false), lm));
    for (const E of [pts[0], pts[n]]) { const st = new THREE.Mesh(new THREE.BoxGeometry(rr * 7, CL, rr * 7), lm); st.position.copy(E); st.position.y -= CL / 2; st.castShadow = true; scene.add(st); }
    L3.push({ o, xs, hc, mid: pts[Math.floor(n / 2)] }); }
  // 光
  let ux = 0, uz = -1;
  if (elev) { const a = proj.fromLL(elev.top[0], elev.top[1]), b = proj.fromLL(elev.base[0], elev.base[1]), n = Math.hypot(a[0] - b[0], a[1] - b[1]); if (n > 50) { ux = (a[0] - b[0]) / n; uz = (a[1] - b[1]) / n; } }
  scene.add(new THREE.HemisphereLight(0xe6eef8, 0x9aa6b2, 1.55));
  const sun = new THREE.DirectionalLight(0xfff6ea, 1.35); sun.position.set(CX + (-uz * 0.8 - ux * 0.6) * S2, (hmax - hmin) * EX + S2 * 0.9, CZ + (ux * 0.8 - uz * 0.6) * S2); sun.target.position.set(CX, 0, CZ); scene.add(sun, sun.target);
  sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048); const sc2 = sun.shadow.camera; sc2.left = sc2.bottom = -S2 * 0.75; sc2.right = sc2.top = S2 * 0.75; sc2.near = S2 * 0.1; sc2.far = S2 * 4; sun.shadow.bias = -0.0004; sun.shadow.normalBias = S2 / 600;
  scene.fog = new THREE.Fog(0xe4eef7, S2 * 1.6, S2 * FAR * 1.15);
  const ren = new THREE.WebGLRenderer({ antialias: true, alpha: true }); ren.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  ren.shadowMap.enabled = true; ren.shadowMap.type = THREE.PCFSoftShadowMap; tex.anisotropy = Math.min(8, ren.capabilities.getMaxAnisotropy());
  box.innerHTML = ""; box.classList.add("c3");
  const lay = document.createElement("div"); lay.style.cssText = "position:absolute;inset:0;pointer-events:none;overflow:hidden";
  const fb = document.createElement("button"); fb.className = "cbtn"; fb.textContent = "全画面";
  const cap = document.createElement("div"); cap.className = "ccap";
  let showNm = !!LS.get("skiNames", false); const nb = document.createElement("button"); nb.className = "cbtn nm";
  const nbSet = () => { nb.textContent = "名前"; nb.classList.toggle("on", showNm); }; nbSet();
  box.append(ren.domElement, lay, fb, nb, cap);
  // カメラ：ふもとから山頂を見上げる
  const cam = new THREE.PerspectiveCamera(38, 1, S2 / 200, S2 * FAR * 3);
  const ctr = new THREE.Vector3(CX, (hmax - hmin) * EX * 0.42, CZ);
  const dist = S2 * 0.95; cam.position.set(ctr.x - ux * dist * 0.82, ctr.y + dist * 0.62, ctr.z - uz * dist * 0.82);
  const ctl = new OrbitControls(cam, ren.domElement); ctl.target.copy(ctr); ctl.maxPolarAngle = Math.PI * 0.47; ctl.minDistance = S2 * 0.04; ctl.maxDistance = S2 * 2.2; ctl.enableDamping = false; ctl.update();
  // 札
  const lbs = []; const addL = (p, t, cls, pri) => { const e = document.createElement("div"); e.className = "lbl " + cls; e.textContent = t; lay.append(e); const L = { p, e, pri, w: 0 }; lbs.push(L); lbs.sort((a, b) => a.pri - b.pri); return L; };
  if (elev) { if (elev.top[2] - elev.base[2] >= 80) { const a = proj.fromLL(elev.top[0], elev.top[1]); addL(new THREE.Vector3(a[0], Y(a[0], a[1]) + rr * 14, a[1]), "▲ 山頂 " + elev.top[2] + "m", "pk", 0); }
    const b = proj.fromLL(elev.base[0], elev.base[1]); addL(new THREE.Vector3(b[0], Y(b[0], b[1]) + rr * 14, b[1]), "山麓 " + elev.base[2] + "m", "pk", 1); }
  for (const x of L3) if (x.o.nm) addL(x.mid.clone().add(new THREE.Vector3(0, rr * 4, 0)), x.o.nm, "lift", 2);
  const plen = q => { let s = 0; for (let i = 1; i < q.length; i++)s += Math.hypot(q[i][0] - q[i - 1][0], q[i][1] - q[i - 1][1]); return s; };
  P.filter(o => o.nm && !o.cl).map(o => ({ o, L: plen(o.q) })).sort((a, b) => b.L - a.L).slice(0, 25).forEach(({ o }, i) => { const m = o.q[Math.floor(o.q.length / 2)]; addL(new THREE.Vector3(m[0], Y(m[0], m[1]) + rr * 3, m[1]), o.nm, o.c || "", 3 + i / 100); });
  const FI = { P: "P", H: '<svg width="12" height="12" viewBox="0 0 24 24"><path d="M12 3 2 12h3v8h5v-5h4v5h5v-8h3z" fill="#fff"/></svg>' };
  const FN = { P: "駐車場", H: "センターハウス" };
  for (const [t, nm, dla, dlo] of (d.f || [])) { if (!FI[t]) continue; const [x, z] = M(dla, dlo); if (x < x0 || x > x1 || z < z0 || z > z1) continue;
    const e = document.createElement("div"); e.className = "fac " + t; e.innerHTML = `<i>${FI[t]}</i><span hidden>${esc(nm || FN[t])}</span>`;
    e.onclick = () => { cap.textContent = (nm || FN[t]) + (nm && t === "P" && !/駐車/.test(nm) ? "（駐車場）" : ""); }; lay.append(e);
    lbs.push({ p: new THREE.Vector3(x, Y(x, z) + rr * 2, z), e, pri: t === "H" ? 1.4 : 1.5, w: 0, fac: true }); }
  lbs.sort((a, b) => a.pri - b.pri);
  const v3 = new THREE.Vector3();
  const place = () => { const w = box.clientWidth, h = box.clientHeight, used = [];
    for (const L of lbs) { if (L.pri >= 2 && !showNm) { L.e.style.display = "none"; continue; } if (L.fac && !L.init) { L.init = 1; L.e.querySelector("span").hidden = !showNm; }
      v3.copy(L.p).project(cam); const sx = (v3.x + 1) / 2 * w, sy = (1 - v3.y) / 2 * h;
      if (!L.w || L.dyn) { L.e.style.display = ""; L.w = L.e.offsetWidth || 60; }
      const rc = L.fac ? [sx - 9, sy - 9, sx - 9 + L.w, sy + 9] : [sx - L.w / 2, sy - 18, sx + L.w / 2, sy - 2];
      const ok = v3.z < 1 && rc[0] > 2 && rc[2] < w - 2 && rc[1] > 2 && rc[3] < h - 2 && (L.pri < 0 || !used.some(u => !(rc[2] < u[0] || rc[0] > u[2] || rc[3] < u[1] || rc[1] > u[3])));
      L.e.style.display = ok ? "" : "none"; if (ok) { used.push([rc[0] - 3, rc[1] - 2, rc[2] + 3, rc[3] + 2]); L.e.style.transform = `translate(${Math.round(rc[0])}px,${Math.round(rc[1])}px)`; } } };
  nb.onclick = () => { showNm = !showNm; LS.set("skiNames", showNm); nbSet(); for (const L of lbs) { if (L.fac) L.e.querySelector("span").hidden = !showNm; L.w = 0; } place(); };
  const api = {};
  const draw = () => { ren.render(scene, cam); place(); api.onDraw && api.onDraw(); };
  ctl.addEventListener("change", draw);
  const resize = () => { const w = box.clientWidth, h = box.clientHeight; if (!w || !h) return; ren.setSize(w, h); cam.aspect = w / h; cam.updateProjectionMatrix(); draw(); };
  const ro = new ResizeObserver(resize); ro.observe(box);
  const full = on => { box.classList.toggle("full", on); document.body.style.overflow = on ? "hidden" : ""; fb.textContent = on ? "閉じる" : "全画面"; resize(); };
  fb.onclick = () => full(!box.classList.contains("full"));
  // 斜度：20mごとに標高を取り、平均＝両端の高低差÷長さ、最大＝40mの区間で一番急な所
  const slope = q => { const pts = []; let len = 0;
    for (let i = 1; i < q.length; i++) { const a = q[i - 1], b = q[i], L = Math.hypot(b[0] - a[0], b[1] - a[1]), n = Math.max(1, Math.ceil(L / 20)); for (let j = i === 1 ? 0 : 1; j <= n; j++) { const t = j / n; pts.push({ d: len + L * t, h: hAt(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t) }); } len += L; }
    const drop = Math.abs(pts[0].h - pts[pts.length - 1].h), deg = (dh, dd) => Math.round(Math.atan2(Math.abs(dh), dd) * 180 / Math.PI);
    let mx = 0; for (let i = 0, j = 0; i < pts.length; i++) { while (j < pts.length && pts[j].d - pts[i].d < 40) j++; if (j < pts.length) mx = Math.max(mx, deg(pts[j].h - pts[i].h, pts[j].d - pts[i].d)); }
    return { len, drop, avg: len > 0 ? deg(drop, len) : 0, max: Math.max(mx, len > 0 ? deg(drop, len) : 0) }; };
  // 押した所のコース名
  const ray = new THREE.Raycaster(), nd = new THREE.Vector2(); let downAt = null;
  ren.domElement.addEventListener("pointerdown", e => { downAt = [e.clientX, e.clientY]; });
  ren.domElement.addEventListener("pointerup", e => { if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 6) return;
    const rc = ren.domElement.getBoundingClientRect(); nd.set((e.clientX - rc.left) / rc.width * 2 - 1, -(e.clientY - rc.top) / rc.height * 2 + 1); ray.setFromCamera(nd, cam);
    const hit = ray.intersectObject(terr)[0]; if (!hit) { cap.textContent = ""; return; } const p = [hit.point.x, hit.point.z], lim = Math.max(30, cam.position.distanceTo(hit.point) / 40);
    let best = null, bd = lim; for (const o of P) for (let i = 1; i < o.q.length; i++) { const dd = segDist(p, o.q[i - 1], o.q[i]); if (dd < bd) { bd = dd; best = o; } }
    for (const o of Lf) for (let i = 1; i < o.q.length; i++) { const dd = segDist(p, o.q[i - 1], o.q[i]); if (dd < bd) { bd = dd; best = { nm: o.nm || "リフト", lift: true, q: o.q }; } }
    if (!best) { cap.textContent = ""; return; }
    const sl = slope(best.q), km = v => v >= 1000 ? (Math.round(v / 100) / 10) + "km" : Math.round(v) + "m";
    cap.textContent = best.lift ? `${best.nm}・${km(sl.len)}・高さ${Math.round(sl.drop)}m` :
      `${best.nm || "名前なし"}${DN[best.c] ? "（" + DN[best.c] + "）" : ""}　平均${sl.avg}°・最大${sl.max}°・${km(sl.len)}・標高差${Math.round(sl.drop)}m`; });
  const dispose = () => { try { ro.disconnect(); ctl.dispose(); ren.dispose(); ren.forceContextLoss(); scene.traverse(o => { o.geometry && o.geometry.dispose(); if (o.material) { o.material.map && o.material.map.dispose(); o.material.dispose(); } }); } catch (e) { } box.classList.remove("full"); document.body.style.overflow = ""; };
  // 地形の絵に描く（滑った跡など）。fn(g, T, lw) を呼んでから絵を更新
  const paint = fn => { fn(g, T, lw, sc); tex.needsUpdate = true; draw(); };
  Object.assign(api, { THREE, scene, cam, ctl, ren, box, cap, Y, hAt, proj, P, Lf, rr, S2, EX, hmin, draw, resize, dispose, paint, addL, slope });
  resize();
  return api;
}
