import re

from lark import Lark

with open(__file__.replace("grammar.py", "grammar.lark"), "r") as f:
    grammar = f.read()


def parser(code: str):
    double_dot_pattern = r"\.\."

    spaced_double_dot_code = re.sub(double_dot_pattern, " .. ", code)

    curring_pattern = r"\)\("
    spaced_curring_code = re.sub(curring_pattern, ", ", spaced_double_dot_code)

    _parser = Lark(
        grammar,
        parser="lalr",
        lexer="contextual",
        start="specification",
        propagate_positions=True,
    )

    return _parser.parse(spaced_curring_code)
