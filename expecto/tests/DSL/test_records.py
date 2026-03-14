#!/usr/bin/env python3
"""
Test script for DSL record type support.

This demonstrates the new record type functionality that allows handling
JSON-like structured data with strongly-typed fields.
"""

from src.DSL.compiler import DSLCompiler


def test_basic_record():
    """Test basic record type functionality."""
    print("=== Test: Basic Record ===")
    compiler = DSLCompiler()
    code = """
    predicate test_person(p: record[name: string, age: int]) {
        p["name"] == "Alice" and p["age"] > 18
    }
    """

    try:
        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        if errors:
            print("Type errors:")
            for err in errors:
                print(f"  - {err}")
        else:
            print("✓ Type checking successful!")
            print(f"  Signature: {ast.declarations[0].get_signature()}")
            z3_exprs = compiler.to_z3(ast)
            print(f"  Generated {len(z3_exprs)} Z3 expressions")
    except Exception as e:
        print(f"✗ Error: {e}")


def test_nested_records():
    """Test nested record types (like JSON objects)."""
    print("\n=== Test: Nested Records ===")
    compiler = DSLCompiler()
    code = """
    predicate test_config(data: record[phase: string, self: record[sigma: real, mu: int], params: record[]]) {
        data["phase"] == "entry" and 
        data["self"]["sigma"] == 0.0 and 
        data["self"]["mu"] == 0 and
        len(keys(data)) == 3 and
        has_key(data, "phase") and
        has_key(data["self"], "sigma")
    }
    """

    try:
        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        if errors:
            print("Type errors:")
            for err in errors:
                print(f"  - {err}")
        else:
            print("✓ Type checking successful!")
            print(f"  Signature: {ast.declarations[0].get_signature()}")
            z3_exprs = compiler.to_z3(ast)
            print(f"  Generated {len(z3_exprs)} Z3 expressions")
    except Exception as e:
        print(f"✗ Error: {e}")


def test_empty_record():
    """Test empty record type."""
    print("\n=== Test: Empty Record ===")
    compiler = DSLCompiler()
    code = """
    predicate test_empty(data: record[]) {
        len(keys(data)) == 0
    }
    """

    try:
        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        if errors:
            print("Type errors:")
            for err in errors:
                print(f"  - {err}")
        else:
            print("✓ Type checking successful!")
            print(f"  Signature: {ast.declarations[0].get_signature()}")
    except Exception as e:
        print(f"✗ Error: {e}")


def test_builtin_functions():
    """Test built-in functions for records."""
    print("\n=== Test: Built-in Functions ===")
    compiler = DSLCompiler()
    code = """
    predicate test_builtins(data: record[a: int, b: string, c: bool]) {
        len(keys(data)) == 3 and
        has_key(data, "a") and
        has_key(data, "b") and
        not has_key(data, "x")
    }
    """

    try:
        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        if errors:
            print("Type errors:")
            for err in errors:
                print(f"  - {err}")
        else:
            print("✓ Type checking successful!")
            print(f"  Signature: {ast.declarations[0].get_signature()}")
    except Exception as e:
        print(f"✗ Error: {e}")


def test_type_errors():
    """Test that type errors are properly caught."""
    print("\n=== Test: Type Error Detection ===")
    compiler = DSLCompiler()
    code = """
    predicate test_errors(data: record[name: string, age: int]) {
        data["email"] == "test@test.com"  // Should fail - no 'email' field
    }
    """

    try:
        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        if errors:
            print("✓ Type errors correctly detected:")
            for err in errors:
                print(f"  - {err}")
        else:
            print("✗ Expected type errors but none found")
    except Exception as e:
        print(f"✗ Unexpected error: {e}")


def test_map_vs_record():
    """Test the difference between maps and records."""
    print("\n=== Test: Map vs Record ===")
    compiler = DSLCompiler()
    code = """
    predicate test_map(m: map[string, int]) {
        m["key1"] == 42  // Map access returns option[int]
    }
    
    predicate test_record(r: record[field1: int, field2: string]) {
        r["field1"] == 42  // Record access returns int directly
    }
    """

    try:
        ast = compiler.parse(code)
        errors = compiler.type_check(ast)
        if errors:
            print("Type errors:")
            for err in errors:
                print(f"  - {err}")
        else:
            print("✓ Type checking successful!")
            for i, decl in enumerate(ast.declarations):
                print(f"  {i + 1}. {decl.get_signature()}")
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    print("Testing DSL Record Type Support")
    print("=" * 50)

    test_basic_record()
    test_nested_records()
    test_empty_record()
    test_builtin_functions()
    test_type_errors()
    test_map_vs_record()

    print("\n" + "=" * 50)
    print("All tests completed!")
