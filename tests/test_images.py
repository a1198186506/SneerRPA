import base64
import copy
import io
from pathlib import Path
import sys
import unittest
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'extensions'))
from image_assets import encode_crop, validate_image, PREFIX
from validation import validate_flow


class ImageAssets(unittest.TestCase):
    def setUp(self):
        self.source=Image.new('RGB',(80,60),'white')
        self.source.putpixel((12,13),(101,88,232))
        self.asset=encode_crop(self.source,(10,10,50,40),(-1920,-200))

    def test_original_pixels_dimensions_and_negative_origin(self):
        self.assertGreater(validate_image(self.asset),0)
        self.assertEqual(self.asset['capture_rect'],{'x':-1910,'y':-190,'width':40,'height':30})
        restored=Image.open(io.BytesIO(base64.b64decode(self.asset['data_url'][len(PREFIX):])))
        self.assertEqual(restored.getpixel((2,3)),(101,88,232))
        self.assertEqual(restored.size,(40,30))

    def test_tiny_and_outside_regions_are_rejected(self):
        for box in [(1,1,2,2),(-1,0,10,10),(0,0,100,100)]:
            with self.assertRaises(ValueError):
                encode_crop(self.source,box)

    def test_invalid_png_metadata_and_duplicate_ids(self):
        for updates in [{'width':99},{'data_url':PREFIX+'a'},{'data_url':'data:image/svg+xml;base64,AAAA'},{'name':''}]:
            with self.assertRaises(ValueError):
                validate_image({**self.asset,**updates})
        flow={'schema_version':1,'steps':[],'images':[self.asset,copy.deepcopy(self.asset)]}
        with self.assertRaises(ValueError):
            validate_flow(flow,allow_empty=True)

    def test_images_are_separate_from_control_targets(self):
        flow={'schema_version':1,'steps':[],'images':[self.asset]}
        validate_flow(flow,allow_empty=True)
        flow['steps']=[{'id':'click','name':'点击','type':'element.click','params':{'element':self.asset['id']}}]
        with self.assertRaises(ValueError):
            validate_flow(flow)


if __name__=='__main__':
    unittest.main(verbosity=2)
