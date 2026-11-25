import unittest

import cairo
import gi

gi.require_version("Gtk", "3.0")
from agent_usage.widget import ELEMENT_CHANGE, ELEMENT_HOLD, ELEMENTS, element_mix, shift_hue


def pixel(surface):
    data = surface.get_data()
    return data[2], data[1], data[0], data[3]  # red, green, blue, alpha


class OrbTest(unittest.TestCase):
    def test_shift_hue_keeps_alpha_and_brightness(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 2, 1)
        context = cairo.Context(surface)
        context.set_source_rgba(1, 0, 0, 0.5)
        context.rectangle(0, 0, 1, 1)
        context.fill()
        red, green, blue, alpha = pixel(shift_hue(surface, 1 / 3))
        self.assertEqual(alpha, pixel(surface)[3])
        self.assertEqual((red, blue), (0, 0))
        self.assertEqual(green, pixel(surface)[0])
        self.assertEqual(shift_hue(surface, 0.5).get_data()[7], 0)

    def test_elements_hold_then_change_in_order(self):
        span = ELEMENT_HOLD + ELEMENT_CHANGE
        self.assertEqual(element_mix(1.0), (0, 1, 0.0))
        self.assertEqual(element_mix(ELEMENT_HOLD + ELEMENT_CHANGE / 2)[:2], (0, 1))
        self.assertAlmostEqual(element_mix(ELEMENT_HOLD + ELEMENT_CHANGE / 2)[2], 0.5)
        self.assertEqual(element_mix(span * (len(ELEMENTS) - 1) + 1)[:2], (len(ELEMENTS) - 1, 0))
        self.assertEqual(element_mix(span * len(ELEMENTS) + 1)[:2], (0, 1))

if __name__ == "__main__":
    unittest.main()
