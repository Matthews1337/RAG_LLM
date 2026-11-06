from django.contrib import admin

from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    fields = ['role', 'content', 'llm_model', 'created_at']
    readonly_fields = fields
    extra = 0
    can_delete = False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'updated_at']
    list_filter = ['user']
    search_fields = ['title']
    inlines = [MessageInline]
