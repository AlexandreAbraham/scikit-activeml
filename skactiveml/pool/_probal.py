import itertools
import warnings

import numpy as np
from scipy.special import factorial, gammaln
from sklearn import clone
from sklearn.metrics import pairwise_kernels
from sklearn.utils import check_array, check_random_state

from skactiveml.base import SingleAnnotPoolBasedQueryStrategy, \
    ClassFrequencyEstimator
from skactiveml.classifier import PWC
from skactiveml.utils import check_classifier_params, check_X_y, ExtLabelEncoder
from skactiveml.utils import rand_argmax, MISSING_LABEL, check_cost_matrix, \
    check_scalar, is_labeled


class McPAL(SingleAnnotPoolBasedQueryStrategy):
    """Multi-class Probabilistic Active Learning

    This class implements multi-class probabilistic active learning (McPAL) [1]
    strategy.

    Parameters
    ----------
    clf: BaseEstimator
        Probabilistic classifier for gain calculation.
    prior: float, optional (default=1)
        Prior probabilities for the Dirichlet distribution of the samples.
    m_max: int, optional (default=1)
        Maximum number of hypothetically acquired labels.
    random_state: numeric | np.random.RandomState, optional
        Random state for candidate selection.

    References
    ----------
    [1] Daniel Kottke, Georg Krempl, Dominik Lang, Johannes Teschner, and Myra
    Spiliopoulou.
        Multi-Class Probabilistic Active Learning,
        vol. 285 of Frontiers in Artificial Intelligence and Applications,
        pages 586-594. IOS Press, 2016
    """

    def __init__(self, clf, prior=1, m_max=1, random_state=None):
        super().__init__(random_state=random_state)
        self.clf = clf
        self.prior = prior
        self.m_max = m_max

    def query(self, X_cand, X, y, sample_weight, batch_size=1,
              return_utilities=False, **kwargs):
        """Query the next instance to be labeled.

        Parameters
        ----------
        X_cand: array-like, shape(n_candidates, n_features)
            Unlabeled candidate samples
        X: array-like (n_training_samples, n_features)
            Complete data set
        y: array-like (n_training_samples)
            Labels of the data set
        batch_size: int, optional (default=1)
            The number of instances to be selected.
        sample_weight: array-like (n_training_samples)
            Densities for each instance in X
        return_utilities: bool (default=False)
            If True, the utilities are additionally returned.

        Returns
        -------
        query_indices: np.ndarray, shape (1)
            The index of the queried instance.
        utilities: np.ndarray, shape (1, n_candidates)
            The utilities of all instances in X_cand
            (only returned if return_utilities is True).
        """
        # Check if the classifier and its arguments are valid
        if not isinstance(self.clf, ClassFrequencyEstimator):
            raise TypeError("'clf' must implement methods according to "
                            "'ClassFrequencyEstimator'.")
        check_classifier_params(self.clf.classes, self.clf.missing_label)
        self.clf = clone(self.clf)

        # Check if 'prior' is valid
        check_scalar(self.prior, 'prior', (float, int),
                     min_inclusive=False, min_val=0)

        # Check if 'm_max' is valid
        if self.m_max < 1 or not float(self.m_max).is_integer():
            raise ValueError("'m_max' must be a positive integer.")

        # Check the given data
        X_cand = check_array(X_cand, force_all_finite=False)
        X, y = check_X_y(X, y, force_all_finite=False,
                         missing_label=self.clf.missing_label)

        # Check 'batch_size'
        check_scalar(batch_size, 'batch_size', int, min_val=1)

        # Calculate utilities and return the output
        self.clf.fit(X, y)
        k_vec = self.clf.predict_freq(X_cand)
        utilities = sample_weight * _cost_reduction(k_vec, prior=self.prior,
                                                    m_max=self.m_max)
        query_indices = rand_argmax(utilities, self.random_state)
        if return_utilities:
            return query_indices, np.array([utilities])
        else:
            return query_indices


