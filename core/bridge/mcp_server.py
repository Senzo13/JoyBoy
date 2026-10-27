"""JoyBoy MCP tools using the official Python SDK's pinned v1 maintenance line."""
from __future__ import annotations

import argparse
import contextlib
from functools import wraps
import sys

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP, Image as MCPImage
from mcp.types import ToolAnnotations

from core.bridge.studio import Studio
from core.infra.paths import PROJECT_DIR


def create_server(studio):
    server = FastMCP("JoyBoy Light", instructions=(
        "Local image canvas and masked editing. White selects editable pixels. "
        "Import an image, create a mask, then edit via OpenAI API or apply an existing candidate. "
        "API image calls are separately billed. Codex chat uses the official local app-server. "
        "Never call joyboy_chat recursively from a JoyBoy chat."
    ))
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
    creates = ToolAnnotations(readOnlyHint=False, destructiveHint=False)

    def tool(**options):
        def register(function):
            @wraps(function)
            def guarded(*args, **kwargs):
                with contextlib.redirect_stdout(sys.stderr):
                    return function(*args, **kwargs)
            return server.tool(**options)(guarded)
        return register

    @tool(annotations=read_only)
    def joyboy_status() -> dict:
        """Provider readiness, Codex model catalog and centralized capability locks."""
        return studio.status()

    @tool(annotations=creates)
    def joyboy_import(path: str) -> dict:
        """Import an image from an explicitly allowed local folder; return immutable asset ID."""
        return studio.import_image(path)

    @tool(annotations=read_only)
    def joyboy_inspect(asset_id: str) -> dict:
        """Read image/mask metadata, output path and pixel verification report."""
        return studio.inspect(asset_id)

    @tool(annotations=read_only)
    def joyboy_preview(asset_id: str) -> MCPImage:
        """Preview an image asset (thumbnail only; original output stays full size)."""
        from core.bridge.images import png_bytes
        image = studio.image(asset_id)
        image.thumbnail((1024, 1024))
        return MCPImage(data=png_bytes(image), format="png")

    @tool(annotations=creates)
    def joyboy_mask(asset_id: str, rectangles: list[list[int]] | None = None,
                    mask_path: str | None = None) -> dict:
        """Create mask: rectangles [x,y,width,height] or same-size grayscale PNG, white=edit.

        Choose rectangles OR mask_path. Black pixels remain exactly protected.
        """
        if mask_path and rectangles:
            raise ValueError("Choose rectangles OR mask_path")
        data = studio.allowed_file(mask_path).read_bytes() if mask_path else None
        return studio.set_mask(asset_id, rectangles, data)

    @tool(annotations=creates)
    def joyboy_apply(asset_id: str, mask_id: str, candidate_id: str, feather: int = 0) -> dict:
        """Composite an existing candidate through the mask; verify canvas/protected pixels.

        This performs a real local composition, with no model/API call. All canvases must match.
        """
        return studio.apply_candidate(asset_id, mask_id, candidate_id, feather)

    @tool(annotations=creates)
    def joyboy_edit(asset_id: str, mask_id: str, prompt: str, feather: int = 0) -> dict:
        """Billable OpenAI Images edit with an alpha mask, then strict local pixel protection."""
        return studio.edit(asset_id, mask_id, prompt, feather)

    @tool(annotations=creates)
    def joyboy_generate(prompt: str) -> dict:
        """Generate one draft image using OPENAI_API_KEY (separate API billing)."""
        return studio.generate(prompt)

    @tool(annotations=creates)
    def joyboy_chat(text: str, model: str | None = None, thread_id: str | None = None,
                    image_ids: list[str] | None = None) -> dict:
        """Chat through official Codex app-server; model IDs come from joyboy_status.

        Optional image attachments are vision inputs. This exposes no Codex image generation API.
        """
        return studio.chat(text, model, thread_id, image_ids or [])

    return server


def main():
    parser = argparse.ArgumentParser(description="JoyBoy local MCP server (stdio)")
    parser.add_argument("--data-dir")
    parser.add_argument("--allow-root", action="append", default=[])
    args = parser.parse_args()
    load_dotenv(PROJECT_DIR / ".env", override=False)
    # Imported legacy helpers may print diagnostics: stdout is protocol-only.
    with contextlib.redirect_stdout(sys.stderr):
        server = create_server(Studio(args.data_dir, args.allow_root))
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
