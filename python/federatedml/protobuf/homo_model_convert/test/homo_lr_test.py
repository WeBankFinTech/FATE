#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  Copyright 2021 The FATE Authors. All Rights Reserved.
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

import unittest

import os
import tempfile
from sklearn.linear_model import LogisticRegression

from federatedml.protobuf.homo_model_convert.homo_model_convert import model_convert, save_converted_model
from federatedml.protobuf.generated.lr_model_param_pb2 import LRModelParam
from federatedml.protobuf.generated.lr_model_meta_pb2 import LRModelMeta


class TestHomoLRConverter(unittest.TestCase):
    def setUp(self):
        param_dict = {
            'iters': 5,
            'loss_history': [],
            'is_converged': True,
            'weight': {
                'x3': 0.3,
                'x2': 0.2,
                'x1': 0.1
            },
            'intercept': 0.5,
            'header': ['x1', 'x2', 'x3'],
            'best_iteration': -1
        }
        self.model_param = LRModelParam(**param_dict)

        meta_dict = {
            'penalty': 'l2',
            'tol': 1e-05,
            'fit_intercept': True,
            'optimizer': 'sgd',
            'max_iter': 5,
            'alpha': 0.01
        }
        self.model_meta = LRModelMeta(**meta_dict)

    def test_sklearn_converter(self):
        target_framework, model = model_convert(model_contents={
                                                    'HomoLogisticRegressionParam': self.model_param,
                                                    'HomoLogisticRegressionMeta': self.model_meta
                                                },
                                                module_name='HomoLR',
                                                framework_name='sklearn')
        self.assertTrue(target_framework == 'sklearn')
        self.assertTrue(isinstance(model, LogisticRegression))
        self.assertTrue(model.intercept_[0] == self.model_param.intercept)
        self.assertTrue(model.coef_.shape == (1, len(self.model_param.header)))
        self.assertTrue(model.tol == self.model_meta.tol)

        with tempfile.TemporaryDirectory() as d:
            dest = save_converted_model(model, target_framework, d)
            self.assertTrue(os.path.isfile(dest))
            self.assertTrue(dest.endswith(".joblib"))


if __name__ == '__main__':
    unittest.main()
