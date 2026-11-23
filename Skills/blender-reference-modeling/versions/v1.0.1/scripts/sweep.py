# -*- coding: utf-8 -*-
"""
sweep：曲线网络上放样截面（几何原语层，领域无关）。线脚、包边、门框、管、焊缝、密封条、系带、屋脊的当沟 / 盖脊都是它。
站（station）= dict(p=(x, y, z) 线上点, lat 截面 u 轴（斜接处长度 = 1/cos(半折角)）, [n 截面 v 轴], 以及任意数据键)。
两种模式：
  2.5D（站无 n）：lat 为平面向量，截面 (u, z) → (p.xy + lat·u, z)，z 是绝对高（屋脊、地面上的线脚）
  3D  （站带 n）：截面 (u, v) → p + lat·u + n·v，v 是沿法向的相对高（曲面上的包边、管、系带）

  stations(P3, side=+1, **data)        2.5D：lat = 平面切向的左法向 × side（side = −1 取右侧）
  stations3(P3, N, side=+1, **data)    3D：每点给法向 N（如 Surface.normal），lat = (N × 切向) × side
  Network().edge(name, P3, N=None, **data).path([名…], side, clear, closed)
                                        沿若干条边走（名前加 "-" = 反向），节点处斜接；closed = 首尾也斜接成环
  join(legs, clear, closed)             多段站列在公共节点斜接：节点一站，lat = 两侧向角平分 / cos(半折角)（3D 时 n 取平均）；
                                        离节点 < clear 的站剔掉（内侧环不互穿）；clear ≥ 截面在折角内侧的伸出量
                                        （截面在路径一侧伸出 u 时，离角 d < u 的环越过斜接线；护臂包边按 0.45 × 截面宽取，四角自交 57 处）
  decimate(st, min_step)                站距下限（倒角宽的几倍以上，否则活 Bevel 自交）
  limit_rate(st, key, k)                st[key] 沿弧长的变化率限幅（前后两遍；截面宽度骤变处不立薄墙）
  slope(st, key)                        st[key] 对弧长的导数（如脊顶坡度 → 截面竖向补偿）
  sweep(st, profile)                    profile(站) → [(u, z|v)] 闭合截面环或 None（断开）→ 条带列表
  loft_polys(strips, tag, closed=False) 条带 → 多边形汤（同拓扑环相邻连四边面，两端平面 n-gon 收口；closed = 首尾环相连、不收口）
[实测：修仙牌楼转角当沟 / 盖脊 / 连檐板（2.5D，分叉点 45° 斜接，审计自交 0）；鳞甲护臂包边 / 系带（3D，闭合环）]
"""
import math
import numpy as np


def _unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _per_point(data, i, n):
    return {k: (v[i] if isinstance(v, (list, np.ndarray)) and len(v) == n else v) for k, v in data.items()}


def stations(P3, side=1.0, **data):
    P = np.asarray(P3, float)
    out = []
    for i in range(len(P)):
        a, b = P[max(0, i - 1)], P[min(len(P) - 1, i + 1)]
        t = _unit((b - a)[:2])
        out.append(dict(p=P[i].copy(), lat=side * np.array([-t[1], t[0]]), **_per_point(data, i, len(P))))
    return out


def stations3(P3, N, side=1.0, **data):
    P, N = np.asarray(P3, float), np.asarray(N, float)
    out = []
    for i in range(len(P)):
        t = _unit(P[min(len(P) - 1, i + 1)] - P[max(0, i - 1)])
        n = _unit(N[i] - t * (N[i] @ t))
        out.append(dict(p=P[i].copy(), n=n, lat=side * np.cross(n, t), **_per_point(data, i, len(P))))
    return out


def _d(a, b):
    """站距：3D 模式（站带 n）取空间距离，2.5D 取平面距离。"""
    pa, pb = np.asarray(a["p"], float), np.asarray(b["p"], float)
    return float(np.linalg.norm(pa - pb) if "n" in a else np.linalg.norm(pa[:2] - pb[:2]))


def join(legs, clear=0.0, closed=False):
    """legs[i] 的末站与 legs[i+1] 的首站是同一节点（closed 时末段末站与首段首站也是）。"""
    if not closed:
        return _join_open(legs, clear)
    r = _join_open(list(legs) + [legs[0]], clear)
    k = max(i for i, s in enumerate(r) if s.get("miter"))             # 闭合角（末段 → 首段）
    return [r[k]] + [s for s in r[1:k] if s.get("miter") or _d(s, r[k]) >= clear]


