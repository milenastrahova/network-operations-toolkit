import unittest
from netops.metrics import percentile, summary, variation
from netops.alerts import DebouncedAlert

class TestMetrics(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(summary([])["p99"])
    def test_nearest_rank(self):
        self.assertEqual(percentile(list(range(1,101)),99),99)
    def test_small_n(self):
        self.assertEqual(percentile([1,2],95),2)
    def test_invalid_percentage(self):
        with self.assertRaises(ValueError):percentile([1],101)
    def test_invalid_measurement(self):
        with self.assertRaises(ValueError):summary([float('nan')])
    def test_variation(self):
        self.assertEqual(variation([2,7,6])["max"],5)

class TestAlert(unittest.TestCase):
    def test_debounce(self):
        alert = DebouncedAlert()
        self.assertIsNone(alert.observe(False))
        self.assertIsNone(alert.observe(False))
        self.assertEqual(alert.observe(False), "OPENED")
        self.assertIsNone(alert.observe(False))
        self.assertIsNone(alert.observe(True))
        self.assertEqual(alert.observe(True), "RECOVERED")
    def test_failure_counter_resets(self):
        alert=DebouncedAlert()
        alert.observe(False);alert.observe(True)
        self.assertIsNone(alert.observe(False))
    def test_invalid_threshold(self):
        with self.assertRaises(ValueError): DebouncedAlert(failures_to_open=0)
