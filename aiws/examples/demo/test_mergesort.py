import random
import unittest

from mergesort import merge, sort


class MergeSortTest(unittest.TestCase):
    def test_merge(self):
        self.assertEqual(merge([1, 4, 9], [2, 3]), [1, 2, 3, 4, 9])

    def test_sort_random(self):
        xs = [random.randint(0, 999) for _ in range(500)]
        self.assertEqual(sort(xs), sorted(xs))


if __name__ == "__main__":
    unittest.main()
