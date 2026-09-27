"""Professional HTML email for Rafii notifications (adaptive coworker spec §17; architecture lock E1).

Reusable, table-based components with inline styles (email clients ignore most CSS), a `<style>` block only for
dark-mode and small-screen refinements, and a plain-text twin for every message. The visual system follows the
Rafii app: white card on a quiet grey page, editorial serif headline, black pill primary action, grey secondary
text, one small status pill.

Rules enforced here:
- every interpolated value is HTML-escaped; subjects and preheaders are single-line and carry no private content
  (no draft text, no DM, no handle, no amount);
- exactly one primary CTA, an absolute https deep link built from a relative `/app/...` path (anything else falls
  back to `/app`);
- a notification-settings link and, for non-transactional mail, a signed one-click unsubscribe link
  (List-Unsubscribe + List-Unsubscribe-Post headers);
- localised subject, preheader and body (en, zh-Hant-HK, zh-Hant, zh-Hans; Cantonese locales use Hong Kong written
  Chinese), and a deterministic TEMPLATE_VERSION recorded on each delivery.
"""
from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

TEMPLATE_VERSION = "rafii-email/1.1.0"
LOCALES_PATH = Path(__file__).with_name("email_locales.json")
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,'PingFang HK','PingFang TC','Noto Sans CJK TC','Microsoft JhengHei',sans-serif"
SERIF = "Georgia,'Times New Roman','Songti TC','Noto Serif CJK TC',serif"
INK, INK_2, INK_3, PAGE, CARD, LINE = "#111111", "#4d4d4d", "#6b6b6b", "#f2f2f2", "#ffffff", "#e5e5e5"
# Calm, monochrome status labels. Severity is written explicitly, never conveyed by colour alone.
PILL = {kind: ("#e8e8e8", "#111111") for kind in ("action","critical","warning","info","security","success")}
_SAFE_PATH = re.compile(r"^/app(?:/[A-Za-z0-9._~\-]*)*(?:\?[A-Za-z0-9._~\-=&%]*)?$")
# The template each event family renders with (catalogue `template`); anything else uses the digest shell.
TEMPLATES = ("weekly_ready", "drafts_ready", "approval_required", "campaign_blocked", "needs_input", "asset_review", "publish_scheduled",
             "publish_verified", "publish_failed", "publish_uncertain", "channel_reconnect", "automation_completed", "automation_failed", "engagement",
             "opportunity", "weekly_performance", "analytics_anomaly", "preference_proposed", "budget_threshold", "payment_failed", "trial_ending",
             "subscription_active", "security_alert", "digest", "phone_call_failed")


@lru_cache(maxsize=1)
def catalogue():
    return json.loads(LOCALES_PATH.read_text())


def resolve_locale(tag):
    """Map a person's locale to a shipped email locale. Cantonese (yue) reads Hong Kong written Chinese in email."""
    tag = (tag or "").strip()
    lowered = tag.lower()
    if lowered.startswith("yue") or lowered in ("zh-hk", "zh-mo", "zh-hant-hk", "zh-hant-mo"):
        return "zh-Hant-HK"
    if lowered.startswith("zh-hans") or lowered in ("zh-cn", "zh-sg", "zh"):
        return "zh-Hans"
    if lowered.startswith("zh"):
        return "zh-Hant"
    return "en"


def _fmt(template, values):
    """Fill {placeholders} with cleaned values; unknown placeholders render empty, never as raw braces."""
    def replace(match):
        value = values.get(match.group(1))
        return "" if value is None else " ".join(str(value).split())[:160]
    return re.sub(r"\{([a-zA-Z]+)\}", replace, template or "").strip()


def one_line(value, limit=120):
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:limit]


def deep_link(base_url, path):
    base = str(base_url or "").rstrip("/")
    parsed = urlsplit(base)
    local = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
    if (parsed.scheme != "https" and not local) or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("email links need an absolute https origin")
    return base + safe_app_path(path)


