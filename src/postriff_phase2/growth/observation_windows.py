"""Native counter snapshots qualify only within the actual collection window.

The existing operator overdue boundary is ten minutes. Use that boundary as the
maximum collection lateness, not as permission to reconstruct missed horizons.
Backfill and untagged current snapshots have no historical horizon qualification.
"""
import math

OFFSETS = (('t0',0),('1h',3600),('24h',86400),('7d',604800))
SECONDS = dict(OFFSETS)
MAX_LATENESS_SECONDS = 600


def missed(row, at):
    anchor=row.get('anchorAt')
    offset=SECONDS.get(row.get('offset'))
    return (offset is not None and type(anchor) in (int,float) and math.isfinite(anchor)
            and at>anchor+offset+MAX_LATENESS_SECONDS)
