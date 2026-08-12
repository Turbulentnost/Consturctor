# Constructor Agent Runtime

A Cursor Composer/Agent-style **tool-calling agent** for the Constructor project. The model never writes files directly or via shell redirection — the **host executes tools** and returns JSON results in a loop until the task is done.

> **Agent skill reference:** [SKILL.md](SKILL.md) — полный справочник инструментов, правил безопасности, цикла и CLI (для AI-агентов и сборщиков).

## Plan (implementation order)

1. **Tools + registry + types** — file/shell/search tools with a uniform JSON result contract
2. **Safety** — workspace sandbox, command denylist, size limits
3. **Loop + LLM client** — provider-agnostic chat loop with parallel read-only tools
4. **CLI** — `main.py` task runner
5. **Verification** — offline mock scenario (`hello.py` + pytest)

## Layout

```
agent/
  loop.py              # tool-calling loop
  llm_client.py          # OpenAI + MockLLM
  tool_registry.py       # schemas + dispatch
  safety.py              # path + command policy
  tools/                 # one module per tool
  prompts/system.md
main.py                  # CLI (repo root)
```

## Quick start

From the Constructor repo root (`Consturctor/`):

### Offline demo (no API key)

```bash
py -3.12 main.py --mock "Create hello.py with add(a,b) and a pytest test"
```

On Linux/macOS use `python` or `python3` instead of `py -3.12`.

Uses `MockLLMClient`, which runs a scripted sequence:

1. `write_file` → `examples/hello.py` and `examples/test_hello.py`
2. `run_terminal` → pytest (fails on intentional bug)
3. `read_file` → inspect source
4. `str_replace` → fix `add`
5. `run_terminal` → pytest (passes)

### Real LLM (OpenAI-compatible)

```bash
set AGENT_API_KEY=sk-...
set AGENT_MODEL=gpt-4o-mini
py -3.12 main.py "Add a utility function and run tests"
```

Environment variables:

| Variable | Purpose |
|----------|---------|
| `AGENT_WORKSPACE` | Workspace root (default: cwd) |
| `AGENT_API_KEY` / `OPENAI_API_KEY` | API key |
| `AGENT_MODEL` / `OPENAI_MODEL` | Model name |
| `AGENT_BASE_URL` / `OPENAI_BASE_URL` | Optional compatible API base |
| `AGENT_MAX_STEPS` | Loop limit (default 25) |
| `AGENT_PROVIDER` | `openai` or `mock` |
| `AGENT_DEBUG` | `1`/`true` for tool trace |

Force mock mode: `py -3.12 main.py --mock "..."`

## No shell writes policy

**Source of truth = files on disk.**

| Operation | Allowed tool | NOT allowed |
|-----------|--------------|-------------|
| Create/overwrite file | `write_file` | `echo > file`, heredoc, `tee` |
| Patch existing file | `str_replace` | `sed -i`, inline python `-c` writes |
| Delete file | `delete_file` | `rm`, `del` |
| Run tests/build | `run_terminal` | any command with `>`, `>>`, `\|` to file |

`run_terminal` blocks redirection, `tee`, destructive git/shell ops, and commands outside an allowlist (`python`, `py`, `pytest`, `git`, `npm`, etc.).

## Tool result contract

```json
{"ok": true, "tool": "write_file", "data": {"path": "hello.py", "bytes_written": 42}, "error": null}
{"ok": false, "tool": "str_replace", "data": null, "error": {"code": "not_found", "message": "..."}}
```

## Example session (mock)

```bash
cd Consturctor
py -3.12 main.py --mock "hello demo"
```

Expected artifacts under `examples/`:

- `hello.py` — `add(a, b)` returning `a + b`
- `test_hello.py` — pytest asserting `add(2, 3) == 5`

## Programmatic use

```python
from agent import run_agent, load_config_from_env, create_llm_client

config = load_config_from_env(".")
result = run_agent("Refactor foo", config, create_llm_client(config))
print(result.final_answer)
```

## Notes

- `read_lints` is an honest stub (returns `unavailable`).
- Writes outside `AGENT_WORKSPACE` are rejected.
- Read-only tools (`read_file`, `glob`, `grep`) may run in parallel within a step.
