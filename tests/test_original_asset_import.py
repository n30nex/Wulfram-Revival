"""Preserve archives while resolving appended replacement members exactly."""
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
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('asset_import', ROOT/'scripts/import-original-assets.py')
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


class OriginalAssetImportTests(unittest.TestCase):
    def test_last_duplicate_and_case_alias_win_without_rewriting_source_archives(self):
        with tempfile.TemporaryDirectory(prefix='wulfram-assets-') as temporary:
            root = Path(temporary)
            client, output = root/'client', root/'output'
            for relative in importer.FILES.values():
                source = client/'data'/relative
                source.parent.mkdir(parents=True, exist_ok=True)
                if source.suffix == '.zip':
                    with zipfile.ZipFile(source, 'w') as archive:
                        archive.writestr('placeholder', b'unchanged')
                else:
                    source.write_bytes(bytes(768))
            base = client/'data/bitmaps/base.zip'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with zipfile.ZipFile(base, 'w') as archive:
                    archive.writestr('panel', b'old')
                    archive.writestr('panel', b'replacement')
                    archive.writestr('Alias', b'old alias')
                    archive.writestr('alias', b'final alias')
            audio = client/'data/base_sound'
            audio.mkdir()
            (audio/'index.wgn').write_text('TEST fixture 1 1 0 1 2 .5 0\n')
            (audio/'fixture.ogg').write_bytes(b'OggS-test-preservation')
            original = base.read_bytes()
            arguments = ['import-original-assets.py', '--client', str(client), '--output', str(output)]
            with patch.object(sys, 'argv', arguments), contextlib.redirect_stdout(io.StringIO()):
                importer.main()
            self.assertEqual(base.read_bytes(), original)
            self.assertEqual((output/'base.zip').read_bytes(), original)
            self.assertEqual((output/'resolved/base/panel').read_bytes(), b'replacement')
            self.assertEqual((output/'resolved/base/alias').read_bytes(), b'final alias')
            self.assertEqual((output/'audio/fixture.ogg').read_bytes(), (audio/'fixture.ogg').read_bytes())
            manifest = json.loads((output/'manifest.json').read_text())
            for entry in manifest['files']:
                self.assertEqual(hashlib.sha256((output/entry['file']).read_bytes()).hexdigest(), entry['sha256'])
            (output/'resolved/base/panel').write_bytes(b'user content')
            with patch.object(sys, 'argv', arguments), self.assertRaisesRegex(ValueError, 'Refusing to replace'):
                importer.main()
            self.assertEqual((output/'resolved/base/panel').read_bytes(), b'user content')


if __name__ == '__main__':
    unittest.main()
