"""Every logged-in dashboard page plus account self-service, split by area.

Re-exported here so `apps.accounts.urls` can keep using `views.<name>`.
Shared team-scoping helpers live in `common`.
"""

from .account import *  # noqa: F401,F403
from .prospect import *  # noqa: F401,F403
from .admin_dashboard import *  # noqa: F401,F403
from .admin_fees import *  # noqa: F401,F403
from .admin_invoices import *  # noqa: F401,F403
from .coach import *  # noqa: F401,F403
from .coach_tryouts import *  # noqa: F401,F403
from .mass_email import *  # noqa: F401,F403
from .parent import *  # noqa: F401,F403
from .common import _can_manage_tryout_signup, _get_coach_team_or_404, _get_roster_team_or_404  # noqa: F401
