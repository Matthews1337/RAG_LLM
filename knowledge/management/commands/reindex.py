from django.core.management.base import BaseCommand

from knowledge.ingest import process_document
from knowledge.models import Document


class Command(BaseCommand):
    help = 'Gera novamente os trechos e embeddings dos documentos (necessário ao trocar o modelo de embeddings).'

    def add_arguments(self, parser):
        parser.add_argument('--topic', help='Slug do tópico. Sem ele, reindexa todos os documentos.')

    def handle(self, *args, topic=None, **options):
        documents = Document.objects.select_related('topic')
        if topic:
            documents = documents.filter(topic__slug=topic)

        for document in documents:
            self.stdout.write(f'{document.topic} / {document.title}... ', ending='')
            process_document(document.pk)
            document.refresh_from_db()
            if document.status == Document.Status.READY:
                self.stdout.write(self.style.SUCCESS(f'{document.chunk_count} trechos'))
            else:
                self.stdout.write(self.style.ERROR(document.error))
