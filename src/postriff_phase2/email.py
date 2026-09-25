"""Transactional email for the hosted consumer web: invitations, welcome, trial and billing notices.

Real: `ResendTransport` posts to Resend over HTTPS through the injected transport (defaults to
`providers.http_transport`). Fixture: `NullTransport` records messages in memory and is what tests
and the dev server use. `Mailer` renders plain, short text+HTML pairs and never raises to business
callers: an email failure must not fail an invite, a webhook, or a reminder sweep. `Reminders` is a
bounded, deduped sweep over `pr_trials` recorded in `pr_notifications` (migration 008).

Addresses are validated with the same rule as `HostedWorkspaceService.invite`. No message body,
address, or API key is ever logged or returned to API clients; `pr_notifications.meta` stays free
of addresses and bodies.
"""
import html
import math
import time
from postriff_alpha.domain import AlphaError
from postriff_phase2.providers import http_transport

RESEND_URL = "https://api.resend.com/emails"
MAX_PER_RUN = 50
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def valid_address(email):
    """Same plausibility rule as invite(): a string, contains '@', 3..254 chars."""
    return isinstance(email, str) and "@" in email and 3 <= len(email.strip()) <= 254


def _clean(value, limit=200):
    """Collapse whitespace (no header/line injection) and bound length; used for every interpolated string."""
    text = " ".join(str(value if value is not None else "").split())
    return text[:limit]


def _date(epoch):
    try:
        return time.strftime("%d %B %Y", time.gmtime(float(epoch)))
    except (TypeError, ValueError, OverflowError):
        return "soon"



# Automation notices (orchestration): subject, first paragraph, button label. Silence never approves, so the review
# notice says plainly that nothing is published without the person.
AUTOMATION_NOTICES = {
    "review_ready": ("Ready for your approval: {name}", "Your automation “{name}” prepared posts that need your approval. Nothing is published unless you approve it before its publish time.", "Review and approve"),
    "approval_expired": ("Not published: {name}", "A post from your automation “{name}” reached its publish time without an approval, so it was not published. The draft is kept.", "See the draft"),
    "platform_disconnected": ("Reconnect an account: {name}", "Your automation “{name}” couldn't publish because an account is disconnected. The draft is kept; reconnect the account to publish.", "Open the automation"),
    "publish_failed": ("Couldn't publish: {name}", "A post from your automation “{name}” couldn't be published. The approved draft is kept.", "Open the automation"),
    "run_skipped": ("Skipped this time: {name}", "Your automation “{name}” skipped this run.", "Open the automation"),
}

# Notices the Rafii NotificationService sends when RAFII_NOTIFICATIONS_V2_ENABLED is on (architecture lock N5).
# Invitations and welcome mail stay here: they are synchronous account operations that report `emailSent`.
V2_KINDS = frozenset({"review_ready", "approval_expired", "platform_disconnected", "publish_failed", "run_skipped", "drafts_ready",
                      "trial_ending", "payment_failed", "subscription_activated", "new_device"})
# trial_ended stays legacy: v2 has no trial-ended event, and routing it away would drop the email.


def _notifications_v2():
    from postriff_phase2.coworker import flags
    return flags.enabled("RAFII_NOTIFICATIONS_V2_ENABLED")


class NullTransport:
    """Fixture transport: records every message in `.sent` and delivers nothing."""

    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(dict(message))
        return {"id": f"null-{len(self.sent)}", "delivered": False}


class ResendTransport:
    """Real transport: POST https://api.resend.com/emails with a Bearer key. Raises AlphaError 502 on failure."""

    def __init__(self, api_key, transport=None):
        if not api_key or not isinstance(api_key, str):
            raise AlphaError("Email is not configured.", 503)
        self.api_key, self.transport = api_key, transport or http_transport

    def send(self, message):
        to = message.get("to")
        payload = {
            "from": message["from"],
            "to": [to] if isinstance(to, str) else list(to or []),
            "subject": message["subject"],
            "html": message["html"],
            "text": message["text"],
            "tags": [{"name": str(t["name"]), "value": str(t["value"])} for t in message.get("tags", [])],
        }
        if message.get("headers"):
            # List-Unsubscribe / List-Unsubscribe-Post from the notification renderer (RFC 8058); values are single-line.
            payload["headers"] = {str(k): " ".join(str(v).split())[:500] for k, v in message["headers"].items()}
        request_headers = {"Authorization": f"Bearer {self.api_key}"}
        if message.get("idempotencyKey"):
            # Resend deduplicates a retried send with the same key (NotificationService delivery id).
            request_headers["Idempotency-Key"] = str(message["idempotencyKey"])[:256]
        response = self.transport("POST", RESEND_URL, headers=request_headers, body=payload)
        status, body = response.get("status"), response.get("body")
        if not isinstance(status, int) or not 200 <= status < 300:
            raise AlphaError("The email service did not accept this message.", 502)
        return {"id": body.get("id") if isinstance(body, dict) else None}


