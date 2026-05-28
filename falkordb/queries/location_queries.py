from __future__ import annotations


def search_locations_query(search_text: str) -> tuple[str, dict[str, str]]:
    query = """
    CALL db.idx.fulltext.queryNodes('Location', $search_text)
    YIELD node, score
    RETURN node, score
    ORDER BY score DESC
    """
    return query, {"search_text": search_text}
