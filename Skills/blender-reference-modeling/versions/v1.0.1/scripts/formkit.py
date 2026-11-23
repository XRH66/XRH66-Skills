"""数形结合的基础算法（纯 Python，可选 numpy；Blender 内外都能用）。

    python formkit.py --selftest          # 逐项自检，打印每项的误差数字

内容（每个函数都在 selftest 里有一条断言）：
  曲线    kappa_curve 曲率沿弧长分段积分（欧拉 / 对数螺线）· wing_curve 平—起势—回落—直段 · resample 等弧长重采样
          polyline_theta · offset_curve · tapered_stroke · cubic_bezier · interp_x · discrete_curvature 离散曲率（曲率图）
  拟合    nelder_mead（带边界）· fit_multistart 多起点 + 撞边界报告 · dist_to_polyline / rms_to_polyline 几何距离
          signed_dist 有符号残差（残差诊断）· huber 稳健损失（抗遮挡）· fillet_seg 拐点段（构件交接处的拐角）
          fair_kappa 拟合后的顺滑（κ 高斯摊开，转角守恒；σ = 转折软硬，审美参数）
  过渡    smoothstep · smoothmax / smoothmin（log-sum-exp 圆角）
  随机    rng（种子 + 件名）· noise1 · fbm1
  成形    rmf_frames 旋转最小标架（双反射法，扫掠不翻转）· sweep 截面沿路径扫掠出 quad · loft 多截面放样
  分布    poisson_disk 泊松盘采样（最小间距）
  距离场  polygon_sdf 多边形有符号距离（内负外正）· relief_height 轮廓 → 浮雕剖面

单位约定：长度 mm，角度弧度，曲率 1/mm。曲线点 = (x, z, θ, s)。
来源：xiuxian-gateway 的 spec/curves.py（曲线、拟合、随机、smoothmax 已在项目里用过），其余为通用算法，自检通过但尚未在完整项目里用过。
"""
import hashlib
import math
import random
import sys

try:
    import numpy as _np
except Exception:          # 没有 numpy 时退回纯 Python
    _np = None


# ================================================================ 曲线
def kappa_curve(segs, x0=0.0, z0=0.0, th0=0.0, ds=8.0):
    """segs: [(L, k0, k1, mode), ...]；mode "lin" = κ 线性变（欧拉螺线），"exp" = κ 几何变（对数螺线，k0·k1 > 0）。
    中点法积分 θ = θ0 + ∫κ ds，x = ∫cosθ ds，z = ∫sinθ ds。返回 [(x, z, θ, s)]。"""
    x, z, th, s = float(x0), float(z0), float(th0), 0.0
    out = [(x, z, th, s)]
    for (L, k0, k1, mode) in segs:
        if L <= 0:
            continue
        n = max(1, int(math.ceil(L / ds)))
        h = L / n
        for i in range(n):
            t = (i + 0.5) / n
            k = k0 * (k1 / k0) ** t if (mode == "exp" and k0 * k1 > 0) else k0 + (k1 - k0) * t
            thm = th + k * h * 0.5
            x += math.cos(thm) * h
            z += math.sin(thm) * h
            th += k * h
            s += h
            out.append((x, z, th, s))
    return out