class Mailer:
    """Builds text+HTML for each notice kind and hands it to the transport. Returns {'sent', 'kind'}; never raises."""
    KINDS = ("invitation", "welcome", "trial_ending", "trial_ended", "payment_failed", "subscription_activated", "new_device")

    def __init__(self, transport, from_address, public_base_url, brand="Rafii"):
        if not valid_address(from_address):
            raise AlphaError("Email sender address is not configured.", 503)
        self.transport, self.from_address = transport, from_address.strip()
        self.public_base_url, self.brand = str(public_base_url or "").rstrip("/"), _clean(brand, 40) or "Rafii"

    # ---- templates -------------------------------------------------------------------------------
    def _template(self, kind, ctx):
        """Returns (subject, paragraphs, button_label, button_url). All values are raw strings; escaping happens in render()."""
        b = self.brand
        if kind == "invitation":
            who, role = _clean(ctx.get("inviter_label"), 120) or f"A {b} user", _clean(ctx.get("role"), 40) or "member"
            return (f"You’re invited to a {b} workspace",
                    [f"{who} invited you to join their {b} workspace as {role}.",
                     f"This invitation expires on {_date(ctx.get('expires_at'))}. If you weren’t expecting it, you can ignore this email."],
                    "Accept invitation", ctx.get("accept_url"))
        if kind == "welcome":
            return (f"Welcome to {b}",
                    [f"Thanks for joining {b}. Your workspace is ready: connect a channel, add an idea, and draft your first post.",
                     "Nothing is published without your explicit approval."],
                    f"Open {b}", ctx.get("app_url"))
        if kind == "trial_ending":
            days = max(1, int(ctx.get("days_left") or 1))
            return (f"Your {b} trial ends in {days} day{'' if days == 1 else 's'}",
                    [f"Your {b} trial ends on {_date(ctx.get('expires_at'))}.",
                     "Choose a plan to keep drafting and publishing without interruption. Nothing is charged automatically; the trial never converts on its own."],
                    "See plans", ctx.get("pricing_url"))
        if kind == "trial_ended":
            note = _clean(ctx.get("export_note"), 300) or "You can still sign in to read and export your drafts and ideas."
            return (f"Your {b} trial has ended",
                    [f"Your {b} trial has ended. Drafting and publishing are paused until you choose a plan.", note],
                    "See plans", ctx.get("pricing_url"))
        if kind == "payment_failed":
            return ("Action needed: payment failed",
                    [f"We couldn’t collect your latest {b} payment.",
                     f"Please update your payment method before {_date(ctx.get('grace_until'))} to keep your plan active. Until then your workspace keeps working."],
                    "Update payment", ctx.get("billing_url"))
        if kind == "subscription_activated":
            plan = _clean(ctx.get("plan_label"), 60) or b
            return (f"Your {plan} plan is active",
                    [f"Thanks. Your {plan} plan on {b} is now active.",
                     "You can review invoices, change the plan, or cancel any time from billing."],
                    "Manage billing", ctx.get("billing_url"))
        if kind == "new_device":
            device = _clean(ctx.get("device_label"), 60) or "an unrecognised device"
            return (f"New sign-in to your {b} account",
                    [f"Someone signed in to your {b} account from {device} on {_date(ctx.get('at'))}.",
                     "If this was you, there is nothing to do. If it wasn’t, open your profile, sign out every other session and turn on two-factor authentication."],
                    "Review where you are signed in", ctx.get("profile_url"))
        if kind == "drafts_ready":
            name = _clean(ctx.get("automation_name"), 80) or "Your automation"
            count = max(1, int(ctx.get("count") or 1))
            drafts = f"{count} draft{'' if count == 1 else 's'}"
            return (f"{drafts} ready for review: {name}",
                    [f"Your automation “{name}” prepared {drafts} for your review.",
                     "Nothing was scheduled or published. Open the drafts to edit, approve or discard them."],
                    "Review drafts", ctx.get("review_url"))
        if kind in AUTOMATION_NOTICES:
            name = _clean(ctx.get("automation_name"), 80) or "Your automation"
            detail = _clean(ctx.get("detail"), 400)
            subject, lead, label = AUTOMATION_NOTICES[kind]
            return (subject.format(name=name), [lead.format(name=name), *([detail] if detail else [])], label, ctx.get("review_url"))
        raise AlphaError("Unknown email kind.", 500)

    def render(self, kind, **ctx):
        """(subject, text, html) for a kind. Text and HTML carry the same link; every string is escaped in HTML."""
        subject, paragraphs, label, url = self._template(kind, ctx)
        url = _clean(url, 2000)
        if not url.startswith(("https://", "http://")):
            raise AlphaError("Email link must be an absolute http(s) URL.", 500)
        privacy = f"{self.public_base_url}/privacy"
        footer = f"You received this because you have a {self.brand} account. Privacy: {privacy}"
        text = "\n\n".join([*paragraphs, f"{label}: {url}", footer]) + "\n"
        e = html.escape
        body = "".join(f'<p style="margin:0 0 16px 0;font-size:16px;line-height:24px;color:#1f2933;">{e(p)}</p>' for p in paragraphs)
        html_doc = (
            '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{e(subject)}</title></head>"
            f'<body style="margin:0;padding:0;background:#f5f6f8;font-family:{FONT};">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f6f8;"><tr><td align="center" style="padding:24px 16px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;background:#ffffff;border-radius:8px;">'
            f'<tr><td style="padding:32px 32px 8px 32px;font-family:{FONT};font-size:20px;font-weight:600;color:#111827;">{e(self.brand)}</td></tr>'
            f'<tr><td style="padding:8px 32px 0 32px;font-family:{FONT};">{body}</td></tr>'
            '<tr><td style="padding:8px 32px 32px 32px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="background:#111827;border-radius:6px;"><a href="{e(url)}" style="display:inline-block;padding:12px 20px;font-family:{FONT};font-size:16px;color:#ffffff;text-decoration:none;">{e(label)}</a></td>'
            "</tr></table>"
            f'<p style="margin:16px 0 0 0;font-family:{FONT};font-size:13px;line-height:20px;color:#6b7280;">If the button doesn’t work, open this link: <a href="{e(url)}" style="color:#374151;">{e(url)}</a></p></td></tr>'
            f'<tr><td style="padding:0 32px 32px 32px;font-family:{FONT};font-size:12px;line-height:18px;color:#6b7280;">You received this because you have a {e(self.brand)} account. Privacy: <a href="{e(privacy)}" style="color:#6b7280;">{e(privacy)}</a></td></tr>'
            "</table></td></tr></table></body></html>"
        )
        return subject, text, html_doc

    # ---- delivery --------------------------------------------------------------------------------
    def _deliver(self, kind, to, **ctx):
        if kind in V2_KINDS and _notifications_v2():
            # The notification service owns these notices (events derived from state, planned per preferences, HTML
            # templates, retries); sending here too would email the person twice.
            return {"sent": False, "kind": kind, "reason": "routed_to_notifications_v2"}
        try:
            if not valid_address(to):
                raise AlphaError("Enter a valid email address.")
            subject, text, html_doc = self.render(kind, **ctx)
            receipt = self.transport.send({"from": self.from_address, "to": to.strip().lower(), "subject": subject, "text": text, "html": html_doc, "tags": [{"name": "kind", "value": kind}]})
            if not isinstance(receipt, dict) or not receipt.get('id') or receipt.get('delivered') is False:
                return {"sent": False, "kind": kind, "reason": "Delivery not confirmed by the configured transport"}
            return {"sent": True, "kind": kind}
        except AlphaError as error:
            return {"sent": False, "kind": kind, "reason": str(error)}

    def invitation(self, to, inviter_label, role, accept_url, expires_at):
        return self._deliver("invitation", to, inviter_label=inviter_label, role=role, accept_url=accept_url, expires_at=expires_at)

    def welcome(self, to, app_url):
        return self._deliver("welcome", to, app_url=app_url)

    def trial_ending(self, to, days_left, expires_at, pricing_url):
        return self._deliver("trial_ending", to, days_left=days_left, expires_at=expires_at, pricing_url=pricing_url)

    def trial_ended(self, to, pricing_url, export_note):
        return self._deliver("trial_ended", to, pricing_url=pricing_url, export_note=export_note)

    def payment_failed(self, to, grace_until, billing_url):
        return self._deliver("payment_failed", to, grace_until=grace_until, billing_url=billing_url)

    def subscription_activated(self, to, plan_label, billing_url):
        return self._deliver("subscription_activated", to, plan_label=plan_label, billing_url=billing_url)

    def automation_notice(self, to, kind, automation_name, detail, review_url):
        """An automation needs the person: posts waiting for approval, an approval that expired, or an account that
        was disconnected before a post's time. Deduped per run and person in pr_notifications by the worker."""
        return self._deliver(kind, to, automation_name=automation_name, detail=detail, review_url=review_url)

    def drafts_ready(self, to, automation_name, count, review_url):
        """Opt-in: an automation prepared drafts (`CampaignWorker._notify`); one per run and person."""
        return self._deliver("drafts_ready", to, automation_name=automation_name, count=count, review_url=review_url)

    def new_device(self, to, device_label, at, profile_url):
        """Opt-in alert the first time a session is seen (hosted `_alert_new_device`)."""
        return self._deliver("new_device", to, device_label=device_label, at=at, profile_url=profile_url)


