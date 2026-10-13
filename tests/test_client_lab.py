"""The screenshot check must catch a clipped map even when geometry is correct."""
from pathlib import Path
import runpy
import struct
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

LAB = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/client-lab.py'))


class ClientLabTests(unittest.TestCase):
    def test_a_single_world_frame_followed_by_an_error_is_not_success(self):
        for stays in (False, True):
            now, calls = [0.0], [0]
            def inspect(_):
                calls[0] += 1
                return {'scene':'world' if stays or calls[0] == 1 else 'other'}
            clock = LAB['wait_for_state'].__globals__['time']
            with patch.object(clock,'monotonic',side_effect=lambda:now[0]), \
                 patch.object(clock,'sleep',side_effect=lambda seconds:now.__setitem__(0,now[0]+seconds)):
                state, stable = LAB['wait_for_state'](SimpleNamespace(inspect=inspect),[960,540],
                                                      lambda current: current['scene']=='world',timeout=1)
            self.assertEqual(stable,stays)
            self.assertGreaterEqual(now[0],.75)

    def test_cursor_pixel_check_rejects_a_pointer_drawn_at_an_offset(self):
        header=bytearray(54); header[:2]=b'BM'
        struct.pack_into('<I',header,10,54)
        struct.pack_into('<ii',header,18,128,128)
        struct.pack_into('<H',header,28,24)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'cursor.bmp'
            for x,y,problem in ((40,40,True),(20,20,False)):
                pixels=bytearray(128*128*3)
                for row in range(y,y+5):
                    for col in range(x,x+5):
                        at=(127-row)*128*3+col*3
                        pixels[at:at+3]=b'\xff\xff\xff'
                path.write_bytes(header+pixels)
                state={'cursor_position':[20,20],'layout_problems':[]}
                LAB['check_cursor_image'](path,state)
                self.assertEqual(bool(state['layout_problems']),problem)

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
