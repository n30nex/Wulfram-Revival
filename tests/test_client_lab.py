"""The screenshot check must catch a clipped map even when geometry is correct."""
from pathlib import Path
import runpy
import struct
import tempfile
import unittest

LAB = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/client-lab.py'))


class ClientLabTests(unittest.TestCase):
    def test_ui_size_is_consistent_across_hd_pixel_densities(self):
        for width,height in ((1280,720),(1920,1080),(2560,1440),(3840,2160)):
            self.assertEqual(LAB['logical_size'](width,height),[960,540])

    def test_map_pixel_check_rejects_blank_texture(self):
        header = bytearray(54)
        header[:2] = b'BM'
        struct.pack_into('<I',header,10,54)
        struct.pack_into('<ii',header,18,128,128)
        struct.pack_into('<H',header,28,24)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'screen.bmp'
            for value,problem in ((64,False),(0,True)):
                path.write_bytes(header+bytes([value])*(128*128*3))
                state = {'scene':'map','viewports':{'entry_map':{'origin':[16,16],'size':[96,96]}},'layout_problems':[]}
                LAB['check_map_image'](path,state)
                self.assertEqual(bool(state['layout_problems']),problem)
            state['viewports']['entry_map']['origin']=[100,100]
            with self.assertRaisesRegex(ValueError,'leave the screenshot'):
                LAB['check_map_image'](path,state)


if __name__ == '__main__': unittest.main()
