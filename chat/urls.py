from django.urls import path

from . import views

app_name = 'chat'

urlpatterns = [
    path('', views.chat_view, name='home'),
    path('conversas/<int:pk>/', views.chat_view, name='conversation'),
    path('conversas/<int:pk>/excluir/', views.conversation_delete, name='conversation_delete'),
    path('api/mensagens/', views.send_message, name='send'),
]
