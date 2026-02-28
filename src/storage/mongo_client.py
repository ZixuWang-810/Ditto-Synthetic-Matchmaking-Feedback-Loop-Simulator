"""MongoDB storage client for persisting personas and conversations.

Provides real-time persistence alongside JSONL backup, making MongoDB
the single source of truth for chat history, user behavior, and feedback patterns.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from src import config

logger = logging.getLogger(__name__)


class MongoStorage:
    """MongoDB storage for personas and conversations.

    Uses lazy connection — only connects when first operation is called.
    Designed for dual-write alongside JSONL for crash resilience and portability.
    """

    def __init__(
        self,
        uri: str | None = None,
        db_name: str | None = None,
    ):
        self._uri = uri or config.MONGODB_URI
        self._db_name = db_name or config.MONGODB_DB_NAME
        self._client = None
        self._db = None

    # ── Connection Management ─────────────────────────────────────────────

    def _get_db(self):
        """Lazy-initialize the MongoDB connection and return the database."""
        if self._db is None:
            try:
                from pymongo import MongoClient
                self._client = MongoClient(self._uri, serverSelectionTimeoutMS=5000)
                # Verify connection
                self._client.admin.command("ping")
                self._db = self._client[self._db_name]
                self._ensure_indexes()
                logger.info(f"Connected to MongoDB: {self._db_name}")
            except Exception as e:
                raise ConnectionError(
                    f"Failed to connect to MongoDB at {self._uri}: {e}\n"
                    f"Ensure MongoDB is running. Install: https://www.mongodb.com/docs/manual/installation/"
                )
        return self._db

    def _ensure_indexes(self):
        """Create indexes for efficient querying."""
        db = self._db
        # Personas
        db.personas.create_index("name")
        db.personas.create_index("gender")
        db.personas.create_index("date_type")
        # Conversations
        db.conversations.create_index("persona.name")
        db.conversations.create_index("post_date_rating")
        db.conversations.create_index("dropped_off")
        db.conversations.create_index("created_at")

    def close(self):
        """Close the MongoDB connection."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None

    # ── Persona Operations ────────────────────────────────────────────────

    def insert_personas(self, personas: list) -> int:
        """Insert personas into MongoDB, skipping duplicates by id.

        Args:
            personas: List of Persona model instances.

        Returns:
            Number of personas inserted.
        """
        db = self._get_db()
        docs = []
        for p in personas:
            doc = p.model_dump(mode="json")
            doc["_id"] = doc.pop("id")  # Use persona UUID as _id
            doc["synced_at"] = datetime.now(timezone.utc).isoformat()
            docs.append(doc)

        if not docs:
            return 0

        # Use ordered=False to skip duplicates and continue
        try:
            result = db.personas.insert_many(docs, ordered=False)
            inserted = len(result.inserted_ids)
        except Exception as e:
            # BulkWriteError contains info about duplicates — count successful inserts
            if hasattr(e, "details"):
                inserted = e.details.get("nInserted", 0)
            else:
                raise
        
        logger.info(f"Inserted {inserted} personas into MongoDB")
        return inserted

    def load_personas(self) -> list:
        """Load all personas from MongoDB.

        Returns:
            List of Persona model instances.
        """
        from src.models.persona import Persona

        db = self._get_db()
        docs = list(db.personas.find())
        personas = []
        for doc in docs:
            doc["id"] = doc.pop("_id")
            personas.append(Persona.model_validate(doc))
        logger.info(f"Loaded {len(personas)} personas from MongoDB")
        return personas

    def get_persona_by_id(self, persona_id: str):
        """Get a single persona by ID."""
        from src.models.persona import Persona

        db = self._get_db()
        doc = db.personas.find_one({"_id": persona_id})
        if doc:
            doc["id"] = doc.pop("_id")
            return Persona.model_validate(doc)
        return None

    def get_persona_count(self) -> int:
        """Get the total number of personas in MongoDB."""
        db = self._get_db()
        return db.personas.count_documents({})

    def clear_personas(self):
        """Delete all personas from MongoDB."""
        db = self._get_db()
        result = db.personas.delete_many({})
        logger.info(f"Deleted {result.deleted_count} personas from MongoDB")

    # ── Conversation Operations ───────────────────────────────────────────

    def insert_conversation(self, conversation) -> bool:
        """Insert a single conversation log into MongoDB.

        Args:
            conversation: ConversationLog model instance.

        Returns:
            True if inserted, False if duplicate.
        """
        db = self._get_db()
        doc = conversation.model_dump(mode="json")
        doc["_id"] = doc.pop("conversation_id")
        doc["created_at"] = datetime.now(timezone.utc).isoformat()

        try:
            db.conversations.insert_one(doc)
            logger.debug(f"Inserted conversation {doc['_id'][:8]} into MongoDB")
            return True
        except Exception as e:
            if "duplicate" in str(e).lower() or "E11000" in str(e):
                logger.debug(f"Conversation {doc['_id'][:8]} already exists in MongoDB")
                return False
            raise

    def insert_conversations(self, conversations: list) -> int:
        """Bulk insert conversations, skipping duplicates.

        Returns:
            Number of conversations inserted.
        """
        inserted = 0
        for conv in conversations:
            if self.insert_conversation(conv):
                inserted += 1
        return inserted

    def load_conversations(self, limit: int = 0) -> list:
        """Load conversations from MongoDB.

        Args:
            limit: Max conversations to return (0 = all).

        Returns:
            List of ConversationLog model instances.
        """
        from src.models.conversation import ConversationLog

        db = self._get_db()
        cursor = db.conversations.find().sort("created_at", -1)
        if limit > 0:
            cursor = cursor.limit(limit)

        conversations = []
        for doc in cursor:
            doc["conversation_id"] = doc.pop("_id")
            conversations.append(ConversationLog.model_validate(doc))
        return conversations

    def get_conversation_count(self) -> int:
        """Get the total number of conversations in MongoDB."""
        db = self._get_db()
        return db.conversations.count_documents({})

    def clear_conversations(self):
        """Delete all conversations from MongoDB."""
        db = self._get_db()
        result = db.conversations.delete_many({})
        logger.info(f"Deleted {result.deleted_count} conversations from MongoDB")

    # ── Analytics Queries ─────────────────────────────────────────────────

    def get_summary_stats(self) -> dict:
        """Get summary statistics from MongoDB.

        Returns:
            Dict with counts, averages, and distributions.
        """
        db = self._get_db()

        total_personas = db.personas.count_documents({})
        total_conversations = db.conversations.count_documents({})
        accepted = db.conversations.count_documents({"rounds_to_acceptance": {"$ne": None}})
        dropped = db.conversations.count_documents({"dropped_off": True})

        # Average rating
        pipeline = [
            {"$match": {"post_date_rating": {"$ne": None}}},
            {"$group": {"_id": None, "avg_rating": {"$avg": "$post_date_rating"}}},
        ]
        rating_result = list(db.conversations.aggregate(pipeline))
        avg_rating = rating_result[0]["avg_rating"] if rating_result else None

        # Average rounds to acceptance
        pipeline = [
            {"$match": {"rounds_to_acceptance": {"$ne": None}}},
            {"$group": {"_id": None, "avg_rounds": {"$avg": "$rounds_to_acceptance"}}},
        ]
        rounds_result = list(db.conversations.aggregate(pipeline))
        avg_rounds = rounds_result[0]["avg_rounds"] if rounds_result else None

        # Gender distribution
        gender_pipeline = [
            {"$group": {"_id": "$gender", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        gender_dist = {
            doc["_id"]: doc["count"]
            for doc in db.personas.aggregate(gender_pipeline)
        }

        # Rating distribution
        rating_pipeline = [
            {"$match": {"post_date_rating": {"$ne": None}}},
            {"$group": {"_id": "$post_date_rating", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        rating_dist = {
            doc["_id"]: doc["count"]
            for doc in db.conversations.aggregate(rating_pipeline)
        }

        return {
            "total_personas": total_personas,
            "total_conversations": total_conversations,
            "matches_accepted": accepted,
            "dropped_off": dropped,
            "acceptance_rate": accepted / total_conversations if total_conversations else 0,
            "avg_post_date_rating": round(avg_rating, 2) if avg_rating else None,
            "avg_rounds_to_acceptance": round(avg_rounds, 2) if avg_rounds else None,
            "gender_distribution": gender_dist,
            "rating_distribution": rating_dist,
        }

    def get_rejection_stats(self, top_n: int = 10) -> list[dict]:
        """Get the most common rejection keywords/phrases.

        Returns:
            List of dicts with 'reason' and 'count'.
        """
        db = self._get_db()
        pipeline = [
            {"$unwind": "$rejection_reasons"},
            {"$group": {"_id": "$rejection_reasons", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": top_n},
        ]
        return [
            {"reason": doc["_id"], "count": doc["count"]}
            for doc in db.conversations.aggregate(pipeline)
        ]


# ── Factory Function ──────────────────────────────────────────────────────────

_instance: Optional[MongoStorage] = None


def get_mongo_storage() -> MongoStorage:
    """Get or create a singleton MongoStorage instance."""
    global _instance
    if _instance is None:
        _instance = MongoStorage()
    return _instance
