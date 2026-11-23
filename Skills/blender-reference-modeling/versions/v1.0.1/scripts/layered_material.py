"""成因分层写实材质构建器（Cycles，纯 bpy，不依赖任何插件 / 第三方节点）。

来源：xiuxian-gateway R8 / R8b（古建牌楼：青瓦、老木、朱漆、红灰墙、青石岩、夯土地面）。
参数是该项目调好的默认值；新项目复制本文件，把参数挪进自己的 spec 模块，再按参考图调色。

用法 A（库）：
    import layered_material as LM          # 或 exec 本文件
    LM.build("stone", "M_Stone")           # kind ∈ LM.KINDS；返回 bpy 材质
    LM.build("wood", "M_Beam", axis="X", k=0.9, col=(0.12, 0.09, 0.07))   # 关键字 = 覆盖默认参数
用法 B（无头色板自检）：
    blender --background --factory-startup --python layered_material.py -- --swatch out.png
    → 每种材质一个倒角立方体，侧光 + Cycles 出一张色板图。

约定：
- 纹理坐标 = Object 空间（米）；尺度参数单位 1/m。对象需 apply scale，否则纹理随缩放变形。
- 逐件差异读 Object Info → Random：几何节点实例 / 复制件自动不同。
- 几何节点属性（可选；没有时 Attribute 节点输出 0，层自动失效）：
  plaster 读 streak（流痕）/ damp（返潮）；stone 读 top（朝上积灰）/ wear（棱磨 / 崩口）。
- 棱损用 AO inside=True 取反得到凸棱度：与网格密度无关，但只在 Cycles 有效。
"""
import sys
import os
import math
import types
import bpy

S = types.SimpleNamespace()
S.MAT_STREAK    = 0.9                 # 材质：流痕混入强度
S.MAT_DAMP      = 0.85                # 返潮混入强度
S.MAT_WEAR      = 1.0                 # 石棱磨亮强度
S.MAT_DUST      = 0.35                # 顶面积灰强度（R8：0.6 盖住逐块色差，回调）
S.DUST_COL      = (0.30, 0.25, 0.18)  # 积灰色（偏土黄，与青灰石面拉开）
S.PLASTER_STREAK_K = 0.42             # 流痕处颜色 = 灰皮色 × K
S.PLASTER_DAMP_K   = 0.50             # 返潮处颜色 = 灰皮色 × K（并降粗糙度）
S.STONE_WEAR_K     = 2.1              # 磨亮处颜色 = 石色 × K
S.MT_AO_SAMPLES = 8

MT_TILE = dict(                      # 青瓦（灰陶，还原焰）：逐片色差、窑变斑、细孔、缝脏、朝上地衣
    col=(0.058, 0.062, 0.066), warm=(0.078, 0.066, 0.056), warm_mix=0.55, inst_var=0.45,
    mottle_scale=2.2, mottle_k=0.30, pore_scale=220.0, bump=0.30,
    lichen_col=(0.34, 0.35, 0.29), lichen_scale=5.0, lichen_th=(0.60, 0.70), lichen_up=(0.35, 0.8),
    rough=(0.72, 0.93), ao_dist=0.12, ao_k=0.75, edge_dist=0.012, edge_k=0.35)
MT_RIDGE = dict(MT_TILE, col=(0.072, 0.075, 0.078), warm=(0.085, 0.078, 0.070), inst_var=0.10,
                mottle_scale=0.9, lichen_th=(0.56, 0.68))                     # 脊筒 / 当沟 / 压顶：青砖
MT_BED = dict(MT_TILE, col=(0.095, 0.090, 0.080), warm=(0.11, 0.10, 0.085), inst_var=0.0,
              lichen_th=(0.5, 0.62), rough=(0.85, 0.97))                      # 瓦下灰泥（掺灰泥）
MT_WOOD = dict(                      # 老木（不施彩，风化）：年轮、顺纹纤维、干裂、朝上银灰、缝脏、棱磨
    col=(0.115, 0.086, 0.064), late=(0.050, 0.036, 0.027), silver=(0.20, 0.19, 0.175), silver_k=0.55,
    ring_scale=16.0, ring_dist=4.0, ring_w=0.35, grain_k=0.45, fiber=(1.0, 45.0, 45.0), fiber_scale=2.5,
    crack_stretch=(0.12, 1.0, 1.0), crack_scale=9.0, crack_w=0.030, crack_mask=(0.52, 0.64), inst_var=0.30,
    bump=0.45, rough=(0.62, 0.90), ao_dist=0.18, ao_k=0.85, edge_dist=0.010, edge_k=0.45)
# 各木件：(材质名, 顺纹轴, 颜色倍率)；顺纹轴取件的长向（局部坐标）
MT_LACQUER = dict(                   # 朱漆：日晒褪色、竖向雨痕、龟裂、剥落露灰白地仗、棱角先掉
    col=(0.25, 0.036, 0.024), faded=(0.36, 0.10, 0.075), fade_scale=0.7, fade_k=0.85,
    streak_scale=(9.0, 9.0, 0.35), streak_k=0.55, craq_scale=38.0, craq_w=0.025, craq_k=0.45,
    ground=(0.34, 0.31, 0.27), chip_scale=7.0, chip_th=(0.66, 0.70), chip_edge=0.30,
    bump=0.35, rough=(0.38, 0.72), ao_dist=0.25, ao_k=0.7, edge_dist=0.015)