def bisect(f, lo, hi, it=60):
    """单调函数 f 的根（f(lo) 与 f(hi) 异号）。"""
    flo = f(lo)
    for _ in range(it):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if (fm < 0) == (flo < 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return 0.5 * (lo + hi)


def wing_curve(z0, half, x_flat, tip_angle, ramp_ratio=0.60, release=0.18, straight=0.0, ds=8.0):
    """"平 → 起势 → 回落 →（直段）"复合曲线，终点 x 精确落在 half。
    设计量：half 半展、x_flat 平段大致终点、tip_angle 末端切角。ramp_ratio 起势段占弯段比例；
    release 曲率回落到峰值的比例（≥ 0.02，否则退化）；straight 末端直段占比。
    首段（θ = 0 的平段）只平移 x，所以平段长度可以解析求出，不用迭代。"""
    wing_len = max(1.0, (half - x_flat) * 1.08)
    bend = wing_len * (1 - straight)
    L1, L2, Ls = bend * ramp_ratio, bend * (1 - ramp_ratio), wing_len * straight
    release = max(release, 1e-6)

    def segs(lf, k1):
        return [(lf, 0.0, 0.0, "lin"), (L1, 0.0, k1, "lin"), (L2, k1, k1 * release, "exp"), (Ls, 0.0, 0.0, "lin")]
    unit = kappa_curve(segs(0.0, 1e-4), ds=ds)[-1][2] / 1e-4          # θ_end 与 k1 成正比
    k1 = tip_angle / unit
    lf = half - kappa_curve(segs(0.0, k1), ds=ds)[-1][0]
    return kappa_curve(segs(max(0.0, lf), k1), 0.0, z0, 0.0, ds=ds)


def resample(pts, step):
    """按弧长等距重采样（pts 取前两维）。"""
    xy = [(p[0], p[1]) for p in pts]
    out, acc = [xy[0]], 0.0
    for a, b in zip(xy, xy[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        while acc + seg >= step and seg > 0:
            t = (step - acc) / seg
            a = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            out.append(a)
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            acc = 0.0
        acc += seg
    if math.hypot(out[-1][0] - xy[-1][0], out[-1][1] - xy[-1][1]) > 1e-9:
        out.append(xy[-1])
    return out


def polyline_theta(xy):
    """给折线补切向角 → [(x, z, θ)]（中心差分）。"""
    out = []
    for i in range(len(xy)):
        a, b = xy[max(0, i - 1)], xy[min(len(xy) - 1, i + 1)]
        out.append((xy[i][0], xy[i][1], math.atan2(b[1] - a[1], b[0] - a[0])))
    return out


def offset_curve(pts, dist_fn):
    """沿右手法线 (sinθ, −cosθ) 偏移；dist_fn(i, n) 给每点偏移量（可变厚度）。pts 需含 θ。"""
    n = len(pts)
    return [(p[0] + math.sin(p[2]) * dist_fn(i, n), p[1] - math.cos(p[2]) * dist_fn(i, n)) for i, p in enumerate(pts)]


def tapered_stroke(pts, w0, w1, power=1.0):
    """中轴（含 θ）→ 由 w0 渐细到 w1 的闭合轮廓（卷尾、枝干、刀锋）。"""
    n = len(pts)
    left, right = [], []
    for i, p in enumerate(pts):
        w = (w0 + (w1 - w0) * (i / max(1, n - 1)) ** power) / 2
        left.append((p[0] - math.sin(p[2]) * w, p[1] + math.cos(p[2]) * w))
        right.append((p[0] + math.sin(p[2]) * w, p[1] - math.cos(p[2]) * w))
    return left + right[::-1]


def cubic_bezier(a, c1, c2, b, n=64):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append(tuple(u ** 3 * a[k] + 3 * u * u * t * c1[k] + 3 * u * t * t * c2[k] + t ** 3 * b[k] for k in range(len(a))))
    return out


def interp_x(pts, x):
    """x 单调的曲线上按 x 线性插值 z（超出端点取端点）。"""
    if x <= pts[0][0]:
        return pts[0][1]
    lo, hi = 0, len(pts) - 1
    if x >= pts[hi][0]:
        return pts[hi][1]
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if pts[mid][0] <= x:
            lo = mid
        else:
            hi = mid
    a, b = pts[lo], pts[hi]
    t = (x - a[0]) / max(1e-12, b[0] - a[0])
    return a[1] + (b[1] - a[1]) * t


def discrete_curvature(xy):
    """离散带符号曲率（Menger：4·面积 / 三边积），返回 [(s, κ)]，s 为中点弧长。用来画"曲率图"查节奏。
    输入先按等弧长重采样，否则点距不均会放大噪声。"""
    pts = [(p[0], p[1]) for p in xy]
    s, out = 0.0, []
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        s += math.hypot(b[0] - a[0], b[1] - a[1])
        cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        d = math.hypot(b[0] - a[0], b[1] - a[1]) * math.hypot(c[0] - b[0], c[1] - b[1]) * math.hypot(c[0] - a[0], c[1] - a[1])
        out.append((s, 2.0 * cr / d if d > 0 else 0.0))
    return out


# ================================================================ 拟合
def nelder_mead(loss, x0, step, iters=600, bounds=None, tol=1e-10):
    """Nelder–Mead（无 scipy）。bounds = [(lo, hi) 或 None, ...]：试探点投影回边界内。返回 (x, f, evals)。"""
    n = len(x0)

    def clip(v):
        if not bounds:
            return list(v)
        return [min(max(v[j], bounds[j][0]), bounds[j][1]) if bounds[j] else v[j] for j in range(n)]
    simplex = [clip(x0)]
    for i in range(n):
        v = list(x0)
        v[i] += step[i]
        simplex.append(clip(v))
    vals = [loss(v) for v in simplex]
    evals = len(vals)
    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda k: vals[k])
        simplex, vals = [simplex[k] for k in order], [vals[k] for k in order]
        if abs(vals[-1] - vals[0]) <= tol * (abs(vals[0]) + tol):
            break
        cen = [sum(simplex[k][j] for k in range(n)) / n for j in range(n)]
        xr = clip([cen[j] + (cen[j] - simplex[-1][j]) for j in range(n)])
        fr = loss(xr)
        evals += 1
        if fr < vals[0]:
            xe = clip([cen[j] + 2 * (cen[j] - simplex[-1][j]) for j in range(n)])
            fe = loss(xe)
            evals += 1
            simplex[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            simplex[-1], vals[-1] = xr, fr
        else:
            xc = clip([cen[j] + 0.5 * (simplex[-1][j] - cen[j]) for j in range(n)])
            fc = loss(xc)
            evals += 1
            if fc < vals[-1]:
                simplex[-1], vals[-1] = xc, fc
            else:
                for k in range(1, n + 1):
                    simplex[k] = clip([simplex[0][j] + 0.5 * (simplex[k][j] - simplex[0][j]) for j in range(n)])
                    vals[k] = loss(simplex[k])
                    evals += 1
    k = min(range(n + 1), key=lambda i: vals[i])
    return simplex[k], vals[k], evals


def fit_multistart(loss, x0, step, bounds, starts=6, seed=0, iters=600, restarts=2):
    """多起点 + 收敛后原地重启（防止单纯形塌缩）。返回 dict(x, f, at_bound, runs)。
    at_bound：落在边界上的参数下标 —— 有就说明对象 / 参数化可能选错了，要报告，不要直接采用。"""
    rnd = random.Random(seed)
    inits = [list(x0)] + [[rnd.uniform(*b) if b else x0[j] + rnd.uniform(-1, 1) * step[j]
                           for j, b in enumerate(bounds)] for _ in range(starts - 1)]
    runs = []
    for v in inits:
        x, f, _ = nelder_mead(loss, v, step, iters, bounds)
        for _ in range(restarts):
            x, f, _ = nelder_mead(loss, x, [s * 0.3 for s in step], iters, bounds)
        runs.append((f, x))
    runs.sort(key=lambda r: r[0])
    f, x = runs[0]
    at = [j for j, b in enumerate(bounds) if b and (abs(x[j] - b[0]) <= 1e-6 * (1 + abs(b[0])) or abs(x[j] - b[1]) <= 1e-6 * (1 + abs(b[1])))]
    return dict(x=x, f=f, at_bound=at, runs=[r[0] for r in runs])


def dist_to_polyline(points, poly):
    """每个点到折线的最短几何距离（不是竖直差）。有 numpy 时向量化。"""
    P = [(p[0], p[1]) for p in points]
    Q = [(q[0], q[1]) for q in poly]
    if _np is not None:
        p = _np.asarray(P, float)[:, None, :]
        a = _np.asarray(Q[:-1], float)[None]
        b = _np.asarray(Q[1:], float)[None]
        ab = b - a
        t = _np.clip(((p - a) * ab).sum(-1) / _np.maximum((ab * ab).sum(-1), 1e-12), 0, 1)
        d = _np.linalg.norm(p - (a + ab * t[..., None]), axis=-1)
        return d.min(axis=1).tolist()
    out = []
    for (px, pz) in P:
        best = 1e30
        for (ax, az), (bx, bz) in zip(Q, Q[1:]):
            dx, dz = bx - ax, bz - az
            L2 = dx * dx + dz * dz
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / L2))
            best = min(best, math.hypot(px - ax - dx * t, pz - az - dz * t))
        out.append(best)
    return out


def rms_to_polyline(points, poly):
    d = dist_to_polyline(points, poly)
    return math.sqrt(sum(v * v for v in d) / max(1, len(d)))


def signed_dist(points, poly):
    """带符号几何距离：点在折线走向的左侧（x 向右走时即"上方"）为正。
    残差诊断用：对称物体两半的有符号残差沿 x 画在一起——同形 = 形体特征没进模型，反形 = 位姿 / 不对称。"""
    d = dist_to_polyline(points, poly)
    out = []
    for (px, pz), dv in zip(points, d):
        best, sg = 1e30, 1.0
        for (ax, az), (bx, bz) in zip(poly, poly[1:]):
            dx, dz = bx - ax, bz - az
            L2 = dx * dx + dz * dz
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / L2))
            e = math.hypot(px - ax - dx * t, pz - az - dz * t)
            if e < best:
                best, sg = e, (1.0 if dx * (pz - az) - dz * (px - ax) >= 0 else -1.0)
        out.append(sg * dv)
    return out


