# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for Gunicorn charm integration tests."""

# pylint: disable=redefined-outer-name
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from ops.model import ActiveStatus
from pytest_operator.plugin import OpsTest


@pytest.fixture(scope="module")
def metadata():
    """Provides charm metadata."""
    yield yaml.safe_load(Path("./metadata.yaml").read_text("utf-8"))


@pytest.fixture(scope="module")
def influx_model_name():
    """Get influx's model name for testing."""
    return "influxdbmodel"


@pytest_asyncio.fixture(scope="module")
async def app(
    ops_test: OpsTest,
    influx_model_name: str,
    pytestconfig: pytest.Config,
):
    """
    Gunicorn charm used for integration testing.
    Builds the charm, deployes it and adds relations for testing purposes.
    """
    result = await ops_test.juju("controllers", "--format", "yaml")
    result_stdout = result[1]
    controller_name = next(
        filter(
            lambda item: item[1]["cloud"] == "localhost",
            yaml.safe_load(result_stdout)["controllers"].items(),
        ),
        "localhost",
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
        "--channel",
        "edge",
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
    resources = {
        "gunicorn-image": pytestconfig.getoption("--gunicorn-image"),
    }
    assert ops_test.model
    charm = pytestconfig.getoption("--charm-file")
    application = await ops_test.model.deploy(f"./{charm}", resources=resources, series="focal")
    await ops_test.model.deploy("postgresql-k8s", channel="latest/stable", series="focal")
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
    # mypy has difficulty with ActiveStatus
    expected_status = ActiveStatus.name  # type: ignore
    await ops_test.model.wait_for_idle(status=expected_status, raise_on_error=False)

    yield application
