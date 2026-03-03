"""
APEX SWARM - Agent Tools Module
Gives agents real capabilities beyond text generation.

Tools:
  - web_search: Search the web via DuckDuckGo HTML
  - fetch_url: Read any webpage content
  - crypto_prices: Live prices from CoinGecko free API
  - run_code: Execute Python in a restricted sandbox

File: agent_tools.py
"""

import asyncio
import html
import json
import logging
import re
import sys
from io import StringIO
from typing import Any

import httpx

logger = logging.getLogger("apex-swarm")

# ─── TOOL DEFINITIONS (for Claude function calling) ───────

TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": "Search the web for current information. Returns top results with titles, URLs, and snippets. Use for news, prices, facts, research.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch and read the text content of any webpage URL. Returns the main text content. Use when you need to read an article, documentation, or any web page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to fetch (https://...)"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "crypto_prices",
        "description": "Get live cryptocurrency prices, market cap, 24h change, and volume from CoinGecko. Use for any crypto/token price lookups.",
        "input_schema": {
            "type": "object",
            "properties": {
                "coins": {
                    "type": "string",
                    "description": "Comma-separated CoinGecko IDs (e.g. 'bitcoin,ethereum,solana')",
                },
                "vs_currency": {
                    "type": "string",
                    "description": "Currency to price against (default: usd)",
                    "default": "usd",
                },
            },
            "required": ["coins"],
        },
    },
    {
        "name": "run_code",
        "description": "Execute Python code and return the output. Use for calculations, data processing, analysis. Code runs in a sandbox with no network or file access.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"}
            },
            "required": ["code"],
        },
    },
]

# Map agent categories to which tools they can use
CATEGORY_TOOLS = {
    "Crypto & DeFi": ["web_search", "fetch_url", "crypto_prices", "run_code"],
    "Coding & Dev": ["web_search", "fetch_url", "run_code"],
    "Writing & Content": ["web_search", "fetch_url"],
    "Data & Research": ["web_search", "fetch_url", "run_code"],
    "Business & Strategy": ["web_search", "fetch_url", "run_code"],
    "Productivity": ["web_search", "fetch_url"],
}


def get_tools_for_agent(category: str) -> list[dict]:
    """Return tool definitions available for an agent category."""
    allowed = CATEGORY_TOOLS.get(category, ["web_search", "fetch_url"])
    return [t for t in TOOL_DEFINITIONS if t["name"] in allowed]


# ─── TOOL IMPLEMENTATIONS ─────────────────────────────────

