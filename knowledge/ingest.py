"""Extrai o texto dos documentos, divide em trechos e grava os embeddings no pgvector."""

import logging
import threading
from pathlib import Path

from django.conf import settings
from django.db import connection, transaction
from docx import Document as DocxDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from .embeddings import get_embeddings
from .models import Chunk, Document

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = ('.pdf', '.docx', '.txt', '.md')
EMBED_BATCH_SIZE = 32


def extract_pages(document):
    """Retorna [(número da página ou None, texto)]."""
    extension = Path(document.file.name).suffix.lower()
    with document.file.open('rb') as f:
        if extension == '.pdf':
            reader = PdfReader(f)
            return [(number, page.extract_text() or '') for number, page in enumerate(reader.pages, start=1)]
        if extension == '.docx':
            docx = DocxDocument(f)
            parts = [paragraph.text for paragraph in docx.paragraphs]
            for table in docx.tables:
                parts.extend(' | '.join(cell.text for cell in row.cells) for row in table.rows)
            return [(None, '\n'.join(parts))]
        return [(None, f.read().decode('utf-8', errors='replace'))]


def split_pages(pages):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE, chunk_overlap=settings.CHUNK_OVERLAP
    )
    return [
        # O Postgres não aceita o caractere NUL, comum em PDFs
        (page, text.replace('\x00', ''))
        for page, page_text in pages
        for text in splitter.split_text(page_text)
        if text.strip()
    ]


def process_document(document_id):
    document = Document.objects.get(pk=document_id)
    document.status = Document.Status.PROCESSING
    document.error = ''
    document.save(update_fields=['status', 'error'])

    try:
        pieces = split_pages(extract_pages(document))
        if not pieces:
            raise ValueError('Nenhum texto encontrado no arquivo. Se for um PDF escaneado, aplique OCR antes.')

        embeddings = get_embeddings()
        vectors = []
        for start in range(0, len(pieces), EMBED_BATCH_SIZE):
            batch = pieces[start:start + EMBED_BATCH_SIZE]
            vectors.extend(embeddings.embed_documents([text for _, text in batch]))

        with transaction.atomic():
            document.chunks.all().delete()
            Chunk.objects.bulk_create(
                Chunk(
                    document=document,
                    topic_id=document.topic_id,
                    position=position,
                    page=page,
                    content=text,
                    embedding=vector,
                )
                for position, ((page, text), vector) in enumerate(zip(pieces, vectors))
            )
            document.status = Document.Status.READY
            document.chunk_count = len(pieces)
            document.save(update_fields=['status', 'chunk_count'])
    except Exception as exc:
        logger.exception('Falha ao processar o documento %s', document_id)
        document.status = Document.Status.ERROR
        document.error = str(exc)
        document.chunk_count = 0
        document.save(update_fields=['status', 'error', 'chunk_count'])


def process_in_background(document_ids):
    """Processa os documentos em sequência numa thread, sem travar o upload.

    Suficiente para uso local; em produção troque por uma fila (Celery, RQ...).
    """
    def run():
        try:
            for document_id in document_ids:
                process_document(document_id)
        finally:
            connection.close()

    threading.Thread(target=run, daemon=True).start()
