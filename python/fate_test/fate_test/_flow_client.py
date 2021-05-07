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
import os
import json
import time
import typing
from datetime import timedelta
from pathlib import Path

import requests
from fate_test._parser import Data, Job
from flow_sdk.client import FlowClient
from fate_test import _config


class FLOWClient(object):

    def __init__(self,
                 address: typing.Optional[str],
                 data_base_dir: typing.Optional[Path],
                 cache_directory: typing.Optional[Path]):
        self.address = address
        self.version = "v1"
        self._http = requests.Session()
        self._data_base_dir = data_base_dir
        self._cache_directory = cache_directory
        self.data_size = 0

    def set_address(self, address):
        self.address = address

    def upload_data(self, data: Data, callback=None, output_path=None):
        try:
            response, data_path = self._upload_data(conf=data.config, output_path=output_path, verbose=0, drop=1)
            if callback is not None:
                callback(response)
            status = self._awaiting(response.job_id, "local")
            response.status = status
        except Exception as e:
            raise RuntimeError(f"upload data failed") from e
        return response, data_path

    def delete_data(self, data: Data):
        try:
            self._delete_data(table_name=data.config['table_name'], namespace=data.config['namespace'])
        except Exception as e:
            raise RuntimeError(f"delete data failed") from e

    def submit_job(self, job: Job, callback=None) -> 'SubmitJobResponse':
        try:
            response = self._submit_job(**job.submit_params)
            if callback is not None:
                callback(response)
            status = self._awaiting(response.job_id, "guest", callback)
            response.status = status

        except Exception as e:
            raise RuntimeError(f"submit job failed") from e
        return response

    def deploy_model(self, model_id, model_version, dsl=None):
        result = self._deploy_model(model_id=model_id, model_version=model_version, dsl=dsl)
        return result

    def output_data_table(self, job_id, role, party_id, component_name):
        result = self._output_data_table(job_id=job_id, role=role, party_id=party_id, component_name=component_name)
        return result

    def add_notes(self, job_id, role, party_id, notes):
        self._add_notes(job_id=job_id, role=role, party_id=party_id, notes=notes)

    def check_connection(self):
        try:
            version = self._http.request(method="POST", url=f"{self._base}version/get", json={"module": "FATE"},
                                         timeout=2).json()
        except Exception:
            import traceback
            traceback.print_exc()
            raise
        fate_version = version.get("data", {}).get("FATE")
        if fate_version:
            return fate_version, self.address

        raise EnvironmentError(f"connection not ok")

    def _awaiting(self, job_id, role, callback=None):
        while True:
            response = self._query_job(job_id, role=role)
            if response.status.is_done():
                return response.status
            if callback is not None:
                callback(response)
            time.sleep(1)

    def _save_json(self, file, file_name):
        file = json.dumps(file, indent=4)
        file_path = os.path.join(str(self._cache_directory), file_name)
        try:
            with open(file_path, "w", encoding='utf-8') as f:
                f.write(file)
        except Exception as e:
            raise Exception(f"write error==>{e}")
        return file_path

    def _upload_data(self, conf, output_path=None, verbose=0, drop=1):
        if output_path is not None:
            conf['file'] = os.path.join(os.path.abspath(output_path), os.path.basename(conf.get('file')))
        else:
            if _config.data_switch is not None:
                conf['file'] = os.path.join(str(self._cache_directory), os.path.basename(conf.get('file')))
            else:
                conf['file'] = os.path.join(str(self._data_base_dir), conf.get('file'))
        path = Path(conf.get('file'))
        if not path.is_file():
            path = self._data_base_dir.joinpath(conf.get('file')).resolve()

        if not path.exists():
            raise Exception('The file is obtained from the fate flow client machine, but it does not exist, '
                            f'please check the path: {path}')
        upload_response = self.flow_client(request='data/upload', param=self._save_json(conf, 'upload_conf.json'),
                                           verbose=verbose, drop=drop)
        response = UploadDataResponse(upload_response)
        return response, conf['file']

    def _delete_data(self, table_name, namespace):
        param = {
            'table_name': table_name,
            'namespace': namespace
        }
        response = self.flow_client(request='table/delete', param=param)
        return response

    def _submit_job(self, conf, dsl):
        param = {
            'job_dsl': self._save_json(dsl, 'submit_dsl.json'),
            'job_runtime_conf': self._save_json(conf, 'submit_conf.json')
        }
        response = SubmitJobResponse(self.flow_client(request='job/submit', param=param))
        return response

    def _deploy_model(self, model_id, model_version, dsl=None):
        post_data = {'model_id': model_id,
                     'model_version': model_version,
                     'predict_dsl': dsl}
        response = self.flow_client(request='model/deploy', param=post_data)
        result = {}
        try:
            retcode = response['retcode']
            retmsg = response['retmsg']
            if retcode != 0 or retmsg != 'success':
                raise RuntimeError(f"deploy model error: {response}")
            result["model_id"] = response["data"]["model_id"]
            result["model_version"] = response["data"]["model_version"]
        except Exception as e:
            raise RuntimeError(f"deploy model error: {response}") from e

        return result

    def _output_data_table(self, job_id, role, party_id, component_name):
        post_data = {'job_id': job_id,
                     'role': role,
                     'party_id': party_id,
                     'component_name': component_name}
        response = self.flow_client(request='component/output_data_table', param=post_data)
        result = {}
        try:
            retcode = response['retcode']
            retmsg = response['retmsg']
            if retcode != 0 or retmsg != 'success':
                raise RuntimeError(f"deploy model error: {response}")
            result["name"] = response["data"][0]["table_name"]
            result["namespace"] = response["data"][0]["table_namespace"]
        except Exception as e:
            raise RuntimeError(f"output data table error: {response}") from e
        return result

    def _query_job(self, job_id, role):
        param = {
            'job_id': job_id,
            'role': role
        }
        response = QueryJobResponse(self.flow_client(request='job/query', param=param))
        return response

    def get_version(self):
        response = self._post(url='version/get', json={"module": "FATE"})
        try:
            retcode = response['retcode']
            retmsg = response['retmsg']
            if retcode != 0 or retmsg != 'success':
                raise RuntimeError(f"get version error: {response}")
            fate_version = response["data"]["FATE"]
        except Exception as e:
            raise RuntimeError(f"get version error: {response}") from e
        return fate_version

    def _add_notes(self, job_id, role, party_id, notes):
        data = dict(job_id=job_id, role=role, party_id=party_id, notes=notes)
        response = AddNotesResponse(self._post(url='job/update', json=data))
        return response

    @property
    def _base(self):
        return f"http://{self.address}/{self.version}/"

    def _post(self, url, **kwargs) -> dict:
        request_url = self._base + url
        try:
            response = self._http.request(method='post', url=request_url, **kwargs)
        except Exception as e:
            raise RuntimeError(f"post {url} with {kwargs} failed") from e

        try:
            if isinstance(response, requests.models.Response):
                response = response.json()
            else:
                try:
                    response = json.loads(response.content.decode('utf-8', 'ignore'), strict=False)
                except (TypeError, ValueError):
                    return response
        except json.decoder.JSONDecodeError:
            response = {'retcode': 100,
                        'retmsg': "Internal server error. Nothing in response. You may check out the configuration in "
                                  "'FATE/conf/service_conf.yaml' and restart fate flow server."}
        return response

    def flow_client(self, request, param, verbose=0, drop=0):
        client = FlowClient(self.address.split(':')[0], self.address.split(':')[1], self.version)
        if request == 'data/upload':
            stdout = client.data.upload(conf_path=param, verbose=verbose, drop=drop)
        elif request == 'table/delete':
            stdout = client.table.delete(table_name=param['table_name'], namespace=param['namespace'])
        elif request == 'job/submit':
            stdout = client.job.submit(conf_path=param['job_runtime_conf'], dsl_path=param['job_dsl'])
        elif request == 'job/query':
            stdout = client.job.query(job_id=param['job_id'], role=param['role'])
        elif request == 'model/deploy':
            stdout = client.model.deploy(model_id=param['model_id'], model_version=param['model_version'],
                                         predict_dsl=param['predict_dsl'])
        elif request == 'component/output_data_table':
            stdout = client.component.output_data_table(job_id=param['job_id'], role=param['role'],
                                                        party_id=param['party_id'],
                                                        component_name=param['component_name'])

        else:
            stdout = {"retcode": None}

        status = stdout["retcode"]
        if status != 0:
            if request == 'table/delete' and stdout["retmsg"] == "no find table":
                return stdout
            raise ValueError({'retcode': 100, 'retmsg': stdout["retmsg"]})

        return stdout


