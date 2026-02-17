"""httpx async GET, 10KB cap. (§4 Phase 4)"""
from __future__ import annotations

import httpx

from multiclaws.tools.registry import Tool

MAX_BYTES = 10 * 1024  # 10KB
TIMEOUT = 10


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "Fetch the text content of a URL (GET only, 10KB cap)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "headers": {"type": "object", "description": "Optional HTTP headers"},
        },
        "required": ["url"],
    }

    async def execute(self, url: str, headers: dict | None = None, **_) -> dict:
        if not url.startswith(("http://", "https://")):
            return {"error": "Only http/https URLs allowed"}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers or {})
                resp.raise_for_status()
                content = resp.content[:MAX_BYTES].decode("utf-8", errors="replace")
                return {
                    "result": content,
                    "status_code": resp.status_code,
                    "url": str(resp.url),
                    "truncated": len(resp.content) > MAX_BYTES,
                }
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {url}"}
        except Exception as e:
            return {"error": str(e)}