class BayesianPriorLearner(PWC):
    # TODO: commment
    def __init__(self, n_neighbors=None, metric='rbf', metric_dict=None,
                 classes=None, missing_label=MISSING_LABEL, cost_matrix=None,
                 prior=None, random_state=None):
        super().__init__(n_neighbors=n_neighbors, metric=metric,
                         metric_dict=metric_dict, classes=classes,
                         missing_label=missing_label, cost_matrix=cost_matrix,
                         random_state=random_state)
        self.prior = prior

    def fit(self, X, y, sample_weight=None):
        """Fit the model using X as training data and y as class labels.

        Parameters
        ----------
        X : matrix-like, shape (n_samples, n_features)
            The sample matrix X is the feature matrix representing the samples.
        y : array-like, shape (n_samples) or (n_samples, n_outputs)
            It contains the class labels of the training samples.
            The number of class labels may be variable for the samples, where
            missing labels are represented the attribute 'missing_label'.
        sample_weight : array-like, shape (n_samples) or (n_samples, n_outputs)
            It contains the weights of the training samples' class labels.
            It must have the same shape as y.

        Returns
        -------
        # TODO
        self: PWC,
            The PWC is fitted on the training data.
        """
        super().fit(X=X, y=y, sample_weight=sample_weight)
        n_classes = len(self.classes_)
        if self.prior is None:
            self.prior_ = np.zeros([1, n_classes])
        else:
            self.prior_ = np.array(self.prior)
            if self.prior_.shape != (n_classes,):
                raise ValueError(
                    "Shape mismatch for 'prior': It is '{}' instead of '({"
                    "})'".format(self.prior_.shape, n_classes)
                )
            else:
                self.prior_ = self.prior_.reshape(1, -1)

    def predict_freq(self, X):
        """Return class frequency estimates for the input samples 'X'.

        Parameters
        ----------
        X: array-like, shape (n_samples, n_features) or shape
        (n_samples, m_samples) if metric == 'precomputed'
            Input samples.

        Returns
        -------
        # TODO
        F: array-like, shape (n_samples, classes)
            The class frequency estimates of the input samples. Classes are
            ordered according to classes_.
        """
        return super().predict_freq(X) + self.prior_


