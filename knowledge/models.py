from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.text import slugify
from pgvector.django import HnswIndex, VectorField


class Topic(models.Model):
    name = models.CharField('nome', max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(
        'descrição',
        help_text='Descreva os assuntos cobertos. A IA usa este texto para decidir '
        'a qual tópico cada pergunta pertence.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'tópico'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('knowledge:topic_detail', args=[self.slug])


class Document(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Na fila'
        PROCESSING = 'processing', 'Processando'
        READY = 'ready', 'Pronto'
        ERROR = 'error', 'Erro'

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='documents', verbose_name='tópico')
    title = models.CharField('título', max_length=255)
    file = models.FileField('arquivo', upload_to='documents/%Y/%m/')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)
    chunk_count = models.PositiveIntegerField('trechos', default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'documento'

    def __str__(self):
        return self.title


@receiver(post_delete, sender=Document)
def delete_document_file(sender, instance, **kwargs):
    instance.file.delete(save=False)


class Chunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks')
    # Duplicado do documento para filtrar a busca vetorial por tópico sem JOIN
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='chunks')
    position = models.PositiveIntegerField()
    page = models.PositiveIntegerField(null=True, blank=True)
    content = models.TextField()
    embedding = VectorField(dimensions=settings.EMBEDDING_DIMENSIONS)

    class Meta:
        ordering = ['document', 'position']
        verbose_name = 'trecho'
        indexes = [
            HnswIndex(
                name='chunk_embedding_hnsw',
                fields=['embedding'],
                m=16,
                ef_construction=64,
                opclasses=['vector_cosine_ops'],
            ),
        ]

    def __str__(self):
        return f'{self.document} #{self.position}'
