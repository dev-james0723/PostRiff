"""Deterministic reports from immutable observations and explicit acceptance evidence."""
from collections import Counter
from datetime import datetime, timezone
from html import escape
import hashlib
from .events import canonical, safe_text, safe_url
from .periods import aware, TZ

EXPECTED_SOURCES=("luci","typeless","codex","claude","browser","mission","token_pilot","git")


def report(period, events, generated_at=None, sources=None, preview=False):
    generated=aware(generated_at or datetime.now(timezone.utc))
    as_of=min(period.cutoff,generated)
    latest={}
    for e in events:
        # Late arrival can supplement the cutoff only when its source version
        # was already effective then. An edit after cutoff cannot rewrite history.
        if aware(e["observed_at"])>generated: continue
        effective=aware(e['payload'].get('sourceFreshAt') or e['happened_at'])
        if effective>as_of: continue
        identity=(e["source"],e["source_id"])
        old=latest.get(identity)
        if not old or (effective,e["revision"])>(aware(old['payload'].get('sourceFreshAt') or old['happened_at']),old["revision"]):latest[identity]=e
    selected=sorted((e for e in latest.values() if period.start<=aware(e["happened_at"])<as_of),key=lambda e:(e["happened_at"],e["key"]))
    evidence={e["key"]:e for e in selected}
    completed=set();resolved=set();missions={};projects={};claims=0;verified_claims=0
    for e in selected:
        p=e["payload"];mid=e.get("mission_id")
        if e["source"]=="mission" and mid: missions[mid]=p.get("state","unknown")
        if e.get("project_id"): projects.setdefault(e["project_id"], {"id":e["project_id"],"accepted":None,"total":None,"phase":"unknown"})
        if e["source"]!="acceptance" or not mid: continue
        claims+=1
        requirements=p.get("requirements",[])
        valid=isinstance(requirements,list) and bool(requirements) and bool(p.get("scopeVersion")) and all(
            isinstance(r,dict) and r.get("status")=="passed" and r.get("scopeVersion")==p["scopeVersion"]
            and r.get("evidenceRefs") and all(ref in evidence for ref in r["evidenceRefs"])
            for r in requirements)
        if not valid: continue
        verified_claims+=1
        if p.get("kind")=="completed":completed.add(mid)
        if p.get("kind")=="incident_resolved" and p.get("withoutHuman") is True:resolved.add(e["source_id"])
        if p.get("kind")=="milestone" and e.get("project_id") and type(p.get("accepted")) is int and type(p.get("total")) is int and 0<=p["accepted"]<=p["total"] and p["total"]>0:
            projects[e["project_id"]].update({"accepted":p["accepted"],"total":p["total"],"phase":p.get("phase","unknown")})
    source_counts=Counter(e["source"] for e in selected)
    coverage=[]
    for source in EXPECTED_SOURCES:
        meta=(sources or {}).get(source,{})
        coverage.append({"source":source,"status":meta.get("status","unknown"),
            "count":source_counts.get(source,0),"freshAt":meta.get("freshAt"),
            "gaps":meta.get("gaps",["source_not_verified"]),"complete":meta.get("complete",False) is True})
    gaps=[f"{c['source']}:{gap}" for c in coverage for gap in c["gaps"]]
    # Healthy source metadata does not establish continuous capture coverage.
    # Keep these report-wide limits even when source health replaces its gaps.
    gaps.extend(("bounded_metadata_only","full_day_screen_audio_unverified"))
    if generated<period.cutoff:gaps.append("preview_before_cutoff")
    if preview:gaps.append("preview_not_scheduled_delivery")
    mission_complete=next(c for c in coverage if c["source"]=="mission")["complete"]
    counts={"completed":len(completed),"autonomouslyResolved":len(resolved),
        "running":sum(v in {"running","verifying","waiting_tool","waiting_external"} for v in missions.values()) if mission_complete else None,
        "needsHuman":sum(v=="waiting_human" for v in missions.values()) if mission_complete else None}
    summary=f"本報告涵蓋 {period.start.astimezone(TZ):%m/%d %H:%M} 至 {as_of.astimezone(TZ):%m/%d %H:%M}。已有完成證據的任務 {counts['completed']} 項，自主解決事件 {counts['autonomouslyResolved']} 項。"
    summary+="觀察資料只證明來源曾記錄活動，不能據此判斷任務已完成或實際工時。仍在進行及需要你處理的總數，只有完整任務來源核對後才顯示。"
    summary+="圖像、摘要及電話內容沿用同一份資料。未取得的背景頁、session 擁有者與驗收資料已列為缺口，沒有用舊狀態補作最新成果。詳細證據可按來源記錄回查。"
    summary+="目前觀察只有有限時間窗口的 metadata 記錄，未取得全日連續電腦畫面與系統音訊的擷取、儲存及回放證據。"
    after17=sum(aware(e["happened_at"]).astimezone(TZ).date().isoformat()==period.workday and aware(e["happened_at"]).astimezone(TZ).hour>=17 for e in selected)
    manifest=[{"id":e["key"],"source":e["source"],"sourceId":e["source_id"],"revision":e["revision"],
        "capturedAt":e["happened_at"],"observedAt":e["observed_at"],"projectId":e.get("project_id"),"missionId":e.get("mission_id"),
        "url":safe_url(e["payload"]["url"]) if e["payload"].get("url") else None,
        "sha":e["payload"].get("sha"),"deploymentId":e["payload"].get("deploymentId"),
        "captureMode":"metadata" if e["source"] not in ("browser","acceptance") else e["payload"].get("kind","unknown")} for e in selected]
    result={"schemaVersion":1,"executionState":"preview" if preview else "generated",
        "period":period.as_dict(),"asOf":as_of.isoformat(),"generatedAt":generated.isoformat(),
        "counts":counts,"coverage":coverage,"gaps":gaps,"projects":list(projects.values()),
        "summary":summary,"after17ObservationCount":after17,"lateObservationCount":sum(aware(e['observed_at'])>period.cutoff for e in selected),"evidence":manifest,
        "evidenceCoverage":{"verified":verified_claims,"required":claims,"ratio":verified_claims/claims if claims else None},
        "screenshots":[],"actions":[],"histogram":dict(sorted(Counter(aware(e["happened_at"]).astimezone(TZ).strftime('%H:00') for e in selected).items()))}
    result["fingerprint"]=hashlib.sha256(canonical(result).encode()).hexdigest()
    return result