def huber(d, delta):
    """Huber 损失的均值：|d| ≤ delta 取 d²/2，之外线性。遮挡、挂件、取点错误不会把整条曲线拉偏。
    delta 取 1.5–2 倍取点噪声（像素级参考约 1.5 px）。"""
    s = 0.0
    for v in d:
        a = abs(v)
        s += 0.5 * a * a if a <= delta else delta * (a - 0.5 * delta)
    return s / max(1, len(d))


def fair_kappa(segs, sigma, ds=None):
    """拟合之后的顺滑（取势）：κ(s) 与高斯核（σ，弧长单位）卷积，返回逐格常曲率的 segs，直接给 kappa_curve。
    - 每一处转折的转角质量只在弧长上摊开，不增不减：总转角（末端切角）严格不变，端部不外溢；
    - 拐角变成曲率连续的缓弯；单个转角 Δθ 摊开后最小曲率半径 ≈ σ·√(2π)/Δθ；
    - σ 是审美参数（转折的软硬），由眼睛定；拟合给的是骨架（转折位置、转角），不要让 σ 去追数据。"""
    if sigma <= 0:
        return list(segs)
    L = sum(sg[0] for sg in segs if sg[0] > 0)
    h = ds or max(L / 4000.0, sigma / 8.0)
    n = max(2, int(math.ceil(L / h)))
    h = L / n
    turn = [0.0] * n                                  # 每格的转角（细分积分，极短的圆角段也计入）
    s0 = 0.0
    for (Ls, k0, k1, mode) in segs:
        if Ls <= 0:
            continue
        m = max(4, int(math.ceil(Ls / (h / 8.0))))
        for i in range(m):
            t = (i + 0.5) / m
            k = k0 * (k1 / k0) ** t if (mode == "exp" and k0 * k1 > 0) else k0 + (k1 - k0) * t
            c = min(n - 1, int((s0 + Ls * t) / h))
            turn[c] += k * Ls / m
        s0 += Ls
    R = int(math.ceil(4 * sigma / h))
    ker = [math.exp(-0.5 * (j * h / sigma) ** 2) for j in range(-R, R + 1)]
    out = [0.0] * n
    for i, tq in enumerate(turn):                      # 散射：每格的转角按核分到邻格，核在端部截断后重新归一
        if tq == 0.0:
            continue
        lo, hi = max(0, i - R), min(n - 1, i + R)
        w = ker[lo - i + R:hi - i + R + 1]
        sw = sum(w)
        for j, wj in zip(range(lo, hi + 1), w):
            out[j] += tq * wj / sw
    return [(h, t / h, t / h, "lin") for t in out]


