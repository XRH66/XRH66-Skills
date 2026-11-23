# -*- coding: utf-8 -*-
"""
gate：流程闸门（方法层，领域无关）。每步必须留下交付物，下一步开工前先过闸；不过就停，并列出缺什么。
只查"做没做、有没有依据、字段自洽"，查不了"做得对不对"——那靠自检（selfcheck）里的粗模对比和用户过目。

    python gate.py init <项目目录>              写模板：ident.json / selfcheck.json / measure.json / accept.json（已有不覆盖）
    python gate.py <步> <项目目录>              步 ∈ ident / selfcheck / measure / accept；退出码 0 = 过，1 = 不过
    python gate.py all <项目目录>               依次检查，停在第一个不过的
    python gate.py --selftest

各步交付物（项目目录下 gate/ 子目录）。字段语义见 references/levels.md §1c（字段表）。
  ident.json      参考清点（classification 五类、views 视图表，至少一个 primary）、歧义清单（ambiguities）、构件树：
                  根节点 id = "root"、role = "assembly"（整件本身）；其余节点 parent = 它坐在 / 装在哪个件上；
                  每个节点：角色（support 支承 / part 件 / mount 件上的安装件 / detail 小件）、数量、初定级、证据图（参考局部放大，不能是原图）；
                  出独立几何的 L0–L3 节点再答八问：接口、对称、重复、轮廓、高度、装配、面型、跟不跟所坐的面（conform + 枚举理由）、
                  两向截面（curve / polyline + 段数）、做法是否沿用旧案例；
                  detail 与 L4 节点写去向 route；support 写外形来源 profile_source（拟合方法 + 用哪些视图）与是否交付 deliver
  selfcheck.json  先重跑 ident（改了树就要重过）；每个出几何的 L0–L3 节点逐项写核查结论（含"件上的件""支承"）、发现、改动；
                  粗模（L0 / L1）同视角对比图（不能是参考原图）；冷读结论（可选）；用户过目结论（ok / 跳过：理由）
  measure.json    每个形状参数的值与来源（参考上的哪处读数）；阶段 1 量到的数字可以先写进来
  accept.json     先重查 selfcheck（含用户过目）；同视角对比图（不能是参考原图）、剪影 IoU 与及格线（及格线的理由，看结果前定；
                  多视图可写 ious 逐视图）、逐件对照（每个 mount 节点和有特征的件：模型特写 + 参考局部放大（两张不同）+ 结论，
                  结论以"像 / 不像 / 缺失"开头）、差异清单（每条 {node, what, class, back_to, status}；每个"不像 / 缺失"的件都要有一条；
                  status ∈ 已修 / 用户接受，"待改"不过闸）、三项审计全部 pass
跳步：只有用户明说才行，且要在对应交付物里写 "skipped": "用户原话 / 理由"。
[实测：科幻叠板护臂——识别时漏了"面型 / 跟形 / 绕轴截面"，审计全过但做成了软的柱状环；本闸门由此而来。
 之后又漏了"件上的件"（铰座做成方盒切断叠板）和"支承体从参考拟合"（手臂用直管 / 写死解剖比例）→ 加 role、profile_source、逐件对照。
 冷读审查（金色护臂，多视图参考）：模板原文 / 关键词能蒙过闸、证据可用原图、id 可重复成环、没有视图表 → 改为结构化校验]
"""
import os
import sys
import json

ROLES = ("assembly", "support", "part", "mount", "detail")
SURFACES = ("curved", "hard", "mixed")
LEVELS = ("L0", "L1", "L2", "L3", "L4", "skip")
CONFORM_REASONS = ("thin", "soft", "small", "rigid")           # 跟形只允许 thin / soft / small；rigid = 自有截面
ROUTES = ("separate", "relief", "normal", "material", "asset")  # 独立网格 / 父件上的几何浮雕 / 法线 / 材质 / 外部资产
PROFILE_METHODS = ("silhouette_fit", "known_shape", "measured")  # 先验只当初值，不算外形来源
VIEW_USES = ("primary", "aux", "ignore")
CLASSES = ("主体", "插图", "标注", "干扰物", "存疑")
CHECKS = ("拆到底", "面型", "跟形", "两向截面", "惯性", "件上的件", "支承")
DIFF_CLASSES = ("遗漏", "识别", "族参数", "构造", "相机")       # 遗漏 = ident 有、模型没做；识别 = ident 本身错 / 缺
DIFF_STATUS = ("已修", "用户接受")
VERDICTS = ("像", "不像", "缺失")
AUDITS = ("eval_audit", "audit_objects", "audit_instances")
WEAK = {"—", "-", "/", "ok", "OK", "无", "是", "否", "对", "n/a", "N/A"}
FULL = ["interface", "symmetry", "repeat", "outline", "height", "assembly", "surface", "conform", "conform_reason", "conform_why",
        "section_along", "section_around", "inherited"]

