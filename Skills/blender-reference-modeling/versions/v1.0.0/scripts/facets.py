# -*- coding: utf-8 -*-
"""facets：绕支承的折面硬表面板（不跟支承形，自有折线截面；支承只定位、查干涉）。纯 numpy，带 selftest。
来源：科幻叠板护臂 v2（2026-11-21）——叠板 / 护片 / 腕甲的截面、层间净距、平面性问题，抽成与领域无关的函数。[实测]

约定：截面平面坐标 (x, z)；支承截面 sec(v, th) → (x, z)，th 为角参数（度），绕一圈为凸闭曲线；v 为沿轴位置。
  facet_ring(...) 返回闭合截面环 = 外表面折线 + 内表面折线（反序），可直接给 sweep 放样（同拓扑环）。

几条规则（踩过的坑，pitfalls 有行）：
1. 顶点外扩系数 f 数值求：弦上采样点都不进支承（扁截面上圆的 1/cos(Δ/2) 公式会切进去）——clear_scale。
2. 同一放样件各站用同一 f，或用相似截面（vref）：各站 f 不同 → 四边面不共面 → 三角化对角线切进支承 / 平着色出 X 形折痕。
3. 截面角范围随站变化的段（端切角、尖唇）放样站要密：站间直线插值会抄近路。
4. 多层叠放的抬高 / 倾角用射线实测两层截面间距二分求（solve_up），不按厚度叠加：两层折点不同时弦拱失配。
"""
import math
import numpy as np

R = math.radians


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def ray_hit(poly, d, closed=False):
    """原点出发、方向 d 的射线与折线 poly（(n, 2)）的最远交点距离；无交点 nan。"""
    P = np.asarray(poly, float)
    segs = list(zip(P[:-1], P[1:])) + ([(P[-1], P[0])] if closed else [])
    best = np.nan
    for p, q in segs:
        e = q - p
        M = np.array([[d[0], -e[0]], [d[1], -e[1]]])
        if abs(np.linalg.det(M)) < 1e-12:
            continue
        t, s = np.linalg.solve(M, p)
        if t > 0 and -1e-9 <= s <= 1 + 1e-9:
            best = t if np.isnan(best) else max(best, t)
    return best


def support_poly(sec, v, n=180):
    return np.array([sec(v, t) for t in np.linspace(0.0, 360.0, n, endpoint=False)])


def rho(sec, v, pts, n=180):
    """点到原点距离 / 同方向支承半径（≥ 1 = 在支承外）。"""
    S = support_poly(sec, v, n)
    return np.array([np.linalg.norm(p) / ray_hit(S, unit(p), closed=True) for p in pts])


def clear_scale(sec, v, ths, vref=None, n=16):
    """顶点取 sec(vref or v, th)·f，求最小 f 使每条弦都不进 v 处支承。"""
    E = np.array([sec(v if vref is None else vref, t) for t in ths])
    s = np.linspace(0.0, 1.0, n)
    pts = np.concatenate([E[i] + (E[i + 1] - E[i]) * s[:, None] for i in range(len(E) - 1)])
    return 1.0 / min(1.0, float(rho(sec, v, pts).min())) if vref is None else 1.0 / float(rho(sec, v, pts).min())


def facet_ring(sec, v, ths, h, T, f=None, vref=None):
    """绕支承的折线截面板：顶点在 f·支承（相似截面时取参考站 vref）上，内表面沿顶点角平分法向外移 h，外表面再 + T（T 可逐顶点）。
    返回闭合环 (2n, 2)：外表面 n 点 + 内表面 n 点（反序）。"""
    if f is None:
        f = clear_scale(sec, v, ths, vref)
    P = np.array([np.asarray(sec(v if vref is None else vref, t), float) * f for t in ths])
    n = []
    for i in range(len(P)):
        e = [P[min(i + 1, len(P) - 1)] - P[i], P[i] - P[max(i - 1, 0)]]
        ns = [np.array([t[1], -t[0]]) / np.linalg.norm(t) for t in e if np.linalg.norm(t) > 1e-9]
        m = unit(sum(ns))
        if m @ P[i] < 0:
            m = -m
        n.append(m / max(min(m @ ns[0], 1.0), 0.3))
    n = np.array(n)
    inner = P + n * h
    outer = inner + n * np.broadcast_to(np.asarray(T, float), (len(P),))[:, None]
    return np.vstack([outer, inner[::-1]])


