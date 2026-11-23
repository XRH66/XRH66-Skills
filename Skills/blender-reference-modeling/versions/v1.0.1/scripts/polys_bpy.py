# -*- coding: utf-8 -*-
"""
polys_bpy：多边形汤 [(pts(k, 3) mm, tag)] → Blender 对象。两半：
  系统 Python 侧  save(path, polys, groups, origin_mm, meta)   写 .npz + .json（不依赖 bpy）
  Blender 侧      build_from(path, collection) → [对象]         读回、按组成件（bmesh：焊点、去退化、统一法线、活 Bevel）
这样几何生成（numpy / scipy / Pillow）留在系统 Python，Blender 里只成面，无头和 GUI 都能跑。[实测：修仙牌楼翼角样件]

groups：[dict(name="SY_Corner_Shell", tags=["band", "slope", "soffit"], bevel_mm=10, color=(r, g, b), weld_mm=0.5,
               seg=2, angle_deg=35, recalc=True, mat_by_tag={"slope": "M_TileBed", …})]（mat_by_tag：借已有材质，按面分槽）
  - 同组多边形合成一个对象；坐标 = (p − origin)·0.001（场景 1 BU = 1 m），对象 location = origin·0.001 → 原点在接口中心、scale = 1。
  - Bevel 修改器保持活的（不 apply）；审计请审求值后结果（eval_audit.py）。
"""
import json
import os

MM = 0.001


# ---------------------------------------------------------------- 系统 Python 侧
def save(path, polys, groups, origin_mm=(0.0, 0.0, 0.0), meta=None):
    import numpy as np
    tags = sorted({t for _, t in polys})
    sizes = np.array([len(p) for p, _ in polys], np.int32)
    verts = np.concatenate([np.asarray(p, float) for p, _ in polys], 0)
    tidx = np.array([tags.index(t) for _, t in polys], np.int32)
    np.savez_compressed(path + ".npz", verts=verts, sizes=sizes, tidx=tidx)
    with open(path + ".json", "w", encoding="utf-8") as f:
        json.dump(dict(tags=tags, groups=groups, origin_mm=list(map(float, origin_mm)), meta=meta or {}), f, ensure_ascii=False, indent=1)
    return path


# ---------------------------------------------------------------- Blender 侧
def _material(name, color):
    import bpy
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = tuple(color) + (1.0,)
        bsdf.inputs["Roughness"].default_value = 0.8
    m.diffuse_color = tuple(color) + (1.0,)
    return m


def build_from(path, collection="COL_SY", replace=True):
    import bpy
    import bmesh
    import numpy as np
    d = np.load(path + ".npz")
    info = json.load(open(path + ".json", encoding="utf-8"))
    verts, sizes, tidx = d["verts"], d["sizes"], d["tidx"]
    starts = np.r_[0, np.cumsum(sizes)[:-1]]
    tags = info["tags"]
    org = np.array(info["origin_mm"], float)
    coll = bpy.data.collections.get(collection)
    if coll is None:
        coll = bpy.data.collections.new(collection)
        bpy.context.scene.collection.children.link(coll)
    out = []
    for g in info["groups"]:
        want = {tags.index(t) for t in g["tags"] if t in tags}
        idx = [i for i in range(len(sizes)) if tidx[i] in want]
        if not idx:
            continue
        if replace and g["name"] in bpy.data.objects:
            old = bpy.data.objects[g["name"]]
            me_old = old.data
            bpy.data.objects.remove(old)
            if me_old and me_old.users == 0:
                bpy.data.meshes.remove(me_old)
        bm = bmesh.new()
        lay = bm.faces.layers.int.new("tag")
        for i in idx:
            pts = (verts[starts[i]:starts[i] + sizes[i]] - org) * MM
            vs = [bm.verts.new(tuple(p)) for p in pts]
            try:
                f = bm.faces.new(vs)
                f[lay] = int(tidx[i])
            except ValueError:
                pass
        mbt = g.get("mat_by_tag")                       # {tag: 材质名}：借用已有材质（如主文件里的），按面分槽
        slots = []
        if mbt:
            for f in bm.faces:
                nm = mbt.get(tags[f[lay]])
                if nm not in slots:
                    slots.append(nm)
                f.material_index = slots.index(nm)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=g.get("weld_mm", 0.5) * MM)
        bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=0.05 * MM)
        lone = [v for v in bm.verts if not v.link_faces]
        if lone:
            bmesh.ops.delete(bm, geom=lone, context="VERTS")
        if g.get("cap_holes"):                           # 平面开口（如接口截面）补 n-gon 收口 → 闭合实体
            bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=0)
        if g.get("recalc", True):
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        me = bpy.data.meshes.new(g["name"])
        bm.to_mesh(me)
        bm.free()
        if slots:
            for nm in slots:
                me.materials.append(bpy.data.materials.get(nm) or _material(nm, g.get("color", (0.6, 0.6, 0.6))))
        else:
            me.materials.append(_material("M_" + g["name"], g.get("color", (0.6, 0.6, 0.6))))
        ob = bpy.data.objects.new(g["name"], me)
        ob.location = tuple(org * MM)
        coll.objects.link(ob)
        if g.get("bevel_mm"):
            m = ob.modifiers.new("Bevel", "BEVEL")
            m.width = g["bevel_mm"] * MM
            m.segments = g.get("seg", 2)
            m.limit_method = "ANGLE"
            import math
            m.angle_limit = math.radians(g.get("angle_deg", 35.0))
            m.harden_normals = False
        for p in me.polygons:
            p.use_smooth = False
        out.append(ob)
    return out


def clean_factory_scene():
    """--factory-startup 的默认场景：删掉默认立方体 / 相机 / 灯（只在新文件里用，不要在用户场景里调）。"""
    import bpy
    for nm in ("Cube", "Camera", "Light"):
        ob = bpy.data.objects.get(nm)
        if ob is not None:
            bpy.data.objects.remove(ob)
    for coll in (bpy.data.meshes, bpy.data.cameras, bpy.data.lights):
        for b in list(coll):
            if b.users == 0:
                coll.remove(b)


def stats(objs):
    """求值后每个对象的面数 / 三角面占比 / n-gon 数（项目规范：quad 为主）。"""
    import bpy
    dg = bpy.context.evaluated_depsgraph_get()
    res = {}
    for ob in objs:
        me = ob.evaluated_get(dg).to_mesh()
        n = len(me.polygons)
        tri = sum(1 for p in me.polygons if p.loop_total == 3)
        ng = sum(1 for p in me.polygons if p.loop_total > 4)
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(me)
        bnd = [e for e in bm.edges if e.is_boundary]
        bb = None
        if bnd:
            co = [(ob.matrix_world @ v.co) for e in bnd for v in e.verts]
            bb = [[round(min(c[k] for c in co), 3) for k in range(3)], [round(max(c[k] for c in co), 3) for k in range(3)]]
        bm.free()
        res[ob.name] = dict(faces=n, tri_frac=round(tri / max(n, 1), 3), ngons=ng, verts=len(me.vertices), boundary=len(bnd), boundary_bbox_m=bb,
                            location=[round(v, 4) for v in ob.location], scale=list(ob.scale))
        ob.evaluated_get(dg).to_mesh_clear()
    return res


if __name__ == "__main__":
    print(__doc__)
    print("在 Blender 里：import polys_bpy as PB; PB.build_from(path)；系统 Python：PB.save(path, polys, groups, origin)")
    print(os.path.abspath(__file__))
