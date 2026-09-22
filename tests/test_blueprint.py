"""The shipped blueprint parses and validates as an automation blueprint."""

from pathlib import Path

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.util.yaml import parse_yaml

BLUEPRINT = (
    Path(__file__).parent.parent
    / "blueprints"
    / "automation"
    / "trooperthorn"
    / "cast_delivery_alert.yaml"
)


def test_blueprint_is_valid() -> None:
    """The blueprint loads with its inputs and targets the automation domain."""
    data = parse_yaml(BLUEPRINT.read_text(encoding="utf-8"))
    blueprint = Blueprint(
        data,
        expected_domain="automation",
        path=str(BLUEPRINT),
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    assert blueprint.name == "Cast delivery alert"
    assert set(blueprint.inputs) == {"notify_service", "include_probes"}
    assert blueprint.metadata["source_url"].endswith("cast_delivery_alert.yaml")
