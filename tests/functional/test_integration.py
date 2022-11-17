import asyncio

import juju.action
import requests
from ops.model import ActiveStatus, Application
from pytest_operator.plugin import OpsTest


async def test_status(ops_test: OpsTest, app: Application):
    """
    arrange: given that the gunicorn application is correctly deployed
    act: when we check the status of the applications
    assert: the model should have all its charms in active state.
    """
    assert ops_test.model.applications["gunicorn-k8s"].status == ActiveStatus.name
    assert ops_test.model.applications["postgresql-k8s"].status == ActiveStatus.name


async def test_workload_psql_var(ops_test: OpsTest, app: Application):
    """
    arrange: given that the gunicorn application is correctly deployed
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
    response = requests.get(f"http://{address}:8080")
    assert response.status_code == 200
    assert "TEST_ENV_VAR: postgresql://gunicorn-k8s:" in response.text


async def test_show_environment_context_action(ops_test: OpsTest, app: Application):
    """
    arrange: given that the gunicorn application is deployed and related to another charm
    act: when the show-environment-context is ran
    assert: the action result is successful and returns the expected output
    """
    action: juju.action.Action = await app.units[0].run_action("show-environment-context")
    await action.wait()

    assert action.status == "completed"
    assert action.results['available-variables']
    assert "pg.db_uri" in action.results['available-variables']
    assert "influxdb.hostname" in action.results['available-variables']
