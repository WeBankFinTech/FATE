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

from colorama import init, deinit, Fore, Style
import math
import numpy as np

from prettytable import PrettyTable, ORGMODE

SCRIPT_METRICS = "script_metrics"
DISTRIBUTION_METRICS = "distribution_metrics"


class TxtStyle:
    TRUE_VAL = Fore.GREEN
    FALSE_VAL = Fore.RED + Style.BRIGHT
    TITLE = Fore.BLUE
    FIELD_VAL = Fore.YELLOW
    DATA_FIELD_VAL = Fore.CYAN
    END = Style.RESET_ALL


def show_data(data):
    data_table = PrettyTable()
    data_table.set_style(ORGMODE)
    data_table.field_names = ["Data", "Information"]
    for name, table_name in data.items():
        row = [name, f"{TxtStyle.DATA_FIELD_VAL}{table_name}{TxtStyle.END}"]
        data_table.add_row(row)
    print(data_table.get_string(title=f"{TxtStyle.TITLE}Data Summary{TxtStyle.END}"))
    print("\n")


def _get_common_metrics(**results):
    common_metrics = None
    for result in results.values():
        if common_metrics is None:
            common_metrics = set(result.keys())
        else:
            common_metrics = common_metrics & result.keys()
    if SCRIPT_METRICS in common_metrics:
        common_metrics.remove(SCRIPT_METRICS)
    return list(common_metrics)


def _filter_results(metrics, **results):
    filtered_results = {}
    for model_name, result in results.items():
        model_result = [result.get(metric, None) for metric in metrics]
        if None in model_result:
            continue
        filtered_results[model_name] = model_result
    return filtered_results


def style_table(txt):
    colored_txt = txt.replace("True", f"{TxtStyle.TRUE_VAL}True{TxtStyle.END}")
    colored_txt = colored_txt.replace("False", f"{TxtStyle.FALSE_VAL}False{TxtStyle.END}")
    return colored_txt


def evaluate_almost_equal(metrics, results, abs_tol=None, rel_tol=None):
    """
    Evaluate for each given metric if values in results are almost equal
    Parameters
    ----------
    metrics: List[str], metrics names
    results: dict, results to be evaluated
    abs_tol: float, absolute error tolerance
    rel_tol: float, relative difference tolerance
    Returns
    -------
    bool, return True if all metrics in results are almost equal
    """
    # return False if empty
    if len(metrics) == 0:
        return False
    eval_summary = {}
    for i, metric in enumerate(metrics):
        v_eval = [res[i] for res in results.values()]
        first_v = v_eval[0]
        if metric == SCRIPT_METRICS:
            continue
        if abs_tol is not None and rel_tol is not None:
            eval_summary[metric] = all(math.isclose(v, first_v, abs_tol=abs_tol, rel_tol=rel_tol) for v in v_eval)
        elif abs_tol is not None:
            eval_summary[metric] = all(math.isclose(v, first_v, abs_tol=abs_tol) for v in v_eval)
        elif rel_tol is not None:
            eval_summary[metric] = all(math.isclose(v, first_v, rel_tol=rel_tol) for v in v_eval)
        else:
            eval_summary[metric] = all(math.isclose(v, first_v) for v in v_eval)
    all_match = all(eval_summary.values())
    return eval_summary, all_match


def _distribution_metrics(**results):
    filtered_metric_group = _filter_results([DISTRIBUTION_METRICS], **results)
    for script, model_results_pair in filtered_metric_group.items():
        metric_results = model_results_pair[0]
        common_metrics = _get_common_metrics(**metric_results)
        filtered_results = _filter_results(common_metrics, **metric_results)
        table = PrettyTable()
        table.set_style(ORGMODE)
        script_model_names = list(filtered_results.keys())
        table.field_names = ["Script Model Name"] + common_metrics
        for script_model_name in script_model_names:
            row = [f"{script}-{script_model_name}"] + [f"{TxtStyle.FIELD_VAL}{v}{TxtStyle.END}" for v in
                                                       filtered_results[script_model_name]]
            table.add_row(row)
        print(table.get_string(title=f"{TxtStyle.TITLE}{script} distribution metrics{TxtStyle.END}"))
        print("\n" + "#" * 60)


