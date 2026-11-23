# -*- coding: utf-8 -*-
"""
preview：不开 Blender 的多方案平涂预览（软件 z-buffer）。numpy + Pillow。
用途：结构方案还没定时，几秒钟出"同视角 × 多方案"的图（正交立面 / 平面 / 3/4 透视 / 参考机位），给人挑形，不是成品渲染。[实测]

几何格式（全 skill 通用）：多边形汤 polys = [(pts(k, 3), tag), …]，以四边形为主、收口可为平面凸 n-gon，tag 是构件类（字符串）。
  strip / grid / box / mirror 生成；roofkit 等几何模块直接产出这种格式；Blender 侧可按 tag 成对象。
投影：proj(pts) → (uv(n, 2), depth(n,))；ortho(…) / persp(…) / from_camkit(cam)。
  xform(u, v) → 像素 (x, y)：把投影坐标放进画布（缩放 + 平移 + v 翻转由调用者定）。
轮廓：材质类变化或深度跳变处压暗 → 平涂图也能看清构件边。
"""
import numpy as np
from PIL import Image, ImageFilter, ImageDraw

LIGHT = np.array([-0.35, -0.55, 0.76]) / np.linalg.norm([-0.35, -0.55, 0.76])
PALETTE = dict(band=(150, 140, 120), slope=(95, 100, 100), soffit=(120, 105, 85), ridge=(170, 165, 155), hip=(170, 165, 155), hip_b=(170, 165, 155), fc=(140, 100, 60), yc=(130, 92, 55),
               wood=(140, 100, 60), jl=(110, 70, 35), jl_lao=(110, 70, 35), jl_zai=(120, 78, 40), ts=(96, 92, 86), stone=(160, 158, 150), other=(128, 128, 128))


# ---------------------------------------------------------------- 几何原语
def strip(A, B, tag):
    return [(np.array([A[i], A[i + 1], B[i + 1], B[i]], float), tag) for i in range(len(A) - 1)]


def grid(cols, tag):
    out = []
    for a, b in zip(cols, cols[1:]):
        out += strip(a, b, tag)
    return out


def box(a, d, s0, s1, w, ztop0, ztop1, h, tag):
    """平面方向 d 上的长盒：a + d·s0（顶 ztop0）到 a + d·s1（顶 ztop1），宽 w，高 h（向下）。6 个四边形，法线朝外。"""
    a, d = np.asarray(a, float)[:2], np.asarray(d, float)[:2]
    n = np.array([-d[1], d[0]])
    c = []
    for (p, zt) in ((a + d * s0, ztop0), (a + d * s1, ztop1)):
        for (sg, dz) in ((1, 0), (-1, 0), (-1, -h), (1, -h)):
            q = p + n * sg * w / 2
            c.append((q[0], q[1], zt + dz))
    c = np.array(c)
    faces = [(3, 2, 1, 0), (5, 6, 7, 4), (1, 5, 4, 0), (2, 6, 5, 1), (3, 7, 6, 2), (0, 4, 7, 3)]
    return [(c[list(f)], tag) for f in faces]


def mirror(polys, axis=1):
    """对 axis（0 = x，1 = y）镜像；顶点顺序反转以保持法线朝外。"""
    s = np.ones(3)
    s[axis] = -1
    return [(p[::-1] * s, t) for (p, t) in polys]


# ---------------------------------------------------------------- 投影
def ortho(u_axis=0, v_axis=2, depth_axis=1, depth_sign=1.0):
    """正交：u、v 取两根坐标轴，depth 取第三根（depth_sign = −1 表示从该轴正向往负向看）。"""
    def f(pts):
        return pts[:, [u_axis, v_axis]], depth_sign * pts[:, depth_axis]
    return f


def persp(eye, target, lens=40.0, sensor=36.0, W=900, up=(0.0, 0.0, 1.0)):
    eye, tgt = np.asarray(eye, float), np.asarray(target, float)
    fwd = (tgt - eye) / np.linalg.norm(tgt - eye)
    rt = np.cross(fwd, up)
    rt /= np.linalg.norm(rt)
    upv = np.cross(rt, fwd)
    fpx = lens / sensor * W

    def f(pts):
        v = pts - eye
        dep = v @ fwd
        return np.stack([fpx * (v @ rt) / dep, fpx * (v @ upv) / dep], 1), dep
    return f


def from_camkit(cam):
    """camkit.Pinhole → proj（uv 的 v 向上）。"""
    return lambda pts: cam.project(pts)


