"""剪影对比：两张同机位图 → IoU、各自多出的面积、最差的列 / 行、叠加图。普通 Python（Pillow + numpy）。

    python silhouette_iou.py A.png B.png [--out overlay.png] [--align none|bbox] [--fill] [--json out.json]

A = 渲染，B = 参考（或改动前的渲染）。

掩膜：
- 有 alpha 通道（渲染开了 Film → Transparent）时直接用 alpha > 0.5；
- 没有时用四角像素的中位色当背景，与背景色差 > 阈值（--th，默认 0.12）即前景。
- 参考图背景杂乱时，先在图像软件里抠成透明或纯色底，再来比。

--align none（默认）：不对齐。同一台相机渲出来的图要这样比，尺寸和位置的误差都会算进去。
--align bbox：两张掩膜各自裁到外框，缩放到同一尺寸再比。只比"形"，不比大小和位置；
             参考图机位未知时用。注意：整体缩放 10% 在这种模式下 IoU 仍有 0.994（不对齐时 0.69）。
--fill：把内部的洞填实再比（只比外包络）。默认不填：门洞、内凹是大形的一部分。

输出（stdout 一行 JSON，可选写文件）：iou、a_only / b_only（占并集的比例）、
worst_cols / worst_rows（按该列 / 行不一致像素占并集高度 / 宽度的比例排序）、两张图的外框与宽高比。
叠加图：白 = 都有，红 = 只有 A，蓝 = 只有 B。
"""
import argparse
import json
import sys

import numpy as np
from PIL import Image


def mask_of(path, th):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        a = np.asarray(im.convert("RGBA"), dtype=np.float32)[..., 3] / 255.0
        if a.min() < 0.5 < a.max():
            return a > 0.5, "alpha"
    rgb = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
    h, w, _ = rgb.shape
    k = max(2, min(h, w) // 50)
    corners = np.concatenate([rgb[:k, :k].reshape(-1, 3), rgb[:k, -k:].reshape(-1, 3),
                              rgb[-k:, :k].reshape(-1, 3), rgb[-k:, -k:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    return np.linalg.norm(rgb - bg, axis=2) > th, "bg_color"


def fill_holes(m):
    """从图像边缘泛洪（4 邻接），没被泛洪到的背景 = 洞，填实。
    有 scipy 用 ndimage.binary_fill_holes（C 实现，1080p 约 0.02 s，结果与下面逐像素等价）；
    没有就退回纯 Python BFS（1080p 约 1 s）。注意 PIL 的 ImageDraw.floodfill 也是 Python 循环，不更快。"""
    try:
        from scipy.ndimage import binary_fill_holes
        return binary_fill_holes(m)
    except Exception:
        pass
    from collections import deque
    h, w = m.shape
    seen = np.zeros_like(m, dtype=bool)
    q = deque()
    for y in range(h):
        for x in (0, w - 1):
            if not m[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if not m[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= yy < h and 0 <= xx < w and not m[yy, xx] and not seen[yy, xx]:
                seen[yy, xx] = True
                q.append((yy, xx))
    return ~seen


def bbox(m):
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def crop_resize(m, bb, size):
    x0, y0, x1, y1 = bb
    im = Image.fromarray((m[y0:y1, x0:x1] * 255).astype(np.uint8))
    return np.asarray(im.resize(size, Image.NEAREST)) > 127


def compare(a_path, b_path, align="none", fill=False, th=0.12, out=None, top=5):
    a, sa = mask_of(a_path, th)
    b, sb = mask_of(b_path, th)
    if fill:
        a, b = fill_holes(a), fill_holes(b)
    ba, bb_ = bbox(a), bbox(b)
    if ba is None or bb_ is None:
        raise SystemExit("silhouette_iou: 有一张图没有前景（检查背景 / 阈值）")
    if align == "bbox":
        size = (max(ba[2] - ba[0], bb_[2] - bb_[0]), max(ba[3] - ba[1], bb_[3] - bb_[1]))
        a, b = crop_resize(a, ba, size), crop_resize(b, bb_, size)
    elif a.shape != b.shape:
        raise SystemExit("silhouette_iou: 尺寸不同 %s vs %s；同机位图应同分辨率，或用 --align bbox" % (a.shape, b.shape))
    inter, union = a & b, a | b
    nu = int(union.sum())
    diff = a ^ b
    hu = max(1, int(union.any(axis=1).sum()))
    wu = max(1, int(union.any(axis=0).sum()))
    cols = diff.sum(axis=0) / hu
    rows = diff.sum(axis=1) / wu
    res = dict(
        iou=round(float(inter.sum()) / max(1, nu), 4),
        a_only=round(float((a & ~b).sum()) / max(1, nu), 4),
        b_only=round(float((b & ~a).sum()) / max(1, nu), 4),
        worst_cols=[dict(x=int(i), frac=round(float(cols[i]), 4)) for i in np.argsort(-cols)[:top] if cols[i] > 0],
        worst_rows=[dict(y=int(i), frac=round(float(rows[i]), 4)) for i in np.argsort(-rows)[:top] if rows[i] > 0],
        bbox_a=ba, bbox_b=bb_,
        aspect_a=round((ba[2] - ba[0]) / (ba[3] - ba[1]), 4), aspect_b=round((bb_[2] - bb_[0]) / (bb_[3] - bb_[1]), 4),
        mask_source=[sa, sb], align=align, filled=fill, size=[int(a.shape[1]), int(a.shape[0])])
    if out:
        ov = np.zeros(a.shape + (3,), dtype=np.uint8)
        ov[inter] = (235, 235, 235)
        ov[a & ~b] = (230, 40, 40)
        ov[b & ~a] = (40, 90, 230)
        Image.fromarray(ov).save(out)
        res["overlay"] = out
    return res


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--out")
    p.add_argument("--json")
    p.add_argument("--align", choices=("none", "bbox"), default="none")
    p.add_argument("--fill", action="store_true")
    p.add_argument("--th", type=float, default=0.12)
    o = p.parse_args(argv)
    r = compare(o.a, o.b, o.align, o.fill, o.th, o.out)
    if o.json:
        with open(o.json, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
    print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
