import abc
import os
from functools import cached_property
from threading import RLock
from typing import Any, Generic, Iterable, Mapping, TypeVar

from .helper import (
    PlaceholderHelper,
)

T = TypeVar("T")

_missing = object()


class PropertySource(abc.ABC, Generic[T]):
    def __init__(self, name: str):
        self.name = name

    def __contains__(self, name):
        return self.get_property(name) is None

    def __getitem__(self, name) -> T:
        value = self.get_property(name)
        if value is None:
            raise KeyError(f"property '{name}' not exist.")
        return value

    @abc.abstractmethod
    def get_property(self, name: str) -> T | None:
        raise NotImplementedError

    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.name})"

    __str__ = __repr__


class EnumerablePropertySource(PropertySource[T], Generic[T]):
    @abc.abstractmethod
    def get_property_names(self) -> list[str]:
        raise NotImplementedError


class MappingPropertySource(EnumerablePropertySource[Mapping[str, Any]]):
    def __init__(self, name: str, mapping: Mapping[str, Any]):
        self._mapping = mapping
        super().__init__(name)

    def get_property(self, name: str) -> Any:
        return self._mapping.get(name, None)

    def get_property_names(self) -> list[str]:
        return list(self._mapping.keys())


class CompositePropertySource(EnumerablePropertySource[Any]):
    def __init__(self, name: str):
        super().__init__(name)
        self._property_sources: list[PropertySource] = []

    def get_property(self, name: str) -> T | None:
        for source in self._property_sources:
            candidate = source.get_property(name)
            if candidate is not None:
                return candidate
        return None

    def get_property_names(self) -> list[str]:
        result = []
        for source in self._property_sources:
            if not isinstance(source, EnumerablePropertySource):
                raise RuntimeError(
                    f"Failed to enumerate property names due to non-enumerable property source: {source}"
                )
            result.extend(source.get_property_names())
        return result

    @property
    def property_sources(self) -> list[PropertySource[Any]]:
        return self._property_sources


class MutablePropertySources(object):
    def __init__(self, sources: list[PropertySource] | None = None):
        self._sources = list(sources) if sources else []
        self._lock = RLock()

    def __iter__(self):
        return iter(self._sources)

    def __contains__(self, name: str):
        return self.get(name) is not None

    def __getitem__(self, name: str) -> PropertySource:
        source = self.get(name)
        if source is None:
            raise KeyError(f"property source '{name}' not exist.")
        return source

    def get(self, name: str) -> PropertySource | None:
        for source in self._sources:
            if source.name == name:
                return source
        return None

    def append_last(self, source: PropertySource):
        with self._lock:
            self._remove_source(source)
            self._sources.append(source)

    def append_first(self, source: PropertySource):
        with self._lock:
            self._remove_source(source)
            self._sources.insert(0, source)

    def clear(self):
        with self._lock:
            self._sources.clear()

    def _remove_source(self, source: PropertySource):
        try:
            self._sources.remove(source)
        except ValueError:
            pass


class MissingRequiredPropertiesException(RuntimeError):
    pass


class PropertyResolver:
    def __init__(
        self,
        property_sources: MutablePropertySources,
        placeholder_prefix: str = "${",
        placeholder_suffix: str = "}",
        value_separator: str = "}",
    ):
        self._placeholder_prefix = placeholder_prefix
        self._placeholder_suffix = placeholder_suffix
        self._property_sources = property_sources
        self._value_separator = value_separator
        self._required_properties: set[str] = set()

    def add_required_properties(self, names: str | Iterable[str]):
        if isinstance(names, str):
            names = [names]
        for name in names:
            self._required_properties.add(name)

    def validate_required_properties(self):
        missing = []
        for key in self._required_properties:
            if self.get_property(key) is None:
                missing.append(key)
        if missing:
            raise MissingRequiredPropertiesException(
                f"The following properties were declared as required but could not be resolved: {missing}"
            )

    @cached_property
    def strict_helper(self):
        return self._create_placeholder_helper(False)

    @cached_property
    def non_strict_helper(self):
        return self._create_placeholder_helper(True)

    def _create_placeholder_helper(
        self, ignore_unresolvable_placeholders: bool
    ):
        return PlaceholderHelper(
            self._placeholder_prefix,
            self._placeholder_suffix,
            self._value_separator,
            "\\",
            ignore_unresolvable_placeholders,
        )

    def _convert_result(self, value, type_: type[T]) -> T:  # noqa
        if type_ is None or isinstance(value, type_):
            return value
        return type_(value)

    def get_property(
        self,
        key: str,
        type_: type[T] | None = None,
        default: T | None = None,
    ) -> T | None:
        for source in self._property_sources:
            value = source.get_property(key)
            if value is None:
                continue
            return self._convert_result(value, type_)
        return default

    def get_required_property(
        self,
        key: str,
        type_: type[T] | None = None,
    ) -> T | None:
        result = self.get_property(key, type_, _missing)
        if result is _missing:
            raise RuntimeError(f"property '{key}' not found")
        return result

    def resolve_placeholder(self, text: str) -> str | None:
        return self.non_strict_helper.replace_placeholders(
            text, self._get_property_as_raw_string
        )

    def resolve_required_placeholder(self, text: str) -> str:
        return self.strict_helper.replace_placeholders(
            text, self._get_property_as_raw_string
        )

    def _get_property_as_raw_string(self, name: str) -> str:
        return self.get_property(name, str, None)