class XPAL(SingleAnnotPoolBasedQueryStrategy):

    def __init__(self, clf, metric='error',
                 cost_vector=None, cost_matrix=None, custom_perf_func=None,
                 prior_cand=1.e-3, prior_eval=1.e-3,
                 estimator_metric='rbf', estimator_metric_dict=None,
                 batch_mode='greedy', all_sim_labels_equal=True,
                 nonmyopic_look_ahead=1, nonmyopic_neighbors='nearest',
                 nonmyopic_independence=True,
                 random_state=None):
        """ XPAL
        The cost-sensitive expected probabilistic active learning (CsXPAL) strategy is a generalization of the
        multi-class probabilistic active learning (McPAL) [1], the optimised probabilistic active learning (OPAL) [2]
        strategy, and the cost-sensitive probabilistic active learning (CsPAL) strategy due to consideration of a cost
        matrix for multi-class classification problems and the computation of the expected error on an evaluation set.

        Attributes
        ----------
        prob_estimator: BaseEstimator
            The method that estimates the ground truth. The method should be
            Bayesian, e.g. local learning with Bayesian Prior.
        prob_estimator_eval: BaseEstimator
            Similar to prob_estimator but used for calculating the
            probabilities of evaluation instances. The default is to use the
            prob_estimator if not given.
        metric: string
            "error"
                equivalent to accuracy
            "cost-vector"
                requires cost-vector
            "misclassification-loss"
                requires cost-matrix
            "mean-abs-error"
            "macro-accuracy"
                optional: TODO: prior_class_probability
            "f1-score"

        cost_matrix: array-like (n_classes, n_classes)
        cost_vector: array-like (n_classes)

        mode: string
            The mode to select candidates:
                "default" (default)
                    Instances are selected sequentially using the non-myopic
                    selection with max_nonmyopic_size into a batch.
                "density-qpprox"
                    no X_eval needed, but weights

        max_nonmyopic_size: int

        random_state

        missing_label

        References
        ----------
        [1] TODO: xpal arxiv, diss
        """
        super().__init__(random_state=random_state)

        self.clf = clf
        self.metric = metric
        self.cost_vector = cost_vector
        self.cost_matrix = cost_matrix
        self.custom_perf_func = custom_perf_func
        self.prior_cand = prior_cand
        self.prior_eval = prior_eval
        self.estimator_metric = estimator_metric
        self.estimator_metric_dict = estimator_metric_dict
        self.batch_mode = batch_mode
        self.all_sim_labels_equal = all_sim_labels_equal
        self.nonmyopic_look_ahead = nonmyopic_look_ahead
        self.nonmyopic_neighbors = nonmyopic_neighbors
        self.nonmyopic_independence = nonmyopic_independence

    def _validate_input(self, X_cand, X, y, X_eval, batch_size, sample_weight,
                        return_utilities):

        # init parameters
        # TODO: implement and adapt, what happens if X_eval=self
        # random_state = check_random_state(self.random_state, len(X_cand),
        #                                   len(X_eval))
        self._random_state = check_random_state(self.random_state)

        check_classifier_params(self._classes, self._missing_label,
                                self.cost_matrix)
        check_scalar(self.prior_cand, target_type=float, name='prior_cand',
                     min_val=0, min_inclusive=False)
        check_scalar(self.prior_eval, target_type=float, name='prior_eval',
                     min_val=0, min_inclusive=False)

        self._batch_size = batch_size
        check_scalar(self._batch_size, target_type=int, name='batch_size',
                     min_val=1)
        if len(X_cand) < self._batch_size:
            warnings.warn(
                "'batch_size={}' is larger than number of candidate samples "
                "in 'X_cand'. Instead, 'batch_size={}' was set ".format(
                    self._batch_size, len(X_cand)))
            self._batch_size = len(X_cand)

        # TODO: check if X_cand, X, X_eval have similar num_features
        # TODO: check if X, y match
        # TODO: check if weight match with X_cand
        if sample_weight is None:
            self.sample_weight_ = np.ones(len(X))
        else:
            self.sample_weight_ = sample_weight
        # TODO: check if return_utilities is bool

    def query(self, X_cand, X, y, X_eval, batch_size=1,
              sample_weight_cand=None, sample_weight=None,
              sample_weight_eval=None, return_utilities=False, **kwargs):
        """

        Attributes
        ----------
        X: array-like (n_training_samples, n_features)
            Labeled samples
        y: array-like (n_training_samples)
            Labels of labeled samples
        X_cand: array-like (n_samples, n_features)
            Unlabeled candidate samples
        X_eval: array-like (n_samples, n_features) or string
            Unlabeled evaluation samples
        """

        missing_label = self.clf.missing_label
        label_encoder = ExtLabelEncoder(missing_label=missing_label,
                                        classes=self.clf.classes).fit(y)
        classes = label_encoder.classes_
        n_classes = len(classes)

        # TODO: n_features should come from _validate_data (check dimensions)
        n_features = X_cand.shape[1]
        #X_cand = check_X_y(X_cand)


        if self.estimator_metric_dict is None:
            self.estimator_metric_dict = {}

        metric, cost_matrix, perf_func = \
            _transform_metric(self.metric, self.cost_vector, self.cost_matrix,
                              self.custom_perf_func, n_classes=n_classes)

        # TODO: check if cost_matrix is similar to clf, otherwise warning


        #self._validate_input(X_cand, X, y, X_eval, batch_size, sample_weight,
        #                     return_utilities)

        if sample_weight is None:
            sample_weight = np.ones(len(X))

        prior = calculate_optimal_prior(cost_matrix)
        self._prior_cand = self.prior_cand * prior
        self._prior_eval = self.prior_eval * prior

        if self.estimator_metric == 'rbf' and \
                self.estimator_metric_dict is None:
            # TODO: include std, citations, check gamma-bandwidth transformation
            bandwidth = estimate_bandwidth(X.shape[0], X.shape[1])
            estimator_metric_dict = {'gamma': 1/bandwidth}
        if self.estimator_metric_dict is None:
            estimator_metric_dict = {}
        else:
            estimator_metric_dict = self.estimator_metric_dict

        K = lambda X1, X2: pairwise_kernels(X1, X2,
                                            metric=self.estimator_metric,
                                            **estimator_metric_dict)

        # filter out mostly all unlabeled for Bayesian Local Learner
        mask_lbld = is_labeled(y, missing_label)
        if np.sum(mask_lbld) == 0:
            mask_lbld[0] = True

        X_ = X[mask_lbld]
        y_ = y[mask_lbld]
        sample_weight_ = sample_weight[mask_lbld]
        sim_c_x = K(X_cand, X_)
        if X_eval is None:
            sim_e_x = sim_c_x
            sim_e_c = K(X_cand, X_cand)
        else:
            sim_e_x = K(X_eval, X_)
            sim_e_c = K(X_eval, X_cand)
        if batch_size > 1 or self.nonmyopic_look_ahead > 1:
            sim_c_c = K(X_cand, X_cand)
        else:
            sim_c_c = np.full([len(X_cand), len(X_cand)], np.nan)

        prob_estimator_cand = BayesianPriorLearner(prior=self._prior_cand,
                                                   classes=classes,
                                                   missing_label=missing_label,
                                                   metric="precomputed")
        prob_estimator_eval = BayesianPriorLearner(prior=self._prior_cand,
                                                   classes=classes,
                                                   missing_label=missing_label,
                                                   metric="precomputed")

        if self.batch_mode == 'full':
            if self.nonmyopic_look_ahead > 1:
                raise NotImplementedError("batch_mode = 'full' can only be "
                                          "combined with "
                                          "nonmyopic_look_ahead = 1")
            cand_idx_set = np.array(list(itertools.permutations(range(len(
                X_cand)), batch_size)))

            batch_utilities = nonmyopic_gain(
                clf=self.clf,
                X_c=X_cand,
                cand_idx_set=cand_idx_set,
                X=X_,
                y=y_,
                sample_weight=sample_weight_,
                prob_estimator_cand=prob_estimator_cand,
                K_c_x=sim_c_x,
                K_c_c=sim_c_c,
                prob_estimator_eval=prob_estimator_eval,
                K_e_x=sim_e_x,
                K_e_c=sim_e_c,
                X_eval=X_eval,
                classes=classes,
                metric=metric,
                cost_matrix=cost_matrix,
                perf_func=perf_func,
                gain_mode='batch',
                nonmyopic_independence=self.nonmyopic_independence,
                all_sim_labels_equal=self.all_sim_labels_equal
            )

            utilities = np.full([batch_size, len(X_cand)], np.nan)
            tmp_utilities = np.nanmax(batch_utilities, axis=1)
            cur_best_idx = rand_argmax([tmp_utilities], axis=1,
                                           random_state=self.random_state)
            best_indices = cand_idx_set[cur_best_idx]

        elif self.batch_mode == 'greedy':
            for i_greedy in range(batch_size):
                utilities = np.full([batch_size, len(X_cand)], np.nan,
                                    dtype=float)
                best_indices = np.full([batch_size], np.nan, dtype=int)
                unlabeled_cand_idx = np.setdiff1d(np.arange(len(X_cand)),
                                                  best_indices)
                cand_idx_set = _get_nonmyopic_cand_set(
                    neighbors=self.nonmyopic_neighbors,
                    cand_idx=unlabeled_cand_idx,
                    sim_cand=sim_c_c[unlabeled_cand_idx][:,unlabeled_cand_idx],
                    M=self.nonmyopic_look_ahead)
                # concatenate new candidates to previous selection
                cand_idx_set = np.array([np.hstack([best_indices[:i_greedy],
                                                    c]) for c in cand_idx_set])
                tmp_utilities = nonmyopic_gain(
                    clf=self.clf,
                    X_c=X_cand,
                    cand_idx_set=cand_idx_set,
                    X=X_,
                    y=y_,
                    sample_weight=sample_weight_,
                    prob_estimator_cand=prob_estimator_cand,
                    K_c_x=sim_c_x,
                    K_c_c=sim_c_c,
                    prob_estimator_eval=prob_estimator_eval,
                    K_e_x=sim_e_x,
                    K_e_c=sim_e_c,
                    X_eval=X_eval,
                    classes=classes,
                    metric=metric,
                    cost_matrix=cost_matrix,
                    perf_func=perf_func,
                    gain_mode='nonmyopic',

                    nonmyopic_independence=self.nonmyopic_independence,
                    all_sim_labels_equal=self.all_sim_labels_equal
                )
                tmp_utilities = np.nanmax(tmp_utilities, axis=1)
                cur_best_idx = rand_argmax([tmp_utilities], axis=1,
                                           random_state=self.random_state)

                best_indices[i_greedy] = unlabeled_cand_idx[cur_best_idx]
                utilities[i_greedy, unlabeled_cand_idx] = tmp_utilities

        else:
            raise ValueError('batch_mode unknown')

        if return_utilities:
            return best_indices, utilities
        else:
            return best_indices

