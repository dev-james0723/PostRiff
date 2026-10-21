"""Unicode data regression supplement; independent of live X acceptance."""
from collections import Counter
from pathlib import Path
import json,re,unittest,sys
from postriff_phase2._vendor.twitter_text import parse_tweet,extract_emojis_with_indices
from postriff_phase2.x_text import normalize_text,text_eligibility
ROOT=Path(__file__).resolve().parents[1]
def unicode_report():
    table=ROOT/'src/postriff_phase2/_vendor/twitter_text/regexp/emoji-test.txt'
    lines=table.read_text().splitlines();assert '# Version: 18.0' in lines
    expected={'fully-qualified':3963,'minimally-qualified':1029,'unqualified':243,'component':9}
    counts=Counter();seen=set();failures=[];passed=0
    for n,line in enumerate(lines,1):
        raw=line.partition('#')[0].strip()
        if not raw:continue
        points,status=(p.strip() for p in raw.split(';',1))
        assert status in expected and re.fullmatch(r'[0-9A-F]+(?: +[0-9A-F]+)*',points)
        seq=''.join(chr(int(p,16)) for p in points.split());assert seq not in seen
        seen.add(seq);counts[status]+=1
        result=parse_tweet(seq)
        matched=(status=='component' or extract_emojis_with_indices('a'+seq+'z')==[{'emoji':seq,'indices':[1,1+len(seq)]}])
        if result.valid and result.weightedLength==2 and matched:passed+=1
        else:failures.append({'line':n,'points':points,'weight':result.weightedLength,'matched':matched})
    assert dict(counts)==expected,counts
    return {'synthetic':True,'providerCalls':0,'unicodeVersion':'18.0','cases':sum(counts.values()),'passed':passed,'statusCounts':dict(counts),'failures':failures}
class XText(unittest.TestCase):
    def test_all_unicode_18_sequences(self):
        report=unicode_report();self.assertEqual(report['failures'],[],json.dumps(report))
    def test_new_sequences_and_chinese_boundaries(self):
        for seq in ('中','🙂\u200d↔️','\U0001FAF9\U0001F3FD','👨‍👩‍👧‍👦'):
            self.assertEqual(parse_tweet(seq*140).weightedLength,280)
            self.assertEqual(text_eligibility(seq*140),'ordinary')
            self.assertEqual(text_eligibility(seq*141),'long')
    def test_urls_use_twenty_three_and_preserve_newlines(self):
        self.assertEqual(parse_tweet('https://example.com/'+('x'*400)).weightedLength,23)
        self.assertEqual(text_eligibility('https://example.com/'+('x'*400)),'ordinary')
        self.assertEqual(normalize_text('Cafe\u0301\r\nA\rB '),'Café\nA\nB ')
    def test_complete_invalid_character_scan(self):
        for bad in ('\ufffe','\uffff','\ufeff','\x00','\ud800'):
            for text in ('A'+bad+'B','https://example.com/a'+bad+'b?x=1','🙂'+bad+'\u200d↔️'):
                with self.subTest(code=hex(ord(bad))),self.assertRaises((ValueError,UnicodeError)):normalize_text(text)
                self.assertEqual(text_eligibility(text),'invalid')
        self.assertEqual(text_eligibility('\u200e中文字\u200f'),'ordinary')
    def test_vendor_needs_no_external_parser_or_pkg_resources(self):
        self.assertNotIn('twitter_text',sys.modules)
        self.assertNotIn('pkg_resources',sys.modules)
if __name__=='__main__':
    print(json.dumps(unicode_report(),ensure_ascii=True,indent=2))
