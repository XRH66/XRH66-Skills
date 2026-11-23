# -*- coding: utf-8 -*-
"""
roofkit：中式带翼角屋顶的转角模块（方案族）。纯 numpy；输出 preview 的多边形汤 [(quad, tag)]，Blender / Pillow 共用。
来源：修仙牌楼 E1 / B3 / C1 / C2（2026-11-20/21）抽成与项目无关的写法；项目只给数值（spec）和本体立面（body）。

两族
  blade（刀锋族）  平面收拢到翼尖（中轴上），没有山面。axis_beam=False → E1；True → B3（中轴角梁 + 翼角椽扇落角梁两侧）。
  true（真转角族） 45° 角梁，山面檐 = 前檐镜像的平面；山面檐高由 sag 连续控制：
                   sag = 1：镜像下垂（C1，山面陡、檐底 V 形折线）；sag = 0：抬平到"前檐在山面那个 x 处的高度"（C2，正视里山面檐藏在前檐后）；
                   中间值插值。cam 给定时前檐 / 戗脊沿参考视线对位（像点不变 = 按新平面重拟合），否则用本体原样。
  同族方案的差别只剩一个量（axis_beam / sag），对比才公平。

本体 body（项目给，右半 x ≥ 0，前檐 y < 0，单位 mm）
  U          檐下皮 [(x, z, θ)]（到翼尖）；U_ext (x, z)；E_ext_x 戗脊带末端 x
  z_under(x) z_eave(x) z_top(x)（中轴上的坡面上缘）plan_y(x)（刀锋族平面，负值）
  stations   [(xu, zu, xe, ze, θ)] 放样站；Hu / Hl 脊带上 / 下缘 [(x, z)]；eave_d 满出檐；x_cut 转角从此接上
尺寸 dims：band_w raft_pitch yc_set yc_l yc_r fc_h fc_w fc_l fc_recess raft_embed raft_min_y ridge_bw ridge_embed slope_n section_f
参数 par：见 TRUE_KEYS / BLADE_KEYS（项目 spec 里给全，这里不设默认值，单一数值源）

局限（等第二个案例再抽）：真转角只做矩形平面的 90° 角（plan_angle ≠ 90 直接报错）；Frame 已按任意平分线写好，
山面坐标、檐底折线在非 90° 下怎么定，要等八角亭这类案例来定。
"""
import math
import numpy as np

SQ2 = math.sqrt(2.0)
TRUE_KEYS = ("chong", "jl_w", "jl_h", "zjl_h", "ts_size", "side_blend", "fan_gamma", "fan_alpha_last", "clear_min",
             "yc_min_frac", "fc_min_frac", "slope_n", "soffit_n", "ext_n", "x_cut", "sag", "end_depth", "blend_tilt",
             "drain_min", "lao_end", "zai_out", "zjl_tail", "tail_auto", "station_stride")
BLADE_KEYS = ("jl_w", "jl_h", "zjl_h", "ts_size", "fan_gamma", "fan_alpha_last", "clear_min", "yc_min_frac", "fc_min_frac",
              "x_cut", "axis_beam", "lao_end", "zai_out", "zjl_tail")


def _need(par, keys, who):
    miss = [k for k in keys if k not in par]
    if miss:
        raise KeyError("%s 缺参数（应写在项目 spec 里）：%s" % (who, ", ".join(miss)))


def seg_point_dist(p, a, b):
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / max(float(np.dot(ab, ab)), 1e-12), 0.0, 1.0)
    return float(np.linalg.norm(p - (a + t * ab)))


def seg_seg_dist(p0, p1, q0, q1):
    d1, d2 = p1 - p0, q1 - q0
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) > 1e-12:
        r = q0 - p0
        t = (r[0] * d2[1] - r[1] * d2[0]) / den
        u = (r[0] * d1[1] - r[1] * d1[0]) / den
        if 0 <= t <= 1 and 0 <= u <= 1:
            return 0.0
    return min(seg_point_dist(p0, q0, q1), seg_point_dist(p1, q0, q1), seg_point_dist(q0, p0, p1), seg_point_dist(q1, p0, p1))


