"""Public wire schema and executable admission agree on representative unions."""
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from test_trend_contracts import row, payload
from postriff_phase2.growth.trends.contracts import validate_observation, digest


class ObservationSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / 'docs/design/social-trend-intelligence/observation.schema.json'
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def test_all_evidence_kinds_and_deletion_match(self):
        for kind in ('raw_post', 'owned_post', 'aggregate_metric', 'search_lead', 'trend_seed'):
            value = row(kind=kind, payload=payload(kind))
            with self.subTest(kind=kind):
                self.validator.validate(value)
                validate_observation(value)
        self.validator.validate(row(operation='delete', payload={'platform': 'fixture'}))

    def test_unions_reject_fabricated_evidence_fields(self):
        for kind, prohibited in (('aggregate_metric', 'text'), ('search_lead', 'mention_count'), ('trend_seed', 'author_key')):
            value = row(kind=kind, payload=payload(kind))
            value['payload'][prohibited] = 'fabricated'
            value['payload_digest'] = digest(value['payload'])
            self.assertTrue(list(self.validator.iter_errors(value)))

    def test_missing_unknown_and_malformed_fields_fail(self):
        value = row()
        for mutation in ('missing', 'unknown', 'wrong_scope', 'array_identity'):
            bad = copy.deepcopy(value)
            if mutation == 'missing':
                del bad['available_at']
            elif mutation == 'unknown':
                bad['viral_score'] = 1
            elif mutation == 'wrong_scope':
                bad['scope_key'] = '*'
            else:
                bad['payload']['native_id'] = ['not-a-string']
            self.assertTrue(list(self.validator.iter_errors(bad)), mutation)
