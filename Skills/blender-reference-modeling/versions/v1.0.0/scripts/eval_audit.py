"""审计求值后的网格（修改器 / 几何节点之后），而不是原网格。

在 Blender 里运行（任一通道均可）：
    blender file.blend --background --python eval_audit.py -- COL_A COL_B --out audit.json
或在已打开的会话里 exec 本文件，先设全局变量 AUDIT_COLLECTIONS = ["COL_A", ...]。

副本模式（给只审原网格的外部审计工具用，如插件 audit_mesh）：
    ... -- COL_A COL_B --make-copies      → 每个对象的求值结果建一个 QC_<名字> 网格（世界坐标，无修改器），
                                            放进集合 QC_EVAL，并打印对象名列表（JSON）
    ... --clear-copies                    → 删掉 QC_EVAL 及其中所有对象 / 网格
  会话里：AUDIT_MAKE_COPIES = True 或 AUDIT_CLEAR_COPIES = True。审完一定要清，别把 QC_ 留进交付文件。

对给定集合里每个网格对象（含被排除的 kit 集合，临时打开再还原）：
  求值 → 临时 bmesh → 检查：边界边、非流形边、退化面、孤立点、自交（BVH 自重叠，排除共点的相邻面）、
  闭合壳的有向体积 < 0（法线朝内）。
只用几何节点做实例化的对象（求值后无自身面）跳过，它们的 kit 件单独审。
默认不改动场景：不建对象、不 apply、不写文件（除非给了 --out）。
"""
import sys
import json
import bpy
import bmesh
from mathutils.bvhtree import BVHTree

DEGEN_AREA = 1e-10      # m²
MAX_PAIRS = 10


QC_COLL = "QC_EVAL"


def _args():
    g = globals()
    cols, out = list(g.get("AUDIT_COLLECTIONS", [])), g.get("AUDIT_OUT")
    mode = "copies" if g.get("AUDIT_MAKE_COPIES") else "clear" if g.get("AUDIT_CLEAR_COPIES") else "audit"
    if "--" in sys.argv:
        rest = sys.argv[sys.argv.index("--") + 1:]
        if "--make-copies" in rest:
            mode = "copies"
            rest.remove("--make-copies")
        if "--clear-copies" in rest:
            mode = "clear"
            rest.remove("--clear-copies")
        if "--out" in rest:
            i = rest.index("--out")
            out = rest[i + 1]
            rest = rest[:i] + rest[i + 2:]
        cols = cols or rest
    return cols, out, mode


def _layer_colls(lc, acc):
    acc.append(lc)
    for c in lc.children:
        _layer_colls(c, acc)
    return acc


def audit_object(ob, dg):
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        if me is None or len(me.polygons) == 0:
            return None
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.transform(ob.matrix_world)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        r = dict(name=ob.name, verts=len(bm.verts), faces=len(bm.faces))
        r["boundary_edges"] = sum(1 for e in bm.edges if e.is_boundary)
        r["nonmanifold_edges"] = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
        r["degenerate_faces"] = sum(1 for f in bm.faces if f.calc_area() < DEGEN_AREA)
        r["loose_verts"] = sum(1 for v in bm.verts if not v.link_edges)
        tree = BVHTree.FromBMesh(bm, epsilon=0.0)
        pairs = []
        for a, b in tree.overlap(tree):
            if a >= b:
                continue
            va = {v.index for v in bm.faces[a].verts}
            if va & {v.index for v in bm.faces[b].verts}:
                continue                                  # 相邻面共点，不算自交
            pairs.append((a, b))
        r["self_intersections"] = len(pairs)
        r["self_intersection_pairs"] = [[a, b, [round(c, 4) for c in bm.faces[a].calc_center_median()]] for a, b in pairs[:MAX_PAIRS]]
        closed = r["boundary_edges"] == 0 and r["nonmanifold_edges"] == 0
        r["signed_volume"] = round(bm.calc_volume(signed=True), 6) if closed else None
        r["normals_inverted"] = bool(closed and r["signed_volume"] < 0)
        bm.free()
        return r
    finally:
        ev.to_mesh_clear()


