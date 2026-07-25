# Import every model module so Base.metadata is complete for create_all / Alembic autogen.
from app.models.household import Household  # noqa: F401
from app.models.user import User, Role  # noqa: F401
from app.models.session import UserSession  # noqa: F401
from app.models.connection import ProviderConnection, Provider, ConnStatus  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.account import Account, AccountType  # noqa: F401