def _get_nonmyopic_cand_set(neighbors, cand_idx, sim_cand, M):
    if neighbors == 'same':
        cand_idx_set = np.tile(cand_idx, [M, 1]).T
    elif neighbors == 'nearest':
        # TODO check correctness
        cand_idx_set = (-sim_cand[cand_idx][:,cand_idx]).argsort(axis=1)[:,:M]
    else:
        raise ValueError('neighbor_mode unknown')
    return cand_idx_set

def nonmyopic_gain(clf, X_c, cand_idx_set, X, y, sample_weight,
                   prob_estimator_cand, K_c_x, K_c_c,
                   prob_estimator_eval, K_e_x, K_e_c,
                   X_eval, classes,
                   metric, cost_matrix, perf_func,
                   gain_mode='nonmyopic',
                   nonmyopic_independence=False,
                   all_sim_labels_equal=True):

    clf = clone(clf)
    clf.fit(X, y, sample_weight)
    if X_eval is None:
        pred_old_cand = clf.predict(X_c)
    else:
        pred_old_cand = clf.predict(X_eval)

    if sample_weight is None:
        sample_weight = np.ones(len(X))

    if gain_mode == 'nonmyopic':
        tmp_utilities = np.empty(cand_idx_set.shape)
    elif gain_mode == 'batch':
        tmp_utilities = np.empty([len(cand_idx_set), 1])

    if nonmyopic_independence:
        prob_estimator_cand.fit(X, y, sample_weight)
        prob_cand_X = prob_estimator_cand.predict_proba(K_c_x)
    else:
        # TODO: speed up
        pass

    y_sim_lists = [_get_y_sim_list(n_classes=len(classes),
                                   n_instances=n,
                                   all_sim_labels_equal=all_sim_labels_equal)
                   for n in range(1, cand_idx_set.shape[1]+1)]

    X_ = np.concatenate([X_c, X], axis=0)
    K_c_cx_ = np.concatenate([K_c_c, K_c_x], axis=1)
    K_e_cx_ = np.concatenate([K_e_c, K_e_x], axis=1)
    sample_weight_ = np.concatenate([np.ones(len(X_c)), sample_weight])

    idx_lbld = np.arange(len(X_c), len(X_c)+len(X))
    append_lbld = lambda x : np.concatenate([x, idx_lbld])

    decomposable = (metric == 'misclassification-loss')

    for i_org_cand_idx, org_cand_idx in enumerate(cand_idx_set):
        org_cand_idx = list(org_cand_idx)
        if gain_mode == 'nonmyopic':
            cand_idx_subsets = [org_cand_idx[:(i+1)] for i in range(len(
                org_cand_idx))]
        elif gain_mode == 'batch':
            cand_idx_subsets = [org_cand_idx]

        for i_cand_idx, cand_idx in enumerate(cand_idx_subsets):
            idx_new = append_lbld(cand_idx)
            X_new = X_[idx_new]
            if X_eval is None:
                K_new = K_e_cx_[cand_idx,:][:, idx_new]
            else:
                K_new = K_e_cx_[:, idx_new]
            sample_weight_new = sample_weight_[idx_new]

            y_sim_list = y_sim_lists[len(cand_idx)-1]

            if nonmyopic_independence:
                prob_cand_y = prob_cand_X[cand_idx, :]
                prob_y_sim = np.prod(prob_cand_y[range(len(cand_idx)),
                                                 y_sim_list], axis=1)
            else:
                prob_y_sim = dependent_cand_prob(X_c, cand_idx, y_sim_list,
                                            X, y, sample_weight,
                                            prob_estimator_cand, K_c_x, K_c_c,
                                            nonmyopic_independence)


            tmp_utilities[i_org_cand_idx, i_cand_idx] = 0
            for i_y_sim, y_sim in enumerate(y_sim_list):
                y_new = np.concatenate([y_sim, y], axis=0)

                prob_estimator_eval.fit(X_new, y_new, sample_weight_new)
                prob_eval = prob_estimator_eval.predict_proba(K_new)

                new_clf = clf.fit(X_new, y_new, sample_weight_new)
                if X_eval is None:
                    pred_new = new_clf.predict(X_c[cand_idx])
                    pred_old = pred_old_cand[cand_idx]
                else:
                    pred_new = new_clf.predict(X_eval)
                    pred_old = pred_old_cand

                tmp_utilities[i_org_cand_idx, i_cand_idx] += \
                    _dperf(prob_eval, pred_old, pred_new,
                           decomposable=decomposable, cost_matrix=cost_matrix,
                           perf_func=perf_func) \
                    * prob_y_sim[i_y_sim]

        if gain_mode == 'nonmyopic':
            tmp_utilities /= np.arange(1, tmp_utilities.shape[1] + 1).reshape(
                1,-1)
    return tmp_utilities

