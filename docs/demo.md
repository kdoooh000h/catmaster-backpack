# Demo Evidence

This record summarizes local Hermes blind tests for CatMaster Backpack.

## What Was Tested

Two Hermes entrypoints were tested:

```text
hm   -> /home/k/.local/bin/hermes-main
hmk  -> /home/k/.local/bin/kurisu
```

Before the blind read test, the existing tmux sessions were closed:

```text
hermes-main
hermes-kurisu
```

The blind prompts intentionally did not mention:

```text
Backpack
gateway
select
```

## File Read Blind Test

Main profile output:

```text
HM_MAIN_BLIND_RESULT HM_MAIN_BLIND_SENTINEL_20260510_C
```

Session evidence:

```text
tool_backpack {"request":"select read_file"}
read_file /tmp/opencode/hm-blind-backpack-test/main-blind.txt
no "Tool Backpack index:"
```

Kurisu profile output:

```text
HMK_KURISU_BLIND_RESULT HMK_KURISU_BLIND_SENTINEL_20260510_D
```

Session evidence:

```text
tool_backpack {"request":"select read_file"}
read_file /tmp/opencode/hm-blind-backpack-test/kurisu-blind.txt
no "Tool Backpack index:"
```

## File Search Blind Test

Main profile output:

```text
HM_MAIN_SEARCH_RESULT target-main.txt
```

Session evidence:

```text
tool_backpack {"request":"select search_files"}
search_files found /tmp/opencode/hm-blind-search-test/main/target-main.txt
no "Tool Backpack index:"
```

Kurisu profile output:

```text
HMK_KURISU_SEARCH_RESULT target-kurisu.txt
```

Session evidence:

```text
tool_backpack {"request":"select search_files"}
search_files found /tmp/opencode/hm-blind-search-test/kurisu/target-kurisu.txt
no "Tool Backpack index:"
```

## Interpretation

These tests show that the Hermes integration can keep the initial visible surface small while still letting the model select and use task-relevant tools. They do not prove equivalent behavior in hosts that lack dynamic tool-surface hooks.
