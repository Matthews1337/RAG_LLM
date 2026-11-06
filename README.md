# Chat RAG por tópicos

Chat em Django para perguntar sobre documentos. Os administradores organizam os documentos em **tópicos** (ex.: "Legislação brasileira", "Tecnologia"). A cada pergunta, um fluxo em LangGraph identifica o tópico, busca os trechos mais relevantes no pgvector e responde citando as fontes. Quando a pergunta serve para mais de um tópico, a IA pergunta qual tema o usuário quer.

## Como rodar

```powershell
docker compose up -d                                  # Postgres + pgvector (5433) e Ollama (11434, usa a GPU)
docker compose exec ollama ollama pull bge-m3         # modelo de embeddings
docker compose exec ollama ollama pull qwen2.5:3b     # LLM open source local (opcional)

python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env                                # e preencha DJANGO_SECRET_KEY e as chaves de API

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Acesse http://127.0.0.1:8000, entre com o superusuário, clique em **+ Novo tópico** no menu lateral e envie os documentos (PDF, DOCX, TXT ou MD). Eles são processados em segundo plano, e o status aparece na página do tópico.

Usuários comuns (sem `is_staff`) só conversam. Eles são criados no admin, em `/admin/`.

## LLMs

Os modelos exibidos no chat vêm de `LLM_MODELS` no `.env`, no formato `provedor:modelo`:

| Provedor | Exemplo | Chave no `.env` |
|---|---|---|
| Ollama (open source, local) | `ollama:qwen2.5:3b` | — |
| Claude | `anthropic:claude-sonnet-5-5` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai:gpt-5-mini` | `OPENAI_API_KEY` |
| Gemini | `google_genai:gemini-flash-latest` | `GOOGLE_API_KEY` |

Um modelo pago só aparece quando a chave dele está preenchida. Qualquer provedor suportado pelo `init_chat_model` do LangChain funciona, desde que o pacote `langchain-<provedor>` esteja instalado.

`ROUTER_LLM_MODEL` define o modelo que reescreve e classifica a pergunta. Deixe vazio para usar o mesmo modelo escolhido no chat, ou aponte para um modelo rápido e barato (ex.: `anthropic:claude-haiku-5-5`).

## Fluxo do LangGraph ([chat/graph.py](chat/graph.py))

```
START → rewrite_question ─┬─ tema escolhido pelo usuário ──────────► retrieve → generate_answer → END
                          └─► classify_topic ─┬─ tópico(s) claros ─► retrieve
                                              ├─ ambígua ──────────► ask_clarification → END
                                              └─ nenhum tópico ────► answer_off_topic → END
```

1. **rewrite_question**: transforma a mensagem numa pergunta independente, usando o histórico ("e no Python?" vira "Como funciona a herança em Python?").
2. **classify_topic**: busca no pgvector o trecho mais parecido de cada tópico.
   - Se dois ou mais tópicos são relevantes e estão praticamente empatados, a pergunta é ambígua.
   - Caso contrário, o LLM escolhe o tópico com base na descrição dele e nesses trechos.
3. **ask_clarification**: pergunta qual tema o usuário quer, com um botão por tópico e a opção "Todos esses temas".
4. **retrieve** e **generate_answer**: busca os trechos nos tópicos escolhidos e responde citando as fontes como [1], [2]...

A descrição do tópico importa: é com ela que o LLM decide para onde vai cada pergunta.

### Ajustes de ambiguidade

`RAG_MAX_DISTANCE` (0,45) e `RAG_AMBIGUITY_MARGIN` (0,03) estão calibrados para o `bge-m3`:
- Se a IA pergunta o tema demais, diminua a margem.
- Se não pergunta quando deveria, aumente a margem.

## Trocar o modelo de embeddings

Altere `EMBEDDING_MODEL` e `EMBEDDING_DIMENSIONS` no `.env`. Depois, rode `python manage.py makemigrations knowledge`. Por fim, apague os trechos antigos e reindexe:

```powershell
python manage.py shell -c "from knowledge.models import Chunk; Chunk.objects.all().delete()"
python manage.py migrate
python manage.py reindex
```

## Produção

O processamento de documentos roda numa thread, o que basta para uso local. Em produção, use uma fila (Celery ou RQ) e sirva o Django com um servidor que suporte streaming.
