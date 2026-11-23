# -*- coding: utf-8 -*-
"""
parts：面上安装件与小件（几何原语层，领域无关，纯 numpy）。原理见 references/geometry-math.md §7、§7b、§8。
输出都是多边形汤 [(pts(k, 3), tag)]，全四边面 + 平面 n-gon 收口，闭合实体（polys_bpy.build_from 成件）。

局部标架
  frame(o, ex, ey, ez, shear=0)            局部 (a, b, c) → 世界 o + a·ex + b·ey + (c + shear·b)·ez
  face_frame(A1, A2, B1, B2, out)          安装折面四角（A = 前站两角，B = 后站两角）→ (中心, ex 沿板, ey 沿轴, ez 朝外)；
                                            out = 朝外参考（向量，或返回参考向量的函数 f(c)）
  seat_offset(samples, c, ez, lift)        落座：占地范围内支承点沿 ez 的最高处 + lift（件底抬到这里，不沉不悬）
  surface_seat(surf, u, v, hu, hv, lift)   柔性 / 曲面支承（support.Surface）上的落座：面帧 + 占地 [u±hu]×[v±hv] 实测最高 → to_w
实体
  quads(A, B, tag)                          两条同点数闭环之间的四边面带
  block(to_w, sx, sy, h, tag, win, floor)   方块 |a|≤sx、|b|≤sy、0≤c≤h；win=(wx, wy) 顶面开窗、窗底 c=floor
  lathe(rings, seg, to_w, tag, axis)        回转体：rings=[(r, t)] 沿局部轴；两端平面收口（销、铆钉、螺栓、轴套）
  rivet(o, ez, ex, r, h, sink, seg, tag)    圆顶铆钉（底沉入面 sink，避免共面贴合）
  tube_loop(path, N, profile, tag)          沿闭合路径扫掠闭合截面 → 环面实体（带扣框、带环、垫圈、箍）
  rounded_rect(w, h, r, n)                  圆角矩形闭合路径（局部 (a, b)）
  buckle(to_w, w, h, r, wire, tag)          带扣 = 圆截面框（tube_loop）+ 扣针（lathe，从横档伸到前框）
  keeper(to_w, w, h, t, depth, tag)         带环 = 扁矩形截面的圆角矩形环
  torus(to_w, R, r, seg, rseg, tag)         圆环（拉环、吊环、垫圈）：环面在局部 (a, b)，中心在原点
  angle_plate(to_w, l1, l2, h, t, tag)      折角片（包角、角码）：两翼沿局部 +a、+b，内角贴棱线（原点 = 棱线底端），高 h、厚 t，外包
  tapered_bar(p_top, p_bot, s_top, s_bot, tag, up)   收分方杆（家具腿、桁杆）：两端方截面边长 s_top → s_bot，轴线可斜（外撇）
  strap(surf, uv, width, thick, clear, tag) 皮带：曲面 surf 上的中线 uv 列 → 外偏 clear + thick/2，圆角扁截面扫掠；
                                            tip = 尾端收尖长度（0 = 平头）
[实测：科幻护臂铰座（face_frame + seat_offset + block 开窗 + lathe 销 + rivet）——从 case-gauntlet/gen2.py 抽出；
 皮带 / 带扣 / 带环 [自检]：冷读审查提出，合成测试通过，还没在项目里用过]
"""
import math
import numpy as np


def unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


# ---------------------------------------------------------------- 标架与落座
def frame(o, ex, ey, ez, shear=0.0):
    o, ex, ey, ez = (np.asarray(t, float) for t in (o, ex, ey, ez))
    return lambda a, b, c: o + a * ex + b * ey + (c + shear * b) * ez


def face_frame(A1, A2, B1, B2, out):
    A1, A2, B1, B2 = (np.asarray(p, float) for p in (A1, A2, B1, B2))
    c = (A1 + A2 + B1 + B2) / 4
    ex = unit(A2 - A1)
    ey = unit((B1 + B2) / 2 - (A1 + A2) / 2)
    ey = unit(ey - ex * (ey @ ex))
    ez = unit(np.cross(ex, ey))
    ref = out(c) if callable(out) else np.asarray(out, float)
    if ez @ ref < 0:
        ez, ex = -ez, -ex                      # 保持右手系
    return c, ex, ey, ez


def seat_offset(samples, c, ez, lift=0.2):
    S = np.atleast_2d(np.asarray(samples, float))
    return max(float(((S - c) @ ez).max()), 0.0) + lift