def smooth01(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


class Frame:
    """转角平面标架：T = 角点，Fd = 角梁轴（指向外），Fn = Fd 左法向。mir = 关于角梁竖直面的镜像。
    矩形 90° 角：Fd = (1, −1)/√2，mir(x, y) = (xs − y, xs − x)，xs = xT + yT。plan_angle = α 时 Fd 与 +x 夹角 −α/2。"""

    def __init__(self, T, axis_dir):
        self.T = np.asarray(T, float)
        d = np.asarray(axis_dir, float)
        self.Fd = d / np.linalg.norm(d)
        self.Fn = np.array([-self.Fd[1], self.Fd[0]])
        self.R = 2 * np.outer(self.Fd, self.Fd) - np.eye(2)

    @classmethod
    def bisector(cls, T, plan_angle_deg):
        a = -math.radians(plan_angle_deg) / 2
        return cls(T, (math.cos(a), math.sin(a)))

    def mir(self, p):
        p = np.asarray(p, float)
        q = self.T + self.R @ (p[:2] - self.T)
        return np.array([q[0], q[1], p[2]]) if len(p) == 3 else q

    def mir_dir(self, d):
        return self.R @ np.asarray(d, float)[:2]

    def sigma(self, p):
        """到角梁轴的有符号距离（前檐一侧为负）。"""
        return float(np.dot(np.asarray(p, float)[:2] - self.T, self.Fn))


# ==================================================================== 公共：椽头序列、翼角椽扇、截长、构造检查、角梁
class CornerBase:
    def _base(self, body, dims, par):
        self.b, self.d, self.P = body, dims, par
        self.Wb = dims["band_w"]
        self.need = dims["yc_set"] + dims["yc_l"] + dims["yc_r"]   # 正身椽露明末端离椽头

    def _set_frame(self, T, axis_dir):
        self.fr = Frame(T, axis_dir)
        self.T, self.Fd, self.Fn = self.fr.T, self.fr.Fd, self.fr.Fn    # Fn：σ 正向 = 背离前檐（侧檐 / 后檐一侧）
        self.F0f = self.T - self.Fn * self.P["jl_w"] / 2                # 角梁前侧面（线：F0f + λ·Fd）

    def sigma(self, p):
        return float(np.dot(np.asarray(p, float)[:2] - self.T, self.Fn))

    def _heads(self, path):
        """椽头沿檐下皮 3D 弧长等距（半椽距起），法向指向中轴。"""
        out, acc, nxt = [], 0.0, self.d["raft_pitch"] / 2
        for a, b in zip(path, path[1:]):
            L = float(np.linalg.norm(b - a))
            while acc + L >= nxt:
                p = a + (b - a) * ((nxt - acc) / max(L, 1e-9))
                t2 = (b - a)[:2] / np.linalg.norm((b - a)[:2])
                N = np.array([-t2[1], t2[0]])
                if N[1] < 0:
                    N = -N
                out.append((p, N))
                nxt += self.d["raft_pitch"]
            acc += L
        return out

    def _gap(self, p, d, F0):
        A = np.array([[d[0], -self.Fd[0]], [d[1], -self.Fd[1]]])
        if abs(np.linalg.det(A)) < 1e-9:
            return 1e9
        s, _ = np.linalg.solve(A, F0 - p)
        return s if s > 0 else 1e9

    def fan(self, heads, normals, F0, gamma, alpha_last_deg):
        """翼角椽扇：尾落角梁侧面，λ = λ0 + (λ1 − λ0)·t^γ 单调聚拢；末根与角梁夹 alpha_last。"""
        Fd, Fn = self.Fd, np.array([-self.Fd[1], self.Fd[0]])
        A = np.array([[normals[0][0], -Fd[0]], [normals[0][1], -Fd[1]]])
        _, lam0 = np.linalg.solve(A, F0 - heads[0])
        pl = heads[-1]
        dist = abs(float(np.dot(pl - F0, Fn)))
        assert dist > 1.0, "末根椽头压在角梁面上"
        lam1 = float(np.dot(pl - F0, Fd)) - dist / math.tan(math.radians(alpha_last_deg))
        n, out = len(heads), []
        for k in range(n):
            lam = lam0 + (lam1 - lam0) * (k / max(n - 1, 1)) ** gamma
            tail = F0 + lam * Fd
            dv = tail - heads[k]
            L = float(np.linalg.norm(dv))
            out.append(dict(head=heads[k], tail=tail, lam=float(lam), dir=dv / L, L=L, nrm=normals[k], fan=True))
        return out

    def front_rafters(self):
        """前檐右半全部椽（正身 + 翼角扇）；返回 (seq, k0)，k0 = 首根扇椽。"""
        P, H = self.P, self.heads
        k0 = next(k for k, (p, N) in enumerate(H) if self._gap(p[:2], N, self.F0f) <= self.need)
        sig = np.array([self.sigma(p[:2]) for (p, N) in H])
        k1 = len(H) - 1
        while k1 >= k0 and sig[k1] > -(P["jl_w"] / 2 + self.d["yc_r"] + 10.0):
            k1 -= 1
        seq = [dict(head=p[:2].copy(), dir=N.copy(), L=self.need, nrm=N.copy(), lam=None, fan=False, z3=p.copy()) for (p, N) in H[:k0]]
        R = self.fan(np.array([p[:2] for (p, N) in H[k0:k1 + 1]]), np.array([N for (p, N) in H[k0:k1 + 1]]),
                     self.F0f, P["fan_gamma"], P["fan_alpha_last"])
        for r, (p, N) in zip(R, H[k0:k1 + 1]):
            r["z3"] = p.copy()
        seq += R
        self.cut_lengths(seq)
        return seq, k0

    # ---- 檐底高（椽、角梁贴它）
    def zu_at(self, p):
        return self.zu(p[0])

    def side_at(self, p):
        return self.zu(p[0])

    def zf(self, r):
        return self.side_at if r.get("side") == "s" else self.zu_at

    def offsets(self):
        d = self.d
        return dict(yc=-d["fc_h"] + d["raft_embed"] - d["yc_r"], fc=d["raft_embed"] - d["fc_h"] / 2,
                    yc_bot=-d["fc_h"] + d["raft_embed"] - 2 * d["yc_r"], fc_bot=d["raft_embed"] - d["fc_h"])

    def rafter_line3(self, r, start, zoff):
        a = r["head"] + r["dir"] * start
        b = r["head"] + r["dir"] * max(r["L"], start + 1.0)
        zf = self.zf(r)
        return np.array([a[0], a[1], zf(a) + zoff]), np.array([b[0], b[1], zf(b) + zoff])

    def cut_lengths(self, seq):
        """檐椽 / 飞椽露明长按相邻椽 3D 中心线净距截（翼尖段相邻椽在高度上错开，平面重叠 ≠ 相撞）。"""
        d, gap, off = self.d, self.P["clear_min"], self.offsets()

        def cut(start, nominal, D, key, zoff, tail_room):
            lines = [self.rafter_line3(r, start, zoff) for r in seq]
            for r in seq:
                r[key] = min(start + nominal, r["L"] - tail_room)

            def pt(i, s_):
                r = seq[i]
                a, b = lines[i]
                return a + (b - a) * ((s_ - start) / max(max(r["L"], start + 1.0) - start, 1e-9))
            for i, r in enumerate(seq):
                nb = [j for j in (i - 1, i + 1) if 0 <= j < len(seq)]
                lo, hi = start, r[key]
                ok = lambda s_: all(seg_point_dist(pt(i, s_), *lines[j]) >= D for j in nb)
                if hi <= lo or ok(hi):
                    continue
                for _ in range(40):
                    mid = (lo + hi) / 2
                    lo, hi = (mid, hi) if ok(mid) else (lo, mid)
                r[key] = lo
        cut(d["yc_set"], d["yc_l"], 2 * d["yc_r"] + gap, "s_yc", off["yc"], d["yc_r"])
        cut(d["fc_recess"], d["fc_l"], d["fc_w"] + gap, "s_fc", off["fc"], 5.0)
        for r in seq:
            r["vis"] = max(0.0, r["s_yc"] - d["yc_set"])
            r["fc"] = max(0.0, r["s_fc"] - d["fc_recess"])
        return seq

    def checks(self, seq, k0):
        d, off = self.d, self.offsets()
        R = seq[k0:]
        lam = np.array([r["lam"] for r in R])
        ang = [math.degrees(math.atan2(r["nrm"][0] * r["dir"][1] - r["nrm"][1] * r["dir"][0], float(np.dot(r["nrm"], r["dir"])))) for r in R]
        win = seq[k0 - 1:]
        cl, fcl, cl2 = [], [], []
        for r0, r1 in zip(win, win[1:]):
            for (start, key, zoff, wdt, dst) in ((d["yc_set"], "s_yc", off["yc"], 2 * d["yc_r"], cl), (d["fc_recess"], "s_fc", off["fc"], d["fc_w"], fcl)):
                if r0[key] - start < 1.0 or r1[key] - start < 1.0:
                    continue
                a0, b0 = self.rafter_line3(r0, start, zoff)
                a1, b1 = self.rafter_line3(r1, start, zoff)
                f0 = (r0[key] - start) / max(max(r0["L"], start + 1.0) - start, 1e-9)
                f1 = (r1[key] - start) / max(max(r1["L"], start + 1.0) - start, 1e-9)
                e0, e1 = a0 + (b0 - a0) * f0, a1 + (b1 - a1) * f1
                dst.append(min(seg_point_dist(a0 + (e0 - a0) * u, a1, e1) for u in np.linspace(0, 1, 41)) - wdt)
            if r0["vis"] >= 1.0 and r1["vis"] >= 1.0:
                p0, q0 = r0["head"] + r0["dir"] * d["yc_set"], r0["head"] + r0["dir"] * r0["s_yc"]
                p1, q1 = r1["head"] + r1["dir"] * d["yc_set"], r1["head"] + r1["dir"] * r1["s_yc"]
                cl2.append(seg_seg_dist(p0, q0, p1, q1) - 2 * d["yc_r"])
        rnd = lambda v: round(float(v), 1)
        return dict(n_fan=len(R), lam0=rnd(lam[0]), lam1=rnd(lam[-1]),
                    tail_step_min=rnd(np.diff(lam).min()) if len(lam) > 1 else None, tail_monotone=bool(np.all(np.diff(lam) > 0)),
                    rot_max=rnd(max(abs(a) for a in ang)), yc_clear3d_min=rnd(min(cl)) if cl else None,
                    fc_clear3d_min=rnd(min(fcl)) if fcl else None, yc_clear_plan_min=rnd(min(cl2)) if cl2 else None,
                    vis=[round(r["vis"]) for r in R], fc=[round(r["fc"]) for r in R])

    # ---- 角梁：沿轴 λ（T − λ·Fd，λ < 0 = 出 T）
    def axis_pt(self, lam):
        return self.T - lam * self.Fd

    def z_axis(self, lam):
        return self.zu(self.axis_pt(lam)[0])

    def zjl_top(self, lam):
        """仔角梁顶 = 檐下皮 + 瓦口带竖高 − 20（与瓦口平，套兽落在檐口高度）。"""
        return self.z_axis(lam) + self.Wb * math.cos(self.th(self.axis_pt(lam)[0])) - 20.0


def beam_polys(K, tail_lao, tail_zai, n=36):
    """仔角梁 + 老角梁（叠其下，头停在 lao_end）+ 套兽（占位盒，套仔角梁头）。
    每根梁 = 一个整体扫掠实体（沿轴 n+1 个矩形截面 + 两端封口），不拼小盒（拼盒的端面重合 → 非流形、自交）；
    老 / 仔角梁 tag 分开（jl_lao / jl_zai）：上下面贴合共面，同一网格里会被审计算成自交，本来也是两根构件。"""
    from preview import box
    P, out = K.P, []

    def beam(l0, l1, top_fn, h, w, tag):
        ls = np.linspace(l0, l1, n + 1)
        rings = []
        for l in ls:
            p = K.axis_pt(l)
            zt = top_fn(l)
            rings.append([np.r_[p + K.Fn * w / 2, zt], np.r_[p - K.Fn * w / 2, zt], np.r_[p - K.Fn * w / 2, zt - h], np.r_[p + K.Fn * w / 2, zt - h]])
        for a, b in zip(rings, rings[1:]):
            for i in range(4):
                j = (i + 1) % 4
                out.append((np.array([a[i], a[j], b[j], b[i]]), tag))
        out.append((np.array(rings[0]), tag))
        out.append((np.array(rings[-1][::-1]), tag))
    beam(tail_lao, P["lao_end"], lambda l: K.zjl_top(l) - P["zjl_h"], P["jl_h"], P["jl_w"], "jl_lao")
    beam(tail_zai, -P["zai_out"], K.zjl_top, P["zjl_h"], P["jl_w"] * 0.9, "jl_zai")
    tx, ty, tz = P["ts_size"]
    ph = K.axis_pt(-P["zai_out"])
    zt = K.zjl_top(-P["zai_out"]) + 40
    out += box(ph - K.Fd * tx * 0.3, K.Fd, 0, tx, ty, zt, zt, tz, "ts")
    return out


def beam_lines(K, tail_lao, tail_zai, mirror_y):
    """角梁、套兽底棱（3D 折线）→ 最低可见边候选。mirror_y：另一角（y 镜像）也加。"""
    P, segs = K.P, []
    for (l0, l1, bot, w) in ((tail_lao, P["lao_end"], -P["zjl_h"] - P["jl_h"], P["jl_w"]), (tail_zai, -P["zai_out"], -P["zjl_h"], 0.9 * P["jl_w"])):
        ls = np.linspace(l0, l1, 50)
        for sg in (-1, 1):
            segs.append(np.array([[*(K.axis_pt(l) + K.Fn * sg * w / 2), K.zjl_top(l) + bot] for l in ls]))
    tx, ty, tz = P["ts_size"]
    ph = K.axis_pt(-P["zai_out"])
    zb = K.zjl_top(-P["zai_out"]) + 40 - tz
    for sg in (-1, 1):
        a = ph - K.Fd * tx * 0.3 + K.Fn * sg * ty / 2
        b = ph + K.Fd * tx * 0.7 + K.Fn * sg * ty / 2
        segs.append(np.array([[a[0], a[1], zb], [b[0], b[1], zb]]))
    if mirror_y:
        segs += [s * np.array([1, -1, 1]) for s in segs]
    return segs


def rafter_items(seq, K, x_from=None):
    """椽序列 → 实际放置的椽件 [(椽头, 方向, 起, 止, z 函数, 顶偏移, 宽, 高, 底偏移, 类 "fc"/"yc")]（翼角短椽按 *_min_frac 门槛，正身按 0.4）。"""
    P, d, off = K.P, K.d, K.offsets()
    ymin, fmin = P["yc_min_frac"] * d["yc_l"], P["fc_min_frac"] * d["fc_l"]
    out = []
    for r in seq:
        if x_from is not None and r["head"][0] < x_from:
            continue
        zf, h, dv = K.zf(r), r["head"], r["dir"]
        if r["fc"] >= (fmin if r["fan"] else 0.4 * d["fc_l"]):
            out.append((h, dv, d["fc_recess"], r["s_fc"], zf, d["raft_embed"], d["fc_w"], d["fc_h"], off["fc_bot"], "fc"))
        if r["vis"] >= (ymin if r["fan"] else 0.4 * d["yc_l"]):
            out.append((h, dv, d["yc_set"], r["s_yc"], zf, -d["fc_h"] + d["raft_embed"], 2 * d["yc_r"], 2 * d["yc_r"], off["yc_bot"], "yc"))
    return out


def rafter_polys(items):
    from preview import box
    out = []
    for (h, dv, s0, s1, zf, top, w, hh, _bot, *_k) in items:
        out += box(h, dv, s0, s1, w, zf(h + dv * s0) + top, zf(h + dv * s1) + top, hh, "wood")
    return out


def rafter_solids(items, seg=16):
    """成品级椽件：飞椽 = 方盒（tag "fc"），檐椽 = seg 段圆柱（tag "yc"，两端 n-gon 平面收口）。顶点数可 > 4，只给 Blender 用。"""
    from preview import box
    out = []
    for (h, dv, s0, s1, zf, top, w, hh, _bot, kind) in items:
        a2, b2 = h + dv * s0, h + dv * s1
        if kind == "fc":
            out += box(h, dv, s0, s1, w, zf(a2) + top, zf(b2) + top, hh, "fc")
            continue
        r = w / 2
        A = np.array([a2[0], a2[1], zf(a2) + top - r])
        B = np.array([b2[0], b2[1], zf(b2) + top - r])
        ax = (B - A) / np.linalg.norm(B - A)
        e1 = np.cross(ax, [0.0, 0.0, 1.0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(e1, ax)
        ang = np.linspace(0, 2 * math.pi, seg, endpoint=False)
        ring = np.cos(ang)[:, None] * e1 + np.sin(ang)[:, None] * e2
        RA, RB = A + r * ring, B + r * ring
        for i in range(seg):
            j = (i + 1) % seg
            out.append((np.array([RA[i], RB[i], RB[j], RA[j]]), "yc"))
        out.append((RA.copy(), "yc"))
        out.append((RB[::-1].copy(), "yc"))
    return out


def rafter_bottoms(items, mirror_y=True):
    segs = []
    for (h, dv, s0, s1, zf, _top, _w, _hh, bot, *_k) in items:
        a, b = h + dv * s0, h + dv * s1
        s = np.array([[a[0], a[1], zf(a) + bot], [b[0], b[1], zf(b) + bot]])
        segs.append(s)
        if mirror_y:
            segs.append(s * np.array([1, -1, 1]))
    return segs


def ridge_band(Hu, Hl, x_from, x_to, hw, embed, to3=None, lo_floor=None):
    """脊带（闭合实体：两侧面 + 顶 + 底 + 两端封口）。to3(x, z) → 3D 点（缺省 = 中轴 (x, 0, z)）；侧面沿 to3 后的局部法向展开 hw。"""
    from preview import strip
    up, lo = [], []
    for (xu, zu), (xl, zl) in zip(Hu, Hl):
        if xl < x_from or xl > x_to:
            continue
        zl2 = zl - embed if lo_floor is None else max(zl - embed, lo_floor(xl, zl))
        f = to3 or (lambda x, z: np.array([x, 0.0, z]))
        up.append(np.asarray(f(xu, zu), float))
        lo.append(np.asarray(f(xl, zl2), float))
    if len(up) < 2:
        return []
    t = up[-1][:2] - up[0][:2]
    t /= np.linalg.norm(t)
    n3 = np.r_[-t[1], t[0], 0.0] * hw
    out = []
    for sg in (-1, 1):
        out += strip([p + sg * n3 for p in up], [p + sg * n3 for p in lo], "ridge")
    out += strip([p - n3 for p in up], [p + n3 for p in up], "ridge")
    out += strip([p + n3 for p in lo], [p - n3 for p in lo], "ridge")                       # 底（埋进屋面）
    for k in (0, -1):                                                                         # 两端封口 → 闭合实体
        out.append((np.array([up[k] - n3, up[k] + n3, lo[k] + n3, lo[k] - n3]), "ridge"))
    return out


# ==================================================================== 刀锋族（E1 / B3）
class BladeCorner(CornerBase):
    """角在翼尖（中轴上），角梁轴 = +x。axis_beam=False：E1 原样（椽按 span_cap 截，不放角梁）。"""

    def __init__(self, body, dims, par):
        _need(par, BLADE_KEYS, "BladeCorner")
        self._base(body, dims, par)
        U = body["U"]
        self.Ux = np.array([u[0] for u in U])
        self.Uth = np.array([u[2] for u in U])
        self.xT, self.zT, self.thT = float(U[-1][0]), float(U[-1][1]), float(U[-1][2])
        self._set_frame((self.xT, 0.0), (1.0, 0.0))
        self.Fn = np.array([0.0, 1.0])
        self.F0f = self.T - self.Fn * par["jl_w"] / 2
        path = np.array([(xu, body["plan_y"](xe), zu) for (xu, zu, xe, ze, th) in body["stations"]])
        self.heads = self._heads(path)
        self.xw = None

    def sigma(self, p):
        return float(p[1])

    def zu(self, x):
        if x <= self.xT:
            return self.b["z_under"](x)
        return self.zT + math.tan(self.thT) * (x - self.xT)

    def th(self, x):
        return float(np.interp(x, self.Ux, self.Uth)) if x <= self.xT else self.thT

    def e1_items(self, x_from=None):
        """E1 原样的椽：头同序列，法向指向中轴，长度按 span_cap（离中轴 raft_min_y），不足 0.4 倍不放。"""
        d, off, out = self.d, self.offsets(), []
        zf = lambda q: self.b["z_under"](q[0])
        for (p, Nn) in self.heads:
            if x_from is not None and p[0] < x_from:
                continue
            cap = (abs(p[1]) - d["raft_min_y"]) / max(1e-6, abs(Nn[1]))
            h = p[:2]
            Lf = min(d["fc_l"], cap)
            if Lf >= 0.4 * d["fc_l"]:
                out.append((h, Nn, d["fc_recess"], d["fc_recess"] + Lf, zf, d["raft_embed"], d["fc_w"], d["fc_h"], off["fc_bot"], "fc"))
            Ly = min(d["yc_l"], cap - d["yc_set"])
            if Ly >= 0.4 * d["yc_l"]:
                out.append((h, Nn, d["yc_set"], d["yc_set"] + Ly, zf, -d["fc_h"] + d["raft_embed"], 2 * d["yc_r"], 2 * d["yc_r"], off["yc_bot"], "yc"))
        return out

    def tails(self):
        return self.xT - self.P["x_cut"], self.P["zjl_tail"]


def blade_shell(body, dims, x_from):
    """刀锋族壳体（右前象限）：连檐带、瓦面（举折截面到中轴）、檐底（平到中轴）。"""
    from preview import strip
    st = [s for s in body["stations"] if s[0] >= x_from - 200]
    N, f = dims["slope_n"], dims["section_f"]
    rings = []
    for (xu, zu, xe, ze, th) in st:
        ye = abs(body["plan_y"](xe))
        zt = body["z_top"](xe)
        pts = [(xu, -ye, zu), (xe, -ye, ze)] + [(xe, -ye * (1 - j / N), ze + (zt - ze) * f(j / N)) for j in range(1, N)] + [(xe, 0.0, zt)]
        rings.append([np.array(p, float) for p in pts])
    out = []
    for a, b in zip(rings, rings[1:]):
        out.append((np.array([a[0], a[1], b[1], b[0]]), "band"))
        out += strip(a[1:], b[1:], "slope")
        out.append((np.array([a[0], b[0], [b[0][0], 0, b[0][2]], [a[0][0], 0, a[0][2]]], float), "soffit"))
    return out


# ==================================================================== 真转角族（C1 / C2 / 中间档）
class TrueCorner(CornerBase):
    """矩形平面 45° 角梁。sag ∈ [0, 1]：山面檐高 = 抬平 + sag·(镜像 − 抬平)。cam（camkit.Pinhole）给定 → 前檐 / 戗脊沿视线对位。"""

    def __init__(self, body, dims, par, cam=None, plan_angle=90.0):
        _need(par, TRUE_KEYS, "TrueCorner")
        if abs(plan_angle - 90.0) > 1e-9:
            raise NotImplementedError("真转角暂只支持矩形平面 90° 角；非 90° 的山面坐标与檐底折线等第二个案例再定")
        self._base(body, dims, par)
        self.cam = cam
        P = par
        self.Dfull, self.Dc = float(body["eave_d"]), float(P["end_depth"])
        self.c = P["chong"] / SQ2
        self.w = P["side_blend"]
        self.sag = float(P["sag"])
        U = body["U"]
        self.E1 = np.array([(u[0], body["plan_y"](u[0]), u[1]) for u in U])
        self.E1th = np.array([u[2] for u in U])
        self.Zfix = None
        xT, xw, it = float(U[-1][0]), None, 0
        for it in range(12):
            self._setup(xT, xw)
            self._profile()
            xT_new = float(self.Ux[-1])
            self._setup(xT_new, xw)
            self._profile()
            self.xw = None
            xw_new = self._find_xw()
            done = xw is not None and abs(xT_new - xT) < 0.01 and abs(xw_new - xw) < 0.01
            xT, xw = xT_new, xw_new
            if done:
                break
        self._setup(xT, xw)
        self._profile()
        self.iters = it + 1
        self.dM = math.sin(self.thT) * self.Wb / (1.0 - self.sT)
        self.M = self.ext_station(self.dM)["P"]
        xx = np.linspace(self.xs, body["E_ext_x"], 200)
        hp = np.array([self.to_hip(x_, body["z_top"](x_)) for x_ in xx])
        self.hip_x, self.hip_z = hp[:, 0], hp[:, 2]
        self.heads = self._heads(self._u_path(self.Yf))
        if P["drain_min"] is not None:                     # 端坡排水下限：戗脊点不低于对应侧檐瓦口 + drain_min
            rows = sorted((self.xs - ss["yt"], ss["Q"][2] + P["drain_min"])
                          for ss in (self.side_station(float(xu)) for xu in np.linspace(self.xs, self.xT, 60)))
            self.Zfix = (np.array([r[0] for r in rows]), np.array([r[1] for r in rows]))

    # ---------------------------------------------------------------- 平面 / 前檐
    def _setup(self, xT, xw):
        self.xT = xT
        self.yT = -(self.Dc + self.c)
        self.xs = self.xT + self.yT
        self._set_frame((self.xT, self.yT), (1.0, -1.0))
        self.xw = xw
        self.sT = 2 * self.c / (self.xT - xw) if xw is not None else 0.0

    def mir(self, p):
        return self.fr.mir(p)

    def mir_dir(self, d):
        return self.fr.mir_dir(d)

    def Yf(self, x):
        xc = self.P["x_cut"]
        if x <= xc:
            return -self.Dfull
        if x < self.xs and self.Dc < self.Dfull:
            return -(self.Dfull + (self.Dc - self.Dfull) * smooth01((x - xc) / (self.xs - xc)))
        if self.xw is None or x <= self.xw:
            return -self.Dc
        if x <= self.xT:
            t = (x - self.xw) / (self.xT - self.xw)
            return -(self.Dc + self.c * t * t)
        return self.yT - self.sT * (x - self.xT)

    def _profile(self):
        """前檐下皮：有相机 → 本体各点沿视线滑到 y = Yf(x)；否则本体原样（C1 旧做法，翼尖不动）。"""
        if self.cam is None:
            self.Ux, self.Uz, self.Uth = self.E1[:, 0], self.E1[:, 2], self.E1th
            self.zT, self.thT = float(self.Uz[-1]), float(self.Uth[-1])
            return
        Q = np.array([self.cam.slide(p, lambda q: q[1] - self.Yf(q[0]), 0.8, 1.2) for p in self.E1])
        Q = Q[np.r_[True, np.diff(Q[:, 0]) > 1e-6]]
        self.Ux, self.Uz = Q[:, 0], Q[:, 2]
        self.Uth = np.arctan(np.gradient(self.Uz, self.Ux))
        self.zT, self.thT = float(self.Uz[-1]), float(np.mean(self.Uth[-4:]))

    def to_hip(self, x, z):
        """中轴点 (x, 0, z) → 45° 戗脊线 x + y = xs 上：有相机沿视线滑，否则同 x 平移。"""
        if self.cam is None:
            return np.array([x, self.xs - x, z])
        return self.cam.slide_to_plane((x, 0.0, z), (1.0, 1.0, 0.0), self.xs)

    def zu(self, x):
        if x <= self.xT:
            return float(np.interp(x, self.Ux, self.Uz))
        return self.zT + math.tan(self.thT) * (x - self.xT)

    def th(self, x):
        return float(np.interp(x, self.Ux, self.Uth)) if x <= self.xT else self.thT

    def _u_path(self, plan):
        st = self.P["station_stride"]
        xs_ = np.unique(np.r_[[s[0] for s in self.b["stations"] if s[0] <= self.P["x_cut"]], self.Ux[::st], self.xT])
        return np.array([(x, plan(x), self.zu(x)) for x in xs_ if x <= self.xT + 1e-6], float)

    def _find_xw(self):
        for (p, N) in self._heads(self._u_path(lambda x: -self.Dc if x > self.P["x_cut"] else -self.Dfull)):
            if p[0] > self.P["x_cut"] and self._gap(p[:2], N, self.F0f) <= self.need:
                return float(p[0])
        raise ValueError("正身椽够不到角梁")

    # ---------------------------------------------------------------- 山面檐 / 檐底 / 戗脊
    def q(self, u):
        return u if u >= self.w else (u * u + self.w * self.w) / (2 * self.w)

    def zus(self, y):
        """山面檐下皮高（y = 山面上的 y，≤ 0）：抬平 zu(Xs) 与镜像 zu(xs + q) 按 sag 插值。"""
        u = abs(y)
        lev = self.zu(self.xs - self.Yf(self.xs + u))
        if self.sag == 0.0:
            return lev
        return lev + self.sag * (self.zu(self.xs + self.q(u)) - lev)

    def ths(self, y):
        u, e = abs(y), 5.0
        nat = math.atan((self.zus(u + e) - self.zus(max(u - e, 0.0))) / (u + e - max(u - e, 0.0)))
        uT = abs(self.yT)
        wgt = max(0.0, 1.0 - (uT - u) / self.P["blend_tilt"]) ** 2 if u <= uT else 1.0
        natT = math.atan((self.zus(uT) - self.zus(uT - e)) / e)
        return nat + (self.thT - natT) * wgt

    def soffit_z(self, x, y):
        """檐底：sag = 0 一整片 z = zu(x)（C2）；sag = 1 前檐 / 山面两片取低者、交出折线（C1）；中间按 sag 插值。
        在山面檐线上两者都等于 zus(y)，檐底与檐带下皮咬合。"""
        z = self.zu(x)
        if self.sag == 0.0:
            return z
        u = abs(y)
        mir = self.zu(self.xs + self.q(u))
        return (1.0 - self.sag) * z + self.sag * min(z, mir)

    def side_at(self, p):
        return self.soffit_z(p[0], p[1])

    def crease(self, y):
        return self.xs + self.q(abs(y))

    def Zh(self, x):
        if x <= self.xs:
            z = self.b["z_top"](x)
        elif x <= self.hip_x[-1]:
            z = float(np.interp(x, self.hip_x, self.hip_z))
        else:
            z0 = self.hip_z[-1]
            z = z0 + (self.M[2] - z0) * (x - self.hip_x[-1]) / max(self.M[0] - self.hip_x[-1], 1e-6)
        if self.Zfix is not None and x >= self.xs:
            z = max(z, float(np.interp(x, *self.Zfix)))
        return z

    # ---------------------------------------------------------------- 站
    def station(self, xu, planar=False):
        zu, th, y = self.zu(xu), self.th(xu), self.Yf(xu)
        if planar:
            xe, ze = xu, self.b["z_eave"](xu)
        else:
            xe, ze = xu - math.sin(th) * self.Wb, zu + math.cos(th) * self.Wb
        return dict(xu=xu, th=th, U=np.array([xu, y, zu]), P=np.array([xe, y, ze]), xe=xe)

    def side_station(self, xu):
        """前檐站 xu（≥ xs）的镜像侧檐站：下皮 B、瓦口 Q（在山面竖直面内沿法向偏移）。"""
        yb = self.xs - xu
        xb = self.xs - self.Yf(xu)
        zb, ts = self.zus(yb), self.ths(yb)
        yt = yb + math.sin(ts) * self.Wb
        return dict(yb=yb, B=np.array([xb, yb, zb]), Q=np.array([xb, yt, zb + math.cos(ts) * self.Wb]), yt=yt)

    def ext_station(self, d):
        x, y = self.xT + d, self.yT - self.sT * d
        zb = self.zT + math.tan(self.thT) * d
        B = np.array([x, y, zb])
        P = np.array([x - math.sin(self.thT) * self.Wb, y, zb + math.cos(self.thT) * self.Wb])
        h = min(1.0, d / self.dM) if hasattr(self, "dM") else 0.0
        return dict(B=B, P=P, m=B + (P - B) * h, xe=P[0])

    def stations(self):
        xc = self.P["x_cut"]
        cand = sorted(set(float(x) for x in self.Ux[::self.P["station_stride"]] if xc < x < self.xT - 1e-6) | {self.xs, self.xT})
        out = [self.station(xc, planar=True)]
        for xu in cand:
            s = self.station(xu)
            if s["xe"] <= xc + 5.0 or (1e-9 < abs(xu - self.xs) < 5.0):
                continue
            out.append(s)
        return out

    def shell_grids(self):
        N, Ms, f = self.P["slope_n"], self.P["soffit_n"], self.d["section_f"]
        st, ext = self.stations(), [self.ext_station(self.dM * j / self.P["ext_n"]) for j in range(1, self.P["ext_n"] + 1)]
        fb, sb, fsl, ssl, fso, sso = [], [], [], [], [], []

        def col(start, top, n, zf=None):
            c = []
            for j in range(n + 1):
                t = j / n
                xy = start[:2] + (top[:2] - start[:2]) * t
                c.append(np.array([xy[0], xy[1], zf(xy) if zf else start[2] + (top[2] - start[2]) * f(t)]))
            return c
        soff = lambda xy: self.soffit_z(xy[0], xy[1])
        for s in st:
            U3, P3, xu = s["U"], s["P"], s["xu"]
            fb.append((U3, P3))
            if xu < self.xs - 1e-9:
                top, inner, ss = np.array([s["xe"], 0.0, self.Zh(s["xe"])]), np.array([xu, 0.0]), None
            else:
                ss = self.side_station(xu)
                xh = self.xs - ss["yt"]
                top, inner = np.array([xh, ss["yt"], self.Zh(xh)]), np.array([self.crease(ss["yb"]), ss["yb"]])
            c = col(P3, top, N)
            c[-1] = top
            fsl.append(c)
            so = col(U3, np.r_[inner, 0.0], Ms, soff)
            fso.append(so)
            if ss is not None:
                sb.append((ss["B"], ss["Q"]))
                r = col(ss["Q"], top, N)
                r[-1] = top
                ssl.append(r)
                rs = col(ss["B"], np.r_[inner, 0.0], Ms, soff)
                rs[-1] = so[-1]
                sso.append(rs)
        for e in ext:
            m, P3 = e["m"], e["P"]
            fb.append((m, P3))
            sb.append((m, self.mir(P3)))
            top = np.array([P3[0], self.xs - P3[0], self.Zh(P3[0])])
            for start, dst in ((P3, fsl), (self.mir(P3), ssl)):
                c = col(start, top, N)
                c[-1] = top
                dst.append(c)
        return dict(front_band=fb, side_band=sb, front_slope=fsl, side_slope=ssl, front_soffit=fso, side_soffit=sso,
                    n_main=len(st), n_ext=len(ext))

    def side_rafters(self, front):
        out = []
        for r in front:
            if r["head"][0] < self.xs:
                continue
            m = dict(r, head=self.mir(r["head"]), dir=self.mir_dir(r["dir"]), nrm=self.mir_dir(r["nrm"]), side="s")
            if r.get("tail") is not None:
                m["tail"] = self.mir(r["tail"])
            m["z3"] = np.array([m["head"][0], m["head"][1], self.side_at(m["head"])])
            out.append(m)
        return out

    def tails(self, seq, k0):
        """老角梁尾：首根扇椽尾内 add，至少 min_len，不超过轴长 − margin；仔角梁尾 zjl_tail。"""
        if self.P.get("jl_tail_fixed") is not None:          # 回归核对旧方案用（如旧 C1 固定 2800）
            return float(self.P["jl_tail_fixed"]), self.P["zjl_tail"]
        add, mn, margin = self.P["tail_auto"]
        lam0 = -float(seq[k0]["lam"])
        return min(max(lam0 + add, mn), abs(self.yT) * SQ2 - margin), self.P["zjl_tail"]

    def drainage(self, n=13):
        out = []
        for xu in np.linspace(self.xs, self.xT, n):
            ss = self.side_station(float(xu))
            out.append((round(ss["yb"]), round(self.Zh(self.xs - ss["yt"]) - ss["Q"][2])))
        return out


# ==================================================================== 组装：一个方案 → 多边形汤 + 残差线 + 数字
def build(body, dims, par, cam=None):
    """par["family"] = "blade" / "true"。返回 dict(K, polys（右半 + y 镜像）, cyan, lows, seq, k0, tails, checks, summary)。"""
    from preview import strip, grid, mirror
    xc = par["x_cut"]
    hw, emb = dims["ridge_bw"] / 2, dims["ridge_embed"]
    Hu, Hl = body["Hu"][1:], body["Hl"][1:]
    x_end = body["E_ext_x"]
    xs0 = np.arange(0.0, xc, 80.0)
    D = body["eave_d"]
    if par["family"] == "blade":
        K = BladeCorner(body, dims, par)
        polys = blade_shell(body, dims, xc) + ridge_band(Hu, Hl, xc, 1e9, hw, emb)
        xs = np.r_[np.arange(0.0, x_end, 40.0), x_end]
        cyan = np.c_[xs, [body["plan_y"](x) for x in xs], [body["z_eave"](x) for x in xs]]
        xu = np.r_[np.arange(0.0, body["U_ext"][0], 40.0), body["U_ext"][0]]
        fU = np.c_[xu, [body["plan_y"](x) for x in xu], [body["z_under"](x) for x in xu]]
        lows = [fU, fU * np.array([1, -1, 1])]
        if par["axis_beam"]:
            seq, k0 = K.front_rafters()
            K.xw = float(seq[k0]["head"][0])
            tl = K.tails()
            items = rafter_items(seq, K)
            polys += rafter_polys([it for it in items if it[0][0] >= xc]) + beam_polys(K, *tl)
            lows += rafter_bottoms(items) + beam_lines(K, *tl, mirror_y=False)
            chk = K.checks(seq, k0)
        else:
            seq, k0, tl, chk = None, None, None, None
            items = K.e1_items()
            polys += rafter_polys([it for it in items if it[0][0] >= xc])
            lows += rafter_bottoms(items)
        summ = dict(family="blade", axis_beam=bool(par["axis_beam"]), T=[round(K.xT, 1), 0.0, round(K.zT, 1)])
    else:
        K = TrueCorner(body, dims, par, cam=cam)
        sg = K.shell_grids()
        fb, sb = sg["front_band"], sg["side_band"]
        polys = strip([u for u, p in fb], [p for u, p in fb], "band") + strip([b for b, q in sb], [q for b, q in sb], "band")
        polys += grid(sg["front_slope"], "slope") + grid(sg["side_slope"], "slope")
        polys += grid(sg["front_soffit"], "soffit") + grid(sg["side_soffit"], "soffit")
        polys += ridge_band(Hu, Hl, xc, K.xs, hw, emb)
        polys += [(p, "hip") for p, _ in ridge_band(Hu, Hl, K.xs - 150, 1e9, hw, emb, to3=K.to_hip,
                                                   lo_floor=lambda xl, zl: K.Zh(K.to_hip(xl, zl)[0]) - 40)]
        seq, k0 = K.front_rafters()
        tl = K.tails(seq, k0)
        allr = seq + K.side_rafters(seq)
        items = rafter_items(allr, K)
        polys += beam_polys(K, *tl) + rafter_polys([it for it in items if it[0][0] >= xc])
        nm = sg["n_main"]
        cyan = np.r_[np.c_[xs0, [-D] * len(xs0), [body["z_eave"](x) for x in xs0]], np.array([p for u, p in fb])]
        fU = np.r_[np.c_[xs0, [-D] * len(xs0), [body["z_under"](x) for x in xs0]], np.array([u for u, p in fb[:nm]])]
        sU = np.array([b for b, q in sb[:len(sb) - sg["n_ext"]]])
        side = np.r_[sU[::-1] * np.array([1, -1, 1]), sU[1:]]
        lows = [fU, fU * np.array([1, -1, 1]), side] + rafter_bottoms(items) + beam_lines(K, *tl, mirror_y=True)
        chk = K.checks(seq, k0)
        dr = K.drainage()
        xx = np.linspace(K.xs + 1, K.hip_x[-1], 120)
        lift = max(K.Zh(x) - float(np.interp(x, K.hip_x, K.hip_z)) for x in xx)
        summ = dict(family="true", sag=K.sag, registered=cam is not None, iters=K.iters,
                    T=[round(K.xT, 1), round(K.yT, 1), round(K.zT, 1)], xs=round(K.xs, 1), xw=round(K.xw, 1),
                    thT_deg=round(math.degrees(K.thT), 1), side_mid_under=round(K.zus(0.0), 1), side_sag=round(K.zT - K.zus(0.0), 1),
                    M=[round(v, 1) for v in K.M], drain_min=min(d_ for _, d_ in dr), hip_lift_for_drainage=round(lift, 1),
                    n_front=len(seq), n_side=len(allr) - len(seq))
    polys = polys + [(p, "hip_b" if t == "hip" else t) for p, t in mirror(polys, 1)]   # 前 / 后戗脊分开成件
    return dict(K=K, polys=polys, items=items, cyan=cyan, lows=lows, seq=seq, k0=k0, tails=tl, checks=chk, summary=summ)


def selftest():
    """合成本体（直檐 + 二次起翘）上跑两族五档，查：构造单调 / 净距、sag 单调、镜像几何、Frame 一般角。"""
    import preview  # noqa: F401（beam / rafter 用到）
    fr = Frame.bisector((10.0, -3.0), 90.0)
    assert np.allclose(fr.mir((4.0, -1.0)), (7.0 - (-1.0), 7.0 - 4.0)), "90° 镜像应为 (xs − y, xs − x)"
    fr8 = Frame.bisector((0.0, 0.0), 135.0)
    assert np.allclose(fr8.mir(fr8.mir((3.0, 1.0))), (3.0, 1.0)) and abs(math.degrees(math.atan2(fr8.Fd[1], fr8.Fd[0])) + 67.5) < 1e-9
    half, z0 = 8400.0, 10500.0
    xs = np.linspace(0, half, 1051)
    z = z0 + 1800.0 * np.clip((xs - 4000.0) / (half - 4000.0), 0, 1) ** 2
    th = np.arctan(np.gradient(z, xs))
    U = [(float(a), float(b), float(c)) for a, b, c in zip(xs, z, th)]
    zu = lambda x: float(np.interp(abs(x), xs, z))
    zt = lambda x: zu(x) + 1500.0 - 0.0 * x
    dims = dict(band_w=280.0, raft_pitch=215.0, yc_set=280.0, yc_l=1100.0, yc_r=60.0, fc_h=100.0, fc_w=100.0, fc_l=720.0,
                fc_recess=12.0, raft_embed=6.0, raft_min_y=80.0, ridge_bw=380.0, ridge_embed=220.0, slope_n=12,
                section_f=lambda s: 0.6 * s + 0.4 * s * s)
    w = dims["band_w"]
    st = [(float(x), zu(x), float(x) - math.sin(t) * w, zu(x) + math.cos(t) * w, float(t)) for x, t in zip(xs[::20], th[::20])]
    body = dict(U=U, U_ext=(half + 200, zu(half) + 150), E_ext_x=half - 300, z_under=zu, z_eave=lambda x: zu(x) + w,
                z_top=zt, plan_y=lambda x: -2400.0 * (1 - 0.85 * np.clip((abs(x) - 5300) / 3100, 0, 1)), stations=st,
                Hu=[(float(x), zt(x) + 600) for x in xs[::30]], Hl=[(float(x), zt(x)) for x in xs[::30]], eave_d=2400.0, x_cut=5000.0)
    base = dict(jl_w=240.0, jl_h=360.0, zjl_h=240.0, ts_size=(260.0, 260.0, 320.0), fan_gamma=1.0, fan_alpha_last=14.0,
                clear_min=20.0, yc_min_frac=0.15, fc_min_frac=0.25, x_cut=5000.0, lao_end=1200.0, zai_out=250.0)
    tr = dict(base, family="true", chong=360.0, side_blend=700.0, slope_n=12, soffit_n=8, ext_n=6, end_depth=2400.0,
              blend_tilt=500.0, drain_min=60.0, zjl_tail=1400.0, tail_auto=(300.0, 2000.0, 150.0), station_stride=10)
    sags = []
    for sag in (1.0, 0.4, 0.0):
        R = build(body, dims, dict(tr, sag=sag))
        c, s = R["checks"], R["summary"]
        assert c["tail_monotone"] and c["yc_clear3d_min"] >= 0 and c["fc_clear3d_min"] >= 0, (sag, c)
        sags.append(s["side_sag"])
        K = R["K"]
        p = np.array([K.xT - 300.0, K.yT + 40.0])
        assert np.allclose(K.mir(K.mir(p)), p)
    assert sags[0] > sags[1] > sags[2], sags
    for beam in (False, True):
        R = build(body, dims, dict(base, family="blade", axis_beam=beam, zjl_tail=2600.0))
        assert len(R["polys"]) > 100
    print("roofkit selftest ok：Frame（90° / 135°）、真转角三档 sag 单调 %s、椽扇单调且净距 ≥ 门槛、刀锋族两档" % [round(v) for v in sags])


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest"):
        selftest()
    else:
        print(__doc__)
