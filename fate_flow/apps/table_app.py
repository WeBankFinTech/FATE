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
from fate_arch import storage
from fate_flow.utils.api_utils import get_json_result
from fate_flow.settings import stat_logger
from flask import Flask, request

manager = Flask(__name__)


@manager.errorhandler(500)
def internal_server_error(e):
    stat_logger.exception(e)
    return get_json_result(retcode=100, retmsg=str(e))


@manager.route('/registry')
def table_registry():
    request_data = request.json
    address_dict = request_data.get('address')
    storage_engine = request_data.get('storage_engine')
    table_name = request_data.get('table_name')
    namespace = request_data.get('namespace')
    address = storage.StorageTableMeta.create_address(storage_engine=storage_engine, address_dict=address_dict)
    with storage.Session.build(storage_engine=storage_engine, options=request_data.get("options")) as storage_session:
        storage_session.create_table(address=address, name=table_name, namespace=namespace, partitions=request_data.get('partitions'),
                                     is_kv_storage=request_data.get('is_kv_storage', 0), is_serialize=request_data.get('is_serialize', 0))
    return get_json_result(data={"table_name": table_name, "namespace": namespace})


@manager.route('/delete', methods=['post'])
def table_delete():
    request_data = request.json
    table_name = request_data.get('table_name')
    namespace = request_data.get('namespace')
    with storage.Session.build(name=table_name, namespace=namespace) as storage_session:
        table = storage_session.get_table()
        if table:
            table.destroy()
            data = {'table_name': table_name, 'namespace': namespace}
            try:
                table.close()
            except Exception as e:
                stat_logger.exception(e)
            return get_json_result(data=data)
        else:
            return get_json_result(retcode=101, retmsg='no find table')


@manager.route('/<table_func>', methods=['post'])
def dtable(table_func):
    config = request.json
    if table_func == 'table_info':
        table_key_count = 0
        table_partition = None
        table_schema = None
        table_name, namespace = config.get("name") or config.get("table_name"), config.get("namespace")
        if config.get('create', False):
            pass
        else:
            table_meta = storage.StorageTableMeta(name=table_name, namespace=namespace)
            if table_meta:
                table_key_count = table_meta.get_count()
                table_partition = table_meta.get_partitions()
                table_schema = table_meta.get_schema()
        return get_json_result(data={'table_name': table_name, 'namespace': namespace, 'count': table_key_count, 'partition': table_partition, "schema": table_schema})
    else:
        return get_json_result()


