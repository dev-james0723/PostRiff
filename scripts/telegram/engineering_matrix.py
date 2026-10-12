"""Generate a code inventory. No generated row is evidence of real acceptance."""
import csv
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from postriff_phase2.telegram.capabilities import CATALOG,SEND_RIGHTS,SEND_TYPES
rights={
 'identity':'Bot membership; channel post proof or group administrator proof; private chat initiated by user',
 'pin':'Channel can_edit_messages; group/supergroup can_pin_messages',
 'topics':'Permission to send in the observed/explicitly connected forum topic',
 'topic_management':'can_manage_topics',
 'comments_read':'Bot access to selected group/discussion chat; privacy mode limits observed messages',
 'engagement':'Bot administrator for reaction updates; poll/message observations where provided',
 'reactions':'Bot administrator for reaction updates',
 'reaction_set':'Accessible message and send permission; ordinary emoji only',
 'channel_dm':'Parent channel can_manage_direct_messages; separate Rafii DM consent and selected observed topic',
 'suggested_posts':'Parent channel can_post_messages for approve; can_manage_direct_messages for decline',
 'approve_suggested_post':'Parent channel can_post_messages; unpaid suggestion',
 'decline_suggested_post':'Parent channel can_manage_direct_messages; unpaid suggestion',
 'edit_own':'Own recorded messages; channel can_post_messages; Business can_reply; type/time restrictions',
 'delete_own':'Own recorded messages within ordinary deletion window; Business can_delete_sent_messages',
 'business_messaging':'BusinessBotRights.can_reply, active owner-verified consented connection, incoming private message within 24h',
 'business_read':'BusinessBotRights.can_read_messages',
 'business_stories':'BusinessBotRights.can_manage_stories',
 'business_checklist':'Active business connection with appropriate Business messaging rights',
 'detailed_analytics':'Advanced owner consent; Telegram administrator can_view_stats eligibility/statistics DC',
 'native_schedule':'Advanced owner consent; selected resolved channel; user can_post_messages; Premium for repeats',
 'story_publish':'Advanced owner consent; stories.canSendStory, channel rights, boosts/Premium/limits/privacy checks',
 'story_analytics':'Advanced owner consent; eligible story administrator access',
 'story_statistics_basic':'Advanced owner consent; eligible can_view_stats; native getStoryStats only',
 'telegraph':'Separate encrypted Telegraph access token and explicit public article approval',
}
backend_only={'reaction_set','text_formatting','photo_album','video_album','mixed_album','audio_album','document_album','live_photo_album','native_schedule','detailed_analytics','story_statistics_basic','forward','copy'}
rows=[]
for name,spec in CATALOG.items():
 permission=rights.get(name)
 if not permission:
  permission='Channel can_post_messages; groups membership/admin and selected-format send rights; Business can_reply within 24h' if name in SEND_TYPES else 'Disabled; no administrator privilege requested'
 if name in SEND_RIGHTS:permission+='; non-admin groups '+SEND_RIGHTS[name]
 rows.append({'Rafii capability':name,'Telegram API':spec.api,'Required connection':spec.layer,'Required admin/right':permission,'Implemented':'candidate' if spec.implemented else 'disabled/unimplemented','UI':'partial/API controls' if name in backend_only and spec.implemented else 'contextual' if spec.implemented else 'disabled','E2E tested':'NO — NOT RUN','Enabled in production':'NO — no real qualification installed','Limitations':spec.limitation or 'Destination-specific real acceptance still required'})
out=ROOT/'docs/telegram';out.mkdir(parents=True,exist_ok=True)
with (out/'engineering-matrix.csv').open('w',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=rows[0],lineterminator='\n');writer.writeheader();writer.writerows(rows)
markdown='# Telegram engineering matrix\n\nGenerated from the candidate capability catalog. Implementation is a code inventory; it is not a claim of live Telegram support. No real destination is connected or qualified in this task.\n\n'
headers=list(rows[0]);markdown+='| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'
for row in rows:markdown+='| '+' | '.join(str(row[k]).replace('|','/').replace('\n',' ') for k in headers)+' |\n'
(out/'engineering-matrix.md').write_text(markdown)
print(json.dumps({'capabilities':len(rows),'candidateImplemented':sum(s.implemented for s in CATALOG.values()),'realE2EPassed':0,'productionQualified':0}))
