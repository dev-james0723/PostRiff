"""Hosted Control connects with verify-full against the bundled, pinned Supabase root (no public CA chains to it)."""
import hashlib
import ssl
import unittest

from rafii_control import store

EXPECTED = '807025ad50d4ed219d2c9c7d299c004f824eb00cf7f65afef607d07b72e6cafa'


class HostedTlsTests(unittest.TestCase):
    def test_bundled_root_is_the_published_supabase_root_2021(self):
        pem = store.SUPABASE_ROOT.read_text()
        der = ssl.PEM_cert_to_DER_cert(pem)
        self.assertEqual(hashlib.sha256(der).hexdigest(), EXPECTED)

    def test_verify_full_without_root_uses_the_bundled_one(self):
        dsn = 'host=aws-0-us-east-1.pooler.supabase.com port=5432 dbname=postgres user=login.ref password=x sslmode=verify-full'
        self.assertEqual(store.tls_options(dsn), {'sslrootcert': str(store.SUPABASE_ROOT)})

    def test_an_explicit_root_or_another_sslmode_is_left_alone(self):
        self.assertEqual(store.tls_options('host=h dbname=postgres sslmode=verify-full sslrootcert=/etc/ca.pem'), {})
        self.assertEqual(store.tls_options('host=127.0.0.1 port=5432 dbname=postgres'), {})
        self.assertEqual(store.tls_options('host=h dbname=postgres sslmode=require'), {})


if __name__ == '__main__':
    unittest.main()
