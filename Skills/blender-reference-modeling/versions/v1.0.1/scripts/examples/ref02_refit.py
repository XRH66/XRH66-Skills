"""复现 case-xiuxian.md 阶段六的表：ref02 剪影下缘从"手取 14 点"到"去位姿 + 双拐点"的逐步改进。

注意：这条线后来证明是仰视下檐底深色带的下边（透视轮廓），不是檐口立面线。本脚本只演示拟合方法
（密集取点、去位姿、下限、残差、换对象族），它的骨架不能当檐下皮用。

    python examples/ref02_refit.py [--ref PATH] [--out DIR] [--project PRJ]

只读参考图，不改任何项目文件。--project 给出时额外量"原项目手取 14 点拟合"那一行（要能 import 项目的 concept_elevation）。
全部拟合用 Huber（δ = 1.5 px）做损失，报告几何距离 RMS。单位 px（ref02 1 px = 20 mm）。耗时约 5 分钟。
"""
import argparse
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import formkit as F
import ref_trace as RT
from PIL import Image, ImageDraw

AX, GY, MMPX, XS = 369.0, 786.0, 20.0, 180.0          # 中轴、地面（px），比例，斗拱带外缘（|x| < XS 被遮挡，不用）
DELTA = 1.5


def kspl(v, N, ds=2.0):
    """曲率样条：从 XS 起，κ 在 N+1 个等弧长节点间线性变。v = [z_start, θ0, 总长, κ0..κN(1e-3/px)]。"""
    segs = [(v[2] / N, v[3 + i] * 1e-3, v[4 + i] * 1e-3, "lin") for i in range(N)]
    return [(x, z) for (x, z, _, _) in F.kappa_curve(segs, XS, v[0], v[1], ds=ds)]


def knee1(v, ds=2.0):
    """A 段（线性 κ）→ 拐点（圆角 r、转角 Δθ）→ B 段（线性 κ）。10 参。"""
    zs, th0, La, ka0, ka1, r, dth, Lb, kb0, kb1 = v
    segs = [(La, ka0 * 1e-3, ka1 * 1e-3, "lin"), F.fillet_seg(r, dth), (Lb, kb0 * 1e-3, kb1 * 1e-3, "lin")]
    return [(x, z) for (x, z, _, _) in F.kappa_curve(segs, XS, zs, th0, ds=ds)]


def knee2(v, ds=2.0):
    """A → 拐点 1 → B → 拐点 2 → C（直），各段常曲率。11 参。"""
    zs, th0, La, ka, r1, d1, Lb, kb, r2, d2, Lc = v
    segs = [(La, ka * 1e-3, ka * 1e-3, "lin"), F.fillet_seg(r1, d1), (Lb, kb * 1e-3, kb * 1e-3, "lin"),
            F.fillet_seg(r2, d2), (Lc, 0.0, 0.0, "lin")]
    return [(x, z) for (x, z, _, _) in F.kappa_curve(segs, XS, zs, th0, ds=ds)]


def wing(v, ds=2.0):
    z0, half, xf, tip, ramp, rel, st = v
    return [(x, z) for (x, z, _, _) in F.wing_curve(z0, half, xf, math.radians(tip), ramp, rel, st, ds=ds)]


