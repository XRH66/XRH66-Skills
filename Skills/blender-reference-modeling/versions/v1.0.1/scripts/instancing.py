# -*- coding: utf-8 -*-
"""
instancing：实例记录、对称群、叠层净距（几何原语层，领域无关，纯 numpy；Blender 端见 points_to_blender）。
实例记录 = dict(p=(x, y, z) mm, rot=(rx, ry, rz) 欧拉 XYZ（与 Blender 同约定 R = Rz·Ry·Rx）, scl=(sx, sy, sz), var=int, 及任意键)。

  frame(Y, Zhint)                       件的局部轴：Y = 主方向（件沿 Y 伸展），Z ≈ Zhint（如支承法向），X = Y × Z → 3×3（列 = X, Y, Z）
  euler_from(R) / matrix_from(eul)      旋转矩阵 ↔ 欧拉 XYZ（Blender 约定；万向锁处 rx = 0）
  record(p, Y, Zhint, length=None, L0=1, var=0, **k)   一条实例记录（scl = (1, length/L0, 1)：沿 Y 拉伸）
  jitter(recs, seed, dp, drot, dscl, keys)            可控随机：位置 / 角度 / 缩放的小扰动，可复现
  mirror(recs, axis=0, plane=0)          镜像：位置翻转，旋转矩阵 M·R·M 后把 X 重算为 Y × Z（保持右手系，件不翻面）
  rotate_n(recs, n, center)              n 次绕 Z 旋转对称展开
  translate(recs, vec, count)            平移阵列
  stack_drop(top_lo, bot_up, extra=0)    叠层净距：下层顶面高程与上层底面高程在公共采样上的最大侵入量 + extra，<0 记 0
                                         （上层整体下放 / 抬起多少才不穿；extra 含倒角、截面翻滚 w/2·|roll|、弯折余量）
  save_json(recs, path) / load_json(path)
  points_to_blender(recs, name, coll)    （Blender 内）点网格 + 属性 rot / scl / var，交给 GN 实例器
[实测：修仙牌楼椽：两层叠放 drop = max(yc_top − fc_bot) + FC_W/2·|roll| + CLEAR，实例干涉 63 → 0]
"""
import json
import math
import numpy as np


def _unit(v):
    v = np.asarray(v, float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def frame(Y, Zhint=(0, 0, 1)):
    Y = _unit(Y)
    Z = np.asarray(Zhint, float)
    Z = _unit(Z - Y * (Z @ Y))
    if np.linalg.norm(Z) < 1e-9:                                  # Zhint ∥ Y：退而取世界 X 构造
        Z = _unit(np.cross(Y, (1, 0, 0)))
    X = np.cross(Y, Z)
    return np.column_stack([X, Y, Z])


def matrix_from(e):
    rx, ry, rz = e
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def euler_from(R):
    R = np.asarray(R, float)
    sy = -R[2, 0]
    if abs(sy) < 1 - 1e-9:
        return (math.atan2(R[2, 1], R[2, 2]), math.asin(sy), math.atan2(R[1, 0], R[0, 0]))
    return (0.0, math.copysign(math.pi / 2, sy), math.atan2(-R[0, 1], R[1, 1]))


def record(p, Y, Zhint=(0, 0, 1), length=None, L0=1.0, var=0, **k):
    return dict(p=tuple(map(float, p)), rot=euler_from(frame(Y, Zhint)), scl=(1.0, (length / L0) if length else 1.0, 1.0), var=int(var), **k)


def jitter(recs, seed=0, dp=0.0, drot=0.0, dscl=0.0):
    rng = np.random.default_rng(seed)
    out = []
    for r in recs:
        r = dict(r)
        r["p"] = tuple(np.asarray(r["p"]) + rng.uniform(-dp, dp, 3))
        R = matrix_from(r["rot"]) @ matrix_from(rng.uniform(-drot, drot, 3))   # 局部系里扰动
        r["rot"] = euler_from(R)
        r["scl"] = tuple(np.asarray(r["scl"]) * (1 + rng.uniform(-dscl, dscl)))
        out.append(r)
    return out


def mirror(recs, axis=0, plane=0.0):
    M = np.eye(3)
    M[axis, axis] = -1
    out = []
    for r in recs:
        r = dict(r)
        p = np.array(r["p"], float)
        p[axis] = 2 * plane - p[axis]
        R = matrix_from(r["rot"])
        Y, Z = M @ R[:, 1], M @ R[:, 2]
        r["p"], r["rot"] = tuple(p), euler_from(np.column_stack([np.cross(Y, Z), Y, Z]))
        r["mirrored"] = not r.get("mirrored", False)
        out.append(r)
    return out


def rotate_n(recs, n, center=(0, 0, 0)):
    c = np.asarray(center, float)
    out = []
    for k in range(n):
        Rk = matrix_from((0, 0, 2 * math.pi * k / n))
        for r in recs:
            q = dict(r)
            q["p"] = tuple(c + Rk @ (np.asarray(r["p"]) - c))
            q["rot"] = euler_from(Rk @ matrix_from(r["rot"]))
            q["k"] = k
            out.append(q)
    return out


def translate(recs, vec, count):
    v = np.asarray(vec, float)
    return [dict(r, p=tuple(np.asarray(r["p"]) + v * i), i=i) for i in range(count) for r in recs]


def stack_drop(top_lo, bot_up, extra=0.0):
    top_lo, bot_up = np.asarray(top_lo, float), np.asarray(bot_up, float)
    m = ~(np.isnan(top_lo) | np.isnan(bot_up))
    if not m.any():
        return 0.0
    return max(0.0, float(np.max(top_lo[m] - bot_up[m])) + extra)


def save_json(recs, path):
    conv = lambda v: [float(x) for x in v] if isinstance(v, (tuple, list, np.ndarray)) else (bool(v) if isinstance(v, (bool, np.bool_)) else (int(v) if isinstance(v, (int, np.integer)) else (float(v) if isinstance(v, (float, np.floating)) else v)))
    json.dump([{k: conv(v) for k, v in r.items()} for r in recs], open(path, "w", encoding="utf-8"), ensure_ascii=False)


def load_json(path):
    return json.load(open(path, encoding="utf-8"))


def points_to_blender(recs, name, coll=None, mm=0.001):
    """Blender 内调用。点网格 + 点属性 rot(FLOAT_VECTOR) / scl(FLOAT_VECTOR) / var(INT)；实例器读这些属性。"""
    import bpy
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(np.asarray(r["p"]) * mm) for r in recs], [], [])
    for key, typ in (("rot", "FLOAT_VECTOR"), ("scl", "FLOAT_VECTOR"), ("var", "INT")):
        a = me.attributes.new(key, typ, "POINT")
        for i, r in enumerate(recs):
            if typ == "INT":
                a.data[i].value = int(r.get(key, 0))
            else:
                a.data[i].vector = tuple(r[key])
    ob = bpy.data.objects.new(name, me)
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def instancer_bpy(points_ob, kit_coll, name="GN_KitInstancer"):
    """（Blender 内）通用 GN 实例器：点 → Instance on Points；实例 = kit 集合的第 var 个子对象（按名字排序，命名 *_v0、*_v1…），
    旋转 = 属性 rot（欧拉 XYZ）、缩放 = 属性 scl。kit 集合应排除出视图层（只当模板）。[实测：鳞甲护臂 152 片 5 变体]"""
    import bpy
    ng = bpy.data.node_groups.get(name)
    if ng is None:
        ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
        ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        N, Lk = ng.nodes, ng.links
        gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
        iop = N.new("GeometryNodeInstanceOnPoints")
        ci = N.new("GeometryNodeCollectionInfo")
        ci.transform_space = "ORIGINAL"
        ci.inputs["Separate Children"].default_value = True
        ci.inputs["Reset Children"].default_value = True
        ci.name = "KitCollection"
        a_rot, a_scl, a_var = (N.new("GeometryNodeInputNamedAttribute") for _ in range(3))
        for a, nm, dt in ((a_rot, "rot", "FLOAT_VECTOR"), (a_scl, "scl", "FLOAT_VECTOR"), (a_var, "var", "INT")):
            a.data_type = dt
            a.inputs["Name"].default_value = nm
        e2r = N.new("FunctionNodeEulerToRotation")
        Lk.new(gi.outputs[0], iop.inputs["Points"])
        Lk.new(ci.outputs[0], iop.inputs["Instance"])
        iop.inputs["Pick Instance"].default_value = True
        Lk.new(a_var.outputs["Attribute"], iop.inputs["Instance Index"])
        Lk.new(a_rot.outputs["Attribute"], e2r.inputs[0])
        Lk.new(e2r.outputs[0], iop.inputs["Rotation"])
        Lk.new(a_scl.outputs["Attribute"], iop.inputs["Scale"])
        Lk.new(iop.outputs[0], go.inputs[0])
    ng.nodes["KitCollection"].inputs["Collection"].default_value = kit_coll
    m = points_ob.modifiers.new(name, "NODES")
    m.node_group = ng
    return m


