from functools import cache

from django.conf import settings
from langchain.embeddings import init_embeddings


@cache
def get_embeddings():
    provider = settings.EMBEDDING_MODEL.split(':', 1)[0]
    kwargs = {'base_url': settings.OLLAMA_BASE_URL} if provider == 'ollama' else {}
    return init_embeddings(settings.EMBEDDING_MODEL, **kwargs)