def dependent_cand_prob(X_c, cand_idx, y_sim_list,
                       X, y, sample_weight,
                       prob_estimator, K_c_x, K_c_c,):
    # TODO: Speed Up (eg concatenate) - besser große kernelmatrix und
    #  dann indizieren
    prob_y_sim = np.ones(len(y_sim_list))
    for i_y_sim, y_sim in enumerate(y_sim_list):
        for i_y in range(len(y_sim)):
            X_new = np.concatenate([X, X_c[cand_idx[0:i_y]]],
                                   axis=0)
            y_new = np.concatenate([y, y_sim[0:i_y]], axis=0)
            sample_weight_new = np.concatenate([sample_weight, np.ones(
                i_y)], axis=0)
            prob_estimator.fit(X_new, y_new, sample_weight_new)

            K_c_cx = np.concatenate([K_c_x[cand_idx[i_y:i_y + 1], :],
                                     K_c_c[cand_idx[i_y:i_y + 1], :]
                                          [:, cand_idx[0:i_y]]
                                    ],
                                    axis=1)
            prob_cand_y = prob_estimator.predict_proba(K_c_cx)
            prob_y_sim[i_y_sim] *= prob_cand_y[0][y_sim[i_y]]
    return prob_y_sim

def _get_y_sim_list(n_classes, n_instances, all_sim_labels_equal=True):
    if all_sim_labels_equal:
        return np.tile(np.arange(n_classes), [n_instances, 1]).T
    else:
        return list(itertools.product(*([range(n_classes)] * n_instances)))


