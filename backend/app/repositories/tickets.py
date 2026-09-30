from __future__ import annotations

from hashlib import sha256

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket


def ticket_number_from_tool_call(tool_call_id: str) -> str:
    digest = sha256(tool_call_id.encode("utf-8")).hexdigest()[:20].upper()
    return f"TK{digest}"


class TicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_get(
        self,
        *,
        conversation_id: str,
        tool_call_id: str,
        issue_description: str,
        ticket_type: str,
    ) -> Ticket:
        ticket_no = ticket_number_from_tool_call(tool_call_id)
        ticket = await self._session.get(Ticket, ticket_no)
        if ticket is not None:
            return ticket

        ticket = Ticket(
            ticket_no=ticket_no,
            conversation_id=conversation_id,
            issue_description=issue_description,
            ticket_type=ticket_type,
        )
        self._session.add(ticket)
        await self._session.flush()
        return ticket
