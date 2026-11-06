import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import Truncator
from django.views.decorators.http import require_POST
from langchain_core.messages import AIMessage, HumanMessage

from knowledge.models import Topic

from .graph import ANSWER_NODES, HISTORY_LIMIT, rag_graph, topic_names
from .llm import available_models, resolve_model_id
from .models import Conversation, Message

logger = logging.getLogger(__name__)


@login_required
def chat_view(request, pk=None):
    conversation = get_object_or_404(Conversation, pk=pk, user=request.user) if pk else None
    history = [m.as_dict() for m in conversation.messages.prefetch_related('topics')] if conversation else []
    models = available_models()
    return render(request, 'chat/chat.html', {
        'conversation': conversation,
        'history': history,
        'models': models,
        'default_model': resolve_model_id() if models else '',
        'has_topics': Topic.objects.exists(),
    })


@login_required
@require_POST
def conversation_delete(request, pk):
    get_object_or_404(Conversation, pk=pk, user=request.user).delete()
    return redirect('chat:home')


@login_required
@require_POST
def send_message(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Requisição inválida.'}, status=400)

    question = str(data.get('message') or '').strip()
    if not question:
        return JsonResponse({'error': 'Digite uma mensagem.'}, status=400)
    try:
        model_id = resolve_model_id(data.get('model'))
    except ImproperlyConfigured as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    if data.get('conversation_id'):
        conversation = get_object_or_404(Conversation, pk=data['conversation_id'], user=request.user)
    else:
        conversation = Conversation.objects.create(user=request.user, title=Truncator(question).chars(60))

    requested_topics = [int(i) for i in data.get('topic_ids') or [] if str(i).isdigit()]
    topic_ids = list(Topic.objects.filter(pk__in=requested_topics).values_list('pk', flat=True))

    # Clique em um tema depois de uma pergunta de esclarecimento: responde à pergunta original
    # naquele tema, em vez de tratar o nome do tema como uma nova pergunta
    graph_question, history_end = question, None
    last = conversation.messages.order_by('-id').first()
    if topic_ids and last and last.clarification_options:
        original = conversation.messages.filter(role=Message.Role.USER, id__lt=last.pk).order_by('-id').first()
        if original:
            graph_question, history_end = original.content, original.pk

    previous = conversation.messages.filter(id__lt=history_end) if history_end else conversation.messages.all()
    history = [
        HumanMessage(m.content) if m.role == Message.Role.USER else AIMessage(m.content)
        for m in reversed(previous.order_by('-id')[:HISTORY_LIMIT])
    ]
    Message.objects.create(conversation=conversation, role=Message.Role.USER, content=question)

    response = StreamingHttpResponse(
        stream_answer(conversation, graph_question, history, model_id, topic_ids),
        content_type='application/x-ndjson',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


def event(kind, **data):
    return json.dumps({'type': kind, **data}, ensure_ascii=False) + '\n'


def node_status(node, state):
    if node == 'rewrite_question':
        return 'Buscando nos documentos...' if state.get('topic_ids') else 'Identificando o tópico...'
    if node == 'classify_topic' and state.get('topic_ids'):
        return f'Buscando em: {", ".join(topic_names(state["topic_ids"]))}'
    if node == 'retrieve':
        return 'Escrevendo a resposta...'
    return None


def stream_answer(conversation, question, history, model_id, topic_ids):
    """Executa o grafo e envia ao navegador um JSON por linha (status, tokens e a mensagem final)."""
    yield event('conversation', id=conversation.pk, title=conversation.title, url=conversation.get_absolute_url())
    yield event('status', text='Analisando a pergunta...')

    state = {'topic_ids': topic_ids}
    try:
        for mode, payload in rag_graph.stream(
            {'question': question, 'history': history, 'model': model_id, 'topic_ids': topic_ids},
            stream_mode=['updates', 'messages'],
        ):
            if mode == 'messages':
                chunk, metadata = payload
                if metadata.get('langgraph_node') in ANSWER_NODES and chunk.text:
                    yield event('token', text=chunk.text)
                continue
            for node, update in payload.items():
                state.update(update or {})
                status = node_status(node, state)
                if status:
                    yield event('status', text=status)
    except Exception as exc:
        logger.exception('Erro no fluxo do RAG')
        yield event('error', message=f'Não foi possível gerar a resposta com {model_id}: {exc}')
        return

    clarification_ids = state.get('clarification_topic_ids') or []
    message = Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=state.get('answer', ''),
        llm_model=model_id,
        sources=state.get('sources') or [],
        clarification_options=[
            {'id': topic.pk, 'name': topic.name} for topic in Topic.objects.filter(pk__in=clarification_ids)
        ],
    )
    message.topics.set(state.get('topic_ids') or [])
    conversation.save(update_fields=['updated_at'])
    yield event('done', message=message.as_dict())
