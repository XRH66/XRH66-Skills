# -*- coding: utf-8 -*-
"""实例间干涉审计：逐对象审计（eval_audit）看不到 GN / 点实例之间的穿插。
把指定载体对象的实例按 depsgraph 展开成世界坐标 BVH，包围盒预筛后两两求交。

    blender -b file.blend --python audit_instances.py -- 载体A 载体B … [--xmin 4.5] [--out out.json]
或在会话里 exec，先设全局 INST_NAMES = [...]（可选 INST_XMIN、INST_OUT）。
对象之间模式（逐对象审计只看自交，看不到两个对象互穿）：
    blender -b file.blend --python audit_instances.py -- --objects 对象或集合名… [--out out.json]
  求值后网格（含修改器）两两求交；名字是集合时取其中全部网格对象。设计上贴合的件别放进同一次审计。

- 只审"本不该相交"的件（椽、栏杆、阵列件）。按设计搭接的件（瓦上下片、鳞片叠压）不要放进来，否则全是假阳性。
- --xmin：只审 |x| ≥ 该值（m）的实例（只看接口 / 新加区域时用，省时间）。
- 贴合面（共面接触）也会报相交：两层件设计上贴合时，先按净距规则让开（见 pitfalls"两层椽"），再审。
[实测：修仙牌楼 C2 转角 224 件椽，63 对 → 下放檐椽后 0 对]
"""
import sys
import json
import bpy
from mathutils.bvhtree import BVHTree
from mathutils import Vector


def _cfg():
    g = globals()
    names, xmin, out = list(g.get("INST_NAMES", [])), g.get("INST_XMIN", None), g.get("INST_OUT", None)
    g["OBJ_MODE"] = g.get("OBJ_MODE", False)
    if "--" in sys.argv:
        rest = sys.argv[sys.argv.index("--") + 1:]
        i = 0
        while i < len(rest):
            if rest[i] == "--xmin":
                xmin = float(rest[i + 1])
                i += 2
            elif rest[i] == "--objects":
                globals()["OBJ_MODE"] = True
                i += 1
            elif rest[i] == "--out":
                out = rest[i + 1]
                i += 2
            else:
                names.append(rest[i])
                i += 1
    return names, xmin, out


def run(names, xmin=None):
    dg = bpy.context.evaluated_depsgraph_get()
    items = []
    for inst in dg.object_instances:
        if not inst.is_instance or inst.parent is None or inst.parent.original.name not in names:
            continue
        mw = inst.matrix_world.copy()
        if xmin is not None and abs(mw.translation.x) < xmin:
            continue
        me = inst.object.data
        vs = [mw @ v.co for v in me.vertices]
        if not vs:
            continue
        items.append(dict(src=inst.parent.original.name, at=[round(c, 3) for c in mw.translation],
                          lo=Vector([min(v[k] for v in vs) for k in range(3)]), hi=Vector([max(v[k] for v in vs) for k in range(3)]),
                          bvh=BVHTree.FromPolygons(vs, [list(p.vertices) for p in me.polygons])))
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if any(a["hi"][k] < b["lo"][k] or b["hi"][k] < a["lo"][k] for k in range(3)):
                continue
            if a["bvh"].overlap(b["bvh"]):
                pairs.append((a["src"], a["at"], b["src"], b["at"]))
    by = {}
    for p in pairs:
        k = " × ".join(sorted((p[0], p[2])))
        by[k] = by.get(k, 0) + 1
    return dict(verdict="pass" if not pairs else "fail", instances=len(items), overlap_pairs=len(pairs), by_pair=by, sample=pairs[:12])


def run_objects(names):
    dg = bpy.context.evaluated_depsgraph_get()
    obs = []
    for nm in names:
        c = bpy.data.collections.get(nm)
        obs += [o for o in (c.all_objects if c else [bpy.data.objects.get(nm)]) if o is not None and o.type == "MESH"]
    items = []
    for ob in obs:
        ev = ob.evaluated_get(dg)
        me = ev.to_mesh()
        vs = [ev.matrix_world @ v.co for v in me.vertices]
        if vs:
            items.append(dict(src=ob.name, lo=Vector([min(v[k] for v in vs) for k in range(3)]), hi=Vector([max(v[k] for v in vs) for k in range(3)]),
                              bvh=BVHTree.FromPolygons(vs, [list(p.vertices) for p in me.polygons])))
        ev.to_mesh_clear()
    by = {}
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if any(a["hi"][k] < b["lo"][k] or b["hi"][k] < a["lo"][k] for k in range(3)):
                continue
            n = len(a["bvh"].overlap(b["bvh"]))
            if n:
                by[a["src"] + " × " + b["src"]] = n
    return dict(verdict="pass" if not by else "fail", objects=len(items), overlap_pairs=len(by), by_pair=by)


if __name__ == "__main__":
    names, xmin, out = _cfg()
    if not names:
        print(__doc__)
    elif globals().get("OBJ_MODE"):
        res = run_objects(names)
        print("OBJECTS", json.dumps(res, ensure_ascii=False))
        if out:
            json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    else:
        res = run(names, xmin)
        print("INSTANCES", json.dumps({k: v for k, v in res.items() if k != "sample"}, ensure_ascii=False))
        if out:
            json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
