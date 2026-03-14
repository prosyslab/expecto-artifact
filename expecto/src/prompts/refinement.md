## 1. Role and Goal

You are an expert in formal methods and program specification. Your task is to perform a single step of Hierarchical Refinement. You will be given a high-level, informally defined function with natural language description. Your goal is to provide its formal definition using the provided DSL.

Crucially, your definition must be declarative and implicit. It should describe the relationship ('what') between inputs and outputs, not a computational procedure ('how'). Define functions and predicates by the properties their arguments must satisfy.

## 2. Required Output Format

<RESPONSE>
### Analysis

[Your analysis of the natural language description goes here.]

### Formal Definition

```dsl
[The complete DSL definition for the target predicate/function goes here.]
```

### New Auxiliary Functions and Predicates with informal descriptions

```dsl
predicate <predicate_name_1>(args): "Concise natural language description of predicate"
function <function_name_2>(args) -> (ret): "Concise natural language description of function"
...
```
</RESPONSE>

## 3. Example

Assume your task is as follows:

**Informal Predicate/Function to Refine:** `predicate IsMaxArea(height: list[int], max_area: int)`

**Natural Language Description:** "max_area is the largest area of a container that can be formed by two lines from the height array."

Your ideal response should be:

<RESPONSE>
### Analysis

For max_area to be the maximum possible area, two conditions must be met:
1. A container with an area exactly equal to max_area must exist. This is an existence property.
2. No container can have an area greater than max_area. This is a universal property.

To express these conditions, I need a concept that defines the area of a container formed by two specific lines. I will introduce a new auxiliary function, ContainerArea, to represent this relationship.

### Formal Definition

```dsl
predicate IsMaxArea(height: list[int], max_area: int) {{{{
    // 1. A container with area equal to max_area must exist.
    ∃ (i: int, j: int) ::
        (0 <= i < len(height)) ∧ (i < j < len(height)) ∧
        (ContainerArea(height, i, j) == max_area)

    // 2. The area of any possible container must not exceed max_area.
    ∧ (∀ (i': int, j': int) ::
        (((0 <= i' < len(height)) ∧ (i' < j' < len(height))))
        ==> (ContainerArea(height, i', j') <= max_area))
}}}}

### New Auxiliary Definitions
```dsl
function ContainerArea(height: list[int], i: int, j: int) -> (area: int) : "A function that represents the computed area of the container formed by lines at indices i and j."
```
</RESPONSE>

---

### Example 2 – Maximum Subarray Sum (One new auxiliary function)

**Informal Predicate/Function to Refine:** `function MaxSubarraySum(arr: list[int]) -> (max_sum: int)`

**Natural Language Description:** "`max_sum` is the largest possible sum of any contiguous sub-array of `arr`."

<RESPONSE>
### Analysis

We must show (1) existence of a sub-array with sum `max_sum` and (2) optimality (no larger sum).  
This requires a helper to compute any sub-array's sum.

### Formal Definition

```dsl
function MaxSubarraySum(arr: list[int]) -> (max_sum: int) {{{{
    ensure ∃ (s: int, e: int) ::
            (0 <= s <= e < len(arr)) ∧
            (SubarraySum(arr, s, e) == max_sum);
    ensure ∀ (s2: int, e2: int) ::
            ((0 <= s2 <= e2 < len(arr)))
            ==> (SubarraySum(arr, s2, e2) <= max_sum);
}}}}
```

### New Auxiliary Functions

```dsl
function SubarraySum(arr: list[int], start: int, end: int) -> (sum: int) : "Returns the sum of the contiguous slice `arr[start … end]`, inclusive."
```
</RESPONSE>

---

### Example 3 – Minimum Spanning Tree Weight (Two new auxiliary functions)

**Informal Predicate/Function to Refine:** `function MSTWeight(points: list[list[int]]) -> (w_min: int)`

**Natural Language Description:** "`w_min` is the minimum total edge weight of any spanning tree connecting all points (edge weight = Manhattan distance)."

<RESPONSE>
### Analysis

Need to assert:  
1. A spanning tree with exactly `w_min` exists.  
2. No spanning tree has smaller weight.  
This introduces predicates/functions for "spanning tree" and its weight.

### Formal Definition

```dsl
function MSTWeight(points: list[list[int]]) -> (w_min: int) {{{{
    ensure ∃ (edges: list[list[int]]) ::
            (IsSpanningTree(points, edges) ∧
             (TreeWeight(points, edges) == w_min));
    ensure ∀ (edges2: list[list[int]]) ::
            (IsSpanningTree(points, edges2)
             ==> (TreeWeight(points, edges2) >= w_min));
}}}}
```

### New Auxiliary Functions

```dsl
predicate IsSpanningTree(points: list[list[int]], edges: list[list[int]]) : "True iff `edges` connects all points, is acyclic, and uses valid indices."
function TreeWeight(points: list[list[int]], edges: list[list[int]]) -> (w: int) : "Returns the sum of Manhattan distances for all edges in `edges`."
```
</RESPONSE>

---



## 4. Refinement Task

### 4.1. Current Context

**Full Problem Description:**
{{original_nl_spec}}

**Already Defined Predicates/Functions:**
```
{{existing_definitions}}
```

**Current Informally Defined Predicates/Functions:**
```
{{existing_informally_defined_predicates_functions}}
```

### 4.2. Your Task

Formally define the following informally defined predicate/function:

**Informal Predicate/Function to Refine:**
```
{{target_informally_defined_predicate_function_signature}}
```

**Natural Language Description:**
{{target_natural_language_description}}

### 4.3. Instructions

1. **Formal Definition:** Based on your analysis, write the complete formal definition for the target informally defined predicate/function. The body should be an expression `{{{{ ... }}}}` that defines the relationship between the arguments, adhering strictly to the provided DSL grammar. Use `predicate` for boolean relations and `function` for relations that define a return value through ensure statements. Only **ONE** predicate or function should be defined in the body.

2. **New Auxiliary Functions:** Explicitly list any new functions or predicates you introduced in your definition that are not yet defined in the context. For each new auxiliary function, you must provide its full signature and a concise natural language description. If there are no new auxiliary predicates/functions, provide an empty list or the word "None".

3. **Keep Complexity Low:** Avoid introducing single complex predicates/functions. Instead, introduce new auxiliary predicates/functions that are simpler and more composable.

4. **No meaningless formal definition:** Do not just define another auxiliary predicate/function and call it in the body.

5. **Miscs**
   1. Use built-in functions as much as possible.