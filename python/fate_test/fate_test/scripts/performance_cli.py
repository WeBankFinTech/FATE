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
import json
import os
import time
import uuid
from datetime import timedelta
import click
import glob

from fate_test import _config
from fate_test._client import Clients
from fate_test._config import Config
from fate_test.utils import TxtStyle
from fate_test._flow_client import JobProgress, SubmitJobResponse, QueryJobResponse
from fate_test._io import LOGGER, echo
from prettytable import PrettyTable, ORGMODE
from fate_test._parser import JSON_STRING, Testsuite
from fate_test.scripts._options import SharedOptions
from fate_test.scripts._utils import _load_testsuites, _upload_data, _delete_data, _load_module_from_script, \
    _add_replace_hook


@click.command("performance")
@click.option('-t', '--job-type', type=click.Choice(['intersect', 'intersect_multi', 'hetero_lr', 'hetero_sbt']),
              help="Select the job type, you can also set through include")
@click.option('-i', '--include', type=click.Path(exists=True), multiple=True, metavar="<include>",
              help="include *testsuite.json under these paths")
@click.option('-r', '--replace', default="{}", type=JSON_STRING,
              help="a json string represents mapping for replacing fields in data/conf/dsl")
@click.option('-m', '--timeout', type=int, default=3600,
              help="Task timeout duration")
@click.option('-e', '--max-iter', type=int, help="When the algorithm model is LR, the number of iterations is set")
@click.option('-d', '--max-depth', type=int,
              help="When the algorithm model is SecureBoost, set the number of model layers")
@click.option('-nt', '--num-trees', type=int, help="When the algorithm model is SecureBoost, set the number of trees")
@click.option('-p', '--task-cores', type=int, help="processors per node")
@click.option('-uj', '--update-job-parameters', default="{}", type=JSON_STRING,
              help="a json string represents mapping for replacing fields in conf.job_parameters")
@click.option('-uc', '--update-component-parameters', default="{}", type=JSON_STRING,
              help="a json string represents mapping for replacing fields in conf.component_parameters")
@click.option('-s', '--storage-tag', type=str,
              help="tag for storing performance time consuming, for future comparison")
@click.option('-v', '--history-tag', type=str, multiple=True,
              help="Extract performance time consuming from history tags for comparison")
@click.option("--skip-data", is_flag=True, default=False,
              help="skip uploading data specified in testsuite")
@click.option("--disable-clean-data", "clean_data", flag_value=False, default=None)
@SharedOptions.get_shared_options(hidden=True)
@click.pass_context
def run_task(ctx, job_type, include, replace, timeout, update_job_parameters, update_component_parameters,
             max_iter, max_depth, num_trees, task_cores, storage_tag, history_tag, skip_data, clean_data, **kwargs):
    """
    Test the performance of big data tasks, alias: bp
    """
    ctx.obj.update(**kwargs)
    ctx.obj.post_process()
    config_inst = ctx.obj["config"]
    namespace = ctx.obj["namespace"]
    yes = ctx.obj["yes"]
    data_namespace_mangling = ctx.obj["namespace_mangling"]
    if clean_data is None:
        clean_data = config_inst.clean_data

    def get_perf_template(conf: Config, job_type):
        perf_dir = os.path.join(os.path.abspath(conf.perf_template_dir) + '/' + job_type + '/' + "*testsuite.json")
        return glob.glob(perf_dir)

    if not include:
        include = get_perf_template(config_inst, job_type)
    # prepare output dir and json hooks
    _add_replace_hook(replace)

    echo.welcome()
    echo.echo(f"testsuite namespace: {namespace}", fg='red')
    echo.echo("loading testsuites:")
    suites = _load_testsuites(includes=include, excludes=tuple(), glob=None)
    for i, suite in enumerate(suites):
        echo.echo(f"\tdataset({len(suite.dataset)}) dsl jobs({len(suite.jobs)}) {suite.path}")

    if not yes and not click.confirm("running?"):
        return

    echo.stdout_newline()
    with Clients(config_inst) as client:

        for i, suite in enumerate(suites):
            # noinspection PyBroadException
            try:
                start = time.time()
                echo.echo(f"[{i + 1}/{len(suites)}]start at {time.strftime('%Y-%m-%d %X')} {suite.path}", fg='red')

                if not skip_data:
                    try:
                        _upload_data(client, suite, config_inst)
                    except Exception as e:
                        raise RuntimeError(f"exception occur while uploading data for {suite.path}") from e

                echo.stdout_newline()
                try:
                    _submit_job(client, suite, namespace, config_inst, timeout, update_job_parameters, storage_tag, history_tag,
                                update_component_parameters, max_iter, max_depth, num_trees, task_cores)
                except Exception as e:
                    raise RuntimeError(f"exception occur while submit job for {suite.path}") from e

                try:
                    _run_pipeline_jobs(config_inst, suite, namespace, data_namespace_mangling)
                except Exception as e:
                    raise RuntimeError(f"exception occur while running pipeline jobs for {suite.path}") from e

                echo.echo(f"[{i + 1}/{len(suites)}]elapse {timedelta(seconds=int(time.time() - start))}", fg='red')
                if not skip_data and clean_data:
                    _delete_data(client, suite)
                echo.echo(suite.pretty_final_summary(), fg='red')

            except Exception:
                exception_id = uuid.uuid1()
                echo.echo(f"exception in {suite.path}, exception_id={exception_id}")
                LOGGER.exception(f"exception id: {exception_id}")
            finally:
                echo.stdout_newline()

    echo.farewell()
    echo.echo(f"testsuite namespace: {namespace}", fg='red')


