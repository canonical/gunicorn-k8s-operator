from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from ops.model import ActiveStatus
from pytest_operator.plugin import OpsTest


@pytest.fixture(scope="module")
def metadata():
    """Provides charm metadata."""
    yield yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.fixture(scope="module")
def gunicorn_image(pytestconfig: pytest.Config):
    """Get the gunicorn image."""
    value: None | str = pytestconfig.getoption("--gunicorn-image")
    assert value is not None, "please specify the --gunicorn-image command line option"
    return value


@pytest.fixture(scope="module")
def statsd_exporter_image(metadata):
    """Provides the statsd prometheus exporter image from the metadata."""
    yield metadata["resources"]["statsd-prometheus-exporter-image"]["upstream-source"]


@pytest.fixture(scope="module")
def influx_model_name():
    """Get influx's model name for testing."""
    return "influxdbmodel"


@pytest_asyncio.fixture(scope="module")
async def app(
    ops_test: OpsTest,
    gunicorn_image: str,
    statsd_exporter_image: str,
    influx_model_name: str,
):
    """
    arrange: given a development version of the gunicorn charm
    act: deploy it with postgresql-k8s (same model) and influxdb (cross-model/controller),
        and relate them.
    assert: the build and deploy process should end correctly.
    """
    result = await ops_test.juju("controllers", "--format", "yaml")
    result_stdout = result[1]
    controller_name = next(
        filter(
            lambda item: item[1]["cloud"] == "localhost",
            yaml.safe_load(result_stdout)["controllers"].items(),
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
    application = await ops_test.model.deploy(charm, resources=resources, series="focal")
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

    yield application
