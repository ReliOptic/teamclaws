"""File operations — all via safe_path. (§7-1)"""
from __future__ import annotations

from multiclaws.tools.registry import Tool
from multiclaws.tools.sandbox import safe_path, SecurityError


class FileReadTool(Tool):
    name = "file_read"
    description = "Read text content of a file within the workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path within workspace"},
            "max_bytes": {"type": "integer", "description": "Max bytes to read (default 32768)"},
        },
        "required": ["path"],
    }

    async def execute(self, path: str, max_bytes: int = 32768, **_) -> dict:
        try:
            p = safe_path(path)
            if not p.exists():
                return {"error": f"File not found: {path}"}
            content = p.read_bytes()[:max_bytes].decode("utf-8", errors="replace")
            return {"result": content, "path": str(p), "size": p.stat().st_size}
        except SecurityError as e:
            return {"error": str(e)}


class FileWriteTool(Tool):
    name = "file_write"
    description = "Write text content to a file within the workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path within workspace"},
            "content": {"type": "string", "description": "Text content to write"},
            "append": {"type": "boolean", "description": "Append instead of overwrite (default false)"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, path: str, content: str, append: bool = False, **_) -> dict:
        try:
            p = safe_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with p.open(mode, encoding="utf-8") as f:
                f.write(content)
            return {"result": "ok", "path": str(p), "bytes": len(content.encode())}
        except SecurityError as e:
            return {"error": str(e)}


class FileListTool(Tool):
    name = "file_list"
    description = "List files and directories within a workspace path."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path (default: root)"},
            "pattern": {"type": "string", "description": "Glob pattern (default: *)"},
        },
        "required": [],
    }

    async def execute(self, path: str = ".", pattern: str = "*", **_) -> dict:
        try:
            p = safe_path(path)
            entries = [
                {"name": e.name, "type": "dir" if e.is_dir() else "file",
                 "size": e.stat().st_size if e.is_file() else 0}
                for e in sorted(p.glob(pattern))[:200]
            ]
            return {"result": entries, "path": str(p)}
        except SecurityError as e:
            return {"error": str(e)}
