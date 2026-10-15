"""Map sky settings are preserved as data, not executed or silently replaced."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('map_import', ROOT/'scripts/import-modern-maps.py')
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


class ModernMapImportTests(unittest.TestCase):
    def test_preserved_sky_script_is_sealed_and_local_changes_are_protected(self):
        with tempfile.TemporaryDirectory(prefix='wulfram-map-') as temporary:
            root = Path(temporary)
            original = b'sky_names "2starset, Aurora"\r\nmap_name "Fixture"\r\n'
            for name in ('crossroads', 'mayhem', 'frontier'):
                source = root/'shared/data/maps'/name
                source.mkdir(parents=True)
                (source/'land').write_text('2x2\n100x100\n0 0\n0 0\n0 0\n0 0\n')
                (source/'tagmap2').write_text('synthetic\n')
                (source/'start_script').write_bytes(original)
            output = root/'output'
            arguments = ['import-modern-maps.py', '--content-root', str(root), '--output', str(output)]
            with patch.object(sys, 'argv', arguments), contextlib.redirect_stdout(io.StringIO()):
                importer.main()
            manifest = json.loads((output/'manifest.json').read_text())
            for entry in manifest['maps']:
                self.assertEqual((output/(entry['name']+'.start_script')).read_bytes(), original)
                self.assertEqual(entry['start_script_sha256'], hashlib.sha256(original).hexdigest())
            target = output/'crossroads.start_script'
            target.write_bytes(b'local customization')
            with patch.object(sys, 'argv', arguments), self.assertRaisesRegex(SystemExit, 'Refusing to replace different sky'):
                importer.main()
            self.assertEqual(target.read_bytes(), b'local customization')


if __name__ == '__main__':
    unittest.main()