def selftest():
    rng = np.random.default_rng(3)
    for _ in range(200):
        e = rng.uniform(-math.pi, math.pi, 3) * (1, 0.49, 1)
        assert np.allclose(euler_from(matrix_from(e)), e, atol=1e-9), "欧拉往返"
    F = frame((0, -1, 0.3), (0, 0, 1))
    assert np.allclose(F.T @ F, np.eye(3), atol=1e-12) and np.linalg.det(F) > 0, "标架正交右手"
    assert np.allclose(F[:, 1], _unit((0, -1, 0.3))) and F[2, 2] > 0.9, "Y 主方向、Z 近竖直"
    r = record((100, 0, 0), (0.3, -1, -0.4), (0, 0, 1), length=500, L0=250)
    assert r["scl"] == (1.0, 2.0, 1.0)
    m = mirror([r])[0]
    Rm = matrix_from(m["rot"])
    assert np.isclose(np.linalg.det(Rm), 1) and m["p"][0] == -100, "镜像右手 / 位置"
    Ro = matrix_from(r["rot"])
    assert np.allclose(Rm[:, 1], Ro[:, 1] * (-1, 1, 1)) and np.allclose(Rm[:, 2], Ro[:, 2] * (-1, 1, 1)), "镜像 Y、Z 翻 x 分量"
    assert len(rotate_n([r], 6)) == 6 and np.allclose(rotate_n([r], 4)[1]["p"], (0, 100, 0), atol=1e-9), "旋转对称"
    assert translate([r], (0, 0, 10), 3)[2]["p"][2] == 20, "平移阵列"
    j1, j2 = jitter([r] * 5, seed=7, dp=2, drot=0.02), jitter([r] * 5, seed=7, dp=2, drot=0.02)
    assert all(a["p"] == b["p"] for a, b in zip(j1, j2)), "随机可复现"
    s = np.linspace(0, 1, 11)
    assert abs(stack_drop(10 + 5 * s, 12 + 0 * s, extra=3) - 6) < 1e-12, "叠层净距"
    assert stack_drop([0, 1], [5, 6]) == 0.0
    print("instancing selftest ok：欧拉往返、标架、拉伸缩放、镜像保右手、旋转 / 平移展开、随机可复现、叠层净距")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    selftest() if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest") else print(__doc__)
