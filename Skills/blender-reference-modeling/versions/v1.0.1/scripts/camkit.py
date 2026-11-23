# -*- coding: utf-8 -*-
"""
camkit：参考视角的相机、沿视线对位、按"最低可见边"算残差。纯 numpy（拟合相机时用 scipy，可缺）。
来源：修仙牌楼 ref02 翼角对比（2026-11-20/21）里反复用到的那套量测，抽成与项目无关的函数。[实测]

约定
  像平面坐标 (u, v)：u 向右、v 向上（和 ref_trace.unpose 之后的坐标一致，不是图像行号）。
  Pinhole(eye, fwd, up, f, pp)：针孔相机；project(P) → (uv, depth)。depth = 沿视轴的距离。
  front_cam(F, D, h, phi, pp_v)：正对 +y、仰角 phi、光心 (0, −D, h) 的常用参数化（ref02 就是它）。

三件事
  1. project / slide：P_new = O + (P − O)·s 不改像点。把模型某条线沿视线挪到新的平面位置 = 在这张参考上"按新平面重拟合"。
     比较两种结构时，先把各自的线对位到同一像点，再比别的；不然比出来的是"有没有对位"，不是结构（C1 吃过这个亏）。
  2. envelope：几条 3D 候选线投影后取下包络 = 参考里"最低可见边"的代理（按构建规则，哪个构件在哪里有就放哪条）。
  3. line_residual：观测点到模型折线的带符号距离（上方为正）、RMS、按 u 分段的均值。
"""
import math
import numpy as np


class Pinhole:
    def __init__(self, eye, fwd, up, f, pp=(0.0, 0.0)):
        self.eye = np.asarray(eye, float)
        fwd = np.asarray(fwd, float)
        self.fwd = fwd / np.linalg.norm(fwd)
        rt = np.cross(self.fwd, np.asarray(up, float))
        self.rt = rt / np.linalg.norm(rt)
        self.up = np.cross(self.rt, self.fwd)
        self.f = float(f)
        self.pp = np.asarray(pp, float)

    def project(self, P):
        """P: (n, 3) → uv (n, 2)，depth (n,)。depth ≤ 0 的点在相机后面（uv 为 nan）。"""
        v = np.atleast_2d(np.asarray(P, float)) - self.eye
        dep = v @ self.fwd
        with np.errstate(divide="ignore", invalid="ignore"):
            uv = np.stack([self.f * (v @ self.rt) / dep, self.f * (v @ self.up) / dep], 1) + self.pp
        uv[dep <= 0] = np.nan
        return uv, dep

    def uv(self, P):
        return self.project(P)[0]

    # ------------------------------------------------------------ 沿视线对位
    def slide(self, P, g, s_lo=0.5, s_hi=2.0, it=80):
        """把 P 沿视线（光心 → P）挪到 g(Q) = 0 的位置，像点不变。g 在 [s_lo, s_hi] 两端须异号。"""
        P = np.asarray(P, float)
        d = P - self.eye
        f = lambda s: g(self.eye + d * s)
        a, b = s_lo, s_hi
        fa, fb = f(a), f(b)
        if fa * fb > 0:
            raise ValueError("slide：g 在 s∈[%.2f, %.2f] 不变号（%.3g, %.3g）" % (a, b, fa, fb))
        for _ in range(it):
            m = 0.5 * (a + b)
            fm = f(m)
            if fa * fm <= 0:
                b, fb = m, fm
            else:
                a, fa = m, fm
        return self.eye + d * (0.5 * (a + b))

    def slide_to_plane(self, P, n, c):
        """挪到平面 n·Q = c 上（闭式解）。竖直平面（如 45° 戗脊线 x + y = xs）用 n = (1, 1, 0)、c = xs。"""
        P, n = np.asarray(P, float), np.asarray(n, float)
        d = P - self.eye
        den = float(n @ d)
        if abs(den) < 1e-12:
            raise ValueError("slide_to_plane：视线与平面平行")
        return self.eye + d * ((c - float(n @ self.eye)) / den)