MT_FRAME = dict(MT_LACQUER, col=(0.20, 0.035, 0.025), faded=(0.27, 0.085, 0.065), chip_th=(0.60, 0.65))  # 普拍枋 / 阑额：暗朱
MT_PLASTER = dict(                   # 红灰墙心（石灰掺红土）：刷浆斑驳、起皮露白灰、砂粒、发丝裂；流痕 / 返潮来自 GN 属性
    col=(0.34, 0.098, 0.066), wash_scale=(1.2, 9.0), wash_k=0.22,
    flake_col=(0.50, 0.45, 0.38), flake_scale=1.8, flake_th=(0.67, 0.69),
    sand_scale=500.0, crack_scale=3.0, crack_w=0.010, crack_wobble=(2.5, 0.12), crack_mask=(0.52, 0.62), crack_dark=0.55, bump=0.25, rough=(0.78, 0.95), ao_dist=0.3, ao_k=0.6)
MT_STONE = dict(                     # 青石（R8b 重做为岩石）：层理色带 + 方解石脉 + 晶粒 + 溶蚀麻坑 + 双层凹凸 + 凹处包浆 + 雨痕 / 地衣
    ramp=((0.0, (0.045, 0.052, 0.058)), (0.35, (0.100, 0.107, 0.112)), (0.62, (0.165, 0.167, 0.163)), (1.0, (0.240, 0.226, 0.200))),
    base_scale=2.4, base_dist=0.7, inst_shift=0.22, mottle_scale=9.0, mottle_k=0.32,                       # 底色噪波 → 色带；逐块沿色带平移
    warm=(0.215, 0.195, 0.165), warm_mix=0.35,
    strata_stretch=(0.5, 0.5, 6.0), strata_scale=1.2, strata_k=0.10,    # 层理：z 向压密的噪波 = 不规则水平纹层（R8b：Wave 条带太像斑马纹，弃用）
    vein_scale=3.5, vein_th=(0.93, 0.975), vein_mask=(0.55, 0.7), vein_col=(0.42, 0.42, 0.40),
    grain_scale=170.0, grain_k=0.10, fleck_scale=420.0, fleck_th=0.985, fleck_k=0.35, fleck_col=(0.30, 0.30, 0.29),
    cav_scale=7.0, cav_th=(0.64, 0.70), cav_dark=0.6,                   # 风化蚀坑：高细节噪波阈值 = 不规则（R8b：Voronoi 圆坑像混凝土气孔，弃用）
    rust_scale=(2.0, 2.0, 0.6), rust_th=(0.66, 0.80), rust_col=(0.20, 0.13, 0.07), rust_k=0.55,
    fis_scale=2.2, fis_w=0.004, fis_mask=(0.60, 0.68), fis_dark=0.55,                   # 发丝裂隙
    relief_scale=6.0, relief_dist=0.005, relief_k=1.0, micro_scale=60.0, micro_dist=0.0008, micro_k=0.7,
    cavity_k=0.45,                                                        # 凹凸高度低处压暗（包浆积垢）
    rain_scale=(7.0, 7.0, 0.5), rain_th=(0.55, 0.75), rain_k=0.55,       # 立面黑色雨痕
    lichen_scale=7.0, lichen_r=(0.18, 0.28), lichen_mask=(0.62, 0.72), lichen_col=(0.36, 0.37, 0.33),
    dirt_col=(0.085, 0.080, 0.060), dirt_h=(0.0, 0.45), dirt_k=0.7,
    rough=(0.55, 0.92), ao_dist=0.10, ao_k=0.8, edge_dist=0.010, edge_k=0.30)
MT_STONE_DARK = dict(MT_STONE, ramp=((0.0, (0.045, 0.050, 0.054)), (0.4, (0.080, 0.085, 0.088)), (0.7, (0.115, 0.116, 0.113)), (1.0, (0.150, 0.142, 0.130))),
                     inst_shift=0.0, warm_mix=0.0)
MT_GROUND = dict(                    # 场地：夯土 + 碎石，近台基处更湿暗
    col=(0.165, 0.128, 0.088), col2=(0.105, 0.082, 0.058), mottle_scale=0.35, mottle_k=0.7,
    gravel_scale=55.0, gravel_r=0.32, gravel_mask=(0.52, 0.72), gravel_col=(0.20, 0.185, 0.16),
    fine_scale=260.0, bump=0.6, rough=(0.80, 0.97), wet_r=(4.5, 9.0), wet_k=0.35)
MT_MOSS = dict(col_a=(0.035, 0.070, 0.015), col_b=(0.11, 0.12, 0.030), scale=60.0, rough=0.85, sss=0.15)






