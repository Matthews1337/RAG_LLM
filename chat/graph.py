"""Fluxo do RAG em LangGraph.

    START → rewrite_question ─┬─ (tópico já escolhido pelo usuário) ──────────► retrieve → generate_answer → END
                              └─► classify_topic ─┬─ tópico(s) identificado(s) ─► retrieve
                                                  ├─ pergunta ambígua ──────────► ask_clarification → END
                                                  └─ nenhum tópico ─────────────► answer_off_topic → END
"""

import logging
from typing import TypedDict

from django.conf import settings
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from knowledge.models import Topic
from knowledge.retrieval import best_chunk_per_topic, search_chunks

from .llm import get_chat_model

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 6

# Nós cujos tokens são enviados ao navegador em tempo real
ANSWER_NODES = {'generate_answer', 'answer_off_topic'}


class RagState(TypedDict, total=False):
    question: str  # última mensagem do usuário
    history: list[BaseMessage]  # mensagens anteriores da conversa
    model: str  # "provedor:modelo" escolhido no chat
    search_query: str  # pergunta reescrita para ser entendida sem o histórico
    topic_ids: list[int]  # onde buscar; já vem preenchido quando o usuário escolhe um tópico
    clarification_topic_ids: list[int]
    clarifying_question: str
    sources: list[dict]
    answer: str


class TopicChoice(BaseModel):
    """Classificação da pergunta nos tópicos da base de documentos."""

    topic_ids: list[int] = Field(
        description='IDs dos tópicos a que a pergunta pertence. Vazio se não pertencer a nenhum.'
    )
    ambiguous: bool = Field(
        description='true quando a pergunta pode ser de mais de um tópico e não dá para saber qual o usuário quer.'
    )
    clarifying_question: str = Field(
        default='',
        description='Quando ambiguous for true: pergunta curta e direta ao usuário sobre qual tema ele quer.',
    )


REWRITE_PROMPT = """Reescreva a última mensagem do usuário como uma pergunta completa e independente, \
que possa ser entendida sem ler a conversa.
- Se a mensagem responde a uma pergunta do assistente (por exemplo, informando o tema), junte-a com a \
pergunta original do usuário.
- Se a mensagem já é independente, devolva-a sem mudanças.
- Mantenha o idioma do usuário. Não responda à pergunta.
Responda apenas com a pergunta reescrita."""

CLASSIFY_PROMPT = """Você classifica perguntas nos tópicos de uma base de documentos.
Para cada tópico há a descrição e o trecho dos documentos mais parecido com a pergunta.

Tópicos:
{topics}

Regras:
- Devolva em topic_ids o id do tópico a que a pergunta pertence.
- Se a pergunta trata ao mesmo tempo de assuntos de mais de um tópico, devolva todos eles e ambiguous=false.
- Se a pergunta pode se referir a tópicos diferentes e não dá para saber qual o usuário quer (por exemplo, \
o mesmo termo aparece em dois tópicos com sentidos diferentes), devolva os candidatos em topic_ids, \
ambiguous=true e escreva em clarifying_question uma pergunta direta, no idioma do usuário, perguntando \
sobre qual tema ele quer saber.
- Se a pergunta não tem relação com nenhum tópico (cumprimentos, conversa casual, outros assuntos), devolva \
topic_ids vazio."""

ANSWER_PROMPT = """Você é um assistente que responde com base nos documentos de uma base de conhecimento.

Pergunta atual, reescrita de forma independente: {query}

Trechos encontrados nos documentos de {topics}:

{context}

Instruções:
- Use apenas as informações dos trechos acima. Não invente.
- Cite as fontes com o número do trecho entre colchetes, como [1] ou [2][3].
- Se os trechos não trazem a resposta, diga que não encontrou essa informação nos documentos.
- Responda no idioma do usuário, em Markdown."""

OFF_TOPIC_PROMPT = """Você é o assistente de uma base de documentos organizada nos tópicos: {topics}.
A mensagem do usuário não se encaixa em nenhum desses tópicos.
- Se for um cumprimento ou conversa casual, responda de forma breve e cordial e diga em quais tópicos pode ajudar.
- Caso contrário, explique que não há documentos sobre esse assunto e liste os tópicos disponíveis.
Nunca responda à pergunta com conhecimento próprio, mesmo que saiba a resposta. Responda no idioma do usuário."""


def router_llm(state):
    return get_chat_model(settings.ROUTER_LLM_MODEL or state['model'])


def recent_history(state):
    history = (state.get('history') or [])[-HISTORY_LIMIT:]
    # Claude e Gemini exigem que a conversa comece com uma mensagem do usuário
    while history and history[0].type != 'human':
        history = history[1:]
    return history


def join_names(names):
    names = list(names)
    if len(names) <= 1:
        return ''.join(names)
    return f'{", ".join(names[:-1])} ou {names[-1]}'


def topic_names(topic_ids):
    return Topic.objects.filter(pk__in=topic_ids).values_list('name', flat=True)


def rewrite_question(state):
    history = recent_history(state)
    if not history:
        return {'search_query': state['question']}

    conversation = '\n'.join(
        f'{"Usuário" if message.type == "human" else "Assistente"}: {message.text}' for message in history
    )
    response = router_llm(state).invoke([
        SystemMessage(REWRITE_PROMPT),
        HumanMessage(f'Conversa:\n{conversation}\n\nÚltima mensagem do usuário: {state["question"]}'),
    ])
    return {'search_query': response.text.strip() or state['question']}