def fillet_seg(r, dth):
    """拐点 = 半径 r、转角 dth（带符号，弧度）的一小段圆弧，给 kappa_curve 当一段用。
    轮廓由几个构件的外缘拼成时，交接处是拐角而不是缓弯；用光滑曲率族硬拟会在拐角两侧来回振荡。"""
    r = max(r, 1e-9)
    k = math.copysign(1.0 / r, dth) if dth else 0.0
    return (r * abs(dth), k, k, "lin")


# ================================================================ 过渡
def smoothstep(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def smoothmax(a, b, k):
    """log-sum-exp 光滑 max：k ≈ 圆角半径量级。"""
    m = max(a, b)
    return m + k * math.log(math.exp((a - m) / k) + math.exp((b - m) / k))


def smoothmin(a, b, k):
    return -smoothmax(-a, -b, k)


# ================================================================ 受控随机
def rng(seed, key):
    """件级随机源：同 seed + 同件名 → 同结果。"""
    h = hashlib.md5(("%s:%s" % (seed, key)).encode("utf-8")).hexdigest()
    return random.Random(int(h[:12], 16))


def _lattice(i, seed):
    h = hashlib.md5(("%s|%d" % (seed, i)).encode("utf-8")).hexdigest()
    return int(h[:8], 16) / float(0xFFFFFFFF) * 2.0 - 1.0


def noise1(x, seed):
    """1D 值噪声，约 [-1, 1]，C1 连续。"""
    i = math.floor(x)
    t = x - i
    t = t * t * (3 - 2 * t)
    return _lattice(i, seed) * (1 - t) + _lattice(i + 1, seed) * t


def fbm1(x, seed, octaves=3, gain=0.5, lac=2.0):
    """多尺度噪声，归一化到约 [-1, 1]。"""
    amp, freq, tot, norm = 1.0, 1.0, 0.0, 0.0
    for o in range(octaves):
        tot += amp * noise1(x * freq, "%s/%d" % (seed, o))
        norm += amp
        amp *= gain
        freq *= lac
    return tot / norm


# ================================================================ 成形：扫掠 / 放样
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    L = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / L, a[1] / L, a[2] / L)


