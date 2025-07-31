from unittest.mock import Mock, call

import pytest

from src.placeholder_helper import PlaceholderHelper, PlaceholderResolutionException


class TestPlaceholderHelper:
    non_strict_helper = PlaceholderHelper("${", "}")
    strict_helper = PlaceholderHelper("${", "}", ignore_unresolvable_placeholders=False)

    def test_with_properties(self):
        text = "foo=${foo}3"
        assert "foo=bar3" == self.non_strict_helper.replace_placeholders(text, {"foo": "bar"})

    def test_with_multiple_properties(self):
        text = "foo=${foo},bar=${bar}"
        assert "foo=bar,bar=baz" == self.non_strict_helper.replace_placeholders(text, {"foo": "bar", "bar": "baz"})

    def test_recurse_in_property(self):
        text = "foo=${bar}"

        assert "foo=bar" == self.non_strict_helper.replace_placeholders(text, {"bar": "${baz}", "baz": "bar"})

    def test_recurse_in_placeholder(self):
        text = "foo=${b${inner}}"
        assert "foo=bar" == self.non_strict_helper.replace_placeholders(text, {"bar": "bar", "inner": "ar"})

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

        assert "foo=bar,bar=${bar}" == self.non_strict_helper.replace_placeholders(text, {"foo": "bar"})

    def test_unresolved_placeholder_as_error(self):
        text = "foo=${foo},bar=${bar}"

        with pytest.raises(PlaceholderResolutionException):
            self.strict_helper.replace_placeholders(text, {"foo": "bar"})

    @pytest.mark.parametrize(
        ["text", "value"],
        [
            ("${firstName}", "John"),
            ("$${firstName}", "$John"),
            ("}${firstName}", "}John"),
            ("${firstName}$", "John$"),
            ("${firstName}}", "John}"),
            ("${firstName} ${firstName}", "John John"),
            ("First name: ${firstName}", "First name: John"),
            ("${firstName} is the first name", "John is the first name"),
            ("${first${nested1}}", "John"),
            ("${${nested0}${nested1}}", "John"),
        ],
    )
    def test_placeholder_is_replaced(self, text, value):
        result = self.non_strict_helper.replace_placeholders(
            text, {"firstName": "John", "nested0": "first", "nested1": "Name"}
        )
        assert result == value

    @pytest.mark.parametrize(
        ["text", "value"],
        [
            ("${p1}:${p2}", "v1:v2"),
            ("${p3}", "v1:v2"),
            ("${p4}", "v1:v2"),
            ("${p5}", "v1:v2:${bogus}"),
            ("${p0${p0}}", "${p0${p0}}"),
        ],
    )
    def test_nested_placeholders_are_replaced(self, text, value):
        result = self.non_strict_helper.replace_placeholders(
            text, {"p1": "v1", "p2": "v2", "p3": "${p1}:${p2}", "p4": "${p3}", "p5": "${p1}:${p2}:${bogus}"}
        )
        assert result == value


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


class TestEscaped:
    helper = PlaceholderHelper("${", "}", ":", "\\", True)

    @pytest.mark.parametrize(
        ["text", "expected"],
        [
            ("\\${firstName}", "${firstName}"),
            ("First name: \\${firstName}", "First name: ${firstName}"),
            ("$\\${firstName}", "$${firstName}"),
            ("\\}${firstName}", "\\}John"),
            ("${\\${test}}", "John"),
            ("${p2}", "${p1:default}"),
            ("${p3}", "${p1:default}"),
            ("${p4}", "adc${p1}"),
            ("${p5}", "adcv1"),
            ("${p6}", "adcdef${p1}"),
            ("${p7}", "adc\\${"),
            ("DOMAIN\\\\${user.name}", "DOMAIN\\${user.name}"),
            ("triple\\\\\\${backslash}", "triple\\\\${backslash}"),
            ("start\\${prop1}middle\\${prop2}end", "start${prop1}middle${prop2}end"),
        ],
    )
    def test_escaped_placeholder_is_not_replaced(self, text, expected):
        assert expected == self.helper.replace_placeholders(
            text,
            {
                "firstName": "John",
                "${test}": "John",
                "p1": "v1",
                "p2": "\\${p1:default}",
                "p3": "${p2}",
                "p4": "adc${p0:\\${p1}}",
                "p5": "adc${\\${p0}:${p1}}",
                "p6": "adc${p0:def\\${p1}}",
                "p7": "adc\\${",
            },
        )

    @pytest.mark.parametrize(
        ["text", "expected"],
        [("${first\\:Name}", "John"), ("${last\\:Name}", "${last:Name}")],
    )
    def test_escaped_separator_is_not_replaced(self, text, expected):
        assert expected == self.helper.replace_placeholders(text, {"first:Name": "John"})

    @pytest.mark.parametrize(
        ["text", "expected"],
        [
            ("${protocol\\://host/${app.environment}/name}", "protocol://example.com/qa/name"),
            ("${${app.service}\\://host/${app.environment}/name}", "protocol://example.com/qa/name"),
            ("${service/host/${app.environment}/name:\\value}", "https://example.com/qa/name"),
            ("${service/host/${name\\:value}/}", "${service/host/${name:value}/}"),
        ],
    )
    def test_escaped_separator_in_nested_placeholder_is_not_replaced(self, text, expected):
        assert expected == self.helper.replace_placeholders(
            text,
            {
                "app.environment": "qa",
                "app.service": "protocol",
                "protocol://host/qa/name": "protocol://example.com/qa/name",
                "service/host/qa/name": "https://example.com/qa/name",
                "service/host/qa/name:value": "https://example.com/qa/name-value",
            },
        )


class TestException:
    helper = PlaceholderHelper("${", "}", ":", None, False)

    def test_with_circular_reference(self):
        with pytest.raises(PlaceholderResolutionException) as exc:
            self.helper.replace_placeholders("${pL}", {"pL": "${pR}", "pR": "${pL}"})

        assert 'Circular placeholder reference \'pL\' in value "${pL}" <-- "${pR}" <-- "${pL}"' == exc.value.args[0]

    def test_unresolvable_placeholder_is_reported(self):
        with pytest.raises(PlaceholderResolutionException) as exc:
            self.helper.replace_placeholders("X${bogus}Z", lambda x: None)

        assert "Could not resolve placeholder 'bogus' in value \"X${bogus}Z\"" == exc.value.args[0]

    def test_unresolvable_placeholder_in_nested_placeholder_is_reported_with_chain(self):
        with pytest.raises(PlaceholderResolutionException) as exc:
            self.helper.replace_placeholders("${p3}", {"p1": "v1", "p2": "v2", "p3": "${p1}:${p2}:${bogus}"})

        assert (
            "Could not resolve placeholder 'bogus' in value \"${p1}:${p2}:${bogus}\" <-- \"${p3}\"" == exc.value.args[0]
        )
