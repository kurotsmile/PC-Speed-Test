# Plugin Benchmarks

Add custom benchmark modules in this folder.

Rules:
- File extension must be `.py`.
- Each plugin must expose `run_test()` function.
- `run_test()` should return a `dict`.
- Optional key: `score` (0..100) to be included in Health Check.

Example:

```python
def run_test():
    return {
        "name": "db-test",
        "score": 78.5,
        "latency_ms": 42.1,
    }
```
