# Copyright (c) 2019-2020 SAP SE or an SAP affiliate company. All rights reserved. This file is
# licensed under the Apache Software License, v. 2 except as noted otherwise in the LICENSE file
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import subprocess
import yaml
import tempfile
from ensure import ensure_annotations
from collections import namedtuple
from passlib.apache import HtpasswdFile

from ci.util import (
    Failure,
    fail,
    info,
    not_empty,
    not_none,
    which,
)
from kube.client import KubernetesClient
from model.kubernetes import KubernetesConfig

CONCOURSE_HELM_CHART_REPO = "https://concourse-charts.storage.googleapis.com/"
STABLE_HELM_CHART_REPO = "https://kubernetes-charts.storage.googleapis.com/"

BasicAuthCred = namedtuple('BasicAuthCred', ['user', 'password'])


# Stuff used for yaml formatting, when dumping a dictionary
class LiteralStr(str):
    """Used to create yaml block style indicator | """


def literal_str_representer(dumper, data):
    """Used to create yaml block style indicator"""
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')


def ensure_cluster_version(kubernetes_config: KubernetesConfig):
    not_none(kubernetes_config)

    client = KubernetesClient(kubernetes_config.kubeconfig())

    cluster_version_info = client.get_cluster_version_info()
    configured_version_info = kubernetes_config.cluster_version()

    if (
        cluster_version_info.major != configured_version_info['major'] or
        cluster_version_info.minor != configured_version_info['minor']
    ):
        fail(
            'cluster version mismatch "Major: {a_major} Minor: '
            '{a_minor}". Expected "Major: {e_major} Minor: {e_minor}".'.format(
                a_major=cluster_version_info.major,
                a_minor=cluster_version_info.minor,
                e_major=configured_version_info['major'],
                e_minor=configured_version_info['minor'],
            )
        )
# pylint: enable=no-member


def ensure_helm_setup():
    """Ensure up-to-date helm installation. Return the path to the found Helm executable"""
    # we currently have both helmV3 and helmV2 in our images. To keep it convenient for local
    # execution, try both
    try:
        helm_executable = which('helm3')
    except Failure:
        info("No executable 'helm3' found in path. Falling back to 'helm'")
        helm_executable = which('helm')

    with open(os.devnull) as devnull:
        subprocess.run(
            [helm_executable, 'repo', 'add', 'concourse', CONCOURSE_HELM_CHART_REPO],
            check=True,
            stdout=devnull
        )
        subprocess.run(
            [helm_executable, 'repo', 'add', 'stable', STABLE_HELM_CHART_REPO],
            check=True,
            stdout=devnull
        )
        subprocess.run([helm_executable, 'repo', 'update'], check=True, stdout=devnull)
    return helm_executable


@ensure_annotations
def create_basic_auth_secret(
    secret_name: str,
    namespace: str,
    basic_auth_cred: BasicAuthCred=None
):
    """ Creates a secret with the configured TLS certificates in the K8s cluster.
        Optionally adds credentials for Basic Authentication"""
    not_empty(secret_name)
    not_empty(namespace)

    c = KubernetesClient()
    namespace_helper = c.namespace_helper()
    namespace_helper.create_if_absent(namespace)

    secret_helper = c.secret_helper()
    if not secret_helper.get_secret(secret_name, namespace):
        ht = HtpasswdFile()
        ht.set_password(basic_auth_cred.user, basic_auth_cred.password)
        data = {
            'auth':ht.to_string().decode('utf-8'),
        }
        secret_helper.put_secret(
            name=secret_name,
            data=data,
            namespace=namespace,
        )


def execute_helm_deployment(
    kubernetes_config: KubernetesConfig,
    namespace: str,
    chart_name: str,
    release_name: str,
    *values: dict,
    chart_version: str=None,
):
    yaml.add_representer(LiteralStr, literal_str_representer)
    helm_executable = ensure_helm_setup()
    # create namespace if absent
    c = KubernetesClient(kubeconfig_dict=kubernetes_config.kubeconfig())
    namespace_helper = c.namespace_helper()
    if not namespace_helper.get_namespace(namespace):
        namespace_helper.create_namespace(namespace)

    KUBECONFIG_FILE_NAME = "kubecfg"

    # prepare subprocess args using relative file paths for the values files
    subprocess_args = [
        helm_executable,
        "upgrade",
        release_name,
        chart_name,
        "--install",
        "--force",
        "--namespace",
        namespace,
    ]

    if chart_version:
        subprocess_args += ["--version", chart_version]

    for idx, _ in enumerate(values):
        subprocess_args.append("--values")
        subprocess_args.append("value" + str(idx))

    helm_env = os.environ.copy()
    helm_env['KUBECONFIG'] = KUBECONFIG_FILE_NAME

    # create temp dir containing all previously referenced files
    with tempfile.TemporaryDirectory() as temp_dir:
        for idx, value in enumerate(values):
            with open(os.path.join(temp_dir, "value" + str(idx)), 'w') as f:
                yaml.dump(value, f)

        with open(os.path.join(temp_dir, KUBECONFIG_FILE_NAME), 'w') as f:
            yaml.dump(kubernetes_config.kubeconfig(), f)

        # run helm from inside the temporary directory so that the prepared file paths work
        subprocess.run(subprocess_args, check=True, cwd=temp_dir, env=helm_env)
