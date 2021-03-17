# Copyright (C) 2021  Christopher S. Galpin.  See /NOTICE.
import _string
import html
import re
from dataclasses import dataclass
from itertools import zip_longest
from operator import attrgetter
from pathlib import Path
from string import Formatter
from typing import Any, List

from yaml import Node, SafeLoader, ScalarNode, add_constructor, safe_load


class YamlFormatter(Formatter):
    def vformat(self, format_string, args, kwargs):
        i = 0
        input = format_string
        # format while protecting any escaped braces
        while (formatted := super().vformat(protected := input.replace('{{', '{{{{').replace('}}', '}}}}'), args, kwargs)) != protected:
            if i == 10:
                raise ValueError("possible self-reference in format; too many nested references, stopped after 10")

            only_escaped_braces_left = formatted == input
            if only_escaped_braces_left:
                return super().vformat(formatted, args, kwargs)  # one last time

            i += 1
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
                return attrgetter(key)(AttrDict(kwargs))
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
    def __getattr__(self, item: Any):
        key, is_find, value = item.partition('=')
        key, value = html.unescape(key), html.unescape(value)

        if is_find:
            result = next((item for item in self if item[key] == value), None)
            return attr_wrap(result)
        return attr_wrap(self[item])

    def __getitem__(self, item: Any):
        return attr_wrap(super().__getitem__(item))


@dataclass
class InsertInfo:
    sequence: list
    replace_format: str = None
    positions: List[int] = None

    @staticmethod
    def insert_constructor(loader: SafeLoader, node: Node) -> list:
        if isinstance(node.value[0], ScalarNode):
            info = InsertInfo(sequence=loader.construct_object(node.value[0], deep=True))
        else:
            info = InsertInfo(*loader.construct_sequence(node.value[0], deep=True))
        current_list: List[Any] = info.sequence  # already constructed
        input_list: List[Any] = [loader.construct_object(n, deep=True) for n in node.value[1:]]
        if info.replace_format is None and info.positions is None:
            return current_list + input_list

        def item_id(item: Any, idx: int) -> int:
            return idx if info.replace_format is None else formatter.format(info.replace_format, l=item)

        # ordered
        result_dict = {item_id(item, idx): item for idx, item in enumerate(current_list)}
        input_dict = {item_id(item, idx + len(result_dict)): item for idx, item in enumerate(input_list)}

        to_pos = {}
        to_end = []
        for input_pos, (input_id, input_item) in zip_longest(info.positions or [], input_dict.items()):
            if input_pos is not None:
                result_dict.pop(input_id, None)
                to_pos[input_pos] = input_item
            elif input_id in result_dict:
                result_dict[input_id] = input_item
            else:
                to_end.append(input_item)

        result_list = list(result_dict.values()) + to_end
        for item in sorted(to_pos):
            result_list.insert(item, to_pos[item])
        return result_list


def join_constructor(loader: SafeLoader, node: Node) -> str:
    info = loader.construct_sequence(node, deep=True)
    separator, input_list = info[0], info[1]
    format = info[2] if len(info) == 3 else '{l}'

    def flatten(l: list) -> list:
        return sum(map(flatten, l), []) if isinstance(l, list) else [l]

    input_list = flatten(input_list)
    return separator.join(value for item in input_list if (value := formatter.format(format, l=item)))


def merge_constructor(loader: SafeLoader, node: Node) -> dict:
    input_dict: dict = loader.construct_mapping(node, deep=True)
    base_dict = input_dict.pop('<')
    merged = {**base_dict, **input_dict}
    return merged


def concat_constructor(loader: SafeLoader, node: Node) -> list:
    input_list: List[list] = loader.construct_sequence(node, deep=True)
    result = [item for list_ in input_list for item in list_]
    return result


def each_constructor(loader: SafeLoader, node: Node) -> list:
    input_list, attr, is_required = loader.construct_sequence(node, deep=True)
    result = []
    for item in input_list:
        try:
            result.append(attrgetter(attr)(attr_wrap(item)))
        except KeyError:
            if is_required:
                raise
    return result


def get_constructor(loader: SafeLoader, node: Node):
    input_list, attr = loader.construct_sequence(node, deep=True)
    return attrgetter(attr)(attr_wrap(input_list))


def parent_constructor(loader: SafeLoader, node: Node):
    result = attrgetter(loader.construct_scalar(node))(_data)
    return result


_data = AttrDict()
formatter = YamlFormatter()
add_constructor('!insert', InsertInfo.insert_constructor, Loader=SafeLoader)
add_constructor('!join', join_constructor, Loader=SafeLoader)
add_constructor('!merge', merge_constructor, Loader=SafeLoader)
add_constructor('!concat', concat_constructor, Loader=SafeLoader)
add_constructor('!each', each_constructor, Loader=SafeLoader)
add_constructor('!get', get_constructor, Loader=SafeLoader)
add_constructor('!parent', parent_constructor, Loader=SafeLoader)


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