def front_cam(F, D, h, phi, pp_v=0.0):
    """正对 +y：光心 (0, −D, h)，绕 x 轴仰 phi（正 = 向上看）。与 xiuxian eave_common.project 逐点一致。"""
    c, s = math.cos(phi), math.sin(phi)
    return Pinhole((0.0, -D, h), (0.0, c, s), (0.0, -s, c), F, (0.0, pp_v))


def look_at(eye, target, f, pp=(0.0, 0.0), up=(0.0, 0.0, 1.0)):
    return Pinhole(eye, np.asarray(target, float) - np.asarray(eye, float), up, f, pp)


# ---------------------------------------------------------------- 残差
def signed_dist(points, poly):
    """点到折线的带符号距离（沿折线前进方向左侧 = 正；折线 u 递增时即"上方为正"）。"""
    P = np.asarray(points, float)
    Q = np.asarray(poly, float)
    a, b = Q[:-1], Q[1:]
    ab = b - a
    L2 = np.maximum((ab ** 2).sum(1), 1e-12)
    ap = P[:, None, :] - a[None]
    t = np.clip((ap * ab[None]).sum(2) / L2[None], 0, 1)
    dv = P[:, None, :] - (a[None] + t[..., None] * ab[None])
    dist = np.sqrt((dv ** 2).sum(2))
    j = dist.argmin(1)
    i = np.arange(len(P))
    cr = ab[j, 0] * ap[i, j, 1] - ab[j, 1] * ap[i, j, 0]
    return np.where(cr >= 0, 1.0, -1.0) * dist[i, j]


def envelope(polylines, step=0.5, side="low", u0=None):
    """几条 2D 折线（u 任意走向）在 u 网格上取下（low）/ 上（high）包络，返回 (m, 2)，u 递增。"""
    segs = np.concatenate([np.stack([p[:-1], p[1:]], 1) for p in polylines if len(p) > 1], 0)
    segs = segs[np.all(np.isfinite(segs.reshape(len(segs), -1)), 1)]
    umin = min(segs[:, :, 0].min(), 0.0) if u0 is None else u0
    U = np.arange(umin, segs[:, :, 0].max() + step, step)
    V = np.full(len(U), np.inf if side == "low" else -np.inf)
    a, b = segs[:, 0], segs[:, 1]
    lo, hi = np.minimum(a[:, 0], b[:, 0]), np.maximum(a[:, 0], b[:, 0])
    pick = np.minimum if side == "low" else np.maximum
    for k in range(len(segs)):
        i0, i1 = int(np.ceil((lo[k] - umin) / step)), int(np.floor((hi[k] - umin) / step))
        if i1 < i0:
            continue
        us = U[i0:i1 + 1]
        du = b[k, 0] - a[k, 0]
        t = (us - a[k, 0]) / du if abs(du) > 1e-9 else np.zeros_like(us)
        V[i0:i1 + 1] = pick(V[i0:i1 + 1], a[k, 1] + t * (b[k, 1] - a[k, 1]))
    ok = np.isfinite(V)
    return np.c_[U[ok], V[ok]]


def line_residual(obs, poly, bins=()):
    """obs (n, 2) 到 poly 的带符号距离；返回 dict(rms, r, bins={"a-b": 均值})。bins 按 obs 的 u 分段。"""
    r = signed_dist(obs, poly)
    out = dict(rms=round(float(np.sqrt(np.mean(r ** 2))), 2), r=r)
    obs = np.asarray(obs, float)
    out["bins"] = {"%g-%g" % (a, b): (round(float(np.mean(r[m])), 1) if (m := (obs[:, 0] >= a) & (obs[:, 0] < b)).any() else None)
                   for a, b in bins}
    return out


def residual_pair(cam, top3d, lows3d, obs_top, obs_low, bins=(), step=0.5, to_obs=None):
    """一次算两条线：top = 一条模型线（如檐口线）；low = 若干候选线的下包络（最低可见边）。
    to_obs：可选，把相机 uv 再变到观测坐标（如项目的去位姿 / 主点约定），缺省恒等。"""
    tf = to_obs or (lambda q: q)
    pt = tf(cam.uv(top3d))
    env = envelope([tf(cam.uv(l)) for l in lows3d], step=step)
    rt = line_residual(obs_top, pt, bins)
    rl = line_residual(obs_low, env, bins)
    return dict(top_rms=rt["rms"], low_rms=rl["rms"], top_bins=rt["bins"], low_bins=rl["bins"], env=env)


