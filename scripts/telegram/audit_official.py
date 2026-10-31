"""Refresh public official documentation. No Telegram credentials or side effects."""
import hashlib
import json
import re
import sys
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from postriff_phase2.telegram.capabilities import CATALOG
SECTIONS = '''sendMessage sendPhoto sendVideo sendAnimation sendAudio sendVoice sendVideoNote sendDocument sendLivePhoto sendMediaGroup sendPoll sendPaidMedia copyMessage forwardMessage editMessageText editMessageCaption editMessageMedia editMessageReplyMarkup deleteMessage deleteMessages pinChatMessage unpinChatMessage setMessageReaction createForumTopic editForumTopic closeForumTopic reopenForumTopic getBusinessConnection readBusinessMessage deleteBusinessMessages approveSuggestedPost declineSuggestedPost getChat getChatMember ChatAdministratorRights ChatMemberAdministrator BusinessConnection BusinessBotRights MessageEntity LinkPreviewOptions InputMediaLivePhoto LivePhoto InputPollOption InputPollMedia InputPollOptionMedia InlineKeyboardButton Update Message MessageReactionUpdated MessageReactionCountUpdated postStory editStory deleteStory sendRichMessage InputRichMessage EphemeralMessageParameters'''.split()
URLS=['https://core.telegram.org/bots/api','https://core.telegram.org/api/scheduled-messages','https://core.telegram.org/api/stats','https://core.telegram.org/api/stories','https://core.telegram.org/method/stories.canSendStory','https://core.telegram.org/method/stats.getStoryStats','https://telegra.ph/api']
SECTIONS += '''ChatFullInfo ChatPermissions ReplyParameters DirectMessagesTopic SuggestedPostParameters SuggestedPostInfo SuggestedPostPrice SuggestedPostApproved SuggestedPostApprovalFailed SuggestedPostPaid SuggestedPostRefunded InputMediaPhoto InputMediaVideo InputMediaAudio InputMediaDocument Poll PollOption PollAnswer InputPaidMedia InputPaidMediaPhoto InputPaidMediaVideo PaidMediaInfo PaidMediaPhoto PaidMediaVideo'''.split()
URLS += ['https://core.telegram.org/method/'+name for name in ('messages.sendMessage','messages.editMessage','messages.getScheduledHistory','messages.sendScheduledMessages','messages.deleteScheduledMessages','stats.getBroadcastStats','stats.getMegagroupStats','stats.getMessageStats','stats.getMessagePublicForwards','stats.loadAsyncGraph','channels.getFullChannel','channels.getParticipant','messages.getHistory','messages.getDiscussionMessage','messages.getReplies','messages.getMessagesReactions','stories.sendStory','stories.getAlbums','stories.getStoriesArchive')]
class Tables(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.title='';self.heading=None;self.cell=None;self.row=None;self.sections={};self.all_headings=[]
 def handle_starttag(self,tag,attrs):
  if tag in ('h3','h4'):self.heading=''
  elif tag=='tr':self.row=[]
  elif tag in ('td','th') and self.row is not None:self.cell=''
 def handle_data(self,data):
  if self.heading is not None:self.heading+=data
  if self.cell is not None:self.cell+=data
 def handle_endtag(self,tag):
  if tag in ('h3','h4') and self.heading is not None:
   self.title=self.heading.strip();self.all_headings.append(self.title);self.heading=None
   if self.title in SECTIONS:self.sections.setdefault(self.title,[])
  elif tag in ('td','th') and self.cell is not None:
   self.row.append(' '.join(self.cell.split()));self.cell=None
  elif tag=='tr' and self.row is not None:
   if self.title in SECTIONS:self.sections.setdefault(self.title,[]).append(self.row)
   self.row=None
result={'auditedAt':datetime.now(timezone.utc).isoformat(),'sources':[]}
for url in URLS:
 with urlopen(url,timeout=30) as r:raw=r.read(3_000_000)
 parser=Tables();parser.feed(raw.decode())
 entry={'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'headings':parser.all_headings}
 if url.endswith('/bots/api'):
  entry.update(sections=parser.sections,requiredSections=SECTIONS,missingSections=sorted(set(SECTIONS)-set(parser.sections)),relevantAdditionalMethods=[h for h in parser.all_headings if re.match(r'(send|edit|delete|approve|decline|get.*(Stories|Reaction|ManagedBot|PersonalChat)|postStory|copy|forward)',h)])
  if entry['missingSections']:raise RuntimeError('Official Bot API sections missing: '+str(entry['missingSections']))
 result['sources'].append(entry)
out=ROOT/'docs/telegram/evidence/official-api-audit.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'sources':len(result['sources']),'botSections':len(result['sources'][0]['sections']),'missing':result['sources'][0]['missingSections'],'output':str(out)}))
