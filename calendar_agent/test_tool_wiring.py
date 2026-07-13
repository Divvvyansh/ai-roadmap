#!/usr/bin/env python3
"""
Tool wiring verifier — usable two ways:

  CLI (check one tool):
      python test_tool_wiring.py <tool_name>

  pytest (checks every tool registered in TOOL_MAP):
      pytest test_tool_wiring.py -v
"""

import sys
import importlib

import pytest


# ---------------------------------------------------------------------------
# Core check logic (raises AssertionError so pytest can catch it)
# ---------------------------------------------------------------------------

def _collect_errors(tool_name: str) -> list[str]:
    errors = []

    try:
        mod = importlib.import_module("calendar_tools")
        if not hasattr(mod, tool_name):
            errors.append(f"Function '{tool_name}' not found in calendar_tools.py")
    except Exception as e:
        errors.append(f"calendar_tools import error: {e}")

    try:
        schemas_mod = importlib.import_module("tool_schemas")
        registered = [t["name"] for t in schemas_mod.TOOLS]
        if tool_name not in registered:
            errors.append(f"Schema for '{tool_name}' not found in tool_schemas.TOOLS")
    except Exception as e:
        errors.append(f"tool_schemas import error: {e}")

    try:
        agent_mod = importlib.import_module("agent")
        if tool_name not in agent_mod.TOOL_MAP:
            errors.append(f"'{tool_name}' not in agent.TOOL_MAP")
    except Exception as e:
        errors.append(f"agent import error: {e}")

    return errors


# ---------------------------------------------------------------------------
# pytest — parametrized over every tool in TOOL_MAP
# ---------------------------------------------------------------------------

def _all_tool_names():
    try:
        agent_mod = importlib.import_module("agent")
        return list(agent_mod.TOOL_MAP.keys())
    except Exception:
        return []


@pytest.mark.parametrize("tool_name", _all_tool_names())
def test_tool_wiring(tool_name):
    errors = _collect_errors(tool_name)
    assert not errors, "\n".join(errors)


# ---------------------------------------------------------------------------
# CLI — check a single named tool
# ---------------------------------------------------------------------------

def check(tool_name: str):
    errors = _collect_errors(tool_name)
    if errors:
        for err in errors:
            print(f"FAIL: {err}")
        sys.exit(1)
    print(f"OK: '{tool_name}' is correctly wired in calendar_tools.py, tool_schemas.py, and agent.py")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_tool_wiring.py <tool_name>")
        sys.exit(1)
    check(sys.argv[1])