"""Verification tests for the O.S.C.A.R. architectural refactor."""

import json
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name} — {detail}")
        failed += 1


print("=" * 60)
print("VERIFICATION: JSON Extraction (gemini_client)")
print("=" * 60)

from oscar.gemini_client import _extract_json_text, _is_valid_json, _extract_balanced_braces

# Clean JSON
test("Clean JSON",
     _extract_json_text('{"action": "click", "x": 100}') == '{"action": "click", "x": 100}')

# Fenced JSON
test("Fenced ```json block",
     json.loads(_extract_json_text('Here is the action:\n```json\n{"action": "done"}\n```\nDone!'))["action"] == "done")

# JSON with trailing commentary
test("JSON with trailing text",
     json.loads(_extract_json_text('I think we should do this: {"action": "wait"} and that\'s it'))["action"] == "wait")

# Nested JSON
nested = '{"action": "click", "data": {"x": 10, "y": 20}}'
test("Nested JSON objects",
     json.loads(_extract_json_text(nested))["data"]["x"] == 10)

# Deeply nested with strings containing braces
tricky = '{"action": "type", "text": "function() { return {a: 1}; }"}'
result = _extract_json_text(tricky)
test("Strings containing braces",
     json.loads(result)["action"] == "type",
     f"Got: {result[:60]}")

# Malformed input
try:
    _extract_json_text("No JSON here at all.")
    test("Malformed input raises ValueError", False)
except ValueError:
    test("Malformed input raises ValueError", True)

# Balanced brace extraction
test("Balanced braces basic",
     _extract_balanced_braces('hello {"a": 1} world') == '{"a": 1}')

test("Balanced braces nested",
     _extract_balanced_braces('{"a": {"b": 2}}') == '{"a": {"b": 2}}')


print()
print("=" * 60)
print("VERIFICATION: Command Safety (terminal_agent)")
print("=" * 60)

from oscar.agents.terminal_agent import TerminalAgent
from pathlib import Path

agent = TerminalAgent(root_dir=Path.cwd())
cwd = Path.cwd()

test("Format-Table is ALLOWED",
     agent._is_safe_command("Format-Table", cwd))

test("Format-List is ALLOWED",
     agent._is_safe_command("Format-List", cwd))

test("Format-Wide is ALLOWED",
     agent._is_safe_command("Format-Wide", cwd))

test("format C: is BLOCKED (disk format)",
     not agent._is_safe_command("format C:", cwd))

test("format.com is BLOCKED",
     not agent._is_safe_command("format.com C:", cwd))

test("Get-ChildItem is ALLOWED",
     agent._is_safe_command("Get-ChildItem .", cwd))

test("shutdown is BLOCKED",
     not agent._is_safe_command("shutdown /s /t 0", cwd))

test("git reset --hard is BLOCKED",
     not agent._is_safe_command("git reset --hard HEAD", cwd))

test("diskpart is BLOCKED",
     not agent._is_safe_command("diskpart", cwd))

test("ls equivalent is ALLOWED",
     agent._is_safe_command("Get-ChildItem", cwd))


print()
print("=" * 60)
print("VERIFICATION: Grid Overlay (vision/grid_overlay)")
print("=" * 60)

from oscar.vision.grid_overlay import grid_cell_to_pixel, pixel_to_grid_cell

# A1 on 1920x1080 with 10x10 grid
cx, cy = grid_cell_to_pixel("A1", screen_width=1920, screen_height=1080)
test("A1 center pixel",
     cx == 96 and cy == 54,
     f"Got ({cx}, {cy})")

# J10 on 1920x1080
cx, cy = grid_cell_to_pixel("J10", screen_width=1920, screen_height=1080)
test("J10 center pixel",
     cx == 1824 and cy == 1026,
     f"Got ({cx}, {cy})")

# E5 on 1920x1080 — center of grid
cx, cy = grid_cell_to_pixel("E5", screen_width=1920, screen_height=1080)
test("E5 center pixel (mid-grid)",
     cx == 864 and cy == 486,
     f"Got ({cx}, {cy})")

# Reverse: pixel to cell
cell = pixel_to_grid_cell(96, 54, screen_width=1920, screen_height=1080)
test("Pixel (96,54) -> A1",
     cell == "A1",
     f"Got {cell}")

cell = pixel_to_grid_cell(1824, 1026, screen_width=1920, screen_height=1080)
test("Pixel (1824,1026) -> J10",
     cell == "J10",
     f"Got {cell}")

# Invalid cell
try:
    grid_cell_to_pixel("Z99", screen_width=1920, screen_height=1080)
    test("Invalid cell raises ValueError", False)
except ValueError:
    test("Invalid cell raises ValueError", True)


print()
print("=" * 60)
print("VERIFICATION: Tool Registry")
print("=" * 60)

from oscar.tools.tool_registry import ToolRegistry, ToolSpec, get_default_registry

async def dummy_handler(**kw):
    return "ok"

registry = ToolRegistry()
spec = ToolSpec(name="test_tool", description="A test tool", handler=dummy_handler, tags=("test",))
registry.register(spec)

test("Register and get tool",
     registry.get("test_tool") is spec)

test("Tool in registry",
     "test_tool" in registry)

test("List tools",
     len(registry.list_tools()) == 1)

test("List by tags",
     len(registry.list_tools(tags={"test"})) == 1)

test("List by wrong tags",
     len(registry.list_tools(tags={"other"})) == 0)

test("Describe for prompt",
     "test_tool: A test tool" in registry.describe_for_prompt())

registry.unregister("test_tool")
test("Unregister tool",
     registry.get("test_tool") is None)

test("Default registry singleton",
     get_default_registry() is get_default_registry())


print()
print("=" * 60)
print("VERIFICATION: Context Snapshot")
print("=" * 60)

from oscar.context import TaskContext

ctx = TaskContext(task="test", current_working_directory="/tmp")
ctx.browser_url = "https://example.com"
snap = ctx.snapshot()

test("Snapshot is a deep copy",
     snap is not ctx)

test("Snapshot preserves values",
     snap.browser_url == "https://example.com")

ctx.browser_url = "https://changed.com"
test("Snapshot is isolated from mutations",
     snap.browser_url == "https://example.com")


print()
print("=" * 60)
print(f"RESULTS: {passed} passed, {failed} failed")
print("=" * 60)

sys.exit(1 if failed else 0)
