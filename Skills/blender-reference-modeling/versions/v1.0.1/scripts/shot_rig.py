"""同机位评估出图，不改用户的灯光 / 合成。

在 Blender 里运行：
    blender file.blend --background --python shot_rig.py -- shots.json out_dir [--keep-comp] [--no-sun]
或在会话里 exec，先设全局变量 SHOTS / OUT_DIR（可选 EVAL_SUN、COMP_OFF、SAMPLES、RES）。

shots.json：[{"name": "34", "loc": [x,y,z], "target": [x,y,z], "lens": 32}, ...]（米）
- 临时加一盏侧向日光（EVAL_SUN），看凹凸；临时关合成（COMP_OFF），看材质真实明度。
- 渲完一律删除临时相机 / 灯，恢复相机、采样、分辨率、合成开关（try/finally，报错也恢复）。
- 最后给用户看的图，用 --keep-comp --no-sun 再渲一张（即用户自己的灯光与调色）。
"""
import sys
import os
import json
import math
import bpy
from mathutils import Vector


def _cfg():
    g = globals()
    shots, out = g.get("SHOTS"), g.get("OUT_DIR")
    sun, comp_off = g.get("EVAL_SUN", True), g.get("COMP_OFF", True)
    if "--" in sys.argv:
        rest = sys.argv[sys.argv.index("--") + 1:]
        if "--keep-comp" in rest:
            comp_off = False
            rest.remove("--keep-comp")
        if "--no-sun" in rest:
            sun = False
            rest.remove("--no-sun")
        if len(rest) >= 2:
            shots = json.load(open(rest[0], encoding="utf-8"))
            out = rest[1]
    return shots, out, sun, comp_off, g.get("SAMPLES", 48), g.get("RES", (1200, 800))


def render_shots(shots, out, sun=True, comp_off=True, samples=48, res=(1200, 800)):
    sc = bpy.context.scene
    out = os.path.abspath(out)              # Blender 把相对路径按 blend 目录 / 盘根解析，先转绝对路径
    os.makedirs(out, exist_ok=True)
    saved = dict(camera=sc.camera, comp=sc.render.use_compositing, rx=sc.render.resolution_x, ry=sc.render.resolution_y,
                 path=sc.render.filepath, samples=getattr(sc.cycles, "samples", None) if hasattr(sc, "cycles") else None)
    cam = bpy.data.objects.new("TMP_ShotCam", bpy.data.cameras.new("TMP_ShotCam"))
    sc.collection.objects.link(cam)
    lamp = None
    written = []
    try:
        if sun:
            lamp = bpy.data.objects.new("TMP_EvalSun", bpy.data.lights.new("TMP_EvalSun", "SUN"))
            lamp.data.energy = 3.2
            lamp.data.angle = math.radians(2.5)
            lamp.data.color = (1.0, 0.96, 0.90)
            lamp.rotation_euler = (math.radians(58), 0.0, math.radians(125))   # 侧向偏低：凹凸可读
            sc.collection.objects.link(lamp)
        if comp_off:
            sc.render.use_compositing = False
        if saved["samples"] is not None:
            sc.cycles.samples = samples
        sc.render.resolution_x, sc.render.resolution_y = res
        for s in shots:
            cam.location = s["loc"]
            cam.rotation_euler = (Vector(s["target"]) - Vector(s["loc"])).to_track_quat("-Z", "Y").to_euler()
            cam.data.lens = s.get("lens", 35)
            sc.camera = cam
            sc.render.filepath = os.path.join(out, "shot_%s.png" % s["name"])
            bpy.ops.render.render(write_still=True)
            written.append(sc.render.filepath)
    finally:
        sc.camera = saved["camera"]
        sc.render.use_compositing = saved["comp"]
        sc.render.resolution_x, sc.render.resolution_y = saved["rx"], saved["ry"]
        sc.render.filepath = saved["path"]
        if saved["samples"] is not None:
            sc.cycles.samples = saved["samples"]
        cd = cam.data
        bpy.data.objects.remove(cam)
        bpy.data.cameras.remove(cd)
        if lamp is not None:
            ld = lamp.data
            bpy.data.objects.remove(lamp)
            bpy.data.lights.remove(ld)
    print("SHOTS %d" % len(written))
    for p in written:
        print("  " + p)
    return written


if __name__ == "__main__" or "SHOTS" in globals():
    shots, out, sun, comp_off, samples, res = _cfg()
    if not shots or not out:
        raise SystemExit("shot_rig: 需要 shots.json 与输出目录（或全局 SHOTS / OUT_DIR）")
    render_shots(shots, out, sun, comp_off, samples, res)
