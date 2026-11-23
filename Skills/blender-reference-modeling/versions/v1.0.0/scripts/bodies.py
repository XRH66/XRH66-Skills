# -*- coding: utf-8 -*-
"""
bodies：剪影体与浮雕板（几何原语层，领域无关，纯 numpy）。原理见 references/levels.md §3（剪影体）、§5（纹饰分诊与浮雕）。
不规则件（吻兽、兽面、涡卷徽饰）先做到剪影体 / 浮雕板这一级，再挖规律；不要拿照片灰度当高度。

  superellipse(a, b, n, m)                   超椭圆截面点（n = 2 椭圆，越大越方）
  silhouette_body(t, w, d, n, m, tag, axis)  两视剪影 → 体：沿主轴站 t，正视宽 w(t)、侧视深 d(t)（全宽），截面超椭圆，
                                             同拓扑环放样 + 两端收口 → 闭合四边面实体。宽 / 深 ≤ 0 的站自动收成小环
  width_from_mask(mask, axis)                二值剪影（行 = 主轴）→ 每行宽度与中心（ref_trace 掩膜或渲染 alpha）
  relief_slab(outlines, size, base, res, tag)    浮雕板：layers = [(闭合轮廓 (k, 2), 高 H, 斜边宽 bevel, 鼓 dome)] 逐层叠加
                                             （台地：外层先、内层叠上去），高度 = Σ formkit.relief_height(sdf)；
                                             输出矩形底板 + 高度场顶面的闭合四边面实体（局部 (x, y, z)，z 向上）；
                                             res ≤ 斜边宽 / 3，否则轮廓呈锯齿（高度场的固有代价——要锐利轮廓就改用台地放样或法线）
[自检：剪影体正 / 侧投影宽度回到输入、闭合；浮雕板闭合、轮廓内高度 = 各层之和、轮廓外 = 底板。还没在项目里用过]
"""
import math
import numpy as np
import formkit


def superellipse(a, b, n=2.0, m=24):
    th = np.linspace(0, 2 * math.pi, m, endpoint=False)
    c, s = np.cos(th), np.sin(th)
    e = 2.0 / n
    return np.stack([a * np.sign(c) * np.abs(c) ** e, b * np.sign(s) * np.abs(s) ** e], 1)


def _quads(A, B, tag):
    m = len(A)
    return [(np.array([A[i], A[(i + 1) % m], B[(i + 1) % m], B[i]]), tag) for i in range(m)]


def silhouette_body(t, w, d, n=2.5, m=24, tag="body", cx=None, cz=None, min_r=0.5):
    """主轴沿 y：站 t（mm），截面在 (x, z)；cx / cz = 每站剪影中心偏移（可缺）。"""
    t, w, d = (np.asarray(v, float) for v in (t, w, d))
    cx = np.zeros_like(t) if cx is None else np.asarray(cx, float)
    cz = np.zeros_like(t) if cz is None else np.asarray(cz, float)
    rings = []
    for ti, wi, di, xi, zi in zip(t, w, d, cx, cz):
        q = superellipse(max(wi / 2, min_r), max(di / 2, min_r), n, m)
        rings.append(np.column_stack([q[:, 0] + xi, np.full(m, ti), q[:, 1] + zi]))
    out = []
    for A, B in zip(rings, rings[1:]):
        out += _quads(A, B, tag)
    return out + [(rings[0].copy(), tag), (rings[-1][::-1].copy(), tag)]


def width_from_mask(mask, axis=0):
    M = np.asarray(mask, bool)
    if axis == 1:
        M = M.T
    W, C = [], []
    for row in M:
        idx = np.flatnonzero(row)
        W.append(idx[-1] - idx[0] + 1 if len(idx) else 0)
        C.append((idx[-1] + idx[0]) / 2 if len(idx) else np.nan)
    return np.array(W, float), np.array(C, float)


