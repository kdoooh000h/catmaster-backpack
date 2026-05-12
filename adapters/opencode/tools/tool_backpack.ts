import { tool } from "@opencode-ai/plugin"

type ToolEntry = {
  id: number
  name: string
  description: string
}

const tools: ToolEntry[] = [
  { id: 101, name: "grep", description: "search file content" },
  { id: 102, name: "glob", description: "search file names" },
  { id: 103, name: "read", description: "read files" },
  { id: 201, name: "edit", description: "edit files" },
  { id: 202, name: "bash", description: "run shell commands" },
]

function toolIndex() {
  return {
    status: "ok",
    decision: "tool_index",
    d: "index",
    tools: tools.map((entry) => [entry.id, entry.name, entry.description]),
    next: "select <id|tool_name>",
    note: "This portable OpenCode adapter returns Tool Backpack protocol decisions; it does not hide native OpenCode tools.",
  }
}

function selectedTools(request: string) {
  const rawSelector = request.replace(/^select\s+/i, "").trim()
  const selectors = rawSelector.split(/[\s,]+/).filter(Boolean)
  const selected = selectors.map((selector) =>
    tools.find((entry) => String(entry.id) === selector || entry.name === selector),
  )
  if (selected.some((entry) => entry === undefined)) {
    return {
      status: "blocked",
      decision: "unknown_tool",
      d: "blocked",
      next: "select <id|tool_name>",
    }
  }
  const names = selected.map((entry) => entry!.name)
  if (names.length === 1) {
    const selectedEntry = selected[0]!
    return {
      status: "ok",
      decision: "select_tool",
      d: "selected",
      id: selectedEntry.id,
      tool: selectedEntry.name,
      next: `call ${selectedEntry.name}`,
      note: "This portable OpenCode adapter returns Tool Backpack protocol decisions; it does not hide native OpenCode tools.",
    }
  }
  return {
    status: "ok",
    decision: "select_tools",
    d: "selected",
    tools: names,
    next: "call selected tools",
    note: "This portable OpenCode adapter returns Tool Backpack protocol decisions; it does not hide native OpenCode tools.",
  }
}

export default tool({
  description: "Tool gateway.",
  args: {
    request: tool.schema.string().describe("Use index or select <id|tool_name>"),
  },
  async execute(args) {
    const request = args.request.trim()
    if (/^(index|list|tools)$/i.test(request)) {
      return JSON.stringify(toolIndex())
    }
    if (/^(select\s+)?[A-Za-z0-9_,\s-]+$/.test(request)) {
      return JSON.stringify(selectedTools(request.match(/^select\s+/i) ? request : `select ${request}`))
    }
    return JSON.stringify({
      status: "blocked",
      decision: "needs_selection",
      d: "blocked",
      next: "select <id|tool_name>",
    })
  },
})
