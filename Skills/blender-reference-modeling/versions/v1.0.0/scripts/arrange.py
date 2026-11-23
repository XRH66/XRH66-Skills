# -*- coding: utf-8 -*-
"""
arrange：面上 / 线上排布（几何原语层，领域无关）。瓦垄、鳞片、甲片、砖、板条、铆钉、栏杆、椽都是它。
规则 = 起点沿边界等距 → 按方向推进 → 碰停止条件就停；尺寸渐变 + 成组随机。只出平面点列（mm），高程 / 法向交 support。

  arc(P) / at_arc(P, s)                 折线弧长表 / 弧长 s 处的点与单位切向（维数随输入；s 超出两端按端段直线外推）
  resample(P, step)                     按弧长等距重采样
  starts_along(B, pitch, phase=0.5, s0=0, s1=None)   边界折线上等距起点：s = s0 + (k + phase)·pitch；返回 [(点, 切向, s)]
  march(p0, d, step, stop, max_n, include_stop)   从 p0 沿方向 d（常向量或 d(p) 方向场）走（step 可为函数 step(p)：件随处变大小），stop(p, n) 为真即停
                                        （include_stop = True 时保留越界那一点：件要插进边界件里时用）
  fit(S, s_end, tail=0)                 一维排位等比拉开，使末件（位置 + 尾长 tail）正好收在 s_end（march 停下后边界留空时用）
  dist_to_polyline(p, P)                平面点到折线距离与最近点弧长
  ray_polyline(p, d, P)                 射线与折线首个交点距离（None = 不交）；做"走到边界为止"的停止条件
  group_noise(n, size, amp, seed)       成组随机：每 size 个一组共享一个偏移，再加组内小抖动（amp 的 20%）
  gap_scale(S, nominal)                 线上排布时按两侧邻距与名义间距之比给每件宽度缩放（翼角扇开处件变宽 / 变窄）
[实测：修仙牌楼瓦垄 walk() 与椽排布（本模块是其去领域化版本）；鳞甲护臂排距随周长变 + fit 收口]
"""
import math
import numpy as np


def arc(P):
    P = np.asarray(P, float)                                    # 维数随输入：传 P[:, :2] 得平面弧长，传 3D 得空间弧长
    return np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]


def at_arc(P, s):
    P = np.asarray(P, float)
    S = arc(P)
    i = int(np.clip(np.searchsorted(S, s) - 1, 0, len(P) - 2))
    seg = P[i + 1] - P[i]
    L = max(np.linalg.norm(seg), 1e-12)
    t = seg / L
    return P[i] + t * (s - S[i]), t


def resample(P, step):
    S = arc(P)
    n = max(1, int(round(S[-1] / step)))
    return np.array([at_arc(P, s)[0] for s in np.linspace(0, S[-1], n + 1)])


def starts_along(B, pitch, phase=0.5, s0=0.0, s1=None):
    S = arc(B)
    s1 = S[-1] if s1 is None else s1
    out, k = [], 0
    while True:
        s = s0 + (k + phase) * pitch
        if s > s1 + 1e-9:
            break
        p, t = at_arc(B, s)
        out.append((p, t, s))
        k += 1
    return out


def march(p0, d, step, stop, max_n=10000, include_stop=False):
    p = np.asarray(p0, float)[:2].copy()
    out = []
    for n in range(max_n):
        if stop(p, n):
            if include_stop:
                out.append(p.copy())
            break
        out.append(p.copy())
        v = np.asarray(d(p) if callable(d) else d, float)[:2]
        p = p + v / max(np.linalg.norm(v), 1e-12) * (step(p) if callable(step) else step)
    return np.array(out).reshape(-1, 2)


def fit(S, s_end, tail=0.0):
    S = np.asarray(S, float)
    if len(S) < 2:
        return S
    k = (s_end - tail - S[0]) / max(S[-1] - S[0], 1e-12)
    return S[0] + (S - S[0]) * k


def dist_to_polyline(p, P):
    p, P = np.asarray(p, float)[:2], np.asarray(P, float)[:, :2]
    S = arc(P)
    best = (np.inf, 0.0)
    for i in range(len(P) - 1):
        a, b = P[i], P[i + 1]
        ab = b - a
        L2 = max(float(ab @ ab), 1e-24)
        u = float(np.clip((p - a) @ ab / L2, 0, 1))
        d = float(np.linalg.norm(p - (a + u * ab)))
        if d < best[0]:
            best = (d, S[i] + u * math.sqrt(L2))
    return best


