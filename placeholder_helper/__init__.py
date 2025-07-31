import abc
import contextlib
import functools
from abc import ABC
from collections.abc import Callable, Iterable, Mapping
from typing import cast

__all__ = [
    "PlaceholderHelper",
    "PlaceholderResolutionException",
]


class PlaceholderResolutionException(RuntimeError):
    def __init__(
        self,
        reason: str,
        placeholder: str,
        values: str | list[str] | None = None,
        *args,
    ):
        if values is None:
            values = []
        elif isinstance(values, str):
            values = [values]

        super().__init__(self._build_message(reason, values), *args)
        self._reason = reason
        self._placeholder = placeholder
        self._values = values

    @staticmethod
    def _build_message(reason: str, values: list[str]):
        if not values:
            return reason

        message = " <-- ".join(f'"{value}"' for value in values)
        return f"{reason} in value {message}"

    def with_value(self, value: str):
        values = list(self._values)
        values.append(value)
        return self.__class__(self._reason, self._placeholder, values)


def is_text_only(parts: list["Part"]) -> bool:
    return all(isinstance(part, TextPart) for part in parts)


class PartResolutionContext:
    def __init__(
        self,
        prefix: str,
        suffix: str,
        ignore_unresolvable_placeholders: bool,
        parser: Callable[[str], list["Part"]],
        resolver: Callable[[str], str],
    ):
        self.prefix = prefix
        self.suffix = suffix
        self._ignore_unresolvable_placeholders = ignore_unresolvable_placeholders
        self._parser = parser
        self._resolver = resolver
        self._visited_placeholders = None

    def parse(self, text: str) -> list["Part"]:
        return self._parser(text)

    def resolve_placeholder(self, name: str) -> str:
        return self._resolver(name)

    def resolve_part(self, part: "Part") -> str:
        return part.resolve(self)

    def resolve_parts(self, parts: Iterable["Part"], value: str | None = None) -> str:
        try:
            return "".join(self.resolve_part(part) for part in parts)
        except PlaceholderResolutionException as exc:
            if value is not None:
                raise exc.with_value(value) from None
            raise exc

    def resolve_recursively(self, key: str) -> str | None:
        resolved_value = self.resolve_placeholder(key)
        if resolved_value is None:
            return None
        with self._visit_placeholder(key):
            parts = self.parse(resolved_value)
            if is_text_only(parts):
                return "".join(part.text for part in parts)
            return self.resolve_parts(parts, resolved_value)

    def handle_unresolvable_placeholder(self, key: str, text: str) -> str:
        if self._ignore_unresolvable_placeholders:
            return f"{self.prefix}{key}{self.suffix}"

        original_value = f"{self.prefix}{key}{self.suffix}" if key != text else None
        raise PlaceholderResolutionException(f"Could not resolve placeholder '{key}'", key, original_value)

    @contextlib.contextmanager
    def _visit_placeholder(self, placeholder: str):
        visited_placeholders = self._visited_placeholders
        if visited_placeholders is None:
            visited_placeholders = self._visited_placeholders = set()
        if placeholder in visited_placeholders:
            raise PlaceholderResolutionException(f"Circular placeholder reference '{placeholder}'", placeholder)

        visited_placeholders.add(placeholder)
        try:
            yield
        finally:
            visited_placeholders.remove(placeholder)


class Part(abc.ABC):
    @abc.abstractmethod
    def resolve(self, context: PartResolutionContext) -> str:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def text(self) -> str:
        raise NotImplementedError


class BasePart(Part, ABC):
    def __init__(self, text: str):
        self._text = text

    @property
    def text(self) -> str:
        return self._text


class TextPart(BasePart):
    def resolve(self, context: PartResolutionContext) -> str:
        return self.text


class SimplePlaceholderPart(BasePart):
    def __init__(self, text: str, key: str, fallback: str | None):
        super().__init__(text)
        self._key = key
        self._fallback = fallback

    def resolve(self, context: PartResolutionContext) -> str:
        value = self._resolve_recursively(context)
        if value is not None:
            return value
        if self._fallback is not None:
            return self._fallback
        return context.handle_unresolvable_placeholder(self._key, self.text)

    def _resolve_recursively(self, context: PartResolutionContext) -> str | None:
        if self.text != self._key:
            value = context.resolve_recursively(self.text)
            if value is not None:
                return value
        return context.resolve_recursively(self._key)


class NestedPlaceholderPart(BasePart):
    def __init__(self, text: str, key_parts: list[Part], default_parts: list[Part] | None = None):
        super().__init__(text)
        self._key_parts = key_parts
        self._default_parts = default_parts

    def resolve(self, context: PartResolutionContext) -> str:
        resolved_key = context.resolve_parts(self._key_parts)
        value = context.resolve_recursively(resolved_key)
        if value is not None:
            return value
        if self._default_parts is not None:
            return context.resolve_parts(self._default_parts)

        return context.handle_unresolvable_placeholder(resolved_key, self.text)


