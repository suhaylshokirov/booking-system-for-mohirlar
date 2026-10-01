"""`providers` (staff who perform services) and `provider_services` (who offers what).

Rules stored here: a provider is deactivated with `is_active`, never deleted.
`provider_services` has a composite primary key, so a provider cannot offer the
same service twice, and its foreign keys are `ON DELETE RESTRICT`: a service or
provider that is still linked cannot be hard-deleted by accident.

`phone` is optional and always stored as E.164 (`+998901234567`): the CHECK
refuses any other spelling, so every number on a page can be a working `tel:`
link. Typed input is normalised by `app/schemas/types.PhoneNumber`.
"""

from sqlalchemy import CheckConstraint, ForeignKey, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"
    __table_args__ = (
        CheckConstraint("char_length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name="phone_e164"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    bio: Mapped[str | None] = mapped_column(String(1000))
    phone: Mapped[str | None] = mapped_column(String(16))  # "+" and at most 15 digits
    is_active: Mapped[bool] = mapped_column(server_default=true())


class ProviderService(Base):
    """One row = "this provider performs this service"."""

    __tablename__ = "provider_services"

    provider_id: Mapped[int] = mapped_column(
        ForeignKey("providers.id", ondelete="RESTRICT"), primary_key=True
    )
    service_id: Mapped[int] = mapped_column(
        ForeignKey("services.id", ondelete="RESTRICT"), primary_key=True
    )
