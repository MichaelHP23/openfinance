from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin, TimestampMixin


class Household(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "households"
    name: Mapped[str] = mapped_column()
