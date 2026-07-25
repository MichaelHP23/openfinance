# Import every model module so Base.metadata is complete for create_all / Alembic autogen.
from app.models.household import Household  # noqa: F401
from app.models.user import User, Role  # noqa: F401
from app.models.session import UserSession  # noqa: F401