def safe_app_path(path):
    if not isinstance(path, str) or not _SAFE_PATH.fullmatch(path):
        return "/app"
    # Browsers normalize dot segments before navigating. Do not permit a payload to escape /app.
    if any(segment in (".", "..") for segment in path.split("?", 1)[0].split("/")):
        return "/app"
    return path


e = html.escape


# --- components -------------------------------------------------------------------------------------------------------
def Preheader(text):
    return (f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;font-size:1px;line-height:1px;color:{PAGE};">'
            f'{e(one_line(text, 140))}{"&#8199;&#847;" * 20}</div>')


def BrandHeader(brand="Rafii", base_url="https://rafii.invalid"):
    """Exact email-safe translation of marketing/wordmark.tsx: inverted R + visible text.
    The approved face is decorative. Neither meaning nor the CTA depends on images loading."""
    avatar = deep_link(base_url, "/app").removesuffix("/app") + "/raffi/avatar-128.png"
    return (f'<tr><td class="rf-pad" style="padding:32px 32px 16px 32px;">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td valign="middle" data-rafii-wordmark="approved"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td class="rf-mark" width="28" height="28" align="center" valign="middle" style="width:28px;height:28px;background:{INK};border-radius:8px;'
            f'font-family:{FONT};font-size:14px;line-height:28px;font-weight:700;color:#ffffff;">R</td>'
            f'<td class="rf-ink" style="padding-left:8px;font-family:{FONT};font-size:18px;line-height:28px;font-weight:600;letter-spacing:-0.3px;color:{INK};">Rafii</td>'
            '</tr></table></td>'
            f'<td width="48" align="right" valign="middle"><img data-rafii-character="approved" src="{e(avatar)}" width="48" height="48" alt="" '
            'style="display:block;width:48px;height:48px;border:0;outline:none;text-decoration:none;"></td>'
            '</tr></table></td></tr>')


def ContextLabel(text):
    return (f'<tr><td class="rf-pad" style="padding:16px 32px 0 32px;font-family:{FONT};font-size:12px;line-height:16px;letter-spacing:0.06em;'
            f'text-transform:uppercase;color:{INK_3};"><span class="rf-ink3">{e(one_line(text, 60))}</span></td></tr>')


def StatusPill(kind, label):
    bg, fg = PILL.get(kind, PILL["info"])
    return (f'<span class="rf-pill" style="display:inline-block;padding:4px 10px;border-radius:999px;background:{bg};color:{fg};'
            f'font-family:{FONT};font-size:12px;line-height:16px;font-weight:600;">{e(one_line(label, 30))}</span>')


def Headline(text, pill=""):
    return (f'<tr><td class="rf-pad" style="padding:8px 32px 0 32px;">{pill}'
            f'<h1 class="rf-ink" style="margin:12px 0 0 0;font-family:{SERIF};font-size:30px;line-height:37px;font-weight:500;letter-spacing:-0.4px;color:{INK};">{e(one_line(text, 120))}</h1></td></tr>')


def PrimaryCard(paragraphs, rows=()):
    body = "".join(f'<p class="rf-ink2" style="margin:0 0 14px 0;font-family:{FONT};font-size:16px;line-height:24px;color:{INK_2};">{e(p)}</p>' for p in paragraphs if p)
    details = "".join(f'<tr><td style="padding:6px 0;font-family:{FONT};font-size:14px;line-height:20px;color:{INK_3};width:40%;" class="rf-ink3">{e(one_line(k, 40))}</td>'
                      f'<td style="padding:6px 0;font-family:{FONT};font-size:14px;line-height:20px;color:{INK};" class="rf-ink">{e(one_line(v, 80))}</td></tr>' for k, v in rows)
    table = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid {LINE};margin-top:4px;">{details}</table>'
             if details else "")
    return f'<tr><td class="rf-pad" style="padding:24px 32px 4px 32px;">{body}{table}</td></tr>'


