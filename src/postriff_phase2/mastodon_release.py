"""Independent Mastodon write release gate; OAuth consent and disconnect are separate.

The existing environment registry supplies booleans from REVIEWED,
PUBLISH_LIVE_TESTED and PUBLISH_APPROVED. Missing or non-boolean evidence fails closed.
This gate grants no per-action, account, workspace or automation authority.
"""


def write_qualified(provider):
    return (getattr(provider, 'id', None) == 'mastodon'
            and getattr(provider, 'execution_enabled', True) is True
            and all(getattr(provider, name, False) is True for name in
                    ('production_reviewed', 'publish_live_tested', 'publishing_permission')))
