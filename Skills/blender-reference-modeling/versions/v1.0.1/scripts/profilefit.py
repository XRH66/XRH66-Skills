# -*- coding: utf-8 -*-
"""
profilefit：支承体（手臂、柱身、器物腹、壳体）从参考剪影拟合（方法层 + 几何原语，领域无关，纯 numpy）。
原理见 references/fitting.md §5（单视图）、§2b（多视图）。

模型：轴线 P0 → P1（v ∈ [0, 1]），截面超椭圆，半轴 a(v)（沿 ax 方向）、b(v)（沿 bx 方向），指数 n（2 = 椭圆，越大越方）。
尺寸曲线 bump(v; e0, e1, vp, peak, k)：两端值 e0 / e1 的直线 + 在 vp 处抬到 peak 的光滑鼓包（k 越大鼓包越窄）。
  5 个可读参数——"两端多粗、哪里最粗、最粗多少、鼓得多集中"；peak = 直线在 vp 的值时退化为直管（对照用）。

  bump(v, p)                                 p = (e0, e1, vp, peak, k)
  Body(P0, P1, ax, a, b, n)                  a / b：v → 半轴（函数）；ax：截面 a 方向（与轴正交化）
    .ring(v, m) / .surface() / .polys(nv, m, tag)   截面点 / support.Surface（u = 角度，v）/ 闭合四边面网格
  widths(body, cam, vs, m)                   每站投影后的剪影宽度（垂直于投影轴线方向的跨度，透视下逐点投影）
  fit(views, P0, P1, ax, p0a, p0b=None, ratio=None, n=2, huber_px=1.5, linear=False)
      views = [(cam, vs, w_obs)]；p0b = None 时 b = ratio·a（单视图：另一向用扁率先验）
      → dict(pa, pb, body, rms_px, per_view, at_bound)。at_bound 非空 = 结构选错，不放宽边界
[自检：合成双视图——两向尺寸曲线恢复误差 < 1%，直管模型残差大 ≥ 5 倍；单视图 + 扁率先验也收敛。还没在真实参考上跑过]
"""
import math
import numpy as np
import formkit


def bump(v, p):
    e0, e1, vp, peak, k = p
    v = np.asarray(v, float)
    vp = min(max(vp, 1e-3), 1 - 1e-3)
    base = e0 + (e1 - e0) * v
    g = np.where(v < vp, np.sin(0.5 * math.pi * np.clip(v / vp, 0, 1)), np.sin(0.5 * math.pi * np.clip((1 - v) / (1 - vp), 0, 1)))
    return base + (peak - (e0 + (e1 - e0) * vp)) * np.abs(g) ** max(k, 0.2)


class Body:
    def __init__(self, P0, P1, ax, a, b, n=2.0):
        self.P0, self.P1 = np.asarray(P0, float), np.asarray(P1, float)
        t = self.P1 - self.P0
        self.t = t / np.linalg.norm(t)
        ax = np.asarray(ax, float)
        ax = ax - self.t * (ax @ self.t)
        self.ax = ax / np.linalg.norm(ax)
        self.bx = np.cross(self.t, self.ax)
        self.a, self.b, self.n = a, b, n

    def _se(self, th):
        c, s = np.cos(th), np.sin(th)
        e = 2.0 / self.n
        return np.sign(c) * np.abs(c) ** e, np.sign(s) * np.abs(s) ** e

    def point(self, u, v):
        c, s = self._se(u)
        return self.P0 + (self.P1 - self.P0) * v + self.ax * (float(self.a(v)) * c) + self.bx * (float(self.b(v)) * s)

    def ring(self, v, m=48):
        th = np.linspace(0, 2 * math.pi, m, endpoint=False)
        c, s = self._se(th)
        o = self.P0 + (self.P1 - self.P0) * v
        return o + np.outer(float(self.a(v)) * c, self.ax) + np.outer(float(self.b(v)) * s, self.bx)

    def surface(self):
        import support
        return support.Surface(self.point)

    def polys(self, nv=24, m=32, tag="support"):
        R = [self.ring(v, m) for v in np.linspace(0, 1, nv)]
        out = []
        for A, B in zip(R, R[1:]):
            for i in range(m):
                j = (i + 1) % m
                out.append((np.array([A[i], B[i], B[j], A[j]]), tag))
        return out + [(R[0].copy(), tag), (R[-1][::-1].copy(), tag)]


def widths(body, cam, vs, m=48):
    a, b = cam.uv([body.P0, body.P1])
    d = b - a
    d = d / np.linalg.norm(d)
    perp = np.array([-d[1], d[0]])
    out = []
    for v in vs:
        q = cam.uv(body.ring(v, m)) @ perp
        out.append(q.max() - q.min())
    return np.array(out)


