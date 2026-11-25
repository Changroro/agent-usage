import unittest

import gi

gi.require_version("Gtk", "3.0")
import math

from agent_usage.widget import fan_angles, panel_origin

AREA = (3840, 20, 1920, 1040)


class PlacementTest(unittest.TestCase):
    def test_top_bar_default_is_top_right(self):
        self.assertEqual(panel_origin(None, (440, 300), AREA), (3840 + 1920 - 440 - 12, 28))

    def test_bubble_bottom_right_opens_left_and_upward(self):
        x, y = panel_origin((5680, 980, 56, 56), (440, 500), AREA)
        self.assertEqual((x, y + 500), (5680 - 448, 1036))

    def test_bubble_top_left_opens_right_and_downward(self):
        self.assertEqual(panel_origin((3850, 40, 56, 56), (440, 500), AREA), (3850 + 64, 40))

    def test_tall_panel_stays_inside_workarea(self):
        x, y = panel_origin((5680, 980, 56, 56), (440, 1030), AREA)
        self.assertGreaterEqual(y, 28)
        self.assertLessEqual(x + 440, 3840 + 1920)

    def test_fan_opens_upward_when_there_is_room(self):
        self.assertEqual([round(math.degrees(angle)) for angle in fan_angles((4800, 1000), AREA)], [145, 90, 35])

    def test_fan_turns_inward_only_as_much_as_needed_in_corner(self):
        angles = [math.degrees(angle) for angle in fan_angles((5708, 1008), AREA)]
        self.assertGreater(angles[1], 90)
        self.assertLess(angles[1], 153)
        for angle in angles:
            x = 5708 + 118 * math.cos(math.radians(angle))
            self.assertLessEqual(x + 32, 3840 + 1920)

    def test_two_agents_spread_evenly_around_top(self):
        self.assertEqual([round(math.degrees(angle), 1) for angle in fan_angles((4800, 1000), AREA, count=2)], [117.5, 62.5])

    def test_fan_opens_downward_near_top(self):
        self.assertEqual(round(math.degrees(fan_angles((4800, 60), AREA)[1])), -90)

if __name__ == "__main__":
    unittest.main()
