"""Durable, bounded per-paper research conversations."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from research_digest.ai_artifacts import resolve_preferred_library_summary
from research_digest.ai_providers import GeneratedAIText, ResearchConversationProvider
from research_digest.conversation_provenance import (
    parse_rolling_summary_boundary,
    rolling_summary_input_fingerprint,
)
from research_digest.db import (
    AIConversationBusyError,
    AIConversationConflictError,
    Database,
)
from research_digest.models import (
    AIArtifact,
    AIArtifactProvenance,
    AIConversation,
    AIConversationMessage,
    AIConversationRole,
    Article,
    LibraryNote,
)

RESEARCH_CONVERSATION_VERSION = 1
DEFAULT_SEND_LOCK_STALE_SECONDS = 15 * 60.0
SEND_LOCK_TIMEOUT_MARGIN_SECONDS = 60.0


class ConversationError(RuntimeError):
    """Raised when a conversation action cannot complete safely."""


class ConversationContextError(ConversationError):
    """Raised when bounded context cannot represent the required material."""


@dataclass(frozen=True)
class ConversationContextPolicy:
    """Deterministic UTF-8 budgets for one research-conversation request."""

    max_context_bytes: int = 128 * 1024
    max_title_bytes: int = 4 * 1024
    max_abstract_bytes: int = 48 * 1024
    max_note_bytes: int = 12 * 1024
    max_preferred_summary_bytes: int = 8 * 1024
    max_rolling_summary_bytes: int = 16 * 1024
    max_live_conversation_bytes: int = 40 * 1024
    max_current_user_message_bytes: int = 16 * 1024
    max_assistant_message_bytes: int = 32 * 1024
    max_compression_source_bytes: int = 96 * 1024

    def __post_init__(self) -> None:
        values = tuple(self.__dict__.values())
        if any(value <= 0 for value in values):
            raise ValueError("conversation context budgets must be positive")
        if self.max_current_user_message_bytes > self.max_live_conversation_bytes:
            raise ValueError("current-message budget must fit the live-conversation budget")


DEFAULT_CONTEXT_POLICY = ConversationContextPolicy()


@dataclass(frozen=True)
class AIConversationOverview:
    conversation: AIConversation
    message_count: int

    def __post_init__(self) -> None:
        if self.conversation.id is None:
            raise ValueError("persisted conversation id is required")
        if self.message_count < 0:
            raise ValueError("message count must not be negative")


@dataclass(frozen=True)
class ConversationContextComposition:
    article_context_bytes: int
    note_bytes: int
    preferred_summary_bytes: int
    rolling_summary_bytes: int
    live_conversation_bytes: int
    recent_message_count: int
    summarized_through_sequence: int
    total_assembled_bytes: int
    truncated_components: tuple[str, ...]


@dataclass(frozen=True)
class AssembledConversationContext:
    serialized: str
    composition: ConversationContextComposition


@dataclass(frozen=True)
class ConversationTurnResult:
    user_message: AIConversationMessage
    assistant_message: AIConversationMessage
    context: AssembledConversationContext
    rolling_summary_artifact: AIArtifact | None
    compression_provider_called: bool


@dataclass(frozen=True)
class _RollingSummaryState:
    artifact: AIArtifact | None
    summarized_through_sequence: int

    @property
    def content(self) -> str:
        return self.artifact.content if self.artifact is not None else ""


class _ContextOverflow(RuntimeError):
    pass


def create_conversation(
    db: Database,
    *,
    article_id: int,
    title: str | None = None,
    provider: str,
    model_id: str,
    conversation_version: int = RESEARCH_CONVERSATION_VERSION,
    created_at: datetime | None = None,
) -> AIConversation:
    """Create a transcript header without invoking a provider."""

    if db.get_library_entry(article_id) is None:
        raise ConversationError("New discussions require a saved Library paper.")
    normalized_title = title.strip() if title is not None else ""
    if not normalized_title:
        normalized_title = f"Discussion {len(db.list_ai_conversations(article_id)) + 1}"
    return db.create_ai_conversation(
        article_id=article_id,
        title=normalized_title,
        provider=provider,
        model_id=model_id,
        conversation_version=conversation_version,
        created_at=created_at,
    )


def rename_conversation(
    db: Database,
    *,
    conversation_id: int,
    title: str,
) -> AIConversation:
    """Rename a discussion without invoking a provider."""

    return db.rename_ai_conversation(conversation_id, title)


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


def inspect_conversation_context(
    db: Database,
    *,
    conversation_id: int,
    policy: ConversationContextPolicy = DEFAULT_CONTEXT_POLICY,
) -> AssembledConversationContext:
    """Expose deterministic context composition for tests/developer diagnostics."""

    conversation, article, messages = _load_conversation_state(db, conversation_id)
    rolling = _load_rolling_summary(db, conversation, messages)
    return _assemble_context(
        db,
        article=article,
        messages=messages,
        rolling=rolling,
        policy=policy,
    )


def send_conversation_message(
    db: Database,
    *,
    conversation_id: int,
    content: str,
    provider: ResearchConversationProvider,
    policy: ConversationContextPolicy = DEFAULT_CONTEXT_POLICY,
    now: datetime | None = None,
) -> ConversationTurnResult:
    """Persist one user turn, then generate and atomically persist one response."""

    _validate_current_message(content, policy)
    owner = f"conversation-send:{uuid.uuid4().hex}"
    try:
        db.acquire_ai_conversation_send_lock(
            conversation_id,
            owner=owner,
            stale_after_seconds=_send_lock_stale_seconds(provider),
            now=now,
        )
    except AIConversationBusyError as exc:
        raise ConversationError(str(exc)) from exc
    try:
        messages = db.list_ai_conversation_messages(conversation_id)
        if messages and messages[-1].role == AIConversationRole.USER:
            raise ConversationError(
                "This discussion already has an unanswered message. Retry that response first."
            )
        expected_sequence = messages[-1].sequence_number if messages else 0
        user_message = db.begin_ai_conversation_turn(
            conversation_id=conversation_id,
            content=content,
            expected_last_sequence=expected_sequence,
            created_at=now,
        )
        return _complete_pending_turn(
            db,
            conversation_id=conversation_id,
            user_message=user_message,
            provider=provider,
            policy=policy,
            now=now,
        )
    except AIConversationConflictError as exc:
        raise ConversationError(str(exc)) from exc
    finally:
        db.release_ai_conversation_send_lock(conversation_id, owner=owner)


def retry_conversation_response(
    db: Database,
    *,
    conversation_id: int,
    provider: ResearchConversationProvider,
    policy: ConversationContextPolicy = DEFAULT_CONTEXT_POLICY,
    now: datetime | None = None,
) -> ConversationTurnResult:
    """Explicitly retry the one durable unanswered user message."""

    owner = f"conversation-retry:{uuid.uuid4().hex}"
    try:
        db.acquire_ai_conversation_send_lock(
            conversation_id,
            owner=owner,
            stale_after_seconds=_send_lock_stale_seconds(provider),
            now=now,
        )
    except AIConversationBusyError as exc:
        raise ConversationError(str(exc)) from exc
    try:
        messages = db.list_ai_conversation_messages(conversation_id)
        if not messages or messages[-1].role != AIConversationRole.USER:
            raise ConversationError("There is no unanswered message to retry.")
        return _complete_pending_turn(
            db,
            conversation_id=conversation_id,
            user_message=messages[-1],
            provider=provider,
            policy=policy,
            now=now,
        )
    except AIConversationConflictError as exc:
        raise ConversationError(str(exc)) from exc
    finally:
        db.release_ai_conversation_send_lock(conversation_id, owner=owner)


def promote_assistant_takeaway_to_note(
    db: Database,
    *,
    article_id: int,
    message_id: int,
    approved_text: str,
) -> LibraryNote:
    """Append explicitly approved existing response text to the human note."""

    message = db.get_ai_conversation_message(message_id)
    if message is None or message.role != AIConversationRole.ASSISTANT:
        raise ConversationError("Only a stored assistant response can be promoted.")
    conversation = db.get_ai_conversation(message.conversation_id)
    if conversation is None or conversation.article_id != article_id:
        raise ConversationError("The selected response does not belong to this paper.")
    if not approved_text.strip():
        raise ConversationError("Takeaway text cannot be empty.")
    existing = db.get_library_note(article_id)
    note_text = (
        approved_text if existing is None else f"{existing.note_text.rstrip()}\n\n{approved_text}"
    )
    saved = db.save_library_note(article_id=article_id, note_text=note_text)
    if saved is None:
        raise RuntimeError("approved takeaway did not produce a Library note")
    return saved


def rolling_summary_boundary(
    *,
    conversation_id: int,
    artifact: AIArtifact,
) -> int:
    """Read the exact covered sequence from structured, fail-closed provenance."""

    try:
        return parse_rolling_summary_boundary(
            conversation_id=conversation_id,
            input_fingerprint=artifact.input_fingerprint,
        )
    except ValueError as exc:
        raise ConversationContextError(
            "The stored rolling summary has unsupported boundary provenance."
        ) from exc


def _complete_pending_turn(
    db: Database,
    *,
    conversation_id: int,
    user_message: AIConversationMessage,
    provider: ResearchConversationProvider,
    policy: ConversationContextPolicy,
    now: datetime | None,
) -> ConversationTurnResult:
    conversation, article, messages = _load_conversation_state(db, conversation_id)
    if article.id is None or db.get_library_entry(article.id) is None:
        raise ConversationError("Continue the discussion after saving the paper again.")
    if not messages or messages[-1].id != user_message.id:
        raise ConversationError("The pending conversation turn changed; reload and try again.")
    rolling = _load_rolling_summary(db, conversation, messages)
    compression_called = False
    rolling_artifact: AIArtifact | None = None
    try:
        assembled = _assemble_context(
            db,
            article=article,
            messages=messages,
            rolling=rolling,
            policy=policy,
        )
    except _ContextOverflow:
        rolling = _compress_context(
            db,
            conversation=conversation,
            article=article,
            messages=messages,
            rolling=rolling,
            provider=provider,
            policy=policy,
            now=now,
        )
        compression_called = True
        rolling_artifact = rolling.artifact
        assembled = _assemble_context(
            db,
            article=article,
            messages=messages,
            rolling=rolling,
            policy=policy,
        )

    generated = provider.respond(article=article, context=assembled.serialized)
    _validate_generated_text(
        generated,
        provider=provider,
        expected_generator_version=provider.response_generator_version,
        expected_input_fingerprint=_sha256_text(assembled.serialized),
        max_output_bytes=policy.max_assistant_message_bytes,
        output_label="assistant response",
    )
    if user_message.id is None:
        raise RuntimeError("pending user message id is required")
    assistant = db.complete_ai_conversation_turn(
        conversation_id=conversation_id,
        pending_user_message_id=user_message.id,
        content=generated.content,
        provider=generated.provider,
        model_id=generated.model_id,
        conversation_version=RESEARCH_CONVERSATION_VERSION,
        created_at=now,
    )
    return ConversationTurnResult(
        user_message=user_message,
        assistant_message=assistant,
        context=assembled,
        rolling_summary_artifact=rolling_artifact,
        compression_provider_called=compression_called,
    )


def _compress_context(
    db: Database,
    *,
    conversation: AIConversation,
    article: Article,
    messages: list[AIConversationMessage],
    rolling: _RollingSummaryState,
    provider: ResearchConversationProvider,
    policy: ConversationContextPolicy,
    now: datetime | None,
) -> _RollingSummaryState:
    if conversation.id is None:
        raise RuntimeError("persisted conversation id is required")
    boundary = _select_compression_boundary(
        db,
        article=article,
        messages=messages,
        rolling=rolling,
        policy=policy,
    )
    source_messages = [
        message
        for message in messages
        if rolling.summarized_through_sequence < message.sequence_number <= boundary
    ]
    compression_context = json.dumps(
        {
            "context_version": RESEARCH_CONVERSATION_VERSION,
            "paper_title": _bounded_text(
                article.title,
                policy.max_title_bytes,
                label="title",
            )[0],
            "prior_rolling_summary": rolling.content or None,
            "prior_summarized_through_sequence": (rolling.summarized_through_sequence or None),
            "messages_to_summarize": [_message_payload(message) for message in source_messages],
            "summarized_through_sequence": boundary,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if _utf8_size(compression_context) > policy.max_compression_source_bytes:
        raise ConversationContextError(
            "The older discussion is too large for one bounded context compression. "
            "Start a new discussion for the next question."
        )
    generated = provider.summarize_conversation(article=article, context=compression_context)
    _validate_generated_text(
        generated,
        provider=provider,
        expected_generator_version=provider.summary_generator_version,
        expected_input_fingerprint=_sha256_text(compression_context),
        max_output_bytes=policy.max_rolling_summary_bytes,
        output_label="rolling conversation summary",
    )
    fingerprint = rolling_summary_input_fingerprint(
        conversation_id=conversation.id,
        summarized_through_sequence=boundary,
        compression_context=compression_context,
    )
    artifact = db.replace_ai_conversation_rolling_summary(
        conversation_id=conversation.id,
        content=generated.content,
        provenance=AIArtifactProvenance(
            provider=generated.provider,
            model_id=generated.model_id,
            reasoning_effort=generated.reasoning_effort,
            generator_version=generated.generator_version,
            input_fingerprint=fingerprint,
        ),
        summarized_through_sequence=boundary,
        created_at=now,
    )
    return _RollingSummaryState(
        artifact=artifact,
        summarized_through_sequence=boundary,
    )


def _send_lock_stale_seconds(provider: ResearchConversationProvider) -> float:
    """Keep the lease valid across at most one compression and one response call."""

    timeout_seconds = provider.timeout_seconds
    if timeout_seconds <= 0:
        raise ConversationError("The research-conversation provider timeout is invalid.")
    bounded_call_window = (2 * timeout_seconds) + SEND_LOCK_TIMEOUT_MARGIN_SECONDS
    return max(DEFAULT_SEND_LOCK_STALE_SECONDS, bounded_call_window)


def _select_compression_boundary(
    db: Database,
    *,
    article: Article,
    messages: list[AIConversationMessage],
    rolling: _RollingSummaryState,
    policy: ConversationContextPolicy,
) -> int:
    candidates = [
        message.sequence_number
        for message in messages[:-1]
        if message.sequence_number > rolling.summarized_through_sequence
        and message.role == AIConversationRole.ASSISTANT
    ]
    placeholder = "s" * policy.max_rolling_summary_bytes
    for boundary in candidates:
        candidate_rolling = _RollingSummaryState(
            artifact=_placeholder_artifact(article, placeholder),
            summarized_through_sequence=boundary,
        )
        try:
            _assemble_context(
                db,
                article=article,
                messages=messages,
                rolling=candidate_rolling,
                policy=policy,
            )
        except _ContextOverflow:
            continue
        return boundary
    raise ConversationContextError(
        "This discussion cannot fit one bounded request yet. Start a new discussion "
        "or ask a shorter question."
    )


def _assemble_context(
    db: Database,
    *,
    article: Article,
    messages: list[AIConversationMessage],
    rolling: _RollingSummaryState,
    policy: ConversationContextPolicy,
) -> AssembledConversationContext:
    if article.id is None:
        raise RuntimeError("persisted article id is required")
    title, title_truncated = _bounded_text(article.title, policy.max_title_bytes, label="title")
    abstract, abstract_truncated = _bounded_text(
        article.abstract,
        policy.max_abstract_bytes,
        label="abstract",
    )
    note_record = db.get_library_note(article.id)
    note, note_truncated = _bounded_text(
        note_record.note_text if note_record is not None else "",
        policy.max_note_bytes,
        label="note",
    )
    preferred = resolve_preferred_library_summary(db, article_id=article.id)
    preferred_text, summary_truncated = _bounded_text(
        preferred.content if preferred is not None else "",
        policy.max_preferred_summary_bytes,
        label="preferred summary",
    )
    rolling_text, rolling_truncated = _bounded_text(
        rolling.content,
        policy.max_rolling_summary_bytes,
        label="rolling summary",
    )
    recent = [
        message
        for message in messages
        if message.sequence_number > rolling.summarized_through_sequence
    ]
    live_payload = [_message_payload(message) for message in recent]
    live_json = json.dumps(
        live_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    live_bytes = _utf8_size(live_json)
    if live_bytes > policy.max_live_conversation_bytes:
        raise _ContextOverflow
    payload = {
        "context_version": RESEARCH_CONVERSATION_VERSION,
        "authoritative_paper_source": {"title": title, "abstract": abstract},
        "user_authored_context": {"my_notes": note or None},
        "derived_ai_context": {
            "preferred_ai_summary": preferred_text or None,
            "rolling_conversation_summary": rolling_text or None,
            "summarized_through_sequence": (rolling.summarized_through_sequence or None),
        },
        "live_conversation": live_payload,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    total_bytes = _utf8_size(serialized)
    if total_bytes > policy.max_context_bytes:
        raise _ContextOverflow
    truncated = tuple(
        label
        for label, active in (
            ("title", title_truncated),
            ("abstract", abstract_truncated),
            ("note", note_truncated),
            ("preferred_summary", summary_truncated),
            ("rolling_summary", rolling_truncated),
        )
        if active
    )
    return AssembledConversationContext(
        serialized=serialized,
        composition=ConversationContextComposition(
            article_context_bytes=_utf8_size(title) + _utf8_size(abstract),
            note_bytes=_utf8_size(note),
            preferred_summary_bytes=_utf8_size(preferred_text),
            rolling_summary_bytes=_utf8_size(rolling_text),
            live_conversation_bytes=live_bytes,
            recent_message_count=len(recent),
            summarized_through_sequence=rolling.summarized_through_sequence,
            total_assembled_bytes=total_bytes,
            truncated_components=truncated,
        ),
    )


def _load_conversation_state(
    db: Database,
    conversation_id: int,
) -> tuple[AIConversation, Article, list[AIConversationMessage]]:
    conversation = db.get_ai_conversation(conversation_id)
    if conversation is None:
        raise ConversationError("The discussion no longer exists.")
    article = db.get_article(conversation.article_id)
    if article is None:
        raise ConversationError("The paper no longer exists in the local corpus.")
    return conversation, article, db.list_ai_conversation_messages(conversation_id)


def _load_rolling_summary(
    db: Database,
    conversation: AIConversation,
    messages: list[AIConversationMessage],
) -> _RollingSummaryState:
    if conversation.rolling_summary_artifact_id is None:
        return _RollingSummaryState(artifact=None, summarized_through_sequence=0)
    if conversation.id is None:
        raise RuntimeError("persisted conversation id is required")
    artifact = db.get_ai_artifact(conversation.rolling_summary_artifact_id)
    if artifact is None:
        raise ConversationContextError("The rolling conversation summary is unavailable.")
    boundary = rolling_summary_boundary(conversation_id=conversation.id, artifact=artifact)
    covered = next((message for message in messages if message.sequence_number == boundary), None)
    if covered is None or covered.role != AIConversationRole.ASSISTANT:
        raise ConversationContextError(
            "The rolling summary boundary does not match the durable transcript."
        )
    return _RollingSummaryState(
        artifact=artifact,
        summarized_through_sequence=boundary,
    )


def _validate_current_message(content: str, policy: ConversationContextPolicy) -> None:
    if not content.strip():
        raise ConversationError("Write a message before sending.")
    if _utf8_size(content) > policy.max_current_user_message_bytes:
        raise ConversationContextError(
            "This message is too large for one bounded research-conversation request."
        )


def _validate_generated_text(
    generated: GeneratedAIText,
    *,
    provider: ResearchConversationProvider,
    expected_generator_version: str,
    expected_input_fingerprint: str,
    max_output_bytes: int,
    output_label: str,
) -> None:
    if (
        generated.provider != provider.provider
        or generated.model_id != provider.model_id
        or generated.reasoning_effort != provider.reasoning_effort
        or generated.generator_version != expected_generator_version
        or generated.input_fingerprint != expected_input_fingerprint
    ):
        raise ConversationError(
            f"The {output_label} provider returned provenance outside the configured route."
        )
    if _utf8_size(generated.content) > max_output_bytes:
        raise ConversationContextError(f"The generated {output_label} exceeded its size limit.")


def _message_payload(message: AIConversationMessage) -> dict[str, object]:
    return {
        "sequence_number": message.sequence_number,
        "role": message.role.value,
        "content": message.content,
    }


def _bounded_text(text: str, maximum: int, *, label: str) -> tuple[str, bool]:
    if _utf8_size(text) <= maximum:
        return text, False
    marker = f"\n[{label} truncated for bounded model context]"
    marker_bytes = marker.encode("utf-8")
    if len(marker_bytes) >= maximum:
        return marker_bytes[:maximum].decode("utf-8", errors="ignore"), True
    prefix = text.encode("utf-8")[: maximum - len(marker_bytes)].decode(
        "utf-8",
        errors="ignore",
    )
    return prefix + marker, True


def _placeholder_artifact(article: Article, content: str) -> AIArtifact:
    from research_digest.models import AIArtifactRetentionClass, AIArtifactType, utc_now

    if article.id is None:
        raise RuntimeError("persisted article id is required")
    return AIArtifact(
        id=1,
        article_id=article.id,
        artifact_type=AIArtifactType.CONVERSATION_SUMMARY,
        content=content,
        created_at=utc_now(),
        provider="context-planner",
        model_id="context-planner",
        reasoning_effort=None,
        generator_version="context-planner",
        input_fingerprint="context-planner",
        retention_class=AIArtifactRetentionClass.LIBRARY,
        expires_at=None,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))
