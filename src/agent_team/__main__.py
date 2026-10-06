"""Control-plane commands. Every external delivery requires its explicit command."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from .collector import collect_once, coverage_from_journal
from .events import Journal, canonical
from .periods import period
from .reports import report,svg,html


def main():
    p=argparse.ArgumentParser(prog='james-agent-team');p.add_argument('--journal',required=True)
    commands=p.add_subparsers(dest='command',required=True)
    c=commands.add_parser('collect');c.add_argument('--luci',action='store_true');c.add_argument('--window-seconds',type=int,default=1800)
    r=commands.add_parser('preview');r.add_argument('--workday',required=True);r.add_argument('--kind',choices=('half_day','whole_day'),required=True);r.add_argument('--output',required=True);r.add_argument('--font')
    args=p.parse_args();journal=Journal(args.journal)
    try:
        if args.command=='collect':result=collect_once(journal,luci=args.luci,window_seconds=args.window_seconds)
        else:
            out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
            events=journal.all();data=report(period(args.workday,args.kind),events,datetime.now(timezone.utc),coverage_from_journal(events),preview=True)
            (out/'report.json').write_text(canonical(data)+'\n')
            (out/'report.svg').write_text(svg(data));(out/'report.html').write_text(html(data))
            if args.font:
                from .png import render
                render(data,out/'report.png',font_path=args.font)
            result={'executionState':'real_source_preview','fingerprint':data['fingerprint'],'counts':data['counts'],'sourceReferences':len(data['evidence']),'scheduledDelivery':'not_executed'}
        print(json.dumps(result,ensure_ascii=False))
    finally:journal.close()


if __name__=='__main__':main()
