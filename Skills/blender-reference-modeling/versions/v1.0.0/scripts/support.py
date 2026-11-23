# -*- coding: utf-8 -*-
"""
support：支承查询（几何原语层，领域无关）。件坐在什么上，就问它：高程、法向、边界在哪、离边还有多远。
来源两种，接口相同：
  Support.from_func(zfun, inside=None)   解析式（inside(x, y) 给定义域；缺省处处有定义）
  Support.from_polys(polys, tags=None)   多边形汤 [(pts(k, 3), tag)]（如 polys_bpy.dump 从 Blender 导出的壳面），
                                         numpy 竖直射线：网格分桶 + 重心坐标，取最高命中（从上往下看到的那层）
  Support.union([s1, s2, …])             多个支承取最高命中（主体壳 + 拼接件）
查询（mm，与几何同单位）：
  z(x, y) → float | None（None = 不在支承上）
  normal(x, y, eps) → 单位法向（中心差分；任一侧落空则单侧差分，全落空给 (0, 0, 1)）
  room(p, d, start, step, max_len) → 从 p 沿平面方向 d 走，最早落空处的距离（剩余坡长 / 离边距离）
  drape(xy) → 平面折线逐点取高程；落空点在两端按相邻两点直线外推、中间按插值（件挑出支承边时用，不用公式外推）
教训（修仙牌楼）：檐口瓦挑出屋面边，主文件用立面公式外推高程 / 法向，首片被拧、接不上瓦当；改为壳面射线 + 直线外推后接上。[实测]
"""
import math
import numpy as np


class Support:
    def __init__(self, zfun):
        self._z = zfun

    # ---------------------------------------------------------------- 构造
    @classmethod
    def from_func(cls, zfun, inside=None):
        if inside is None:
            return cls(lambda x, y: float(zfun(x, y)))
        return cls(lambda x, y: float(zfun(x, y)) if inside(x, y) else None)

    @classmethod
    def from_polys(cls, polys, tags=None, cell=None):
        tris = []
        for pts, tag in polys:
            if tags is not None and tag not in tags:
                continue
            P = np.asarray(pts, float)
            for i in range(1, len(P) - 1):
                tris.append((P[0], P[i], P[i + 1]))
        if not tris:
            raise ValueError("from_polys：没有三角形（tags 过滤后为空？）")
        T = np.array(tris)                                        # (n, 3, 3)
        lo, hi = T[:, :, :2].min(1), T[:, :, :2].max(1)
        if cell is None:
            cell = float(np.median(np.max(hi - lo, 1))) * 2.0 or 1.0
        org = lo.min(0)
        bins = {}
        i0 = np.floor((lo - org) / cell).astype(int)
        i1 = np.floor((hi - org) / cell).astype(int)
        for k in range(len(T)):
            for a in range(i0[k, 0], i1[k, 0] + 1):
                for b in range(i0[k, 1], i1[k, 1] + 1):
                    bins.setdefault((a, b), []).append(k)
        bins = {key: np.array(v) for key, v in bins.items()}
        A, B, C = T[:, 0], T[:, 1], T[:, 2]
        v0, v1 = (B - A)[:, :2], (C - A)[:, :2]
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        ok = np.abs(den) > 1e-12                                  # 竖直三角形（侧壁）对竖直射线无贡献

        def zf(x, y):
            idx = bins.get((int(math.floor((x - org[0]) / cell)), int(math.floor((y - org[1]) / cell))))
            if idx is None:
                return None
            idx = idx[ok[idx]]
            if len(idx) == 0:
                return None
            w = np.array([x, y]) - A[idx, :2]
            d = den[idx]
            u = (w[:, 0] * v1[idx, 1] - v1[idx, 0] * w[:, 1]) / d
            v = (v0[idx, 0] * w[:, 1] - w[:, 0] * v0[idx, 1]) / d
            m = (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
            if not m.any():
                return None
            zs = A[idx, 2] + u * (B[idx, 2] - A[idx, 2]) + v * (C[idx, 2] - A[idx, 2])
            return float(zs[m].max())
        s = cls(zf)
        s.n_tris = len(T)
        return s

    @classmethod
    def union(cls, sups):
        def zf(x, y):
            zs = [z for z in (s.z(x, y) for s in sups) if z is not None]
            return max(zs) if zs else None
        return cls(zf)

    # ---------------------------------------------------------------- 查询
    def z(self, x, y):
        return self._z(x, y)

    def normal(self, x, y, eps=30.0):
        z0 = self.z(x, y)
        g = []
        for dx, dy in ((eps, 0.0), (0.0, eps)):
            a, b = self.z(x + dx, y + dy), self.z(x - dx, y - dy)
            if a is not None and b is not None:
                g.append((a - b) / (2 * eps))
            elif z0 is not None and a is not None:
                g.append((a - z0) / eps)
            elif z0 is not None and b is not None:
                g.append((z0 - b) / eps)
            else:
                return np.array([0.0, 0.0, 1.0])
        n = np.array([-g[0], -g[1], 1.0])
        return n / np.linalg.norm(n)

    def room(self, p, d, start=0.0, step=20.0, max_len=3000.0):
        p, d = np.asarray(p, float)[:2], np.asarray(d, float)[:2]
        u = start
        while u < max_len:
            q = p + d * u
            if self.z(q[0], q[1]) is None:
                return u
            u += step
        return max_len

    def drape(self, xy):
        xy = np.asarray(xy, float)
        Z = [self.z(x, y) for x, y in xy]
        ok = [i for i, z in enumerate(Z) if z is not None]
        if len(ok) < 2:
            return None
        s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]   # 按弧长内插 / 外推（点距不必相等）
        for i in range(len(Z)):
            if Z[i] is None:
                if i < ok[0]:
                    a, b = ok[0], ok[1]
                elif i > ok[-1]:
                    a, b = ok[-2], ok[-1]
                else:
                    a, b = max(k for k in ok if k < i), min(k for k in ok if k > i)
                Z[i] = Z[a] + (Z[b] - Z[a]) * (s[i] - s[a]) / max(s[b] - s[a], 1e-9)
        return np.c_[xy, Z]


