"""构建脚本的静态检查（在 Blender 外用普通 Python 跑）。

    python cold_check.py <dir_or_file> [...]

为什么需要：在 Blender 会话里 importlib.reload 不会清掉模块旧属性，被误删的函数仍在内存里，
热构建照样通过，直到重开 Blender 才报"未定义"。这一步在提交 / 交付前把这类问题提前抓出来。

检查：
  1. 语法（compile）。
  2. 未定义名字（有 pyflakes 用 pyflakes；没有则用 AST 粗查：模块里调用但未定义 / 未导入的顶层函数名）。
  3. 同一模块里重复定义的顶层函数（补丁拼接常见）。
仍需做：重开 Blender 后完整构建一次。本脚本不能替代冷启动构建。
"""
import ast
import builtins
import os
import subprocess
import sys


def files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, _, fs in os.walk(p):
                if "__pycache__" in root:
                    continue
                for f in fs:
                    if f.endswith(".py"):
                        yield os.path.join(root, f)
        elif p.endswith(".py"):
            yield p


def ast_check(path, src):
    tree = ast.parse(src, path)
    issues, defined, seen = [], set(dir(builtins)), {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in seen:
                issues.append("%s:%d: 顶层重复定义 %r（首次在第 %d 行）" % (path, node.lineno, node.name, seen[node.name]))
            seen[node.name] = node.lineno
            defined.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                defined.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for t in ast.walk(node):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    defined.add(t.id)
    has_star = any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in tree.body)
    local = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            local.add(n.id)
        elif isinstance(n, ast.arg):
            local.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                local.add((a.asname or a.name).split(".")[0])
    if not has_star:
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                nm = n.func.id
                if nm not in defined and nm not in local:
                    issues.append("%s:%d: 调用了未定义的 %r" % (path, n.lineno, nm))
    return issues


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    targets = list(files(argv or ["."]))
    issues = []
    for f in targets:
        src = open(f, encoding="utf-8").read()
        try:
            compile(src, f, "exec")
        except SyntaxError as e:
            issues.append("%s:%s: 语法错误 %s" % (f, e.lineno, e.msg))
            continue
        issues += [i for i in ast_check(f, src) if "重复定义" in i]
    r = subprocess.run([sys.executable, "-m", "pyflakes", *targets], capture_output=True, text=True)
    if "No module named pyflakes" in r.stderr:
        mode = "ast"
    else:
        mode = "pyflakes"
        issues += [ln for ln in r.stdout.splitlines() if "undefined name" in ln]
    if mode == "ast":
        for f in targets:
            try:
                issues += [i for i in ast_check(f, open(f, encoding="utf-8").read()) if "未定义" in i]
            except SyntaxError:
                pass
    print("COLD_CHECK", "pass" if not issues else "fail", "(%d files, %s)" % (len(targets), mode))
    for i in issues:
        print("  " + i)
    print("下一步：重开 Blender，完整构建一次，才算验证。")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
