"""Sandbox tests: allowlist, rejections, timeout and output truncation."""

from __future__ import annotations

import asyncio

from app.agent.tools.base import ToolContext
from app.agent.tools.python_exec import PythonExecTool, validate_code


def test_acceptance_example_is_allowed() -> None:
    assert validate_code("data = [1,2,3,4]\nprint(sum(data)/len(data))") is None


def test_blocked_imports() -> None:
    assert "os" in validate_code("import os\nos.system('dir')")
    assert "sys" in validate_code("import sys")
    assert "subprocess" in validate_code("import subprocess")
    assert "pathlib" in validate_code("from pathlib import Path")


def test_blocked_builtins_and_reflection() -> None:
    assert "open" in validate_code("open('x.txt')")
    assert "eval" in validate_code("eval('1+1')")
    assert "exec" in validate_code("exec('1+1')")
    assert "compile" in validate_code("compile('1', '', 'eval')")
    assert "getattr" in validate_code("getattr([], 'append')")
    assert "禁止访问下划线" in validate_code('"".__class__')
    assert "禁止访问下划线" in validate_code("[].__mro__")


def test_allowed_stdlib_imports_and_features() -> None:
    assert validate_code("import math\nprint(math.sqrt(16))") is None
    assert validate_code("from statistics import mean\nprint(mean([1,2]))") is None
    assert validate_code("import json\nprint(json.dumps({'a': 1}))") is None
    assert validate_code("import io\nprint(io.StringIO('x').getvalue())") is None
    code = (
        "def square(x):\n"
        "    return x * x\n"
        "total = 0\n"
        "for i in range(10):\n"
        "    total += square(i)\n"
        "print(total)\n"
        "print([i * 2 for i in range(4) if i > 0])\n"
    )
    assert validate_code(code) is None


def test_unsupported_syntax_is_rejected() -> None:
    assert "JoinedStr" in validate_code('print(f"x={1}")')
    assert "Lambda" in validate_code("f = lambda x: x")
    assert "Try" in validate_code("try:\n    pass\nexcept Exception:\n    pass")
    assert "NamedExpr" in validate_code("if (n := 10) > 5:\n    print(n)")


def _args(code: str) -> object:
    return type("Args", (), {"code": code, "stdin": ""})()


async def _run(code: str):
    tool = PythonExecTool()
    return await tool.run(_args(code), ToolContext(question="测试"))  # type: ignore[arg-type]


def test_executes_allowed_code() -> None:
    result = asyncio.run(_run("data = [1,2,3,4]\nprint(sum(data)/len(data))"))
    assert result.ok
    assert "2.5" in result.data["stdout"]


def test_runtime_error_is_structured() -> None:
    result = asyncio.run(_run("1 / 0"))
    assert not result.ok
    assert "ZeroDivisionError" in result.summary


def test_timeout_kills_process(monkeypatch) -> None:
    monkeypatch.setattr("app.agent.tools.python_exec.TIMEOUT_SECONDS", 0.4)
    result = asyncio.run(_run("while True:\n    pass"))
    assert not result.ok
    assert "超时" in result.summary


def test_stdout_is_truncated() -> None:
    result = asyncio.run(_run("print('x' * 12000)"))
    assert result.ok
    assert "截断" in result.data["stdout"]
    assert len(result.data["stdout"].encode("utf-8")) <= 9 * 1024


def test_stdin_is_available() -> None:
    args = type("Args", (), {"code": "print(input().upper())", "stdin": "hello"})()
    result = asyncio.run(
        PythonExecTool().run(args, ToolContext(question="测试"))  # type: ignore[arg-type]
    )
    assert result.ok
    assert "HELLO" in result.data["stdout"]
