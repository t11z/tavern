"""Custom SRD content endpoints.

Instance Library
----------------
Provides CRUD for instance-level custom content stored in MongoDB
``custom_{collection}`` collections.  Custom documents here shadow the SRD
baseline for all campaigns on this instance.

Campaign Overrides
------------------
Provides CRUD for campaign-scoped content stored in the
``campaign_overrides`` collection.  Documents here shadow both the SRD
baseline and the Instance Library, but only within the specified campaign.

Supported collections
---------------------
``monsters``, ``spells``, ``classes``, ``species``, ``backgrounds``,
``feats``, ``conditions``, ``equipment``, ``magic-items``

Auth note
---------
Authentication is not yet implemented (ADR-0006 stubs).  All endpoints
accept unauthenticated requests.

Document format
---------------
All documents must include an ``index`` field (lowercase slug, unique within
the collection) and a ``name`` field.  Additional fields are collection-
specific and are stored as-is.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tavern.api.dependencies import get_db_session
from tavern.api.errors import bad_request, not_found
from tavern.models.campaign import Campaign
from tavern.srd_db import get_srd_db

_ALLOWED_COLLECTIONS = frozenset(
    {
        "monsters",
        "spells",
        "classes",
        "species",
        "backgrounds",
        "feats",
        "conditions",
        "equipment",
        "magic-items",
    }
)

# Maps external (user-facing) collection names to 5e-database MongoDB collection names.
# The 5e-database uses legacy "races" naming; Tavern's public API uses "species" per SRD 5.2.1.
_MONGO_COLLECTION = {
    "species": "races",
}


def _mongo_collection(collection: str) -> str:
    """Return the MongoDB collection name for a user-facing *collection* name."""
    return _MONGO_COLLECTION.get(collection, collection)


DbSession = Annotated[AsyncSession, Depends(get_db_session)]

# ---------------------------------------------------------------------------
# Instance Library router — /api/srd/{collection}
# ---------------------------------------------------------------------------

srd_router = APIRouter(prefix="/srd", tags=["srd"])


def _validate_collection(collection: str) -> None:
    if collection not in _ALLOWED_COLLECTIONS:
        raise bad_request(
            "invalid_collection",
            f"Collection {collection!r} is not supported. "
            f"Allowed: {', '.join(sorted(_ALLOWED_COLLECTIONS))}",
        )


def _validate_document(body: dict[str, Any]) -> None:
    if "index" not in body:
        raise bad_request("missing_index", "Document must include an 'index' field.")
    if "name" not in body:
        raise bad_request("missing_name", "Document must include a 'name' field.")
    if not isinstance(body["index"], str) or not body["index"]:
        raise bad_request("invalid_index", "'index' must be a non-empty string.")


@srd_router.get("/{collection}", response_model=list[dict])
async def list_custom_documents(collection: str) -> list[dict[str, Any]]:
    """List all custom documents in *collection* from the Instance Library."""
    _validate_collection(collection)
    db = get_srd_db()
    results: list[dict[str, Any]] = []
    async for doc in db[f"custom_{_mongo_collection(collection)}"].find({}):
        doc.pop("_id", None)
        results.append(doc)
    return results


@srd_router.post("/{collection}", status_code=201, response_model=dict)
async def create_custom_document(
    collection: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Insert a new document into *collection* in the Instance Library.

    The ``index`` field must be unique within the collection.
    """
    _validate_collection(collection)
    _validate_document(body)

    db = get_srd_db()
    index = body["index"].lower()
    body["index"] = index

    existing = await db[f"custom_{_mongo_collection(collection)}"].find_one({"index": index})
    if existing is not None:
        raise bad_request(
            "index_conflict",
            f"A document with index {index!r} already exists in {collection!r}.",
        )

    await db[f"custom_{_mongo_collection(collection)}"].insert_one(body)
    body.pop("_id", None)
    return body


@srd_router.get("/{collection}/{index}", response_model=dict)
async def get_custom_document(collection: str, index: str) -> dict[str, Any]:
    """Return a single document by *index* from the Instance Library."""
    _validate_collection(collection)
    db = get_srd_db()
    doc = await db[f"custom_{_mongo_collection(collection)}"].find_one({"index": index.lower()})
    if doc is None:
        raise not_found(collection, index)
    doc.pop("_id", None)
    return doc


