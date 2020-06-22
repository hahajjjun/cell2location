# -*- coding: utf-8 -*-
"""Co-located cell combination model - de-novo factorisation of cell type density using sklearn NMF."""

import matplotlib
import matplotlib.pyplot as plt
# +
import numpy as np
import pandas as pd

from cell2location.models.base_model import BaseModel


# defining the model itself
class CoLocatedCombination_sklearnNMF(BaseModel):
    r""" Co-located cell combination model - de-novo factorisation of cell type density using sklearn NMF.

    This model takes the absolute cell density inferred by CoLocationModelNB4V2 as input
    to non-negative matrix factorisation to identify co-occuring cell type combinations or 'microenvironments'.

    If you want to find the most disctinct cell type combinations, use a small number of factors.

    If you want to find very strong co-location signal and assume that most cell types are on their own,
    use a lot of factors (> 30).

    To perform this analysis we initialise the model and train it several times to evaluate consitency.
    This class wraps around scikit-learn NMF to perform training, visualisation, export of the results.

    .. Note:: factors are exchangeable so while you find factors with consistent cell type composition,
      every time you train the model you get those factors in a different order.

    This analysis is most revealing for tissues (such as lymph node) and cell types (such as glial cells)
    where signals between cell types mediate their location patterns.
    In the mouse brain locations of neurones are determined during development
    so most neurones stand alone in their location pattern.

    Density :math:`w_{sf}` of each cell type `f` across locations `s` is modelled as an additive function of
    the cell combinations (micro-environments) `r`. This means the density of one cell type in one location can
    be explained by 2 distinct combinations `r`.

    Cell type density is therefore a function of the following non-negative components:

    .. math::
        w_{sf} = \sum_{r} ({i_{sr} \: k_{rf} \: m_{f}})

    Components
      * :math:`k_{rf}` represents the proportion of cells of each type (regulatory programmes) `f` that correspond to each
        co-located combination `r`, normalised for total abundance of each cell type :math:`m_{f}`.
      * :math:`m_{f}` cell type budget accounts for the difference in abundance between cell types,
        thus focusing the interpretation of :math:`k_{rf}` on cell co-location.
      * :math:`i_{sr}` is proportional to the number of cells from each neighbourhood `r` in each location `s`,
        and shows the abundance of combinations `r` in locations `s`.

    In practice :math:`q_{rf} = k_{rf} \: m_{f}` is obtained from scikit-learn NMF and normalised by the sum across
    combinations `r` to obtain :math:`k_{rf}`:

    .. math::
        k_{rf} = q_{rf} / (\sum_{r} q_{rf})

    .. Note:: So, the model reports the proportion of cells of each type that belong to each combination
      (parameter called 'cell_type_fractions').
      For example, 81% of Astro_2 are found in fact_28. This way we are not biased by the absolute abundance of each cell type.


    :param n_fact: Maximum number of cell type (regulatory programmes) combinations
    :param X_data: Numpy array of the cell abundance (cols) in locations (rows)
    :param n_iter: number of training iterations
    :param verbose, var_names, var_names_read, obs_names, fact_names, sample_id: See parent class BaseModel for details.
    :param init, random_state, alpha, l1_ratio: arguments for sklearn.decomposition.NMF with sensible defaults
        see help(sklearn.decomposition.NMF) for more details
    :param nmf_kwd_args: dictionary with more keyword arguments for sklearn.decomposition.NMF
    """

    def __init__(
            self,
            n_fact: int,
            X_data: np.ndarray,
            n_iter=10000,
            verbose=True,
            var_names=None, var_names_read=None,
            obs_names=None, fact_names=None, sample_id=None,
            init='random', random_state=0, alpha=0.1, l1_ratio=0.5,
            nmf_kwd_args={}
    ):

        ############# Initialise parameters ################
        super().__init__(X_data, n_fact,
                         0, n_iter,
                         0, 0,
                         verbose, var_names, var_names_read,
                         obs_names, fact_names, sample_id)

        self.location_factors_df = None
        self.X_data_sample = None

        self.init = init
        self.random_state = random_state
        np.random.seed(random_state)
        self.alpha = alpha
        self.l1_ratio = l1_ratio
        self.nmf_kwd_args = nmf_kwd_args

    def fit(self, n=3, n_type='restart'):
        r"""Find parameters using sklearn.decomposition.NMF, optionally restart several times,
            and export parameters to self.samples['post_sample_means']
        :param n: number of independent initialisations
        :param n_type: type of repeated initialisation: 
                                  'restart' to pick different initial value,
                                  'cv' for molecular cross-validation - splits counts into n datasets, 
                                         for now, only n=2 is implemented
                                  'bootstrap' for fitting the model to multiple downsampled datasets. 
                                         Run `mod.bootstrap_data()` to generate variants of data
        :return: exported parameters in self.samples['post_sample_means'] 
        """

        self.models = {}
        self.results = {}
        self.samples = {}

        self.n_type = n_type

        if np.isin(n_type, ['bootstrap']):
            if self.X_data_sample is None:
                self.bootstrap_data(n=n)
        elif np.isin(n_type, ['cv']):
            if self.X_data_sample is None:
                self.generate_cv_data()  # cv data added to self.X_data_sample

        init_names = ['init_' + str(i + 1) for i in np.arange(n)]

        for i, name in enumerate(init_names):

            # when type is molecular cross-validation or bootstrap, 
            # replace self.x_data with new data
            if np.isin(n_type, ['cv', 'bootstrap']):
                self.x_data = self.X_data_sample[i]
            else:
                self.x_data = self.X_data

            from sklearn.decomposition import NMF
            self.models[name] = NMF(n_components=self.n_fact, init=self.init,
                                    alpha=self.alpha, l1_ratio=self.l1_ratio,
                                    max_iter=self.n_iter, **self.nmf_kwd_args)
            W = self.models[name].fit_transform(self.x_data)
            H = self.models[name].components_
            self.results[name] = {'post_sample_means': {'location_factors': W,
                                                        'cell_type_factors': H.T,
                                                        'nUMI_factors': (W * H.T.sum(0))},
                                  'post_sample_sds': None,
                                  'post_sample_q05': None, 'post_sample_q95': None}
            self.samples = self.results[name]

            # plot training history
            if self.verbose:
                print(name + ' - iterations until convergence: ' + str(self.models[name].n_iter_));

    def evaluate_stability(self, node_name, align=True):
        r"""Evaluate stability of the solution between training initialisations
            (correlates the values of factors between training initialisations)
        :param node_name: name of the parameter to evaluate, see `self.samples['post_sample_means'].keys()`  
                        Factors should be in columns.
        :param align: boolean, match factors between training restarts using linear_sum_assignment?
        :return: plots comparing all training initialisations to initialisation 1. 
        """

        for i in range(len(self.results.keys()) - 1):
            print(self.align_plot_stability(self.results['init_' + str(1)]['post_sample_means'][node_name],
                                            self.results['init_' + str(i + 2)]['post_sample_means'][node_name],
                                            str(1), str(i + 2), align=align))

    def compute_expected(self):
        r""" Compute expected abundance of each cell type in each location.
        """

        # compute the poisson rate
        self.mu = np.dot(self.samples['post_sample_means']['location_factors'],
                         self.samples['post_sample_means']['cell_type_factors'].T)

    def compute_expected_fact(self, fact_ind=None):
        r"""Compute expected abundance of each cell type in each location
            that comes from a subset of factors. E.g. expressed factors in self.fact_filt
        """

        if fact_ind is None:
            fact_ind = self.fact_filt

        # compute the poisson rate
        self.mu = np.dot(self.samples['post_sample_means']['location_factors'][:, fact_ind],
                         self.samples['post_sample_means']['cell_type_factors'].T[fact_ind, :])

    def plot_posterior_mu_vs_data(self, mu_node_name='mu', data_node='X_data'):
        r""" Plot expected value (of cell density) of the model against observed input data:
        2D histogram, where each point is each point in the input data matrix

        :param mu_node_name: name of the object slot containing expected value
        :param data_node: name of the object slot containing data
        """

        if type(mu_node_name) is str:
            mu = getattr(self, mu_node_name)
        else:
            mu = mu_node_name

        if type(data_node) is str:
            data_node = getattr(self, data_node)

        plt.hist2d(data_node.flatten(),
                   mu.flatten(),
                   bins=50, norm=matplotlib.colors.LogNorm())
        plt.xlabel('Data, values')
        plt.ylabel('Posterior sample, values')
        plt.title('UMI counts (all spots, all genes)')
        plt.tight_layout()

    def sample2df(self, node_name='nUMI_factors',
                  ct_node_name='cell_type_factors'):
        r""" Export cell combinations and their profile across locations as Pandas data frames.

        :param node_name: name of the location loading model parameter to be exported
        :param ct_node_name: name of the cell_type loadings model parameter to be exported
        :return: 8 Pandas dataframes added to model object:
                 .cell_type_loadings, .cell_factors_sd, .cell_factors_q05, .cell_factors_q95
                 .gene_loadings, .gene_loadings_sd, .gene_loadings_q05, .gene_loadings_q95
        """

        # export location factors
        self.location_factors_df = \
            pd.DataFrame.from_records(self.samples['post_sample_means'][node_name],
                                      index=self.obs_names,
                                      columns=['mean_' + node_name + i for i in self.fact_names])

        self.cell_type_loadings = \
            pd.DataFrame.from_records(self.samples['post_sample_means'][ct_node_name],
                                      index=self.var_names,
                                      columns=['mean_' + ct_node_name + i for i in self.fact_names])

        self.cell_type_fractions = (self.cell_type_loadings.T / self.cell_type_loadings.sum(1)).T

        self.cell_type_loadings_sd = None
        self.cell_type_loadings_q05 = None
        self.cell_type_loadings_q95 = None


    def annotate_adata(self, adata):
        r""" Add location loadings to anndata.obs

        :param adata: anndata object to annotate
        :return: updated anndata object
        """

        if self.location_factors_df is None:
            self.sample2df()

        # location factors
        # add location factors to adata
        adata.obs[self.location_factors_df.columns] = self.location_factors_df.loc[adata.obs.index, :]

        return (adata)
