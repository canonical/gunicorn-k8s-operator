import asyncio
import subprocess

import pytest
import requests
import yaml
from ops.model import ActiveStatus
from pytest_operator.plugin import OpsTest


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_psql(
    ops_test: OpsTest,
    gunicorn_image: str,
    statsd_exporter_image: str,
    influx_model_name: str,
):
    """
    arrange: given a development version of the gunicorn charm
    act: deploy it with postgresql-k8s (same model) and influxdb (cross-model/controller),
    and relate them.
    """
    result = subprocess.check_output(["juju", "controllers", "--format", "yaml"])
    controller_name = next(
        filter(
            lambda item: item[1]["cloud"] == "localhost",
            yaml.safe_load(result)["controllers"].items(),
        )
    )[0]
    await ops_test.juju(
        "add-model",
        influx_model_name,
        "--controller",
        controller_name,
        check=True,
    )
    await ops_test.juju(
        "deploy",
        "influxdb",
        "--model",
        f"{controller_name}:{influx_model_name}",
        check=True,
    )
    await ops_test.juju(
        "offer",
        "influxdb:query",
        "influxoffer",
        "--controller",
        controller_name,
        check=True,
    )
    charm = await ops_test.build_charm(".")
    resources = {
        "gunicorn-image": gunicorn_image,
        "statsd-prometheus-exporter-image": statsd_exporter_image,
    }
    await ops_test.model.deploy(charm, resources=resources, series="focal")
    await ops_test.model.deploy("postgresql-k8s")
    await ops_test.model.add_relation(
        "postgresql-k8s:db",
        "gunicorn-k8s:pg",
    )
    await ops_test.juju(
        "relate",
        "gunicorn-k8s:influxdb",
        f"{controller_name}:admin/{influx_model_name}.influxoffer",
        check=True,
    )
    await ops_test.model.wait_for_idle(status=ActiveStatus.name, raise_on_error=False)
    await ops_test.juju(
        "destroy-model",
        f"{controller_name}:{influx_model_name}",
        "--force",
        "--destroy-storage",
        "-y",
    )


async def test_status(ops_test: OpsTest):
    """
    arrange: given the resulting juju model of the first test
    assert: the model should have all its charms in active state.
    """
    assert ops_test.model.applications["gunicorn-k8s"].status == ActiveStatus.name
    assert ops_test.model.applications["postgresql-k8s"].status == ActiveStatus.name


async def test_workload_psql_var(ops_test: OpsTest):
    """
    arrange: given the resulting juju model of the first test
    act: when the environment config option is modified
    assert: assert that the environment variable has been correctly injected
    to the deployed charm's docker container.
    """
    app = ops_test.model.applications["gunicorn-k8s"]
    await app.set_config({"environment": "TEST_ENV_VAR: {{pg.db_uri}}"})
    config = await app.get_config()
    assert config["environment"]["value"] == "TEST_ENV_VAR: {{pg.db_uri}}"
    await asyncio.sleep(10)
    status = await ops_test.model.get_status()
    unit = list(status.applications["gunicorn-k8s"].units)[0]
    address = status["applications"]["gunicorn-k8s"]["units"][unit]["address"]
    response = requests.get(f"http://{address}")
    assert response.status_code == 200
    assert "TEST_ENV_VAR" in response.text