def _transform_metric(metric, cost_matrix, cost_vector, perf_func, n_classes):
    if metric == 'error':
        metric = 'misclassification-loss'
        cost_matrix = 1 - np.eye(n_classes)
        perf_func = None
    elif metric == 'cost-vector':
        if cost_vector is None or cost_vector.shape != (n_classes):
            raise ValueError("For metric='cost-vector', the argument "
                             "'cost_vector' must be given when initialized and "
                             "must have shape (n_classes)")
        metric = 'misclassification-loss'
        cost_matrix = cost_vector.reshape(-1, 1) \
                      @ np.ones([1, n_classes])
        np.fill_diagonal(cost_matrix, 0)
        perf_func = None
    elif metric == 'misclassification-loss':
        if cost_matrix is None:
            raise ValueError("'cost_matrix' cannot be None for "
                             "metric='misclasification-loss'")
        check_cost_matrix(cost_matrix, n_classes)
        metric = 'misclassification-loss'
        cost_matrix = cost_matrix
        perf_func = None
    elif metric == 'mean-abs-error':
        metric = 'misclassification-loss'
        row_matrix = np.arange(n_classes).reshape(-1, 1) \
                     @ np.ones([1, n_classes])
        cost_matrix = abs(row_matrix - row_matrix.T)
        perf_func = None
    elif metric == 'macro-accuracy':
        metric = 'custom'
        perf_func = macro_accuracy_func
        cost_matrix = None
    elif metric == 'f1-score':
        metric = 'custom'
        perf_func = f1_score_func
        cost_matrix = None
    elif metric == 'cohens-kappa':
        # TODO: implement
        metric = 'custom'
        perf_func = perf_func
        cost_matrix = None
    else:
        raise ValueError("Metric '{}' not implemented. Use "
                         "metric='custom' instead.".format(metric))
    return metric, cost_matrix, perf_func

