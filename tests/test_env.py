import pytest

from placeholder_helper.env import MappingPropertySource, StandardEnvironment


@pytest.fixture(scope="session")
def environment() -> StandardEnvironment:
    return StandardEnvironment()


def test_merge():
    child = StandardEnvironment()
    child.active_profiles = ["c1", "c2"]
    child.property_sources.append_last(
        MappingPropertySource(
            "childMock", {"childKey": "childVal", "bothKey": "childBothVal"}
        )
    )

    parent = StandardEnvironment()
    parent.active_profiles = ["p1", "p2"]
    parent.property_sources.append_last(
        MappingPropertySource(
            "parentMock", {"parentKey": "parentVal", "bothKey": "parentBothVal"}
        )
    )

    assert child.get_property("childKey") == "childVal"
    assert child.get_property("parentKey") is None
    assert child.get_property("bothKey") == "childBothVal"

    assert parent.get_property("childKey") is None
    assert parent.get_property("parentKey") == "parentVal"
    assert parent.get_property("bothKey") == "parentBothVal"

    assert set(child.active_profiles) == {"c1", "c2"}
    assert set(parent.active_profiles) == {"p1", "p2"}

    child.merge(parent)

    assert child.get_property("childKey") == "childVal"
    assert child.get_property("parentKey") == "parentVal"
    assert child.get_property("bothKey") == "childBothVal"

    assert parent.get_property("childKey") is None
    assert parent.get_property("parentKey") == "parentVal"
    assert parent.get_property("bothKey") == "parentBothVal"