def match_script_metrics(abs_tol, rel_tol, **results):
    filtered_metric_group = _filter_results([SCRIPT_METRICS], **results)
    for script, model_results_pair in filtered_metric_group.items():
        metric_results = model_results_pair[0]
        common_metrics = _get_common_metrics(**metric_results)
        filtered_results = _filter_results(common_metrics, **metric_results)
        table = PrettyTable()
        table.set_style(ORGMODE)
        script_model_names = list(filtered_results.keys())
        table.field_names = ["Script Model Name"] + common_metrics
        for script_model_name in script_model_names:
            row = [f"{script_model_name}-{script}"] + [f"{TxtStyle.FIELD_VAL}{v}{TxtStyle.END}" for v in
                                                       filtered_results[script_model_name]]
            table.add_row(row)
        print(table.get_string(title=f"{TxtStyle.TITLE}{script} Script Metrics Summary{TxtStyle.END}"))
        _all_match(common_metrics, filtered_results, abs_tol, rel_tol, script)
        print("\n" + "#" * 60)


def match_metrics(evaluate, group_name, abs_tol=None, rel_tol=None, storage_tag=None, history_tag=None,
                  fate_version=None, cache_directory=None, **results):
    """
    Get metrics
    Parameters
    ----------
    evaluate: bool, whether to evaluate metrics are almost equal, and include compare results in output report
    group_name: str, group name of all models
    abs_tol: float, max tolerance of absolute error to consider two metrics to be almost equal
    rel_tol: float, max tolerance of relative difference to consider two metrics to be almost equal
    storage_tag: str, metrics information storage tag
    history_tag: str, historical metrics information comparison tag
    fate_version: str, FATE version
    cache_directory: str, Storage path of metrics information
    results: dict of model name: metrics
    Returns
    -------
    match result
    """
    init(autoreset=True)
    common_metrics = _get_common_metrics(**results)
    filtered_results = _filter_results(common_metrics, **results)
    table = PrettyTable()
    table.set_style(ORGMODE)
    model_names = list(filtered_results.keys())
    table.field_names = ["Model Name"] + common_metrics
    for model_name in model_names:
        row = [f"{model_name}-{group_name}"] + [f"{TxtStyle.FIELD_VAL}{v}{TxtStyle.END}" for v in
                                                filtered_results[model_name]]
        table.add_row(row)
    print(table.get_string(title=f"{TxtStyle.TITLE}Metrics Summary{TxtStyle.END}"))

    if evaluate and len(filtered_results.keys()) > 1:
        _all_match(common_metrics, filtered_results, abs_tol, rel_tol)

    _distribution_metrics(**results)
    match_script_metrics(abs_tol, rel_tol, **results)
    if history_tag:
        history_tag = ["_".join([i, group_name]) for i in history_tag]
        comparison_quality(group_name, history_tag, cache_directory, abs_tol, rel_tol, **results)
    if storage_tag:
        storage_tag = "_".join(['FATE', fate_version, storage_tag, group_name])
        _save_quality(storage_tag, cache_directory, **results)
    deinit()


def _all_match(common_metrics, filtered_results, abs_tol, rel_tol, script=None):
    eval_summary, all_match = evaluate_almost_equal(common_metrics, filtered_results, abs_tol, rel_tol)
    eval_table = PrettyTable()
    eval_table.set_style(ORGMODE)
    eval_table.field_names = ["Metric", "All Match"]
    for metric, v in eval_summary.items():
        row = [metric, v]
        eval_table.add_row(row)

    print(style_table(eval_table.get_string(title=f"{TxtStyle.TITLE}Match Results{TxtStyle.END}")))
    script = "" if script is None else f"{script} "
    if all_match:
        print(f"All {script}Metrics Match: {TxtStyle.TRUE_VAL}{all_match}{TxtStyle.END}")
    else:
        print(f"All {script}Metrics Match: {TxtStyle.FALSE_VAL}{all_match}{TxtStyle.END}")