def _join_open(legs, clear=0.0):
    out = []
    for i, leg in enumerate(legs):
        leg = [dict(s) for s in leg]
        if i > 0:
            prev = out[-1]
            l1, l2 = _unit(prev["lat"]), _unit(leg[0]["lat"])
            c = float(np.clip(np.dot(l1, l2), -1.0, 1.0))
            half = math.acos(c) / 2
            m = dict(leg[0], lat=_unit(l1 + l2) / max(math.cos(half), 1e-6), miter=True)
            if "n" in leg[0]:
                m["n"] = _unit(np.asarray(prev["n"], float) + np.asarray(leg[0]["n"], float))
                L0 = np.linalg.norm(m["lat"])                       # 两段端点 n 各按弦切向正交化，平均后 lat 需再正交一次（保留斜接长度）
                m["lat"] = _unit(m["lat"] - m["n"] * (m["lat"] @ m["n"])) * L0
            node = leg[0]
            near = lambda s: _d(s, node) < clear
            out.pop()                                            # 前一段的节点站（先弹，否则它也算"近站"，会多弹一个远站）
            while out and near(out[-1]):
                out.pop()
            leg = [m] + [s for s in leg[1:] if not near(s)]
        out += leg
    return out


class Network:
    """最小曲线网络：命名的边（3D 折线，可带每点法向 N 与数据），按边序列取路径（节点处斜接）。"""

    def __init__(self):
        self.edges = {}

    def edge(self, name, P3, N=None, **data):
        self.edges[name] = (np.asarray(P3, float), None if N is None else np.asarray(N, float), data)
        return self

    def path(self, names, side=1.0, clear=0.0, closed=False):
        legs = []
        for nm in names:
            P, N, data = self.edges[nm.lstrip("-")]
            if nm.startswith("-"):
                P, N = P[::-1], (None if N is None else N[::-1])
                data = {k: (v[::-1] if isinstance(v, (list, np.ndarray)) else v) for k, v in data.items()}
            legs.append(stations(P, side, **data) if N is None else stations3(P, N, side, **data))
        return join(legs, clear, closed)


def arc(st):
    k = 3 if "n" in st[0] else 2
    P = np.array([np.asarray(s["p"], float)[:k] for s in st])
    return np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]


def decimate(st, min_step):
    keep = [st[0]]
    for s in st[1:-1]:
        if _d(s, keep[-1]) >= min_step or s.get("miter"):
            keep.append(s)
    keep.append(st[-1])
    return keep


def limit_rate(st, key, k):
    s = arc(st)
    v = [float(x[key]) for x in st]
    for i in range(1, len(v)):
        v[i] = min(v[i], v[i - 1] + k * (s[i] - s[i - 1]))
    for i in range(len(v) - 2, -1, -1):
        v[i] = min(v[i], v[i + 1] + k * (s[i + 1] - s[i]))
    for x, val in zip(st, v):
        x[key] = val
    return st


def slope(st, key):
    s = arc(st)
    v = np.array([float(x[key]) for x in st])
    return [float((v[min(len(v) - 1, i + 1)] - v[max(0, i - 1)]) / max(s[min(len(v) - 1, i + 1)] - s[max(0, i - 1)], 1e-6)) for i in range(len(v))]


def sweep(st, profile):
    strips, cur = [], []
    for s in st:
        prof = profile(s)
        if prof is None:
            if len(cur) > 1:
                strips.append(cur)
            cur = []
            continue
        p, l = np.asarray(s["p"], float), np.asarray(s["lat"], float)
        if "n" in s:
            n = np.asarray(s["n"], float)
            cur.append(np.array([p + l * u + n * v for (u, v) in prof]))
        else:
            cur.append(np.array([(p[0] + l[0] * u, p[1] + l[1] * u, z) for (u, z) in prof]))
    if len(cur) > 1:
        strips.append(cur)
    return strips


def loft_polys(strips, tag, cap=True, closed=False):
    out = []
    for rings in strips:
        n = len(rings[0])
        pairs = list(zip(rings, rings[1:])) + ([(rings[-1], rings[0])] if closed else [])
        for a, b in pairs:
            for i in range(n):
                j = (i + 1) % n
                out.append((np.array([a[i], a[j], b[j], b[i]]), tag))
        if cap and not closed:
            out.append((np.asarray(rings[0])[::-1].copy(), tag))
            out.append((np.asarray(rings[-1]).copy(), tag))
    return out


def _closed_edges(polys):
    e = {}
    for P, _ in polys:
        k = [tuple(np.round(p, 5)) for p in P]
        for i in range(len(k)):
            key = tuple(sorted((k[i], k[(i + 1) % len(k)])))
            e[key] = e.get(key, 0) + 1
    return all(v == 2 for v in e.values())