def _submit_job(clients: Clients, suite: Testsuite, namespace: str, config: Config, timeout, update_job_parameters,
                storage_tag, history_tag, update_component_parameters, max_iter, max_depth, num_trees, task_cores):
    # submit jobs
    with click.progressbar(length=len(suite.jobs),
                           label="jobs",
                           show_eta=False,
                           show_pos=True,
                           width=24) as bar:
        for job in suite.jobs_iter():
            start = time.time()
            job_progress = JobProgress(job.job_name)

            def _raise():
                exception_id = str(uuid.uuid1())
                job_progress.exception(exception_id)
                suite.update_status(job_name=job.job_name, exception_id=exception_id)
                echo.file(f"exception({exception_id})")
                LOGGER.exception(f"exception id: {exception_id}")

            # noinspection PyBroadException
            try:
                if max_iter is not None:
                    job.job_conf.update_component_parameters('max_iter', max_iter)
                if max_depth is not None:
                    job.job_conf.update_component_parameters('max_depth', max_depth)
                if num_trees is not None:
                    job.job_conf.update_component_parameters('num_trees', num_trees)
                if task_cores is not None:
                    job.job_conf.update_job_common_parameters(task_cores=task_cores)
                job.job_conf.update(config.parties, config.work_mode, config.backend, timeout, update_job_parameters,
                                    update_component_parameters)
            except Exception:
                _raise()
                continue

            def update_bar(n_step):
                bar.item_show_func = lambda x: job_progress.show()
                time.sleep(0.1)
                bar.update(n_step)

            update_bar(1)

            def _call_back(resp: SubmitJobResponse):
                if isinstance(resp, SubmitJobResponse):
                    job_progress.submitted(resp.job_id)
                    echo.file(f"[jobs] {resp.job_id} ", nl=False)
                    suite.update_status(job_name=job.job_name, job_id=resp.job_id)

                if isinstance(resp, QueryJobResponse):
                    job_progress.running(resp.status, resp.progress)

                update_bar(0)

            # noinspection PyBroadException
            try:
                response = clients["guest_0"].submit_job(job=job, callback=_call_back)

                # noinspection PyBroadException
                try:
                    # add notes
                    notes = f"{job.job_name}@{suite.path}@{namespace}"
                    for role, party_id_list in job.job_conf.role.items():
                        for i, party_id in enumerate(party_id_list):
                            clients[f"{role}_{i}"].add_notes(job_id=response.job_id, role=role, party_id=party_id,
                                                             notes=notes)
                except Exception:
                    pass
            except Exception:
                _raise()
            else:
                job_progress.final(response.status)
                suite.update_status(job_name=job.job_name, status=response.status.status)
                if response.status.is_success():
                    if suite.model_in_dep(job.job_name):
                        dependent_jobs = suite.get_dependent_jobs(job.job_name)
                        for predict_job in dependent_jobs:
                            model_info, table_info = None, None
                            for i in _config.deps_alter[predict_job.job_name]:
                                if isinstance(i, dict):
                                    name = i.get('name')
                                    data_pre = i.get('data')

                            if 'data_deps' in _config.deps_alter[predict_job.job_name]:
                                roles = list(data_pre.keys())
                                table_info, hierarchy = [], []
                                for role_ in roles:
                                    role, index = role_.split("_")
                                    input_ = data_pre[role_]
                                    for data_input, cpn in input_.items():
                                        try:
                                            table_name = clients["guest_0"].output_data_table(
                                                job_id=response.job_id,
                                                role=role,
                                                party_id=config.role[role][int(index)],
                                                component_name=cpn)
                                        except Exception:
                                            _raise()
                                        if predict_job.job_conf.dsl_version == 2:
                                            hierarchy.append([role, index, data_input])
                                            table_info.append({'table': table_name})
                                        else:
                                            hierarchy.append([role, 'args', 'data'])
                                            table_info.append({data_input: [table_name]})
                                table_info = {'hierarchy': hierarchy, 'table_info': table_info}
                            if 'model_deps' in _config.deps_alter[predict_job.job_name]:
                                if predict_job.job_conf.dsl_version == 2:
                                    # noinspection PyBroadException
                                    try:
                                        model_info = clients["guest_0"].deploy_model(
                                            model_id=response.model_info["model_id"],
                                            model_version=response.model_info["model_version"],
                                            dsl=predict_job.job_dsl.as_dict())
                                    except Exception:
                                        _raise()
                                else:
                                    model_info = response.model_info

                            suite.feed_dep_info(predict_job, name, model_info=model_info, table_info=table_info)
            update_bar(0)
            time_consuming = time.time() - start
            performance_dir = "/".join(
                [os.path.join(os.path.abspath(config.cache_directory), 'benchmark_history', "performance.json")])
            fate_version = clients["guest_0"].get_version()
            if history_tag:
                history_tag = ["_".join([i, job.job_name]) for i in history_tag]
                comparison_quality(job.job_name, history_tag, performance_dir, time_consuming)
            if storage_tag:
                storage_tag = "_".join(['FATE', fate_version, storage_tag, job.job_name])
                save_quality(storage_tag, performance_dir, time_consuming)
            echo.stdout_newline()


