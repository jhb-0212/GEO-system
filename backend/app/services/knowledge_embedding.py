"""知识库 embedding：可配置 Ollama / OpenAI 兼容接口。

没有配置或调用失败时返回 None，检索自动退回词法/三元组；
embedding 不是解析前置条件，不能让文档解析因外部模型不可用而失败。
"""

from __future__ import annotations

import math

import httpx

from app.core.config import settings

BATCH_SIZE = 16


def embedding_configured() -> bool:
    return bool(settings.knowledge_embedding_base_url.strip())


def embedding_model() -> str:
    return settings.knowledge_embedding_model.strip() or "bge-m3"


def _ollama_base(base: str) -> bool:
    return base.endswith("/api") or "11434" in base or "ollama" in base.lower()


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    base = settings.knowledge_embedding_base_url.strip().rstrip("/")
    if not base or not texts:
        return None
    headers = {"Content-Type": "application/json"}
    if settings.knowledge_embedding_api_key.strip():
        headers["Authorization"] = f"Bearer {settings.knowledge_embedding_api_key.strip()}"
    results: list[list[float]] = []
    try:
        with httpx.Client(timeout=settings.knowledge_embedding_timeout_seconds) as client:
            for start in range(0, len(texts), BATCH_SIZE):
                batch = texts[start:start + BATCH_SIZE]
                if _ollama_base(base):
                    endpoint = f"{base}/embed" if base.endswith("/api") else f"{base}/api/embed"
                    response = client.post(
                        endpoint,
                        headers=headers,
                        json={"model": embedding_model(), "input": batch},
                    )
                else:
                    endpoint = f"{base}/embeddings" if base.endswith("/v1") else f"{base}/v1/embeddings"
                    response = client.post(
                        endpoint,
                        headers=headers,
                        json={"model": embedding_model(), "input": batch},
                    )
                response.raise_for_status()
                payload = response.json()
                vectors = payload.get("embeddings") if isinstance(payload, dict) else None
                if vectors is None and isinstance(payload, dict):
                    data = payload.get("data")
                    if isinstance(data, list):
                        vectors = [item.get("embedding") for item in data if isinstance(item, dict)]
                if not isinstance(vectors, list) or len(vectors) != len(batch):
                    raise ValueError("embedding response size mismatch")
                for vector in vectors:
                    if not isinstance(vector, list) or not vector:
                        raise ValueError("embedding vector empty")
                    results.append([float(value) for value in vector])
        return results
    except Exception:
        return None


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
