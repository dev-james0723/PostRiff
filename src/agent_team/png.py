"""Small deterministic image renderer. Pillow is supplied by host/runtime, never installed locally."""
from pathlib import Path
from .periods import aware, TZ


def render(data, target, font_path):
    from PIL import Image, ImageDraw, ImageFont
    font_path=Path(font_path)
    if not font_path.is_file():raise ValueError('CJK_font_unavailable')
    im=Image.new('RGB',(1080,1420),'#10212b');draw=ImageDraw.Draw(im)
    def text(x,y,value,size=22,color='#e9f1f3'):
        draw.text((x,y),str(value),fill=color,font=ImageFont.truetype(str(font_path),size))
    text(56,54,'JAMES AGENT TEAM',22,'#79ccc1')
    text(56,112,data['period']['workday']+' '+('全日報告' if data['period']['kind']=='whole_day' else '半日報告'),46)
    text(56,181,'資料截至 '+aware(data['asOf']).astimezone(TZ).strftime('%m/%d %H:%M %Z'),21)
    text(56,220,'本機真實來源預覽 · 未送達' if data['executionState']=='preview' else '已生成 · 送達另行核對',20,'#edbc80')
    for i,(k,label) in enumerate([('completed','已驗證完成'),('autonomouslyResolved','自主解決'),('running','仍在進行'),('needsHuman','需要你')]):
        x=56+i*244;draw.rounded_rectangle((x,274,x+228,439),18,fill='#1b3441');text(x+20,297,label,20)
        text(x+20,344,data['counts'][k] if data['counts'][k] is not None else '?',51)
    text(56,478,'來源覆蓋',28)
    for i,c in enumerate(data['coverage']):
        y=529+i*45;draw.ellipse((60,y+6,72,y+18),fill='#79ccc1' if c['complete'] else '#edbc80')
        text(91,y,f"{c['source']} · {c['status']} · {c['count']} 筆",22)
    text(56,887,'觀察記錄時間分布',28);text(56,926,'記錄數量不代表工時或完成數',19,'#a4bcc4')
    bins=list(data['histogram'].items())[:24];maximum=max((n for _,n in bins),default=1)
    for i,(hour,n) in enumerate(bins):
        w=900/max(len(bins),1);x=60+i*w;h=100*n/maximum
        draw.rectangle((x,1064-h,x+max(w-6,2),1064),fill='#79ccc1');text(x,1075,hour[:2],16)
    text(56,1140,'證據與待核對事項',28)
    text(56,1189,f"{len(data['evidence'])} 筆來源 reference · 真實截圖 {len(data['screenshots'])} 張",21)
    text(56,1227,'背景瀏覽器及真實任務驗收尚未接通',20,'#edbc80')
    text(56,1265,'完成數只採逐條驗收證據；未知狀態保留 ?',20)
    text(56,1330,'報告 '+data['fingerprint'][:16]+' · Indianapolis · 01:00 工作日分界',17,'#a4bcc4')
    p=Path(target);p.parent.mkdir(parents=True,exist_ok=True);im.save(p,format='PNG',optimize=False)
    return str(p)