def fit(views, P0, P1, ax, p0a, p0b=None, ratio=None, n=2.0, huber_px=1.5, linear=False, starts=4, seed=0):
    two = p0b is not None
    if not two and ratio is None:
        raise ValueError("单视图要给扁率先验 ratio（b = ratio·a）或给 p0b 用第二视图")
    L = float(np.linalg.norm(np.asarray(P1, float) - np.asarray(P0, float)))
    x0 = list(p0a) + (list(p0b) if two else [])
    nb = 2 if two else 1

    def unpack(x):
        ps = [list(x[5 * i:5 * i + 5]) for i in range(nb)]
        if linear:
            for p in ps:
                p[3] = p[0] + (p[1] - p[0]) * p[2]
        return ps

    def mk(x):
        ps = unpack(x)
        fa = lambda v, p=ps[0]: float(bump(v, p))
        fb = (lambda v, p=ps[1]: float(bump(v, p))) if two else (lambda v: ratio * fa(v))
        return Body(P0, P1, ax, fa, fb, n), ps

    def loss(x):
        B, _ = mk(x)
        r = []
        for cam, vs, w in views:
            r.extend(widths(B, cam, vs) - np.asarray(w, float))
        return formkit.huber(r, huber_px)

    step, bounds = [], []
    for i in range(nb):
        p = x0[5 * i:5 * i + 5]
        sz = max(abs(p[0]), abs(p[1]), abs(p[3]), 1.0)
        step += [0.2 * sz, 0.2 * sz, 0.15, 0.2 * sz, 0.5]
        bounds += [(0.05 * sz, 4 * sz), (0.05 * sz, 4 * sz), (0.05, 0.95), (0.05 * sz, 4 * sz), (0.3, 6.0)]
    R = formkit.fit_multistart(loss, x0, step, bounds, starts=starts, seed=seed, iters=500, restarts=2)
    B, ps = mk(R["x"])
    per = []
    for cam, vs, w in views:
        e = widths(B, cam, vs) - np.asarray(w, float)
        per.append(float(np.sqrt((e ** 2).mean())))
    allr = np.concatenate([widths(B, c, vs) - np.asarray(w, float) for c, vs, w in views])
    return dict(pa=ps[0], pb=ps[1] if two else None, body=B, rms_px=float(np.sqrt((allr ** 2).mean())), per_view=per,
                at_bound=R["at_bound"], length=L)


def selftest():
    import camkit
    rng = np.random.default_rng(1)
    P0, P1, ax = (0, 0, 0), (0, 250, 0), (1, 0, 0)
    ta, tb = (30.0, 22.0, 0.3, 42.0, 1.6), (26.0, 18.0, 0.25, 33.0, 2.0)           # 真值：a 肌腹在 30%，b 在 25%
    T = Body(P0, P1, ax, lambda v: float(bump(v, ta)), lambda v: float(bump(v, tb)))
    top = camkit.look_at((0, 125, 1500), (0, 125, 0), 2400, up=(0, 1, 0))       # 俯视：剪影宽 = 2a
    side = camkit.look_at((1500, 125, 0), (0, 125, 0), 2400, up=(0, 0, 1))      # 侧视：剪影宽 = 2b
    vs = np.linspace(0.04, 0.96, 24)
    obs = [(c, vs, widths(T, c, vs) + rng.normal(0, 0.4, len(vs))) for c in (top, side)]
    g0 = (28.0, 28.0, 0.5, 30.0, 1.0)
    R = fit(obs, P0, P1, ax, g0, g0)
    va = np.linspace(0, 1, 41)
    ea = np.abs(bump(va, R["pa"]) - bump(va, ta)).max() / 42
    eb = np.abs(bump(va, R["pb"]) - bump(va, tb)).max() / 33
    assert ea < 0.02 and eb < 0.02 and not R["at_bound"], ("双视图恢复", ea, eb, R["at_bound"])
    Rl = fit(obs, P0, P1, ax, g0, g0, linear=True)
    assert Rl["rms_px"] > 5 * R["rms_px"], ("直管残差应大得多", Rl["rms_px"], R["rms_px"])
    R1 = fit(obs[:1], P0, P1, ax, g0, ratio=0.8)
    e1 = np.abs(bump(va, R1["pa"]) - bump(va, ta)).max() / 42
    assert e1 < 0.03, ("单视图 + 扁率先验", e1)
    print("profilefit selftest ok：双视图 a / b 最大相对误差 %.2f%% / %.2f%%（剪影残差 %.2f px）；直管残差 %.2f px（%.0f 倍）；单视图 a %.2f%%"
          % (100 * ea, 100 * eb, R["rms_px"], Rl["rms_px"], Rl["rms_px"] / R["rms_px"], 100 * e1))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    selftest() if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest") else print(__doc__)
