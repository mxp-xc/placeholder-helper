from unittest.mock import Mock, call

import pytest

from placeholder_helper import PlaceholderHelper, PlaceholderResolutionException


class TestPlaceholderHelper:
    non_strict_helper = PlaceholderHelper("${", "}")
    strict_helper = PlaceholderHelper("${", "}", ignore_unresolvable_placeholders=False)

    def test_with_properties(self):
        text = "foo=${foo}3"
        assert "foo=bar3" == self.non_strict_helper.replace_placeholders(
            text, {"foo": "bar"}
        )

    def test_with_multiple_properties(self):
        text = "foo=${foo},bar=${bar}"
        assert "foo=bar,bar=baz" == self.non_strict_helper.replace_placeholders(
            text, {"foo": "bar", "bar": "baz"}
        )

    def test_recurse_in_property(self):
        text = "foo=${bar}"

        assert "foo=bar" == self.non_strict_helper.replace_placeholders(
            text, {"bar": "${baz}", "baz": "bar"}
        )

    def test_recurse_in_placeholder(self):
        text = "foo=${b${inner}}"
        assert "foo=bar" == self.non_strict_helper.replace_placeholders(
            text, {"bar": "bar", "inner": "ar"}
        )

        assert "actualValue+actualValue" == self.non_strict_helper.replace_placeholders(
            "${top}",
            {
                "top": "${child}+${child}",
                "child": "${${differentiator}.grandchild}",
                "differentiator": "first",
                "first.grandchild": "actualValue",
            },
        )

    def test_with_resolver(self):
        text = "foo=${foo}"
        assert "foo=bar" == self.non_strict_helper.replace_placeholders(
            text, lambda name: "bar" if name == "foo" else None
        )

    def test_unresolved_placeholder_is_ignored(self):
        text = "foo=${foo},bar=${bar}"

        assert "foo=bar,bar=${bar}" == self.non_strict_helper.replace_placeholders(
            text, {"foo": "bar"}
        )

    def test_unresolved_placeholder_as_error(self):
        text = "foo=${foo},bar=${bar}"

        with pytest.raises(PlaceholderResolutionException):
            self.strict_helper.replace_placeholders(text, {"foo": "bar"})


class TestDefaultValue:
    helper = PlaceholderHelper("${", "}", ":")

    @pytest.mark.parametrize(
        ["text", "value"],
        [
            ("${invalid:test}", "test"),
            ("${invalid:${one}}", "1"),
            ("${invalid:${one}${two}}", "12"),
            ("${invalid:${one}:${two}}", "1:2"),
            ("${invalid:${also_invalid:test}}", "test"),
            ("${invalid:${also_invalid:${one}}}", "1"),
        ],
    )
    def test_default_value_is_applied(self, text, value):
        result = self.helper.replace_placeholders(text, {"one": "1", "two": "2"})
        assert result == value

    def test_default_value_is_not_evaluated_early(self):
        resolver = Mock()
        resolver.side_effect = lambda key: "1" if key == "one" else None

        text = "This is ${one:or${two}}"
        result = self.helper.replace_placeholders(text, resolver)

        assert result == "This is 1"

        resolver.assert_has_calls([call("one")])
        resolver.assert_any_call("one")
        with pytest.raises(AssertionError):
            resolver.assert_any_call("two")

        assert resolver.call_count == 1
        resolver.assert_called_once_with("one")


def mock_placeholder_resolver(*pairs) -> Mock:
    if len(pairs) % 2 != 0:
        raise ValueError("Arguments must be even (key-value pairs)")

    resolver = Mock()
    values = dict(zip(pairs[::2], pairs[1::2], strict=True))

    def resolve_placeholder(key):
        return values.get(key)

    resolver.side_effect = resolve_placeholder
    return resolver
