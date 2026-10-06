import tempfile
import unittest
from pathlib import Path
from agent_team.events import Event, Journal, projection, safe_url


class JournalTests(unittest.TestCase):
    def test_incremental_outbox_transaction_and_immutable_version(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'journal.db')
            e=Event('typeless','record1','v1','2026-10-05T14:00:00Z','2026-10-05T14:01:00Z',{'status':'pending'})
            self.assertEqual(j.ingest([e],'typeless',{'last':'record1'}),1)
            self.assertEqual(j.ingest([e]),0)
            conflicting=Event('typeless','record1','v1',e.happened_at,e.observed_at,{'status':'completed'})
            with self.assertRaises(ValueError):j.ingest([conflicting],'typeless',{'last':'lost'})
            self.assertEqual(j.cursor('typeless'),{'last':'record1'})
            self.assertEqual(len(j.pending()),1)
            j.acknowledge([e.key],'2026-10-05T14:02:00Z');self.assertEqual(j.pending(),[])
            j.close()

    def test_cloud_boundary(self):
        for field in ['raw_text','refined_text','audio_local_path','credentials','hidden_reasoning','tool_output']:
            with self.assertRaises(ValueError):projection({field:'private'})
        self.assertEqual(safe_url('https://site.example/page?token=private#fragment'),'https://site.example/page')
        with self.assertRaises(ValueError):safe_url('http://localhost/secret')

    def test_source_time_and_identity_validation(self):
        with self.assertRaises(ValueError):Event('typeless','/Users/private','v1','2026-10-05T14:00:00Z','2026-10-05T14:01:00Z',{}).cloud()
        with self.assertRaises(ValueError):Event('typeless','id','v1','2026-10-05T15:00:00Z','2026-10-05T14:01:00Z',{}).cloud()


class PublicEvidenceUrlTests(unittest.TestCase):
    def test_public_https_and_query_fragment_redaction_are_canonical(self):
        self.assertEqual(safe_url('https://site.example/page?token=private#fragment'),'https://site.example/page')
        self.assertEqual(safe_url('https://SITE.example:443/page'),'https://site.example/page')
        self.assertEqual(safe_url('https://8.8.8.8/public'),'https://8.8.8.8/public')
        self.assertEqual(safe_url('https://[2606:4700:4700::1111]/public'),'https://[2606:4700:4700::1111]/public')
        self.assertEqual(safe_url('https://site.example/%E9%A0%90%E8%A6%BD'),'https://site.example/%E9%A0%90%E8%A6%BD')

    def test_local_private_link_local_reserved_and_deceptive_hosts_are_rejected(self):
        hosts=['localhost','one-label','service.local','service.internal','service.localhost','service.test',
               'service.home.arpa','service.local.','127.0.0.1','10.0.0.1','172.16.0.1','192.168.1.1',
               '169.254.169.254','100.64.0.1','0.0.0.0','224.0.0.1','2130706433','127.1',
               '0177.0.0.1','0x7f000001','[::1]','[fe80::1]','[fc00::1]','[::ffff:127.0.0.1]',
               '[fe80::1%25en0]','site.example:80','site.example:444','site.example:','site.example:0443']
        for host in hosts:
            with self.subTest(host=host),self.assertRaises(ValueError):
                safe_url('https://'+host+'/page')

    def test_credentials_malformed_lengths_controls_and_authorities_are_rejected(self):
        urls=['https://user:password@site.example/page','https://@site.example/page','http://site.example/page',
              'https://site.example/\npage','https://site.example/\tpage','https://site.example/\x00page',
              'https://site.example/page name','https://site.example\\@other.example/page',
              'https://[broken/page','https://site.example/%FF','https://site.example/%zz',
              'https://site.example/'+('a'*2_048),'https://site.example/one/../page']
        for url in urls:
            with self.subTest(case=urls.index(url)),self.assertRaises(ValueError):safe_url(url)
        for value in (None,123,{'url':'https://site.example'}):
            with self.assertRaises(ValueError):safe_url(value)

    def test_decoded_sensitive_paths_and_nested_encoding_are_rejected(self):
        paths=['/sk-syntheticprivate123456','/ghp_syntheticprivate1234567890','/token/privatevalue',
               '/api_key=private','/secret/private','/%55sers/private-user/file','/home/private-user/file',
               '/private/tmp/file','/var/log/private','/C:/Users/private-user/file',
               '/person%40example.com','/%2B15551234567','/555-123-4567','/15551234567',
               '/%252FUsers%252Fprivate-user','/sk%252Dsyntheticprivate123456','/part%00private',
               '/to%EF%BD%8Ben/private','/sk-%E2%80%8Bsyntheticprivate123456']
        for path in paths:
            with self.subTest(case=paths.index(path)),self.assertRaises(ValueError):safe_url('https://site.example'+path)

    def test_projection_cannot_restore_private_path_after_text_redaction(self):
        with self.assertRaises(ValueError):projection({'url':'https://site.example/ghp_syntheticprivate1234567890'})
        result=projection({'url':'https://site.example/preview?secret=private'})
        self.assertEqual(result['url'],'https://site.example/preview')
        self.assertNotIn('private',str(result))
