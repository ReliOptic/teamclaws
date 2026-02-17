"""
AOL: n8n webhook trigger. MultiClaws decides, n8n executes. (§10)
Simple httpx POST — n8n handles retries, scheduling, chain execution.
"""
from __future__ import annotations

import httpx
from multiclaws.utils.logger import get_logger

log = get_logger("automation.n8n")
TIMEOUT = 10


async def trigger_webhook(
    base_url: str,
    workflow_name: str,
    payload: dict,
) -> dict:
    """POST to n8n webhook. Returns response JSON or error dict."""
    if not base_url:
        return {"error": "N8N_WEBHOOK_BASE not configured"}

    url = f"{base_url.rstrip('/')}/{workflow_name}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return {"result": "triggered", "status": resp.status_code,
                    "response": resp.text[:1024]}
    except httpx.HTTPStatusError as e:
        log.error("n8n webhook %s failed: %s", workflow_name, e)
        return {"error": f"HTTP {e.response.status_code}", "workflow": workflow_name}
    except Exception as e:
        log.error("n8n trigger error: %s", e)
        return {"error": str(e)}
