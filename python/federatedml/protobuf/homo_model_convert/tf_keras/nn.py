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
#

import io
import tempfile
import tensorflow
import zipfile

from ..component_converter import ComponentConverterBase


class NNComponentConverter(ComponentConverterBase):

    @staticmethod
    def get_target_modules():
        return ['HomoNN']

    def convert(self, model_dict):
        param_obj = model_dict["HomoNNModelParam"]
        meta_obj = model_dict["HomoNNModelMeta"]
        if meta_obj.params.config_type != "nn" and meta_obj.params.config_type != "keras":
            raise ValueError("Invalid config type: {}".format(meta_obj.config_type))

        with tempfile.TemporaryDirectory() as tmp_path:
            with io.BytesIO(param_obj.saved_model_bytes) as bytes_io:
                with zipfile.ZipFile(bytes_io, 'r', zipfile.ZIP_DEFLATED) as f:
                    f.extractall(tmp_path)
                    try:
                        model = tensorflow.keras.models.load_model(tmp_path)
                    except Exception as e:
                        model = tensorflow.compat.v1.keras.experimental.load_from_saved_model(tmp_path)
        return model
