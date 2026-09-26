"""Workspace role and action-permission model (architecture spec section 8).

Every hosted mutation names an action; the action maps to one requirement class.
Unknown actions fail closed. Cross-tenant denials must stay indistinguishable from
missing resources ("Workspace unavailable."), so this module only raises for
members who exist but lack a right.
"""
from postriff_alpha.domain import AlphaError

ROLES = ("owner", "admin", "editor", "approver", "viewer")
FLAGS = ("can_publish", "can_reply", "can_moderate", "can_manage_connections")

# Requirement classes. Roles listed always qualify; a flag grants the class to any
# non-viewer member that carries it. Owners qualify for everything.
CLASSES = {
    "read": {"roles": ROLES, "flag": None},
    "edit": {"roles": ("owner", "admin", "editor"), "flag": None},
    "approve": {"roles": ("owner", "approver"), "flag": "can_publish"},
    "reply": {"roles": ("owner",), "flag": "can_reply"},
    "moderate": {"roles": ("owner",), "flag": "can_moderate"},
    "manage_connections": {"roles": ("owner", "admin"), "flag": "can_manage_connections"},
    "manage_members": {"roles": ("owner", "admin"), "flag": None},
    "owner": {"roles": ("owner",), "flag": None},
}

# Hosted actions that are not plain editorial edits. Anything absent is "edit".
ACTION_CLASSES = {
    "p2_review": "approve", "p2_approve": "approve", "p2_approve_many": "approve", "p2_cancel": "approve",
    "p2_channel_add": "manage_connections", "p2_channel_verify": "manage_connections",
    "p2_channel_disconnect": "manage_connections",
    "p2_plan": "owner",
    # Whether memory files may reach a cloud model is a workspace privacy decision.
    "memory_egress": "owner",
    "research_egress": "owner",
    # The workspace default writer (Auto) decides which AI provider receives everyone's cloud-allowed sources.
    "writer_defaults": "owner",
    # Accepting or undoing a learned preference changes how every member's drafts read (design decision D);
    # approving the voice profile itself changes them just as much, so it is an owner decision too.
    "preference": "owner", "learning_settings": "owner", "learning_reset": "owner", "profile_decide": "owner", "you_restore_voice": "owner",
    # This is the durable privacy boundary for analysis/generation routes.
    "voice_sample_grant": "owner",
    "raffi_recurrence_activate": "owner", "raffi_recurrence_pause": "owner",
    "raffi_recurrence_resume": "owner", "raffi_recurrence_cancel": "owner",
    # Deciding on an automation's drafted post is a publication decision, like approving in Queue; the worker
    # commits an approved post as the person who approved it (publisher.commit), under the same class.
    "raffi_run_decide": "approve", "raffi_run_commit": "approve",
    # Any member may ask for their own "drafts ready" email; it changes nothing that is drafted.
    "raffi_recurrence_watch": "read",
    "refresh": "read", "p2_refresh": "read",
}

# Actions that additionally require a recently verified sign-in (step-up).
STEP_UP_ACTIONS = {"p2_channel_disconnect", "delete_account", "member_update", "member_remove", "invitation_create", "session_revoke"}
STEP_UP_WINDOW = 600  # seconds since the session's verified auth time


class Membership:
    __slots__ = ("role", "flags")

    def __init__(self, role, flags=None):
        if role not in ROLES:
            raise AlphaError("Workspace unavailable.", 403)
        self.role = role
        self.flags = {name: bool((flags or {}).get(name)) for name in FLAGS}

    @classmethod
    def from_row(cls, role, can_publish=False, can_reply=False, can_moderate=False, can_manage_connections=False):
        return cls(role, {"can_publish": can_publish, "can_reply": can_reply, "can_moderate": can_moderate, "can_manage_connections": can_manage_connections})

    def allows(self, requirement):
        spec = CLASSES.get(requirement)
        if spec is None:
            return False
        if self.role == "owner" or self.role in spec["roles"]:
            return True
        return bool(spec["flag"]) and self.role != "viewer" and self.flags[spec["flag"]]

    def summary(self):
        return {"role": self.role, **self.flags}


def classify(action):
    if not isinstance(action, str) or not action:
        raise AlphaError("Expected a structured command.")
    return ACTION_CLASSES.get(action, "edit")


def require(membership, requirement):
    if not membership.allows(requirement):
        raise AlphaError(f"This action needs the '{requirement}' permission in this workspace.", 403)


def require_action(membership, action):
    require(membership, classify(action))


def validate_grant(role, flags, granted_by):
    """A member may grant only roles/flags at or below their own authority."""
    if role not in ROLES or role == "owner":
        raise AlphaError("Choose admin, editor, approver, or viewer.")
    if not isinstance(flags, dict) or set(flags) - set(FLAGS) or any(type(value) is not bool for value in flags.values()):
        raise AlphaError("Permissions must be explicit true/false flags.")
    if granted_by.role != "owner":
        for name, value in flags.items():
            if value and not granted_by.flags[name]:
                raise AlphaError(f"You cannot grant '{name}' because you do not hold it.", 403)
        if role == "admin" and granted_by.role != "admin":
            raise AlphaError("Only owners and admins may create admins.", 403)
    return {name: bool(flags.get(name, False)) for name in FLAGS}