def _dperf(probs, pred_old, pred_new, decomposable, cost_matrix=None,
           perf_func=None):
    if decomposable:
        # TODO: check if cost_matrix is correct
        pred_changed = (pred_new != pred_old)
        return np.sum(probs[pred_changed, :] *
                      (cost_matrix.T[pred_old[pred_changed]] -
                       cost_matrix.T[pred_new[pred_changed]])) / \
               len(probs)
    else:
        # TODO: check if perf_func is correct
        n_classes = probs.shape[1]
        conf_mat_old = np.zeros([n_classes, n_classes])
        conf_mat_new = np.zeros([n_classes, n_classes])
        for y_pred in range(n_classes):
            conf_mat_old[:, y_pred] += np.sum(probs[pred_old == y_pred], axis=0)
            conf_mat_new[:, y_pred] += np.sum(probs[pred_new == y_pred], axis=0)
        return perf_func(conf_mat_new) - perf_func(conf_mat_old)

def estimate_bandwidth(n_samples, n_features):
    nominator = 2 * n_samples * n_features
    denominator = (n_samples - 1) * np.log((n_samples - 1) / ((np.sqrt(2) * 10 ** -6) ** 2))
    bandwidth = np.sqrt(nominator / denominator)
    return bandwidth

def score_recall(conf_matrix):
    return conf_matrix[-1, -1] / conf_matrix[-1, :].sum()


def macro_accuracy_func(conf_matrix):
    return np.mean(conf_matrix.diagonal() / conf_matrix.sum(axis=1))


def score_accuracy(conf_matrix):
    return conf_matrix.diagonal().sum() / conf_matrix.sum()


def score_precision(conf_matrix):
    pos_pred = conf_matrix[:, -1].sum()
    return conf_matrix[-1, -1] / pos_pred if pos_pred > 0 else 0


def f1_score_func(conf_matrix):
    recall = score_recall(conf_matrix)
    precision = score_precision(conf_matrix)
    norm = recall + precision
    return 2 * recall * precision / norm if norm > 0 else 0


def calculate_optimal_prior(cost_matrix=None):
    n_classes = len(cost_matrix)
    if cost_matrix is None:
        return np.full([n_classes], 1. / n_classes)
    else:
        M = np.ones([1, len(cost_matrix)]) @ np.linalg.inv(cost_matrix)
        if np.all(M[0] >= 0):
            return M[0] / np.sum(M)
        else:
            return np.full([n_classes], 1. / n_classes)