class Status(object):
    def __init__(self, status: str):
        self.status = status

    def is_done(self):
        return self.status.lower() in ['complete', 'success', 'canceled', 'failed', "timeout"]

    def is_success(self):
        return self.status.lower() in ['complete', 'success']

    def __str__(self):
        return self.status

    def __repr__(self):
        return self.__str__()


class QueryJobResponse(object):
    def __init__(self, response: dict):
        try:
            status = Status(response.get('data')[0]["f_status"])
            progress = response.get('data')[0]['f_progress']
        except Exception as e:
            raise RuntimeError(f"query job error, response: {response}") from e
        self.status = status
        self.progress = progress


class UploadDataResponse(object):
    def __init__(self, response: dict):
        try:
            self.job_id = response["jobId"]
        except Exception as e:
            raise RuntimeError(f"upload error, response: {response}") from e
        self.status: typing.Optional[Status] = None


class AddNotesResponse(object):
    def __init__(self, response: dict):
        try:
            retcode = response['retcode']
            retmsg = response['retmsg']
            if retcode != 0 or retmsg != 'success':
                raise RuntimeError(f"add notes error: {response}")
        except Exception as e:
            raise RuntimeError(f"add notes error: {response}") from e


class SubmitJobResponse(object):
    def __init__(self, response: dict):
        try:
            self.job_id = response["jobId"]
            self.model_info = response["data"]["model_info"]
        except Exception as e:
            raise RuntimeError(f"submit job error, response: {response}") from e
        self.status: typing.Optional[Status] = None