def tied_topics(evidence):
    """Tópicos relevantes cujo melhor trecho está praticamente empatado com o do tópico mais próximo."""
    relevant = [chunk for chunk in evidence if chunk.distance <= settings.RAG_MAX_DISTANCE]
    if len(relevant) < 2:
        return []
    best = relevant[0].distance
    return [chunk.topic_id for chunk in relevant if chunk.distance - best <= settings.RAG_AMBIGUITY_MARGIN]


def describe_topic(topic, chunk):
    snippet = ' '.join(chunk.content.split())[:300] if chunk else '(nenhum trecho parecido)'
    return f'- id {topic["id"]}: {topic["name"]} — {topic["description"]}\n  Trecho mais parecido: "{snippet}"'


def classify_topic(state):
    topics = list(Topic.objects.values('id', 'name', 'description'))
    if not topics:
        return {'topic_ids': []}

    evidence = best_chunk_per_topic(state['search_query'], [t['id'] for t in topics])
    # Tópicos empatados na busca vetorial: os documentos de mais de um tópico respondem igualmente bem,
    # então a pergunta é ambígua mesmo que um LLM escolhesse um deles (ou todos)
    tied = tied_topics(evidence)
    if len(tied) > 1:
        return {'clarification_topic_ids': tied}

    by_topic = {chunk.topic_id: chunk for chunk in evidence}
    listing = '\n'.join(describe_topic(topic, by_topic.get(topic['id'])) for topic in topics)

    llm = router_llm(state).with_structured_output(TopicChoice)
    try:
        choice = llm.invoke([
            SystemMessage(CLASSIFY_PROMPT.format(topics=listing)),
            HumanMessage(state['search_query']),
        ])
    except Exception:
        choice = None
        logger.warning('Falha ao classificar a pergunta', exc_info=True)
    if choice is None:
        # Modelos pequenos às vezes não devolvem JSON válido: usa só a busca vetorial
        return {'topic_ids': [chunk.topic_id for chunk in evidence if chunk.distance <= settings.RAG_MAX_DISTANCE]}

    valid_ids = {t['id'] for t in topics}
    topic_ids = [topic_id for topic_id in dict.fromkeys(choice.topic_ids) if topic_id in valid_ids]
    if choice.ambiguous and len(topic_ids) > 1:
        return {'clarification_topic_ids': topic_ids, 'clarifying_question': choice.clarifying_question.strip()}
    return {'topic_ids': topic_ids}


def ask_clarification(state):
    question = state.get('clarifying_question') or (
        f'Sua pergunta pode se referir a {join_names(topic_names(state["clarification_topic_ids"]))}. '
        'Sobre qual desses temas você quer saber?'
    )
    return {'answer': question}


def retrieve(state):
    chunks = search_chunks(state['search_query'], state['topic_ids'])
    sources = [
        {
            'n': n,
            'title': chunk.document.title,
            'url': chunk.document.file.url,
            'page': chunk.page,
            'topic': chunk.topic.name,
            'content': chunk.content,
        }
        for n, chunk in enumerate(chunks, start=1)
    ]
    return {'sources': sources}


def format_source(source):
    page = f' (p. {source["page"]})' if source['page'] else ''
    return f'[{source["n"]}] {source["title"]}{page}\n{source["content"]}'


def generate_answer(state):
    context = '\n\n'.join(format_source(source) for source in state.get('sources') or [])
    system = ANSWER_PROMPT.format(
        query=state['search_query'],
        topics=join_names(topic_names(state['topic_ids'])),
        context=context or '(nenhum trecho encontrado)',
    )
    response = get_chat_model(state['model']).invoke([
        SystemMessage(system),
        *recent_history(state),
        HumanMessage(state['question']),
    ])
    return {'answer': response.text}


def answer_off_topic(state):
    names = ', '.join(Topic.objects.values_list('name', flat=True)) or '(nenhum tópico cadastrado ainda)'
    response = get_chat_model(state['model']).invoke([
        SystemMessage(OFF_TOPIC_PROMPT.format(topics=names)),
        *recent_history(state),
        HumanMessage(state['question']),
    ])
    return {'answer': response.text}


def route_after_rewrite(state):
    return 'retrieve' if state.get('topic_ids') else 'classify_topic'


def route_after_classify(state):
    if state.get('clarification_topic_ids'):
        return 'ask_clarification'
    if state.get('topic_ids'):
        return 'retrieve'
    return 'answer_off_topic'


def build_graph():
    graph = StateGraph(RagState)
    for node in (rewrite_question, classify_topic, ask_clarification, retrieve, generate_answer, answer_off_topic):
        graph.add_node(node)

    graph.add_edge(START, 'rewrite_question')
    graph.add_conditional_edges('rewrite_question', route_after_rewrite, ['retrieve', 'classify_topic'])
    graph.add_conditional_edges(
        'classify_topic', route_after_classify, ['ask_clarification', 'retrieve', 'answer_off_topic']
    )
    graph.add_edge('retrieve', 'generate_answer')
    for node in ('ask_clarification', 'generate_answer', 'answer_off_topic'):
        graph.add_edge(node, END)
    return graph.compile()


rag_graph = build_graph()
