import unittest

from fmt import format_total


class FormatTotalTest(unittest.TestCase):
    def test_two_decimal_places(self):
        self.assertEqual(format_total(3.5), "3.50")


if __name__ == "__main__":
    unittest.main()
