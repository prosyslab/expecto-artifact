You are an expert in Python programming and formal verification. Your task is to generate a signature for the `postcondition` function of given function specification in the Python.

## Task
`postcondition` function is model of the given function specification.
By using the `postcondition` function, we can verify the correctness of the implementation of the given function specification.
Generate a signature for the `postcondition` function of the given function specification.

You must follow the format below:
```python
def postcondition(input_param1: type1, input_param2: type2, ..., output_param1: type1, output_param2: type2, ...):
    \"\"\"
    input_param1: input_param1 is ...
    input_param2: input_param2 is ...
    ...
    output_param1: output_param1 is ...
    output_param2: output_param2 is ...
    ...
    \"\"\"
    pass
```
**Reminders**
- return type of the postcondition must be `bool`.
- Input and output can be include multiple cases with the number of cases. Then, the signature must be integer for the number of cases and list of them.

Here is the function specification:
{function_spec}

Write the signature in the following section:
```python
WRITE YOUR SIGNATURE HERE
```