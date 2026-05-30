import abc
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class SessionStore(abc.ABC):
    @abc.abstractmethod
    def get_thread_id(self, user_id: int | str) -> str:
        ...

    @abc.abstractmethod
    def reset(self, user_id: int | str) -> None:
        ...

    @abc.abstractmethod
    def checkpointer(self):
        ...


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------


@dataclass
class _Session:
    thread_id: str
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MemorySessionStore(SessionStore):
    def __init__(self) -> None:
        from langgraph.checkpoint.memory import InMemorySaver

        self._sessions: dict[int, _Session] = {}
        self._checkpointer = InMemorySaver()

    def get_thread_id(self, user_id: int | str) -> str:
        now = datetime.now(timezone.utc)
        idle_limit = settings.session_idle_minutes * 60
        session = self._sessions.get(user_id)
        if session and (now - session.last_active).total_seconds() <= idle_limit:
            session.last_active = now
            return session.thread_id
        thread_id = str(uuid.uuid4())
        self._sessions[user_id] = _Session(thread_id=thread_id, last_active=now)
        log.info("New in-memory session for user %s → thread %s", user_id, thread_id)
        return thread_id

    def reset(self, user_id: int | str) -> None:
        self._sessions.pop(user_id, None)

    def checkpointer(self):
        return self._checkpointer


# ---------------------------------------------------------------------------
# MongoDB implementation
# ---------------------------------------------------------------------------


class MongoSessionStore(SessionStore):
    def __init__(self, client: Any, db_name: str) -> None:
        self._client = client
        self._db_name = db_name

    def _col(self):
        return self._client[self._db_name]["sessions"]

    def get_thread_id(self, user_id: int | str) -> str:
        now = datetime.now(timezone.utc)
        idle_limit = settings.session_idle_minutes * 60
        col = self._col()
        doc = col.find_one({"user_id": user_id, "is_active": True})
        if doc:
            last_active: datetime = doc["last_active"]
            if last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=timezone.utc)
            if (now - last_active).total_seconds() <= idle_limit:
                col.update_one({"_id": doc["_id"]}, {"$set": {"last_active": now}})
                return doc["thread_id"]
        col.update_many(
            {"user_id": user_id, "is_active": True}, {"$set": {"is_active": False}}
        )
        thread_id = str(uuid.uuid4())
        col.insert_one(
            {
                "user_id": user_id,
                "thread_id": thread_id,
                "last_active": now,
                "is_active": True,
            }
        )
        log.info("New session for user %s → thread %s", user_id, thread_id)
        return thread_id

    def reset(self, user_id: int | str) -> None:
        self._col().update_many(
            {"user_id": user_id, "is_active": True},
            {"$set": {"is_active": False}},
        )

    def checkpointer(self):
        from langgraph.checkpoint.mongodb import MongoDBSaver

        return MongoDBSaver(self._client, db_name=self._db_name)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_store() -> SessionStore:
    if settings.mongodb_uri:
        from pymongo import MongoClient

        client = MongoClient(settings.mongodb_uri)
        log.info("Using MongoSessionStore (db: %s)", settings.mongodb_database)
        return MongoSessionStore(client, settings.mongodb_database)

    log.info("Using MemorySessionStore (no MONGODB_URI set)")
    return MemorySessionStore()
