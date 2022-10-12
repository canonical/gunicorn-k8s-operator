import pytest
import subprocess
import time
import yaml
from ops.model import ActiveStatus
from pytest_operator.plugin import OpsTest


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_psql(
    ops_test: OpsTest,
    gunicorn_image,
    statsd_exporter_image,
    influx_model_name,
):
    result = subprocess.check_output(["juju", "controllers", "--format", "yaml"])
    controller_name = next(
        filter(
            lambda item: item[1]["cloud"] == "localhost",
            yaml.safe_load(result)["controllers"].items(),
        )
    )[0]
    subprocess.check_output(["juju", "switch", controller_name])
    subprocess.check_output(["juju", "add-model", influx_model_name])
    subprocess.check_output(["juju", "deploy", "influxdb"])
    subprocess.check_output(["juju", "offer", "influxdb:query", "influxoffer"])
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
    subprocess.check_output(
        ["juju", "destroy-model", influx_model_name, "--force", "--destroy-storage", "-y"]
    )
    subprocess.check_output(["juju", "switch", "k8s-ctrl"])


async def test_status(ops_test: OpsTest):
    assert ops_test.model.applications["gunicorn-k8s"].status == ActiveStatus.name
    assert ops_test.model.applications["postgresql-k8s"].status == ActiveStatus.name


async def test_workload_psql_var(ops_test: OpsTest):
    app = ops_test.model.applications["gunicorn-k8s"]
    await app.set_config({"environment": "TEST_ENV_VAR: 1"})
    config = await app.get_config()
    assert config["environment"]["value"] == "TEST_ENV_VAR: 1"
    time.sleep(10)
    gunicorn_unit = app.units[0]
    action = await gunicorn_unit.run("curl 127.0.0.1")
    result = await action.wait()
    stdout = result.results.get("stdout")
    assert "TEST_ENV_VAR" in str(stdout)