NODE_T = dict(
    id="<节点 id；根节点必须是 root>", name="<名称>", parent="<坐在 / 装在哪个件上（节点 id）；根节点为 null>",
    role="<assembly（仅根）/ support 支承 / part 件 / mount 件上的安装件（铰座、凸台、带扣）/ detail 小件（刻线、小卷纹、缝线）>",
    count=1, level="<初定级 L0–L4 / skip；阶段 2 复核>", evidence=["<参考局部放大图路径（ref_trace.py crop），不能是参考原图>"],
    interface="<坐在谁上、朝哪（原点放这里）>", symmetry="<镜像 / n 次旋转 / 平移 / 无>", repeat="<出现几次、哪些参数在变>",
    outline="<能否少参数曲线写出>", height="<台地 / 拱起 / 自由面；有无倒扣>", assembly="<支承 / 贴合 / 搭接 / 净距 / 斜接；压着谁 / 被谁压>",
    surface="<curved | hard | mixed —— 渐变 = 曲面，成块 + 亮棱暗缝 = 硬表面；mixed 另写 surface_note>",
    conform=False, conform_reason="<thin | soft | small | rigid —— 跟不跟所坐的面（parent 的面）；跟形只能因为薄 / 软 / 小>",
    conform_why="<一句话依据>",
    section_along=dict(type="<curve | polyline>", segments=None, note="<沿主轴一刀>"),
    section_around=dict(type="<curve | polyline>", segments=None, note="<绕主轴一刀>"),
    inherited="<做法沿用自哪个旧案例？理由在此是否成立？无则写 none>",
    route="<仅 detail / L4：separate | relief | normal | material | asset>",
    profile_source=dict(method="<仅 support：silhouette_fit | known_shape | measured>", views=["<用哪些视图 id>"], note=""),
    deliver="<仅 support：true / false（如人的手臂只作支承不交付）>",
    skip_why="<仅 skip：为什么不做>")

TEMPLATES = {
    "ident.json": dict(
        object="", refs=[],
        classification={k: ["<参考里哪样东西 / 哪块区域>"] for k in CLASSES},
        views=[dict(id="<v1>", ref="<refs 里的哪张>", region="<x0 y0 x1 y1 或 全图>", facing="<正视 / 转约 20° / 仰视；有无强透视>",
                    use="<primary | aux | ignore>", note="<与其他视图对不上的地方>")],
        ambiguities=["<检查点 A 要用户定的歧义；能用另一视图消掉的不算>"],
        nodes=[dict(id="root", name="<整件名称>", parent=None, role="assembly", count=1, level="<整件目标级>",
                    evidence=["<整件局部放大 / 子视图切图>"]), dict(NODE_T)]),
    "selfcheck.json": dict(nodes={"<节点 id>": dict(checked={k: "<结论>" for k in CHECKS}, found="", changed="")},
                           blockout_compare="<粗模同视角对比图路径>", cold_read="<可选：冷读子代理的结论>", user_review="pending"),
    "measure.json": {"<参数名>": dict(value=None, source="<参考上的哪处读数（图 / 像素坐标 / 比例）>")},
    "accept.json": dict(compare_image="", iou=None, iou_min=None, iou_min_note="<及格线的理由（看结果前定；口径见 fitting.md §0）>",
                        ious=[dict(view="<可选：多视图逐视图>", iou=None, iou_min=None)],
                        pieces=[dict(node="<节点 id>", closeup="<模型特写路径>", ref_crop="<参考同部位放大图路径>",
                                     verdict="<像 / 不像 / 缺失：差在哪>")],
                        differences=[{"node": "<节点 id>", "what": "<差在哪>", "class": "<遗漏 | 识别 | 族参数 | 构造 | 相机>",
                                      "back_to": "<回到哪步：§1 / §3 / §4 …>", "status": "<已修 | 用户接受>"}],
                        no_diff_basis="<差异清单为空时写依据>",
                        audits={k: "" for k in ("eval_audit", "audit_objects", "audit_instances")}),
}