def MetricsRow(metrics):
    if not metrics:
        return ""
    cells = "".join(f'<td align="left" valign="top" style="padding:12px 8px 12px 0;width:{int(100 / len(metrics))}%;">'
                    f'<div class="rf-ink" style="font-family:{SERIF};font-size:24px;line-height:28px;font-weight:600;color:{INK};">{e(one_line(m.get("value"), 16))}</div>'
                    f'<div class="rf-ink3" style="font-family:{FONT};font-size:12px;line-height:16px;color:{INK_3};">{e(one_line(m.get("label"), 30))}</div></td>'
                    for m in metrics[:4])
    return f'<tr><td class="rf-pad" style="padding:4px 32px;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{cells}</tr></table></td></tr>'


def PrimaryCTA(label, url):
    return (f'<tr><td class="rf-pad" style="padding:12px 32px 8px 32px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td class="rf-cta" style="border-radius:999px;background:{INK};">'
            f'<a href="{e(url)}" class="rf-cta-a" style="display:inline-block;padding:14px 24px;min-width:120px;text-align:center;font-family:{FONT};font-size:16px;'
            f'line-height:20px;font-weight:600;color:#ffffff;text-decoration:none;border-radius:999px;">{e(one_line(label, 40))}</a></td></tr></table></td></tr>')


def SecondaryAction(label, url):
    return (f'<tr><td class="rf-pad rf-ink3" style="padding:4px 32px 20px 32px;font-family:{FONT};font-size:13px;line-height:20px;color:{INK_3};">'
            f'{e(label)} <a href="{e(url)}" class="rf-link" style="color:{INK_2};word-break:break-all;">{e(url)}</a></td></tr>')


def NotificationSettingsLink(label, url):
    return f'<a href="{e(url)}" class="rf-link" style="color:{INK_3};text-decoration:underline;">{e(label)}</a>'


def Footer(reason, settings, unsubscribe=None, privacy=None):
    links = " · ".join(x for x in (settings, unsubscribe, privacy) if x)
    return (f'<tr><td class="rf-pad rf-foot" style="padding:18px 32px 28px 32px;border-top:1px solid {LINE};font-family:{FONT};font-size:12px;line-height:18px;color:{INK_3};">'
            f'{e(reason)}<br>{links}</td></tr>')


def EmailShell(*, lang, title, preheader, rows):
    style = ("@media (max-width:620px){.rf-card{width:100%!important;border-radius:0!important}.rf-pad{padding-left:20px!important;padding-right:20px!important}"
             "h1{font-size:24px!important;line-height:30px!important}}"
             "@media (prefers-color-scheme:dark){body,.rf-page{background:#0f0f0f!important}.rf-card{background:#1b1b1b!important;border-color:#2a2a2a!important}"
             ".rf-foot{border-top-color:#333333!important}.rf-ink{color:#f5f5f5!important}.rf-ink2{color:#d6d6d6!important}.rf-ink3,.rf-foot{color:#b3b3b3!important}.rf-link{color:#e0e0e0!important}"
             ".rf-pill{background:#333333!important;color:#f5f5f5!important}.rf-mark{background:#f5f5f5!important;color:#111111!important}.rf-cta{background:#f5f5f5!important}.rf-cta-a{color:#111111!important}}")
    return ('<!doctype html>'
            f'<html lang="{e(lang)}" dir="ltr" xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="x-apple-disable-message-reformatting">'
            '<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">'
            f'<title>{e(title)}</title><style>{style}</style></head>'
            f'<body class="rf-page" style="margin:0;padding:0;background:{PAGE};-webkit-text-size-adjust:100%;">{Preheader(preheader)}'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="rf-page" style="background:{PAGE};"><tr><td align="center" style="padding:24px 12px;">'
            '<!--[if mso]><table role="presentation" width="600" align="center" cellpadding="0" cellspacing="0"><tr><td><![endif]-->'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="rf-card" style="width:100%;max-width:600px;background:{CARD};'
            f'border:1px solid {LINE};border-radius:20px;">{"".join(rows)}</table><!--[if mso]></td></tr></table><![endif]--></td></tr></table></body></html>')


