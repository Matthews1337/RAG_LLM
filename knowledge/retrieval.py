from functools import lru_cache

from django.conf import settings
from django.db import connection, transaction
from pgvector.django import CosineDistance

from .embeddings import get_embeddings
from .models import Chunk


@lru_cache(maxsize=256)
def embed_query(text):
    return tuple(get_embeddings().embed_query(text))


def search_chunks(query, topic_ids, k=None):
    """Trechos mais próximos da pergunta, restritos aos tópicos informados."""
    queryset = (
        Chunk.objects.filter(topic_id__in=topic_ids)
        .select_related('document', 'topic')
        .annotate(distance=CosineDistance('embedding', list(embed_query(query))))
        .order_by('distance')[: k or settings.RAG_TOP_K]
    )
    with transaction.atomic():
        with connection.cursor() as cursor:
            # Com o filtro por tópico, o índice HNSW pode devolver menos trechos que o pedido;
            # a varredura iterativa (pgvector >= 0.8) continua buscando até completar.
            cursor.execute('SET LOCAL hnsw.iterative_scan = strict_order')
        return list(queryset)


def best_chunk_per_topic(query, topic_ids, k=20):
    """O trecho mais próximo da pergunta em cada tópico, do mais próximo ao mais distante.

    Tópicos sem nenhum trecho entre os k mais próximos ficam de fora.
    """
    best = {}
    for chunk in search_chunks(query, topic_ids, k=k):
        best.setdefault(chunk.topic_id, chunk)
    return list(best.values())
