# Copyright (C) 2021  Christopher S. Galpin.  See /NOTICE.
import _string
import html
import re
from dataclasses import dataclass
from itertools import zip_longest
from operator import attrgetter
from pathlib import Path
from string import Formatter

from yaml import Node, SafeLoader, add_constructor, safe_load


class YamlFormatter(Formatter):
    def vformat(self, format_string, args, kwargs) -> str:
        i = 0
        while True:
            i += 1
            if i == 10:
                raise ValueError("possible self-reference in format; too many nested references, stopped after 10")

            # can't be any inner braces, not even escaped as {{ or }}
            formatted = re.sub(r'{{(.*?)}}', r'&#123;&#123;\1&#125;&#125;', format_string, flags=re.DOTALL)

            def escape_inner_fields(text: str) -> str:
                def get_fields(text_: str) -> list[int, int, int]:
                    stack = []
                    for m in re.finditer(r'[{}]', text_):
                        pos = m.start()
                        if text_[pos] == '{':
                            stack.append(pos)
                        elif text_[pos] == '}':
                            prev_pos = stack.pop()
                            yield prev_pos, pos + 1, len(stack)

                adjustment = 0  # keep iterator working after substitutions
                for open_pos, close_pos, depth in get_fields(text):
                    open_pos += adjustment
                    close_pos += adjustment

                    if depth > 0:  # leave the outermost field
                        inner_field = text[open_pos:close_pos]
                        escaped_field = re.sub(r'{(.*?)}', r'&#123;\1&#125;', inner_field, flags=re.DOTALL)
                        text = text[:open_pos] + escaped_field + text[close_pos:]
                        adjustment += len(escaped_field) - len(inner_field)
                return text

            # leave outermost braces to evaluate those fields
            formatted = escape_inner_fields(formatted)
            formatted = super().vformat(formatted, args, kwargs)

            # restore unevaluated fields for next loop
            while (new_formatted := re.sub(r'&#123;(.*?)&#125;', r'{\1}', formatted, flags=re.DOTALL)) != formatted:
                formatted = new_formatted

            if formatted == format_string:
                return re.sub(r'{{(.*?)}}', r'{\1}', html.unescape(formatted), flags=re.DOTALL)
            format_string = formatted

    # https://stackoverflow.com/a/62024873/879
    def get_sliced_field(self, field_name, args, kwargs) -> (any, str):
        slice_operator = None
        if type(field_name) == str and '|' in field_name:
            field_name, slice_indexes = field_name.split('|')
            slice_indexes = (None if val == '_' else int(val) for val in slice_indexes.split(','))
            slice_operator = slice(*slice_indexes)

        obj, used_key = super().get_field(field_name, args, kwargs)
        if slice_operator is not None:
            obj = obj[slice_operator]

        return obj, used_key

    def get_field(self, field_name_, args, kwargs) -> (any, str):
        if not (m := re.match(r'(.+?)(\??[=+]|\?$)(.*)', field_name_, flags=re.DOTALL)):
            return self.get_sliced_field(field_name_, args, kwargs)

        field_name, operation, text = m.groups()
        try:
            obj, used_key = self.get_sliced_field(field_name, args, kwargs)
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
        replaced = text.replace('__value__', str(obj))
        if operation.endswith('='):
            return replaced, used_key
        if operation.endswith('+'):
            return obj + replaced, used_key
        raise AssertionError

    def convert_field(self, value, conversion) -> str:
        if conversion == 'e':
            return str(value).replace('{', '{{').replace('}', '}}')
        return super().convert_field(value, conversion)

    def get_value(self, key, args, kwargs: dict):
        if isinstance(key, str):
            kwargs.setdefault('g', _data)
            try:
                return attrgetter(key)(AttrDict(kwargs))
            except KeyError:
                if kwargs.get('l') is None:
                    return attrgetter(key)(_data)
                return attrgetter(key)(AttrDict({**_data, **kwargs['l']}))
        return super().get_value(key, args, kwargs)

    def format_field(self, value, format_spec) -> str:
        if value is None:
            return ''  # otherwise we get 'None'
        return super().format_field(value, format_spec)


def attr_wrap(value: any) -> any:
    if isinstance(value, dict):
        return AttrDict(value)
    if isinstance(value, list):
        return AttrList(value)
    return value


class AttrDict(dict):
    def __getattr__(self, item: any):
        return attr_wrap(self[item])


