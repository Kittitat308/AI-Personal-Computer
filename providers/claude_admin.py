"""Reserved Claude Admin provider.

The existing Admin CLI remains connected through ``core.admin.AdminAI``.
This separate class is intentionally not wired into provider selection yet.
"""

from core.admin import AdminAI


class ClaudeAdminAI(AdminAI):
    pass
