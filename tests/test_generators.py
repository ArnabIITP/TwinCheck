import unittest

from twincheck.generators import STRATEGIES, generate_inputs


class GeneratorTests(unittest.TestCase):
    def test_generation_is_reproducible(self):
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                self.assertEqual(
                    generate_inputs(80, seed=123, strategy=strategy),
                    generate_inputs(80, seed=123, strategy=strategy),
                )

    def test_generation_returns_requested_unique_count(self):
        for strategy in STRATEGIES:
            with self.subTest(strategy=strategy):
                cases = generate_inputs(60, seed=4, strategy=strategy)
                self.assertEqual(len(cases), 60)
                self.assertEqual(len(set(cases)), 60)

    def test_integer_strategy_starts_with_boundary_values(self):
        cases = generate_inputs(8, seed=0, strategy="integer")
        self.assertEqual(cases[:5], [
            "-9223372036854775808", "-2147483649", "-2147483648", "-32769", "-32768"
        ])

    def test_invalid_count_and_strategy_are_rejected(self):
        with self.assertRaises(ValueError):
            generate_inputs(0)
        with self.assertRaises(ValueError):
            generate_inputs(10, strategy="unknown")


if __name__ == "__main__":
    unittest.main()
