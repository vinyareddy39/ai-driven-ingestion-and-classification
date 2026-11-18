"""Search index adapter implementing SearchIndex interface (OpenSearch and In-Memory fallback)."""

from typing import Any, Dict, List, Optional
from app.core.interfaces import SearchIndex
from app.core.config import get_app_settings


class InMemorySearchIndex(SearchIndex):
    """In-memory full-text search index with structured filter evaluation."""

    def __init__(self):
        self._index: Dict[str, Dict[str, Any]] = {}

    def index_document(self, doc_id: str, payload: Dict[str, Any]) -> bool:
        self._index[doc_id] = payload
        return True

    def search(self, query: Dict[str, Any], limit: int = 50) -> List[Dict[str, Any]]:
        results = []
        for doc_id, doc in self._index.items():
            match = True
            # Simple query evaluation (handles classifier_version, confidence range, doc_type, etc.)
            for k, condition in query.items():
                val = doc.get(k)
                if isinstance(condition, dict):
                    if "lt" in condition and not (val is not None and val < condition["lt"]):
                        match = False
                    if "lte" in condition and not (val is not None and val <= condition["lte"]):
                        match = False
                    if "gt" in condition and not (val is not None and val > condition["gt"]):
                        match = False
                    if "gte" in condition and not (val is not None and val >= condition["gte"]):
                        match = False
                    if "in" in condition and not (val in condition["in"]):
                        match = False
                elif val != condition:
                    match = False
            if match:
                res_copy = dict(doc)
                res_copy["_id"] = doc_id
                results.append(res_copy)
                if len(results) >= limit:
                    break
        return results

    def delete(self, doc_id: str) -> bool:
        if doc_id in self._index:
            del self._index[doc_id]
            return True
        return False


class OpenSearchAdapter(SearchIndex):
    """Production OpenSearch client adapter."""

    def __init__(self):
        from opensearchpy import OpenSearch
        settings = get_app_settings()
        self.client = OpenSearch(hosts=[settings.OPENSEARCH_URL])
        self.index_name = settings.OPENSEARCH_INDEX
        self._ensure_index()

    def _ensure_index(self):
        try:
            if not self.client.indices.exists(index=self.index_name):
                self.client.indices.create(
                    index=self.index_name,
                    body={
                        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                        "mappings": {
                            "properties": {
                                "uid": {"type": "keyword"},
                                "sha256": {"type": "keyword"},
                                "doc_type": {"type": "keyword"},
                                "confidence": {"type": "float"},
                                "classifier_version": {"type": "keyword"},
                                "review_status": {"type": "keyword"},
                                "full_text": {"type": "text"},
                            }
                        },
                    },
                )
        except Exception:
            pass

    def index_document(self, doc_id: str, payload: Dict[str, Any]) -> bool:
        try:
            self.client.index(index=self.index_name, id=doc_id, body=payload, refresh=True)
            return True
        except Exception:
            return False

    def search(self, query: Dict[str, Any], limit: int = 50) -> List[Dict[str, Any]]:
        body = {"query": query, "size": limit}
        try:
            resp = self.client.search(index=self.index_name, body=body)
            hits = resp.get("hits", {}).get("hits", [])
            results = []
            for h in hits:
                item = h.get("_source", {})
                item["_id"] = h.get("_id")
                results.append(item)
            return results
        except Exception:
            return []

    def delete(self, doc_id: str) -> bool:
        try:
            self.client.delete(index=self.index_name, id=doc_id, refresh=True)
            return True
        except Exception:
            return False


_global_search_adapter: Optional[SearchIndex] = None


def get_search_adapter() -> SearchIndex:
    """Factory returning configured search index adapter."""
    global _global_search_adapter
    if _global_search_adapter is None:
        settings = get_app_settings()
        if settings.SEARCH_BACKEND == "opensearch":
            try:
                _global_search_adapter = OpenSearchAdapter()
            except Exception:
                _global_search_adapter = InMemorySearchIndex()
        else:
            _global_search_adapter = InMemorySearchIndex()
    return _global_search_adapter
