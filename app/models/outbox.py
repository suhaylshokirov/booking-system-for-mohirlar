"""`outbox_messages` — notifications waiting to be delivered (ADR 0009).

A row is written in the same transaction as the booking change it announces,
so the two commit or roll back together: a booking that was rolled back never
"sends" anything, and a committed one is never forgotten. A delivery worker
(not built; there is no SMTP dependency) would read unsent rows, send them and
set `sent_at`.

The recipient's address and the rendered text are copied here, like the price
snapshot on a booking (ADR 0007): what was promised to the customer stays
readable even if they later change their email or the service is renamed.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint(
            "event IN ('booking_created', 'booking_confirmed', 'booking_cancelled')",
            name="known_event",
        ),
        # The worker's query is "oldest unsent first"; the index holds only those.
        Index("ix_outbox_messages_unsent", "id", postgresql_where=text("sent_at IS NULL")),
        Index("ix_outbox_messages_booking", "booking_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event: Mapped[str] = mapped_column(String(30))
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"))
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    recipient_email: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    sent_at: Mapped[datetime | None]
