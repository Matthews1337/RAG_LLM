from django.db.models import Count

from knowledge.models import Topic

from .models import Conversation


def sidebar(request):
    if not request.user.is_authenticated:
        return {}
    return {
        'sidebar_conversations': Conversation.objects.filter(user=request.user).only('pk', 'title')[:50],
        'sidebar_topics': Topic.objects.annotate(document_count=Count('documents')),
    }