class Surface:
    """参数曲面支承：P(u, v) → (x, y, z)。不是高度场的支承（柱、锥、壳、管、球带、车身侧板）用它，排布在 (u, v) 里做。
      point(u, v) / du(u, v) / dv(u, v)      点与偏导（中心差分）
      normal(u, v)                           单位法向 = du × dv 归一（sign = −1 翻向）
      frame(u, v, along="v", tilt=0)          件的标架（列 X, Y, Z）：Y = 沿 along 的切向，Z = 法向；tilt 绕 X 转（正值 = −Y 端抬离曲面）
      line_u(v, u0, u1, n) / line_v(u, v0, v1, n)   等参线（3D 折线：做排布的周线、放样的路径）
      offset(d)                              沿法向偏 d 的新曲面（壳外皮、件的贴合层）
      grid_polys(us, vs, tag, closed_u) / shell_polys(us, vs, t, tag, closed_u)   等参网格四边面 / 有厚度的壳（全四边面；closed_u = 管）
    """

    def __init__(self, f, sign=1.0, eps=1e-4):
        self.f, self.sign, self.eps = f, sign, eps

    def point(self, u, v):
        return np.asarray(self.f(u, v), float)

    def du(self, u, v):
        e = self.eps
        return (self.point(u + e, v) - self.point(u - e, v)) / (2 * e)

    def dv(self, u, v):
        e = self.eps
        return (self.point(u, v + e) - self.point(u, v - e)) / (2 * e)

    def normal(self, u, v):
        n = np.cross(self.du(u, v), self.dv(u, v)) * self.sign
        return n / np.linalg.norm(n)

    def frame(self, u, v, along="v", tilt=0.0):
        Z = self.normal(u, v)
        Y = self.dv(u, v) if along == "v" else self.du(u, v)
        Y = Y - Z * (Y @ Z)
        Y /= np.linalg.norm(Y)
        Y, Z = Y * math.cos(tilt) - Z * math.sin(tilt), Z * math.cos(tilt) + Y * math.sin(tilt)
        return np.column_stack([np.cross(Y, Z), Y, Z])

    def line_u(self, v, u0, u1, n=64):
        return np.array([self.point(u, v) for u in np.linspace(u0, u1, n)])

    def line_v(self, u, v0, v1, n=64):
        return np.array([self.point(u, v) for v in np.linspace(v0, v1, n)])

    def offset(self, d):
        return Surface(lambda u, v: self.point(u, v) + self.normal(u, v) * d, self.sign, self.eps)

    def grid_polys(self, us, vs, tag, flip=False, closed_u=False):
        """closed_u：u 向是周期（管、环）——us 不含周期终点，最后一列与第一列相连。"""
        G = np.array([[self.point(u, v) for u in us] for v in vs])
        nu = len(us)
        out = []
        for j in range(len(vs) - 1):
            for i in range(nu if closed_u else nu - 1):
                i1 = (i + 1) % nu
                q = np.array([G[j, i], G[j, i1], G[j + 1, i1], G[j + 1, i]])
                out.append((q[::-1].copy() if flip else q, tag))
        return out

    def shell_polys(self, us, vs, t, tag, closed_u=False):
        """外皮 = 本曲面，内皮 = 向内偏 t；侧墙封口 → 闭合实体，全四边面（closed_u：管，只封两端）。"""
        inner = self.offset(-t)
        G = np.array([[self.point(u, v) for u in us] for v in vs])
        H = np.array([[inner.point(u, v) for u in us] for v in vs])
        out = self.grid_polys(us, vs, tag, closed_u=closed_u) + inner.grid_polys(us, vs, tag, flip=True, closed_u=closed_u)
        if closed_u:
            wrap = lambda a: np.vstack([a, a[:1]])
            rim, rim_i = [wrap(G[0, :]), wrap(G[-1, ::-1])], [wrap(H[0, :]), wrap(H[-1, ::-1])]
        else:
            rim = [G[0, :], G[:, -1], G[-1, ::-1], G[::-1, 0]]
            rim_i = [H[0, :], H[:, -1], H[-1, ::-1], H[::-1, 0]]
        for a, b in zip(rim, rim_i):
            for k in range(len(a) - 1):
                out.append((np.array([a[k + 1], a[k], b[k], b[k + 1]]), tag))
        return out


