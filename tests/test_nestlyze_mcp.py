import unittest
from unittest.mock import AsyncMock, patch

import nestlyze_mcp as server


class FakeResponse:
    def __init__(self, data, status_code=200, text=""):
        self._data = data
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, *, gets=None, posts=None):
        self.gets = list(gets or [])
        self.posts = list(posts or [])
        self.get_calls = []
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.gets.pop(0)

    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.posts.pop(0)


class NestlyzeMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_listings_clamps_limit_and_returns_compact_rows(self):
        client = FakeClient(gets=[FakeResponse({
            "listings": [{"id": i, "address": f"{i} Main St"} for i in range(30)],
            "total": 30,
        })])
        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result = await server.search_listings(limit=100)

        self.assertEqual(len(result["listings"]), 24)
        self.assertEqual(client.get_calls[0][1]["params"]["limit"], 24)

    async def test_get_listing_details_returns_api_payload(self):
        client = FakeClient(gets=[FakeResponse({"id": 42, "address": "42 Main St"})])
        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result = await server.get_listing_details(42)

        self.assertEqual(result["id"], 42)
        self.assertTrue(client.get_calls[0][0].endswith("/api/v1/listings/42"))

    async def test_get_nestimate_nests_property_details(self):
        client = FakeClient(posts=[FakeResponse({"mid": 1_000_000})])
        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result = await server.get_nestimate(
                "42 Main St", asking_price=1_100_000, beds=3, baths=2, sqft=1500
            )

        payload = client.post_calls[0][1]["json"]
        self.assertEqual(result["mid"], 1_000_000)
        self.assertEqual(payload["asking_price"], 1_100_000)
        self.assertEqual(
            payload["property_details"], {"beds": 3, "baths": 2, "sqft": 1500}
        )
        self.assertNotIn("beds", payload)

    async def test_analyze_property_accepts_production_complete_status(self):
        client = FakeClient(
            posts=[FakeResponse({"job_id": "job-1", "status": "queued"})],
            gets=[
                FakeResponse({"job_id": "job-1", "status": "complete"}),
                FakeResponse({"job_id": "job-1", "status": "complete", "report": {}}),
            ],
        )
        with (
            patch.object(server.httpx, "AsyncClient", return_value=client),
            patch.object(server.asyncio, "sleep", new=AsyncMock()),
        ):
            result = await server.analyze_property("42 Main St")

        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["share_url"], f"{server.BASE_URL}/report?job=job-1")
        self.assertEqual(len(client.get_calls), 2)

    async def test_accuracy_resource_returns_clean_summary(self):
        page = (
            '<html><head><meta name="description" content="Median absolute error '
            '~4.6% (n=16)." /></head></html>'
        )
        client = FakeClient(gets=[FakeResponse({}, text=page)])
        with patch.object(server.httpx, "AsyncClient", return_value=client):
            result = await server.accuracy_resource()

        self.assertIn("~4.6% (n=16)", result)
        self.assertNotIn("<html>", result)


if __name__ == "__main__":
    unittest.main()