# ---------------------------------------------------------------- 拟合相机（只调两三个量）
def fit_front_cam(residual_fn, x0, free=("h", "phi"), fixed=None, bounds=None):
    """residual_fn(cam) → 残差向量。x0/fixed：dict(F, D, h, phi, pp_v)。只放开 free 里的量（仰角、高度这类两三个）。
    数据定不了的量（如相机距离）换起点会漂：不要报成拟合值，也不要进 spec。"""
    from scipy.optimize import least_squares
    base = {"pp_v": 0.0, **(fixed or {}), **x0}
    keys = list(free)

    def mk(v):
        p = dict(base, **dict(zip(keys, v)))
        return front_cam(p["F"], p["D"], p["h"], p["phi"], p["pp_v"])
    lb = [bounds[k][0] if bounds and k in bounds else -np.inf for k in keys]
    ub = [bounds[k][1] if bounds and k in bounds else np.inf for k in keys]
    res = least_squares(lambda v: residual_fn(mk(v)), [base[k] for k in keys], bounds=(lb, ub))
    best = dict(base, **dict(zip(keys, res.x)))
    return best, mk(res.x), res


# ---------------------------------------------------------------- 自检
def selftest():
    rs = np.random.default_rng(0)
    cam = front_cam(2600.0, 70000.0, -4500.0, 0.18, 380.0)
    P = rs.uniform([-8000, -3000, 9000], [8000, 3000, 13000], (50, 3))
    uv = cam.uv(P)
    # 1) 与 eave_common.project 的显式公式一致
    F, D, h, phi = 2600.0, 70000.0, -4500.0, 0.18
    vy, vz = P[:, 1] + D, P[:, 2] - h
    dep = vy * math.cos(phi) + vz * math.sin(phi)
    ref = np.stack([F * P[:, 0] / dep, 380.0 + F * (-vy * math.sin(phi) + vz * math.cos(phi)) / dep], 1)
    assert np.abs(uv - ref).max() < 1e-9, "front_cam 与显式公式不一致"
    # 2) slide / slide_to_plane 不改像点、落在目标上
    Q = np.array([cam.slide(p, lambda q: q[1] - 500.0) for p in P])
    assert np.abs(cam.uv(Q) - uv).max() < 1e-6 and np.abs(Q[:, 1] - 500.0).max() < 1e-3
    R = np.array([cam.slide_to_plane(p, (1, 1, 0), 6000.0) for p in P])
    assert np.abs(cam.uv(R) - uv).max() < 1e-6 and np.abs(R[:, 0] + R[:, 1] - 6000.0).max() < 1e-6
    # 3) envelope：两条交叉直线的下包络 = 折线 min
    a = np.c_[np.linspace(0, 10, 11), np.linspace(0, 10, 11)]
    b = np.c_[np.linspace(0, 10, 11), np.linspace(10, 0, 11)]
    e = envelope([a, b], step=1.0)
    assert np.allclose(e[:, 1], np.minimum(e[:, 0], 10 - e[:, 0]))
    # 4) 残差符号：上方为正
    r = line_residual(np.array([[5.0, 6.0], [5.0, 4.0]]), np.array([[0.0, 5.0], [10.0, 5.0]]), bins=((0, 10),))
    assert r["r"][0] > 0 > r["r"][1] and abs(r["rms"] - 1.0) < 1e-9
    # 5) 拟合相机：只放开 h、phi，从偏离起点回到真值
    obs = cam.uv(P)
    best, _, _ = fit_front_cam(lambda c: (c.uv(P) - obs).ravel(), dict(F=F, D=D, h=-3000.0, phi=0.10, pp_v=380.0))
    assert abs(best["h"] - h) < 1.0 and abs(best["phi"] - phi) < 1e-5, best
    print("camkit selftest ok：投影 / 沿视线对位 / 包络 / 残差符号 / 两参相机拟合")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest"):
        selftest()
    else:
        print(__doc__)
