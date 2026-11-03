"""Sandboxed Python execution via a restricted AST allowlist and a subprocess.

The user code never runs in the API process: it is validated against an AST
allowlist (stdlib math/statistics/csv/json/io/re only, no I/O or reflection
builtins) and executed in an isolated child (`python -I`) with a hard timeout,
capped stdout and a scratch working directory that is removed afterwards.
"""

from __future__ import annotations

import ast
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from app.agent.tools.base import Tool, ToolContext, ToolResult

TIMEOUT_SECONDS = 8.0
MAX_STDOUT_BYTES = 8 * 1024
_MAX_NODES = 1000

_ALLOWED_IMPORTS = {"math", "statistics", "csv", "json", "io", "re"}

_ALLOWED_CALLS = {
    "print", "len", "sum", "min", "max", "abs", "round", "range", "input",
    "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "frozenset", "sorted", "reversed", "zip", "enumerate", "map",
    "filter", "any", "all", "pow", "divmod", "isinstance", "issubclass",
    "format", "repr", "chr", "ord", "hex", "oct", "bin", "iter", "next",
    "hash", "id",
}

_ALLOWED_STMT = {
    ast.Assign, ast.AugAssign, ast.AnnAssign, ast.For, ast.While, ast.If,
    ast.FunctionDef, ast.Return, ast.Pass, ast.Break, ast.Continue,
    ast.Expr, ast.Import, ast.ImportFrom,
}
_ALLOWED_EXPR = {
    ast.Constant, ast.Name, ast.Attribute, ast.Subscript, ast.Slice,
    ast.Tuple, ast.List, ast.Dict, ast.Set, ast.Starred,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Call, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
    ast.comprehension, ast.keyword, ast.arg, ast.arguments, ast.Load,
    ast.And, ast.Or, ast.Not, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Invert,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is,
    ast.IsNot, ast.In, ast.NotIn,
}

_CHILD_RUNNER = r"""
import sys
with open("user_code.py", encoding="utf-8") as fh:
    code = fh.read()
try:
    sys.stdin = open("stdin.txt", encoding="utf-8")
except OSError:
    pass
try:
    exec(compile(code, "user_code.py", "exec"), {"__name__": "__main__"})
except Exception as exc:
    print("SANDBOX_ERROR: %s: %s" % (type(exc).__name__, exc))
"""


class PythonExecArgs(BaseModel):
    code: str = Field(min_length=1, max_length=20000)
    stdin: str = Field(default="", max_length=8000)


def validate_code(code: str) -> str | None:
    """Return a Chinese error message, or None when the code is allowed."""

    text = code.strip()
    if not text:
        return "代码为空"
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return f"语法错误：{exc}"

    if len(tree.body) == 1 and isinstance(tree.body[0], ast.Expression):
        tree = ast.parse(f"print({text})")

    nodes = list(ast.walk(tree))
    if len(nodes) > _MAX_NODES:
        return "代码过于复杂，已拒绝执行"

    bindings: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in _ALLOWED_IMPORTS:
                    return f"禁止导入模块：{alias.name}"
                if (alias.asname or alias.name).startswith("_"):
                    return f"禁止使用下划线别名：{alias.asname or alias.name}"
                bindings.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module not in _ALLOWED_IMPORTS:
                return f"禁止导入模块：{module}"
            for alias in node.names:
                name = alias.asname or alias.name
                if name.startswith("_") or alias.name.startswith("_"):
                    return f"禁止导入下划线名称：{name}"
                bindings.add(name)
        elif isinstance(node, ast.FunctionDef):
            bindings.add(node.name)

    for node in nodes:
        if isinstance(node, ast.Call) and not _call_allowed(node, bindings):
            return f"禁止调用：{_call_text(node)}"
        if isinstance(node, ast.stmt) and type(node) not in _ALLOWED_STMT:
            return f"不支持的语句：{type(node).__name__}"
        if isinstance(node, ast.expr) and type(node) not in _ALLOWED_EXPR:
            return f"不支持的表达式：{type(node).__name__}"
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return f"禁止访问下划线属性：.{node.attr}"
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            return f"禁止访问：{node.id}"
        if isinstance(node, ast.FunctionDef) and node.decorator_list:
            return "函数不允许使用装饰器"
    return None


def _call_allowed(node: ast.Call, bindings: set[str]) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _ALLOWED_CALLS or func.id in bindings
    if isinstance(func, ast.Attribute):
        return not func.attr.startswith("_")
    return False


def _call_text(node: ast.Call) -> str:
    try:
        return ast.unparse(node.func)
    except Exception:
        return type(node.func).__name__


class PythonExecTool(Tool):
    name = "python.exec"
    description = (
        "在受限沙箱中执行 Python 计算代码（math/statistics/csv/json/io/re），"
        "8 秒超时，输出最多 8KB。"
    )
    args_model = PythonExecArgs

    async def run(self, args: BaseModel, context: ToolContext) -> ToolResult:
        exec_args: PythonExecArgs = args  # type: ignore[assignment]
        error = validate_code(exec_args.code)
        if error:
            return ToolResult(ok=False, summary=f"代码被拒绝：{error}")

        workdir = Path(tempfile.mkdtemp(prefix="margin-py-"))
        try:
            (workdir / "user_code.py").write_text(exec_args.code, encoding="utf-8")
            (workdir / "stdin.txt").write_text(exec_args.stdin, encoding="utf-8")
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-c",
                _CHILD_RUNNER,
                cwd=str(workdir),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                raw, _ = await asyncio.wait_for(
                    process.communicate(), timeout=TIMEOUT_SECONDS
                )
            except TimeoutError:
                process.kill()
                await process.communicate()
                return ToolResult(
                    ok=False,
                    summary=f"执行超时（{TIMEOUT_SECONDS:.0f} 秒），进程已终止。",
                )
        except OSError as exc:
            return ToolResult(ok=False, summary=f"沙箱启动失败：{exc}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        output = raw.decode("utf-8", errors="replace")
        truncated = len(output.encode("utf-8", errors="replace")) > MAX_STDOUT_BYTES
        if truncated:
            output = output[:MAX_STDOUT_BYTES].rstrip() + "\n…（输出已截断）"
        if output.startswith("SANDBOX_ERROR: "):
            message = output[len("SANDBOX_ERROR: ") :].strip()[:500]
            return ToolResult(ok=False, summary=f"执行出错：{message}")
        output_text = output.strip()
        return ToolResult(
            ok=True,
            summary=f"输出：{output_text[:400]}" if output_text else "执行完成，无输出。",
            data={"stdout": output},
        )