def fit(D, fn, x0, st, bd, seed, starts=8):
    f = F.fit_multistart(lambda v: F.huber(F.dist_to_polyline(D, fn(v)), DELTA), x0, st, bd, starts=starts, iters=600, seed=seed)
    c = fn(f["x"], ds=1.0)
    return dict(x=f["x"], at_bound=f["at_bound"], rms=F.rms_to_polyline(D, c), curve=c)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="参考图路径（原案例：牌楼项目 ref/ref02-stone-pailou-736x811.png，作者本机项目，不随 skill 发布）")
    ap.add_argument("--out", default=".")
    ap.add_argument("--project", default=None)
    o = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    img = Image.open(o.ref)
    tr = RT.trace(img, (40, 200, 700, 420), "bottom", clean=3, min_run=4, outlier=3.0, win=31)
    P0 = [(x - AX, GY - y) for (x, y) in tr["points"] if abs(x - AX) >= XS]
    R0, L0 = RT.unpose(P0)
    print("取点：右 %d 左 %d（|x| ≥ %d px），trace 丢弃 %d" % (len(R0), len(L0), XS, len(tr["dropped"])))
    sp = RT.sym_pose(P0)
    print("位姿：dx %.2f px  θ %.3f°  p %.2e；左右不对称 %.2f → %.2f px" % (sp["dx"], math.degrees(sp["th"]), sp["p"], sp["asym_before"], sp["asym_after"]))
    R1, L1 = RT.unpose(P0, sp["dx"], sp["th"], sp["p"])
    rows = []

    if o.project:
        sys.path[:0] = [os.path.join(o.project, "spec"), os.path.join(o.project, "build", "v2")]
        import concept_elevation as CE
        fr, _ = CE.fit_ref02()
        old = CE.eave_curve(fr[0], CE.REF_HALF, fr[1], fr[2] * 1e-4, fr[3], fr[4] * 1e-4)
        rows.append(("手取 14 点、eave_curve", 5, F.rms_to_polyline(R0 + L0, [(x / MMPX, z / MMPX) for (x, z, _, _) in old]), "", None))

    D0, D1 = R0 + L0, R1 + L1
    z0 = F.interp_x(R0, XS)
    z1 = F.interp_x(R1, XS)
    w = fit(D0, wing, [440, 315, 180, 25, 0.6, 0.2, 0.2], [3, 3, 15, 4, 0.1, 0.1, 0.1],
            [(400, 470), (280, 340), (60, 260), (3, 60), (0.2, 1.0), (0.02, 1.0), (0.0, 0.9)], seed=1)
    rows.append(("密集点 + wing_curve", 7, w["rms"], "撞边界 %s" % w["at_bound"], None))
    N = 6
    sb = lambda zs, kmin: [(zs - 30, zs + 30), (-0.6, 1.2), (80, 220)] + [(kmin, 60.0)] * (N + 1)
    k6 = lambda v, ds=2.0: kspl(v, N, ds)
    x0 = lambda zs: [zs, 0.15, 150.0] + [3.0] * (N + 1)
    st = [2.0, 0.05, 8.0] + [2.0] * (N + 1)
    fr_ = fit(D0, k6, x0(z0), st, sb(z0, -30.0), seed=2)
    flips = sum(1 for a, b in zip(fr_["x"][3:], fr_["x"][4:]) if a * b < 0)
    rows.append(("自由曲率样条 N=6", 10, fr_["rms"], "κ 节点变号 %d 次" % flips, None))
    fp = fit(D0, k6, x0(z0), st, sb(z0, 0.0), seed=5)
    rows.append(("κ ≥ 0 样条 N=6", 10, fp["rms"], "", None))
    fq = fit(D1, k6, x0(z1), st, sb(z1, 0.0), seed=5)
    rows.append(("去位姿 + κ ≥ 0 样条", 10, fq["rms"], "", fq))
    k1 = fit(D1, knee1, [z1, 0.1, 60, 0, 0, 4, 0.5, 90, 0, 0], [2, .05, 10, 1, 1, 2, .1, 10, 1, 1],
             [(z1 - 30, z1 + 30), (-.6, 1.0), (10, 160), (-15, 15), (-15, 15), (0.5, 40), (0.0, 1.3), (20, 200), (-15, 15), (-15, 15)], seed=7)
    rows.append(("去位姿 + 单拐点", 10, k1["rms"], "", k1))
    k2 = fit(D1, knee2, [z1, 0.1, 60, 0, 4, 0.5, 70, 0, 4, 0.1, 25], [2, .05, 10, 1, 2, .1, 10, 1, 2, .1, 6],
             [(z1 - 30, z1 + 30), (-.6, 1.0), (10, 160), (-15, 15), (0.5, 40), (0.0, 1.3), (10, 180), (-15, 15), (0.5, 40), (-0.8, 0.8), (2, 120)], seed=7)
    side = {n: F.rms_to_polyline(S, k2["curve"]) for n, S in (("R", R1), ("L", L1))}
    rows.append(("去位姿 + 双拐点", 11, k2["rms"], "右 %.2f 左 %.2f" % (side["R"], side["L"]), k2))
    floor = {}
    for n, S in (("R", R0), ("L", L0)):
        floor[n] = fit(S, k6, fr_["x"], st, sb(z0, -30.0), seed=3, starts=3)["rms"]
    rows.append(("单侧自由样条（下限）", 10, (floor["R"] + floor["L"]) / 2, "右 %.2f 左 %.2f" % (floor["R"], floor["L"]), None))

    print("\n%-22s %4s %9s %9s  %s" % ("做法", "参数", "RMS px", "RMS mm", "备注"))
    for name, n, r, note, _ in rows:
        print("%-22s %4d %9.2f %9.0f  %s" % (name, n, r, r * MMPX, note))
    zs, th0, La, ka, r1, d1, Lb, kb, r2, d2, Lc = k2["x"]
    q = F.kappa_curve([(La, ka * 1e-3, ka * 1e-3, "lin")], XS, zs, th0, ds=0.5)[-1]
    print("\n双拐点：A 段倾角 %.1f°，拐点 1 在 x %.0f mm、z %.0f mm，圆角 r %.0f mm，转 %.1f°；拐点 2 圆角 r %.0f mm，转 %.1f°"
          % (math.degrees(th0), q[0] * MMPX, q[1] * MMPX, r1 * MMPX, math.degrees(d1), r2 * MMPX, math.degrees(d2)))

    os.makedirs(o.out, exist_ok=True)
    # 有符号残差图：去位姿后 κ ≥ 0 样条 vs 双拐点，两侧叠画
    W, H = 900, 300
    sheet = Image.new("RGB", (W, 2 * H), (250, 250, 248))
    for k, (title, res) in enumerate((("pose + kappa>=0 spline", fq), ("pose + two knees", k2))):
        d = ImageDraw.Draw(sheet)
        y0 = k * H
        xs_hi = max(R1[-1][0], L1[-1][0])
        X = lambda x: 40 + (W - 60) * (x - XS) / (xs_hi - XS)
        Y = lambda r: y0 + H / 2 - r * 20
        for g in (-4, -2, 0, 2, 4):
            d.line([(40, Y(g)), (W - 20, Y(g))], fill=(170, 170, 170) if g == 0 else (228, 228, 228))
        for S, col in ((R1, (220, 70, 40)), (L1, (30, 90, 230))):
            sd = F.signed_dist(S, res["curve"])
            d.line([(X(x), Y(v)) for (x, _), v in zip(S, sd)], fill=col, width=2)
        d.text((44, y0 + 6), "%s   RMS %.2f px   signed residual vs x, red=R blue=L, grid 2 px" % (title, res["rms"]), fill=(40, 40, 40))
    sheet.save(os.path.join(o.out, "ref02_refit_residual.png"))
    # 叠图：两侧放大
    im = img.convert("RGB")
    d = ImageDraw.Draw(im)
    for res, col in ((fq, (30, 90, 230)), (k2, (240, 140, 0))):
        for sgn in (1, -1):
            pts = [RT.repose(x, z, sgn, sp["dx"], sp["th"], sp["p"]) for (x, z) in res["curve"]]
            d.line([(AX + u, GY - v) for (u, v) in pts], fill=col, width=1)
    for (u, v) in P0:
        d.point((AX + u, GY - v), fill=(0, 200, 60))
    a = im.crop((50, 220, 200, 395)).resize((450, 525), Image.NEAREST)
    b = im.crop((540, 220, 690, 395)).resize((450, 525), Image.NEAREST)
    ov = Image.new("RGB", (910, 525), (255, 255, 255))
    ov.paste(a, (0, 0))
    ov.paste(b, (460, 0))
    ov.save(os.path.join(o.out, "ref02_refit_overlay.png"))
    print("图：%s, %s（绿 = 取点，蓝 = κ ≥ 0 样条，橙 = 双拐点）" % ("ref02_refit_residual.png", "ref02_refit_overlay.png"))


if __name__ == "__main__":
    main()
