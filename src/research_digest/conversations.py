"""Persistence-only services for per-paper AI conversation transcripts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from research_digest.db import Database
from research_digest.models import AIConversation, AIConversationMessage, AIConversationRole


@dataclass(frozen=True)
class AIConversationOverview:
    conversation: AIConversation
    message_count: int

    def __post_init__(self) -> None:
        if self.conversation.id is None:
            raise ValueError("persisted conversation id is required")
        if self.message_count < 0:
            raise ValueError("message count must not be negative")


def create_conversation(
    db: Database,
    *,
    article_id: int,
    title: str,
    provider: str,
    model_id: str,
    conversation_version: int = 1,
    created_at: datetime | None = None,
) -> AIConversation:
    """Create a transcript header without invoking a provider."""

    return db.create_ai_conversation(
        article_id=article_id,
        title=title,
        provider=provider,
        model_id=model_id,
        conversation_version=conversation_version,
        created_at=created_at,
    )


def append_message(
    db: Database,
    *,
    conversation_id: int,
    role: AIConversationRole,
    content: str,
    created_at: datetime | None = None,
) -> AIConversationMessage:
    """Append already-authored text in deterministic sequence order."""

    return db.append_ai_conversation_message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        created_at=created_at,
    )


def list_conversations(db: Database, *, article_id: int) -> list[AIConversation]:
    return db.list_ai_conversations(article_id)


def list_messages(
    db: Database,
    *,
    conversation_id: int,
) -> list[AIConversationMessage]:
    return db.list_ai_conversation_messages(conversation_id)


def list_conversation_overviews(
    db: Database,
    *,
    article_id: int,
) -> list[AIConversationOverview]:
    """List stored discussions with counts in one read-only query."""

    return [
        AIConversationOverview(conversation=conversation, message_count=message_count)
        for conversation, message_count in db.list_ai_conversation_overviews(article_id)
    ]


def set_rolling_summary(
    db: Database,
    *,
    conversation_id: int,
    artifact_id: int | None,
) -> AIConversation:
    """Set only the summary pointer; the complete transcript remains untouched."""

    return db.set_ai_conversation_rolling_summary(conversation_id, artifact_id)
