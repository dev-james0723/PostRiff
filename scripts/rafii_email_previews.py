"""Render every Rafii notification email in every shipped locale to static preview files (no sending).

    PYTHONPATH=src python scripts/rafii_email_previews.py [--out docs/design/site-agent/adaptive-social-coworker/evidence/email]

Writes <template>.<locale>.html, <template>.<locale>.txt and index.json (subject, preheader, size, CTA count,
List-Unsubscribe presence, template version). The values are synthetic; nothing reaches a provider.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_phase2.notifications import catalog, email_render  # noqa: E402
from postriff_phase2.email import DIRECT_TEMPLATES, Mailer, NullTransport

LOCALES = tuple(email_render.catalogue()["locales"])
BASE = "https://app.rafii.example"
VALUES = {"platform": "LinkedIn", "count": 5, "weekOf": "2026-09-28", "recipe": "Weekly plan", "recipeName": "Weekly plan", "title": "A new device signed in",
          "reason": "LinkedIn rejected the post: the text is longer than allowed.", "endsAt": "1 October 2026", "planName": "Pro", "why": "It matches your goal “Fill autumn preorders”."}
METRICS = [{"label": "Verified posts", "value": "12"}, {"label": "Median views", "value": "1,240"}, {"label": "Hypotheses", "value": "2"}]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs/design/site-agent/adaptive-social-coworker/evidence/email")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    templates = {spec["template"]: event for event, spec in catalog.EVENTS.items()}
    index = []
    for template in email_render.TEMPLATES:
        event = templates.get(template)
        transactional = bool(event and catalog.transactional(event))
        for locale in LOCALES:
            rendered = email_render.render(template, locale=locale, values=VALUES, base_url=BASE, href="/app/queue", workspace_name="Harbour Bakery",
                                           unsubscribe_url=f"{BASE}/api/notifications/unsubscribe?token=preview", transactional=transactional,
                                           metrics=METRICS if template == "weekly_performance" else None,
                                           items=[{"title": "Published and confirmed", "detail": "LinkedIn"}, {"title": "Your drafts are ready", "detail": "Weekly plan"}] if template == "digest" else None)
            stem = f"{template}.{locale}"
            (out / f"{stem}.html").write_text(rendered["html"])
            (out / f"{stem}.txt").write_text(rendered["text"])
            index.append({"template": template, "event": event, "locale": locale, "subject": rendered["subject"], "preheader": rendered["preheader"],
                          "htmlBytes": len(rendered["html"].encode()), "ctaCount": rendered["html"].count('class="rf-cta-a"'), "transactional": transactional,
                          "listUnsubscribe": bool(rendered["headers"]), "templateVersion": rendered["templateVersion"], "file": f"{stem}.html","primaryURL":rendered['url']})
    mailer = Mailer(NullTransport(),'Rafii <local@rafii.example>',BASE)
    for kind, link in DIRECT_TEMPLATES.items():
        href=BASE + ('/invite/synthetic-preview' if kind=='invitation' else '/pricing' if link=='pricing_url' else '/app/account/notifications' if kind=='new_device' else '/app')
        subject,text,html_doc=mailer.render(kind,**{link:href},inviter_label='A teammate',role='editor',days_left=3,expires_at=1800000000,
                                           grace_until=1800000000,plan_label='Studio',automation_name='Weekly plan',count=3,device_label='A new device')
        stem=f'direct_{kind}.en'
        (out/f'{stem}.html').write_text(html_doc)
        (out/f'{stem}.txt').write_text(text)
        index.append({'template':f'direct_{kind}','event':None,'locale':'en','subject':subject,'preheader':subject,'htmlBytes':len(html_doc.encode()),
                      'ctaCount':html_doc.count('class="rf-cta-a"'),'transactional':True,'listUnsubscribe':False,'templateVersion':email_render.TEMPLATE_VERSION,
                      'file':f'{stem}.html','primaryURL':href})
    (out / "index.json").write_text(json.dumps({"templateVersion": email_render.TEMPLATE_VERSION, "catalogVersion": catalog.CATALOG_VERSION, "previews": index},
                                               ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"previews": len(index), "notificationTemplates": len(email_render.TEMPLATES),"directEnglishTemplates":len(DIRECT_TEMPLATES), "locales": len(LOCALES), "out": str(out)}))


if __name__ == "__main__":
    main()
