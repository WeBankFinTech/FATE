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
import pytorch_lightning as pl
import tempfile
import tensorflow as tf
import torch

from federatedml.protobuf.homo_model_convert.homo_model_convert import model_convert, save_converted_model
from federatedml.protobuf.generated.nn_model_param_pb2 import NNModelParam
from federatedml.protobuf.generated.nn_model_meta_pb2 import NNModelMeta
from federatedml.param.homo_nn_param import HomoNNParam
from federatedml.nn.backend.tf_keras.nn_model import _zip_dir_as_bytes
from federatedml.nn.backend.pytorch.nn_model import build_pytorch
from federatedml.nn.homo_nn._torch import FedLightModule, PyTorchSAClientContext


class TestHomoNNConverter(unittest.TestCase):
    def setUp(self):
        # compose a dummy keras Sequential model
        model = tf.keras.Sequential()
        model.add(tf.keras.Input(shape=(16,)))
        model.add(tf.keras.layers.Dense(8))
        model.compile(loss="categorical_crossentropy")
        with tempfile.TemporaryDirectory() as tmp_path:
            model.save(tmp_path)
            keras_model_bytes = _zip_dir_as_bytes(tmp_path)
        self.keras_model_param = NNModelParam()
        self.keras_model_param.saved_model_bytes = keras_model_bytes
        self.keras_model_meta = NNModelMeta()
        nn_param = HomoNNParam(config_type="keras",
                               early_stop="diff",
                               metrics="Accuracy",
                               optimizer="SGD",
                               loss="categorical_crossentropy")
        nn_param.check()
        self.keras_model_meta.params.CopyFrom(nn_param.generate_pb())

        # a dummy pytorch version 0 model
        nn_param = HomoNNParam(config_type="pytorch",
                               early_stop="diff",
                               metrics="Accuracy",
                               optimizer={
                                   "optimizer": "Adam",
                                   "lr": 0.05
                               },
                               loss="CrossEntropyLoss")
        nn_param.check()
        nn_define = [
                {
                    "layer": "Linear",
                    "name": "line1",
                    "type": "normal",
                    "config": [
                        18,
                        5
                    ]
                },
                {
                    "layer": "Relu",
                    "type": "activate",
                    "name": "relu"
                },
                {
                    "layer": "Linear",
                    "name": "line2",
                    "type": "normal",
                    "config": [
                        5,
                        4
                    ]
                }
            ]
        self.pytorch_model_param = NNModelParam()
        pytorch_nn_model = build_pytorch(nn_define, nn_param.optimizer, nn_param.loss, nn_param.metrics)
        self.pytorch_model_param.saved_model_bytes = pytorch_nn_model.export_model()
        self.pytorch_model_meta = NNModelMeta()
        self.pytorch_model_meta.params.CopyFrom(nn_param.generate_pb())

        # a dummy pytorch lightning model
        nn_param = HomoNNParam(config_type="pytorch",
                               early_stop="diff",
                               metrics="Accuracy",
                               optimizer={
                                   "optimizer": "Adam",
                                   "lr": 0.05
                               },
                               loss="NLLLoss")
        nn_param.check()
        nn_define = [
          {
            "layer": "Conv2d",
            "in_channels": 1,
            "out_channels": 10,
            "kernel_size": [5, 5]
          },
          {
            "layer": "MaxPool2d",
            "kernel_size": 2
          },
          {
            "layer": "ReLU"
          },
          {
            "layer": "Conv2d",
            "in_channels": 10,
            "out_channels": 20,
            "kernel_size": [5, 5]
          },
          {
            "layer": "Dropout2d"
          },
          {
            "layer": "MaxPool2d",
            "kernel_size": 2
          },
          {
            "layer": "ReLU"
          },
          {
            "layer": "Flatten"
          },
          {
            "layer": "Linear",
            "in_features": 320,
            "out_features": 50
          },
          {
            "layer": "ReLU"
          },
          {
            "layer": "Linear",
            "in_features": 50,
            "out_features": 10
          },
          {
            "layer": "LogSoftmax"
          }
        ]
        pl_module = FedLightModule(
            None,
            layers_config=nn_define,
            optimizer_config=nn_param.optimizer,
            loss_config={"loss": nn_param.loss},
        )
        pl_trainer = pl.Trainer()
        pl_trainer.model = pl_module
        self.pl_model_param = NNModelParam(api_version=2)
        with tempfile.TemporaryDirectory() as d:
            filepath = os.path.join(d, "model.ckpt")
            pl_trainer.save_checkpoint(filepath)
            with open(filepath, "rb") as f:
                self.pl_model_param.saved_model_bytes = f.read()
        self.pl_model_meta = NNModelMeta()
        self.pl_model_meta.params.CopyFrom(nn_param.generate_pb())

    def test_tf_keras_converter(self):
        target_framework, model = self._do_convert(self.keras_model_param, self.keras_model_meta)
        self.assertTrue(target_framework == "tf_keras")
        self.assertTrue(isinstance(model, tf.keras.Sequential))
        with tempfile.TemporaryDirectory() as d:
            dest = save_converted_model(model, target_framework, d)
            self.assertTrue(os.path.isdir(dest))

    def test_pytorch_converter(self):
        target_framework, model = self._do_convert(self.pytorch_model_param, self.pytorch_model_meta)
        self.assertTrue(target_framework == "pytorch")
        self.assertTrue(isinstance(model, torch.nn.Sequential))
        with tempfile.TemporaryDirectory() as d:
            dest = save_converted_model(model, target_framework, d)
            self.assertTrue(os.path.isfile(dest))
            self.assertTrue(dest.endswith(".pth"))

    def test_pytorch_lightning_converter(self):
        target_framework, model = self._do_convert(self.pl_model_param, self.pl_model_meta)
        self.assertTrue(target_framework == "pytorch")
        self.assertTrue(isinstance(model, torch.nn.Sequential))
        with tempfile.TemporaryDirectory() as d:
            dest = save_converted_model(model, target_framework, d)
            self.assertTrue(os.path.isfile(dest))
            self.assertTrue(dest.endswith(".pth"))

    @staticmethod
    def _do_convert(model_param, model_meta):
        return model_convert(model_contents={
                                'HomoNNModelParam': model_param,
                                'HomoNNModelMeta': model_meta
                             },
                             module_name='HomoNN')


if __name__ == '__main__':
    unittest.main()