# ---------------------------------------------------------------- 节点工具与配方（与项目 build/v2/materials.py 同源）
class SB:
    """着色节点小工具：输入既可以是常量也可以是 socket。"""

    def __init__(self, name, preview):
        m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        m.use_nodes = True
        m.diffuse_color = tuple(preview) + (1.0,)
        self.m = m
        self.nt = m.node_tree
        self.nt.nodes.clear()
        self.out = self.n("ShaderNodeOutputMaterial")
        self.bs = self.n("ShaderNodeBsdfPrincipled")
        self.nt.links.new(self.bs.outputs["BSDF"], self.out.inputs["Surface"])
        self._tc = self._rand = self._geo = None

    def n(self, kind, **props):
        nd = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(nd, k, v)
        return nd

    def _in(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.nt.links.new(v, sock)
        elif isinstance(v, (tuple, list)):
            dv = sock.default_value
            if len(dv) == 4 and len(v) == 3:
                v = tuple(v) + (1.0,)
            sock.default_value = v
        else:
            sock.default_value = v

    # ---- 基础量
    def rand(self):
        if self._rand is None:
            self._rand = self.n("ShaderNodeObjectInfo").outputs["Random"]
        return self._rand

    def geo(self, out):
        if self._geo is None:
            self._geo = self.n("ShaderNodeNewGeometry")
        return self._geo.outputs[out]

    def coord(self, stretch=(1.0, 1.0, 1.0), inst=True):
        """Object 坐标（m）；inst=True 时按 Random 平移，使每个实例纹理不同。"""
        if self._tc is None:
            self._tc = self.n("ShaderNodeTexCoord")
        v = self._tc.outputs["Object"]
        if inst:
            off = self.n("ShaderNodeVectorMath", operation="SCALE")
            off.inputs[0].default_value = (37.1, 53.3, 71.7)
            self._in(off.inputs["Scale"], self.rand())
            add = self.n("ShaderNodeVectorMath", operation="ADD")
            self._in(add.inputs[0], v)
            self._in(add.inputs[1], off.outputs[0])
            v = add.outputs[0]
        if tuple(stretch) != (1.0, 1.0, 1.0):
            mp = self.n("ShaderNodeMapping")
            self._in(mp.inputs["Vector"], v)
            mp.inputs["Scale"].default_value = stretch
            v = mp.outputs[0]
        return v

    def vscale(self, v, s):
        nd = self.n("ShaderNodeVectorMath", operation="MULTIPLY")
        self._in(nd.inputs[0], v)
        nd.inputs[1].default_value = s
        return nd.outputs[0]

    # ---- 纹理
    def noise(self, v, scale, detail=4.0, rough=0.55, dist=0.0):
        nd = self.n("ShaderNodeTexNoise")
        self._in(nd.inputs["Vector"], v)
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Detail"].default_value = detail
        nd.inputs["Roughness"].default_value = rough
        nd.inputs["Distortion"].default_value = dist
        return nd.outputs["Fac"]

    def voronoi(self, v, scale, feature="F1", rand=1.0, out="Distance"):
        nd = self.n("ShaderNodeTexVoronoi", feature=feature)
        self._in(nd.inputs["Vector"], v)
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Randomness"].default_value = rand
        return nd.outputs[out]

    def wave(self, v, kind, axis, scale, dist, detail=3.0):
        nd = self.n("ShaderNodeTexWave", wave_type=kind)
        if kind == "RINGS":
            nd.rings_direction = axis
        else:
            nd.bands_direction = axis
        self._in(nd.inputs["Vector"], v)
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Distortion"].default_value = dist
        nd.inputs["Detail"].default_value = detail
        return nd.outputs["Fac"]

    # ---- 运算
    def math(self, op, a, b=None, c=None, clamp=False):
        nd = self.n("ShaderNodeMath", operation=op, use_clamp=clamp)
        self._in(nd.inputs[0], a)
        if b is not None:
            self._in(nd.inputs[1], b)
        if c is not None:
            self._in(nd.inputs[2], c)
        elif op == "MULTIPLY_ADD":
            nd.inputs[2].default_value = 0.0
        return nd.outputs[0]

    def mr(self, v, a, b, c=0.0, d=1.0, smooth=False):
        nd = self.n("ShaderNodeMapRange", clamp=True)
        if smooth:
            nd.interpolation_type = "SMOOTHSTEP"
        self._in(nd.inputs["Value"], v)
        nd.inputs["From Min"].default_value = a
        nd.inputs["From Max"].default_value = b
        self._in(nd.inputs["To Min"], c)
        self._in(nd.inputs["To Max"], d)
        return nd.outputs["Result"]

    def ramp(self, fac, stops):
        nd = self.n("ShaderNodeValToRGB")
        self._in(nd.inputs["Fac"], fac)
        els = nd.color_ramp.elements
        while len(els) < len(stops):
            els.new(0.5)
        for e, (pos, col) in zip(els, stops):
            e.position = pos
            e.color = tuple(col) + (1.0,)
        return nd.outputs["Color"]

    def sep(self, v):
        nd = self.n("ShaderNodeSeparateXYZ")
        self._in(nd.inputs[0], v)
        return nd.outputs

    def noise_t(self, v, scale, kind, detail=6.0, rough=0.6, lac=2.0):
        nd = self.n("ShaderNodeTexNoise", noise_type=kind)
        self._in(nd.inputs["Vector"], v)
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Detail"].default_value = detail
        nd.inputs["Roughness"].default_value = rough
        nd.inputs["Lacunarity"].default_value = lac
        return nd.outputs["Fac"]

    def mix(self, fac, a, b, blend="MIX"):
        nd = self.n("ShaderNodeMix", data_type="RGBA", blend_type=blend)
        self._in(nd.inputs[0], fac)
        self._in(nd.inputs[6], a)
        self._in(nd.inputs[7], b)
        return nd.outputs[2]

    def cscale(self, col, s):
        """颜色 × 标量（s 可为 socket）。"""
        nd = self.n("ShaderNodeVectorMath", operation="SCALE")
        self._in(nd.inputs[0], col)
        self._in(nd.inputs["Scale"], s)
        return nd.outputs[0]

    def attr(self, name):
        nd = self.n("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name=name)
        return nd.outputs["Fac"]

    def ao(self, dist, inside=False):
        nd = self.n("ShaderNodeAmbientOcclusion", samples=S.MT_AO_SAMPLES, inside=inside)
        nd.inputs["Distance"].default_value = dist
        return nd.outputs["AO"]

    def up(self):
        sp = self.n("ShaderNodeSeparateXYZ")
        self._in(sp.inputs[0], self.geo("Normal"))
        return sp.outputs["Z"]

    def world_z(self):
        sp = self.n("ShaderNodeSeparateXYZ")
        self._in(sp.inputs[0], self.geo("Position"))
        return sp.outputs["Z"]

    def bump(self, h, strength, dist=0.002):
        nd = self.n("ShaderNodeBump")
        self._in(nd.inputs["Height"], h)
        nd.inputs["Strength"].default_value = strength
        nd.inputs["Distance"].default_value = dist
        return nd.outputs["Normal"]

    def finish(self, col, rough, normal=None, **extra):
        self._in(self.bs.inputs["Base Color"], col)
        self._in(self.bs.inputs["Roughness"], rough)
        if normal is not None:
            self._in(self.bs.inputs["Normal"], normal)
        for k, v in extra.items():
            self._in(self.bs.inputs[k], v)
        return self.m

    # ---- 共用风化层
    def inst_tint(self, col, warm, warm_mix, var):
        """逐件：冷暖偏移 + 明度 ±var/2。"""
        r = self.rand()
        c = self.mix(self.mr(r, 0.0, 1.0, 0.0, warm_mix), col, warm)
        if var > 0:
            r2 = self.math("FRACT", self.math("MULTIPLY", r, 7.13))
            c = self.cscale(c, self.mr(r2, 0.0, 1.0, 1.0 - var / 2, 1.0 + var / 2))
        return c

    def grime(self, col, P):
        """缝脏：AO 外向，凹处压暗（AO 低 → 暗）。"""
        g = self.math("MULTIPLY", self.math("SUBTRACT", 1.0, self.ao(P["ao_dist"])), P["ao_k"], clamp=True)
        return self.mix(g, col, self.cscale(col, 0.3))

    def edge(self, P):
        """凸棱度 0..1。AO inside 向体内打射线：平面处射线穿到远端 = 1（无遮挡），
        棱角处很快碰到相邻面 = 低值 → 取反。"""
        return self.mr(self.ao(P["edge_dist"], inside=True), P.get("edge_ao", (0.97, 0.6))[0], P.get("edge_ao", (0.97, 0.6))[1], 0.0, 1.0, smooth=True)


# ================================================================ 各材质族
def tile(name, P):
    """青瓦 / 青砖。"""
    b = SB(name, P["col"])
    v = b.coord()
    c = b.inst_tint(P["col"], P["warm"], P["warm_mix"], P["inst_var"])
    mot = b.noise(v, P["mottle_scale"], 5.0, 0.6)
    c = b.cscale(c, b.mr(mot, 0.3, 0.7, 1.0 - P["mottle_k"], 1.0 + P["mottle_k"]))
    pore = b.noise(v, P["pore_scale"], 2.0, 0.5)
    lich_n = b.noise(v, P["lichen_scale"], 6.0, 0.65, 0.3)
    lich = b.math("MULTIPLY", b.mr(lich_n, P["lichen_th"][0], P["lichen_th"][1], 0, 1, True),
                  b.mr(b.up(), P["lichen_up"][0], P["lichen_up"][1]))
    c = b.grime(c, P)
    e = b.edge(P)
    c = b.mix(b.math("MULTIPLY", e, P["edge_k"]), c, b.cscale(c, 1.9))          # 棱角磨浅
    c = b.mix(lich, c, P["lichen_col"])
    rough = b.math("MAXIMUM", b.mr(pore, 0.3, 0.7, P["rough"][0], P["rough"][1]), b.math("MULTIPLY", lich, 0.95))
    h = b.math("ADD", b.math("MULTIPLY", pore, 0.6), b.math("MULTIPLY", lich, 0.8))
    h = b.math("ADD", h, b.math("MULTIPLY", mot, 0.5))
    return b.finish(c, rough, b.bump(h, P["bump"], 0.003))


def wood(name, P, axis, k):
    """老木：顺纹轴 axis（局部），颜色倍率 k。"""
    col = [x * k for x in P["col"]]
    late = [x * k for x in P["late"]]
    b = SB(name, col)
    ax = "XYZ".index(axis)

    def along(s_al, s_ac):
        s = [s_ac] * 3
        s[ax] = s_al
        return tuple(s)

    v = b.coord()
    rings = b.wave(v, "RINGS", axis, P["ring_scale"], P["ring_dist"], 4.0)
    fib = b.noise(b.coord(along(P["fiber"][0], P["fiber"][1])), P["fiber_scale"], 6.0, 0.6)
    g = b.math("ADD", b.math("MULTIPLY", rings, P["ring_w"]), b.math("MULTIPLY", fib, 1.0 - P["ring_w"]))
    c = b.mix(b.mr(g, 0.25, 0.75, 1.0 - P["grain_k"], 1.0, True), late, col)
    c = b.cscale(c, b.mr(b.rand(), 0.0, 1.0, 1.0 - P["inst_var"] / 2, 1.0 + P["inst_var"] / 2))
    # 风化：朝上与暴露面泛银灰（大尺度噪波打碎）
    big = b.noise(v, 1.1, 4.0, 0.6)
    sil = b.math("MULTIPLY", b.mr(b.up(), -0.2, 0.9, 0.15, 1.0), b.mr(big, 0.35, 0.65, 0.2, 1.0))
    c = b.mix(b.math("MULTIPLY", sil, P["silver_k"]), c, [x * (0.6 + 0.4 * k) for x in P["silver"]])
    # 干裂：拉长 Voronoi 的边线
    cr_d = b.voronoi(b.coord(along(P["crack_stretch"][0], P["crack_stretch"][1])), P["crack_scale"], "DISTANCE_TO_EDGE")
    crack = b.math("MULTIPLY", b.mr(cr_d, 0.0, P["crack_w"], 1.0, 0.0), b.mr(big, P["crack_mask"][0], P["crack_mask"][1]))
    c = b.mix(crack, c, b.cscale(c, 0.25))
    c = b.grime(c, P)
    e = b.edge(P)
    c = b.mix(b.math("MULTIPLY", e, P["edge_k"]), c, b.cscale(c, 1.7))
    rough = b.math("ADD", b.mr(fib, 0.3, 0.7, P["rough"][0], P["rough"][1]), b.math("MULTIPLY", crack, 0.1), clamp=True)
    h = b.math("SUBTRACT", b.math("ADD", b.math("MULTIPLY", fib, 0.5), b.math("MULTIPLY", rings, 0.25)), crack)
    return b.finish(c, rough, b.bump(h, P["bump"], 0.002))


def lacquer(name, P):
    """朱漆：褪色 → 雨痕 → 龟裂 → 剥落露地仗（棱角先掉）。"""
    b = SB(name, P["col"])
    v = b.coord(inst=False)
    fade = b.noise(v, P["fade_scale"], 5.0, 0.6)
    c = b.mix(b.mr(fade, 0.35, 0.75, 0.0, P["fade_k"], True), P["col"], P["faded"])
    st = b.noise(b.vscale(v, P["streak_scale"]), 1.0, 4.0, 0.55)
    c = b.mix(b.mr(st, 0.5, 0.75, 0.0, P["streak_k"]), c, b.cscale(c, 0.55))
    cq = b.voronoi(v, P["craq_scale"], "DISTANCE_TO_EDGE")
    craq = b.mr(cq, 0.0, P["craq_w"], 1.0, 0.0)
    c = b.mix(b.math("MULTIPLY", craq, P["craq_k"]), c, b.cscale(c, 0.4))
    e = b.edge(P)
    chn = b.noise(v, P["chip_scale"], 8.0, 0.7)
    chip_f = b.math("ADD", chn, b.math("MULTIPLY", e, P["chip_edge"]))
    chip = b.mr(chip_f, P["chip_th"][0], P["chip_th"][1], 0, 1)
    gr = b.cscale(P["ground"], b.mr(b.noise(v, 30.0, 3.0), 0.3, 0.7, 0.75, 1.1))
    c = b.mix(chip, c, gr)
    c = b.grime(c, P)
    rough = b.mr(fade, 0.3, 0.8, P["rough"][0], P["rough"][1])
    rough = b.math("MAXIMUM", rough, b.math("MULTIPLY", chip, 0.92))
    h = b.math("SUBTRACT", b.math("SUBTRACT", 1.0, b.math("MULTIPLY", chip, 1.0)), b.math("MULTIPLY", craq, 0.3))
    return b.finish(c, rough, b.bump(h, P["bump"], 0.0015), **{"Coat Weight": b.mr(chip, 0, 1, 0.25, 0.0)})


def plaster(name, P):
    """红灰墙心：刷浆斑驳 + 起皮露白灰 + 砂粒 + 发丝裂；streak / damp 来自 GN。"""
    b = SB(name, P["col"])
    v = b.coord(inst=False)
    w1 = b.noise(v, P["wash_scale"][0], 4.0, 0.6)
    w2 = b.noise(v, P["wash_scale"][1], 3.0, 0.5)
    k = P["wash_k"]
    c = b.cscale(P["col"], b.mr(b.math("ADD", w1, b.math("MULTIPLY", w2, 0.4)), 0.4, 1.0, 1.0 - k, 1.0 + k))
    fl = b.mr(b.noise(v, P["flake_scale"], 7.0, 0.7), P["flake_th"][0], P["flake_th"][1], 0, 1)
    c = b.mix(fl, c, P["flake_col"])
    wob = b.n("ShaderNodeVectorMath", operation="ADD")                       # 发丝裂：坐标先被噪波扭曲，避免规则多边形网
    b._in(wob.inputs[0], v)
    wn = b.n("ShaderNodeTexNoise")
    b._in(wn.inputs["Vector"], v)
    wn.inputs["Scale"].default_value = P["crack_wobble"][0]
    wn.inputs["Detail"].default_value = 5.0
    sc_ = b.n("ShaderNodeVectorMath", operation="SCALE")
    b._in(sc_.inputs[0], wn.outputs["Color"])
    sc_.inputs["Scale"].default_value = P["crack_wobble"][1]
    b._in(wob.inputs[1], sc_.outputs[0])
    crd = b.voronoi(wob.outputs[0], P["crack_scale"], "DISTANCE_TO_EDGE")
    crack = b.math("MULTIPLY", b.mr(crd, 0.0, P["crack_w"], 1.0, 0.0), b.mr(w1, P["crack_mask"][0], P["crack_mask"][1]))
    c = b.mix(crack, c, b.cscale(c, P["crack_dark"]))
    streak, damp = b.attr("streak"), b.attr("damp")
    c = b.mix(b.math("MULTIPLY", streak, S.MAT_STREAK, clamp=True), c, b.cscale(c, S.PLASTER_STREAK_K))
    c = b.mix(b.math("MULTIPLY", damp, S.MAT_DAMP, clamp=True), c, b.cscale(c, S.PLASTER_DAMP_K))
    c = b.grime(c, P)
    sand = b.noise(v, P["sand_scale"], 2.0, 0.5)
    rough = b.mr(sand, 0.3, 0.7, P["rough"][0], P["rough"][1])
    rough = b.math("MULTIPLY_ADD", damp, -0.25, rough)
    h = b.math("ADD", b.math("MULTIPLY", sand, 0.4), b.math("MULTIPLY", fl, -0.8))
    h = b.math("SUBTRACT", h, crack)
    return b.finish(c, rough, b.bump(h, P["bump"], 0.002))


def stone(name, P):
    """青石 = 岩石（R8b）。成因分层：
    底色（扭曲 fbm → 4 段色带，逐块沿色带平移）→ 层理（沿 Z 扭曲条带）→ 方解石白脉（ridged 噪波阈值，局部出现）
    → 晶粒（Voronoi 胞随机明度 + 少量白斑）→ 溶蚀麻坑（Voronoi F1 小圆，局部）→ 剁斧细道
    → 凹凸 = 大起伏 + 麻坑 + 晶粒（两级 Bump 串联）→ 凹处包浆压暗 → 立面黑雨痕 → 地衣圆斑 → 积灰 / 棱磨（GN 属性）
    → 地脚泥渍 → 缝脏 AO。"""
    b = SB(name, P["ramp"][2][1])
    v = b.coord()
    r = b.rand()
    # 底色
    bn = b.noise(v, P["base_scale"], 10.0, 0.62, P["base_dist"])
    sh = b.mr(r, 0.0, 1.0, -P["inst_shift"], P["inst_shift"])
    c = b.ramp(b.math("ADD", bn, sh, clamp=True), P["ramp"])
    mo = b.noise(v, P["mottle_scale"], 8.0, 0.65, 0.5)                       # 中尺度斑驳（~10 cm）
    c = b.cscale(c, b.mr(mo, 0.3, 0.7, 1.0 - P["mottle_k"], 1.0 + P["mottle_k"]))
    if P["warm_mix"] > 0:
        r2 = b.math("FRACT", b.math("MULTIPLY", r, 5.31))
        c = b.mix(b.math("MULTIPLY", r2, P["warm_mix"]), c, P["warm"])
    # 层理
    st = b.noise(b.vscale(v, P["strata_stretch"]), P["strata_scale"], 6.0, 0.6, 0.4)
    c = b.cscale(c, b.mr(st, 0.3, 0.7, 1.0 - P["strata_k"], 1.0 + P["strata_k"]))
    # 方解石脉
    vr = b.noise_t(v, P["vein_scale"], "RIDGED_MULTIFRACTAL", 6.0, 0.55, 2.3)
    vein = b.math("MULTIPLY", b.mr(vr, P["vein_th"][0], P["vein_th"][1], 0, 1, True),
                  b.mr(b.noise(v, 0.9, 3.0), P["vein_mask"][0], P["vein_mask"][1]))
    c = b.mix(vein, c, P["vein_col"])
    # 晶粒
    gc = b.voronoi(v, P["grain_scale"], "F1", 1.0, out="Color")
    gx = b.sep(gc)[0]
    c = b.cscale(c, b.mr(gx, 0.0, 1.0, 1.0 - P["grain_k"], 1.0 + P["grain_k"]))
    fc = b.voronoi(v, P["fleck_scale"], "F1", 1.0, out="Color")              # 白斑：更细一级的胞，极少数点亮
    fleck = b.mr(b.sep(fc)[1], P["fleck_th"], 1.0, 0, 1)
    c = b.mix(b.math("MULTIPLY", fleck, P["fleck_k"]), c, P["fleck_col"])
    # 风化蚀坑：高细节噪波的高值区 = 不规则凹陷
    cn = b.noise(v, P["cav_scale"], 14.0, 0.72, 0.2)
    pit = b.mr(cn, P["cav_th"][0], P["cav_th"][1], 0, 1, True)
    c = b.mix(pit, c, b.cscale(c, P["cav_dark"]))
    # 铁锈渍：竖向拉长、局部
    rs = b.noise(b.vscale(v, P["rust_scale"]), 1.0, 6.0, 0.6, 0.3)
    rust = b.math("MULTIPLY", b.mr(rs, P["rust_th"][0], P["rust_th"][1], 0, 1, True), P["rust_k"])
    c = b.mix(rust, c, P["rust_col"], "MULTIPLY")
    c = b.mix(b.math("MULTIPLY", rust, 0.5), c, P["rust_col"])
    # 发丝裂隙：大胞 Voronoi 边线，局部出现
    fd = b.voronoi(v, P["fis_scale"], "DISTANCE_TO_EDGE")
    fis = b.math("MULTIPLY", b.mr(fd, 0.0, P["fis_w"], 1.0, 0.0), b.mr(b.noise(v, 1.3, 4.0), P["fis_mask"][0], P["fis_mask"][1]))
    c = b.mix(fis, c, b.cscale(c, P["fis_dark"]))
    # 凹凸高度
    rel = b.noise(v, P["relief_scale"], 14.0, 0.68, 0.3)
    h_macro = b.math("SUBTRACT", b.math("SUBTRACT", rel, b.math("MULTIPLY", pit, 0.7)), b.math("MULTIPLY", fis, 0.6))
    mic = b.noise(v, P["micro_scale"], 8.0, 0.7)
    h_micro = b.math("ADD", b.math("MULTIPLY", gx, 0.5), mic)
    # 包浆：高度低处暗
    c = b.mix(b.math("MULTIPLY", b.mr(h_macro, 0.55, 0.25, 0, 1, True), P["cavity_k"]), c, b.cscale(c, 0.45))
    # 立面雨痕（只在竖直面：1 - |nz|）
    nz = b.math("ABSOLUTE", b.up())
    rn = b.noise(b.vscale(v, P["rain_scale"]), 1.0, 4.0, 0.55)
    rain = b.math("MULTIPLY", b.mr(rn, P["rain_th"][0], P["rain_th"][1], 0, 1, True), b.math("SUBTRACT", 1.0, nz))
    c = b.mix(b.math("MULTIPLY", rain, P["rain_k"]), c, b.cscale(c, 0.35))
    # 地衣圆斑
    ld = b.voronoi(v, P["lichen_scale"], "F1", 1.0)
    lich = b.math("MULTIPLY", b.mr(ld, P["lichen_r"][1], P["lichen_r"][0], 0, 1, True),
                  b.mr(b.noise(v, 2.2, 3.0), P["lichen_mask"][0], P["lichen_mask"][1]))
    c = b.mix(b.math("MULTIPLY", lich, 0.85), c, P["lichen_col"])
    # GN 属性：积灰 / 棱磨 + 崩口新茬
    c = b.mix(b.math("MULTIPLY", b.attr("top"), S.MAT_DUST, clamp=True), c, S.DUST_COL)
    e = b.math("MAXIMUM", b.math("MULTIPLY", b.attr("wear"), S.MAT_WEAR, clamp=True),
               b.math("MULTIPLY", b.edge(P), P["edge_k"]))
    c = b.mix(b.math("MULTIPLY", e, 0.7), c, b.cscale(c, S.STONE_WEAR_K))
    # 地脚泥渍
    z = b.world_z()
    dn = b.noise(v, 3.0, 4.0, 0.6)
    dirt = b.math("MULTIPLY", b.mr(b.math("ADD", z, b.math("MULTIPLY", dn, 0.25)), P["dirt_h"][1], P["dirt_h"][0]), P["dirt_k"])
    c = b.mix(dirt, c, P["dirt_col"])
    c = b.grime(c, P)
    # 粗糙度：晶粒起伏、麻坑 / 地衣更糙、棱磨更光
    rough = b.mr(gx, 0.0, 1.0, P["rough"][0], P["rough"][1])
    rough = b.math("MAXIMUM", rough, b.math("MAXIMUM", pit, lich))
    rough = b.math("SUBTRACT", rough, b.math("MULTIPLY", e, 0.2))
    n1 = b.n("ShaderNodeBump")
    b._in(n1.inputs["Height"], h_macro)
    n1.inputs["Strength"].default_value = P["relief_k"]
    n1.inputs["Distance"].default_value = P["relief_dist"]
    n2 = b.n("ShaderNodeBump")
    b._in(n2.inputs["Height"], h_micro)
    n2.inputs["Strength"].default_value = P["micro_k"]
    n2.inputs["Distance"].default_value = P["micro_dist"]
    b._in(n2.inputs["Normal"], n1.outputs["Normal"])
    return b.finish(c, rough, n2.outputs["Normal"])


def ground(name, P):
    """场地：夯土底（两色大斑）+ 碎石（Voronoi 胞，局部成片）+ 细砂凹凸；离台基越近越湿暗。"""
    b = SB(name, P["col"])
    v = b.coord(inst=False)
    mo = b.noise(v, P["mottle_scale"], 6.0, 0.6, 0.3)
    c = b.mix(b.mr(mo, 0.35, 0.7, 0, P["mottle_k"], True), P["col"], P["col2"])
    gd = b.voronoi(v, P["gravel_scale"], "F1", 1.0)
    gcol = b.voronoi(v, P["gravel_scale"], "F1", 1.0, out="Color")
    gm = b.math("MULTIPLY", b.mr(gd, P["gravel_r"], P["gravel_r"] * 0.7, 0, 1, True),
                b.mr(b.noise(v, 0.8, 4.0), P["gravel_mask"][0], P["gravel_mask"][1]))
    gc = b.cscale(P["gravel_col"], b.mr(b.sep(gcol)[0], 0, 1, 0.6, 1.4))
    c = b.mix(gm, c, gc)
    fine = b.noise(v, P["fine_scale"], 2.0, 0.5)
    c = b.cscale(c, b.mr(fine, 0.3, 0.7, 0.85, 1.15))
    rl = b.n("ShaderNodeVectorMath", operation="LENGTH")
    b._in(rl.inputs[0], b.geo("Position"))
    wet = b.math("MULTIPLY", b.mr(rl.outputs["Value"], P["wet_r"][0], P["wet_r"][1], 1, 0, True), P["wet_k"])
    c = b.mix(wet, c, b.cscale(c, 0.6))
    c = b.grime(c, dict(ao_dist=0.4, ao_k=0.6))
    rough = b.math("SUBTRACT", b.mr(fine, 0.3, 0.7, P["rough"][0], P["rough"][1]), b.math("MULTIPLY", wet, 0.3))
    h = b.math("ADD", b.math("MULTIPLY", gm, 1.0), b.math("MULTIPLY", fine, 0.3))
    h = b.math("ADD", h, b.math("MULTIPLY", mo, 0.4))
    return b.finish(c, rough, b.bump(h, P["bump"], 0.01))


def moss(name, P):
    b = SB(name, P["col_a"])
    v = b.coord()
    n1 = b.noise(v, P["scale"], 4.0, 0.6)
    c = b.mix(b.mr(n1, 0.3, 0.7, 0, 1, True), P["col_a"], P["col_b"])
    c = b.mix(b.mr(b.rand(), 0, 1, 0, 0.5), c, P["col_b"])
    return b.finish(c, P["rough"], b.bump(n1, 0.6, 0.002),
                    **{"Subsurface Weight": P["sss"], "Subsurface Radius": (0.004, 0.006, 0.002)})



PRESETS = dict(tile=MT_TILE, ridge=MT_RIDGE, bed=MT_BED, wood=MT_WOOD, lacquer=MT_LACQUER, frame=MT_FRAME,
               plaster=MT_PLASTER, stone=MT_STONE, stone_dark=MT_STONE_DARK, ground=MT_GROUND, moss=MT_MOSS)
_RECIPE = dict(tile=lambda n, P: tile(n, P), ridge=lambda n, P: tile(n, P), bed=lambda n, P: tile(n, P),
               lacquer=lambda n, P: lacquer(n, P), frame=lambda n, P: lacquer(n, P), plaster=lambda n, P: plaster(n, P),
               stone=lambda n, P: stone(n, P), stone_dark=lambda n, P: stone(n, P), ground=lambda n, P: ground(n, P),
               moss=lambda n, P: moss(n, P))
KINDS = tuple(PRESETS)


def build(kind, name, axis="X", k=1.0, **overrides):
    """按预设建材质（同名材质会被清空重建）。wood 额外收 axis（顺纹轴，件的长向，局部）与 k（颜色倍率）。"""
    P = dict(PRESETS[kind], **overrides)
    if kind == "wood":
        return wood(name, P, axis, k)
    return _RECIPE[kind](name, P)


# ---------------------------------------------------------------- 色板自检
def swatch(out, kinds=KINDS, size=0.5, samples=64, res=(2000, 340)):
    """每种材质一个倒角立方体排成一行（Object 坐标单位 = 米，size 决定纹理看起来的尺度）。
    只在无头 / 空场景里用：会清掉场景里已有对象。"""
    from mathutils import Vector
    sc = bpy.context.scene
    for ob in list(sc.objects):
        bpy.data.objects.remove(ob)
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.render.resolution_x, sc.render.resolution_y = res
    gap = size * 1.45
    x0 = -gap * (len(kinds) - 1) / 2
    for i, kd in enumerate(kinds):
        bpy.ops.mesh.primitive_cube_add(size=size, location=(x0 + i * gap, 0, size / 2))
        ob = bpy.context.active_object
        ob.name = "SW_" + kd
        bv = ob.modifiers.new("Bevel", "BEVEL")
        bv.width, bv.segments = size * 0.03, 3
        ob.data.materials.append(build(kd, "SW_M_" + kd))

    def aim(ob, loc, target):
        ob.location = loc
        ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()

    cam = bpy.data.objects.new("SW_Cam", bpy.data.cameras.new("SW_Cam"))
    sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = gap * len(kinds) + size * 0.2
    aim(cam, (size * 1.2, -8.0, size * 3.2), (0, 0, size * 0.45))       # 略俯视、略偏右：看到正面 + 顶面 + 右侧面
    sc.camera = cam
    sun = bpy.data.objects.new("SW_Sun", bpy.data.lights.new("SW_Sun", "SUN"))
    sun.data.energy = 3.5
    sun.data.angle = math.radians(2.5)
    aim(sun, (-4.0, -5.0, 3.0), (0, 0, 0))                                # 左前上方侧光：凹凸可读
    sc.collection.objects.link(sun)
    if sc.world is None:
        sc.world = bpy.data.worlds.new("SW_World")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.35
    sc.render.filepath = os.path.abspath(out)
    bpy.ops.render.render(write_still=True)
    print("SWATCH", sc.render.filepath, "kinds=" + ",".join(kinds))


if __name__ == "__main__" and "--" in sys.argv:
    a = sys.argv[sys.argv.index("--") + 1:]
    if a[:1] == ["--swatch"] and len(a) >= 2:
        swatch(a[1])