class PlaceholderHelper:
    _WELL_KNOWN_SIMPLE_PREFIXES = {
        "}": "{",
        "]": "[",
        "(": ")",
    }

    def __init__(
        self,
        prefix: str,
        suffix: str,
        separator: str | None = None,
        escape: str | None = None,
        ignore_unresolvable_placeholders: bool = True,
    ):
        if escape:
            assert len(escape) == 1
        self._prefix = prefix
        self._suffix = suffix
        self._separator = separator
        self._escape = escape
        self._ignore_unresolvable_placeholders = ignore_unresolvable_placeholders

        simple_prefix_for_suffix = self._WELL_KNOWN_SIMPLE_PREFIXES.get(self._suffix)
        if simple_prefix_for_suffix and self._prefix.endswith(simple_prefix_for_suffix):
            simple_prefix = simple_prefix_for_suffix
        else:
            simple_prefix = self._prefix

        self._simple_prefix = simple_prefix

    def replace_placeholders(
        self,
        value: str,
        placeholder_resolver: Callable[[str], str | None] | Mapping[str, str],
        ignore_unresolvable_placeholders: bool | None = None,
    ) -> str:
        if isinstance(placeholder_resolver, Mapping):

            def resolver(name):
                return placeholder_resolver.get(name, None)

        elif isinstance(placeholder_resolver, Callable):
            resolver = placeholder_resolver
        else:

            def resolver(name):
                return getattr(placeholder_resolver, name, None)

        parts = self._parse(value, False)

        context = PartResolutionContext(
            prefix=self._prefix,
            suffix=self._suffix,
            ignore_unresolvable_placeholders=ignore_unresolvable_placeholders or self._ignore_unresolvable_placeholders,
            parser=functools.partial(self._parse, in_placeholder=False),
            resolver=resolver,
        )
        return context.resolve_parts(parts, value)

    def _parse(self, value: str, in_placeholder: bool) -> list[Part]:
        start_index = self._next_start_prefix(value, 0)
        if start_index == -1:
            if in_placeholder:
                key, fallback = self._parse_section(value)
                return [SimplePlaceholderPart(value, key, fallback)]
            return [TextPart(value)]

        parts = []
        position = 0
        while start_index != -1:
            end_index = self._next_valid_end_prefix(value, start_index)
            if end_index == -1:
                next_position = start_index + len(self._prefix)
                self._add_text(value, position, next_position, parts)
                start_index = self._next_start_prefix(value, next_position)
            elif self._is_escaped(value, start_index):
                self._add_text(value, position, start_index - 1, parts)

                next_position = start_index + len(self._prefix)
                self._add_text(value, start_index, next_position, parts)
                start_index = self._next_start_prefix(value, next_position)
            else:
                self._add_text(value, position, start_index, parts)
                placeholder = value[start_index + len(self._prefix) : end_index]
                placeholder_parts = self._parse(placeholder, True)
                parts.extend(placeholder_parts)
                start_index = self._next_start_prefix(value, end_index + len(self._suffix))
                next_position = end_index + len(self._suffix)

            position = next_position

        self._add_text(value, position, len(value), parts)
        if in_placeholder:
            return [self._create_nested_placeholder_part(value, parts)]
        return parts

    def _create_nested_placeholder_part(self, text: str, parts: list[Part]) -> NestedPlaceholderPart:
        if self._separator is None:
            return NestedPlaceholderPart(text, parts)
        key_parts = []
        default_parts = []

        for index, part in enumerate(parts):
            if not isinstance(part, TextPart):
                key_parts.append(part)
            else:
                key, fallback = self._parse_section(part.text)
                key_parts.append(TextPart(key))
                if fallback is not None:
                    default_parts.append(TextPart(fallback))
                    default_parts.extend(parts[index + 1 :])
                    return NestedPlaceholderPart(text, key_parts, default_parts)

        return NestedPlaceholderPart(text, key_parts, None)

    def _next_valid_end_prefix(self, value: str, start_index: int) -> int:
        index = start_index + len(self._prefix)
        within_nested_placeholder = 0
        while index < len(value):
            if value[index : index + len(self._suffix)] == self._suffix:
                if within_nested_placeholder > 0:
                    within_nested_placeholder -= 1
                    index += len(self._suffix)
                else:
                    return index

            elif value[index : index + len(self._simple_prefix)] == self._simple_prefix:
                within_nested_placeholder += 1
                index += len(self._simple_prefix)

            else:
                index += 1

        return -1

    @staticmethod
    def _add_text(value: str, start: int, end: int, parts: list[Part]):
        if start > end:
            return
        text = value[start:end]
        if not text:
            return

        if parts and isinstance(parts[-1], TextPart):
            part: TextPart = cast(TextPart, parts[-1])
            parts[-1] = TextPart(part.text + text)
        else:
            parts.append(TextPart(text))

    def _parse_section(self, value: str) -> tuple[str, str | None]:
        if self._separator is None or self._separator not in value:
            return value, None

        buffer = []
        position = 0
        index = value.find(self._separator, position)

        while index != -1:
            if not self._is_escaped(value, index):
                buffer.append(value[position:index])
                fallback = value[index + len(self._separator) :]
                return "".join(buffer), fallback

            buffer.append(value[position : index - 1])
            position = index + len(self._separator)

            buffer.append(value[index:position])
            index = value.find(self._separator, position)

        buffer.append(value[position:])
        return "".join(buffer), None

    def _is_escaped(self, value: str, index: int):
        return self._escape is not None and index > 0 and value[index - 1] == self._escape

    def _next_start_prefix(self, value: str, index: int) -> int:
        return value.find(self._prefix, index)
