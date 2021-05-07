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


class Instance(object):
    """
    Instance object use in all algorithm module

    Parameters
    ----------
    inst_id : int, the id of the instance, reserved fields in this version

    weight: float, the weight of the instance

    feature : object, ndarray or SparseVector Object in this version

    label: None of float, data label

    """
    def __init__(self, inst_id=None, weight=None, features=None, label=None):
        self.inst_id = inst_id
        self.weight = weight
        self.features = features
        self.label = label

    def set_weight(self, weight=1.0):
        self.weight = weight

    def set_label(self, label=1):
        self.label = label

    def set_feature(self, features):
        self.features = features

    @property
    def with_inst_id(self):
        return self.inst_id is not None
