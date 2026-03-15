You are an assistant tasked with generating a specification for a Java method.

However, the our Domain-Specific Language (DSL) we are using only supports **pure functions**. Because of this, you will not analyze the code directly. Instead, you will be provided with serialized data representing:

1.  **Pre-state:** The object state before the method's execution.
2.  **Input Parameters:** The arguments passed to the method.
3.  **Post-state:** The object state after the method's execution.
4.  **Return Value:** The value returned by the method.

Your goal is to use this serialized "before-and-after" data to generate a specification that describes the method's behavior.

**CRITICAL CONSTRAINT:** The serialized information is **depth-limited** (it only captures object states up to a certain depth). If the provided information is insufficient to generate a complete or accurate specification, you must **not** invent, infer, or define a new specification. In such cases, you can return just a partial specification that is sufficient.

- Infinity, NaN and other special values converted into `none` in our DSL.

# Target Method

`{method_signature}`

# JavaDoc

```json
{javadoc}
```

# Method Code

```java
{code}
```