def selftest():
    # L 形网络：沿 +x 1000，再折向 +y 1000，方截面（u ∈ [0, 100]，z ∈ [0, 50]）放在路径右侧
    net = Network().edge("a", [(x, 0, 0) for x in np.linspace(0, 1000, 21)]).edge("b", [(1000, y, 0) for y in np.linspace(0, 1000, 21)])
    w = 100.0
    st = net.path(["a", "b"], side=-1.0, clear=0.45 * w)
    miters = [s for s in st if s.get("miter")]
    assert len(miters) == 1, "节点应只有一站斜接"
    m = miters[0]
    assert np.allclose(np.asarray(m["lat"]) * w, (w, -w), atol=1e-6), "斜接侧向量应为 (1, −1)·w（右侧外角）"
    assert all(np.linalg.norm(np.asarray(s["p"])[:2] - (1000, 0)) >= 0.45 * w for s in st if not s.get("miter")), "节点附近站未剔"
    assert len(st) == 21 + 21 - 1, "只该剔掉节点那一站（两段站距 50 > clear 45，不该多剔）"   # [回归：牌楼脊骨架曾多剔 1 站]
    box = lambda s: [(0, 0), (w, 0), (w, 50), (0, 50)]
    strips = sweep(st, box)
    polys = loft_polys(strips, "trim")
    assert _closed_edges(polys), "放样体不闭合（有边不是两面共享）"
    s_out = arc([dict(p=r[1]) for r in strips[0]])                 # 外角点依次前进不回退（内侧环不互穿）
    assert np.all(np.diff(s_out) > 0), "截面环互穿"
    st2 = [dict(p=(x, 0, 0), lat=(0, 1), w=(400.0 if x < 500 else 100.0)) for x in np.linspace(0, 1000, 11)]
    limit_rate(st2, "w", 0.5)
    ws = [s["w"] for s in st2]
    assert max(abs(a - b) for a, b in zip(ws, ws[1:])) <= 0.5 * 100 + 1e-9, "限幅失败"
    assert len(decimate(st2, 250.0)) < len(st2), "站距下限未生效"
    k = slope([dict(p=(x, 0, 0), zb=0.3 * x) for x in np.linspace(0, 1000, 11)], "zb")
    assert np.allclose(k, 0.3), "坡度"

    # 3D 模式 + 闭合：圆柱（半径 100，轴 y）上 θ ∈ [−1, 1]、y ∈ [0, 200] 的矩形边框，截面贴面（v 沿法向）
    cyl = lambda u, y: np.array([100 * math.sin(u), y, 100 * math.cos(u)])
    nrm = lambda u, y: np.array([math.sin(u), 0, math.cos(u)])
    us, ys = np.linspace(-1, 1, 21), np.linspace(0, 200, 11)
    net3 = (Network().edge("lo", [cyl(u, 0) for u in us], N=[nrm(u, 0) for u in us])
            .edge("r", [cyl(1, y) for y in ys], N=[nrm(1, y) for y in ys])
            .edge("hi", [cyl(u, 200) for u in us], N=[nrm(u, 200) for u in us])
            .edge("l", [cyl(-1, y) for y in ys], N=[nrm(-1, y) for y in ys]))
    loop = net3.path(["lo", "r", "-hi", "-l"], side=1.0, clear=4.0, closed=True)
    assert sum(1 for s in loop if s.get("miter")) == 4, "闭合环四角斜接"
    assert len(loop) == 20 + 10 + 20 + 10, "闭合环站数（每角只并一站）"
    assert all(abs(np.linalg.norm(s["n"]) - 1) < 1e-9 for s in loop), "3D 站法向"
    assert all(abs(np.dot(s["lat"], s["n"])) < 1e-9 for s in loop), "lat ⊥ n"
    c = np.mean([s["p"] for s in loop], axis=0)
    assert all(np.dot(s["lat"], np.asarray(s["p"]) - c) < 0 for s in loop), "side=+1：lat 指向框内"
    ring = sweep(loop, lambda s: [(-5, 0), (5, 0), (5, 3), (-5, 3)])
    pl = loft_polys(ring, "rim", closed=True)
    assert all(len(P) == 4 for P, _ in pl) and _closed_edges(pl), "闭合环放样：全四边面、无边界"
    print("sweep selftest ok：斜接一站 / 侧向量 1/cos、节点剔站、闭合放样、环不互穿、宽度限幅、站距下限、坡度、3D 标架放样、闭合环四角斜接")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    selftest() if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest") else print(__doc__)
