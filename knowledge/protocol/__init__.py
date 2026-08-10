"""Post-operative protocol generation from indexed clinical knowledge."""

from knowledge.protocol.generator import generate_protocols_for_indexed_procedures
from knowledge.protocol.models import PostOpProtocol, ProtocolGenerationReport

__all__ = [
    "PostOpProtocol",
    "ProtocolGenerationReport",
    "generate_protocols_for_indexed_procedures",
]
