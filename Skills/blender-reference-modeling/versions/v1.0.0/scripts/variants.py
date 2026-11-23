# -*- coding: utf-8 -*-
"""
variants：方案族的登记、统一指标、对比图拼版。Pillow，可缺 numpy。

为什么要有（来自修仙牌楼翼角，2026-11-20/21）[实测]
  单张参考常有"拓扑歧义"：刀锋翼和真转角在 ref02 机位下投影几乎一样，俯视 / 3/4 下却是两种屋顶。
  这时不能让残差去定结构，要把结构做成**方案族**，同视角、同口径并排，结构由人按造型定，残差只当约束。

约定
  族 family：离散结构（如 blade / true）。族内用开关（axis_beam）或连续参数（sag 0 → 1）区分方案。
  角色 role：primary（首选）/ backup（备选）；default 是默认构建那一个。
  每个方案的参数只写在项目 spec 里（单一数值源）；这里只登记、排序、出表、拼图。
  公平：每个方案走同样的对位、同样的残差口径；差别要能归到一个变量上。不公平的对比先修再比。
  决定要记下来，连同理由（例："这里造型优先于照片贴合"），免得以后拿同一个残差把它否掉。
"""
import json
import os

ROLE_ZH = dict(primary="首选", backup="备选", trial="试")


def registry(variants, primary=(), backup=(), default=None, order=None):
    """variants: {name: dict(family=…, label=…, …参数)} → 有序列表 [dict(name, role, is_default, **v)]。
    顺序：default → 其余 primary（按给定顺序）→ backup → 未登记角色的（role = trial）。"""
    names = list(order) if order else []
    if not names:
        names = ([default] if default else []) + [n for n in primary if n != default] + list(backup)
        names += [n for n in variants if n not in names]
    out = []
    for n in names:
        if n not in variants:
            raise KeyError("方案 %s 未在 spec 里定义" % n)
        role = "primary" if n in primary or n == default else ("backup" if n in backup else "trial")
        out.append(dict(variants[n], name=n, role=role, is_default=(n == default)))
    return out


def metrics_table(rows, cols, fmt=None):
    """rows: [dict(name=…, **指标)]；cols: [(键, 表头)] → Markdown 表。"""
    fmt = fmt or {}
    head = "| " + " | ".join(h for _, h in cols) + " |"
    sep = "|" + "---|" * len(cols)
    lines = [head, sep]
    for r in rows:
        cells = []
        for k, _ in cols:
            v = r.get(k, "")
            f = fmt.get(k)
            cells.append(f(v) if f else ("%.2f" % v if isinstance(v, float) else str(v)))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def save_numbers(path, rows, meta=None):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(meta=meta or {}, rows=rows), f, ensure_ascii=False, indent=1, default=float)


# ---------------------------------------------------------------- 拼版
def _font(n, path=None):
    from PIL import ImageFont
    for p in ([path] if path else []) + [r"C:\Windows\Fonts\msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
                                         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]:
        if p and os.path.exists(p):
            return ImageFont.truetype(p, n)
    return ImageFont.load_default()


def label(img, title, sub=None, band=58, font_path=None):
    """在图顶加白条写方案名 / 一行数字（原图不缩放，向下加高）。"""
    from PIL import Image, ImageDraw
    out = Image.new("RGB", (img.width, img.height + band), (255, 255, 255))
    out.paste(img, (0, band))
    dr = ImageDraw.Draw(out)
    dr.text((8, 2), title, fill=(0, 0, 0), font=_font(20, font_path))
    if sub:
        dr.text((8, 31), sub, fill=(70, 70, 70), font=_font(16, font_path))
    return out


def sheet(rows, notes=(), gap=14, head=30, font_path=None, bg=(255, 255, 255)):
    """rows: [(行标题, [PIL.Image…])]（每行同列数 = 方案数）；notes: 底部说明若干行。返回 PIL.Image。"""
    from PIL import Image, ImageDraw
    Wtot = max(sum(i.width for i in r) + gap * (len(r) - 1) for _, r in rows)
    Htot = sum(max(i.height for i in r) + head + gap for _, r in rows) + 22 * len(notes) + 20
    out = Image.new("RGB", (Wtot, Htot), bg)
    dr = ImageDraw.Draw(out)
    f17, f15 = _font(17, font_path), _font(15, font_path)
    y = 0
    for title, r in rows:
        dr.text((6, y + 4), title, fill=(30, 30, 30), font=f17)
        y += head
        x = 0
        for im in r:
            out.paste(im, (x, y))
            x += im.width + gap
        y += max(im.height for im in r) + gap
    for k, t in enumerate(notes):
        dr.text((6, y + 4 + 22 * k), t, fill=(0, 0, 0), font=f15)
    return out


def selftest():
    from PIL import Image
    V = dict(E1=dict(family="blade", label="E1"), B3=dict(family="blade", label="B3"),
             C1=dict(family="true", sag=1.0, label="C1"), C2=dict(family="true", sag=0.0, label="C2"))
    reg = registry(V, primary=("C2", "C1"), backup=("E1", "B3"), default="C2")
    assert [r["name"] for r in reg] == ["C2", "C1", "E1", "B3"] and reg[0]["is_default"] and reg[2]["role"] == "backup"
    t = metrics_table([dict(name="C2", rms=9.69)], [("name", "方案"), ("rms", "RMS")])
    assert "9.69" in t
    ims = [label(Image.new("RGB", (120, 80), (200, 200, 200)), r["name"], ROLE_ZH[r["role"]]) for r in reg]
    s = sheet([("测试行", ims)], notes=("说明",))
    assert s.width == 4 * 120 + 3 * 14
    print("variants selftest ok：登记顺序 / 角色 / 表 / 拼版")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest"):
        selftest()
    else:
        print(__doc__)
