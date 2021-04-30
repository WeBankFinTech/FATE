#!/usr/bin/env python
# -*- coding: utf-8 -*-

#
#  Copyright 2019 The FATE Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
################################################################################
#
#
################################################################################

# =============================================================================
# FeatureHistogram
# =============================================================================
import copy
import functools
import numpy as np
from operator import add, sub
import scipy.sparse as sp
import uuid
from typing import List
from fate_arch.session import computing_session as session
from fate_arch.common import log
from federatedml.feature.fate_element_type import NoneType
from federatedml.framework.weights import Weights
from federatedml.secureprotol.iterative_affine import DeterministicIterativeAffineCiphertext

LOGGER = log.getLogger()


class HistogramBag(object):

    """
    holds histograms
    """

    def __init__(self, tensor: list, hid: int = -1, p_hid: int = -1):

        """
        :param tensor: list returned by calculate_histogram
        :param hid: histogram id
        :param p_hid: parent node histogram id
        """

        self.hid = hid
        self.p_hid = p_hid
        self.bag = tensor

    def binary_op(self, other, func, inplace=False):

        assert isinstance(other, HistogramBag)
        assert len(self.bag) == len(other)

        bag = self.bag
        newbag = None
        if not inplace:
            newbag = copy.deepcopy(other)
            bag = newbag.bag

        for bag_idx in range(len(self.bag)):
            for hist_idx in range(len(self.bag[bag_idx])):
                bag[bag_idx][hist_idx][0] = func(self.bag[bag_idx][hist_idx][0], other[bag_idx][hist_idx][0])
                bag[bag_idx][hist_idx][1] = func(self.bag[bag_idx][hist_idx][1], other[bag_idx][hist_idx][1])
                bag[bag_idx][hist_idx][2] = func(self.bag[bag_idx][hist_idx][2], other[bag_idx][hist_idx][2])

        return self if inplace else newbag

    def __add__(self, other):
        return self.binary_op(other, add, inplace=False)

    def __sub__(self, other):
        return self.binary_op(other, sub, inplace=False)

    def __len__(self):
        return len(self.bag)

    def __getitem__(self, item):
        return self.bag[item]

    def __str__(self):
        return str(self.bag)

    def __repr__(self):
        return str(self.bag)


class FeatureHistogramWeights(Weights):

    def __init__(self, list_of_histogram_bags: List[HistogramBag]):

        self.hists = list_of_histogram_bags
        super(FeatureHistogramWeights, self).__init__(l=list_of_histogram_bags)

    def map_values(self, func, inplace):

        if inplace:
            hists = self.hists
        else:
            hists = copy.deepcopy(self.hists)

        for histbag in hists:
            bag = histbag.bag
            for component_idx in range(len(bag)):
                for hist_idx in range(len(bag[component_idx])):
                    bag[component_idx][hist_idx][0] = func(bag[component_idx][hist_idx][0])
                    bag[component_idx][hist_idx][1] = func(bag[component_idx][hist_idx][1])
                    bag[component_idx][hist_idx][2] = func(bag[component_idx][hist_idx][2])

        if inplace:
            return self
        else:
            return FeatureHistogramWeights(list_of_histogram_bags=hists)

    def binary_op(self, other: 'FeatureHistogramWeights', func, inplace: bool):

        new_weights = []
        hists, other_hists = self.hists, other.hists
        for h1, h2 in zip(hists, other_hists):
            rnt = h1.binary_op(h2, func, inplace=inplace)
            if not inplace:
                new_weights.append(rnt)

        if inplace:
            return self
        else:
            return FeatureHistogramWeights(new_weights)

    def axpy(self, a, y: 'FeatureHistogramWeights'):

        func = lambda x1, x2: x1 + a * x2
        self.binary_op(y, func, inplace=True)

        return self

    def __iter__(self):
        pass

    def __str__(self):
        return str([str(hist) for hist in self.hists])

    def __repr__(self):
        return str(self.hists)


