"""Unit tests for external 3 km OSM/Overpass GIS verification and silent-omission detection."""

from __future__ import annotations

import unittest

from eced_watchdog.gis import detect_spatial_omissions, parse_overpass_elements


class TestGisVerification(unittest.TestCase):
    def test_parse_overpass_and_detect_silent_olive_omission(self) -> None:
        lat, lon = 38.6700, 26.8500
        elements = [
            {
                "type": "way",
                "center": {"lat": 38.6750, "lon": 26.8520},
                "tags": {"landuse": "orchard", "trees": "olive_trees", "name": "Ilıpınar Zeytinliği"},
            },
            {
                "type": "way",
                "center": {"lat": 38.6730, "lon": 26.8500},
                "tags": {"waterway": "stream", "name": "Koca Dere"},
            },
            {
                "type": "node",
                "lat": 38.6745,
                "lon": 26.8505,
                "tags": {"place": "village", "name": "Ilıpınar"},
            },
            {
                "type": "way",
                "center": {"lat": 38.6800, "lon": 26.8550},
                "tags": {"boundary": "protected_area", "name": "Foça ÖÇK"},
            },
            # Outside 3 km radius — must be excluded
            {
                "type": "node",
                "lat": 38.7200,
                "lon": 26.9000,
                "tags": {"place": "village", "name": "Uzak Köy"},
            },
        ]

        parsed = parse_overpass_elements(elements, lat, lon, radius_m=3000)
        cats = parsed["categories"]
        self.assertEqual(cats["olive_or_orchard"]["count"], 1)
        self.assertEqual(cats["olive_or_orchard"]["explicit_olive_count"], 1)
        self.assertEqual(cats["water_bodies"]["count"], 1)
        self.assertEqual(cats["protected_or_forest"]["protected_count"], 1)
        self.assertEqual(cats["settlements"]["count"], 1)
        self.assertEqual(cats["settlements"]["nearest"][0]["name"], "Ilıpınar")

        # Case 1: PDF omitted both olive law & groundwater -> should trigger high omission alerts
        alerts_omitted = detect_spatial_omissions(
            parsed,
            {"mentions_olive_law_3573": False, "mentions_groundwater_or_aquifer": False},
        )
        codes = {a["code"] for a in alerts_omitted}
        self.assertIn("omitted_olive_3km", codes)
        self.assertIn("protected_area_3km", codes)
        self.assertIn("omitted_water_1500m", codes)
        self.assertIn("settlement_1km", codes)

        # Case 2: PDF did mention olive & groundwater -> no omitted_olive_3km / omitted_water_1500m
        alerts_mentioned = detect_spatial_omissions(
            parsed,
            {"mentions_olive_law_3573": True, "mentions_groundwater_or_aquifer": True},
        )
        codes2 = {a["code"] for a in alerts_mentioned}
        self.assertNotIn("omitted_olive_3km", codes2)
        self.assertIn("olive_3km_proximity", codes2)
        self.assertNotIn("omitted_water_1500m", codes2)


if __name__ == "__main__":
    unittest.main()
