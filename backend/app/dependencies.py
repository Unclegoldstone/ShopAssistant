from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.services.chat import ChatService
from app.services.extraction import ExtractionService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_extraction_service(request: Request) -> ExtractionService:
    return request.app.state.extraction_service