def surface_seat(surf, u, v, hu, hv, lift=0.2, along="v", n=7):
    F = surf.frame(u, v, along=along)
    c = surf.point(u, v)
    S = [surf.point(uu, vv) for uu in np.linspace(u - hu, u + hu, n) for vv in np.linspace(v - hv, v + hv, n)]
    z = seat_offset(S, c, F[:, 2], lift)
    return frame(c + F[:, 2] * z, F[:, 0], F[:, 1], F[:, 2]), z


# ---------------------------------------------------------------- 实体
def quads(A, B, tag):
    n = len(A)
    return [(np.array([A[i], A[(i + 1) % n], B[(i + 1) % n], B[i]]), tag) for i in range(n)]


def block(to_w, sx, sy, h, tag, win=None, floor=0.0):
    loop = lambda ax, by, c: [to_w(-ax, -by, c), to_w(ax, -by, c), to_w(ax, by, c), to_w(-ax, by, c)]
    B0, B1 = loop(sx, sy, 0.0), loop(sx, sy, h)
    out = [(np.array(B0[::-1]), tag)] + quads(B0, B1, tag)
    if win is None:
        return out + [(np.array(B1), tag)]
    I1, I0 = loop(win[0], win[1], h), loop(win[0], win[1], floor)
    return out + quads(B1, I1, tag) + quads(I1, I0, tag) + [(np.array(I0), tag)]


def lathe(rings, seg, to_w, tag, axis="a"):
    R3 = []
    for r, t in rings:
        ring = []
        for ang in np.linspace(0, 2 * math.pi, seg, endpoint=False):
            p, q = r * math.cos(ang), r * math.sin(ang)
            ring.append(to_w(t, p, q) if axis == "a" else to_w(p, q, t))
        R3.append(ring)
    out = []
    for A, B in zip(R3, R3[1:]):
        out += quads(A, B, tag)
    return out + [(np.array(R3[0][::-1]), tag), (np.array(R3[-1]), tag)]


def rivet(o, ez, ex, r, h, sink, seg=16, tag="rivet"):
    ez = unit(ez)
    ex = unit(np.asarray(ex, float) - (np.asarray(ex, float) @ ez) * ez)
    rings = [(r, -sink), (r, 0.0), (r * 0.85, h * 0.6), (r * 0.5, h * 0.93), (r * 0.15, h)]
    return lathe(rings, seg, frame(o, ex, np.cross(ez, ex), ez), tag, axis="c")


def rounded_rect(w, h, r, n=4):
    r = min(r, w / 2 - 1e-9, h / 2 - 1e-9)
    cs = [(w / 2 - r, h / 2 - r, 0.0), (-w / 2 + r, h / 2 - r, 0.5 * math.pi),
          (-w / 2 + r, -h / 2 + r, math.pi), (w / 2 - r, -h / 2 + r, 1.5 * math.pi)]
    pts = []
    for cx, cy, a0 in cs:
        for k in range(n + 1):
            a = a0 + 0.5 * math.pi * k / n
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.array(pts)


def tube_loop(path, N, profile, tag):
    """path：闭合路径点 (m, 3)（首尾不重复）；N：每点的截面 v 轴（单个向量 = 处处相同）；profile：[(u, v)] 闭合截面。"""
    P = np.asarray(path, float)
    m = len(P)
    N = np.broadcast_to(np.asarray(N, float), P.shape)
    rings = []
    for i in range(m):
        t = unit(P[(i + 1) % m] - P[i - 1])
        n = unit(N[i] - t * (N[i] @ t))
        lat = np.cross(n, t)
        rings.append(np.array([P[i] + lat * u + n * v for u, v in profile]))
    out = []
    for i in range(m):
        out += quads(rings[i], rings[(i + 1) % m], tag)
    return out


def _circle(r, seg):
    return [(r * math.cos(a), r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, seg, endpoint=False)]


def buckle(to_w, w, h, r, wire, tag="buckle", seg=8, n=4):
    """框在局部 (a, b) 平面、中心在原点、离面 c = wire；扣针从后框（b = −h/2）中点伸到前框（b = +h/2）上方。"""
    path = [to_w(a, b, wire) for a, b in rounded_rect(w, h, r, n)[:-1]]
    ez = unit(to_w(0, 0, 1) - to_w(0, 0, 0))
    out = tube_loop(path, ez, _circle(wire, seg), tag)
    pr = wire * 0.7
    prong = frame(to_w(0, -h / 2, 2 * wire + pr * 0.5), unit(to_w(0, 1, 0) - to_w(0, 0, 0)), unit(to_w(1, 0, 0) - to_w(0, 0, 0)), -ez)
    out += lathe([(pr, 0.0), (pr, h - wire), (pr * 0.3, h + wire * 0.5)], seg, prong, tag + "_prong", axis="a")
    return out


