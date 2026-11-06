from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import DocumentUploadForm, TopicForm
from .ingest import process_in_background
from .models import Document, Topic


def staff_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


@staff_required
def topic_create(request):
    form = TopicForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        topic = form.save(commit=False)
        topic.created_by = request.user
        topic.save()
        messages.success(request, f'Tópico "{topic}" criado. Agora envie os documentos.')
        return redirect(topic)
    return render(request, 'knowledge/topic_form.html', {'form': form})


@staff_required
def topic_detail(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    form = TopicForm(instance=topic)
    upload_form = DocumentUploadForm()

    if request.method == 'POST' and 'upload' in request.POST:
        upload_form = DocumentUploadForm(request.POST, request.FILES)
        if upload_form.is_valid():
            ids = [
                Document.objects.create(topic=topic, title=f.name, file=f, uploaded_by=request.user).pk
                for f in upload_form.cleaned_data['files']
            ]
            transaction.on_commit(lambda: process_in_background(ids))
            messages.success(request, f'{len(ids)} documento(s) enviado(s) para processamento.')
            return redirect(topic)
    elif request.method == 'POST':
        form = TopicForm(request.POST, instance=topic)
        if form.is_valid():
            topic = form.save()
            messages.success(request, 'Tópico atualizado.')
            return redirect(topic)

    return render(request, 'knowledge/topic_detail.html', {
        'topic': topic,
        'form': form,
        'upload_form': upload_form,
        'documents': topic.documents.all(),
    })


@staff_required
def topic_status(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    documents = [
        {
            'id': d.pk,
            'status': d.status,
            'status_label': d.get_status_display(),
            'chunk_count': d.chunk_count,
            'error': d.error,
        }
        for d in topic.documents.all()
    ]
    return JsonResponse({'documents': documents})


@staff_required
@require_POST
def topic_delete(request, slug):
    topic = get_object_or_404(Topic, slug=slug)
    topic.delete()
    messages.success(request, f'Tópico "{topic}" excluído.')
    return redirect('chat:home')


@staff_required
@require_POST
def document_reprocess(request, pk):
    document = get_object_or_404(Document, pk=pk)
    document.status = Document.Status.PENDING
    document.save(update_fields=['status'])
    process_in_background([document.pk])
    return redirect(document.topic)


@staff_required
@require_POST
def document_delete(request, pk):
    document = get_object_or_404(Document, pk=pk)
    topic = document.topic
    document.delete()
    messages.success(request, f'Documento "{document}" excluído.')
    return redirect(topic)
