You are a python programming expert. You're task is to parse the given input and output strings into a python values which compatible with the given function signature.

Here is the description about whole problem, input and output.

{problem_description}

Your parser's return value must be compatible with the following function's signature:

{signature}

You must explicitly specify the type of the parser's return value.

Example:
```python
def parser(input: str, output: str) -> tuple[int, int]:
    return int(input), int(output)
```

**IMPORTANT**: you cannot use type union in your parser like `int | str` or `int | float`. You must use the most specific type that can represent the input and output.
If output value has multiple types from the description, you must replace the other case into the most general case.

Example:
Output: generally integer, but if input is wrong then return "Wrong input"
Your parser:
```python
def parser(input: str, output: str) -> int:
    if output.isdigit():
        return int(output)
    else:
        return -1 # "Wrong input" case
```

Write your parser inside of the python code block: ```python```
