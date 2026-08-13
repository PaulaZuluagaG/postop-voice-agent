"""Application-specific exceptions."""


class PostOpError(Exception):
    """Base exception for the postop voice agent."""


class ConfigurationError(PostOpError):
    """Invalid or missing configuration."""


class DocumentParseError(PostOpError):
    """PDF parsing failed."""


class InsufficientTextError(DocumentParseError):
    """Document has insufficient extractable text."""


class DuplicateDocumentError(DocumentParseError):
    """Document content hash already indexed."""


class EmbeddingError(PostOpError):
    """Embedding generation failed."""


class VectorStoreError(PostOpError):
    """Qdrant operation failed."""


class RetrievalError(PostOpError):
    """Context retrieval failed."""


class LLMError(PostOpError):
    """LLM invocation or parsing failed."""


class LLMRateLimitError(LLMError):
    """Groq rate limit prevented LLM completion."""


class LLMCancelledError(LLMError):
    """LLM generation was interrupted before producing output."""


class SessionError(PostOpError):
    """Invalid call session state."""
