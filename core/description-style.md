# Description Style

Use direct technical language. Remove nonessential wording and punctuation without reducing semantics.

## Keep

- Exact capability boundary.
- Required parameter meaning.
- Defaults and limits.
- Safety constraints.
- Preferred-tool guidance when it changes behavior.

## Remove

- Conversational phrasing.
- Repeated examples.
- Decorative punctuation.
- Redundant “use this instead of” phrasing when “preferred over” is equivalent.
- Empty arrays and verbose messages in tool responses.

## Validated Compression Examples

`tool_repo` description:

```text
Tool gateway.
```

`search_files` description:

```text
Search file contents or find files by name. Preferred over grep/rg/find/ls. Ripgrep-backed, faster than shell. target='content': regex inside files; outputs line numbers, file paths only, match counts. target='files': glob file names; results sorted by modification time.
```

`read_file` description:

```text
Read text files with line numbers and pagination. Preferred over cat/head/tail. Output LINE_NUM|CONTENT. Reports similar filenames when missing. Use offset and limit for large files. Rejects >100K chars. No images or binary files; use vision_analyze for images.
```
