# Import every model module so Base.metadata is complete for create_all / Alembic autogen.
from app.models.account import Account, AccountType  # noqa: F401
from app.models.budget import Budget  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.category_rule import CategoryRule, MatchType, RuleSource  # noqa: F401
from app.models.connection import ConnStatus, Provider, ProviderConnection  # noqa: F401
from app.models.household import Household  # noqa: F401
from app.models.recurring import Cadence, RecurringSeries, SeriesStatus  # noqa: F401
from app.models.security import Security  # noqa: F401
from app.models.security_price import SecurityPrice  # noqa: F401
from app.models.session import UserSession  # noqa: F401
from app.models.snapshot import BalanceSnapshot  # noqa: F401
from app.models.trade import Trade, TradeType  # noqa: F401
from app.models.transaction import Transaction  # noqa: F401
from app.models.user import Role, User  # noqa: F401