def keeper(to_w, w, h, t, depth, tag="keeper", n=4):
    """带环：内口 w × h（皮带宽 × 皮带厚 + 间隙），截面厚 t、沿带方向宽 depth；环面在局部 (a, c)，带沿 b 穿过。"""
    path = [to_w(a, 0.0, c) for a, c in rounded_rect(w + t, h + t, t, n)[:-1]]
    ey = unit(to_w(0, 1, 0) - to_w(0, 0, 0))
    prof = [(-t / 2, -depth / 2), (t / 2, -depth / 2), (t / 2, depth / 2), (-t / 2, depth / 2)]
    return tube_loop(path, ey, prof, tag)


def torus(to_w, R, r, seg=24, rseg=8, tag="torus"):
    path = [to_w(R * math.cos(a), R * math.sin(a), 0.0) for a in np.linspace(0, 2 * math.pi, seg, endpoint=False)]
    ez = unit(to_w(0, 0, 1) - to_w(0, 0, 0))
    return tube_loop(path, ez, _circle(r, rseg), tag)


def angle_plate(to_w, l1, l2, h, t, tag="angle"):
    """L 形截面（外包棱线）沿局部 c 拉伸 h。截面：外角在原点外侧 (−t, −t)，两翼沿 +a 长 l1、沿 +b 长 l2。"""
    sec = [(-t, -t), (l1, -t), (l1, 0.0), (0.0, 0.0), (0.0, l2), (-t, l2)]
    A = [to_w(a, b, 0.0) for a, b in sec]
    B = [to_w(a, b, h) for a, b in sec]
    out = quads(A, B, tag)
    for loop, flip in ((A, True), (B, False)):           # 凹六边形端面拆成两块凸四边形
        q1 = [loop[0], loop[1], loop[2], loop[3]]
        q2 = [loop[0], loop[3], loop[4], loop[5]]
        for q in (q1, q2):
            out.append((np.array(q[::-1] if flip else q), tag))
    return out