def _load(d, name):
    p = os.path.join(d, "gate", name)
    if not os.path.exists(p):
        return None, ["缺少 gate/%s（先 python gate.py init）" % name]
    try:
        return json.load(open(p, encoding="utf-8")), []
    except ValueError as e:
        return None, ["gate/%s 不是合法 JSON：%s" % (name, e)]


def _blank(v, tmpl=None):
    """空、等于模板原值、或仍是 <占位> 都算没填。"""
    if tmpl is not None and v == tmpl:
        return True
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip() or v.strip().startswith("<")
    if isinstance(v, (list, dict)):
        return not v or all(_blank(x) for x in (v.values() if isinstance(v, dict) else v))
    return False


def _exists(d, p):
    return isinstance(p, str) and os.path.exists(p if os.path.isabs(p) else os.path.join(d, p))


def _norm(d, p):
    return os.path.normcase(os.path.abspath(p if os.path.isabs(p) else os.path.join(d, p)))


def _digest(d, p):
    import hashlib
    try:
        return hashlib.md5(open(p if os.path.isabs(p) else os.path.join(d, p), "rb").read()).hexdigest()
    except OSError:
        return None


def _is_ref(d, p, refs):
    """路径相同，或内容与某张参考相同（换名拷贝也算原图）。"""
    if _norm(d, p) in {_norm(d, r) for r in refs}:
        return True
    h = _digest(d, p)
    return h is not None and h in {_digest(d, r) for r in refs}