class AttrList(list):
    def __getattr__(self, item: any):
        key, is_find, value = item.partition('^')
        key, value = html.unescape(key), html.unescape(value)

        if is_find:
            result = next((item for item in self if item[key] == value), None)
            return attr_wrap(result)
        return attr_wrap(self[item])

    def __getitem__(self, item: any):
        return attr_wrap(super().__getitem__(item))


def insert_constructor(loader: SafeLoader, node: Node) -> list:
    @dataclass
    class Info:
        base_list: list
        replace_format: str = None
        positions: list[int] = None

    # info is first element of !insert sequence
    info = Info(*loader.construct_sequence(node.value[0], deep=True))
    if not info.base_list:
        info.base_list = loader.construct_sequence(node.value[0].value[0], deep=True)

    input_list = [loader.construct_object(n, deep=True) for n in node.value[1:]]
    if info.replace_format is None and info.positions is None:
        return info.base_list + input_list

    def item_id(item: any, idx: int) -> int:
        # since info.current_list is constructed it's fine to use formatter.format() on it; mappings will exist
        return idx if info.replace_format is None else formatter.format(info.replace_format, l=item)

    # ordered
    result_dict = {item_id(item, idx): item for idx, item in enumerate(info.base_list)}
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


def split_constructor(loader: SafeLoader, node: Node) -> list[str]:
    # info is !split sequence (all scalars)
    info: list = loader.construct_sequence(node, deep=True)
    separator: str = info[0]
    input_str: str = info[1]
    return input_str.split(separator)


def join_constructor(loader: SafeLoader, node: Node) -> str:
    @dataclass
    class Info:
        separator: str
        input_list: list

    # info is !join sequence
    info = Info(*loader.construct_sequence(node, deep=True))
    if not info.input_list:
        info.input_list = loader.construct_sequence(node.value[1], deep=True)

    def flatten(l: list) -> list:
        return sum(map(flatten, l), []) if isinstance(l, list) else [l]

    result = info.separator.join(item or '' for item in flatten(info.input_list))
    return result


def merge_constructor(loader: SafeLoader, node: Node) -> dict:
    input_dict: dict = loader.construct_mapping(node, deep=True)
    base_dict: dict = input_dict.pop('<')
    merged = {**base_dict, **input_dict}
    return merged


def concat_constructor(loader: SafeLoader, node: Node) -> list:
    input_list: list = loader.construct_sequence(node, deep=True)
    result = []
    for idx, list_ in enumerate(input_list):
        result += list_ or loader.construct_sequence(node.value[idx], deep=True)
    return result


def each_constructor(loader: SafeLoader, node: Node) -> list:
    @dataclass
    class Info:
        input_list: list
        attr: str
        format_str: str = None
        is_required: bool = False

    # info is !each sequence
    info = Info(*loader.construct_sequence(node, deep=True))
    if not info.input_list:
        info.input_list = loader.construct_sequence(node.value[0], deep=True)

    result = []
    for item in info.input_list:
        if isinstance(item, dict):
            try:
                item = attrgetter(info.attr)(attr_wrap(item))
            except KeyError:
                if info.is_required:
                    raise
        if info.format_str:
            item = formatter.format(info.format_str, l=item)
        result.append(item)
    return result


def get_constructor(loader: SafeLoader, node: Node):
    @dataclass
    class Info:
        input_list: list
        attr: str

    # info is !get sequence
    info = Info(*loader.construct_sequence(node, deep=True))
    if not info.input_list:
        info.input_list = loader.construct_sequence(node.value[0], deep=True)
    return attrgetter(info.attr)(attr_wrap(info.input_list))


def parent_constructor(loader: SafeLoader, node: Node):
    result = attrgetter(loader.construct_scalar(node))(_data)
    return result


_data = AttrDict()
formatter = YamlFormatter()
# don't use formatter.format() in constructors to evaluate fields like {example} because
#  they may not be constructed i.e. {same_document.example}  let it occur later in user code
add_constructor('!insert', insert_constructor, Loader=SafeLoader)
add_constructor('!split', split_constructor, Loader=SafeLoader)
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


def main() -> None:
    path = Path(__file__).parent.parent.parent / r'tests.yaml'
    g: AttrDict = load(path)
    for pre, post in g.tests:
        assert (result := formatter.format(pre)) == post, (pre, post, result)


if __name__ == '__main__':
    main()
