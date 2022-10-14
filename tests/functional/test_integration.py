import asyncio

import requests
from ops.model import ActiveStatus, Application
from pytest_operator.plugin import OpsTest


async def test_status(ops_test: OpsTest, app: Application):
    """
    arrange: given the resulting juju model of the first test
    act: when we check the status of the applications
    assert: the model should have all its charms in active state.
    """
    assert ops_test.model.applications["gunicorn-k8s"].status == ActiveStatus.name
    assert ops_test.model.applications["postgresql-k8s"].status == ActiveStatus.name


async def test_workload_psql_var(ops_test: OpsTest, app: Application):
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