def split(ring):
    """facet_ring 的环 → (外表面, 内表面)，同顺序。"""
    k = len(ring) // 2
    return ring[:k], ring[k:][::-1]


def loft_scale(sec, stations, ths_fn):
    """同一放样件的公共 f（各站取最大）。"""
    return max(clear_scale(sec, v, ths_fn(v)) for v in stations)


def min_gap(lower, upper, dirs):
    """两层截面（lower 外表面、upper 内表面，开折线）沿径向射线的最小间距，只计两者都覆盖的方向。"""
    g = []
    for d in dirs:
        a, b = ray_hit(lower, d), ray_hit(upper, d)
        if not (np.isnan(a) or np.isnan(b)):
            g.append(b - a)
    return min(g) if g else np.inf


def dirs_around(n=180):
    return [np.array([math.cos(a), math.sin(a)]) for a in np.linspace(0, 2 * math.pi, n, endpoint=False)]


def solve_up(gap_fn, lo, hi, clear, it=30):
    """二分：gap_fn(x) 随 x 单增，求最小 x 使 gap ≥ clear（层间抬高、叠层倾角）。"""
    if gap_fn(hi) < clear:
        return hi
    for _ in range(it):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if gap_fn(m) < clear else (lo, m)
    return hi


def selftest():
    # 扁椭圆支承，沿 v 不均匀收分
    sec = lambda v, t: np.array([(30 - 0.05 * v) * math.sin(R(t)), (24 - 0.08 * v) * math.cos(R(t))])
    ths = [-80, -35, 10, 55, 100]
    # 1. 弦不进支承（数值 f）；圆公式在扁椭圆上不够
    for v in (0, 50, 100):
        f = clear_scale(sec, v, ths)
        E = np.array([sec(v, t) * f for t in ths])
        s = np.linspace(0, 1, 40)
        pts = np.concatenate([E[i] + (E[i + 1] - E[i]) * s[:, None] for i in range(len(E) - 1)])
        assert rho(sec, v, pts).min() >= 1 - 1e-3, v
    f_circ = 1 / math.cos(R(45) / 2)
    E = np.array([sec(100, t) * f_circ for t in ths])
    mid = [(E[i] + E[i + 1]) / 2 for i in range(len(E) - 1)]
    # 2. 相似截面：相邻站对应边平行（四边面共面）
    A = facet_ring(sec, 0, ths, 0.0, 3.0, vref=0)
    B = facet_ring(sec, 100, ths, 0.0, 3.0, vref=0)
    ia, ib = split(A)[1], split(B)[1]
    for i in range(len(ths) - 1):
        ea, eb = unit(ia[i + 1] - ia[i]), unit(ib[i + 1] - ib[i])
        assert abs(ea[0] * eb[1] - ea[1] * eb[0]) < 1e-9, i
    assert rho(sec, 100, ib).min() >= 1 - 1e-6
    # 3. 两层不同折点叠放：按厚度叠会穿，solve_up 求到净距
    lo_ring = facet_ring(sec, 50, ths, 0.0, 4.0)
    up_ths = [-60, 0, 60]
    naive = facet_ring(sec, 50, up_ths, 4.0, 3.0)
    g_naive = min_gap(split(lo_ring)[0], split(naive)[1], dirs_around())
    h = solve_up(lambda x: min_gap(split(lo_ring)[0], split(facet_ring(sec, 50, up_ths, x, 3.0))[1], dirs_around()), 0.0, 20.0, 0.3)
    g = min_gap(split(lo_ring)[0], split(facet_ring(sec, 50, up_ths, h, 3.0))[1], dirs_around())
    assert g_naive < 0.3 and abs(g - 0.3) < 0.02, (g_naive, g)
    print("facets selftest ok  (圆公式中点 ρ min %.3f；按厚度叠放间距 %.2f → 求得抬高 %.2f，间距 %.2f)"
          % (rho(sec, 100, mid).min(), g_naive, h, g))


if __name__ == "__main__":
    selftest()
