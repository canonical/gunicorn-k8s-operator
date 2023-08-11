# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the gunicorn charm."""

import asyncio

import juju.action
import requests
from ops.model import ActiveStatus, Application
from pytest_operator.plugin import OpsTest


async def test_status(ops_test: OpsTest, app: Application):  # pylint: disable=unused-argument
    """
    arrange: given that the gunicorn application is correctly deployed
    act: when we check the status of the applications
    assert: the model should have all its charms in active state.
    """
    # We cannot make mypy recognize the applications from the model
    # or the name from ActiveStatus, so ignore mypy errors
    assert (
        ops_test.model.applications["gunicorn-k8s"].status  # type: ignore[union-attr]
        == ActiveStatus.name  # type: ignore[has-type]
    )
    assert (
        ops_test.model.applications["postgresql-k8s"].status  # type: ignore[union-attr]
        == ActiveStatus.name  # type: ignore[has-type]
    )


async def test_workload_psql_var(ops_test: OpsTest, app: Application):
    """
    arrange: given that the gunicorn application is correctly deployed
    act: when the environment config option is modified
    assert: assert that the environment variable has been correctly injected
        to the deployed charm's docker container.
    """
    app = ops_test.model.applications["gunicorn-k8s"]  # type: ignore[union-attr]
    # We cannot make mypy recognize the getters and setters of the
    # application's config or the status, so ignore mypy error
    await app.set_config(  # type: ignore[attr-defined]
        {
            "environment": (
                "APP_WSGI: 'app:app'\n"
                "APP_NAME: 'my-awesome-app'\n"
                "TEST_ENV_VAR: {{pg.db_uri}}"
            )
        }
    )
    config = await app.get_config()  # type: ignore[attr-defined]
    assert config["environment"]["value"] == "TEST_ENV_VAR: {{pg.db_uri}}"
    await asyncio.sleep(10)
    status = await ops_test.model.get_status()  # type: ignore[union-attr]
    unit = list(status.applications["gunicorn-k8s"].units)[0]
    address = status["applications"]["gunicorn-k8s"]["units"][unit]["address"]
    response = requests.get(f"http://{address}:8080", timeout=60)
    assert response.status_code == 200
    assert "TEST_ENV_VAR: postgresql://gunicorn-k8s:" in response.text


async def test_show_environment_context_action(  # pylint: disable=unused-argument
    ops_test: OpsTest, app: Application
):
    """
    arrange: given that the gunicorn application is deployed and related to another charm
    act: when the show-environment-context is ran
    assert: the action result is successful and returns the expected output
    """
    # We cannot make mypy recognize the unit from the application, so ignore mypy error
    action: juju.action.Action = await app.units[0].run_action(  # type: ignore[attr-defined]
        "show-environment-context"
    )
    await action.wait()

    assert action.status == "completed"
    assert action.results["available-variables"]
    assert "pg.db_uri" in action.results["available-variables"]
    assert "influxdb.hostname" in action.results["available-variables"]