def _run_pipeline_jobs(config: Config, suite: Testsuite, namespace: str, data_namespace_mangling: bool):
    # pipeline demo goes here
    job_n = len(suite.pipeline_jobs)
    for i, pipeline_job in enumerate(suite.pipeline_jobs):
        echo.echo(f"Running [{i + 1}/{job_n}] job: {pipeline_job.job_name}")

        def _raise(err_msg, status="failed"):
            exception_id = str(uuid.uuid1())
            suite.update_status(job_name=job_name, exception_id=exception_id, status=status)
            echo.file(f"exception({exception_id}), error message:\n{err_msg}")
            # LOGGER.exception(f"exception id: {exception_id}")

        job_name, script_path = pipeline_job.job_name, pipeline_job.script_path
        mod = _load_module_from_script(script_path)
        try:
            if data_namespace_mangling:
                try:
                    mod.main(config=config, namespace=f"_{namespace}")
                    suite.update_status(job_name=job_name, status="success")
                except Exception as e:
                    _raise(e)
                    continue
            else:
                try:
                    mod.main(config=config)
                    suite.update_status(job_name=job_name, status="success")
                except Exception as e:
                    _raise(e)
                    continue
        except Exception as e:
            _raise(e, status="not submitted")
            continue


def comparison_quality(group_name, history_tags, history_info_dir, time_consuming):
    assert os.path.exists(history_info_dir), f"Please check the {history_info_dir} Is it deleted"
    with open(history_info_dir, 'r') as f:
        benchmark_quality = json.load(f, object_hook=dict)
    benchmark_performance = {}
    for history_tag in history_tags:
        for tag in benchmark_quality:
            if '_'.join(tag.split("_")[2:]) == history_tag:
                benchmark_performance[tag] = benchmark_quality[tag]
    if benchmark_performance is not None:
        benchmark_performance[group_name] = time_consuming

    table = PrettyTable()
    table.set_style(ORGMODE)
    table.field_names = ["Script Model Name", "time consuming"]
    for script_model_name in benchmark_performance:
        table.add_row([f"{script_model_name}"] +
                      [f"{TxtStyle.FIELD_VAL}{benchmark_performance[script_model_name]}{TxtStyle.END}"])
    print("\n")
    print(table.get_string(title=f"{TxtStyle.TITLE}Performance comparison results{TxtStyle.END}"))


def save_quality(storage_tag, save_dir, time_consuming):
    os.makedirs(os.path.dirname(save_dir), exist_ok=True)
    if os.path.exists(save_dir):
        with open(save_dir, 'r') as f:
            benchmark_quality = json.load(f, object_hook=dict)
    else:
        benchmark_quality = {}
    benchmark_quality.update({storage_tag: time_consuming})
    try:
        with open(save_dir, 'w') as fp:
            json.dump(benchmark_quality, fp, indent=2)
        print("\n" + "Storage successful, please check: ", save_dir)
    except Exception:
        print("\n" + "Storage failed, please check: ", save_dir)
