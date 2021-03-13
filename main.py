# Copyright (C) 2021  Christopher S. Galpin.  See /NOTICE.
import _string
import re
from operator import attrgetter
from pathlib import Path
from string import Formatter
from typing import Any

# noinspection PyProtectedMember
from yaml import safe_load, SafeLoader, add_constructor


class YamlFormatter(Formatter):
    def vformat(self, format_string, args, kwargs):
        input = format_string
        # format while protecting any escaped braces
        while (formatted := super().vformat(protected := input.replace('{{', '{{{{').replace('}}', '}}}}'), args, kwargs)) != protected:
            only_escaped_braces_left = formatted == input
            if only_escaped_braces_left:
                return super().vformat(formatted, args, kwargs)  # one last time
            input = formatted
        return formatted

    def get_field(self, field_name_, args, kwargs):
        if not (m := re.match(r'(.+?)(\??[=+]|\?$)(.*)', field_name_, re.DOTALL)):
            return super().get_field(field_name_, args, kwargs)

        field_name, operation, text = m.groups()
        try:
            obj, used_key = super().get_field(field_name, args, kwargs)
        except KeyError:
            if not operation.startswith('?'):
                raise
            # consider it used for check_unused_args(), as it's intentionally optional
            used_key = _string.formatter_field_name_split(field_name)[0]
            return '', used_key

        finished_with_basic = operation == '?'
        if obj is None or finished_with_basic:
            return obj, used_key

        # obj exists, now do something special
        replaced = text.replace('__value__', obj)
        if operation.endswith('='):
            return replaced, used_key
        if operation.endswith('+'):
            return obj + replaced, used_key
        raise AssertionError

    def convert_field(self, value, conversion):
        if conversion == 'e':
            return str(value).replace('{', '{{').replace('}', '}}')
        return super().convert_field(value, conversion)

    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            kwargs.setdefault('g', _data)
            try:
                return kwargs[key]
            except KeyError:
                if kwargs.get('l') is None:
                    return attrgetter(key)(_data)
                return attrgetter(key)(AttrDict({**_data, **kwargs['l']}))
        return super().get_value(key, args, kwargs)

    def format_field(self, value, format_spec):
        if value is None:
            return ''  # otherwise we get 'None'
        return super().format_field(value, format_spec)


def attr_wrap(value: Any) -> Any:
    if isinstance(value, dict):
        return AttrDict(value)
    if isinstance(value, list):
        return AttrList(value)
    return value


class AttrDict(dict):
    def __getattr__(self, item: Any):
        return attr_wrap(self[item])


class AttrList(list):
    def __getitem__(self, item: Any):
        return attr_wrap(super().__getitem__(item))


# processed later
class Steam2Xml(str):
    pass


_data: AttrDict
add_constructor('!parent', lambda l, n: attrgetter(l.construct_scalar(n))(_data), Loader=SafeLoader)
add_constructor('!steam2xml', lambda l, n: Steam2Xml(l.construct_scalar(n)), Loader=SafeLoader)
formatter = YamlFormatter()


def load(yaml_path: Path):
    yaml_paths = [yaml_path]
    while True:
        with yaml_path.open(encoding='utf-8-sig') as f:
            parent_literal, _, parent_path = f.readline().rstrip().partition('=')
            if parent_literal != '#parent':
                break
            yaml_path = Path(parent_path)
            yaml_paths.append(yaml_path)

    for yaml_path in reversed(yaml_paths):
        with yaml_path.open(encoding='utf-8-sig') as f:
            try:
                _data.update(safe_load(f))
            except Exception as e:
                raise Exception(f"Loading error in: {yaml_path}") from e
    return _data
