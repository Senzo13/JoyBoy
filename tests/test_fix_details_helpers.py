import unittest

from PIL import Image, ImageDraw

from web.routes.generation import _split_detail_regions


def _mask_area(mask):
    return sum(1 for px in mask.tobytes() if px > 0)


class FixDetailsHelperTests(unittest.TestCase):
    def test_split_detail_regions_filters_sorts_and_caps_components(self):
        mask = Image.new("L", (120, 120), 0)
        draw = ImageDraw.Draw(mask)
        draw.rectangle((5, 5, 8, 8), fill=255)       # too small
        draw.rectangle((20, 20, 39, 39), fill=255)   # 400 px
        draw.rectangle((60, 20, 95, 55), fill=255)   # largest
        draw.rectangle((30, 80, 55, 105), fill=255)  # medium

        regions = _split_detail_regions(mask, dilation_px=0, min_area=100, max_regions=2)

        self.assertEqual(len(regions), 2)
        areas = [_mask_area(region) for region in regions]
        self.assertGreaterEqual(areas[0], areas[1])
        self.assertGreater(areas[1], 100)

    def test_split_detail_regions_dilates_region_when_requested(self):
        mask = Image.new("L", (40, 40), 0)
        draw = ImageDraw.Draw(mask)
        draw.rectangle((15, 15, 24, 24), fill=255)

        no_dilate = _split_detail_regions(mask, dilation_px=0, min_area=10, max_regions=1)[0]
        dilated = _split_detail_regions(mask, dilation_px=3, min_area=10, max_regions=1)[0]

        no_dilate_area = _mask_area(no_dilate)
        dilated_area = _mask_area(dilated)
        self.assertGreater(dilated_area, no_dilate_area)


if __name__ == "__main__":
    unittest.main()
