from voice.shared_runtime import get_shared_retriever


def test_shared_retriever_is_singleton() -> None:
    first = get_shared_retriever()
    second = get_shared_retriever()
    assert first is second
    assert first._embedder is second._embedder
