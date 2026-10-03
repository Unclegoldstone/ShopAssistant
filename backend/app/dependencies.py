from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.services.chat import ChatService
from app.services.conversation_history import ConversationHistoryService
from app.services.database_test import DatabaseTestService
from app.services.extraction import ExtractionService
from app.services.faq_crud import FaqCrudService
from app.services.knowledge_test import KnowledgeTestService
from app.services.table_crud import TableCrudService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_conversation_history_service(request: Request) -> ConversationHistoryService:
    return request.app.state.conversation_history_service


def get_extraction_service(request: Request) -> ExtractionService:
    return request.app.state.extraction_service


def get_database_test_service(request: Request) -> DatabaseTestService:
    return request.app.state.database_test_service


def get_faq_crud_service(request: Request) -> FaqCrudService:
    return request.app.state.faq_crud_service


def get_table_crud_service(request: Request) -> TableCrudService:
    return request.app.state.table_crud_service


def get_knowledge_test_service(request: Request) -> KnowledgeTestService:
    return request.app.state.knowledge_test_service
