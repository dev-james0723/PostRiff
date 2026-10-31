"""A source read must still name the same parent directories after reading."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from postriff_phase2.release_provenance import read_regular


class ReleaseDirectoryIdentity(unittest.TestCase):
    def replacement_is_rejected(self, symlink):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / 'runtime'
            parent.mkdir()
            target = parent / 'witness.py'
            payload = b'unchanged synthetic source bytes\n'
            target.write_bytes(payload)
            detached = root / 'detached-runtime'
            original_fdopen = os.fdopen
            replaced = False

            def swap_then_open(descriptor, *args, **kwargs):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    parent.rename(detached)
                    if symlink:
                        parent.symlink_to(detached, target_is_directory=True)
                    else:
                        parent.mkdir()
                        (parent / 'witness.py').write_bytes(payload)
                return original_fdopen(descriptor, *args, **kwargs)

            with patch('postriff_phase2.release_provenance.os.fdopen', side_effect=swap_then_open):
                with self.assertRaises((ValueError, OSError)):
                    read_regular(root, 'runtime/witness.py', 1024)
            self.assertTrue(replaced)

    def test_replaced_parent_does_not_validate_detached_directory(self):
        self.replacement_is_rejected(False)

    def test_symlink_parent_replacement_is_rejected(self):
        self.replacement_is_rejected(True)


if __name__ == '__main__':
    unittest.main()
