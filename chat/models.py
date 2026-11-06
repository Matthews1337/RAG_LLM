from django.conf import settings
from django.db import models
from django.urls import reverse

from knowledge.models import Topic


class Conversation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='conversations')
    title = models.CharField('título', max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'conversa'

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('chat:conversation', args=[self.pk])


class Message(models.Model):
    class Role(models.TextChoices):
        USER = 'user', 'Usuário'
        ASSISTANT = 'assistant', 'Assistente'

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=Role.choices)
    content = models.TextField()
    llm_model = models.CharField('modelo', max_length=100, blank=True)
    topics = models.ManyToManyField(Topic, blank=True, related_name='+', verbose_name='tópicos consultados')
    # Trechos usados na resposta: [{n, title, url, page, topic, content}]
    sources = models.JSONField(default=list, blank=True)
    # Preenchido quando o assistente perguntou qual tema o usuário quer: [{id, name}]
    clarification_options = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        verbose_name = 'mensagem'

    def __str__(self):
        return f'{self.get_role_display()}: {self.content[:50]}'

    def as_dict(self):
        return {
            'id': self.pk,
            'role': self.role,
            'content': self.content,
            'model': self.llm_model,
            'topics': [topic.name for topic in self.topics.all()],
            'sources': self.sources,
            'clarification_options': self.clarification_options,
        }