def _axpy(k, a, b):
    return (b[0] + k * a[0], b[1] + k * a[1], b[2] + k * a[2])


def rmf_frames(path, up=(0.0, 0.0, 1.0)):
    """旋转最小标架（Wang et al. 2008 双反射法）。返回 [(T, R, S)]，R×S = T。
    逐点 to_track_quat / Frenet 标架在拐点和接近竖直时会翻转扭曲；RMF 不会。"""
    n = len(path)
    T = [_norm(_sub(path[min(n - 1, i + 1)], path[max(0, i - 1)])) for i in range(n)]
    r = _sub(up, tuple(_dot(up, T[0]) * c for c in T[0]))
    if _dot(r, r) < 1e-12:
        r = _cross(T[0], (1.0, 0.0, 0.0))
    R = [_norm(r)]
    for i in range(n - 1):
        v1 = _sub(path[i + 1], path[i])
        c1 = _dot(v1, v1)
        if c1 < 1e-18:
            R.append(R[-1])
            continue
        rL = _axpy(-2.0 / c1 * _dot(v1, R[i]), v1, R[i])
        tL = _axpy(-2.0 / c1 * _dot(v1, T[i]), v1, T[i])
        v2 = _sub(T[i + 1], tL)
        c2 = _dot(v2, v2)
        R.append(_norm(rL if c2 < 1e-18 else _axpy(-2.0 / c2 * _dot(v2, rL), v2, rL)))
    return [(T[i], R[i], _cross(T[i], R[i])) for i in range(n)]


def sweep(profile, path, closed=True, scale_fn=None, up=(0.0, 0.0, 1.0)):
    """截面 profile [(u, v)]（在 R-S 平面，逆时针 → 法线朝外）沿 path [(x, y, z)] 扫掠。
    scale_fn(i, n) 给逐站缩放（收分、渐细）。返回 (verts, quads)，quads 是顶点下标四元组。端面不封（需要时用截面 n-gon 封口）。"""
    F = rmf_frames(path, up)
    m, verts, quads = len(profile), [], []
    for i, (P, (T, R, S)) in enumerate(zip(path, F)):
        k = scale_fn(i, len(path)) if scale_fn else 1.0
        for (u, v) in profile:
            verts.append(tuple(P[c] + k * (u * R[c] + v * S[c]) for c in range(3)))
    jn = m if closed else m - 1
    for i in range(len(path) - 1):
        for j in range(jn):
            j2 = (j + 1) % m
            quads.append((i * m + j, i * m + j2, (i + 1) * m + j2, (i + 1) * m + j))
    return verts, quads


def loft(sections, closed=True):
    """多截面放样：sections = [[(x, y, z) × m], ...]，每个截面点数相同、起点对齐、同向。返回 (verts, quads)。"""
    m = len(sections[0])
    verts = [p for sec in sections for p in sec]
    jn = m if closed else m - 1
    quads = [(i * m + j, i * m + (j + 1) % m, (i + 1) * m + (j + 1) % m, (i + 1) * m + j)
             for i in range(len(sections) - 1) for j in range(jn)]
    return verts, quads