# ---------------------------------------------------------------- 光栅
def zrender(polys, proj, xform, W, H, persp=True, ss=2, bg=(238, 242, 246), palette=None, light=LIGHT,
            djump=150.0, rel_jump=0.012, edge_dark=0.45):
    """z-buffer 平涂。persp=True 时深度按 1/z 插值、深度跳变按相对量判；正交时按绝对量 djump（mm）。返回 PIL.Image。"""
    pal = dict(PALETTE, **(palette or {}))
    tags = {t: i for i, t in enumerate(pal)}
    Wp, Hp = W * ss, H * ss
    Z = np.full((Hp, Wp), np.inf)
    IMG = np.empty((Hp, Wp, 3))
    IMG[:] = bg
    MID = np.full((Hp, Wp), -1, np.int32)
    for pts, tag in polys:
        q, dep = proj(pts)
        if not np.all(np.isfinite(q)) or (persp and np.any(dep <= 1.0)):
            continue
        sx = np.array([xform(a, b) for a, b in q], float) * ss
        P = np.asarray(pts, float)
        n = np.cross(P - P.mean(0), np.roll(P, -1, 0) - P.mean(0)).sum(0)     # Newell 法向：三角、四边、n-gon 通用
        nn = np.linalg.norm(n)
        k = 0.38 + 0.62 * abs(float(np.dot(n / nn, light))) if nn > 1e-9 else 0.5
        col = pal.get(tag, tag if isinstance(tag, tuple) else pal["other"])
        cc = np.array(col, float) * k
        cid = tags.get(tag, len(tags))
        for tri in [(0, i, i + 1) for i in range(1, len(P) - 1)]:                # 扇形三角化（凸多边形）
            v, d = sx[list(tri)], dep[list(tri)]
            x0, x1 = max(int(np.floor(v[:, 0].min())), 0), min(int(np.ceil(v[:, 0].max())), Wp - 1)
            y0, y1 = max(int(np.floor(v[:, 1].min())), 0), min(int(np.ceil(v[:, 1].max())), Hp - 1)
            if x1 < x0 or y1 < y0:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            (ax, ay), (bx, by), (cx, cy) = v
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-9:
                continue
            w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
            w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
            w2 = 1.0 - w0 - w1
            m = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not m.any():
                continue
            zz = 1.0 / (w0 / d[0] + w1 / d[1] + w2 / d[2]) if persp else w0 * d[0] + w1 * d[1] + w2 * d[2]
            sub = Z[y0:y1 + 1, x0:x1 + 1]
            upd = m & (zz < sub)
            if not upd.any():
                continue
            sub[upd] = zz[upd]
            IMG[y0:y1 + 1, x0:x1 + 1][upd] = cc
            MID[y0:y1 + 1, x0:x1 + 1][upd] = cid
    e = np.zeros((Hp, Wp), bool)
    for ax_ in (0, 1):
        za, zb = Z, np.roll(Z, 1, ax_)
        fin = np.isfinite(za) & np.isfinite(zb)
        jump = np.zeros_like(e)
        thr = rel_jump * np.minimum(za[fin], zb[fin]) if persp else djump
        jump[fin] = np.abs(za[fin] - zb[fin]) > thr
        e |= (MID != np.roll(MID, 1, ax_)) | jump
    IMG[e] *= edge_dark
    return Image.fromarray(np.clip(IMG, 0, 255).astype(np.uint8)).resize((W, H), Image.LANCZOS)


def mask(polys, proj, xform, size, ss=1):
    """多边形投影后的填充掩膜（L 模式）。用于叠参考图、比外轮廓。"""
    m = Image.new("L", (size[0] * ss, size[1] * ss), 0)
    dr = ImageDraw.Draw(m)
    for pts, _ in polys:
        q, dep = proj(pts)
        if not np.all(np.isfinite(q)):
            continue
        dr.polygon([tuple(np.array(xform(a, b)) * ss) for a, b in q], fill=255)
    return m if ss == 1 else m.resize(size, Image.LANCZOS)


def outline(mask_img, color, width=3):
    """掩膜外轮廓 → (着色层, 透明度)，用法：base.paste(layer, (0, 0), alpha)。"""
    ed = mask_img.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0)
    if width > 1:
        ed = ed.filter(ImageFilter.MaxFilter(width if width % 2 else width + 1))
    return Image.new("RGBA", mask_img.size, tuple(color) + (255,)), ed


def selftest(out=None):
    polys = box((0, 0), (1, 0), -500, 500, 600, 400, 400, 400, "stone")
    polys += box((0, 900), (1, 0), -300, 300, 300, 200, 200, 200, "wood")
    # 法线朝外：每个面法线与（面心 − 盒心）同向
    for pts, _ in polys[:6]:
        n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
        assert float(n @ (pts.mean(0) - np.array([0, 0, 200]))) > 0, "box 法线朝内"
    for pts, _ in mirror(polys[:6], 1):
        n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
        assert float(n @ (pts.mean(0) - np.array([0, 0, 200]))) > 0, "mirror 后法线朝内"
    W = 320
    im = zrender(polys, persp((2500, -2500, 1800), (0, 300, 100), W=W), lambda a, b: (W / 2 + a, 120 - b), W, 240)
    a = np.asarray(im)
    assert (np.abs(a.astype(int) - np.array([238, 242, 246])).sum(2) > 30).mean() > 0.05, "什么也没画上"
    im2 = zrender(polys, ortho(0, 2, 1), lambda u, v: (160 + u * 0.1, 120 - v * 0.1), 320, 240, persp=False)
    mk = mask(polys, ortho(0, 2, 1), lambda u, v: (160 + u * 0.1, 120 - v * 0.1), (320, 240))
    assert np.asarray(mk).max() == 255
    if out:
        Image.fromarray(np.hstack([a, np.asarray(im2)])).save(out)
    print("preview selftest ok：box 法线、镜像法线、透视 / 正交 z-buffer、掩膜")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest"):
        selftest(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        print(__doc__)
