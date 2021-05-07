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

import copy
import numpy as np

from fate_flow.entity.metric import Metric, MetricMeta
from federatedml.model_base import ModelBase
from federatedml.statistic import data_overview
from federatedml.param.sample_weight_param import SampleWeightParam
from federatedml.protobuf.generated.sample_weight_model_meta_pb2 import SampleWeightModelMeta
from federatedml.protobuf.generated.sample_weight_model_param_pb2 import SampleWeightModelParam
from federatedml.statistic.data_overview import get_label_count, check_negative_sample_weight
from federatedml.util import consts, LOGGER


class SampleWeight(ModelBase):
    def __init__(self):
        super().__init__()
        self.model_param = SampleWeightParam()
        self.metric_name = "sample_weight"
        self.metric_namespace = "train"
        self.metric_type = "SAMPLE_WEIGHT"
        self.model_meta_name = "SampleWeightModelMeta"
        self.model_param_name = "SampleWeightModelParam"
        self.weight_mode = None
        self.header = None

    def _init_model(self, params):
        self.model_param = params
        self.class_weight = params.class_weight
        self.sample_weight_name = params.sample_weight_name
        self.normalize = params.normalize
        self.need_run = params.need_run

    @staticmethod
    def get_class_weight(data_instances):
        class_weight = get_label_count(data_instances)
        n_samples = data_instances.count()
        n_classes = len(class_weight.keys())
        res_class_weight = {str(k): n_samples / (n_classes * v) for k, v in class_weight.items()}

        return res_class_weight

    @staticmethod
    def replace_weight(data_instance, class_weight, weight_loc=None, weight_base=None):
        weighted_data_instance = copy.copy(data_instance)
        original_features = weighted_data_instance.features
        if weight_loc is not None:
            if weight_base is not None:
                inst_weight = original_features[weight_loc] / weight_base
            else:
                inst_weight = original_features[weight_loc]
            weighted_data_instance.set_weight(inst_weight)
            weighted_data_instance.features = original_features[np.arange(original_features.shape[0]) != weight_loc]
        else:
            weighted_data_instance.set_weight(class_weight.get(str(data_instance.label), 1))
        return weighted_data_instance

    @staticmethod
    def assign_sample_weight(data_instances, class_weight, weight_loc, normalize):
        weight_base = None
        if weight_loc is not None and normalize:
            def sum_sample_weight(kv_iterator):
                sample_weight = 0
                for _, inst in kv_iterator:
                    sample_weight += inst.features[weight_loc]
                return sample_weight

            weight_sum = data_instances.mapPartitions(sum_sample_weight).reduce(lambda x, y: x + y)
            # LOGGER.debug(f"weight_sum is {weight_sum}")
            weight_base = weight_sum / data_instances.count()
            # LOGGER.debug(f"weight_base is {weight_base}")
        return data_instances.mapValues(lambda v: SampleWeight.replace_weight(v, class_weight, weight_loc, weight_base))

    @staticmethod
    def get_weight_loc(data_instances, sample_weight_name):
        weight_loc = None
        if sample_weight_name:
            try:
                weight_loc = data_instances.schema["header"].index(sample_weight_name)
            except ValueError:
                return
        return weight_loc

    def transform_weighted_instance(self, data_instances, weight_loc):
        if self.class_weight and self.class_weight == 'balanced':
            self.class_weight = SampleWeight.get_class_weight(data_instances)
        return SampleWeight.assign_sample_weight(data_instances, self.class_weight, weight_loc, self.normalize)

    def callback_info(self):
        class_weight = None
        classes = None
        if self.class_weight:
            class_weight = {str(k): v for k, v in self.class_weight.items()}
            classes = sorted([str(k) for k in self.class_weight.keys()])
        # LOGGER.debug(f"callback class weight is: {class_weight}")

        metric_meta = MetricMeta(name='train',
                                 metric_type=self.metric_type,
                                 extra_metas={
                                     "weight_mode": self.weight_mode,
                                     "class_weight": class_weight,
                                     "classes": classes,
                                     "sample_weight_name": self.sample_weight_name
                                 })

        self.callback_metric(metric_name=self.metric_name,
                             metric_namespace=self.metric_namespace,
                             metric_data=[Metric(self.metric_name, 0)])
        self.tracker.set_metric_meta(metric_namespace=self.metric_namespace,
                                     metric_name=self.metric_name,
                                     metric_meta=metric_meta)

    def export_model(self):
        meta_obj = SampleWeightModelMeta(sample_weight_name=self.sample_weight_name,
                                    normalize=self.normalize,
                                    need_run=self.need_run)
        param_obj = SampleWeightModelParam(header=self.header,
                                      weight_mode = self.weight_mode,
                                      class_weight=self.class_weight)
        result = {
            self.model_meta_name: meta_obj,
            self.model_param_name: param_obj
        }
        return result

    def load_model(self, model_dict):
        param_obj = list(model_dict.get('model').values())[0].get(self.model_param_name)
        meta_obj = list(model_dict.get('model').values())[0].get(self.model_meta_name)

        self.header = list(param_obj.header)
        self.need_run = meta_obj.need_run
        self.weight_mode = param_obj.weight_mode
        if self.weight_mode == "class weight":
            self.class_weight = {k: v for k, v in param_obj.class_weight.items()}
        elif self.weight_mode == "sample weight name":
            self.sample_weight_name = meta_obj.sample_weight_name
            self.normalize = meta_obj.normalize
        else:
            raise ValueError(f"Unknown weight mode {self.weight_mode} loaded. "
                             f"Only support 'class weight' and 'sample weight name'")

    def transform(self, data_instances):
        LOGGER.info(f"Enter Sample Weight Transform")
        new_schema = copy.deepcopy(data_instances.schema)
        new_schema["sample_weight"] = "weight"
        weight_loc = None
        if self.weight_mode == "sample weight name":
            weight_loc = SampleWeight.get_weight_loc(data_instances, self.sample_weight_name)
            if weight_loc is not None:
                new_schema["header"].pop(weight_loc)
            else:
                LOGGER.warning(f"Cannot find weight column of given sample_weight_name '{self.sample_weight_name}'."
                               f"Original input data returned")
                return data_instances
        result_instances = self.transform_weighted_instance(data_instances, weight_loc)
        result_instances.schema = new_schema

        self.callback_info()
        if result_instances.mapPartitions(check_negative_sample_weight).reduce(lambda x, y: x or y):
            LOGGER.warning(f"Negative weight found in weighted instances.")
        return result_instances

    def fit(self, data_instances):
        if self.sample_weight_name is None and self.class_weight is None:
            return data_instances

        self.header = data_overview.get_header(data_instances)

        if self.class_weight:
            self.weight_mode = "class weight"

        if self.sample_weight_name and self.class_weight:
            LOGGER.warning(f"Both 'sample_weight_name' and 'class_weight' provided. "
                           f"Only weight from 'sample_weight_name' is used.")

        new_schema = copy.deepcopy(data_instances.schema)
        new_schema["sample_weight"] = "weight"
        weight_loc = None
        if self.sample_weight_name:
            self.weight_mode = "sample weight name"
            weight_loc = SampleWeight.get_weight_loc(data_instances, self.sample_weight_name)
            if weight_loc is not None:
                new_schema["header"].pop(weight_loc)
            else:
                raise ValueError(f"Cannot find weight column of given sample_weight_name '{self.sample_weight_name}'.")
        result_instances = self.transform_weighted_instance(data_instances, weight_loc)
        result_instances.schema = new_schema

        self.callback_info()
        if result_instances.mapPartitions(check_negative_sample_weight).reduce(lambda x, y: x or y):
            LOGGER.warning(f"Negative weight found in weighted instances.")
        return result_instances
