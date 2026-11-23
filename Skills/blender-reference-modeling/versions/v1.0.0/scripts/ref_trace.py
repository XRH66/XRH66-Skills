"""从参考图取特征线（自拟合的数据来源）。普通 Python（Pillow + numpy）。

    python ref_trace.py trace IMG --roi X0 Y0 X1 Y1 [--edge bottom|top] [--axis-x AX --ground-y GY --px-per-mm K]
                              [--clean 3] [--th 0.15] [--min-run 4] [--outlier 3] [--win 31] [--out pts.json] [--overlay ov.png]
    python ref_trace.py rectify IMG --src x1 y1 x2 y2 x3 y3 x4 y4 --size W H --out OUT.png
    python ref_trace.py register SHOT.png CANVAS.png [--scales 1.45 1.55 21] [--shift 12] [--ignore-red]
    python ref_trace.py sympose PTS.json --axis-x AX --ground-y GY [--min-abs-x XS] [--no-perspective]
    python ref_trace.py crop IMG --roi X0 Y0 X1 Y1 [--scale 3] [--grid 0] [--raw] --out OUT.png
    python ref_trace.py selftest

trace：在 ROI 内逐列从上往下找"第一段足够长的前景"，取它的下缘（edge=bottom，剪影下缘）或上缘（edge=top，如屋面上轮廓）。
  先认线：仰视图里剪影下缘可能是底面的透视轮廓，不是立面线（见 references/math-form.md 3.1 第 3 步）。
  - 掩膜：有 alpha 用 alpha；否则四角中位色当背景，色差 > th 为前景。
  - 清理：开运算去小斑点、闭运算补小缝（--clean 像素）；min-run 跳过比它短的前景段（细线、杂点）。
  - 亚像素：在原图的软前景值上，按阈值线性插值边缘位置。
  - 离群点：与滑动中位数（窗口 --win 列，默认 31）差 > outlier 像素的点丢掉（挂件、遮挡），丢了多少会报告。
    比半个窗口还宽的遮挡这里去不掉，要在拟合阶段用稳健损失（截尾 / Huber）处理。
  - 给了 axis-x / ground-y / px-per-mm 就输出毫米坐标（x 相对中轴，z 向上）。
crop：切参考局部放大图（识别证据、逐件对照用）。--scale 放大倍数（最近邻 / LANCZOS 自动选），--grid N 每 N 原像素画一条刻度线便于读尺寸；
      原图坐标写在图片上方另加的标签条里（不盖住内容），事后能对回原图。
      --raw：原分辨率原样切出、不加标签和刻度——从拼图参考里切子视图（views.region）给掩膜 / IoU / 相机拟合用。
rectify：四点单应矫正透视（src 四角 → 输出矩形，顺序左上、右上、右下、左下）。
register：把截图（用户画线的那张）配准回原画布：搜索缩放 × 平移，使非标注像素的灰度差最小。
sympose：对称物体的拍摄位姿（中轴偏移 dx、倾角 θ、水平透视 p），只用"左右镜像最吻合"，不需要形体模型。
  PTS.json 是 trace --out 的输出；只用 |x − AX| ≥ min-abs-x 的点（中段被斗拱、匾额挡住时用）。
  报告去位姿前后的左右不对称 RMS——后者才是对称模型精度的下限。拟合时先 unpose 再拟合，叠图时 repose 回去。
"""
import argparse
import json
import math
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