# ================================================================ 分布
def poisson_disk(w, h, r, seed=0, k=30):
    """Bridson 泊松盘采样：矩形 [0,w]×[0,h] 内任意两点距离 ≥ r，分布均匀不成团。"""
    rnd = random.Random(seed)
    cell = r / math.sqrt(2)
    gw, gh = int(math.ceil(w / cell)), int(math.ceil(h / cell))
    grid = [[-1] * gw for _ in range(gh)]
    pts, active = [], []

    def put(p):
        pts.append(p)
        active.append(len(pts) - 1)
        grid[int(p[1] / cell)][int(p[0] / cell)] = len(pts) - 1
    put((rnd.uniform(0, w), rnd.uniform(0, h)))
    while active:
        i = active[rnd.randrange(len(active))]
        px, py = pts[i]
        for _ in range(k):
            a, d = rnd.uniform(0, 2 * math.pi), rnd.uniform(r, 2 * r)
            q = (px + d * math.cos(a), py + d * math.sin(a))
            if not (0 <= q[0] < w and 0 <= q[1] < h):
                continue
            cx, cy = int(q[0] / cell), int(q[1] / cell)
            ok = True
            for yy in range(max(0, cy - 2), min(gh, cy + 3)):
                for xx in range(max(0, cx - 2), min(gw, cx + 3)):
                    j = grid[yy][xx]
                    if j >= 0 and math.hypot(pts[j][0] - q[0], pts[j][1] - q[1]) < r:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                put(q)
                break
        else:
            active.remove(i)
    return pts


# ================================================================ 距离场
def polygon_sdf(p, poly):
    """点到闭合多边形的有符号距离：内负外正（偶奇规则判内外）。"""
    best, inside = 1e30, False
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        best = min(best, math.hypot(p[0] - a[0] - dx * t, p[1] - a[1] - dy * t))
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < a[0] + (p[1] - a[1]) * dx / dy:
            inside = not inside
    return -best if inside else best


def relief_height(d, H, bevel, dome=0.15):
    """轮廓 → 浮雕剖面：d 为有符号距离（内负）。边缘 bevel 宽内斜切升到 H·(1−dome)，再往里微鼓到 H。
    "轮廓锐利、面饱满、底平"；不要用照片灰度当高度。"""
    if d >= 0:
        return 0.0
    t = -d
    if t <= bevel:
        return H * (1 - dome) * t / bevel
    return H * (1 - dome) + H * dome * (1 - math.exp(-(t - bevel) / (3 * bevel)))