# --- rendering ------------------------------------------------------------------------------------------------------------
def render(template, *, locale="en", values=None, base_url, href=None, workspace_name=None, unsubscribe_url=None, transactional=False,
           metrics=None, details=None, items=None):
    """→ {subject, preheader, html, text, headers, templateVersion, locale}. `values` fill the copy's placeholders;
    `items` (digest) are [{title, detail, href}]."""
    if template not in TEMPLATES:
        template = "digest"
    data = catalogue()
    loc = resolve_locale(locale)
    strings = data["locales"].get(loc) or data["locales"][data["fallback"]]
    copy = strings["templates"].get(template) or data["locales"]["en"]["templates"][template]
    common = strings["common"]
    values = {k: v for k, v in (values or {}).items() if v is not None}
    subject = one_line(_fmt(copy["subject"], values), 110)
    preheader = one_line(_fmt(copy["preheader"], values), 140)
    headline = _fmt(copy["headline"], values) or subject
    lead = _fmt(copy["lead"], values)
    status_kind = copy.get("status", "info")
    url = deep_link(base_url, href)
    settings_url = deep_link(base_url, "/app/account/notifications")
    privacy_url = deep_link(base_url, "/app").removesuffix("/app") + "/privacy"
    reason = _fmt(common["reason"], {"workspace": workspace_name}) if workspace_name else common["reasonPerson"]
    rows = [BrandHeader(common["brand"], base_url), ContextLabel(copy["context"]), Headline(headline, StatusPill(status_kind, common["status"][status_kind]))]
    paragraphs = [lead]  # every approval-related lead already says that nothing is published without the person
    rows.append(PrimaryCard(paragraphs, [(str(k), str(v)) for k, v in (details or [])]))
    if metrics:
        rows.append(MetricsRow(metrics))
    if items:
        rows.append(PrimaryCard([], [(one_line(i.get("title"), 60), one_line(i.get("detail"), 80)) for i in items[:12]]))
    rows.append(PrimaryCTA(copy["cta"], url))
    rows.append(SecondaryAction(common["linkFallback"], url))
    unsubscribe_link = None
    if unsubscribe_url and not transactional:
        unsubscribe_link = NotificationSettingsLink(common["unsubscribe"], unsubscribe_url)
    rows.append(Footer(reason, NotificationSettingsLink(common["settings"], settings_url), unsubscribe_link,
                       NotificationSettingsLink(common["privacy"], privacy_url)))
    html_doc = EmailShell(lang=loc, title=subject, preheader=preheader, rows=rows)
    text_parts = [headline, "", *[p for p in paragraphs if p]]
    for k, v in details or []:
        text_parts.append(f"{one_line(k, 40)}: {one_line(v, 80)}")
    for m in metrics or []:
        text_parts.append(f"{one_line(m.get('label'), 30)}: {one_line(m.get('value'), 16)}")
    for i in items or []:
        text_parts.append(f"- {one_line(i.get('title'), 60)}: {one_line(i.get('detail'), 80)}")
    text_parts += ["", f"{copy['cta']}: {url}", "", reason, f"{common['settings']}: {settings_url}"]
    if unsubscribe_url and not transactional:
        text_parts.append(f"{common['unsubscribe']}: {unsubscribe_url}")
    headers = {}
    if unsubscribe_url and not transactional:
        headers = {"List-Unsubscribe": f"<{unsubscribe_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return {"subject": subject, "preheader": preheader, "html": html_doc, "text": "\n".join(text_parts).strip() + "\n", "headers": headers,
            "templateVersion": TEMPLATE_VERSION, "locale": loc, "template": template, "url": url}