def clear_copies():
    col = bpy.data.collections.get(QC_COLL)
    n = 0
    if col is not None:
        for ob in list(col.objects):
            me = ob.data
            bpy.data.objects.remove(ob)
            if me is not None and me.users == 0:
                bpy.data.meshes.remove(me)
            n += 1
        bpy.data.collections.remove(col)
    print("QC_COPIES cleared %d" % n)
    return n


def make_copies(names):
    """求值结果 → 独立网格对象（世界坐标烘进顶点，无修改器 / 几何节点）。返回对象名列表。"""
    clear_copies()
    col = bpy.data.collections.new(QC_COLL)
    bpy.context.scene.collection.children.link(col)
    vl = bpy.context.view_layer
    lcs = [lc for lc in _layer_colls(vl.layer_collection, []) if lc.collection.name in names]
    was = {lc.name: lc.exclude for lc in lcs}
    made = []
    try:
        for lc in lcs:
            lc.exclude = False
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        # 三段式，不可合并：边遍历 all_objects 边建 / 链接对象，会让 all_objects 缓存重建（遍历提前结束或拿到 None），
        # 链接对象还会让依赖图失效、已取的求值对象被释放。实测在 GUI 会话里把 Blender 卡死过。
        srcs, seen = [], set()
        for name in names:
            src = bpy.data.collections.get(name)
            if src is None:
                continue
            for ob in list(src.all_objects):                     # 1) 先把源对象定下来
                if ob is not None and ob.type == "MESH" and ob.name not in seen:
                    seen.add(ob.name)
                    srcs.append(ob)
        meshes = []
        for ob in srcs:                                          # 2) 全部求值成网格（不动场景）
            me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=False, depsgraph=dg)
            if len(me.polygons) == 0:                            # 纯实例化载体：kit 件单独审
                bpy.data.meshes.remove(me)
                continue
            me.transform(ob.matrix_world)
            meshes.append((ob.name, me))
        for nm, me in meshes:                                    # 3) 最后才建对象、链接
            cp = bpy.data.objects.new("QC_" + nm, me)
            col.objects.link(cp)
            made.append(cp.name)
    finally:
        for lc in lcs:
            lc.exclude = was[lc.name]
    print("QC_COPIES", json.dumps(made, ensure_ascii=False))
    return made


def main():
    names, out, mode = _args()
    if mode == "clear":
        return clear_copies()
    if mode == "copies":
        return make_copies(names)
    vl = bpy.context.view_layer
    lcs = [lc for lc in _layer_colls(vl.layer_collection, []) if lc.collection.name in names]
    was = {lc.name: lc.exclude for lc in lcs}
    try:
        for lc in lcs:
            lc.exclude = False
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        res, seen = [], set()
        for name in names:
            col = bpy.data.collections.get(name)
            if col is None:
                res.append(dict(name=name, missing=True))
                continue
            for ob in col.all_objects:
                if ob.type != "MESH" or ob.name in seen:
                    continue
                seen.add(ob.name)
                r = audit_object(ob, dg)
                if r is not None:
                    res.append(r)
    finally:
        for lc in lcs:
            lc.exclude = was[lc.name]
    keys = ("boundary_edges", "nonmanifold_edges", "degenerate_faces", "loose_verts", "self_intersections")
    totals = {k: sum(r.get(k, 0) or 0 for r in res) for k in keys}
    totals["normals_inverted"] = sum(1 for r in res if r.get("normals_inverted"))
    totals["missing"] = sum(1 for r in res if r.get("missing"))
    verdict = "pass" if not any(totals.values()) else "fail"
    report = dict(verdict=verdict, objects=len(res), totals=totals, results=res)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    print("AUDIT", verdict, json.dumps(totals))
    for r in res:
        bad = {k: r[k] for k in keys if r.get(k)}
        if bad or r.get("normals_inverted") or r.get("missing"):
            print("  ", r["name"], bad, "inverted" if r.get("normals_inverted") else "", r.get("self_intersection_pairs", [])[:3])
    return report


if __name__ == "__main__" or "AUDIT_COLLECTIONS" in globals() or "AUDIT_CLEAR_COPIES" in globals():
    main()
