import pytest
from ops.model import ActiveStatus
from pytest_operator.plugin import OpsTest

@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    charm = await ops_test.build_charm(".")
    resources = {
        "gunicorn-image": "gunicorncharmers/gunicorn-app:20.0.4-20.04_edge"
    }
    await ops_test.model.deploy(charm, resources=resources)
    await ops_test.model.wait_for_idle(status=ActiveStatus.name)