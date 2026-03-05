---
description: "Generate or update CLI usage documentation for PC Speed Test tool, including command reference, examples, and flags"
argument-hint: "Optional: specific section to focus on (e.g., 'command flags', 'usage examples', 'troubleshooting')"
agent: "agent"
---

# Generate CLI Usage Documentation

Generate comprehensive CLI usage documentation for the **PC Speed Test** tool by analyzing the source code and creating clear, user-friendly documentation.

## Task

Based on the codebase (particularly `Pc_speed_test.py` and the `parse_args()` function), create documentation that includes:

### 1. **Command Reference**
- All available CLI flags and arguments (e.g., `--benchmark`, `--json`, `--gui`, `--export-report`, `--health-check`, etc.)
- Explain what each flag does
- Show default values and accepted parameters
- Group related flags logically (e.g., output formats, thresholds, monitoring)

### 2. **Usage Examples**
- Basic usage: `python Pc_speed_test.py` (without arguments)
- With benchmark: `python Pc_speed_test.py --benchmark`
- GUI mode: `python Pc_speed_test.py --gui`
- Health check with export: `python Pc_speed_test.py --health-check --export-report`
- JSON output: `python Pc_speed_test.py --benchmark --json`
- Setting thresholds
- Background monitoring
- Other real-world scenarios

### 3. **Output Formats**
Explain the different ways to consume output:
- Human-readable text (default)
- JSON format (`--json`)
- PDF/TXT/JSON reports (`--export-report --report-format`)
- GUI dashboard (`--gui`)

### 4. **Key Concepts**
- What "benchmarks" means (CPU loops, memory, disk, network tests)
- Health check scoring and recommendations
- Background monitor snapshots
- Report exports and locations
- Alert thresholds and how to configure them

### 5. **Optional: Troubleshooting**
- Common issues (missing dependencies, tkinter not available, etc.)
- How optional features degrade gracefully
- Where output files are stored

## Format

Use **Markdown** with:
- Clear headings and subheadings
- Code blocks for commands and examples
- Tables for flag reference (if helpful)
- Inline code for flags, filenames, and paths
- Cross-references between sections

## Notes

- Focus on clarity for **end users** and **developers** who want to use this tool
- Assume minimal prior knowledge of the tool (explain terminology)
- Make examples copy-paste ready
- Reference the output directory structure where applicable
