"""Tests for custom SRD content endpoints (Phase 4).

MongoDB is mocked via a lightweight in-memory store so these tests run
without a live MongoDB connection.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# In-memory MongoDB stub
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, matched: int = 1, deleted: int = 0) -> None:
        self.matched_count = matched
        self.deleted_count = deleted


class _FakeCollection:
    """Minimal async-compatible Motor collection stub backed by a list."""

    def __init__(self) -> None:
        self._docs: list[dict[str, Any]] = []

    async def find_one(self, query: dict) -> dict | None:
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    def find(self, query: dict):  # noqa: ANN201
        return _FakeCursor([d for d in self._docs if all(d.get(k) == v for k, v in query.items())])

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(doc)

    async def replace_one(self, query: dict, replacement: dict) -> _FakeResult:
        for i, doc in enumerate(self._docs):
            if all(doc.get(k) == v for k, v in query.items()):
                self._docs[i] = dict(replacement)
                return _FakeResult(matched=1)
        return _FakeResult(matched=0)

    async def delete_one(self, query: dict) -> _FakeResult:
        for i, doc in enumerate(self._docs):
            if all(doc.get(k) == v for k, v in query.items()):
                del self._docs[i]
                return _FakeResult(deleted=1)
        return _FakeResult(deleted=0)


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self._pos = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._pos >= len(self._docs):
            raise StopAsyncIteration
        doc = self._docs[self._pos]
        self._pos += 1
        return doc


class _FakeDatabase:
    """Motor database stub that creates collections on first access."""

    def __init__(self) -> None:
        self._collections: dict[str, _FakeCollection] = {}
        self.campaign_overrides = _FakeCollection()

    def __getitem__(self, name: str) -> _FakeCollection:
        if name not in self._collections:
            self._collections[name] = _FakeCollection()
        return self._collections[name]


# ---------------------------------------------------------------------------
# Fixture: api_client with mocked MongoDB
# ---------------------------------------------------------------------------


@pytest.fixture
async def srd_db() -> _FakeDatabase:
    """A fresh in-memory MongoDB stub for each test."""
    return _FakeDatabase()


@pytest.fixture
async def srd_client(api_client: AsyncClient, srd_db: _FakeDatabase) -> AsyncClient:
    """api_client with get_srd_db patched to return the in-memory stub."""
    with patch("tavern.api.srd.get_srd_db", return_value=srd_db):
        yield api_client


# ---------------------------------------------------------------------------
# Instance Library — POST /api/srd/{collection}
# ---------------------------------------------------------------------------


class TestCreateCustomDocument:
    async def test_create_returns_201(self, srd_client: AsyncClient) -> None:
        resp = await srd_client.post(
            "/api/srd/monsters",
            json={"index": "test-goblin", "name": "Test Goblin", "hp": 7},
        )
        assert resp.status_code == 201
        assert resp.json()["index"] == "test-goblin"

    async def test_index_lowercased(self, srd_client: AsyncClient) -> None:
        resp = await srd_client.post(
            "/api/srd/spells",
            json={"index": "Fireball", "name": "Fireball"},
        )
        assert resp.status_code == 201
        assert resp.json()["index"] == "fireball"

    async def test_duplicate_index_returns_400(self, srd_client: AsyncClient) -> None:
        payload = {"index": "dup-item", "name": "Duplicate"}
        await srd_client.post("/api/srd/equipment", json=payload)
        resp = await srd_client.post("/api/srd/equipment", json=payload)
        assert resp.status_code == 400
        assert resp.json()["error"] == "index_conflict"

    async def test_missing_index_returns_400(self, srd_client: AsyncClient) -> None:
        resp = await srd_client.post("/api/srd/monsters", json={"name": "No Index"})
        assert resp.status_code == 400
        assert resp.json()["error"] == "missing_index"

    async def test_missing_name_returns_400(self, srd_client: AsyncClient) -> None:
        resp = await srd_client.post("/api/srd/monsters", json={"index": "no-name"})
        assert resp.status_code == 400
        assert resp.json()["error"] == "missing_name"

    async def test_invalid_collection_returns_400(self, srd_client: AsyncClient) -> None:
        resp = await srd_client.post(
            "/api/srd/dragons",
            json={"index": "test", "name": "Test"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_collection"


# ---------------------------------------------------------------------------
# Instance Library — GET /api/srd/{collection}
# ---------------------------------------------------------------------------


class TestListCustomDocuments:
    async def test_empty_collection_returns_empty_list(self, srd_client: AsyncClient) -> None:
        resp = await srd_client.get("/api/srd/monsters")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_lists_inserted_documents(self, srd_client: AsyncClient) -> None:
        await srd_client.post("/api/srd/monsters", json={"index": "a", "name": "A"})
        await srd_client.post("/api/srd/monsters", json={"index": "b", "name": "B"})
        resp = await srd_client.get("/api/srd/monsters")
        assert resp.status_code == 200
        indices = [d["index"] for d in resp.json()]
        assert "a" in indices
        assert "b" in indices

    async def test_invalid_collection_returns_400(self, srd_client: AsyncClient) -> None:
        resp = await srd_client.get("/api/srd/dragons")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Instance Library — GET /api/srd/{collection}/{index}
# ---------------------------------------------------------------------------


class TestGetCustomDocument:
    async def test_get_existing_document(self, srd_client: AsyncClient) -> None:
        await srd_client.post("/api/srd/feats", json={"index": "test-feat", "name": "Test Feat"})
        resp = await srd_client.get("/api/srd/feats/test-feat")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Feat"

    async def test_get_nonexistent_returns_404(self, srd_client: AsyncClient) -> None:
        resp = await srd_client.get("/api/srd/monsters/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Instance Library — PUT /api/srd/{collection}/{index}
# ---------------------------------------------------------------------------


class TestReplaceCustomDocument:
    async def test_replace_existing_document(self, srd_client: AsyncClient) -> None:
        await srd_client.post("/api/srd/conditions", json={"index": "dazed", "name": "Dazed"})
        resp = await srd_client.put(
            "/api/srd/conditions/dazed",
            json={"index": "dazed", "name": "Dazed (Updated)", "description": "New desc"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Dazed (Updated)"

    async def test_replace_nonexistent_returns_404(self, srd_client: AsyncClient) -> None:
        resp = await srd_client.put(
            "/api/srd/monsters/ghost",
            json={"index": "ghost", "name": "Ghost"},
        )
        assert resp.status_code == 404

    async def test_index_mismatch_returns_400(self, srd_client: AsyncClient) -> None:
        resp = await srd_client.put(
            "/api/srd/monsters/ghost",
            json={"index": "banshee", "name": "Banshee"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "index_mismatch"


# ---------------------------------------------------------------------------
# Instance Library — DELETE /api/srd/{collection}/{index}
# ---------------------------------------------------------------------------


class TestDeleteCustomDocument:
    async def test_delete_existing_returns_204(self, srd_client: AsyncClient) -> None:
        await srd_client.post("/api/srd/spells", json={"index": "boom", "name": "Boom"})
        resp = await srd_client.delete("/api/srd/spells/boom")
        assert resp.status_code == 204

    async def test_delete_nonexistent_returns_404(self, srd_client: AsyncClient) -> None:
        resp = await srd_client.delete("/api/srd/spells/nonexistent")
        assert resp.status_code == 404

    async def test_deleted_document_not_found(self, srd_client: AsyncClient) -> None:
        await srd_client.post("/api/srd/monsters", json={"index": "temp", "name": "Temp"})
        await srd_client.delete("/api/srd/monsters/temp")
        resp = await srd_client.get("/api/srd/monsters/temp")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Campaign Overrides — helpers
# ---------------------------------------------------------------------------


async def _create_campaign(client: AsyncClient) -> str:
    resp = await client.post("/api/campaigns", json={"name": "Override Test Campaign"})
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Campaign Overrides — POST
# ---------------------------------------------------------------------------


class TestCreateCampaignOverride:
    async def test_create_override_returns_201(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        resp = await srd_client.post(
            f"/api/campaigns/{cid}/overrides/monsters",
            json={"index": "custom-goblin", "name": "Custom Goblin", "hp": 99},
        )
        assert resp.status_code == 201
        assert resp.json()["index"] == "custom-goblin"

    async def test_create_override_unknown_campaign_returns_404(
        self, srd_client: AsyncClient
    ) -> None:
        fake_id = uuid.uuid4()
        resp = await srd_client.post(
            f"/api/campaigns/{fake_id}/overrides/monsters",
            json={"index": "x", "name": "X"},
        )
        assert resp.status_code == 404

    async def test_duplicate_override_returns_400(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        payload = {"index": "dup", "name": "Dup"}
        await srd_client.post(f"/api/campaigns/{cid}/overrides/spells", json=payload)
        resp = await srd_client.post(f"/api/campaigns/{cid}/overrides/spells", json=payload)
        assert resp.status_code == 400
        assert resp.json()["error"] == "index_conflict"

    async def test_invalid_collection_returns_400(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        resp = await srd_client.post(
            f"/api/campaigns/{cid}/overrides/dragons",
            json={"index": "x", "name": "X"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Campaign Overrides — GET list
# ---------------------------------------------------------------------------


class TestListCampaignOverrides:
    async def test_empty_list(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        resp = await srd_client.get(f"/api/campaigns/{cid}/overrides/monsters")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_lists_created_overrides(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        await srd_client.post(
            f"/api/campaigns/{cid}/overrides/monsters",
            json={"index": "m1", "name": "M1"},
        )
        await srd_client.post(
            f"/api/campaigns/{cid}/overrides/monsters",
            json={"index": "m2", "name": "M2"},
        )
        resp = await srd_client.get(f"/api/campaigns/{cid}/overrides/monsters")
        assert resp.status_code == 200
        indices = [d["index"] for d in resp.json()]
        assert "m1" in indices
        assert "m2" in indices

    async def test_unknown_campaign_returns_404(self, srd_client: AsyncClient) -> None:
        fake_id = uuid.uuid4()
        resp = await srd_client.get(f"/api/campaigns/{fake_id}/overrides/monsters")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Campaign Overrides — GET single
# ---------------------------------------------------------------------------


class TestGetCampaignOverride:
    async def test_get_existing_override(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        await srd_client.post(
            f"/api/campaigns/{cid}/overrides/feats",
            json={"index": "super-feat", "name": "Super Feat"},
        )
        resp = await srd_client.get(f"/api/campaigns/{cid}/overrides/feats/super-feat")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Super Feat"

    async def test_get_nonexistent_returns_404(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        resp = await srd_client.get(f"/api/campaigns/{cid}/overrides/monsters/ghost")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Campaign Overrides — PUT
# ---------------------------------------------------------------------------


class TestReplaceCampaignOverride:
    async def test_replace_override(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        await srd_client.post(
            f"/api/campaigns/{cid}/overrides/monsters",
            json={"index": "ogre", "name": "Ogre", "hp": 59},
        )
        resp = await srd_client.put(
            f"/api/campaigns/{cid}/overrides/monsters/ogre",
            json={"index": "ogre", "name": "Big Ogre", "hp": 80},
        )
        assert resp.status_code == 200
        assert resp.json()["hp"] == 80

    async def test_replace_nonexistent_returns_404(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        resp = await srd_client.put(
            f"/api/campaigns/{cid}/overrides/monsters/ghost",
            json={"index": "ghost", "name": "Ghost"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Campaign Overrides — DELETE
# ---------------------------------------------------------------------------


class TestDeleteCampaignOverride:
    async def test_delete_override_returns_204(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        await srd_client.post(
            f"/api/campaigns/{cid}/overrides/spells",
            json={"index": "temp-spell", "name": "Temp"},
        )
        resp = await srd_client.delete(f"/api/campaigns/{cid}/overrides/spells/temp-spell")
        assert resp.status_code == 204

    async def test_delete_nonexistent_returns_404(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        resp = await srd_client.delete(f"/api/campaigns/{cid}/overrides/monsters/ghost")
        assert resp.status_code == 404

    async def test_deleted_override_not_found(self, srd_client: AsyncClient) -> None:
        cid = await _create_campaign(srd_client)
        await srd_client.post(
            f"/api/campaigns/{cid}/overrides/monsters",
            json={"index": "temp", "name": "Temp"},
        )
        await srd_client.delete(f"/api/campaigns/{cid}/overrides/monsters/temp")
        resp = await srd_client.get(f"/api/campaigns/{cid}/overrides/monsters/temp")
        assert resp.status_code == 404
