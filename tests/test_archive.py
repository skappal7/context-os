from __future__ import annotations

import pytest

from contextos.archive import ArchiveStore


@pytest.mark.asyncio
async def test_add_and_search(tmp_settings) -> None:
    store = ArchiveStore(tmp_settings.archive_dir, embedding_dim=8)
    v1 = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    v2 = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    await store.add("s1", "first turn", "summary one", v1)
    await store.add("s1", "second turn", "summary two", v2)
    await store.add("s2", "other session", "other", v1)

    hits = await store.search("s1", v1, top_k=2)
    assert len(hits) == 2
    assert hits[0].content == "first turn"  # closest match
    assert all(r.session_id == "s1" for r in hits)
