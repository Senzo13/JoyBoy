"""Real stdio MCP protocol calls, with no paid provider or GPU dependency."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_mask_apply_inspect_and_preview_over_stdio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGBA", (73, 47), (10, 20, 30, 127)).save(root / "source.png")
            Image.new("RGBA", (73, 47), "orange").save(root / "candidate.png")
            params = StdioServerParameters(command=sys.executable, args=[
                "-m", "core.bridge.mcp_server", "--data-dir", str(root / "studio"),
                "--allow-root", str(root)], cwd=str(Path(__file__).resolve().parents[1]),
                env={**os.environ, "JOYBOY_HOME": str(root / "home")})
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    self.assertEqual(len(names), 9)
                    self.assertIn("joyboy_edit", names)

                    async def call(name, arguments):
                        result = await session.call_tool(name, arguments)
                        self.assertFalse(result.isError, str(result))
                        return json.loads(result.content[0].text)

                    original = await call("joyboy_import", {"path": str(root / "source.png")})
                    candidate = await call("joyboy_import", {"path": str(root / "candidate.png")})
                    mask = await call("joyboy_mask", {"asset_id": original["id"], "rectangles": [[11, 9, 17, 13]]})
                    result = await call("joyboy_apply", {"asset_id": original["id"], "mask_id": mask["id"], "candidate_id": candidate["id"]})
                    self.assertEqual(result["verification"], {
                        "dimensions_preserved": True, "protected_pixels": 3210,
                        "protected_pixels_changed": 0, "selected_pixels_changed": 221})
                    inspected = await call("joyboy_inspect", {"asset_id": result["id"]})
                    self.assertEqual(inspected["parent_id"], original["id"])
                    preview = await session.call_tool("joyboy_preview", {"asset_id": result["id"]})
                    self.assertFalse(preview.isError)
                    self.assertEqual(preview.content[0].type, "image")
                    escaped = await session.call_tool("joyboy_import", {"path": str(Path(__file__).resolve())})
                    self.assertTrue(escaped.isError)


if __name__ == "__main__":
    unittest.main()
