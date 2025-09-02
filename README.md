# placeholder-helper
Python implementation of Java spring-framework Placeholder Helper and StandardEnvironment


```python
from placeholder_helper import PlaceholderHelper

helper = PlaceholderHelper("${", "}")

assert "foo = bar" == helper.replace_placeholders("foo = ${foo}", {"foo": "bar"})
assert "foo = baz" == helper.replace_placeholders("foo = ${foo}", {"foo": "${bar}", "bar": "baz"})

```


## default
```python
from placeholder_helper import PlaceholderHelper

helper = PlaceholderHelper("${", "}", ":")
assert "foo = foo" == helper.replace_placeholders("foo = ${invalid:foo}", {})
```

## custom resolver

```python
from placeholder_helper import PlaceholderHelper


def resolver(name):
    if name == "foo":
        return "bar"
    return name


helper = PlaceholderHelper("${", "}")

assert "foo=bar, bar=bar" == helper.replace_placeholders("foo=${foo}, bar=${bar}", resolver)
```