def ray_polyline(p, d, P):
    p, d, P = np.asarray(p, float)[:2], np.asarray(d, float)[:2], np.asarray(P, float)[:, :2]
    d = d / max(np.linalg.norm(d), 1e-12)
    hit = None
    for i in range(len(P) - 1):
        e = P[i + 1] - P[i]
        den = d[0] * (-e[1]) - d[1] * (-e[0])
        if abs(den) < 1e-12:
            continue
        w = P[i] - p
        t = (w[0] * (-e[1]) - w[1] * (-e[0])) / den
        u = (d[0] * w[1] - d[1] * w[0]) / den
        if t >= 0 and -1e-9 <= u <= 1 + 1e-9 and (hit is None or t < hit):
            hit = t
    return hit


def group_noise(n, size, amp, seed=0):
    rng = np.random.default_rng(seed)
    g = rng.uniform(-amp, amp, size=(n + size - 1) // size)
    return np.repeat(g, size)[:n] + rng.uniform(-0.2 * amp, 0.2 * amp, size=n)


def gap_scale(S, nominal):
    S = np.asarray(S, float)
    if len(S) < 2:
        return np.ones(len(S))
    g = np.diff(S)
    left, right = np.r_[g[0], g], np.r_[g, g[-1]]
    return 0.5 * (left + right) / nominal


def selftest():
    B = [(0, 0), (1000, 0), (1000, 500)]                       # L 形边界
    assert abs(arc(B)[-1] - 1500) < 1e-9
    p, t = at_arc(B, 1200)
    assert np.allclose(p, (1000, 200)) and np.allclose(t, (0, 1)), "at_arc"
    p, _ = at_arc(B, 1600)
    assert np.allclose(p, (1000, 600)), "端外直线外推"
    st = starts_along(B, 100, phase=0.5)
    assert len(st) == 15 and np.allclose(st[0][0], (50, 0)), "起点等距 / 相位"
    R = resample(B, 50)
    assert np.allclose(np.diff(arc(R)), 50), "等距重采样"
    # 从底边起点向 +y 走，碰到斜线 y = 800 − 0.5x 就停
    top = np.array([(0, 800), (1000, 300)])
    rows = []
    for q, _, _ in starts_along([(0, 0), (1000, 0)], 200):
        lim = ray_polyline(q, (0, 1), top)
        rows.append(march(q, (0, 1), 50, lambda p, n, q=q, lim=lim: p[1] - q[1] >= lim))
    assert all(len(r) and r[-1][1] < 800 - 0.5 * r[-1][0] <= r[-1][1] + 50 + 1e-9 for r in rows), "停止条件"
    assert [len(r) for r in rows] == sorted([len(r) for r in rows], reverse=True), "越往右越短"
    # 方向场：绕原点的圆周走一圈的四分之一
    circ = march((1000, 0), lambda p: (-p[1], p[0]), 10, lambda p, n: p[0] < 0)
    assert abs(np.linalg.norm(circ, axis=1).max() - 1000) < 60, "方向场"
    assert len(march((0, 0), (1, 0), 10, lambda p, n: p[0] > 25, include_stop=True)) == 4, "保留越界点"
    assert abs(arc([(0, 0, 0), (3, 0, 4)])[-1] - 5) < 1e-12, "3D 弧长"
    g = march((0, 0), (1, 0), lambda p: 10 + 0.5 * p[0], lambda p, n: p[0] > 200)
    assert np.allclose(np.diff(g[:, 0]), 10 + 0.5 * g[:-1, 0]), "步长函数"
    assert np.allclose(fit([0, 10, 20], 50, tail=10), [0, 20, 40]), "收口拉开"
    d, s = dist_to_polyline((500, 30), B)
    assert abs(d - 30) < 1e-9 and abs(s - 500) < 1e-9, "点到折线"
    gn = group_noise(12, 4, 10.0, seed=1)
    assert len(gn) == 12 and np.abs(gn).max() <= 12.0 + 1e-9, "成组随机"
    assert np.std(gn[:4] - gn[:4].mean()) < np.std(gn), "组内应比组间相近"
    sc = gap_scale([0, 100, 200, 350, 550], 100)
    assert np.allclose(sc, (1.0, 1.0, 1.25, 1.75, 2.0)), "邻距缩放"
    print("arrange selftest ok：弧长 / 外推、收口、步长函数、等距起点、重采样、推进到边界、方向场、点到折线、成组随机、邻距缩放")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    selftest() if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest") else print(__doc__)
