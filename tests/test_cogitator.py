"""Shared design and truthful date conventions without a display server."""
from datetime import datetime, timezone
import unittest

from marsi_local.theme import css, definition, imperial_date, sensor_style


class ThemeTests(unittest.TestCase):
    def test_css_and_tk_use_the_same_tokens(self):
        for name, color in definition()["colors"].items():
            self.assertIn(f"--{name}: {color}", css())
        self.assertEqual(definition()["layout"]["fps"], 15)

    def test_four_sensors_have_distinct_colours_shapes_and_patterns(self):
        styles = [sensor_style({}, index) for index in range(4)]
        for key in ("color", "shape"):
            self.assertEqual(len({style[key] for style in styles}), 4)
        self.assertEqual(len({tuple(style["dash"]) for style in styles}), 4)
        self.assertEqual(sensor_style({"color": "#123456"}, 1)["color"], "#123456")
        self.assertEqual(sensor_style({"color": "invalid"}, 1), styles[1])

    def test_imperial_display_uses_real_year_boundaries_and_leap_year(self):
        self.assertEqual(imperial_date(datetime(2026, 1, 1, tzinfo=timezone.utc)), "0.000026.M42")
        self.assertEqual(imperial_date(datetime(2024, 7, 2, tzinfo=timezone.utc)), "0.500024.M42")
        self.assertEqual(imperial_date(datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)), "0.999026.M42")
        self.assertNotEqual(imperial_date(datetime(2026, 1, 1, tzinfo=timezone.utc)),
                            imperial_date(datetime(2027, 1, 1, tzinfo=timezone.utc)))
