"""AI Summarization for Houdini MCP Server.

This module provides server-side AI summarization using Claude to compress
large responses into high-signal, actionable summaries. This reduces token
usage for client AIs while preserving key information.

Uses the Claude API proxy at localhost:8082 for efficient small-model inference.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("houdini_mcp.summarization")

# Configuration
CLAUDE_PROXY_URL = os.getenv("CLAUDE_PROXY_URL", "http://localhost:8082")
SUMMARIZATION_MODEL = os.getenv("SUMMARIZATION_MODEL", "claude-3-5-haiku-latest")
SUMMARIZATION_ENABLED = os.getenv("SUMMARIZATION_ENABLED", "true").lower() == "true"

# Thresholds for automatic summarization (in estimated tokens)
AUTO_SUMMARIZE_THRESHOLD = int(os.getenv("AUTO_SUMMARIZE_THRESHOLD", "5000"))
# Target summary size
TARGET_SUMMARY_TOKENS = int(os.getenv("TARGET_SUMMARY_TOKENS", "500"))


def estimate_tokens(data: Any) -> int:
    """Estimate token count for data.

    Rough estimate: ~4 characters per token for JSON.
    """
    if isinstance(data, str):
        return len(data) // 4
    return len(json.dumps(data, default=str)) // 4


def should_summarize(data: Any, force: bool = False) -> bool:
    """Determine if data should be summarized.

    Args:
        data: The data to potentially summarize
        force: Force summarization regardless of size

    Returns:
        True if summarization should be applied
    """
    if force:
        return True

    if not SUMMARIZATION_ENABLED:
        return False

    return estimate_tokens(data) > AUTO_SUMMARIZE_THRESHOLD


async def summarize_geometry(geo_data: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize geometry data for AI consumption.

    Extracts key insights from geometry statistics:
    - Topology overview (points, primitives, vertices)
    - Bounding box analysis
    - Key attributes
    - Potential issues or notable characteristics

    Args:
        geo_data: Raw geometry summary data

    Returns:
        Original data with 'ai_summary' field added
    """
    prompt = f"""Analyze this Houdini geometry data and provide a concise summary for an AI assistant.

Focus on:
1. Geometry scale and complexity (point/primitive counts)
2. Bounding box size and position
3. Notable attributes (Cd, N, uv, etc.)
4. Any potential issues (empty geometry, unusually high counts)
5. Suggested next steps if relevant

Keep the summary under 200 words. Be technical and precise.

Geometry Data:
```json
{json.dumps(geo_data, indent=2, default=str)[:8000]}
```

Summary:"""

    summary = await _call_claude(prompt)

    if summary:
        geo_data["ai_summary"] = summary
        geo_data["_summarized"] = True

    return geo_data


async def summarize_errors(error_data: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize error/warning data with triage and prioritization.

    Analyzes errors and provides:
    - Error severity ranking
    - Common patterns/root causes
    - Suggested fix order
    - Quick wins vs complex issues

    Args:
        error_data: Raw find_error_nodes output

    Returns:
        Original data with 'ai_summary' and 'prioritized_fixes' fields
    """
    prompt = f"""Analyze these Houdini node errors and provide actionable triage.

For each error category:
1. Identify root cause patterns
2. Prioritize by severity and fix difficulty
3. Suggest fix order (quick wins first)
4. Note any cascading dependencies

Keep the summary under 250 words. Be specific about node paths.

Error Data:
```json
{json.dumps(error_data, indent=2, default=str)[:8000]}
```

Provide:
1. **Priority Fixes** - Most critical errors to fix first
2. **Quick Wins** - Easy fixes that might resolve multiple issues
3. **Root Causes** - Underlying patterns causing errors
4. **Recommendations** - Specific actions to take

Summary:"""

    summary = await _call_claude(prompt)

    if summary:
        error_data["ai_summary"] = summary
        error_data["_summarized"] = True

    return error_data


async def summarize_scene(scene_data: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize scene structure for understanding and optimization.

    Analyzes scene hierarchy and provides:
    - Network organization overview
    - Complexity hotspots
    - Optimization opportunities
    - Recommended cleanup actions

    Args:
        scene_data: Raw serialize_scene output

    Returns:
        Original data with 'ai_summary' field
    """
    prompt = f"""Analyze this Houdini scene structure and provide insights.

Focus on:
1. Network organization and hierarchy depth
2. Node count by type (SOPs, DOPs, ROPs, etc.)
3. Complexity hotspots (deeply nested, high node counts)
4. Potential optimization opportunities
5. Scene cleanliness (unused nodes, naming conventions)

Keep the summary under 200 words. Highlight actionable insights.

Scene Data:
```json
{json.dumps(scene_data, indent=2, default=str)[:10000]}
```

Summary:"""

    summary = await _call_claude(prompt)

    if summary:
        scene_data["ai_summary"] = summary
        scene_data["_summarized"] = True

    return scene_data


async def summarize_render_settings(render_data: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize render configuration for quality/performance analysis.

    Analyzes render settings and provides:
    - Quality vs performance tradeoffs
    - Potential bottlenecks
    - Optimization suggestions
    - Comparison to common presets

    Args:
        render_data: Raw render settings output

    Returns:
        Original data with 'ai_summary' field
    """
    prompt = f"""Analyze these Houdini render settings and provide recommendations.

Evaluate:
1. Quality settings (samples, ray limits, resolution)
2. Performance implications
3. Potential optimizations
4. Comparison to common render presets

Keep the summary under 150 words. Focus on actionable improvements.

Render Settings:
```json
{json.dumps(render_data, indent=2, default=str)[:4000]}
```

Summary:"""

    summary = await _call_claude(prompt)

    if summary:
        render_data["ai_summary"] = summary
        render_data["_summarized"] = True

    return render_data


async def _call_claude(prompt: str) -> Optional[str]:
    """Call Claude API via proxy for summarization.

    Args:
        prompt: The prompt to send

    Returns:
        Claude's response text, or None on error
    """
    if not SUMMARIZATION_ENABLED:
        logger.debug("Summarization disabled, skipping Claude call")
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{CLAUDE_PROXY_URL}/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": SUMMARIZATION_MODEL,
                    "max_tokens": TARGET_SUMMARY_TOKENS * 2,  # Allow some buffer
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

            if response.status_code != 200:
                logger.warning(f"Claude API error: {response.status_code} - {response.text[:200]}")
                return None

            result = response.json()

            # Extract text from response
            if "content" in result and len(result["content"]) > 0:
                return result["content"][0].get("text", "")

            return None

    except httpx.TimeoutException:
        logger.warning("Claude API timeout during summarization")
        return None
    except Exception as e:
        logger.warning(f"Claude API error: {e}")
        return None


def get_summarization_status() -> Dict[str, Any]:
    """Get current summarization configuration status.

    Returns:
        Dict with configuration and health status
    """
    return {
        "enabled": SUMMARIZATION_ENABLED,
        "model": SUMMARIZATION_MODEL,
        "proxy_url": CLAUDE_PROXY_URL,
        "auto_threshold_tokens": AUTO_SUMMARIZE_THRESHOLD,
        "target_summary_tokens": TARGET_SUMMARY_TOKENS,
    }
