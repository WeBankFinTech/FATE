import numpy as np
import unittest

from federatedml.feature.feature_imputation import load_value_to_type


class TestFeatureImputation(unittest.TestCase):
    def test_load_value_to_type(self):
        true_v = None
        v_type = "None"
        str_v = None
        self.assertEqual(true_v, load_value_to_type(str_v, v_type))

        true_v = 42
        v_type = type(true_v).__name__
        str_v = "42"
        self.assertEqual(true_v, load_value_to_type(str_v, v_type))

        true_v = "42.0"
        v_type = type(true_v).__name__
        str_v = "42.0"
        self.assertEqual(true_v, load_value_to_type(str_v, v_type))

        true_v = 42.42
        v_type = type(true_v).__name__
        str_v = "42.42"
        self.assertEqual(true_v, load_value_to_type(str_v, v_type))

        true_v = np.array([42, 2, 3])[0]
        v_type = type(true_v).__name__
        str_v = 42
        self.assertEqual(true_v, load_value_to_type(str_v, v_type))


if __name__ == "__main__":
    unittest.main()