def relief_slab(layers, size, base=2.0, res=1.0, tag="relief"):
    """size = (X, Y)：板以原点为中心；res = 网格间距（mm）。顶面高度 = base + Σ 层高。"""
    X, Y = size
    nx, ny = max(2, int(round(X / res)) + 1), max(2, int(round(Y / res)) + 1)
    xs, ys = np.linspace(-X / 2, X / 2, nx), np.linspace(-Y / 2, Y / 2, ny)
    H = np.full((ny, nx), float(base))
    for poly, h, bevel, dome in layers:
        P = [tuple(p) for p in np.asarray(poly, float)]
        for j, y in enumerate(ys):
            for i, x in enumerate(xs):
                H[j, i] += formkit.relief_height(formkit.polygon_sdf((x, y), P), h, bevel, dome)
    G = np.stack(np.meshgrid(xs, ys), -1)
    top = np.concatenate([G, H[..., None]], -1)
    bot = np.concatenate([G, np.zeros((ny, nx, 1))], -1)
    out = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            out.append((np.array([top[j, i], top[j, i + 1], top[j + 1, i + 1], top[j + 1, i]]), tag))
    for j in range(ny - 1):                                                            # 底：同网格四边面（无 T 接）
        for i in range(nx - 1):
            out.append((np.array([bot[j, i], bot[j + 1, i], bot[j + 1, i + 1], bot[j, i + 1]]), tag))
    rim_t = [top[0, :], top[:, -1], top[-1, ::-1], top[::-1, 0]]
    rim_b = [bot[0, :], bot[:, -1], bot[-1, ::-1], bot[::-1, 0]]
    for a, b in zip(rim_t, rim_b):
        for k in range(len(a) - 1):
            out.append((np.array([a[k + 1], a[k], b[k], b[k + 1]]), tag))
    return out, H


def _edges_ok(polys):
    """边 → 被几个面共享（闭合实体每条边恰好 2）。"""
    e = {}
    for Pq, _ in polys:
        k = [tuple(np.round(p, 5)) for p in Pq]
        for i in range(len(k)):
            key = tuple(sorted((k[i], k[(i + 1) % len(k)])))
            e[key] = e.get(key, 0) + 1
    return e


def selftest():
    t = np.linspace(0, 120, 25)
    w = 40 + 15 * np.sin(np.pi * t / 120)
    d = 25 + 8 * np.sin(np.pi * t / 120)
    B = silhouette_body(t, w, d, n=2.5, m=24)
    e = _edges_ok(B)
    assert all(v == 2 for v in e.values()), "剪影体闭合"
    V = np.concatenate([p for p, _ in B])
    for ti, wi, di in zip(t[::6], w[::6], d[::6]):
        S = V[np.abs(V[:, 1] - ti) < 1e-6]
        assert abs((S[:, 0].max() - S[:, 0].min()) - wi) < 1e-6 and abs((S[:, 2].max() - S[:, 2].min()) - di) < 1e-6, "正 / 侧投影宽度"
    mask = np.zeros((10, 30), bool)
    mask[2:8, 5:20] = True
    W, C = width_from_mask(mask)
    assert W[3] == 15 and C[3] == 12 and W[0] == 0, "掩膜宽度"
    sq = [(-10, -10), (10, -10), (10, 10), (-10, 10)]
    inner = [(-4, -4), (4, -4), (4, 4), (-4, 4)]
    R, H = relief_slab([(sq, 3.0, 1.5, 0.0), (inner, 2.0, 1.0, 0.0)], (30, 30), base=2.0, res=1.0)
    assert abs(H[15, 15] - 7.0) < 1e-6 and abs(H[0, 0] - 2.0) < 1e-9 and abs(H[15, 9] - 5.0) < 0.6, "台地高度"
    assert all(v == 2 for v in _edges_ok(R).values()) and all(len(p) == 4 for p, _ in R), "浮雕板闭合、全四边面"
    print("bodies selftest ok：剪影体闭合、正 / 侧宽度回到输入；掩膜宽度；浮雕板台地高度 = 各层之和、轮廓外 = 底板、顶 / 侧闭合")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    selftest() if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest") else print(__doc__)