async def tool_web_search(query: str) -> str:
    """Search via DuckDuckGo HTML and parse results."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; ApexSwarm/2.1)"},
            )
        if resp.status_code != 200:
            return f"Search failed (HTTP {resp.status_code})"

        text = resp.text
        results = []
        snippets = re.findall(
            r'<a rel="nofollow" class="result__a" href="([^"]*)"[^>]*>(.*?)</a>.*?<a class="result__snippet"[^>]*>(.*?)</a>',
            text,
            re.DOTALL,
        )
        if not snippets:
            snippets_simple = re.findall(
                r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                text,
                re.DOTALL,
            )
            for url, title in snippets_simple[:5]:
                clean_title = html.unescape(re.sub(r"<[^>]+>", "", title).strip())
                results.append(f"- {clean_title}\n  {url}")
        else:
            for url, title, snippet in snippets[:5]:
                clean_title = html.unescape(re.sub(r"<[^>]+>", "", title).strip())
                clean_snippet = html.unescape(re.sub(r"<[^>]+>", "", snippet).strip())
                results.append(f"- {clean_title}\n  {url}\n  {clean_snippet}")

        if not results:
            return f"No results found for: {query}"
        return f"Search results for '{query}':\n\n" + "\n\n".join(results)
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return f"Search error: {str(e)}"


async def tool_fetch_url(url: str) -> str:
    """Fetch a URL and return clean text content."""
    try:
        if not url.startswith(("http://", "https://")):
            return "Invalid URL — must start with http:// or https://"

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ApexSwarm/2.1)"},
            )
        if resp.status_code != 200:
            return f"Failed to fetch URL (HTTP {resp.status_code})"

        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            try:
                return json.dumps(resp.json(), indent=2)[:8000]
            except Exception:
                pass

        text = resp.text
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL)
        text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL)
        text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 6000:
            text = text[:6000] + "\n\n[Content truncated at 6000 chars]"
        return text if text else "Page returned no readable text content."
    except Exception as e:
        logger.error(f"URL fetch failed: {e}")
        return f"Fetch error: {str(e)}"


async def tool_crypto_prices(coins: str, vs_currency: str = "usd") -> str:
    """Get live crypto prices from CoinGecko free API."""
    try:
        coin_list = [c.strip().lower() for c in coins.split(",") if c.strip()]
        if not coin_list:
            return "No coins specified"
        ids = ",".join(coin_list[:10])

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={
                    "ids": ids,
                    "vs_currencies": vs_currency,
                    "include_market_cap": "true",
                    "include_24hr_vol": "true",
                    "include_24hr_change": "true",
                },
            )
        if resp.status_code != 200:
            return f"CoinGecko API error (HTTP {resp.status_code})"

        data = resp.json()
        if not data:
            return f"No price data found for: {ids}. Check coin IDs at coingecko.com."

        def fmt_num(n):
            if not n:
                return "N/A"
            if n >= 1_000_000_000:
                return f"${n/1_000_000_000:.2f}B"
            if n >= 1_000_000:
                return f"${n/1_000_000:.2f}M"
            return f"${n:,.0f}"

        lines = [f"Live Crypto Prices ({vs_currency.upper()}):\n"]
        for coin_id, info in data.items():
            price = info.get(vs_currency, "N/A")
            change = info.get(f"{vs_currency}_24h_change", 0)
            mcap = info.get(f"{vs_currency}_market_cap", 0)
            vol = info.get(f"{vs_currency}_24h_vol", 0)
            change_str = f"+{change:.2f}%" if change and change > 0 else f"{change:.2f}%" if change else "N/A"
            price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else str(price)
            lines.append(
                f"**{coin_id.upper()}**: {price_str} ({change_str})\n"
                f"  Market Cap: {fmt_num(mcap)} | 24h Volume: {fmt_num(vol)}"
            )
        return "\n\n".join(lines)
    except Exception as e:
        logger.error(f"Crypto prices failed: {e}")
        return f"Price lookup error: {str(e)}"


def tool_run_code(code: str) -> str:
    """Execute Python code in a restricted sandbox."""
    BLOCKED = [
        "import os", "import sys", "import subprocess", "import shutil",
        "__import__", "open(", "import socket", "import requests",
        "import httpx", "import urllib", "import ctypes", "import pickle",
        "import shelve", "breakpoint(", "import signal", "import threading",
    ]
    for blocked in BLOCKED:
        if blocked in code:
            return f"Blocked: '{blocked}' is not allowed in the sandbox."

    old_stdout = sys.stdout
    old_stderr = sys.stderr
    captured_out = StringIO()
    captured_err = StringIO()

    import math as _math
    import json as _json

    safe_globals = {
        "__builtins__": {
            "print": print, "range": range, "len": len, "int": int,
            "float": float, "str": str, "list": list, "dict": dict,
            "tuple": tuple, "set": set, "bool": bool, "type": type,
            "abs": abs, "round": round, "min": min, "max": max,
            "sum": sum, "sorted": sorted, "enumerate": enumerate,
            "zip": zip, "map": map, "filter": filter, "reversed": reversed,
            "isinstance": isinstance, "issubclass": issubclass,
            "hasattr": hasattr, "getattr": getattr, "setattr": setattr,
            "ValueError": ValueError, "TypeError": TypeError,
            "KeyError": KeyError, "IndexError": IndexError,
            "ZeroDivisionError": ZeroDivisionError, "Exception": Exception,
            "True": True, "False": False, "None": None,
        },
        "math": _math,
        "json": _json,
    }

    try:
        # Add statistics if available
        import statistics as _stats
        safe_globals["statistics"] = _stats
    except ImportError:
        pass

    try:
        sys.stdout = captured_out
        sys.stderr = captured_err
        exec(code, safe_globals)
        stdout_val = captured_out.getvalue()
        stderr_val = captured_err.getvalue()
        output = ""
        if stdout_val:
            output += stdout_val
        if stderr_val:
            output += "\nSTDERR:\n" + stderr_val
        if not output.strip():
            output = "(Code executed successfully, no output)"
        if len(output) > 4000:
            output = output[:4000] + "\n\n[Output truncated at 4000 chars]"
        return output
    except Exception as e:
        return f"Code execution error: {type(e).__name__}: {str(e)}"
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


# ─── TOOL DISPATCHER ──────────────────────────────────────

# MCP registry reference (set by main.py at startup)
_mcp_registry = None
_mcp_user_key = None


def set_mcp_registry(registry, user_key_col="user_api_key"):
    """Called by main.py to wire MCP registry into tool execution."""
    global _mcp_registry
    _mcp_registry = registry


async def execute_tool(tool_name: str, tool_input: dict, user_api_key: str = None) -> str:
    """Execute a tool call and return the result string.
    Built-in tools are handled directly. Unknown tools are routed to MCP registry."""
    try:
        if tool_name == "web_search":
            return await tool_web_search(tool_input.get("query", ""))
        elif tool_name == "fetch_url":
            return await tool_fetch_url(tool_input.get("url", ""))
        elif tool_name == "crypto_prices":
            return await tool_crypto_prices(
                tool_input.get("coins", ""),
                tool_input.get("vs_currency", "usd"),
            )
        elif tool_name == "run_code":
            return tool_run_code(tool_input.get("code", ""))
        else:
            # Route to MCP registry for user-registered tools
            if _mcp_registry and user_api_key:
                return await _execute_mcp_tool(tool_name, tool_input, user_api_key)
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        logger.error(f"Tool execution error ({tool_name}): {e}")
        return f"Tool error: {str(e)}"


async def _execute_mcp_tool(tool_name: str, tool_input: dict, user_api_key: str) -> str:
    """Find and execute a registered MCP tool by name."""
    try:
        # Find tool by name
        tools = await _mcp_registry.get_tools(user_api_key)
        tool_match = None
        for t in tools:
            # Match by exact name or tool_id
            if t["name"].lower().replace(" ", "_") == tool_name.lower() or t["tool_id"] == tool_name:
                tool_match = t
                break

        if not tool_match:
            return f"MCP tool '{tool_name}' not found in your registered tools"

        result = await _mcp_registry.execute_tool(tool_match["tool_id"], user_api_key, input_data=tool_input)
        if "error" in result:
            return f"MCP tool error: {result['error']}"

        # Format result for Claude
        return f"MCP Tool '{tool_match['name']}' result (HTTP {result.get('status_code', '?')}):\n{json.dumps(result.get('result', {}), indent=2)[:4000]}"
    except Exception as e:
        logger.error(f"MCP tool execution failed ({tool_name}): {e}")
        return f"MCP tool error: {str(e)}"


def get_mcp_tool_definitions(mcp_tools: list[dict]) -> list[dict]:
    """Convert registered MCP tools into Claude tool_use format."""
    defs = []
    for t in mcp_tools:
        tool_name = t["name"].lower().replace(" ", "_").replace("-", "_")
        defs.append({
            "name": tool_name,
            "description": f"[MCP] {t['description']}. Calls: {t['method']} {t['endpoint_url'][:80]}",
            "input_schema": {
                "type": "object",
                "properties": {
                    "input_data": {
                        "type": "object",
                        "description": "Key-value pairs to pass to the API. Keys will be substituted into URL template {placeholders} and request body.",
                    },
                },
                "required": [],
            },
        })
    return defs


# ─── AGENTIC EXECUTION (multi-turn with tools) ────────────

async def execute_with_tools(
    api_key: str,
    model: str,
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    max_turns: int = 5,
    user_api_key: str = None,
    mcp_tools: list[dict] = None,
) -> str:
    """
    Run Claude with tool use in a loop.
    Claude can call built-in tools AND registered MCP tools.
    Returns the final text response.
    """
    messages = [{"role": "user", "content": user_message}]
    final_text = ""

    # Merge built-in tools with MCP tool definitions
    all_tools = list(tools)
    if mcp_tools:
        mcp_defs = get_mcp_tool_definitions(mcp_tools)
        all_tools.extend(mcp_defs)

    for turn in range(max_turns):
        async with httpx.AsyncClient(timeout=45.0) as client:
            payload = {
                "model": model,
                "max_tokens": 2048,
                "system": system_prompt,
                "messages": messages,
            }
            if all_tools:
                payload["tools"] = all_tools

            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )

        if resp.status_code != 200:
            logger.error(f"Claude API error ({resp.status_code}): {resp.text[:200]}")
            return f"Agent error: Claude API returned {resp.status_code}"

        data = resp.json()
        stop_reason = data.get("stop_reason", "")
        content_blocks = data.get("content", [])

        text_parts = []
        tool_calls = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append(block)

        if text_parts:
            final_text = "\n".join(text_parts)

        # If no tool calls, we're done
        if stop_reason != "tool_use" or not tool_calls:
            break

        # Add assistant response then tool results
        messages.append({"role": "assistant", "content": content_blocks})

        tool_results = []
        for tc in tool_calls:
            logger.info(f"Tool call: {tc['name']}({json.dumps(tc.get('input', {}))[:100]})")
            result = await execute_tool(tc["name"], tc.get("input", {}), user_api_key=user_api_key)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    return final_text
# force rebuild