class DataProgress(object):
    def __init__(self, role_str):
        self.role_str = role_str
        self.start = time.time()
        self.show_str = f"[{self.elapse()}] {self.role_str}"
        self.job_id = ""

    def elapse(self):
        return f"{timedelta(seconds=int(time.time() - self.start))}"

    def submitted(self, job_id):
        self.job_id = job_id
        self.show_str = f"[{self.elapse()}]{self.job_id} {self.role_str}"

    def update(self):
        self.show_str = f"[{self.elapse()}]{self.job_id} {self.role_str}"

    def show(self):
        return self.show_str


class JobProgress(object):
    def __init__(self, name):
        self.name = name
        self.start = time.time()
        self.show_str = f"[{self.elapse()}] {self.name}"
        self.job_id = ""

    def elapse(self):
        return f"{timedelta(seconds=int(time.time() - self.start))}"

    def submitted(self, job_id):
        self.job_id = job_id
        self.show_str = f"[{self.elapse()}]{self.job_id} submitted {self.name}"

    def running(self, status, progress):
        if progress is None:
            progress = 0
        self.show_str = f"[{self.elapse()}]{self.job_id} {status} {progress:3}% {self.name}"

    def exception(self, exception_id):
        self.show_str = f"[{self.elapse()}]{self.name} exception({exception_id}): {self.job_id}"

    def final(self, status):
        self.show_str = f"[{self.elapse()}]{self.job_id} {status} {self.name}"

    def show(self):
        return self.show_str
