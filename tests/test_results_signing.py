"""R-OUT-03 signed first-party delivery contract (AC17 signature/replay/rotation cases, pure functions)."""
import unittest

from postriff_phase2.results import signing


BODY = b'{"eventId":"evt_1","type":"booking","occurredAt":"2026-10-01T15:00:00Z"}'


class SigningContractTest(unittest.TestCase):
    def setUp(self):
        self.secret = signing.new_secret()
        self.now = 1_790_870_000

    def test_new_secret_shape_and_fingerprint_do_not_reveal_secret(self):
        self.assertTrue(self.secret.startswith("rfs_"))
        self.assertEqual(len(self.secret), 4 + 64)
        fingerprint = signing.secret_fingerprint(self.secret)
        self.assertEqual(len(fingerprint), 12)
        self.assertNotIn(fingerprint, self.secret)

    def test_valid_signature_verifies_against_current_secret(self):
        header = signing.sign(self.secret, self.now, BODY)
        self.assertEqual(signing.verify(header, BODY, [self.secret], self.now + 10), {"timestamp": self.now, "keyIndex": 0})

    def test_signature_is_over_exact_bytes(self):
        header = signing.sign(self.secret, self.now, BODY)
        altered = BODY.replace(b"booking", b"sale")
        with self.assertRaises(signing.SignatureError) as caught:
            signing.verify(header, altered, [self.secret], self.now)
        self.assertEqual(caught.exception.code, "signature_mismatch")
        whitespace = BODY + b" "
        with self.assertRaises(signing.SignatureError):
            signing.verify(header, whitespace, [self.secret], self.now)

    def test_stale_and_future_timestamps_are_refused(self):
        header = signing.sign(self.secret, self.now, BODY)
        for now in (self.now + signing.REPLAY_WINDOW_SECONDS + 1, self.now - signing.REPLAY_WINDOW_SECONDS - 1):
            with self.assertRaises(signing.SignatureError) as caught:
                signing.verify(header, BODY, [self.secret], now)
            self.assertEqual(caught.exception.code, "timestamp_outside_window")
        # Exactly at the edge is still inside the window.
        self.assertEqual(signing.verify(header, BODY, [self.secret], self.now + signing.REPLAY_WINDOW_SECONDS)["keyIndex"], 0)

    def test_a_stale_timestamp_is_only_reported_for_a_really_signed_delivery(self):
        """Without the secret nobody can make a delivery read as "the producer's clock is off": an unsigned or wrongly
        signed delivery is a mismatch whatever its timestamp."""
        stale = self.now - signing.REPLAY_WINDOW_SECONDS - 60
        for header in (signing.sign(signing.new_secret(), stale, BODY), f"t={stale},v1=" + "a" * 64):
            with self.assertRaises(signing.SignatureError) as caught:
                signing.verify(header, BODY, [self.secret], self.now)
            self.assertEqual(caught.exception.code, "signature_mismatch", header)
        with self.assertRaises(signing.SignatureError) as caught:
            signing.verify(signing.sign(self.secret, stale, BODY), BODY, [self.secret], self.now)
        self.assertEqual(caught.exception.code, "timestamp_outside_window")

    def test_rotation_accepts_previous_secret_and_dual_signatures(self):
        old, new = self.secret, signing.new_secret()
        old_header = signing.sign(old, self.now, BODY)
        self.assertEqual(signing.verify(old_header, BODY, [new, old], self.now)["keyIndex"], 1)
        dual = signing.sign(new, self.now, BODY) + "," + signing.sign(old, self.now, BODY).split(",", 1)[1]
        self.assertEqual(signing.verify(dual, BODY, [new, old], self.now)["keyIndex"], 0)
        # Once the previous secret leaves the accepted set, its signatures stop working.
        with self.assertRaises(signing.SignatureError):
            signing.verify(old_header, BODY, [new], self.now)

    def test_wrong_secret_and_missing_secret(self):
        header = signing.sign(self.secret, self.now, BODY)
        with self.assertRaises(signing.SignatureError) as caught:
            signing.verify(header, BODY, [signing.new_secret()], self.now)
        self.assertEqual(caught.exception.code, "signature_mismatch")
        with self.assertRaises(signing.SignatureError) as caught:
            signing.verify(header, BODY, [], self.now)
        self.assertEqual(caught.exception.code, "connection_has_no_secret")

    def test_malformed_headers(self):
        for value in (None, "", "v1=" + "a" * 64, "t=abc,v1=" + "a" * 64, "t=1,t=2,v1=" + "a" * 64, "t=1,v1=zz",
                      "t=1,v1=" + "A" * 64, "t=1,x=2", "t=1," + ",".join(["v1=" + "a" * 64] * 5), "t=1;v1=" + "a" * 64):
            with self.assertRaises(signing.SignatureError, msg=repr(value)):
                signing.verify(value, BODY, [self.secret], 1)

    def test_body_size_limit_is_checked_before_signature_work(self):
        big = b"x" * (signing.MAX_BODY_BYTES + 1)
        with self.assertRaises(signing.SignatureError) as caught:
            signing.verify("t=1,v1=" + "a" * 64, big, [self.secret], 1)
        self.assertEqual(caught.exception.code, "body_too_large")

    def test_event_digest_is_canonical(self):
        a = {"type": "booking", "eventId": "e1", "amount": {"minor": 1200, "currency": "usd"}}
        b = {"amount": {"currency": "usd", "minor": 1200}, "eventId": "e1", "type": "booking"}
        self.assertEqual(signing.event_digest(a), signing.event_digest(b))
        self.assertNotEqual(signing.event_digest(a), signing.event_digest({**a, "type": "sale"}))


if __name__ == "__main__":
    unittest.main()
