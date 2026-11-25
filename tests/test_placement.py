import unittest

import gi

gi.require_version("Gtk", "3.0")
import math

from agent_usage.widget import fan_angles, fan_layout, items_clear, panel_origin

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
        self.assertEqual([round(math.degrees(angle)) for angle in fan_angles((4800, 1000), AREA)], [144, 90, 36])

    def test_fan_turns_inward_only_as_much_as_needed_in_corner(self):
        angles = [math.degrees(angle) for angle in fan_angles((5708, 1008), AREA)]
        self.assertGreater(angles[1], 90)
        self.assertLess(angles[1], 153)
        for angle in angles:
            x = 5708 + 80 * math.cos(math.radians(angle))
            self.assertLessEqual(x + 32, 3840 + 1920)

    def test_two_agents_spread_evenly_around_top(self):
        self.assertEqual([round(math.degrees(angle), 1) for angle in fan_angles((4800, 1000), AREA, count=2)], [117.0, 63.0])

    def test_fan_opens_downward_near_top(self):
        self.assertEqual(round(math.degrees(fan_angles((4800, 60), AREA)[1])), -90)

    def assert_fan_fits(self, center, count):
        radius, angles = fan_layout(center, AREA, (32, 62, 22), count)
        points = [(center[0] + radius * math.cos(angle), center[1] - radius * math.sin(angle)) for angle in angles]
        for x, y in points:
            self.assertGreaterEqual(x - 32, AREA[0])
            self.assertLessEqual(x + 32, AREA[0] + AREA[2])
            self.assertGreaterEqual(y - 62, AREA[1])
            self.assertLessEqual(y + 22, AREA[1] + AREA[3])
        self.assertTrue(items_clear(points, (32, 62, 22)))
        self.assertLessEqual(radius, 238)
        return radius, angles

    def test_three_agents_keep_original_fan(self):
        self.assertEqual(fan_layout((4800, 1000), AREA, (32, 62, 22), 3), (80, fan_angles((4800, 1000), AREA)))

    def test_overlapping_items_are_detected(self):
        self.assertFalse(items_clear([(0, 0), (40, 0)], (32, 62, 22)))
        self.assertFalse(items_clear([(0, 0), (0, 60)], (32, 62, 22)))
        self.assertTrue(items_clear([(0, 0), (70, 0)], (32, 62, 22)))

    def test_many_accounts_surround_orb_in_open_space(self):
        _radius, angles = self.assert_fan_fits((4800, 500), 7)
        self.assertGreater(max(angles) - min(angles), math.radians(300))

    def test_many_accounts_fit_in_corner(self):
        for count in (2, 3, 4, 5):
            self.assert_fan_fits((5708, 1008), count)

if __name__ == "__main__":
    unittest.main()
