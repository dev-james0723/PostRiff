"""Read only visible account landmarks using the isolated saved session."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'source'))
from tiktok_uploader.Browser import Browser
from tiktok_uploader.cookies import load_cookies_from_file

driver = None
try:
    driver = Browser.get().driver
    driver.set_page_load_timeout(35)
    driver.get('https://www.tiktok.com/robots.txt')
    for cookie in load_cookies_from_file('tiktok_session-jamesaucreates'):
        driver.add_cookie(cookie)
    driver.get('https://www.tiktok.com/foryou?lang=en')
    time.sleep(8)
    if '/login' in driver.current_url:
        print(json.dumps({'state': 'private_login_required'}))
    else:
        links = driver.execute_script("""return Array.from(document.querySelectorAll('a[href]')).filter(a => /profile/i.test((a.innerText||'')+' '+(a.getAttribute('data-e2e')||'')+' '+(a.getAttribute('aria-label')||''))).map(a=>({text:a.innerText.slice(0,80),path:new URL(a.href).pathname,landmark:a.getAttribute('data-e2e')})).slice(0,15)""")
        print(json.dumps({'state':'account_landmarks','links':links}))
        mine = any(link['path'].rstrip('/').lower() == '/@jamesaucreates' for link in links)
        if mine:
            driver.get('https://www.tiktok.com/@jamesaucreates')
            time.sleep(6)
            edit = driver.execute_script("""return Array.from(document.querySelectorAll('button,a')).some(e=>/^(Edit profile|編輯個人資料|编辑资料)$/i.test(e.innerText.trim()))""")
            print(json.dumps({'state':'identity_verified' if edit else 'identity_unresolved','account':'@jamesaucreates','self_navigation_matches':mine,'owner_edit_profile_control':edit}))
except Exception as error:
    print(json.dumps({'state':'verification_failed','error_type':type(error).__name__}))
finally:
    if driver:
        driver.quit()
