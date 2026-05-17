# Nestlyze MCP server

Talk to [Nestlyze](https://nestlyze.com) directly from Claude Desktop, Claude Code, or any other MCP-compatible client. Lets the AI answer questions like *"is 432 Oak St in Palo Alto a good buy?"* by calling the real Nestlyze API.

## Tools exposed

| Tool | What it does |
|------|---|
| `search_listings(city, max_price, ...)` | Browse the listing pool by city/price/beds. |
| `get_listing_details(listing_id)` | Full enriched detail for one home. |
| `get_nestimate(address)` | Just the AI valuation + reasoning bullets (~3s). |
| `analyze_property(address, beds, baths, sqft)` | Full 6-agent due-diligence report (~30-60s). |

Plus one resource:
- `nestlyze://accuracy` — the live MAPE accuracy table (per-metro).

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/wudaming00/nestlyze-mcp.git
cd nestlyze-mcp
pip install -r requirements.txt
```

## Wire into Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "nestlyze": {
      "command": "python",
      "args": ["/absolute/path/to/nestlyze-mcp/nestlyze_mcp.py"]
    }
  }
}
```

Restart Claude Desktop. You should see a 🔌 icon — click to confirm the `nestlyze` server is connected.

## Wire into Claude Code

```bash
claude mcp add nestlyze python /absolute/path/to/nestlyze-mcp/nestlyze_mcp.py
```

## Use against staging / local backend

Set `NESTLYZE_API_BASE`:

```bash
NESTLYZE_API_BASE=http://localhost:8000 python nestlyze_mcp.py
```

## Example prompts (after install)

- "Use the nestlyze tools to find homes in Mountain View, CA under $2M with 3+ beds."
- "Run an analyze_property on 1287 NW 132nd Blvd, Newberry FL."
- "What's Nestimate's published MAPE for the Bay Area?"

## Notes

- The Nestlyze API is rate-limited per IP (~10 analyses/hour anonymous; unlimited with a signed-in account).
- `analyze_property` calls the full 6-agent pipeline — expect 30-60s.
- All requests are unauthenticated by default. If you need to use credits on an account, set `NESTLYZE_BEARER_TOKEN` (not yet wired — file an issue).

## License

MIT — see [LICENSE](LICENSE).