# ================================================================ 自检
def selftest():
    rep = []

    def check(name, ok, info):
        rep.append((name, ok, info))
        print("%-4s %-22s %s" % ("ok" if ok else "FAIL", name, info))

    # 1 常曲率 → 圆：半径误差
    R0 = 1000.0
    c = kappa_curve([(math.pi * R0, 1 / R0, 1 / R0, "lin")], ds=2.0)
    err = max(abs(math.hypot(x, z - R0) - R0) for (x, z, _, _) in c)
    check("kappa_curve 圆", err < 1e-3, "半圆半径最大误差 %.2e mm" % err)
    # 2 欧拉螺线：末端角 = k1·L/2
    L, k1 = 3000.0, 4e-4
    th = kappa_curve([(L, 0.0, k1, "lin")], ds=4.0)[-1][2]
    check("欧拉螺线末端角", abs(th - k1 * L / 2) < 1e-9, "θ_end %.6f vs %.6f" % (th, k1 * L / 2))
    # 3 wing_curve 终点落在 half、末端切角 = tip
    w = wing_curve(9000.0, 15000.0, 5700.0, math.radians(20.2), 1.0, 0.06, 0.73)
    check("wing_curve 落点/切角", abs(w[-1][0] - 15000.0) < 1e-6 and abs(math.degrees(w[-1][2]) - 20.2) < 1e-6,
          "x_end %.6f, tip %.6f°" % (w[-1][0], math.degrees(w[-1][2])))
    # 4 离散曲率还原欧拉螺线 κ(s)
    sp = kappa_curve([(L, 0.0, k1, "lin")], ds=1.0)
    kk = discrete_curvature(resample(sp, 20.0))
    e = max(abs(k - k1 * s / L) for s, k in kk[2:-2])
    check("discrete_curvature", e < 0.01 * k1, "κ 最大偏差 %.2f%% 峰值" % (100 * e / k1))
    # 5 resample 等距
    rs = resample(sp, 50.0)
    gaps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(rs, rs[1:-1])]
    check("resample", max(abs(g - 50.0) for g in gaps) < 0.5, "间距 %.3f–%.3f mm" % (min(gaps), max(gaps)))
    # 6 几何距离：点到直线
    d = dist_to_polyline([(5.0, 3.0), (-2.0, 0.0)], [(0, 0), (10, 0)])
    check("dist_to_polyline", abs(d[0] - 3) < 1e-9 and abs(d[1] - 2) < 1e-9, "%s" % [round(v, 6) for v in d])
    # 7 拟合：从带噪点云还原 wing_curve 参数
    truth = (9000.0, 5700.0, 20.2, 0.7, 0.2)
    rr = random.Random(1)
    gt = wing_curve(truth[0], 15000.0, truth[1], math.radians(truth[2]), truth[3], truth[4], ds=10.0)
    data = [(x + rr.gauss(0, 8), z + rr.gauss(0, 8)) for (x, z) in resample(gt, 120.0)]

    def loss(v):
        cv = wing_curve(v[0], 15000.0, v[1], math.radians(v[2]), v[3], v[4], ds=30.0)
        return rms_to_polyline(data, cv) ** 2
    fr = fit_multistart(loss, [8800.0, 5000.0, 15.0, 0.5, 0.3], [100.0, 400.0, 3.0, 0.1, 0.05],
                        [(8000, 10000), (3000, 9000), (5, 40), (0.2, 1.0), (0.02, 1.0)], starts=4, iters=400, restarts=1)
    xb = fr["x"]
    ok = abs(xb[0] - truth[0]) < 15 and abs(xb[2] - truth[2]) < 0.5 and math.sqrt(fr["f"]) < 12
    check("fit_multistart 还原", ok, "RMS %.1f mm（噪声 8 mm）；z0 %.0f/%.0f  tip %.2f/%.2f°  x_flat %.0f/%.0f" %
          (math.sqrt(fr["f"]), xb[0], truth[0], xb[2], truth[2], xb[1], truth[1]))
    # 8 smoothmax 介于 max 与 max + k·ln2
    v = smoothmax(1.0, 1.0, 0.1)
    check("smoothmax", abs(v - (1 + 0.1 * math.log(2))) < 1e-12, "%.6f" % v)
    # 9 随机可复现
    check("rng 可复现", rng(7, "tile_3").random() == rng(7, "tile_3").random() and rng(7, "a").random() != rng(7, "b").random(), "同件同值、异件异值")
    fb = [fbm1(i * 0.37, "s") for i in range(2000)]
    check("fbm1 范围/均值", max(abs(x) for x in fb) <= 1.0 and abs(sum(fb) / len(fb)) < 0.1, "max|v| %.3f 均值 %.3f" % (max(abs(x) for x in fb), sum(fb) / len(fb)))
    # 10 RMF：沿螺旋扫掠，相邻标架 R 的变化应平滑（无翻转），且 R ⊥ T
    hel = [(300 * math.cos(t), 300 * math.sin(t), 80 * t) for t in [i * 0.05 for i in range(400)]]
    F = rmf_frames(hel)
    jump = max(math.acos(max(-1.0, min(1.0, _dot(F[i][1], F[i + 1][1])))) for i in range(len(F) - 1))
    ortho = max(abs(_dot(t, r)) for (t, r, _) in F)
    check("rmf_frames 不翻转", jump < 0.06 and ortho < 1e-9, "相邻 R 最大转角 %.4f rad，R·T 最大 %.1e" % (jump, ortho))
    # 11 sweep：圆截面沿直线 → 法线朝外、quad 数正确
    circ = [(50 * math.cos(2 * math.pi * j / 16), 50 * math.sin(2 * math.pi * j / 16)) for j in range(16)]
    vs, qs = sweep(circ, [(0, 0, 0), (0, 0, 100), (0, 0, 200)])
    out = 0
    for q in qs:
        a, b, d_ = vs[q[0]], vs[q[1]], vs[q[3]]
        nrm = _cross(_sub(b, a), _sub(d_, a))
        ctr = tuple(sum(vs[k][c] for k in q) / 4 for c in range(3))
        out += _dot(nrm, (ctr[0], ctr[1], 0.0)) > 0
    check("sweep 法线朝外", len(qs) == 32 and out == 32, "%d quads，朝外 %d" % (len(qs), out))
    # 12 泊松盘：最小间距 ≥ r
    pd = poisson_disk(1000, 600, 40, seed=3)
    md = min(math.hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(pd) for b in pd[i + 1:])
    check("poisson_disk", md >= 40 - 1e-9 and len(pd) > 150, "%d 点，最小间距 %.2f" % (len(pd), md))
    # 13 多边形 SDF：正方形中心 -50，外侧 +10
    sq = [(0, 0), (100, 0), (100, 100), (0, 100)]
    check("polygon_sdf", abs(polygon_sdf((50, 50), sq) + 50) < 1e-9 and abs(polygon_sdf((110, 50), sq) - 10) < 1e-9, "中心 %.1f，外侧 %.1f" % (polygon_sdf((50, 50), sq), polygon_sdf((110, 50), sq)))
    hs = [relief_height(-t, 10.0, 4.0) for t in (0, 2, 4, 20)]
    check("relief_height 单调", hs == sorted(hs) and hs[0] == 0 and hs[-1] <= 10, "%s" % [round(h, 2) for h in hs])
    # 14 有符号距离：上正下负
    sd = signed_dist([(5.0, 3.0), (5.0, -2.0)], [(0, 0), (10, 0)])
    check("signed_dist", abs(sd[0] - 3) < 1e-9 and abs(sd[1] + 2) < 1e-9, "%s" % sd)
    # 15 Huber：直线 + 10% 遮挡块（+40）。L2 被拉偏，Huber 还原
    rr = random.Random(4)
    pts = [(x, 0.3 * x + rr.gauss(0, 1.0) + (40.0 if 600 <= x < 700 else 0.0)) for x in range(0, 1000, 5)]
    line = lambda v: [(0.0, v[0]), (1000.0, v[0] + 1000.0 * v[1])]
    fl2 = fit_multistart(lambda v: rms_to_polyline(pts, line(v)) ** 2, [0.0, 0.2], [5.0, 0.05], [None, None], starts=2, iters=300, restarts=1)
    fhb = fit_multistart(lambda v: huber(dist_to_polyline(pts, line(v)), 1.5), [0.0, 0.2], [5.0, 0.05], [None, None], starts=2, iters=300, restarts=1)
    dev = lambda v: max(abs(v[0] + x * (v[1] - 0.3)) for x in (0.0, 1000.0))      # 拟合直线偏离真值的最大竖直量
    check("huber 抗遮挡", dev(fhb["x"]) < 0.6 and dev(fl2["x"]) > 3 * dev(fhb["x"]),
          "偏离真值最大 L2 %.2f / Huber %.2f（噪声 1.0，遮挡块 +40 占 10%%）" % (dev(fl2["x"]), dev(fhb["x"])))
    # 16 拐点段：直 → 圆角 r=100 转 60° → 直，末端角 60°，圆角长 = rΔθ
    kc = kappa_curve([(500.0, 0, 0, "lin"), fillet_seg(100.0, math.radians(60)), (500.0, 0, 0, "lin")], ds=1.0)
    check("fillet_seg 拐点", abs(math.degrees(kc[-1][2]) - 60) < 1e-9 and abs(kc[-1][3] - (1000 + 100 * math.pi / 3)) < 1e-6,
          "末端角 %.6f°，总长 %.3f" % (math.degrees(kc[-1][2]), kc[-1][3]))
    # 17 fair_kappa：同一拐角（r=10 的急拐 60°）顺滑 σ=80 → 末端角不变、最小半径 ≈ σ√(2π)/Δθ、曲率连续
    raw = [(500.0, 0, 0, "lin"), fillet_seg(10.0, math.radians(60)), (500.0, 0, 0, "lin")]
    fs = fair_kappa(raw, 80.0)
    fc = kappa_curve(fs, ds=2.0)
    kmax = max(abs(sg[1]) for sg in fs)
    jump = max(abs(a[1] - b[1]) for a, b in zip(fs, fs[1:]))
    r_th = 80.0 * math.sqrt(2 * math.pi) / math.radians(60)
    check("fair_kappa 顺滑", abs(math.degrees(fc[-1][2]) - 60) < 1e-6 and abs(1 / kmax - r_th) < 0.03 * r_th and jump < 1.05 * 0.607 * (fs[0][0] / 80.0) * kmax,   # 逐格常曲率：相邻格跳变上限 = 高斯最大斜率 × 格宽
          "末端角 %.6f°；最小半径 %.1f（理论 %.1f）；相邻格 κ 跳变 / 峰值 %.3f（格宽 σ/8 的理论上限 0.076）" % (math.degrees(fc[-1][2]), 1 / kmax, r_th, jump / kmax))
    bad = [n for n, ok, _ in rep if not ok]
    print("FORMKIT_SELFTEST", "pass" if not bad else "fail %s" % bad, "(%d 项)" % len(rep))
    return not bad


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print(__doc__)
