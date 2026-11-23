# -*- coding: utf-8 -*-
"""几何原语层合成测试：各模块 selftest（support / sweep / arrange / instancing / facets / parts / bodies / multiview / profilefit；--quick 跳过 profilefit） + 一个串起来的合成场景（无 Blender）。
场景：四坡锥面（多边形汤）当支承 → 底边等距起点、沿坡向上推进到斜脊为止 → drape 取高程、法向定标架 → 实例记录 + 镜像
→ 沿两条斜脊放样盖条（顶点斜接）→ 检查：件都在支承上、盖条底不低于支承、镜像件与原件对称、两层叠放净距。
    python primitives_selftest.py
"""
import sys
import numpy as np
import support, sweep, arrange, instancing as inst, facets, parts, bodies, multiview, profilefit


def scene():
    H, A = 1000.0, 2000.0                                          # 锥高、半边长
    apex = np.array([0, 0, H])
    base = [np.array(p) for p in ((-A, -A, 0), (A, -A, 0), (A, A, 0), (-A, A, 0))]
    polys = [(np.array([base[i], base[(i + 1) % 4], apex]), "roof") for i in range(4)]
    S = support.Support.from_polys(polys)
    f = lambda x, y: H * (1 - max(abs(x), abs(y)) / A)

    # 前坡（y < 0 那面）：底边起点，沿 +y 走到斜脊 |x| = |y| 前一步
    hips = [np.array([(-A, -A), (0, 0)]), np.array([(A, -A), (0, 0)])]
    recs, n_pts = [], 0
    for q, _, _ in arrange.starts_along([(0, -A), (A, -A)], 250.0):          # 右半，左半镜像
        stop = lambda p, n: min(arrange.dist_to_polyline(p, h)[0] for h in hips) < 60.0 or p[1] >= 0
        row = arrange.march(q, (0, 1), 200.0, stop)
        if len(row) < 2:
            continue
        P = S.drape(row)
        assert P is not None and np.allclose(P[:, 2], [f(x, y) for x, y in row], atol=1e-6), "drape 高程"
        for i in range(len(P) - 1):
            Y = P[i + 1] - P[i]
            recs.append(inst.record(P[i], Y, S.normal(*P[i, :2], eps=20.0), length=np.linalg.norm(Y), L0=200.0, var=i % 3))
        n_pts += len(P)
    assert len(recs) > 20, "排布太少"
    for r in recs:                                                  # 件 Z 轴 = 支承法向（前坡法向 (0, −0.5, 1)/|·|）
        Z = inst.matrix_from(r["rot"])[:, 2]
        assert np.allclose(Z, np.array([0, -0.5, 1]) / np.hypot(0.5, 1), atol=1e-6), "标架 Z ≠ 法向"
    full = recs + inst.mirror(recs, axis=0)
    for a, b in zip(recs, full[len(recs):]):
        Ra, Rb = inst.matrix_from(a["rot"]), inst.matrix_from(b["rot"])
        assert np.allclose(Rb[:, 1], Ra[:, 1] * (-1, 1, 1)) and np.isclose(np.linalg.det(Rb), 1), "镜像"

    # 沿两条斜脊放样盖条：网络 = 左斜脊上行 + 右斜脊下行，顶点斜接；截面贴支承、离开 6 mm
    up = lambda h: [(x, y, f(x, y)) for x, y in np.linspace(h[0], h[1], 21)]
    net = sweep.Network().edge("L", up(hips[0])).edge("R", up(hips[1]))
    st = sweep.decimate(net.path(["L", "-R"], side=1.0, clear=0.45 * 120.0), 60.0)
    assert sum(1 for s in st if s.get("miter")) == 1, "顶点斜接"
    w = 60.0

    def prof(s):
        p, l = np.asarray(s["p"]), np.asarray(s["lat"])
        zs = [S.z(*(p[:2] + l * u)) for u in (-w, w)]
        if any(z is None for z in zs):
            return None
        zb = max(zs + [p[2]]) + 6.0
        return [(-w, zb), (w, zb), (w, zb + 40), (-w, zb + 40)]
    strips = sweep.sweep(st, prof)
    polys = sweep.loft_polys(strips, "cap")
    assert strips and polys, "放样为空"
    for rings in strips:
        for ring in rings:
            for x, y, z in ring[:2]:                                 # 截面底边两点不低于支承
                zs = S.z(x, y)
                assert zs is None or z >= zs + 6.0 - 1e-6, "盖条底穿入支承"

    # 叠层：上层件底面沿公共采样与下层顶面的侵入量
    s = np.linspace(0, 1, 21)
    drop = inst.stack_drop(f(0, -1500) + 30 + 10 * s, f(0, -1500) + 25 + 0 * s, extra=4.0)
    assert abs(drop - 19.0) < 1e-9, "叠层净距"
    return dict(instances=len(full), stations=len(st), polys=len(polys), drop=drop)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for m in (support, sweep, arrange, inst, facets, parts, bodies, multiview):
        m.selftest()
    if "--quick" not in sys.argv:
        profilefit.selftest()                                       # 约 30 s（多起点 Nelder–Mead）
    print("scene ok", scene())
