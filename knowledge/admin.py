from django.contrib import admin
from django.db import transaction
from django.db.models import Count

from .ingest import process_in_background
from .models import Chunk, Document, Topic


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ['name', 'document_count', 'created_at']
    search_fields = ['name', 'description']
    exclude = ['slug']

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(document_count=Count('documents'))

    @admin.display(description='documentos', ordering='document_count')
    def document_count(self, obj):
        return obj.document_count


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'topic', 'status', 'chunk_count', 'created_at']
    list_filter = ['topic', 'status']
    search_fields = ['title']
    readonly_fields = ['status', 'error', 'chunk_count', 'uploaded_by', 'created_at']
    actions = ['reprocess']

    def save_model(self, request, obj, form, change):
        if not change:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
        if not change or 'file' in form.changed_data:
            # O admin salva dentro de uma transação; a thread só pode ler o documento após o commit
            transaction.on_commit(lambda: process_in_background([obj.pk]))

    @admin.action(description='Reprocessar os documentos selecionados')
    def reprocess(self, request, queryset):
        ids = list(queryset.values_list('pk', flat=True))
        queryset.update(status=Document.Status.PENDING)
        transaction.on_commit(lambda: process_in_background(ids))
        self.message_user(request, f'{len(ids)} documento(s) enviado(s) para processamento.')


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ['document', 'position', 'page', 'topic']
    list_filter = ['topic']
    search_fields = ['content']
    exclude = ['embedding']
    readonly_fields = ['document', 'topic', 'position', 'page', 'content']

    def has_add_permission(self, request):
        return False
