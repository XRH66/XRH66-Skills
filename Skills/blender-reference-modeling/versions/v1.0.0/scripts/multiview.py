# -*- coding: utf-8 -*-
"""
multiview：多视图联合拟合（方法层，领域无关，纯 numpy）。原理见 references/fitting.md §1、§2b、§4。
一个物体、几台相机：相机各自独立，物体的族参数共享；尺度由一个先验尺寸（或已知形）固定。

  View(fwd0, up0, target, f)                 每个视图的基准姿态（目测的大致视线 / 上方向）；
    .cam(x)                                  x = (a, b, roll, D, du, dv)：绕基准上轴 / 右轴的小转角、绕视线滚转、距离、像面平移
                                             → camkit.Pinhole。相对基准的小扰动参数化，俯视 / 仰视也不会万向锁
  OrthoView(fwd0, up0, target)              正交视图（正视 / 侧视 / 俯视的工程图式参考）：.cam(x)，x = (a, b, roll, k, du, dv)，
                                             k = 像素 / mm。距离不存在，D0 传 k 的初值。正交下"大小 ↔ 距离"的歧义变成"k ↔ 尺寸"，
                                             仍要一个先验尺寸定尺度；正视 + 侧视联合可直接定宽、深、高
  lm(resid, x0, iters, lam, h)               Levenberg–Marquardt（数值雅可比），返回 (x, cost, J)
  joint_fit(model, obs, views, D0, theta0, sigma, free_theta)
      model(theta) → {特征名: 3D 点}；obs = [{特征名: (u, v)}]（每个视图一份，缺的特征不写）
      views = [View]；D0 = 每个视图的距离初值；theta0 = 族参数初值；free_theta = 放开哪些（尺度先验那个不放）
      → dict(theta, std, cams, rms_px, per_view, J)
      std = 每个放开族参数的 1σ 不确定度（(JᵀJ)⁻¹ 按标点误差 sigma 缩放）——"这组视图定得了它吗"的直接读数
用法要点：先在 primary 视图上单独定相机（obs 只给一个视图），再加 aux 视图联合；
  某个族参数 std 和它自身量级相当 = 这组视图定不了它 → 再找一个视图、加已知形，或列入歧义（出方案族）。
[自检：合成盒形物体——单个俯视图下厚度 T 的 1σ ≈ 6 mm（偏了 6 mm），加侧视图后 1σ ≈ 0.3 mm、误差 < 2%。还没在真实参考上跑过]
"""
import math
import numpy as np
import camkit


def _rot(axis, ang):
    k = np.asarray(axis, float)
    k = k / np.linalg.norm(k)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K


class View:
    def __init__(self, fwd0, up0, target, f):
        fwd = np.asarray(fwd0, float)
        self.fwd0 = fwd / np.linalg.norm(fwd)
        rt = np.cross(self.fwd0, np.asarray(up0, float))
        self.rt0 = rt / np.linalg.norm(rt)
        self.up0 = np.cross(self.rt0, self.fwd0)
        self.target, self.f = np.asarray(target, float), float(f)

    def cam(self, x):
        a, b, roll, D, du, dv = x
        R = _rot(self.up0, a) @ _rot(self.rt0, b)
        fwd = R @ self.fwd0
        up = _rot(fwd, roll) @ (R @ self.up0)
        return camkit.Pinhole(self.target - fwd * D, fwd, up, self.f, (du, dv))


class _Ortho:
    def __init__(self, fwd, up, rt, k, pp, target):
        self.fwd, self.up, self.rt, self.k, self.pp, self.target = fwd, up, rt, k, np.asarray(pp, float), target

    def uv(self, P):
        v = np.atleast_2d(np.asarray(P, float)) - self.target
        return np.stack([v @ self.rt, v @ self.up], 1) * self.k + self.pp


class OrthoView(View):
    def __init__(self, fwd0, up0, target, f=1.0):
        super().__init__(fwd0, up0, target, f)

    def cam(self, x):
        a, b, roll, k, du, dv = x
        R = _rot(self.up0, a) @ _rot(self.rt0, b)
        fwd = R @ self.fwd0
        up = _rot(fwd, roll) @ (R @ self.up0)
        rt = np.cross(fwd, up)
        return _Ortho(fwd, up, rt, k, (du, dv), self.target)


def _jac(resid, x, r0, h):
    J = np.empty((len(r0), len(x)))
    for j in range(len(x)):
        d = np.zeros_like(x)
        d[j] = h[j]
        J[:, j] = (resid(x + d) - resid(x - d)) / (2 * h[j])
    return J


def lm(resid, x0, iters=200, lam=1e-3, h=None):
    x = np.asarray(x0, float).copy()
    h = np.maximum(np.abs(x) * 1e-6, 1e-6) if h is None else np.asarray(h, float)
    r = resid(x)
    cost = float(r @ r)
    J = _jac(resid, x, r, h)
    for _ in range(iters):
        A, g = J.T @ J, J.T @ r
        moved = False
        while lam < 1e12:
            dx = -np.linalg.lstsq(A + lam * np.diag(np.diag(A) + 1e-12), g, rcond=None)[0]
            r2 = resid(x + dx)
            c2 = float(r2 @ r2)
            if c2 < cost:
                small = cost - c2 < 1e-12 * (1 + cost)
                x, r, cost, lam, moved = x + dx, r2, c2, max(lam / 3, 1e-12), True
                J = _jac(resid, x, r, h)
                break
            lam *= 4
        if not moved or small:
            break
    return x, cost, J