class Reminders:
    """Trial reminder sweep. Real when given a Postgres cursor; deduped by pr_notifications.dedupe_key, at most 50 sends per run.

    `email_lookup(user_id)` resolves the owner's address (Supabase Auth) and may return None, which skips the row.
    """
    EXPORT_NOTE = "You can still sign in to read and export your drafts and ideas; nothing is deleted automatically."
    _SELECT = ("SELECT t.workspace_id::text, m.user_id::text, extract(epoch from t.expires_at) FROM public.pr_trials t "
               "JOIN public.pr_memberships m ON m.workspace_id=t.workspace_id AND m.role='owner' AND m.status='active' "
               "WHERE t.workspace_id IS NOT NULL AND t.expires_at BETWEEN to_timestamp(%s) AND to_timestamp(%s) ORDER BY t.expires_at LIMIT %s")

    def __init__(self, mailer, email_lookup, clock=time.time):
        self.mailer, self.email_lookup, self.clock = mailer, email_lookup, clock

    def run(self, cur, now=None):
        now = float(self.clock() if now is None else now)
        windows = (("trial_ending", now + 2 * 86400, now + 3 * 86400), ("trial_ended", now - 86400, now))
        sent = skipped = 0
        pricing_url = f"{self.mailer.public_base_url}/pricing"
        for kind, start, end in windows:
            budget = MAX_PER_RUN - sent - skipped
            if budget <= 0:
                break
            cur.execute(self._SELECT, (start, end, budget))
            for workspace_id, user_id, expires_at in list(cur.fetchall() or []):
                expires_at = float(expires_at)
                cur.execute("INSERT INTO public.pr_notifications(workspace_id,user_id,kind,dedupe_key) VALUES(%s,%s,%s,%s) ON CONFLICT (dedupe_key) DO NOTHING RETURNING id::text",
                            (workspace_id, user_id, kind, f"{kind}:{workspace_id}:{int(expires_at)}"))
                inserted = cur.fetchone()
                if not inserted:
                    skipped += 1
                    continue
                address = self.email_lookup(user_id)
                if not address:
                    skipped += 1
                    continue
                if kind == "trial_ending":
                    days_left = max(1, int(math.ceil((expires_at - now) / 86400)))
                    result = self.mailer.trial_ending(address, days_left, expires_at, pricing_url)
                else:
                    result = self.mailer.trial_ended(address, pricing_url, self.EXPORT_NOTE)
                if result.get("sent"):
                    cur.execute("UPDATE public.pr_notifications SET sent=true WHERE id=%s", (inserted[0],))
                    sent += 1
                else:
                    skipped += 1
        return {"sent": sent, "skipped": skipped}