def _posint(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _geo(n):
    """出独立几何、要答八问的节点。"""
    return n.get("id") != "root" and n.get("level") in ("L0", "L1", "L2", "L3") and not (
        n.get("role") == "detail" and n.get("route") in ("normal", "material", "asset"))


def check_ident(d):
    J, err = _load(d, "ident.json")
    if J is None:
        return err
    if J.get("skipped"):
        return []
    if _blank(J.get("object")):
        err.append("object 未填")
    refs = [r for r in (J.get("refs") or []) if isinstance(r, str)]
    if not refs or not all(_exists(d, r) for r in refs):
        err.append("refs 为空或文件不存在")
    refset = {_norm(d, r) for r in refs}
    # —— 参考清点 ——
    C = J.get("classification")
    if not isinstance(C, dict) or set(C) - set(CLASSES) or _blank(C.get("主体")):
        err.append("classification 须按 %s 分，主体不能空（其余类没有写 []）" % " / ".join(CLASSES))
    else:
        for k, v in C.items():
            if v and _blank(v):
                err.append("classification.%s 还是模板占位（没有写 []）" % k)
    V = [v for v in (J.get("views") or []) if isinstance(v, dict) and not _blank(v.get("id"))]
    vids = {v["id"] for v in V}
    if len(vids) < len(V):
        err.append("视图 id 重复")
    if not V:
        err.append("views 视图表没填（一张参考里有几个视图就列几个；单视图也列一个）")
    for v in V:
        if v.get("use") not in VIEW_USES:
            err.append("视图 %s：use 须为 %s" % (v["id"], " / ".join(VIEW_USES)))
        if _blank(v.get("facing")) or _blank(v.get("region")):
            err.append("视图 %s：facing / region 未填" % v["id"])
        if v.get("ref") not in refs:
            err.append("视图 %s：ref 不在 refs 里" % v["id"])
    if V and not any(v.get("use") == "primary" for v in V):
        err.append("没有 primary 视图（选一个主对位视角）")
    A = J.get("ambiguities")
    if not isinstance(A, list) or not A or any(_blank(x) for x in A):
        err.append("ambiguities 歧义清单没填（没有写 [\"无\"]）")
    elif isinstance(C, dict) and C.get("存疑") and not _blank(C["存疑"]):
        real = [x for x in A if str(x).strip() not in ("无", "none")]
        if len(real) < len(C["存疑"]):
            err.append("classification.存疑 有 %d 项，歧义清单只有 %d 条——存疑的东西要逐条请用户定" % (len(C["存疑"]), len(real)))
    # —— 树结构 ——
    nodes = [n for n in (J.get("nodes") or []) if isinstance(n, dict)]
    if len(nodes) < 2:
        err.append("构件树只有 %d 个节点：没拆件" % len(nodes))
    ids = [n.get("id") for n in nodes]
    dup = sorted({str(i) for i in ids if ids.count(i) > 1})
    if dup:
        err.append("节点 id 重复：%s" % ", ".join(dup))
    byid = {n.get("id"): n for n in nodes}
    root = byid.get("root")
    if root is None or root.get("parent") is not None or root.get("role") != "assembly":
        err.append("根节点须为 id = \"root\"、parent = null、role = \"assembly\"（整件本身；支承体是它下面的 support 节点）")
    for n in nodes:
        i, seen = n.get("id"), set()
        while i is not None and i not in seen and i in byid:
            seen.add(i)
            i = byid[i].get("parent")
        if i is not None and i in seen:
            err.append("节点 %s：父链成环" % n.get("id"))
    parents = {n.get("parent") for n in nodes}
    for n in nodes:
        tag = "节点 %s" % n.get("id")
        role, lvl = n.get("role"), n.get("level")
        if n.get("id") != "root" and n.get("parent") not in byid:
            err.append("%s：父节点 %s 不在树里" % (tag, n.get("parent")))
        if role not in ROLES or (role == "assembly") != (n.get("id") == "root"):
            err.append("%s：role 须为 %s（assembly 只给根）" % (tag, " / ".join(ROLES[1:])))
        if lvl not in LEVELS:
            err.append("%s：level 须为 %s" % (tag, " / ".join(LEVELS)))
        if not _posint(n.get("count")):
            err.append("%s：count 须为正整数" % tag)
        if _blank(n.get("name")):
            err.append("%s：name 未填" % tag)
        ev = n.get("evidence") or []
        if n.get("id") not in parents:
            if _blank(ev) or not all(_exists(d, e) for e in ev):
                err.append("%s：叶节点没有证据图或文件不存在" % tag)
            elif any(_is_ref(d, e, refs) for e in ev):
                err.append("%s：证据图是参考原图——切局部放大（ref_trace.py crop），描述要在图上对得上" % tag)
        if role == "mount" and n.get("parent") in (None, "root"):
            err.append("%s：安装件要挂在它坐的那个件下面" % tag)
        if role == "support":
            ps = n.get("profile_source")
            if not isinstance(ps, dict) or ps.get("method") not in PROFILE_METHODS:
                err.append("%s：支承外形来源 profile_source.method 须为 %s（先验只当初值，不算来源）" % (tag, " / ".join(PROFILE_METHODS)))
            elif ps["method"] == "silhouette_fit" and (not ps.get("views") or not set(ps["views"]) <= vids):
                err.append("%s：剪影拟合要写用哪些视图（views 里的 id）" % tag)
            if not isinstance(n.get("deliver"), bool):
                err.append("%s：deliver 须为 true / false（支承交不交付）" % tag)
        if lvl == "skip":
            if _blank(n.get("skip_why")):
                err.append("%s：skip 要写 skip_why" % tag)
            continue
        if (role == "detail" or lvl == "L4") and n.get("route") not in ROUTES:
            err.append("%s：detail / L4 要写去向 route ∈ %s" % (tag, " / ".join(ROUTES)))
        if not _geo(n):
            continue                                       # 根、L4、不出几何的 detail 不答八问
        for f in FULL:
            if f not in n or (f != "conform" and _blank(n[f], NODE_T.get(f))):
                err.append("%s：%s 未填" % (tag, f))
        if n.get("surface") not in SURFACES:
            err.append("%s：surface 须为 %s" % (tag, " / ".join(SURFACES)))
        if n.get("surface") == "mixed" and _blank(n.get("surface_note")):
            err.append("%s：mixed 要写 surface_note（哪部分硬、哪部分曲；哪一向是折线）" % tag)
        if not isinstance(n.get("conform"), bool):
            err.append("%s：conform 须为 true / false" % tag)
        cr = n.get("conform_reason")
        if cr not in CONFORM_REASONS:
            err.append("%s：conform_reason 须为 %s" % (tag, " / ".join(CONFORM_REASONS)))
        elif n.get("conform") is True and cr == "rigid":
            err.append("%s：刚性件跟所坐的面——刚性件应有自己的截面" % tag)
        elif n.get("conform") is True and n.get("surface") == "hard" and cr not in ("thin", "soft"):
            err.append("%s：硬表面件跟形只能因为薄 / 软" % tag)
        for k in ("section_along", "section_around"):
            s = n.get(k) or {}
            if s.get("type") not in ("curve", "polyline"):
                err.append("%s：%s.type 须为 curve / polyline" % (tag, k))
            elif s["type"] == "polyline" and not _posint(s.get("segments")):
                err.append("%s：%s 是折线但段数不是正整数" % (tag, k))
        if n.get("surface") == "hard" and all((n.get(k) or {}).get("type") == "curve" for k in ("section_along", "section_around")):
            err.append("%s：标了硬表面，两个方向截面却都是曲线——要么面型判错，要么截面没设计" % tag)
    return err


def check_selfcheck(d):
    J, err = _load(d, "selfcheck.json")
    if J is None:
        return err
    if J.get("skipped"):
        return []
    I, e2 = _load(d, "ident.json")
    if I is None:
        return err + e2
    ei = check_ident(d)
    if ei:
        err.append("ident 现在不过闸（自检改了树要重跑 gate.py ident）：%s" % "；".join(ei[:3]))
    nodes = J.get("nodes") or {}
    for n in I.get("nodes", []):
        if not _geo(n):
            continue
        c = nodes.get(n["id"])
        if not c:
            err.append("节点 %s 没自检" % n["id"])
            continue
        ck = c.get("checked")
        if not isinstance(ck, dict):
            err.append("节点 %s：checked 须为 {核查项: 结论}" % n["id"])
            continue
        for k in CHECKS:
            v = str(ck.get(k) or "").strip()
            if _blank(ck.get(k)) or v == k or v in WEAK or len(v) < 4:
                err.append("节点 %s：%s 没写结论（不适用也写\"不适用：理由\"）" % (n["id"], k))
        if _blank(c.get("found")):
            err.append("节点 %s：found 未填（没发现问题也写\"无\"及依据）" % n["id"])
    refset = {_norm(d, r) for r in (I.get("refs") or []) if isinstance(r, str)}
    bc = J.get("blockout_compare")
    if _blank(bc) or not _exists(d, bc):
        err.append("缺粗模同视角对比图（preview.py 不开 Blender 也能出）")
    elif _is_ref(d, bc, I.get("refs") or []):
        err.append("粗模对比图不能是参考原图")
    ur = str(J.get("user_review", ""))
    if not (ur == "ok" or ur.startswith("跳过")):
        err.append("用户还没过目（user_review = %s）" % ur)
    return err


def check_measure(d):
    J, err = _load(d, "measure.json")
    if J is None:
        return err
    if J.get("skipped"):
        return []
    real = {k: v for k, v in J.items() if not k.startswith("<")}
    if not real:
        err.append("measure.json 没有参数")
    for k, v in real.items():
        if not isinstance(v, dict) or v.get("value") is None or _blank(v.get("source")):
            err.append("参数 %s：缺值或来源" % k)
    return err


def check_accept(d):
    J, err = _load(d, "accept.json")
    if J is None:
        return err
    if J.get("skipped"):
        return []
    es = check_selfcheck(d)
    if es:
        err.append("selfcheck 现在不过闸（检查点 A 没过或改了树）：%s" % "；".join(es[:3]))
    I, _ = _load(d, "ident.json")
    refs = (I or {}).get("refs") or []
    ci = J.get("compare_image")
    if _blank(ci) or not _exists(d, ci):
        err.append("缺同视角对比图")
    elif _is_ref(d, ci, refs):
        err.append("对比图不能是参考原图")
    ious = [x for x in (J.get("ious") or []) if isinstance(x, dict) and not _blank(x.get("view"))]
    rows = ious or [dict(view="主视图", iou=J.get("iou"), iou_min=J.get("iou_min"))]
    for x in rows:
        if not isinstance(x.get("iou"), (int, float)) or not isinstance(x.get("iou_min"), (int, float)) or x["iou"] < x["iou_min"]:
            err.append("剪影 IoU 未达及格线（%s：%s / %s）" % (x.get("view"), x.get("iou"), x.get("iou_min")))
    if _blank(J.get("iou_min_note")):
        err.append("及格线没写理由（iou_min_note，看结果前定）")
    pieces = [p for p in (J.get("pieces") or []) if isinstance(p, dict) and not _blank(p.get("node"))]
    if not pieces:
        err.append("没有逐件对照（pieces：模型特写 + 参考局部放大 + 结论）")
    bad_nodes = set()
    for p in pieces:
        for k in ("closeup", "ref_crop"):
            if _blank(p.get(k)) or not _exists(d, p[k]):
                err.append("逐件对照 %s：%s 缺或文件不存在" % (p.get("node"), k))
        if not _blank(p.get("closeup")) and not _blank(p.get("ref_crop")) and _exists(d, p["closeup"]) and _exists(d, p["ref_crop"])                 and _digest(d, p["closeup"]) == _digest(d, p["ref_crop"]):
            err.append("逐件对照 %s：模型特写和参考放大是同一张图" % p.get("node"))
        v = str(p.get("verdict") or "").strip()
        head = next((h for h in ("不像", "缺失", "像") if v.startswith(h)), None)
        if _blank(p.get("verdict")) or head is None:
            err.append("逐件对照 %s：结论须以 像 / 不像 / 缺失 开头" % p.get("node"))
        elif head != "像":
            bad_nodes.add(p.get("node"))
    if I is not None and not I.get("skipped"):
        done = {p.get("node") for p in pieces}
        for n in I.get("nodes", []):
            if n.get("role") == "mount" and n.get("level") not in ("skip", "L4") and n.get("id") not in done:
                err.append("安装件 %s 没有逐件对照" % n.get("id"))
    if any(not isinstance(x, dict) for x in (J.get("differences") or [])):
        err.append("differences 每条须为 {node, what, class, back_to, status}，不是一句话")
    diffs = [x for x in (J.get("differences") or []) if isinstance(x, dict) and not _blank(x.get("what"))]
    for x in diffs:
        tag = "差异 %s" % (x.get("node") or x.get("what"))
        if x.get("class") not in DIFF_CLASSES:
            err.append("%s：class 须为 %s" % (tag, " / ".join(DIFF_CLASSES)))
        if _blank(x.get("back_to")):
            err.append("%s：没写回到哪步" % tag)
        if x.get("status") not in DIFF_STATUS:
            err.append("%s：status = %s——差异没修也没经用户接受，不能验收" % (tag, x.get("status")))
    covered = {x.get("node") for x in diffs}
    for nd in sorted(bad_nodes - covered, key=str):
        err.append("逐件对照 %s 判了不像 / 缺失，差异清单里没有它" % nd)
    if not diffs and _blank(J.get("no_diff_basis")):
        err.append("差异清单为空，又没写依据（no_diff_basis）")
    A = J.get("audits") or {}
    for k in AUDITS:
        if A.get(k) != "pass":
            err.append("审计 %s：%s" % (k, A.get(k) or "未跑"))
    return err


STEPS = dict(ident=check_ident, selfcheck=check_selfcheck, measure=check_measure, accept=check_accept)


def init(d):
    g = os.path.join(d, "gate")
    os.makedirs(g, exist_ok=True)
    out = []
    for nm, T in TEMPLATES.items():
        p = os.path.join(g, nm)
        if not os.path.exists(p):
            json.dump(T, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            out.append(nm)
    return out


def run(step, d):
    steps = list(STEPS) if step == "all" else [step]
    for s in steps:
        err = STEPS[s](d)
        print("[%s] %s" % (s, "过" if not err else "不过"))
        for e in err:
            print("   -", e)
        if err:
            return 1
    return 0


def selftest():
    import copy
    import tempfile
    d = tempfile.mkdtemp()
    init(d)
    assert check_ident(d), "模板不该过闸"
    for f in ("ref.png", "ev.png", "bo.png", "cl.png"):
        open(os.path.join(d, f), "wb").write(f.encode())
    open(os.path.join(d, "ref_copy.png"), "wb").write(b"ref.png")
    P = lambda: os.path.join(d, "gate", "ident.json")
    W = lambda J, name="ident.json": json.dump(J, open(os.path.join(d, "gate", name), "w", encoding="utf-8"), ensure_ascii=False)

    def n(i, p, **k):
        b = dict(id=i, name=i, parent=p, role="part", count=1, interface="i", symmetry="无", repeat="1", outline="o", height="h",
                 assembly="a", surface="hard", conform=False, conform_reason="rigid", conform_why="刚性大件",
                 section_along=dict(type="polyline", segments=4), section_around=dict(type="polyline", segments=3),
                 level="L3", evidence=["ev.png"], inherited="none")
        b.update(k)
        return b
    good = dict(object="x", refs=["ref.png"], classification={"主体": ["护臂"], "插图": [], "标注": [], "干扰物": [], "存疑": []},
                views=[dict(id="v1", ref="ref.png", region="全图", facing="正视", use="primary")], ambiguities=["无"],
                nodes=[dict(id="root", name="x", parent=None, role="assembly", count=1, level="L3", evidence=["ev.png"]),
                       n("arm", "root", role="support", surface="curved", section_along=dict(type="curve"), section_around=dict(type="curve"),
                         profile_source=dict(method="silhouette_fit", views=["v1"]), deliver=False),
                       n("plate", "arm"), n("hinge", "plate", role="mount"),
                       n("line", "plate", role="detail", level="L4", route="normal")])
    W(good)
    assert check_ident(d) == [], check_ident(d)

    def bad(msg, key, mut):
        J = copy.deepcopy(good)
        mut(J)
        W(J)
        e = check_ident(d)
        assert any(key in x for x in e), (msg, e)
    bad("模板原文应拦", "interface", lambda J: J["nodes"][2].update(interface=NODE_T["interface"]))
    bad("证据是原图应拦", "参考原图", lambda J: J["nodes"][3].update(evidence=["ref.png"]))
    bad("id 重复应拦", "重复", lambda J: J["nodes"].append(n("plate", "arm")))
    bad("成环应拦", "成环", lambda J: J["nodes"].extend([n("a", "b"), n("b", "a")]))
    bad("先验当来源应拦", "profile_source", lambda J: J["nodes"][1].update(profile_source=dict(method="prior")))
    bad("支承不写交付应拦", "deliver", lambda J: J["nodes"][1].pop("deliver"))
    bad("段数字符串应拦", "段数", lambda J: J["nodes"][2].update(section_along=dict(type="polyline", segments="4")))
    bad("count 负数应拦", "count", lambda J: J["nodes"][2].update(count=-1))
    bad("刚性跟形应拦", "刚性件", lambda J: J["nodes"][2].update(conform=True))
    bad("硬表面两向曲线应拦", "硬表面", lambda J: J["nodes"][2].update(section_along=dict(type="curve"), section_around=dict(type="curve")))
    bad("mixed 无说明应拦", "surface_note", lambda J: J["nodes"][2].update(surface="mixed"))
    bad("无 primary 视图应拦", "primary", lambda J: J["views"][0].update(use="aux"))
    bad("根不是 assembly 应拦", "根节点", lambda J: J["nodes"][0].update(role="support"))
    bad("detail 不写去向应拦", "route", lambda J: J["nodes"][4].pop("route"))
    bad("安装件挂根应拦", "安装件", lambda J: J["nodes"][3].update(parent="root"))
    bad("原图换名当证据应拦", "参考原图", lambda J: J["nodes"][3].update(evidence=["ref_copy.png"]))
    bad("视图 id 重复应拦", "视图 id 重复", lambda J: J["views"].append(dict(J["views"][0])))
    bad("存疑不进歧义应拦", "存疑", lambda J: J["classification"].update({"存疑": ["顶板下细板"]}))
    W(good)
    S = dict(nodes={k: dict(checked={c: "核过：无问题" for c in CHECKS}, found="无") for k in ("arm", "plate", "hinge")},
             blockout_compare="bo.png", user_review="pending")
    W(S, "selfcheck.json")
    assert any("过目" in e for e in check_selfcheck(d)), "用户未过目应拦"
    S["user_review"] = "ok"
    S["nodes"]["plate"]["checked"]["面型"] = "面型"
    W(S, "selfcheck.json")
    assert any("面型 没写结论" in e for e in check_selfcheck(d)), "照抄清单应拦"
    S["nodes"]["plate"]["checked"]["面型"] = "—"
    W(S, "selfcheck.json")
    assert any("面型 没写结论" in e for e in check_selfcheck(d)), "单字符结论应拦"
    S["nodes"]["plate"]["checked"]["面型"] = "成块亮棱，硬表面"
    W(S, "selfcheck.json")
    assert check_selfcheck(d) == [], check_selfcheck(d)
    J = copy.deepcopy(good)
    J["nodes"][2]["interface"] = ""
    W(J)
    assert any("ident 现在不过闸" in e for e in check_selfcheck(d)), "改坏树后自检应拦"
    W(good)
    S["blockout_compare"] = "ref.png"
    W(S, "selfcheck.json")
    assert any("参考原图" in e for e in check_selfcheck(d)), "粗模对比用原图应拦"
    S["blockout_compare"] = "bo.png"
    W(S, "selfcheck.json")
    AU = {k: "pass" for k in AUDITS}
    A = dict(compare_image="bo.png", iou=0.7, iou_min=0.8, iou_min_note="合成同机位", pieces=[], differences=[], audits=AU)
    W(A, "accept.json")
    e = check_accept(d)
    assert any("IoU" in x for x in e) and any("逐件" in x for x in e) and any("依据" in x for x in e), ("IoU 不够、没逐件对照、空差异无依据应拦", e)
    A.update(iou=0.96, no_diff_basis="逐件都像", pieces=[dict(node="plate", closeup="cl.png", ref_crop="ev.png", verdict="像")])
    W(A, "accept.json")
    assert any("安装件 hinge" in x for x in check_accept(d)), "安装件没逐件对照应拦"
    A["pieces"].append(dict(node="hinge", closeup="cl.png", ref_crop="ev.png", verdict="缺失：模型里没有铰座"))
    W(A, "accept.json")
    assert any("差异清单里没有它" in x for x in check_accept(d)), "IoU 过线但件缺失、差异没列应拦"
    A["differences"] = [{"node": "hinge", "what": "铰座漏做", "class": "遗漏", "back_to": "§4", "status": "待改"}]
    W(A, "accept.json")
    assert any("不能验收" in x for x in check_accept(d)), "差异待改应拦"
    A["differences"][0]["status"] = "已修"
    A["pieces"][1]["verdict"] = "像：补做后扁宽、长槽"
    A["pieces"][0]["closeup"] = "ev.png"
    W(A, "accept.json")
    assert any("同一张图" in x for x in check_accept(d)), "特写与参考同图应拦"
    A["pieces"][0]["closeup"] = "cl.png"
    A["audits"] = {}
    W(A, "accept.json")
    assert any("audit_objects" in x for x in check_accept(d)), "审计空字典应拦"
    A["audits"] = AU
    A["compare_image"] = "ref_copy.png"
    W(A, "accept.json")
    assert any("参考原图" in x for x in check_accept(d)), "对比图用原图应拦"
    A["compare_image"] = "bo.png"
    W(A, "accept.json")
    assert check_accept(d) == [], check_accept(d)
    S["user_review"] = "pending"
    W(S, "selfcheck.json")
    assert any("selfcheck" in x for x in check_accept(d)), "检查点 A 没过，accept 应拦"
    print("gate selftest ok：模板不过；填全过；模板原文 / 证据用原图 / id 重复 / 成环 / 先验当来源 / 支承不写交付 / 段数非整数 / "
          "count 非正 / 刚性跟形 / 硬表面两向曲线 / mixed 无说明 / 无主视图 / 根角色错 / detail 无去向 / 安装件挂根 各拦；"
          "原图换名 / 视图 id 重复 / 存疑不进歧义 各拦；未过目、照抄清单、单字符结论、改树后未重过、粗模用原图拦；"
          "IoU 不够、无逐件对照、空差异无依据、安装件漏对照、不像 / 缺失没进差异、差异待改、特写与参考同图、审计不全、对比图用原图、A 没过 各拦")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] in ("--selftest", "selftest"):
        selftest()
    elif a[0] == "init":
        print("写模板：", init(a[1]))
    else:
        sys.exit(run(a[0], a[1]))
