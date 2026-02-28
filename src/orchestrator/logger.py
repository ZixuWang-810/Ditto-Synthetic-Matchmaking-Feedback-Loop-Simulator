"""JSONL conversation logger with real-time append for crash resilience.

Supports optional dual-write to MongoDB for real-time persistence.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime

from src import config
from src.models.conversation import ConversationLog

logger = logging.getLogger(__name__)


class ConversationLogger:
    """Writes conversation logs to JSONL files, one entry per conversation.
    
    Each conversation is appended immediately upon completion for crash resilience.
    When MongoDB is enabled, performs dual-write to both JSONL and MongoDB.
    """

    def __init__(self, output_dir: Path | None = None, mongo_enabled: bool = False):
        self.output_dir = output_dir or config.CONVERSATIONS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self.output_dir / f"conversations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        self._count = 0

        # MongoDB dual-write
        self._mongo = None
        if mongo_enabled:
            from src.storage.mongo_client import get_mongo_storage
            self._mongo = get_mongo_storage()
            logger.info("MongoDB dual-write enabled for conversations")

    def log_conversation(self, conversation: ConversationLog):
        """Append a single conversation log to the JSONL file (and MongoDB if enabled)."""
        # Always write to JSONL
        with open(self._log_file, "a", encoding="utf-8") as f:
            f.write(conversation.model_dump_json() + "\n")
        self._count += 1
        logger.debug(f"Logged conversation {conversation.conversation_id} (#{self._count})")

        # Dual-write to MongoDB
        if self._mongo:
            try:
                self._mongo.insert_conversation(conversation)
            except Exception as e:
                logger.warning(f"MongoDB write failed (JSONL still saved): {e}")

    @property
    def logged_count(self) -> int:
        """Number of conversations logged so far."""
        return self._count

    @property
    def log_file_path(self) -> Path:
        """Path to the current log file."""
        return self._log_file

    @staticmethod
    def load_conversations(path: Path) -> list[ConversationLog]:
        """Load conversation logs from a JSONL file."""
        conversations = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    conversations.append(ConversationLog.model_validate_json(line))
        return conversations

