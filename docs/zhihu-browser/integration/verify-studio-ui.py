from playwright.sync_api import sync_playwright
import json
from pathlib import Path
with sync_playwright() as p:
 b=p.chromium.launch(headless=True);page=b.new_page(viewport={'width':1440,'height':1100})
 page.goto('http://127.0.0.1:4310',wait_until='networkidle')
 page.get_by_role('button',name='Channels',exact=True).click()
 page.locator('.channel-card').filter(has=page.get_by_role('heading',name='Zhihu · 知乎',exact=True)).click()
 panel=page.get_by_role('region',name='Zhihu browser connection',exact=True)
 panel.get_by_label('Public profile URL or handle').fill('https://www.zhihu.com/people/tie4gka')
 panel.get_by_role('button',name='Preview test post',exact=True).click()
 panel.get_by_label('Zhihu exact publication preview').wait_for()
 assert panel.get_by_role('button',name='Publish approved test',exact=True).is_disabled()
 assert panel.get_by_text('Public 想法 · Publish now · No media or derivatives',exact=False).is_visible()
 panel.screenshot(path=str(Path('artifacts/zhihu-browser-integration/studio-zhihu-preview.png').resolve()))
 status=page.request.get('http://127.0.0.1:4310/api/connections/zhihu/status').json()
 print(json.dumps({'ui':'passed','preview':'local_only','submitDisabled':True,'status':status}))
 b.close()
