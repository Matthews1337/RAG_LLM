from django.urls import path

from . import views

app_name = 'knowledge'

urlpatterns = [
    path('novo/', views.topic_create, name='topic_create'),
    path('<slug:slug>/', views.topic_detail, name='topic_detail'),
    path('<slug:slug>/status/', views.topic_status, name='topic_status'),
    path('<slug:slug>/excluir/', views.topic_delete, name='topic_delete'),
    path('documentos/<int:pk>/reprocessar/', views.document_reprocess, name='document_reprocess'),
    path('documentos/<int:pk>/excluir/', views.document_delete, name='document_delete'),
]