class FeatureHistogram(object):

    def __init__(self):

        self._cur_to_split_node_info = {}
        self._prev_layer_cached_histograms = {}
        self._cur_layer_cached_histograms = {}
        self._cur_dep = -1
        self._prev_layer_dtable = None
        self._cur_layer_dtables = [None]
        self.stable_reduce = False

    """
    Public Interface for Histogram Computation
    """

    def compute_histogram(self, dep, data_bin, grad_and_hess, bin_split_points, bin_sparse_points,
                          valid_features, node_map,
                          node_sample_count,
                          use_missing=False,
                          zero_as_missing=False,
                          ret="tensor",
                          sparse_optimization=False,
                          hist_sub=True,
                          cur_to_split_nodes=None,
                          bin_num=32
                          ):

        """
        This the new interface for histogram computation
        """

        if hist_sub:

            # if run histogram subtraction, need to trim node map, and get parent/sibling node info for computation
            LOGGER.info('get histogram using histogram subtraction')
            self._update_node_info(cur_to_split_nodes)
            to_compute_node_map, sibling_node_id_map = self._trim_node_map(node_map, node_sample_count)
            parent_node_id_map = self._get_parent_nid_map()
            LOGGER.debug('histogram subtraction at dep {}, new node map is {}, sibling node map is {}, '
                         'cur to split node info is {}, parent node id map is {}'.
                         format(dep, to_compute_node_map, sibling_node_id_map, self._cur_to_split_node_info,
                                parent_node_id_map))
        else:
            # else use original node map
            to_compute_node_map = node_map
            sibling_node_id_map = None
            parent_node_id_map = None

        if ret == 'tensor':

            histograms = self.calculate_histogram(data_bin, grad_and_hess,
                                                  bin_split_points, bin_sparse_points,
                                                  valid_features, to_compute_node_map,
                                                  use_missing, zero_as_missing, ret=ret)

            if not hist_sub:
                return histograms

            # running hist sub
            self._update_cached_histograms(dep, ret=ret)
            if self._is_root_node(node_map):  # root node need no hist sub
                self._cur_layer_cached_histograms[0] = histograms[0]
                result = histograms
            else:
                node_id_list, result = self._tensor_subtraction(histograms, to_compute_node_map)
                self._cached_histograms((node_id_list, result), ret=ret)
            return result

        elif ret == 'tb':

            LOGGER.debug('maps are {} {}'.format(parent_node_id_map, sibling_node_id_map))

            if not sparse_optimization:
                LOGGER.info('computing histogram table using normal mode')
                histogram_table = self.calculate_histogram(data_bin, grad_and_hess,
                                                           bin_split_points, bin_sparse_points,
                                                           valid_features, to_compute_node_map,
                                                           use_missing, zero_as_missing,
                                                           ret=ret,
                                                           parent_node_id_map=parent_node_id_map,
                                                           sibling_node_id_map=sibling_node_id_map)
            else:  # go to sparse optimization codes
                LOGGER.info('computing histogram table using sparse optimization')
                histogram_table = self.calculate_histogram_sp_opt(data_bin=data_bin,
                                                                  grad_and_hess=grad_and_hess,
                                                                  bin_split_points=bin_split_points,
                                                                  cipher_split_num=14,
                                                                  node_map=to_compute_node_map,
                                                                  bin_num=bin_num,
                                                                  valid_features=valid_features,
                                                                  use_missing=use_missing,
                                                                  zero_as_missing=zero_as_missing,
                                                                  parent_node_id_map=parent_node_id_map,
                                                                  sibling_node_id_map=sibling_node_id_map
                                                                  )

            if not hist_sub:
                return histogram_table

            # running hist sub
            self._update_cached_histograms(dep, ret=ret)
            if self._is_root_node(node_map):  # root node need not hist sub
                self._cur_layer_dtables.append(histogram_table)
                result = histogram_table
            else:
                result = self._table_subtraction(histogram_table)
                self._cached_histograms(result, ret=ret)
            return result

    def calculate_histogram(self, data_bin, grad_and_hess,
                            bin_split_points, bin_sparse_points,
                            valid_features=None,
                            node_map=None,
                            use_missing=False,
                            zero_as_missing=False,
                            parent_node_id_map=None,
                            sibling_node_id_map=None,
                            ret="tensor"):

        """
        This is the old interface for histogram computation

        data_bin: data after binning with node positions
        grad_and_hess: g/h for each sample
        bin_split_points: split points
        bin_sparse_points: sparse points
        node_map: node id to node index
        use_missing: enable use missing
        zero_as_missing: enable zero as missing
        parent_node_id_map: map current node_id to its parent id, this para is for hist sub
        sibling_node_id_map: map current node_id to its sibling id, this para is for hist sub
        ret: return type, if 'tb', return histograms stored in DTable
        """

        LOGGER.debug("bin_shape is {}, node num is {}".format(bin_split_points.shape, len(node_map)))

        # reformat, now format is: key, ((data_instance, node position), (g, h))
        batch_histogram_intermediate_rs = data_bin.join(grad_and_hess, lambda data_inst, g_h: (data_inst, g_h))

        if batch_histogram_intermediate_rs.count() == 0: # if input sample number is 0, return empty histograms

            node_histograms = FeatureHistogram._generate_histogram_template(node_map, bin_split_points, valid_features,
                                                                            1 if use_missing else 0)
            hist_list = FeatureHistogram._generate_histogram_key_value_list(node_histograms, node_map, bin_split_points,
                                                                            parent_node_id_map=parent_node_id_map,
                                                                            sibling_node_id_map=sibling_node_id_map)

            if ret == 'tensor':
                feature_num = bin_split_points.shape[0]
                return FeatureHistogram._recombine_histograms(hist_list, node_map, feature_num)
            else:
                histograms_table = session.parallelize(hist_list, partition=data_bin.partitions, include_key=True)
                return FeatureHistogram._construct_table(histograms_table)

        else:  # compute histograms

            batch_histogram_cal = functools.partial(
                FeatureHistogram._batch_calculate_histogram,
                bin_split_points=bin_split_points, bin_sparse_points=bin_sparse_points,
                valid_features=valid_features, node_map=node_map,
                use_missing=use_missing, zero_as_missing=zero_as_missing,
                parent_nid_map=parent_node_id_map,
                sibling_node_id_map=sibling_node_id_map,
                stable_reduce=self.stable_reduce
            )

            agg_func = self._stable_hist_aggregate if self.stable_reduce else self._hist_aggregate
            histograms_table = batch_histogram_intermediate_rs.mapReducePartitions(batch_histogram_cal, agg_func)
            if self.stable_reduce:
                histograms_table = histograms_table.mapValues(self._stable_hist_reduce)

            if ret == "tensor":
                feature_num = bin_split_points.shape[0]
                histogram_list = list(histograms_table.collect())
                rs = FeatureHistogram._recombine_histograms(histogram_list, node_map, feature_num)
                return rs
            else:
                return FeatureHistogram._construct_table(histograms_table)

    """
    Histogram computation functions
    """

    @staticmethod
    def _tensor_histogram_cumsum(histograms):
        # histogram cumsum, from left to right
        for i in range(1, len(histograms)):
            for j in range(len(histograms[i])):
                histograms[i][j] += histograms[i - 1][j]

        return histograms

    @staticmethod
    def _dtable_histogram_cumsum(histograms):

        # histogram cumsum, from left to right
        if len(histograms) == 0:
            return histograms

        new_hist = [[0, 0, 0] for i in range(len(histograms))]
        new_hist[0][0] = copy.deepcopy(histograms[0][0])
        new_hist[0][1] = copy.deepcopy(histograms[0][1])
        new_hist[0][2] = copy.deepcopy(histograms[0][2])

        for i in range(1, len(histograms)):
            # ciphertext cumsum skipping
            if histograms[i][2] == 0:
                new_hist[i] = new_hist[i - 1]
                LOGGER.debug('skipping')
                continue

            for j in range(len(histograms[i])):
                new_hist[i][j] = new_hist[i - 1][j] + histograms[i][j]

        return new_hist

    @staticmethod
    def _host_histogram_cumsum_map_func(v):

        fid, histograms = v
        new_value = (fid, FeatureHistogram._dtable_histogram_cumsum(histograms))
        return new_value

    @staticmethod
    def _hist_aggregate(fid_histogram1, fid_histogram2):
        # add histograms with same key((node id, feature id)) together
        fid_1, histogram1 = fid_histogram1
        fid_2, histogram2 = fid_histogram2
        aggregated_res = [[] for i in range(len(histogram1))]
        for i in range(len(histogram1)):
            for j in range(len(histogram1[i])):
                aggregated_res[i].append(histogram1[i][j] + histogram2[i][j])

        return fid_1, aggregated_res

    @staticmethod
    def _stable_hist_aggregate(fid_histogram1, fid_histogram2):

        partition_id_list_1, hist_val_list_1 = fid_histogram1
        partition_id_list_2, hist_val_list_2 = fid_histogram2
        value = [partition_id_list_1+partition_id_list_2, hist_val_list_1+hist_val_list_2]
        return value

    @staticmethod
    def _stable_hist_reduce(value):

        # [partition1, partition2, ...], [(fid, hist), (fid, hist) .... ]
        partition_id_list, hist_list = value
        order = np.argsort(partition_id_list)
        aggregated_hist = None
        for idx in order:  # make sure reduce in order to avoid float error
            hist = hist_list[idx]
            if aggregated_hist is None:
                aggregated_hist = hist
                continue
            aggregated_hist = FeatureHistogram._hist_aggregate(aggregated_hist, hist)
        return aggregated_hist

    @staticmethod
    def _generate_histogram_template(node_map: dict, bin_split_points: np.ndarray, valid_features: dict,
                                     missing_bin):

        # for every feature, generate histograms containers (initialized val are 0s)
        node_num = len(node_map)
        node_histograms = []
        for k in range(node_num):
            feature_histogram_template = []
            for fid in range(bin_split_points.shape[0]):
                # if is not valid features, skip generating
                if valid_features is not None and valid_features[fid] is False:
                    feature_histogram_template.append([])
                    continue
                else:
                    # 0, 0, 0 -> grad, hess, sample count
                    feature_histogram_template.append([[0, 0, 0]
                                                       for j in
                                                       range(bin_split_points[fid].shape[0] + missing_bin)])

            node_histograms.append(feature_histogram_template)
            # check feature num
            assert len(feature_histogram_template) == bin_split_points.shape[0]

        return node_histograms

    @staticmethod
    def _generate_histogram_key_value_list(node_histograms, node_map, bin_split_points, parent_node_id_map,
                                           sibling_node_id_map, partition_key=None):

        # generate key_value hist list for DTable parallelization
        ret = []
        inverse_map = FeatureHistogram._inverse_node_map(node_map)
        for node_idx in range(len(node_map)):
            for fid in range(bin_split_points.shape[0]):
                # key: (nid, fid), value: (fid, hist)
                # if parent_nid is offered, map nid to its parent nid for histogram subtraction
                node_id = inverse_map[node_idx]
                key = (parent_node_id_map[node_id], fid) if parent_node_id_map is not None else (node_id, fid)
                # if sibling_node_id_map is offered, recorded its sibling ids for histogram subtraction
                value = (fid, node_histograms[node_idx][fid]) if sibling_node_id_map is None else \
                    ((fid, node_id, sibling_node_id_map[node_id]), node_histograms[node_idx][fid])
                if partition_key is not None:
                    value = [[partition_key], [value]]
                ret.append((key, value))

        return ret

    @staticmethod
    def _batch_calculate_histogram(kv_iterator, bin_split_points=None,
                                   bin_sparse_points=None, valid_features=None,
                                   node_map=None, use_missing=False, zero_as_missing=False,
                                   parent_nid_map=None, sibling_node_id_map=None, stable_reduce=False):
        data_bins = []
        node_ids = []
        grad = []
        hess = []

        data_record = 0  # total instance number of this partition

        partition_key = None  # this var is for stable reduce

        # go through iterator to collect g/h feature instances/ node positions
        for data_id, value in kv_iterator:

            if partition_key is None and stable_reduce:  # first key of data is used as partition key
                partition_key = data_id

            data_bin, nodeid_state = value[0]
            unleaf_state, nodeid = nodeid_state
            if unleaf_state == 0 or nodeid not in node_map:
                continue
            g, h = value[1]  # encrypted text in host, plaintext in guest
            data_bins.append(data_bin)  # features
            node_ids.append(nodeid)  # current node position
            grad.append(g)
            hess.append(h)
            data_record += 1

        LOGGER.debug("begin batch calculate histogram, data count is {}".format(data_record))
        node_num = len(node_map)

        missing_bin = 1 if use_missing else 0

        # if the value of a feature is 0, the corresponding bin index will not appear in the sample sparse vector
        # need to compute correct sparse point g_sum and s_sum by:
        # (node total sum value) - (node feature total sum value) + (non 0 sparse point sum)
        # [0, 0, 0] -> g, h, sample count
        zero_optim = [[[0 for i in range(3)]
                       for j in range(bin_split_points.shape[0])]
                      for k in range(node_num)]
        zero_opt_node_sum = [[0 for i in range(3)]
                             for j in range(node_num)]

        node_histograms = FeatureHistogram._generate_histogram_template(node_map, bin_split_points, valid_features,
                                                                        missing_bin)

        for rid in range(data_record):

            # node index is the position in the histogram list of a certain node
            node_idx = node_map.get(node_ids[rid])

            for fid, value in data_bins[rid].features.get_all_data():
                if valid_features is not None and valid_features[fid] is False:
                    continue
                if use_missing and value == NoneType():
                    # missing value is set as -1
                    value = -1
                node_histograms[node_idx][fid][value][0] += grad[rid]
                node_histograms[node_idx][fid][value][1] += hess[rid]
                node_histograms[node_idx][fid][value][2] += 1


        for nid in range(node_num):##cal feature level g_h incremental
            node_gh_sum_cal_flag = False
            for fid in range(bin_split_points.shape[0]):
                if valid_features is not None and valid_features[fid] is False:
                    continue
                    zero_optim[nid][fid][0] = sum(node_histograms[nid][fid][bin_index][0])
                    zero_optim[nid][fid][1] = sum(node_histograms[nid][fid][bin_index][1])
                    zero_optim[nid][fid][2] = sum(node_histograms[nid][fid][bin_index][2])

                if not node_gh_sum_cal_flag: ## node total sum value,cal only one feature enough
                    zero_opt_node_sum[nid][0] += zero_optim[nid][fid][0]
                    zero_opt_node_sum[nid][1] += zero_optim[nid][fid][1]
                    zero_opt_node_sum[nid][2] += zero_optim[nid][fid][2]
                    node_gh_sum_cal_flag = True


        for node_idx in range(node_num):
            for fid in range(bin_split_points.shape[0]):
                if valid_features is not None and valid_features[fid] is True:
                    if not use_missing or (use_missing and not zero_as_missing):
                        # add 0 g/h sum to sparse point
                        sparse_point = bin_sparse_points[fid]
                        node_histograms[node_idx][fid][sparse_point][0] += zero_opt_node_sum[node_idx][0] - \
                                                                           zero_optim[node_idx][fid][
                                                                               0]
                        node_histograms[node_idx][fid][sparse_point][1] += zero_opt_node_sum[node_idx][1] - \
                                                                           zero_optim[node_idx][fid][
                                                                               1]
                        node_histograms[node_idx][fid][sparse_point][2] += zero_opt_node_sum[node_idx][2] - \
                                                                           zero_optim[node_idx][fid][
                                                                               2]
                    else:
                        # if 0 is regarded as missing value, add to missing bin
                        node_histograms[node_idx][fid][-1][0] += zero_opt_node_sum[node_idx][0] - \
                                                                 zero_optim[node_idx][fid][0]
                        node_histograms[node_idx][fid][-1][1] += zero_opt_node_sum[node_idx][1] - \
                                                                 zero_optim[node_idx][fid][1]
                        node_histograms[node_idx][fid][-1][2] += zero_opt_node_sum[node_idx][2] - \
                                                                 zero_optim[node_idx][fid][2]

        ret = FeatureHistogram._generate_histogram_key_value_list(node_histograms, node_map, bin_split_points,
                                                                  parent_nid_map, sibling_node_id_map,
                                                                  partition_key=partition_key)
        return ret

    @staticmethod
    def _recombine_histograms(histograms_list: list, node_map, feature_num):

        histograms = [[[] for j in range(feature_num)] for k in range(len(node_map))]
        for tuple_ in histograms_list:
            node_id, fid = tuple_[0]
            node_idx = node_map[node_id]
            histograms[int(node_idx)][int(fid)] = FeatureHistogram._tensor_histogram_cumsum(tuple_[1][1])
        return histograms

    @staticmethod
    def _construct_table(histograms_table):
        histograms_table = histograms_table.mapValues(FeatureHistogram._host_histogram_cumsum_map_func)
        return histograms_table

    """
    Histogram with sparse optimization 
    """

    @staticmethod
    def calculate_histogram_sp_opt(data_bin, grad_and_hess, bin_split_points, cipher_split_num,
                                   bin_num, node_map, valid_features, use_missing, zero_as_missing,
                                   parent_node_id_map=None, sibling_node_id_map=None):

        LOGGER.debug("bin_shape is {}, node num is {}".format(bin_split_points.shape, len(node_map)))
        # Detect length of cipher
        g, h = grad_and_hess.first()[1]
        cipher_length = len(str(g.cipher))
        phrase_num = int(np.ceil(float(cipher_length) / cipher_split_num)) + 1
        n_final = g.n_final

        # Map-Reduce Functions
        batch_histogram_cal = functools.partial(
            FeatureHistogram._batch_calculate_histogram_with_sp_opt,
            node_map=node_map, bin_num=bin_num,
            phrase_num=phrase_num, cipher_split_num=cipher_split_num,
            valid_features=valid_features, use_missing=use_missing, zero_as_missing=zero_as_missing,
            with_uuid=False
        )
        agg_histogram = functools.partial(FeatureHistogram._aggregate_histogram_with_sp_opt)

        # Map-Reduce Execution
        batch_histogram_intermediate_rs = data_bin.join(grad_and_hess, lambda data_inst, g_h: (data_inst, g_h))
        histogram_table = batch_histogram_intermediate_rs.mapReducePartitions(batch_histogram_cal, agg_histogram)
        map_value_func = functools.partial(FeatureHistogram._aggregate_matrix_phase,
                                           cipher_split_num=cipher_split_num,
                                           phrase_num=phrase_num)
        histogram_table = histogram_table.mapValues(map_value_func)
        transform_func = functools.partial(FeatureHistogram._transform_sp_mat_to_table,
                                           bin_split_points=bin_split_points,
                                           valid_features=valid_features,
                                           use_missing=use_missing,
                                           n_final=n_final,
                                           parent_node_id_map=parent_node_id_map,
                                           sibling_node_id_map=sibling_node_id_map,
                                           inverse_map=FeatureHistogram._inverse_node_map(node_map))

        histogram_table = histogram_table.mapPartitions(transform_func, use_previous_behavior=False)

        return histogram_table

    @staticmethod
    def _aggregate_matrix_phase(value, cipher_split_num, phrase_num):

        # aggregating encrypted text, this is a mapValues function
        b, f, p, t = value[2]
        multiplier_vector = np.array([10 ** (cipher_split_num * i) for i in range(phrase_num)])
        bin_sum_matrix4d = value[0].toarray().reshape((b, f, p, t))
        bin_cnt_matrix = value[1].toarray()

        # b X f X p X t -> b X f X t X p : multiply along the p-axis
        bin_sum_matrix4d_mul = bin_sum_matrix4d.transpose((0, 1, 3, 2)) * multiplier_vector
        # b X f X t x p -> b x f x t
        bin_sum_matrix3d = bin_sum_matrix4d_mul.sum(axis=3)

        left_node_sum_matrix3d = np.cumsum(bin_sum_matrix3d, axis=0)  # accumulate : b X f X t
        left_node_cnt_matrix = np.cumsum(bin_cnt_matrix, axis=0)  # accumulate : b X f

        return [left_node_sum_matrix3d, left_node_cnt_matrix]

    @staticmethod
    def _calculate_histogram_matrix(cipher_matrix, feature_matrix, bin_num, use_missing):

        # Calculate sum of para in left node for each split points
        # Return a matrix of Bins X Feature X Phrase X type
        # C(Case) F(Feature) B(Bin) P(Phrase) T(Type: grad or hess)
        # input: cipher_matrix = t X p X c  feature_matrix = c X f

        # dimension parameter
        b = bin_num + int(use_missing)
        c = feature_matrix.shape[0]
        f = feature_matrix.shape[1]
        p = cipher_matrix.shape[1]
        t = cipher_matrix.shape[0]

        # calculation
        # Cnt Matrix
        if use_missing:
            bin_num_vector = [i for i in range(bin_num)] + [-1]  # 1 x b
        else:
            bin_num_vector = [i for i in range(bin_num)]
        bin_marker_matrix3d = np.equal.outer(bin_num_vector, feature_matrix)  # b X c X f
        bin_cnt_matrix = bin_marker_matrix3d.sum(axis=1)  # b x f
        bin_cnt_matrix_sparse = sp.csc_matrix(bin_cnt_matrix)

        # Feature Matrix
        # b*f X c
        bin_marker_matrix3d_reshape = bin_marker_matrix3d.transpose((0, 2, 1)).reshape((b * f, c))
        bin_marker_matrix3d_reshape_sparse = sp.csc_matrix(bin_marker_matrix3d_reshape)

        # Cipher Matrix
        cipher_matrix_reshape = cipher_matrix.transpose((2, 1, 0)).reshape((c, p * t))  # c x p*t

        # Feature dot Cipher
        bin_sum_matrix4d_reshape = bin_marker_matrix3d_reshape_sparse.dot(cipher_matrix_reshape)  # b*f X p*t
        bin_sum_matrix4d_sparse = sp.csc_matrix(bin_sum_matrix4d_reshape)

        dim = (b, f, p, t)
        return bin_sum_matrix4d_sparse, bin_cnt_matrix_sparse, dim

    @staticmethod
    def _break_down_cipher(cipher_obj, cipher_split_num, pid):
        # break ciper text into phases
        c_str = str(cipher_obj.cipher)
        c_len = len(c_str)
        if cipher_split_num * (pid + 1) <= c_len:
            start = c_len - cipher_split_num * (pid + 1)
            end = c_len - cipher_split_num * pid
            cipher_phase = int(c_str[start:end])
        elif cipher_split_num * pid < c_len:
            start = 0
            end = c_len - cipher_split_num * pid
            cipher_phase = int(c_str[start:end])
        else:
            cipher_phase = 0
        return cipher_phase

    @staticmethod
    def _batch_calculate_histogram_with_sp_opt(kv_iterator, node_map, bin_num, phrase_num, cipher_split_num,
                                               valid_features, use_missing, zero_as_missing, with_uuid=False):

        # initialize
        data_bins_dict = {}
        grad_phrase_dict = {}
        hess_phrase_dict = {}

        # read in data
        data_record = 0
        for _, value in kv_iterator:
            data_bin, nodeid_state = value[0]
            unleaf_state, nodeid = nodeid_state
            if unleaf_state == 0 or nodeid not in node_map:
                continue
            g, h = value[1]
            nid = node_map.get(nodeid)
            if nid not in data_bins_dict:
                data_bins_dict[nid] = []

            # as most sparse point is bin-0
            # when mark it as a missing value (-1), offset it to make it sparse, to restore it to -1 here
            if not use_missing or (use_missing and not zero_as_missing):
                offset = 0
            else:
                offset = -1
            data_bins_dict[nid].append(data_bin.features.toarray()[0][valid_features] + offset)

            # Break down the cipher
            for pid in range(phrase_num):
                grad_cipher_phase = FeatureHistogram._break_down_cipher(g, cipher_split_num, pid)
                hess_cipher_phase = FeatureHistogram._break_down_cipher(h, cipher_split_num, pid)

                if nid not in grad_phrase_dict:
                    grad_phrase_dict[nid] = [[] for pid in range(phrase_num)]
                grad_phrase_dict[nid][pid].append(grad_cipher_phase)

                if nid not in hess_phrase_dict:
                    hess_phrase_dict[nid] = [[] for pid in range(phrase_num)]
                hess_phrase_dict[nid][pid].append(hess_cipher_phase)

            data_record += 1
        LOGGER.debug("begin batch calculate histogram, data count is {}".format(data_record))

        # calculate histogram matrix
        ret = []
        _ = str(uuid.uuid1())
        for nid in data_bins_dict:
            feature_matrix = np.array(data_bins_dict[nid])  # c X f
            cipher_matrix = np.array([grad_phrase_dict[nid], hess_phrase_dict[nid]])  # t X p X c

            bin_sum_matrix4d_sparse, bin_cnt_matrix_sparse, dim = \
                FeatureHistogram._calculate_histogram_matrix(
                    cipher_matrix=cipher_matrix,
                    feature_matrix=feature_matrix,
                    bin_num=bin_num,
                    use_missing=use_missing
                )
            key_ = nid if not with_uuid else (_, nid)
            ret.append((key_, [bin_sum_matrix4d_sparse, bin_cnt_matrix_sparse, dim]))

        return ret

    @staticmethod
    def _aggregate_histogram_with_sp_opt(histogram1, histogram2):
        bin_sum_matrix4d_sparse = histogram1[0] + histogram2[0]
        bin_cnt_matrix_sparse = histogram1[1] + histogram2[1]
        dim = histogram1[2]

        return [bin_sum_matrix4d_sparse, bin_cnt_matrix_sparse, dim]

    @staticmethod
    def _get_obj(raw, n_final):
        if raw == 0:
            result = 0
        else:
            result = DeterministicIterativeAffineCiphertext(raw, n_final)
        return result

    @staticmethod
    def _transform_sp_mat_to_table(kv_iterator, bin_split_points, valid_features, use_missing, n_final,
                                   inverse_map, parent_node_id_map, sibling_node_id_map):

        ret = []
        get_obj = functools.partial(FeatureHistogram._get_obj, n_final=n_final)
        for node_idx, value in kv_iterator:
            valid_fid = 0
            for fid in range(len(valid_features)):

                # if parent_nid is offered, map nid to its parent nid for histogram subtraction
                node_id = inverse_map[node_idx]
                key = (parent_node_id_map[node_id], fid) if parent_node_id_map is not None else (node_id, fid)

                if valid_features[fid]:
                    feature_bin_num = len(bin_split_points[fid]) + int(use_missing)
                    histogram = [[] for _ in range(feature_bin_num)]
                    for bid in range(len(bin_split_points[fid])):
                        grad = value[0][bid, valid_fid, 0]
                        hess = value[0][bid, valid_fid, 1]
                        cnt = value[1][bid, valid_fid]
                        histogram[bid].append(get_obj(grad))
                        histogram[bid].append(get_obj(hess))
                        histogram[bid].append(cnt)

                    if use_missing:
                        grad = value[0][-1, valid_fid, 0]
                        hess = value[0][-1, valid_fid, 1]
                        cnt = value[1][-1, valid_fid]
                        histogram[-1].append(get_obj(grad))
                        histogram[-1].append(get_obj(hess))
                        histogram[-1].append(cnt)

                    valid_fid += 1
                    # if sibling_node_id_map is offered, recorded its sibling ids for histogram subtraction
                    ret_value = (fid, histogram) if sibling_node_id_map is None else \
                        ((fid, node_id, sibling_node_id_map[node_id]), histogram)
                    # key, value
                    ret.append((key, ret_value))
                else:
                    # empty histogram
                    ret_value = (fid, []) if sibling_node_id_map is None else \
                        ((fid, node_id, sibling_node_id_map[node_id]), [])
                    ret.append((key, ret_value))

        return ret

    """
    Histogram subtraction functions
    """

    def _update_node_info(self, nodes):
        """
        generate node summaries for hist subtraction
        """
        if nodes is None:
            raise ValueError('node list should not be None if histogram subtraction is enabled')
        self._cur_to_split_node_info = {}
        for node in nodes:
            node_id = node.id
            self._cur_to_split_node_info[node_id] = {'pid': node.parent_nodeid, 'is_left_node': node.is_left_node}

    @staticmethod
    def _is_root_node(node_map):

        """
        check if current to split is root node
        """
        return 0 in node_map

    def _update_cached_histograms(self, dep, ret='tensor'):

        """
        update cached parent histograms
        """

        if dep != self._cur_dep and ret == 'tensor':
            del self._prev_layer_cached_histograms  # delete previous cached histograms
            self._prev_layer_cached_histograms = self._cur_layer_cached_histograms  # update cached histograms
            self._cur_layer_cached_histograms = {}  # for caching new histograms
            self._cur_dep = dep

        elif dep != self._cur_dep and ret == 'tb':
            del self._prev_layer_dtable
            self._prev_layer_dtable = self._cur_layer_dtables[0]
            for table in self._cur_layer_dtables[1:]:
                self._prev_layer_dtable = self._prev_layer_dtable.union(table)
            self._cur_layer_dtables = []
            self._cur_dep = dep

        LOGGER.info('hist subtraction dep is updated to {}'.format(self._cur_dep))

    def _cached_histograms(self, histograms, ret='tensor'):
        """
        cached cur layer histograms
        """
        if ret == 'tb':
            self._cur_layer_dtables.append(histograms)
        elif ret == 'tensor':
            result_nid, result = histograms
            for node_id, result_hist in zip(result_nid, result):
                self._cur_layer_cached_histograms[node_id] = result_hist

    @staticmethod
    def _inverse_node_map(node_map):
        return {v: k for k, v in node_map.items()}

    def _is_left(self, node_id):
        """
        check if it is left node
        """
        return self._cur_to_split_node_info[node_id]['is_left_node']

    def _get_parent_nid_map(self, ):

        """
        get a map that can map a node to its parent node
        """

        rs = {}
        for nid in self._cur_to_split_node_info:
            if nid == 0:
                return None
            rs[nid] = self._cur_to_split_node_info[nid]['pid']
        return rs

    @staticmethod
    def _trim_node_map(node_map, leaf_sample_counts):

        """
        Only keep the nodes with fewer sample and remove their siblings, for accelerating hist computation
        """

        inverse_node_map = {v: k for k, v in node_map.items()}
        sibling_node_map = {}
        # if is root node, return directly
        if 0 in node_map:
            return node_map, None

        kept_node_id = []

        idx = 0
        for left_count, right_count in zip(leaf_sample_counts[0::2], leaf_sample_counts[1::2]):
            if left_count < right_count:
                kept_node_id.append(inverse_node_map[idx])
                sibling_node_map[inverse_node_map[idx]] = inverse_node_map[idx + 1]
            else:
                kept_node_id.append(inverse_node_map[idx + 1])
                sibling_node_map[inverse_node_map[idx + 1]] = inverse_node_map[idx]
            idx += 2

        new_node_map = {node_id: idx for idx, node_id in enumerate(kept_node_id)}

        return new_node_map, sibling_node_map

    @staticmethod
    def _g_h_count_sub(hist_a, hist_b):
        return hist_a[0] - hist_b[0], hist_a[1] - hist_b[1], hist_a[2] - hist_b[2]

    @staticmethod
    def _hist_sub(tensor_hist_a, tensor_hist_b):

        new_hist = copy.deepcopy(tensor_hist_b)
        assert len(tensor_hist_a) == len(tensor_hist_b)
        for fid in range(len(tensor_hist_a)):
            for bid in range(len(tensor_hist_a[fid])):  # if is not a valid feature, bin_num is 0
                new_hist[fid][bid][0], new_hist[fid][bid][1], new_hist[fid][bid][2] = FeatureHistogram._g_h_count_sub(
                    tensor_hist_a[fid][bid], tensor_hist_b[fid][bid])

        return new_hist

    @staticmethod
    def _table_hist_sub(kv):

        res = []
        for k, v in kv:
            parent_hist, son_hist = v
            fid, p_hist = parent_hist
            (fid, node_id, sib_node_id), s_hist = son_hist
            assert len(p_hist) == len(s_hist), 'bin num not equal'
            bin_num = len(p_hist)
            new_hist = [[0, 0, 0] for i in range(bin_num)]
            for bid in range(bin_num):
                # get sibling histograms by hist subtraction, if is not a valid feature, bin_num is 0
                new_hist[bid][0], new_hist[bid][1], new_hist[bid][2] = FeatureHistogram._g_h_count_sub(p_hist[bid],
                                                                                                       s_hist[bid])
            # key, value
            res.append(((sib_node_id, fid), (fid, new_hist)))
            res.append(((node_id, fid), (fid, s_hist)))

        return res

    def _tensor_subtraction(self, histograms, node_map):

        """
        histogram subtraction for tensor format
        """

        inverse_node_map = self._inverse_node_map(node_map)  # get inverse node map
        node_ids = []
        p_node_ids = []

        for idx in range(len(histograms)):
            node_id = inverse_node_map[idx]
            node_ids.append(node_id)
            p_node_ids.append(self._cur_to_split_node_info[node_id]['pid'])  # get parent histograms id

        result = []
        result_nid = []

        for node_id, pid, hist in zip(node_ids, p_node_ids, histograms):

            # get sibling histograms by histogram subtraction
            parent_hist = self._prev_layer_cached_histograms[pid]
            sibling_hist = self._hist_sub(parent_hist, hist)
            # is right sibling or left sibling ?
            if self._is_left(node_id):
                result.append(hist)
                result.append(sibling_hist)
                result_nid.append(node_id)
                result_nid.append(node_id + 1)
            else:
                result.append(sibling_hist)
                result.append(hist)
                result_nid.append(node_id - 1)
                result_nid.append(node_id)

        return result_nid, result

    def _table_subtraction(self, histograms):

        """
        histogram subtraction for dtable format
        """

        LOGGER.debug('joining parent and son histogram tables')
        parent_and_son_hist_table = self._prev_layer_dtable.join(histograms, lambda v1, v2: (v1, v2))
        result = parent_and_son_hist_table.mapPartitions(FeatureHistogram._table_hist_sub, use_previous_behavior=False)
        return result