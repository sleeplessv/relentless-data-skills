# Spec: multiply, and totals with a thousands separator

Two tickets that change separate files. Each one leaves the check command passing.

## Ticket A

Add `multiply(a, b)` to `calc.py`. It returns the product of `a` and `b`. Add a test of it to `test_calc.py`.

Files: `calc.py`, `test_calc.py`

Acceptance criteria:

- `multiply(4, 3)` returns `12`.
- `test_calc.py` has a test of `multiply`, and the check command passes.

## Ticket B

Change `format_total` in `fmt.py` to put a comma between each group of three digits before the decimal point. Update `test_fmt.py` to match.

Files: `fmt.py`, `test_fmt.py`

Acceptance criteria:

- `format_total(1234.5)` returns `"1,234.50"`.
- `format_total(3.5)` still returns `"3.50"`.
- `test_fmt.py` has a test of each case, and the check command passes.