def _cost_reduction(k_vec_list, C=None, m_max=2, prior=1.e-3):
    """Calculate the expected cost reduction.

    Calculate the expected cost reduction for given maximum number of
    hypothetically acquired labels, observed labels and cost matrix.

    Parameters
    ----------
    k_vec_list: array-like, shape (n_classes)
        Observed class labels.
    C: array-like, shape = (n_classes, n_classes)
        Cost matrix.
    m_max: int
        Maximal number of hypothetically acquired labels.
    prior : float | array-like, shape (n_classes)
       Prior value for each class.

    Returns
    -------
    expected_cost_reduction: array-like, shape (n_samples)
        Expected cost reduction for given parameters.
    """
    n_classes = len(k_vec_list[0])
    n_samples = len(k_vec_list)

    # check cost matrix
    C = 1 - np.eye(n_classes) if C is None else np.asarray(C)

    # generate labelling vectors for all possible m values
    l_vec_list = np.vstack([_gen_l_vec_list(m, n_classes)
                            for m in range(m_max + 1)])
    m_list = np.sum(l_vec_list, axis=1)
    n_l_vecs = len(l_vec_list)

    # compute optimal cost-sensitive decision for all combination of k-vectors
    # and l-vectors
    k_l_vec_list = np.swapaxes(np.tile(k_vec_list, (n_l_vecs, 1, 1)), 0,
                               1) + l_vec_list
    y_hats = np.argmin(k_l_vec_list @ C, axis=2)

    # add prior to k-vectors
    prior = prior * np.ones(n_classes)
    k_vec_list = np.asarray(k_vec_list) + prior

    # all combination of k-, l-, and prediction indicator vectors
    combs = [k_vec_list, l_vec_list, np.eye(n_classes)]
    combs = np.asarray([list(elem)
                        for elem in list(itertools.product(*combs))])

    # three factors of the closed form solution
    factor_1 = 1 / euler_beta(k_vec_list)
    factor_2 = multinomial(l_vec_list)
    factor_3 = euler_beta(np.sum(combs, axis=1)).reshape(n_samples, n_l_vecs,
                                                         n_classes)

    # expected classification cost for each m
    m_sums = np.asarray(
        [factor_1[k_idx]
         * np.bincount(m_list, factor_2 * [C[:, y_hats[k_idx, l_idx]]
                                           @ factor_3[k_idx, l_idx]
                                           for l_idx in range(n_l_vecs)])
         for k_idx in range(n_samples)]
    )

    # compute classification cost reduction as difference
    gains = np.zeros((n_samples, m_max)) + m_sums[:, 0].reshape(-1, 1)
    gains -= m_sums[:, 1:]

    # normalize  cost reduction by number of hypothetical label acquisitions
    gains /= np.arange(1, m_max + 1)

    return np.max(gains, axis=1)


def _gen_l_vec_list(m_approx, n_classes):
    """
    Creates all possible class labeling vectors for given number of
    hypothetically acquired labels and given number of classes.

    Parameters
    ----------
    m_approx: int
        Number of hypothetically acquired labels..
    n_classes: int,
        Number of classes

    Returns
    -------
    label_vec_list: array-like, shape = [n_labelings, n_classes]
        All possible class labelings for given parameters.
    """

    label_vec_list = [[]]
    label_vec_res = np.arange(m_approx + 1)
    for i in range(n_classes - 1):
        new_label_vec_list = []
        for labelVec in label_vec_list:
            for newLabel in label_vec_res[label_vec_res
                                          - (m_approx - sum(labelVec))
                                          <= 1.e-10]:
                new_label_vec_list.append(labelVec + [newLabel])
        label_vec_list = new_label_vec_list

    new_label_vec_list = []
    for labelVec in label_vec_list:
        new_label_vec_list.append(labelVec + [m_approx - sum(labelVec)])
    label_vec_list = np.array(new_label_vec_list, int)

    return label_vec_list


def euler_beta(a):
    """
    Represents Euler beta function:
    B(a(i)) = Gamma(a(i,1))*...*Gamma(a_n)/Gamma(a(i,1)+...+a(i,n))

    Parameters
    ----------
    a: array-like, shape (m, n)
        Vectors to evaluated.

    Returns
    -------
    result: array-like, shape (m)
        Euler beta function results [B(a(0)), ..., B(a(m))
    """
    return np.exp(np.sum(gammaln(a), axis=1) - gammaln(np.sum(a, axis=1)))


def multinomial(a):
    """
    Computes Multinomial coefficient:
    Mult(a(i)) = (a(i,1)+...+a(i,n))!/(a(i,1)!...a(i,n)!)

    Parameters
    ----------
    a: array-like, shape (m, n)
        Vectors to evaluated.

    Returns
    -------
    result: array-like, shape (m)
        Multinomial coefficients [Mult(a(0)), ..., Mult(a(m))
    """
    return factorial(np.sum(a, axis=1)) / np.prod(factorial(a), axis=1)