def selftest():
    # 参数曲面：半径 100 的圆柱（轴 = y），u = 角度，v = 轴向
    cyl = Surface(lambda u, v: (100 * math.sin(u), v, 100 * math.cos(u)))
    n = cyl.normal(0.3, 50)
    assert np.allclose(n, (math.sin(0.3), 0, math.cos(0.3)), atol=1e-6), "柱面法向朝外"
    F = cyl.frame(0.0, 0.0, along="v", tilt=0.1)
    assert np.allclose(F.T @ F, np.eye(3), atol=1e-9) and np.linalg.det(F) > 0, "曲面标架"
    assert F[2, 1] < 0, "tilt > 0：Y 轴向内倾（−Y 端抬起）"
    assert abs(np.linalg.norm(cyl.offset(5).point(1.0, 0)[[0, 2]]) - 105) < 1e-6, "偏移曲面"
    sh = cyl.shell_polys(np.linspace(-1, 1, 9), np.linspace(0, 100, 5), 3.0, "shell")
    e = {}
    for P, _ in sh:
        k = [tuple(np.round(p, 5)) for p in P]
        for i in range(4):
            key = tuple(sorted((k[i], k[(i + 1) % 4])))
            e[key] = e.get(key, 0) + 1
    assert all(len(P) == 4 for P, _ in sh) and all(c == 2 for c in e.values()), "壳闭合、全四边面"
    tube = cyl.shell_polys(np.linspace(0, 2 * math.pi, 16, endpoint=False), np.linspace(0, 100, 5), 3.0, "tube", closed_u=True)
    e = {}
    for P, _ in tube:
        k = [tuple(np.round(p, 5)) for p in P]
        for i in range(4):
            key = tuple(sorted((k[i], k[(i + 1) % 4])))
            e[key] = e.get(key, 0) + 1
    assert all(c == 2 for c in e.values()) and len(tube) == 16 * 4 * 2 + 16 * 2, "闭合管"
    # 解析斜面 z = 0.5·y（y ≤ 0 上有定义）对多边形汤化的同一斜面，查询一致
    f = lambda x, y: 0.5 * y + 1000.0
    S1 = Support.from_func(f, inside=lambda x, y: -2000 <= y <= 0 and -2000 <= x <= 2000)
    xs, ys = np.linspace(-2000, 2000, 9), np.linspace(-2000, 0, 6)
    polys = []
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            q = [(xs[i], ys[j]), (xs[i + 1], ys[j]), (xs[i + 1], ys[j + 1]), (xs[i], ys[j + 1])]
            polys.append((np.array([(a, b, f(a, b)) for a, b in q]), "slope"))
    polys.append((np.array([(-2000, 0, 0), (2000, 0, 0), (2000, 0, 900), (-2000, 0, 900)]), "wall"))   # 竖直面：不应命中
    S2 = Support.from_polys(polys)
    for x, y in ((0, -1000), (333, -77), (-1999, -1)):
        assert abs(S1.z(x, y) - S2.z(x, y)) < 1e-6, "解析 / 多边形汤高程不一致"
    assert S2.z(0, 100) is None, "支承外应落空"
    n = S2.normal(0, -1000)
    assert np.allclose(n, np.array([0, -0.5, 1]) / math.hypot(0.5, 1), atol=1e-6), "法向"
    assert abs(S2.normal(0, -2)[1] - n[1]) < 1e-6, "边上单侧差分"
    r = S2.room((0, -1000), (0, 1), step=10.0)
    assert 1000 <= r <= 1010, "离边距离 %.1f" % r
    D = S2.drape([(0, -100), (0, 0), (0, 40), (0, 80)])
    assert abs(D[2, 2] - f(0, 40)) < 1e-6 and abs(D[3, 2] - f(0, 80)) < 1e-6, "边外直线外推"
    U = Support.union([S2, Support.from_func(lambda x, y: 2000.0, inside=lambda x, y: abs(x) < 100 and abs(y) < 100)])
    assert U.z(0, -50) == 2000.0 and abs(U.z(500, -50) - f(500, -50)) < 1e-6, "并集取最高"
    print("support selftest ok：参数曲面（法向 / 标架 / 偏移 / 闭合壳 / 管）、解析 = 多边形汤、竖直面不命中、边上法向、离边距离、边外外推、并集")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    selftest() if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest") else print(__doc__)
