from pathlib import Path
from textwrap import dedent

PROJECT_ROOT = Path(__file__).parent.parent

# Load prompts
with open(PROJECT_ROOT / "prompts" / "dsl_model_1.dsl", "r") as f:
    dsl_model_1 = f.read()

with open(PROJECT_ROOT / "prompts" / "dsl_model_2.dsl", "r") as f:
    dsl_model_2 = f.read()

with open(PROJECT_ROOT / "prompts" / "dsl_model_3.dsl", "r") as f:
    dsl_model_3 = f.read()

with open(PROJECT_ROOT / "prompts" / "dsl_sys_prompt.md", "r") as f:
    dsl_sys_prompt = f.read()

with open(PROJECT_ROOT / "DSL" / "grammar.lark", "r") as f:
    dsl_grammar = f.read()

with open(PROJECT_ROOT / "prompts" / "refinement.md", "r") as f:
    refinement_prompt = f.read()
    refinement_prompt = refinement_prompt.format()

with open(PROJECT_ROOT / "prompts" / "parser.md", "r") as f:
    parser_generation_prompt = f.read()

with open(PROJECT_ROOT / "prompts" / "signature.md", "r") as f:
    signature_generation_prompt = f.read()

with open(PROJECT_ROOT / "prompts" / "defects4j.md", "r") as f:
    defects4j_prompt = f.read()

def replace_braces(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")

syntax_error_fix_prompt = dedent(
    """
Following syntax error occurred:
{error_message}

Please fix the syntax error and return the corrected code.
""".strip()
)

type_error_fix_prompt = dedent(
    """
Following type error occurred:
{error_message}

Please fix the type error and return the corrected code.
""".strip()
)

execution_error_fix_prompt = dedent(
    """
After executing the code you generated, the following error occurred:
{error_message}

Please fix the execution error and return the corrected code.
""".strip()
)

dsl_generation_prompt = (
    dedent("""
    Your task is to generate a formal specification for given function specification in DSL

    ## Examples of DSL specifications
    Examples are provided for better understanding of the DSL.

    ### Example
    #### Example 1
    ```dsl
    {dsl_model_1}
    ```

    #### Example 2
    ```dsl
    {dsl_model_2}
    ```

    #### Example 3
    ```dsl
    {dsl_model_3}
    ```


    Here is the function specification:
    {{function_spec}}

    Here is the entry point function DSL specification. There are necessary variables are declared:
    ```dsl
    {{baseline_dsl_specification}}
    ```

    ## Guidelines
    1. Before you start, think step-by-step about what you will write.
        - Check what predicates and functions are necessary to model the given function specification.
        - Check how to describe the predicates and functions in DSL.
        - Check which definition method is better implicit or explicit for each functions.
    2. Write your specification inside a ```dsl``` code block after the thinking.
""")
    .strip()
    .format(
        dsl_model_1=replace_braces(dsl_model_1),
        dsl_model_2=replace_braces(dsl_model_2),
        dsl_model_3=replace_braces(dsl_model_3),
    )
)

code_system_prompt = "You are the best Python programmer. Solve the provided PS problem. All inputs and outputs are provided via the standard stream. Write your code inside of ```python and ```. The last code block will be evaluated. The entrypoint of the function is `solution`."