# ---------------------------------------------------------------- 掩膜
def soft_fg(img, th=0.15):
    """返回 (软前景值 0..∞（>1 即前景）, 来源)。alpha 图用 alpha/0.5；否则色差/th。"""
    if img.mode in ("RGBA", "LA"):
        a = np.asarray(img.convert("RGBA"), dtype=np.float32)[..., 3] / 255.0
        if a.min() < 0.5 < a.max():
            return a / 0.5, "alpha"
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    h, w, _ = rgb.shape
    k = max(2, min(h, w) // 50)
    corners = np.concatenate([rgb[:k, :k].reshape(-1, 3), rgb[:k, -k:].reshape(-1, 3),
                              rgb[-k:, :k].reshape(-1, 3), rgb[-k:, -k:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    return np.linalg.norm(rgb - bg, axis=2) / th, "bg_color"


def clean_mask(m, k):
    """开运算（去小斑点）+ 闭运算（补小缝），k 为奇数像素。"""
    if k < 2:
        return m
    k = k | 1
    im = Image.fromarray((m * 255).astype(np.uint8))
    im = im.filter(ImageFilter.MinFilter(k)).filter(ImageFilter.MaxFilter(k))     # open
    im = im.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))     # close
    return np.asarray(im) > 127


# ---------------------------------------------------------------- 取边
def trace(img, roi, edge="bottom", th=0.15, clean=3, min_run=4, outlier=3.0, win=31):
    """返回 dict(points=[(x_px, y_px)], dropped=[…], mask_source)。坐标 = 像素中心为 .5 的连续坐标。"""
    v, src = soft_fg(img, th)
    m = clean_mask(v > 1.0, clean)
    x0, y0, x1, y1 = roi
    pts = []
    for x in range(max(0, x0), min(m.shape[1], x1)):
        col = m[y0:y1, x]
        idx = np.flatnonzero(col)
        if len(idx) == 0:
            continue
        # 第一段长度 ≥ min_run 的前景
        starts = [idx[0]] + [idx[i] for i in range(1, len(idx)) if idx[i] != idx[i - 1] + 1]
        ends = [idx[i] for i in range(len(idx) - 1) if idx[i + 1] != idx[i] + 1] + [idx[-1]]
        run = next(((a, b) for a, b in zip(starts, ends) if b - a + 1 >= min_run), None)
        if run is None:
            continue
        a, b = run[0] + y0, run[1] + y0
        vc = v[:, x]
        if edge == "bottom":            # 前景 b → 背景 b+1，在原图软值上找穿越 1.0 的位置
            y = _cross(vc, b, +1)
        else:
            y = _cross(vc, a, -1)
        pts.append((x + 0.5, y))
    keep, dropped = _drop_outliers(pts, outlier, win)
    return dict(points=keep, dropped=dropped, mask_source=src)


def _cross(vc, i, step):
    """从前景边界像素 i 沿 step 方向，找软值穿越"内部前景水平的 50%"的亚像素位置。
    用 50% 而不是固定阈值：固定阈值会把边缘系统性地推向背景一侧（实测约 0.4 px）。"""
    n = len(vc)
    inner = [vc[k] for k in range(i - 3 * step, i + step, step) if 0 <= k < n]
    T = 0.5 * float(np.median(inner)) if inner else 1.0
    j = i
    for _ in range(3):                                     # 清理后的掩膜可能比原图多出一点：先往里退到 T 以上
        if vc[j] >= T or not (0 <= j - step < n):
            break
        j -= step
    for _ in range(3):                                     # 再往外走到最后一个 ≥ T 的像素
        if 0 <= j + step < n and vc[j + step] >= T:
            j += step
        else:
            break
    if not (0 <= j + step < n) or vc[j] < T:
        return i + 0.5 + 0.5 * step
    t = (vc[j] - T) / max(1e-6, vc[j] - vc[j + step])
    return (j + 0.5) + step * t


def _drop_outliers(pts, tol, win=31):
    if not pts or tol <= 0:
        return pts, []
    ys = np.array([p[1] for p in pts])
    keep, dropped = [], []
    for i, p in enumerate(pts):
        half = min(win // 2, i, len(pts) - 1 - i)           # 窗口关于本点对称：斜坡上中位数 = 本点，端部不误杀
        lo, hi = i - half, i + half + 1
        (keep if abs(p[1] - np.median(ys[lo:hi])) <= tol else dropped).append(p)
    return keep, dropped


def to_mm(pts, axis_x, ground_y, px_per_mm):
    """像素 → 立面毫米（x 相对中轴，z 从地面向上）。"""
    return [((x - axis_x) / px_per_mm, (ground_y - y) / px_per_mm) for (x, y) in pts]


# ---------------------------------------------------------------- 对称位姿（无模型）
def unpose(pts, dx=0.0, th=0.0, p=0.0):
    """去位姿：u → u/(1+p·u)（水平透视，相机偏一侧）→ 减 dx（中轴偏移）→ 绕原点转 -θ（倾斜）。
    pts 为相对"估计中轴 / 地面"的 (u, v)，v 向上。返回 (右半, 左半折到右边)，各按 x 排序。"""
    c, s = math.cos(th), math.sin(th)
    R, L = [], []
    for u, v in pts:
        u = u / (1.0 + p * u) - dx
        u2, v2 = c * u + s * v, -s * u + c * v
        (R if u2 > 0 else L).append((abs(u2), v2))
    return sorted(R), sorted(L)


def repose(x, z, side, dx=0.0, th=0.0, p=0.0):
    """unpose 的逆：对称模型上的点（side=+1 右 / -1 左）→ 参考图的 (u, v)。叠图用。"""
    c, s = math.cos(th), math.sin(th)
    u2 = side * x
    u, v = c * u2 - s * z + dx, s * u2 + c * z
    return u / (1.0 - p * u), v


def _asym(R, L):
    from formkit import rms_to_polyline
    lo, hi = max(R[0][0], L[0][0]), min(R[-1][0], L[-1][0])
    a = [q for q in L if lo <= q[0] <= hi]
    b = [q for q in R if lo <= q[0] <= hi]
    if len(a) < 5 or len(b) < 5:
        return 1e9
    return math.sqrt(0.5 * (rms_to_polyline(a, R) ** 2 + rms_to_polyline(b, L) ** 2))


def sym_pose(pts, perspective=True, seed=0):
    """对称物体的拍摄位姿，不需要任何形体模型：找 dx、θ、p 使右半与左半镜像后几何距离最小。
    返回 dict(dx, th, p, asym_before, asym_after)。asym_after 才是"对称模型能达到的精度下限"的依据；
    去掉的那部分是拍摄造成的，不该让形体参数去吸收（否则曲线会被扭歪来迁就倾斜）。
    p 只是一阶近似；透视强时先用 rectify 做四点矫正。"""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from formkit import fit_multistart
    before = _asym(*unpose(pts))
    f2 = fit_multistart(lambda v: _asym(*unpose(pts, v[0], v[1] * 1e-3, 0.0)) ** 2,
                        [0.0, 0.0], [2.0, 3.0], [(-30, 30), (-60, 60)], starts=6, seed=seed, iters=300)
    dx, th, p, f = f2["x"][0], f2["x"][1] * 1e-3, 0.0, f2["f"]
    if perspective:
        f3 = fit_multistart(lambda v: _asym(*unpose(pts, v[0], v[1] * 1e-3, v[2] * 1e-5)) ** 2,
                            [dx, th * 1e3, 0.0], [2.0, 3.0, 5.0], [(-30, 30), (-60, 60), (-100, 100)], starts=6, seed=seed + 1, iters=400)
        if f3["f"] < f:
            dx, th, p, f = f3["x"][0], f3["x"][1] * 1e-3, f3["x"][2] * 1e-5, f3["f"]
    return dict(dx=dx, th=th, p=p, asym_before=before, asym_after=math.sqrt(f))


# ---------------------------------------------------------------- 透视矫正
def homography(src, dst):
    """4 点 DLT：src → dst 的 3×3 单应矩阵。"""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    h = np.linalg.solve(np.array(A, float), np.array(b, float))
    return np.append(h, 1.0).reshape(3, 3)


def apply_h(H, pts):
    out = []
    for (x, y) in pts:
        p = H @ np.array([x, y, 1.0])
        out.append((p[0] / p[2], p[1] / p[2]))
    return out


def rectify(img, src_quad, size):
    """src_quad（左上、右上、右下、左下）→ 输出 size 矩形。PIL 的 PERSPECTIVE 要"输出 → 输入"的系数。"""
    w, h = size
    dst = [(0, 0), (w, 0), (w, h), (0, h)]
    Hinv = homography(dst, src_quad)
    return img.transform(size, Image.PERSPECTIVE, tuple((Hinv.flatten() / Hinv[2, 2])[:8]), Image.BICUBIC)


# ---------------------------------------------------------------- 配准
def register(shot, canvas, scales, shift, ignore=None):
    """截图 shot 按 1/s 缩放后放到 canvas 上，搜索 s 与整数平移 (dx, dy) ∈ [-shift, shift]²，
    使重叠区灰度平均绝对差最小。ignore(shot_rgb_array) → 布尔掩膜（如红色标注）不参与比较。返回 dict。"""
    cv = np.asarray(canvas.convert("L"), dtype=np.float32)
    best = None
    for s in scales:
        sw, sh = int(round(shot.width / s)), int(round(shot.height / s))
        sm = shot.convert("RGB").resize((sw, sh), Image.BILINEAR)
        g = np.asarray(sm.convert("L"), dtype=np.float32)
        valid = ~ignore(np.asarray(sm)) if ignore else np.ones_like(g, bool)
        for dy in range(-shift, shift + 1):
            for dx in range(-shift, shift + 1):
                # shot 像素 (u, v) → canvas (u + dx, v + dy)
                cx0, cy0 = max(0, dx), max(0, dy)
                cx1, cy1 = min(cv.shape[1], sw + dx), min(cv.shape[0], sh + dy)
                if cx1 - cx0 < 20 or cy1 - cy0 < 20:
                    continue
                a = g[cy0 - dy:cy1 - dy, cx0 - dx:cx1 - dx]
                b = cv[cy0:cy1, cx0:cx1]
                vm = valid[cy0 - dy:cy1 - dy, cx0 - dx:cx1 - dx]
                err = float(np.abs(a - b)[vm].mean())
                if best is None or err < best["err"]:
                    best = dict(scale=s, dx=dx, dy=dy, err=err)
    return best


def crop(img, roi, scale=3.0, grid=0, raw=False):
    x0, y0, x1, y1 = roi
    if raw:
        return img.crop((x0, y0, x1, y1))
    c = img.convert("RGB").crop((x0, y0, x1, y1))
    w, h = c.size
    rs = Image.NEAREST if scale >= 4 else Image.LANCZOS
    c = c.resize((max(1, int(w * scale)), max(1, int(h * scale))), rs)
    from PIL import ImageDraw
    d = ImageDraw.Draw(c)
    if grid:
        for gx in range(0, w, grid):
            d.line([(gx * scale, 0), (gx * scale, c.size[1])], fill=(255, 0, 255), width=1)
        for gy in range(0, h, grid):
            d.line([(0, gy * scale), (c.size[0], gy * scale)], fill=(255, 0, 255), width=1)
    out = Image.new("RGB", (max(c.size[0], 160), c.size[1] + 16), (0, 0, 0))
    out.paste(c, (0, 16))
    ImageDraw.Draw(out).text((3, 2), "roi %d,%d,%d,%d x%g" % (x0, y0, x1, y1, scale), fill=(255, 255, 255))
    return out


def red_marks(rgb):
    return (rgb[..., 0] > 200) & (rgb[..., 1] < 120) & (rgb[..., 2] < 120)


# ---------------------------------------------------------------- 叠图
def overlay(img, pts, out, curves=(), dropped=()):
    """原图 + 取到的点（绿）+ 丢掉的点（红）+ 拟合曲线（蓝，像素坐标）。"""
    im = img.convert("RGB").copy()
    d = ImageDraw.Draw(im)
    for c in curves:
        d.line([tuple(p) for p in c], fill=(30, 90, 230), width=1)
    for (x, y) in pts:
        d.point((x, y), fill=(0, 200, 60))
    for (x, y) in dropped:
        d.ellipse((x - 1.5, y - 1.5, x + 1.5, y + 1.5), outline=(230, 30, 30))
    im.save(out)


# ---------------------------------------------------------------- 自检
def selftest():
    """合成参考：已知曲线（抗锯齿）+ 杂点 + 挂件遮挡 → trace → 与真值比；单应往返；配准还原。"""
    ok_all = True
    W, H, SS = 600, 300, 4
    big = Image.new("RGB", (W * SS, H * SS), (236, 232, 224))
    d = ImageDraw.Draw(big)
    f = lambda x: 120 + 60 * ((x - 300) / 300.0) ** 4 * (-1) + 25 * math.sin(x / 70.0)   # 真值下缘（像素）
    poly = [(0, 40 * SS), (W * SS, 40 * SS)] + [(x * SS, f(x) * SS) for x in range(W, -1, -1)]   # 连续坐标 X 处高 f(X)
    d.polygon(poly, fill=(70, 74, 72))
    for x in range(150, 160):                                   # 挂件：向下突出的小块（应被判为离群点）
        d.rectangle(((x * SS), 100 * SS, (x + 1) * SS, 160 * SS), fill=(70, 74, 72))
    img = big.resize((W, H), Image.LANCZOS)
    dd = ImageDraw.Draw(img)
    rnd = np.random.default_rng(0)
    for _ in range(80):                                         # 杂点
        x, y = rnd.integers(0, W), rnd.integers(200, H)
        dd.point((int(x), int(y)), fill=(60, 60, 60))
    r = trace(img, (0, 30, W, H), "bottom", clean=3, min_run=4, outlier=3)
    errs = [abs(y - f(x)) for (x, y) in r["points"]]
    e_rms = math.sqrt(sum(e * e for e in errs) / len(errs))
    ok = e_rms < 0.25 and len(r["points"]) > 0.9 * W and len(r["dropped"]) >= 6
    ok_all &= ok
    print("%-4s trace 亚像素     %d 点，RMS %.3f px，最大 %.3f px；丢弃离群 %d 点（挂件 10 列）" %
          ("ok" if ok else "FAIL", len(r["points"]), e_rms, max(errs), len(r["dropped"])))
    src = [(37, 21), (512, 44), (560, 280), (12, 250)]
    Hm = homography(src, [(0, 0), (500, 0), (500, 300), (0, 300)])
    back = apply_h(np.linalg.inv(Hm), apply_h(Hm, src))
    e = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(src, back))
    ok = e < 1e-6
    ok_all &= ok
    print("%-4s homography 往返  最大误差 %.1e px" % ("ok" if ok else "FAIL", e))
    shot = img.resize((int(W * 1.5), int(H * 1.5)), Image.BILINEAR)
    canvas = Image.new("RGB", (W, H), (236, 232, 224))
    canvas.paste(img.crop((0, 0, W - 4, H - 6)), (4, 6))         # 原画布相对截图平移 (+4, +6)
    sd = ImageDraw.Draw(shot)
    sd.line([(100, 50), (500, 200)], fill=(255, 0, 0), width=5)   # 用户画线
    rg = register(shot, canvas, [1.46 + 0.01 * i for i in range(9)], 8, ignore=red_marks)
    ok = abs(rg["scale"] - 1.5) < 0.006 and (rg["dx"], rg["dy"]) == (4, 6)
    ok_all &= ok
    print("%-4s register         scale %.3f  dx %d  dy %d  err %.2f" % ("ok" if ok else "FAIL", rg["scale"], rg["dx"], rg["dy"], rg["err"]))
    # 对称位姿：对称的"平—拐—翘"轮廓，加已知位姿（dx 6、θ -0.6°、p -1.5e-4）与 0.3 px 噪声，看能否还原
    g = lambda x: 300 + 0.12 * x + (0.0 if x < 230 else 0.9 * (x - 230) + 0.004 * (x - 230) ** 2)
    rnd = np.random.default_rng(1)
    true = dict(dx=6.0, th=math.radians(-0.6), p=-1.5e-4)
    pts = []
    for x in np.arange(180.0, 330.0, 1.0):
        for side in (1, -1):
            u, v = repose(float(x), g(float(x)), side, **true)
            pts.append((u, v + rnd.normal(0, 0.3)))
    sp = sym_pose(pts)
    ok = abs(sp["dx"] - 6.0) < 0.6 and abs(math.degrees(sp["th"]) + 0.6) < 0.05 and abs(sp["p"] + 1.5e-4) < 3e-5 and sp["asym_after"] < 0.5
    ok_all &= ok
    print("%-4s sym_pose         dx %.2f(6)  θ %.3f°(-0.6)  p %.2e(-1.5e-4)  不对称 %.2f → %.2f px" %
          ("ok" if ok else "FAIL", sp["dx"], math.degrees(sp["th"]), sp["p"], sp["asym_before"], sp["asym_after"]))
    print("REF_TRACE_SELFTEST", "pass" if ok_all else "fail")
    return ok_all


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if argv[:1] == ["selftest"]:
        return 0 if selftest() else 1
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd")
    t = sp.add_parser("trace")
    t.add_argument("img")
    t.add_argument("--roi", type=int, nargs=4, required=True)
    t.add_argument("--edge", choices=("bottom", "top"), default="bottom")
    t.add_argument("--th", type=float, default=0.15)
    t.add_argument("--clean", type=int, default=3)
    t.add_argument("--min-run", type=int, default=4)
    t.add_argument("--outlier", type=float, default=3.0)
    t.add_argument("--win", type=int, default=31)
    t.add_argument("--axis-x", type=float)
    t.add_argument("--ground-y", type=float)
    t.add_argument("--px-per-mm", type=float)
    t.add_argument("--out")
    t.add_argument("--overlay")
    r = sp.add_parser("rectify")
    r.add_argument("img")
    r.add_argument("--src", type=float, nargs=8, required=True)
    r.add_argument("--size", type=int, nargs=2, required=True)
    r.add_argument("--out", required=True)
    g = sp.add_parser("register")
    g.add_argument("shot")
    g.add_argument("canvas")
    g.add_argument("--scales", type=float, nargs=3, default=(1.45, 1.55, 21))
    g.add_argument("--shift", type=int, default=12)
    g.add_argument("--ignore-red", action="store_true")
    q = sp.add_parser("sympose")
    q.add_argument("pts")
    q.add_argument("--axis-x", type=float, required=True)
    q.add_argument("--ground-y", type=float, required=True)
    q.add_argument("--min-abs-x", type=float, default=0.0)
    q.add_argument("--no-perspective", action="store_true")
    c = sp.add_parser("crop")
    c.add_argument("img")
    c.add_argument("--roi", type=int, nargs=4, required=True)
    c.add_argument("--scale", type=float, default=3.0)
    c.add_argument("--grid", type=int, default=0)
    c.add_argument("--raw", action="store_true")
    c.add_argument("--out", required=True)
    o = p.parse_args(argv)
    if o.cmd == "trace":
        img = Image.open(o.img)
        res = trace(img, o.roi, o.edge, o.th, o.clean, o.min_run, o.outlier, o.win)
        if o.px_per_mm and o.axis_x is not None and o.ground_y is not None:
            res["points_mm"] = to_mm(res["points"], o.axis_x, o.ground_y, o.px_per_mm)
        if o.overlay:
            overlay(img, res["points"], o.overlay, dropped=res["dropped"])
        if o.out:
            json.dump(res, open(o.out, "w", encoding="utf-8"), ensure_ascii=False)
        print(json.dumps(dict(n=len(res["points"]), dropped=len(res["dropped"]), mask_source=res["mask_source"])))
    elif o.cmd == "crop":
        crop(Image.open(o.img), o.roi, o.scale, o.grid, o.raw).save(o.out)
        print("CROPPED", o.out)
    elif o.cmd == "rectify":
        q = o.src
        rectify(Image.open(o.img), [(q[0], q[1]), (q[2], q[3]), (q[4], q[5]), (q[6], q[7])], tuple(o.size)).save(o.out)
        print("RECTIFIED", o.out)
    elif o.cmd == "register":
        a, b, n = o.scales
        sc = [a + (b - a) * i / max(1, int(n) - 1) for i in range(int(n))]
        print(json.dumps(register(Image.open(o.shot), Image.open(o.canvas), sc, o.shift, red_marks if o.ignore_red else None)))
    elif o.cmd == "sympose":
        raw = json.load(open(o.pts, encoding="utf-8"))["points"]
        uv = [(x - o.axis_x, o.ground_y - y) for (x, y) in raw if abs(x - o.axis_x) >= o.min_abs_x]
        r = sym_pose(uv, perspective=not o.no_perspective)
        r["th_deg"] = math.degrees(r["th"])
        print(json.dumps(r))
    else:
        p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