def joint_fit(model, obs, views, D0, theta0, sigma=1.5, free_theta=None):
    theta0 = dict(theta0)
    free = list(free_theta or theta0.keys())
    nv, nf = len(obs), len(free)

    def split(x):
        th = dict(theta0)
        th.update({k: x[i] for i, k in enumerate(free)})
        return th, [x[nf + 6 * i: nf + 6 * i + 6] for i in range(nv)]

    def resid(x):
        th, cams = split(x)
        P = model(th)
        out = []
        for o, V, cx in zip(obs, views, cams):
            ks = [k for k in o if k in P]
            uv = V.cam(cx).uv([P[k] for k in ks])
            out.extend(((uv - np.array([o[k] for k in ks])) / sigma).ravel())
        return np.nan_to_num(np.array(out), nan=1e3)

    x0 = np.array([theta0[k] for k in free] + [v for D in D0 for v in (0, 0, 0, D, 0, 0)], float)
    h = np.array([max(abs(theta0[k]) * 1e-5, 1e-4) for k in free] + [v for D in D0 for v in (1e-6, 1e-6, 1e-6, max(abs(D) * 1e-6, 1e-7), 1e-3, 1e-3)])
    x, cost, J = lm(resid, x0, h=h)
    th, cams = split(x)
    r = resid(x) * sigma
    P = model(th)
    per, i = [], 0
    for o in obs:
        k = 2 * len([q for q in o if q in P])
        per.append(float(np.sqrt((r[i:i + k] ** 2).mean())) if k else float("nan"))
        i += k
    cov = np.linalg.pinv(J.T @ J)                     # J 已按 sigma 归一 → 协方差单位即参数单位
    std = {k: float(math.sqrt(max(cov[i, i], 0.0))) for i, k in enumerate(free)}
    return dict(theta=th, std=std, cams=cams, rms_px=float(np.sqrt((r ** 2).mean())), per_view=per, J=J)


def selftest():
    rng = np.random.default_rng(3)

    def model(t):                                     # 盒形物体：长 L（尺度先验，固定）、宽 W、厚 T；外加一个偏心凸台
        L, W, T = t["L"], t["W"], t["T"]
        P = {"%d%d%d" % (i, j, k): np.array([(i - .5) * W, j * L, (k - .5) * T]) for i in range(2) for j in range(2) for k in range(2)}
        P["boss"] = np.array([0.2 * W, 0.6 * L, 0.5 * T + 5])
        return P
    truth = dict(L=200.0, W=60.0, T=35.0)
    target, f, sig = (0, 100, 0), 3000.0, 0.8
    top = View((0.05, 0.08, -1), (0, 1, 0), target, f)            # 俯视：厚度 T 几乎顺着视线（基准姿态 = 目测）
    side = View((1, 0.05, -0.08), (0, 0, 1), target, f)           # 侧视
    P = model(truth)
    tcam = top.cam((0.02, -0.03, 0.01, 1800, 3, -2))              # 真实相机 = 基准 + 未知小扰动
    scam = side.cam((-0.02, 0.02, -0.01, 1700, -4, 1))

    def shoot(cam):
        return {k: cam.uv([p])[0] + rng.normal(0, sig, 2) for k, p in P.items()}
    ot, os_ = shoot(tcam), shoot(scam)
    th0 = dict(L=200.0, W=50.0, T=20.0)
    R1 = joint_fit(model, [ot], [top], [1800], th0, sigma=sig, free_theta=["W", "T"])
    R2 = joint_fit(model, [ot, os_], [top, side], [1800, 1700], th0, sigma=sig, free_theta=["W", "T"])
    eT, eW = abs(R2["theta"]["T"] - 35) / 35, abs(R2["theta"]["W"] - 60) / 60
    assert eT < 0.03 and eW < 0.03, ("双视图恢复", R2["theta"])
    assert R2["std"]["T"] < 1.0 and R1["std"]["T"] > 8 * R2["std"]["T"], ("单视图厚度应定不了", R1["std"], R2["std"])
    # 正交：正视（看 +y）+ 侧视（看 −x），k 未知、L 先验固定 → 定 W、T
    fv, sv = OrthoView((0, 1, 0), (0, 0, 1), target), OrthoView((-1, 0, 0), (0, 0, 1), target)
    oc = [fv.cam((0.01, -0.01, 0.005, 1.3, 2, -1)), sv.cam((-0.01, 0.01, 0, 1.3, -3, 2))]
    oo = [{k: c.uv([p])[0] + rng.normal(0, sig, 2) for k, p in P.items()} for c in oc]
    R3 = joint_fit(model, oo, [fv, sv], [1.2, 1.2], th0, sigma=sig, free_theta=["W", "T"])
    assert abs(R3["theta"]["W"] - 60) < 1.5 and abs(R3["theta"]["T"] - 35) < 1.5, ("正交双视图", R3["theta"])
    print("multiview selftest ok：正交正 + 侧视 W = %.2f、T = %.2f；" % (R3["theta"]["W"], R3["theta"]["T"]), end="")
    print("只用俯视图 T = %.1f ± %.1f mm（真值 35，只能粗定）；加侧视图 T = %.2f ± %.2f、W = %.2f ± %.2f，残差 %.2f px"
          % (R1["theta"]["T"], R1["std"]["T"], R2["theta"]["T"], R2["std"]["T"], R2["theta"]["W"], R2["std"]["W"], R2["rms_px"]))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    selftest() if len(sys.argv) > 1 and sys.argv[1] in ("--selftest", "selftest") else print(__doc__)