@srd_router.put("/{collection}/{index}", response_model=dict)
async def replace_custom_document(
    collection: str,
    index: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Replace an existing document in the Instance Library.

    The document must already exist.  The ``index`` in the body (if present)
    must match the path parameter.
    """
    _validate_collection(collection)
    _validate_document(body)

    index = index.lower()
    if body.get("index", index).lower() != index:
        raise bad_request("index_mismatch", "Body 'index' must match the path parameter.")
    body["index"] = index

    db = get_srd_db()
    result = await db[f"custom_{_mongo_collection(collection)}"].replace_one(
        {"index": index}, body
    )
    if result.matched_count == 0:
        raise not_found(collection, index)

    body.pop("_id", None)
    return body


@srd_router.delete("/{collection}/{index}", status_code=204)
async def delete_custom_document(collection: str, index: str) -> None:
    """Delete a document from the Instance Library."""
    _validate_collection(collection)
    db = get_srd_db()
    result = await db[f"custom_{_mongo_collection(collection)}"].delete_one(
        {"index": index.lower()}
    )
    if result.deleted_count == 0:
        raise not_found(collection, index)


# ---------------------------------------------------------------------------
# Campaign Override router — /api/campaigns/{campaign_id}/overrides/{collection}
# ---------------------------------------------------------------------------

overrides_router = APIRouter(prefix="/campaigns", tags=["campaign-overrides"])


@overrides_router.get("/{campaign_id}/overrides/{collection}", response_model=list[dict])
async def list_campaign_overrides(
    campaign_id: uuid.UUID,
    collection: str,
    db: DbSession,
) -> list[dict[str, Any]]:
    """List all campaign-scoped overrides for *collection*."""
    _validate_collection(collection)
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    if result.scalar_one_or_none() is None:
        raise not_found("campaign", campaign_id)

    mdb = get_srd_db()
    docs: list[dict[str, Any]] = []
    async for doc in mdb.campaign_overrides.find(
        {"campaign_id": str(campaign_id), "collection": collection}
    ):
        docs.append(doc["data"])
    return docs


@overrides_router.post(
    "/{campaign_id}/overrides/{collection}",
    status_code=201,
    response_model=dict,
)
async def create_campaign_override(
    campaign_id: uuid.UUID,
    collection: str,
    body: dict[str, Any],
    db: DbSession,
) -> dict[str, Any]:
    """Create a campaign-scoped override document.

    The document's ``index`` must be unique within *campaign_id* + *collection*.
    """
    _validate_collection(collection)
    _validate_document(body)

    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    if result.scalar_one_or_none() is None:
        raise not_found("campaign", campaign_id)

    index = body["index"].lower()
    body["index"] = index

    mdb = get_srd_db()
    existing = await mdb.campaign_overrides.find_one(
        {"campaign_id": str(campaign_id), "collection": collection, "index": index}
    )
    if existing is not None:
        raise bad_request(
            "index_conflict",
            f"An override with index {index!r} already exists for collection {collection!r}.",
        )

    await mdb.campaign_overrides.insert_one(
        {
            "campaign_id": str(campaign_id),
            "collection": collection,
            "index": index,
            "data": body,
        }
    )
    return body


@overrides_router.get(
    "/{campaign_id}/overrides/{collection}/{index}",
    response_model=dict,
)
async def get_campaign_override(
    campaign_id: uuid.UUID,
    collection: str,
    index: str,
    db: DbSession,
) -> dict[str, Any]:
    """Return a single campaign override by *index*."""
    _validate_collection(collection)
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    if result.scalar_one_or_none() is None:
        raise not_found("campaign", campaign_id)

    mdb = get_srd_db()
    doc = await mdb.campaign_overrides.find_one(
        {"campaign_id": str(campaign_id), "collection": collection, "index": index.lower()}
    )
    if doc is None:
        raise not_found(collection, index)
    return doc["data"]


@overrides_router.put(
    "/{campaign_id}/overrides/{collection}/{index}",
    response_model=dict,
)
async def replace_campaign_override(
    campaign_id: uuid.UUID,
    collection: str,
    index: str,
    body: dict[str, Any],
    db: DbSession,
) -> dict[str, Any]:
    """Replace a campaign override document.  The override must already exist."""
    _validate_collection(collection)
    _validate_document(body)

    index = index.lower()
    if body.get("index", index).lower() != index:
        raise bad_request("index_mismatch", "Body 'index' must match the path parameter.")
    body["index"] = index

    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    if result.scalar_one_or_none() is None:
        raise not_found("campaign", campaign_id)

    mdb = get_srd_db()
    replace_result = await mdb.campaign_overrides.replace_one(
        {"campaign_id": str(campaign_id), "collection": collection, "index": index},
        {
            "campaign_id": str(campaign_id),
            "collection": collection,
            "index": index,
            "data": body,
        },
    )
    if replace_result.matched_count == 0:
        raise not_found(collection, index)
    return body


@overrides_router.delete(
    "/{campaign_id}/overrides/{collection}/{index}",
    status_code=204,
)
async def delete_campaign_override(
    campaign_id: uuid.UUID,
    collection: str,
    index: str,
    db: DbSession,
) -> None:
    """Delete a campaign override."""
    _validate_collection(collection)
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    if result.scalar_one_or_none() is None:
        raise not_found("campaign", campaign_id)

    mdb = get_srd_db()
    delete_result = await mdb.campaign_overrides.delete_one(
        {"campaign_id": str(campaign_id), "collection": collection, "index": index.lower()}
    )
    if delete_result.deleted_count == 0:
        raise not_found(collection, index)
