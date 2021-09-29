import numpy as np
import unittest

from skactiveml.utils import compute_vote_vectors
from skactiveml.utils._aggregation import majority_vote


class TestAggregation(unittest.TestCase):

    def test_compute_vote_vectors(self):
        y = [['tokyo', 'paris', 'tokyo'], ['paris', 'paris', 'nan']]
        w = [[0.5, 1, 2], [0, 1, 0]]
        v_rec = compute_vote_vectors(y=y, w=w,
                                     classes=['tokyo', 'paris', 'new york'],
                                     missing_label='nan')
        v_exp = [[0, 1, 2.5], [0, 1, 0]]
        np.testing.assert_array_equal(v_rec, v_exp)

        y = [[np.nan, np.nan, np.nan], [np.nan, np.nan, np.nan]]
        w = [[0.5, 1, 2], [0, 1, 0]]
        v_rec = compute_vote_vectors(y=y, w=w, classes=[2, 4, 5],
                                     missing_label=np.nan)
        v_exp = [[0, 0, 0], [0, 0, 0]]
        np.testing.assert_array_equal(v_rec, v_exp)

    def test_compute_vote_vectors_no_label(self):
        y = np.full(shape=(2, 3), fill_value=np.nan)
        self.assertRaises(ValueError, compute_vote_vectors, y)

    def test_weighted_majority_vote(self):
        y = np.full(shape=(3, 3), fill_value=1, dtype=float)
        y[:, 1] = 0
        y[2, :] = np.nan

        y_transformed_exp = np.full(shape=(3,), fill_value=1, dtype=float)
        y_transformed_exp[2] = np.nan
        y_transformed_rec = majority_vote(y=y)

        np.testing.assert_array_equal(y_transformed_exp, y_transformed_rec)


if __name__ == '__main__':
    unittest.main()
