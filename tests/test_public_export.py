from pathlib import Path
import json
import runpy
import tempfile
import unittest

EXPORT=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/publish-status.py'))


class ExportTests(unittest.TestCase):
    def test_export_drops_names_addresses_and_extra_server_fields(self):
        data={'updated_utc':'2026-10-12T00:00:00Z','map':'crossroads','phase':'playing',
              'seconds_remaining':100,'bots':64,'players':0,'human_capacity':16,
              'teams':[{'id':team,'points':4,'bots':32,'players':0,'repair_pads':2,'address':'private'} for team in (1,2)],
              'leaders':[{'name':'private-name'}],'password':'private-password'}
        with tempfile.TemporaryDirectory() as directory:
            source,destination=Path(directory)/'input.json',Path(directory)/'status.json'
            source.write_text(json.dumps(data))
            EXPORT['publish'](source,destination)
            rendered=destination.read_text()
            self.assertNotIn('private',rendered)
            self.assertEqual(json.loads(rendered)['bots'],64)
            source.write_text('{invalid')
            with self.assertRaises(ValueError): EXPORT['publish'](source,destination)
            self.assertEqual(destination.read_text(),rendered)


if __name__=='__main__': unittest.main()
