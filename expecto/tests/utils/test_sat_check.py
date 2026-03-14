import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parent.parent.parent
sys.path.append(str(ROOT))

inspect_ai_module = types.ModuleType("inspect_ai")
inspect_ai_module.__path__ = []
util_module = types.ModuleType("inspect_ai.util")
log_module = types.ModuleType("inspect_ai.log")
setattr(util_module, "ExecResult", dict)
setattr(util_module, "SandboxEnvironment", object)
setattr(util_module, "sandbox", lambda *args, **kwargs: None)
setattr(log_module, "EvalSample", dict)
setattr(log_module, "EvalSpec", dict)
sys.modules.setdefault("inspect_ai", inspect_ai_module)
sys.modules.setdefault("inspect_ai.util", util_module)
sys.modules.setdefault("inspect_ai.log", log_module)

import src.utils.sat_check as sat_module


def test_sat_check_uses_original_spec_by_default(monkeypatch):
    captured: dict[str, str] = {}

    class FakeDockerSandbox:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def run_test(self, code: str):
            captured["code"] = code
            return SimpleNamespace(status="success", stderr="", stdout="")

    monkeypatch.setattr(sat_module, "DockerSandbox", FakeDockerSandbox)

    result = asyncio.run(sat_module.sat_check("function spec(x: int) -> (res: int)"))

    assert result.is_ok()
    assert "solver.add(spec)" in captured["code"]
    assert "solver.add(z3.Not(spec))" not in captured["code"]


def test_sat_check_uses_negated_spec_when_requested(monkeypatch):
    captured: dict[str, str] = {}

    class FakeDockerSandbox:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def run_test(self, code: str):
            captured["code"] = code
            return SimpleNamespace(status="success", stderr="", stdout="")

    monkeypatch.setattr(sat_module, "DockerSandbox", FakeDockerSandbox)

    result = asyncio.run(
        sat_module.sat_check("function spec(x: int) -> (res: int)", negate=True)
    )

    assert result.is_ok()
    assert "solver.add(z3.Not(spec))" in captured["code"]