class Environment:
    ACTIVE_PROFILES_PROPERTY_NAME = "spring.profiles.active"

    def __init__(
        self,
        sources: list[PropertySource] | MutablePropertySources | None = None,
        property_resolver: PropertyResolver | None = None,
        active_profiles_property_name: str = ACTIVE_PROFILES_PROPERTY_NAME,
    ):
        if property_resolver is not None:
            property_sources = property_resolver._property_sources  # noqa
            assert sources is None
        elif sources is None:
            property_sources = MutablePropertySources()
        elif isinstance(sources, MutablePropertySources):
            property_sources = sources
        else:
            property_sources = MutablePropertySources(sources)

        self._property_sources: MutablePropertySources = property_sources
        self._property_resolver: PropertyResolver = (
            property_resolver or PropertyResolver(property_sources)
        )
        self._active_profiles_property_name: str = active_profiles_property_name
        self._active_profiles: set[str] = set()
        self._active_profile_lock = RLock()
        self._custom_property_sources(property_sources)

    @property
    def active_profiles(self) -> list[str]:
        return list(self._get_active_profiles())

    @active_profiles.setter
    def active_profiles(self, profiles: Iterable[str]):
        with self._active_profile_lock:
            self._active_profiles.clear()
            for profile in profiles:
                self._validate_profile(profile)
                self._active_profiles.add(profile)

    def add_active_profile(self, profile: str):
        self._validate_profile(profile)
        with self._active_profile_lock:
            self._get_active_profiles()
            self._active_profiles.add(profile)

    def _validate_profile(self, profile: str):  # noqa
        if not profile:
            raise RuntimeError("Invalid profile []: must contain text")
        if profile[0] == "!":
            raise RuntimeError(
                f"Invalid profile [{profile}]: must not begin with ! operator"
            )

    def _get_active_profiles(self) -> set[str]:
        if self._active_profiles:
            return self._active_profiles

        with self._active_profile_lock:
            if self._active_profiles:
                return self._active_profiles

            profiles = self.get_property(
                self._active_profiles_property_name, str
            )
            if profiles:
                self.active_profiles = set(map(str.strip, profiles.split(",")))

            return self._active_profiles

    @property
    def property_sources(self) -> MutablePropertySources:
        return self._property_sources

    def merge(self, parent: "Environment"):
        for source in parent.property_sources:
            if source.name not in self._property_sources:
                self._property_sources.append_last(source)

        active_profiles = parent.active_profiles
        if active_profiles:
            with self._active_profile_lock:
                for profile in active_profiles:
                    self._active_profiles.add(profile)

    def get_property(
        self,
        key: str,
        type_: type[T] = str,
        default: T | None = None,
    ) -> T | None:
        return self._property_resolver.get_property(key, type_, default)

    def get_required_property(
        self,
        key: str,
        type_: type[T] | None = None,
    ) -> T | None:
        return self._property_resolver.get_required_property(key, type_)

    def resolve_placeholder(self, text: str) -> str | None:
        return self._property_resolver.resolve_placeholder(text)

    def resolve_required_placeholder(self, text: str) -> str | None:
        return self._property_resolver.resolve_required_placeholder(text)

    def _custom_property_sources(
        self, property_sources: MutablePropertySources
    ):
        pass


class StandardEnvironment(Environment):
    SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME: str = "systemEnvironment"

    def _custom_property_sources(
        self, property_sources: MutablePropertySources
    ):
        property_sources.append_last(
            MappingPropertySource(
                self.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME, os.environ
            ),
        )