def svg(data):
    """One structured input produces all labels and chart values; never synthesize evidence images."""
    esc=lambda v:escape(safe_text(v,300))
    count=data["counts"];p=data["period"]
    title="全日報告" if p["kind"]=="whole_day" else "半日報告"
    status="本機真實來源預覽 · 未送達" if data["executionState"]=="preview" else "已生成 · 送達另行核對"
    out=['<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1420" viewBox="0 0 1080 1420">',
      '<rect width="1080" height="1420" fill="#10212b"/>',
      '<g font-family="PingFang TC, Noto Sans CJK TC, sans-serif" fill="#e9f1f3">',
      '<text x="56" y="76" font-size="22" fill="#79ccc1">JAMES AGENT TEAM</text>',
      f'<text x="56" y="146" font-size="49" font-weight="700">{esc(p["workday"])} {title}</text>',
      f'<text x="56" y="190" font-size="21">資料截至 {esc(aware(data["asOf"]).astimezone(TZ).strftime("%m/%d %H:%M %Z"))}</text>',
      f'<text x="56" y="228" font-size="20" fill="#edbc80">{status}</text>']
    for i,(key,label) in enumerate([("completed","已驗證完成"),("autonomouslyResolved","自主解決"),("running","仍在進行"),("needsHuman","需要你")]):
        x=56+i*244
        out+=[f'<rect x="{x}" y="274" width="228" height="165" rx="18" fill="#1b3441"/>',
            f'<text x="{x+20}" y="313" font-size="20">{label}</text>',
            f'<text x="{x+20}" y="389" font-size="51" font-weight="600">{count[key] if count[key] is not None else "?"}</text>']
    out.append('<text x="56" y="502" font-size="28" font-weight="600">來源覆蓋</text>')
    for i,c in enumerate(data["coverage"]):
        y=553+i*45;good=c["complete"]
        out+=[f'<circle cx="66" cy="{y-7}" r="6" fill="{"#79ccc1" if good else "#edbc80"}"/>',
            f'<text x="91" y="{y}" font-size="22">{esc(c["source"])} · {esc(c["status"])} · {c["count"]} 筆</text>']
    out+=[f'<text x="56" y="911" font-size="28" font-weight="600">觀察記錄時間分布</text>',
          '<text x="56" y="947" font-size="19" fill="#a4bcc4">記錄數量不代表工時或完成數</text>']
    bins=list(data["histogram"].items())[:24];maximum=max((n for _,n in bins),default=1)
    for i,(hour,n) in enumerate(bins):
        w=900/max(len(bins),1);x=60+i*w;h=100*n/maximum
        out+=[f'<rect x="{x:.1f}" y="{1064-h:.1f}" width="{max(w-6,2):.1f}" height="{h:.1f}" fill="#79ccc1"/>',
              f'<text x="{x:.1f}" y="1094" font-size="16">{esc(hour[:2])}</text>']
    out+=['<text x="56" y="1164" font-size="28" font-weight="600">證據與待核對事項</text>',
       f'<text x="56" y="1210" font-size="21">{len(data["evidence"])} 筆來源 reference · 真實截圖 {len(data["screenshots"])} 張</text>',
       '<text x="56" y="1248" font-size="20" fill="#edbc80">背景瀏覽器及真實任務驗收尚未接通</text>',
       '<text x="56" y="1286" font-size="20">完成數只採逐條驗收證據；未知狀態保留 ?</text>',
       f'<text x="56" y="1351" font-size="17" fill="#a4bcc4">報告 {esc(data["fingerprint"][:16])} · Indianapolis · 01:00 工作日分界</text>',
       '</g></svg>']
    return "\n".join(out)


def html(data):
    """Private review page with same SVG and safe evidence links. Requires server authentication."""
    rows=[]
    for e in data["evidence"][-40:]:
        url=e.get("url")
        label=escape(f"{e['source']} · {e['capturedAt']} · {e['id'][:12]}")
        if url:label=f'<a href="{escape(url,quote=True)}" rel="noreferrer">{label}</a>'
        rows.append(f'<li>{label}</li>')
    return '<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>James Agent Team</title><style>body{margin:0;background:#10212b;color:#e9f1f3;font:16px system-ui}main{max-width:1080px;margin:auto;padding:16px}svg{width:100%;height:auto}a{color:#79ccc1}li{overflow-wrap:anywhere;margin:12px 0}</style><main>'+svg(data)+'<p>'+escape(data['summary'])+'</p><ul>'+''.join(rows)+'</ul><p>Coverage: '+escape(', '.join(data['gaps']))+'</p></main></html>'
