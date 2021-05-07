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
import grpc
import os
from ruamel import yaml

from fate_flow.settings import IP, HTTP_PORT, FATE_FLOW_MODEL_TRANSFER_ENDPOINT
from fate_arch.common.conf_utils import get_base_config
from fate_arch.protobuf.python import model_service_pb2
from fate_arch.protobuf.python import model_service_pb2_grpc
from fate_flow.settings import stat_logger
from fate_flow.utils import model_utils
from fate_flow.pipelined_model import pipelined_model
from federatedml.protobuf.homo_model_convert.homo_model_convert import model_convert, save_converted_model


def generate_publish_model_info(config_data):
    model_id = config_data['job_parameters']['model_id']
    model_version = config_data['job_parameters']['model_version']
    config_data['model'] = {}
    for role, role_party in config_data.get("role").items():
        config_data['model'][role] = {}
        for party_id in role_party:
            config_data['model'][role][party_id] = {
                'model_id': model_utils.gen_party_model_id(model_id, role, party_id),
                'model_version': model_version
            }


def load_model(config_data):
    stat_logger.info(config_data)
    if not config_data.get('servings'):
        return 100, 'Please configure servings address'
    for serving in config_data.get('servings'):
        with grpc.insecure_channel(serving) as channel:
            stub = model_service_pb2_grpc.ModelServiceStub(channel)
            load_model_request = model_service_pb2.PublishRequest()
            for role_name, role_partys in config_data.get("role").items():
                for _party_id in role_partys:
                    load_model_request.role[role_name].partyId.append(_party_id)
            for role_name, role_model_config in config_data.get("model").items():
                for _party_id, role_party_model_config in role_model_config.items():
                    load_model_request.model[role_name].roleModelInfo[_party_id].tableName = role_party_model_config[
                        'model_version']
                    load_model_request.model[role_name].roleModelInfo[_party_id].namespace = role_party_model_config[
                        'model_id']
            stat_logger.info('request serving: {} load model'.format(serving))
            load_model_request.local.role = config_data.get('local').get('role')
            load_model_request.local.partyId = config_data.get('local').get('party_id')
            load_model_request.loadType = config_data['job_parameters'].get("load_type", "FATEFLOW")
            if not get_base_config('use_registry'):
                load_model_request.filePath = f"http://{IP}:{HTTP_PORT}{FATE_FLOW_MODEL_TRANSFER_ENDPOINT}"
            else:
                load_model_request.filePath = config_data['job_parameters'].get("file_path", "")
            stat_logger.info(load_model_request)
            response = stub.publishLoad(load_model_request)
            stat_logger.info(
                '{} {} load model status: {}'.format(load_model_request.local.role, load_model_request.local.partyId,
                                                     response.statusCode))
            if response.statusCode != 0:
                return response.statusCode, '{} {}'.format(response.message, response.error)
    return 0, 'success'


def bind_model_service(config_data):
    service_id = config_data.get('service_id')
    initiator_role = config_data['initiator']['role']
    initiator_party_id = config_data['initiator']['party_id']
    model_id = config_data['job_parameters']['model_id']
    model_version = config_data['job_parameters']['model_version']
    if not config_data.get('servings'):
        return 100, 'Please configure servings address'
    for serving in config_data.get('servings'):
        with grpc.insecure_channel(serving) as channel:
            stub = model_service_pb2_grpc.ModelServiceStub(channel)
            publish_model_request = model_service_pb2.PublishRequest()
            publish_model_request.serviceId = service_id
            for role_name, role_party in config_data.get("role").items():
                publish_model_request.role[role_name].partyId.extend(role_party)

            publish_model_request.model[initiator_role].roleModelInfo[initiator_party_id].tableName = model_version
            publish_model_request.model[initiator_role].roleModelInfo[
                initiator_party_id].namespace = model_utils.gen_party_model_id(model_id, initiator_role,
                                                                               initiator_party_id)
            publish_model_request.local.role = initiator_role
            publish_model_request.local.partyId = initiator_party_id
            stat_logger.info(publish_model_request)
            response = stub.publishBind(publish_model_request)
            stat_logger.info(response)
            if response.statusCode != 0:
                return response.statusCode, response.message
    return 0, None


def download_model(request_data):
    model = pipelined_model.PipelinedModel(model_id=request_data.get("namespace"),
                                           model_version=request_data.get("name"))
    model_data = model.collect_models(in_bytes=True)
    return model_data


def convert_homo_model(request_data):
    party_model_id = model_utils.gen_party_model_id(model_id=request_data["model_id"],
                                                    role=request_data["role"],
                                                    party_id=request_data["party_id"])
    model_version = request_data.get("model_version")
    model = pipelined_model.PipelinedModel(model_id=party_model_id, model_version=model_version)
    if not model.exists():
        return 100, 'Model {} {} does not exist'.format(party_model_id, model_version), None

    with open(model.define_meta_path, "r", encoding="utf-8") as fr:
        define_index = yaml.safe_load(fr)

    framework_name = request_data.get("framework_name")
    detail = []
    for key, value in define_index.get("model_proto", {}).items():
        if key == 'pipeline':
            continue
        for v in value.keys():
            buffer_obj = model.read_component_model(key, v)
            module_name = define_index.get("component_define", {}).get(key, {}).get('module_name')
            converted_framework, converted_model = model_convert(model_contents=buffer_obj,
                                                                 module_name=module_name,
                                                                 framework_name=framework_name)
            if converted_model:
                converted_model_dir = os.path.join(model.variables_data_path, key, "converted_model")
                os.makedirs(converted_model_dir, exist_ok=True)

                saved_path = save_converted_model(converted_model,
                                                  converted_framework,
                                                  converted_model_dir)
                detail.append({
                    "component_name": key,
                    "converted_model_path": saved_path
                })
    if len(detail) > 0:
        return (0,
                f"Conversion of homogeneous federated learning component(s) in model "
                f"{party_model_id}:{model_version} completed. Use export to download the converted model.",
                detail)
    else:
        return 100, f"No component in model {party_model_id}:{model_version} can be converted.", None