def tapered_bar(p_top, p_bot, s_top, s_bot, tag="bar", up=(0.0, 1.0, 0.0)):
    """方截面沿轴 p_bot → p_top，边长线性 s_bot → s_top；截面一边对齐 up 在截面平面上的投影。"""
    a, b = np.asarray(p_bot, float), np.asarray(p_top, float)
    ez = unit(b - a)
    ey = unit(np.asarray(up, float) - ez * (np.asarray(up, float) @ ez))
    ex = np.cross(ey, ez)
    sq = lambda c, s: [c + (ex * u + ey * v) * s / 2 for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    A, B = sq(a, s_bot), sq(b, s_top)
    return [(np.array(A[::-1]), tag)] + quads(A, B, tag) + [(np.array(B), tag)]


def strap(surf, uv, width, thick, clear, tag="strap", r=None, tip=0.0, nr=2):
    """surf：support.Surface；uv：中线参数点列 (k, 2)。截面 = 圆角扁矩形（r 默认 thick/2·0.8）；
    尾端 tip > 0：最后 tip 长度内宽度收到 30%（圆尖头）。返回 (polys, 中线 3D 点)。"""
    UV = np.asarray(uv, float)
    C = np.array([surf.point(u, v) for u, v in UV])
    Nn = np.array([surf.normal(u, v) for u, v in UV])
    P = C + Nn * (clear + thick / 2)
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    r = thick / 2 * 0.8 if r is None else r
    rings = []
    for i in range(len(P)):
        t = unit(P[min(i + 1, len(P) - 1)] - P[max(i - 1, 0)])
        n = unit(Nn[i] - t * (Nn[i] @ t))
        lat = np.cross(n, t)
        k = 1.0 if tip <= 0 or s[-1] - s[i] >= tip else 0.3 + 0.7 * math.sqrt(max(0.0, (s[-1] - s[i]) / tip))
        prof = rounded_rect(width * k, thick, r, nr)[:-1]
        rings.append(np.array([P[i] + lat * a + n * b for a, b in prof]))
    out = []
    for A, B in zip(rings, rings[1:]):
        out += quads(A, B, tag)
    return out + [(rings[0][::-1].copy(), tag), (rings[-1].copy(), tag)], P


# ---------------------------------------------------------------- 自检
def _closed(polys):
    e = {}
    for Pq, _ in polys:
        k = [tuple(np.round(p, 5)) for p in Pq]
        for i in range(len(k)):
            key = tuple(sorted((k[i], k[(i + 1) % len(k)])))
            e[key] = e.get(key, 0) + 1
    return all(v == 2 for v in e.values())


def _planar(polys, tol=1e-6):
    for Pq, _ in polys:
        Pq = np.asarray(Pq)
        if len(Pq) > 3:
            c = Pq.mean(0)
            if np.linalg.svd(Pq - c)[1][-1] > tol * (1 + np.abs(Pq).max()):
                return False
    return True


def selftest():
    import support
    I = frame((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))
    b = block(I, 10, 6, 8, "box", win=(7, 3), floor=1.5)
    assert _closed(b) and _planar(b) and all(len(p) == 4 for p, _ in b), "开窗块：闭合、全四边面"
    L = lathe([(3, -5), (3, 5), (1, 6)], 12, I, "pin")
    assert _closed(L), "回转体闭合"
    # 安装折面：半径 50 的柱面（轴 = y）上一段平折面，前后两站 y = 0 / 20，角度 20°–60°
    ring = lambda y, a: np.array([50 * math.sin(a), y, 50 * math.cos(a)])
    a0, a1 = math.radians(20), math.radians(60)
    c, ex, ey, ez = face_frame(ring(0, a0), ring(0, a1), ring(20, a0), ring(20, a1), out=lambda c: np.array([c[0], 0, c[2]]))
    Fm = np.column_stack([ex, ey, ez])
    assert np.allclose(Fm.T @ Fm, np.eye(3), atol=1e-9) and np.linalg.det(Fm) > 0, "面帧正交、右手"
    assert ez @ np.array([c[0], 0, c[2]]) > 0, "ez 朝外"
    # 落座：占地内是柱面（弦面以外鼓起），件底须抬到最高点之上
    S = [ring(y, a) for y in np.linspace(0, 20, 5) for a in np.linspace(a0, a1, 9)]
    z = seat_offset(S, c, ez, lift=0.2)
    assert z > 0.2 and all((np.asarray(p) - c) @ ez <= z - 0.2 + 1e-9 for p in S), "落座在最高点之上"
    # 曲面（柔性件）落座
    cyl = support.Surface(lambda u, v: (50 * math.sin(u), v, 50 * math.cos(u)))
    tw, zz = surface_seat(cyl, 0.3, 10.0, 0.2, 5.0, lift=0.2)
    assert zz >= 0.2 and abs(np.linalg.norm(tw(0, 0, 0)[[0, 2]]) - 50 - zz) < 1e-6, "曲面落座：在面帧法向上抬 zz"
    rv = rivet((0, 0, 0), (0, 0, 1), (1, 0, 0), 2.0, 1.5, 0.3, 12)
    assert _closed(rv) and min(p[:, 2].min() for p, _ in rv) < 0, "铆钉闭合、底沉入面"
    bk = buckle(I, 30, 20, 4, 1.2)
    assert _closed([p for p in bk if p[1] == "buckle"]) and _closed([p for p in bk if p[1] == "buckle_prong"]), "带扣框、扣针各自闭合"
    assert _closed(torus(I, 20, 3)), "圆环闭合"
    ap = angle_plate(I, 40, 30, 50, 2)
    assert _closed(ap) and _planar(ap) and all(len(p) == 4 for p, _ in ap), "折角片闭合、全四边面"
    tb = tapered_bar((0, 0, 160), (15, 10, 0), 40, 24)
    assert _closed(tb) and _planar(tb), "收分方杆闭合、端面平"
    kp = keeper(I, 25, 3, 1.0, 6)
    assert _closed(kp) and all(len(p) == 4 for p, _ in kp), "带环闭合、全四边面"
    # 皮带：绕柱面半圈，离面 clear，厚 2；任何截面点都在柱面外 ≥ clear − 圆角误差
    uv = [(u, 30.0 + 5 * math.sin(u)) for u in np.linspace(-1.5, 1.5, 25)]
    sp, mid = strap(cyl, uv, 20, 2.0, 0.3, tip=15.0)
    assert _closed(sp), "皮带闭合"
    rr = min(np.hypot(p[:, 0], p[:, 2]).min() for p, _ in sp)
    assert rr >= 50 + 0.3 - 1e-6, "皮带不进支承：最近 %.3f" % (rr - 50)
    w_end = np.linalg.norm(sp[-1][0].max(0) - sp[-1][0].min(0))
    assert w_end < 0.5 * 20 + 3, "尾端收尖"
    print("parts selftest ok：开窗块 / 回转体 / 铆钉 / 带扣 / 带环 / 皮带 / 圆环 / 折角片 / 收分方杆 闭合；面帧正交朝外；折面与曲面落座在实测最高点之上；皮带不进支承、尾端收尖")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    selftest() if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest") else print(__doc__)