def comparison_quality(group_name, history_tags, cache_directory, abs_tol, rel_tol, **results):
    def regression_group(results_dict):
        metric = {}
        for k, v in results_dict.items():
            if not isinstance(v, dict):
                metric[k] = v
        return metric

    def class_group(class_dict):
        metric = {}
        for k, v in class_dict.items():
            if not isinstance(v, dict):
                metric[k] = v
        for k, v in class_dict['distribution_metrics'].items():
            metric.update(v)
        return metric

    history_info_dir = "/".join([os.path.join(os.path.abspath(cache_directory), 'benchmark_history',
                                              "benchmark_quality.json")])
    assert os.path.exists(history_info_dir), f"Please check the {history_info_dir} Is it deleted"
    with open(history_info_dir, 'r') as f:
        benchmark_quality = json.load(f, object_hook=dict)
    regression_metric = {}
    regression_quality = {}
    class_quality = {}
    for history_tag in history_tags:
        for tag in benchmark_quality:
            if '_'.join(tag.split("_")[2:]) == history_tag and SCRIPT_METRICS in results["FATE"]:
                regression_metric[tag] = regression_group(benchmark_quality[tag]['FATE'])
                for key, value in _filter_results([SCRIPT_METRICS], **benchmark_quality[tag])['FATE'][0].items():
                    regression_quality["_".join([tag, key])] = value
            elif '_'.join(tag.split("_")[2:]) == history_tag and DISTRIBUTION_METRICS in results["FATE"]:
                class_quality[tag] = class_group(benchmark_quality[tag]['FATE'])

    if SCRIPT_METRICS in results["FATE"] and regression_metric:
        print()
        regression_metric[group_name] = regression_group(results['FATE'])
        metric_compare(abs_tol, rel_tol, **regression_metric)
        for key, value in _filter_results([SCRIPT_METRICS], **results)['FATE'][0].items():
            regression_quality["_".join([group_name, key])] = value
        metric_compare(abs_tol, rel_tol, **regression_quality)
        print("\n" + "#" * 60)
    elif DISTRIBUTION_METRICS in results["FATE"] and class_quality:

        class_quality[group_name] = class_group(results['FATE'])
        metric_compare(abs_tol, rel_tol, **class_quality)
        print("\n" + "#" * 60)


def metric_compare(abs_tol, rel_tol, **metric_results):
    common_metrics = _get_common_metrics(**metric_results)
    filtered_results = _filter_results(common_metrics, **metric_results)
    table = PrettyTable()
    table.set_style(ORGMODE)
    script_model_names = list(filtered_results.keys())
    table.field_names = ["Script Model Name"] + common_metrics
    for script_model_name in script_model_names:
        table.add_row([f"{script_model_name}"] +
                      [f"{TxtStyle.FIELD_VAL}{v}{TxtStyle.END}" for v in filtered_results[script_model_name]])
    print(table.get_string(title=f"{TxtStyle.TITLE}Comparison results of all metrics of Script Model FATE{TxtStyle.END}"))
    _all_match(common_metrics, filtered_results, abs_tol, rel_tol)


def _save_quality(storage_tag, cache_directory, **results):
    save_dir = "/".join([os.path.join(os.path.abspath(cache_directory), 'benchmark_history', "benchmark_quality.json")])
    os.makedirs(os.path.dirname(save_dir), exist_ok=True)
    if os.path.exists(save_dir):
        with open(save_dir, 'r') as f:
            benchmark_quality = json.load(f, object_hook=dict)
    else:
        benchmark_quality = {}
    benchmark_quality.update({storage_tag: results})
    try:
        with open(save_dir, 'w') as fp:
            json.dump(benchmark_quality, fp, indent=2)
        print("Storage success, please check: ", save_dir)
    except Exception:
        print("Storage failed, please check: ", save_dir)


def parse_summary_result(rs_dict):
    for model_key in rs_dict:
        rs_content = rs_dict[model_key]
        if 'validate' in rs_content:
            return rs_content['validate']
        else:
            return rs_content['train']


def extract_data(txt, col_name, convert_float=True, keep_id=False):
    """
    convert list of string from component output data to array
    Parameters
    ----------
    txt: data in list of string
    col_name: column to extract
    convert_float: whether to convert extracted value to float value
    keep_id: whether to keep id
    Returns
    -------
    array of extracted data, optionally with id
    """
    header = txt[0].split(",")
    data = []
    col_name_loc = header.index(col_name)
    for entry in txt[1:]:
        entry_list = entry.split(",")
        extract_val = entry_list[col_name_loc]
        if convert_float:
            extract_val = float(extract_val)
        if keep_id:
            data.append((entry_list[0], extract_val))
        else:
            data.append(extract_val)
    return np.array(data)
