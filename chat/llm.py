"""Acesso aos LLMs de qualquer provedor suportado pelo LangChain (Claude, OpenAI, Gemini, Ollama...)."""

import os
from functools import cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from langchain.chat_models import init_chat_model

# Provedores pagos só aparecem no chat quando a chave está configurada
PROVIDER_API_KEYS = {
    'anthropic': 'ANTHROPIC_API_KEY',
    'openai': 'OPENAI_API_KEY',
    'google_genai': 'GOOGLE_API_KEY',
    'groq': 'GROQ_API_KEY',
    'mistralai': 'MISTRAL_API_KEY',
}

PROVIDER_LABELS = {
    'anthropic': 'Claude',
    'openai': 'OpenAI',
    'google_genai': 'Gemini',
    'ollama': 'Ollama',
    'groq': 'Groq',
    'mistralai': 'Mistral',
}


def available_models():
    models = []
    for model_id in settings.LLM_MODELS:
        provider, name = model_id.split(':', 1)
        api_key = PROVIDER_API_KEYS.get(provider)
        if api_key and not os.environ.get(api_key):
            continue
        models.append({'id': model_id, 'name': name, 'provider': PROVIDER_LABELS.get(provider, provider)})
    return models


def resolve_model_id(requested=None):
    """Valida o modelo pedido pelo navegador; se não estiver disponível, usa o padrão."""
    model_ids = [model['id'] for model in available_models()]
    for candidate in (requested, settings.DEFAULT_LLM_MODEL):
        if candidate in model_ids:
            return candidate
    if model_ids:
        return model_ids[0]
    raise ImproperlyConfigured('Nenhum LLM disponível. Configure LLM_MODELS e as chaves de API no .env.')


@cache
def get_chat_model(model_id):
    provider = model_id.split(':', 1)[0]
    kwargs = {}
    if provider == 'ollama':
        kwargs = {'base_url': settings.OLLAMA_BASE_URL, 'temperature': 0, 'num_ctx': 8192}
    return init_chat_model(model_id, **kwargs)
