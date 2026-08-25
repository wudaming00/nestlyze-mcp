"""Nestlyze MCP server — exposes the public Nestlyze API as MCP tools.

After install (see README.md), Claude Desktop / Claude Code / any
MCP-compatible client can call:

  - search_listings(city, max_price, min_beds, ...)
      Find homes in the Nestlyze pool.
  - get_listing_details(listing_id)
      Pull the full enriched listing (price, schools, Nestimate, ask history).
  - get_nestimate(address)
      Just the valuation + reasoning bullets for any US address.
  - analyze_property(address, beds, baths, sqft, price)
      Run the full 6-agent due-diligence report (async; polls until ready).

Default base URL is the production API. Override via env NESTLYZE_API_BASE
for staging / local-dev access.
"""
from __future__ import annotations

import asyncio
import html
import os
import re

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("NESTLYZE_API_BASE", "https://nestlyze.com").rstrip("/")
TIMEOUT = httpx.Timeout(60.0, connect=10.0)

mcp = FastMCP("nestlyze")


def _auth_headers() -> dict[str, str]:
    """Attach an account token when the caller explicitly configured one."""
    token = os.environ.get("NESTLYZE_BEARER_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


@mcp.tool()
async def search_listings(
    city: str | None = None,
    state: str | None = None,
    max_price: int | None = None,
    min_price: int | None = None,
    min_beds: int | None = None,
    max_beds: int | None = None,
    limit: int = 12,
) -> dict:
    """Search Nestlyze's listing pool. Returns a compact summary per home
    (id, address, price, beds, baths, sqft, school district, Nestimate hint
    if cached). Pass `city + state` for narrowed results — without them
    you'll get pool-wide first 12 by recency.

    Returns: {listings: [...], count: int, total: int}
    """
    result_limit = max(1, min(int(limit), 24))
    params: dict = {"limit": result_limit}
    if city:
        params["city"] = city
    if state:
        params["state"] = state
    if max_price:
        params["max_price"] = int(max_price)
    if min_price:
        params["min_price"] = int(min_price)
    if min_beds:
        params["min_beds"] = int(min_beds)
    if max_beds:
        params["max_beds"] = int(max_beds)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(
            f"{BASE_URL}/api/v1/listings",
            params=params,
            headers=_auth_headers(),
        )
        r.raise_for_status()
        data = r.json()
    listings = data.get("listings") or data.get("items") or []
    return {
        "listings": [
            {
                "id": lst.get("id"),
                "address": lst.get("address"),
                "city": lst.get("city"),
                "state": lst.get("state"),
                "zip": lst.get("zip"),
                "price": lst.get("price"),
                "beds": lst.get("beds"),
                "baths": lst.get("baths"),
                "sqft": lst.get("sqft"),
                "year_built": lst.get("year_built"),
                "days_on_market": lst.get("days_on_market"),
                "status": lst.get("status"),
                "listing_url": lst.get("listing_url"),
                "url": f"{BASE_URL}/listing/{lst.get('id')}",
            }
            for lst in listings[:result_limit]
        ],
        "count": len(listings),
        "total": data.get("total"),
    }


@mcp.tool()
async def get_listing_details(listing_id: int) -> dict:
    """Fetch the full enriched detail for one listing. Includes price,
    school information, days on market, photos, price history, and the
    district-median comparison when available.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(
            f"{BASE_URL}/api/v1/listings/{int(listing_id)}",
            headers=_auth_headers(),
        )
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def get_nestimate(
    address: str,
    asking_price: float | None = None,
    beds: float | None = None,
    baths: float | None = None,
    sqft: float | None = None,
) -> dict:
    """Get just the Nestimate (AI valuation) for any US address, with
    explanation bullets. Cheap and fast (~3s) — no signup required.

    Returns: {address, mid, low, high, confidence, reasoning: [str], tier}
    """
    payload: dict = {"address": address}
    if asking_price is not None:
        payload["asking_price"] = asking_price
    property_details: dict = {}
    if beds is not None:
        property_details["beds"] = beds
    if baths is not None:
        property_details["baths"] = baths
    if sqft is not None:
        property_details["sqft"] = sqft
    if property_details:
        # The production API expects physical attributes under
        # property_details. Top-level beds/baths/sqft are silently ignored.
        payload["property_details"] = property_details
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(
            f"{BASE_URL}/api/v1/nestimate/compute",
            json=payload,
            headers=_auth_headers(),
        )
        r.raise_for_status()
        return r.json()


@mcp.tool()
async def analyze_property(
    address: str,
    beds: int | None = None,
    baths: int | None = None,
    sqft: int | None = None,
    asking_price: int | None = None,
    report_type: str = "buy",
) -> dict:
    """Run the FULL 6-agent Nestlyze analysis on a US property. This is the
    deep due-diligence report — market, financial, structural, environmental,
    neighborhood, legal — synthesized into one document with risk flags.

    Takes ~30-60 seconds. Returns the executive summary + risk flags + next
    steps + a shareable URL. The full report is browsable at the returned URL.

    Note: anonymous users get 1 free analysis per IP. Subsequent calls from
    the same IP require a signed-in account with credits.
    """
    form_data: dict = {"address": address, "report_type": report_type}
    if beds is not None:
        form_data["beds"] = str(beds)
    if baths is not None:
        form_data["baths"] = str(baths)
    if sqft is not None:
        form_data["sqft"] = str(sqft)
    if asking_price is not None:
        form_data["asking_price"] = str(asking_price)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        headers = _auth_headers()
        r = await client.post(
            f"{BASE_URL}/api/v1/analyze",
            data=form_data,
            headers=headers,
        )
        r.raise_for_status()
        kickoff = r.json()
        job_id = kickoff.get("job_id")
        if not job_id:
            # Some responses return the cached report directly when address
            # has been analyzed before — short-circuit without polling.
            return kickoff
        # Poll for completion. /api/v1/progress/{job_id} returns a status
        # field; /api/v1/report/{job_id} returns the full report once ready.
        # Total wait capped at 120s to keep MCP calls bounded.
        if kickoff.get("status") != "cached":
            for _ in range(60):
                await asyncio.sleep(2)
                p = await client.get(
                    f"{BASE_URL}/api/v1/progress/{job_id}",
                    headers=headers,
                )
                if p.status_code != 200:
                    continue
                prog = p.json()
                status = prog.get("status")
                if status in ("complete", "done", "completed", "ready"):
                    break
                if status in ("failed", "error"):
                    raise RuntimeError(
                        f"Analysis failed: {prog.get('error', 'unknown')}"
                    )
            else:
                raise TimeoutError(
                    "Nestlyze analysis did not finish within 120 seconds"
                )
        rep = await client.get(
            f"{BASE_URL}/api/v1/report/{job_id}",
            headers=headers,
        )
        rep.raise_for_status()
        report = rep.json()
        if report.get("status") not in ("complete", "done", "completed", "ready"):
            raise RuntimeError(
                f"Analysis report is not ready: {report.get('status', 'unknown')}"
            )
        report["share_url"] = f"{BASE_URL}/report?job={job_id}"
        return report


@mcp.resource("nestlyze://accuracy")
async def accuracy_resource() -> str:
    """Published Nestimate accuracy summary with sample size and date.
    Loaded from the public page's canonical description so it stays in sync.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(
            f"{BASE_URL}/nestimate-accuracy",
            headers={"User-Agent": "Googlebot", **_auth_headers()},
        )
        r.raise_for_status()
        match = re.search(
            r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
            r.text,
            flags=re.IGNORECASE,
        )
        summary = html.unescape(match.group(1)).strip() if match else (
            "The public accuracy page did not expose a machine-readable summary."
        )
        return f"{summary}\n\nSource: {BASE_URL}/nestimate-accuracy"


if __name__ == "__main__":
    mcp.run()
