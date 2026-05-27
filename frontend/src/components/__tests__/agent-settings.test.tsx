import { describe, expect, it, vi, beforeEach, afterEach } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import { AgentSettings } from "@/components/agent-settings"
import { api } from "@/lib/api"
import type { AgentInstance } from "@/lib/types"

function makeAgent(over: Partial<AgentInstance> = {}): AgentInstance {
  return {
    id: "local-default",
    label: "Hermes (local)",
    type: "hermes",
    transport: "local-acp",
    transport_config: {},
    system_prompt_override: null,
    enabled: true,
    created_via: "config",
    created_at: "2026-05-27T00:00:00Z",
    updated_at: "2026-05-27T00:00:00Z",
    ...over,
  }
}

const ok = (stdout: string) => ({ stdout, stderr: "", exit_code: 0 })

let inspectionSpy: ReturnType<typeof vi.spyOn>
let saveSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  inspectionSpy = vi
    .spyOn(api, "getAgentInspection")
    .mockImplementation(async (_id, kind) => ok(`${kind}-output\nrow`))
  saveSpy = vi
    .spyOn(api, "setAgentSystemPrompt")
    .mockImplementation(async (_id, prompt) =>
      makeAgent({ system_prompt_override: prompt }),
    )
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("AgentSettings (AC-W1-U4 / U5 frontend)", () => {
  it("renders the agent label and four read-only inspection sections", async () => {
    render(
      <AgentSettings
        open
        onOpenChange={() => {}}
        agent={makeAgent()}
        lang="en"
      />,
    )

    expect(screen.getByText("Hermes (local)")).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId("inspection-skills")).toBeInTheDocument()
      expect(screen.getByTestId("inspection-mcp")).toBeInTheDocument()
      expect(screen.getByTestId("inspection-tools")).toBeInTheDocument()
      expect(screen.getByTestId("inspection-config")).toBeInTheDocument()
    })

    expect(screen.getByTestId("inspection-skills").textContent).toContain(
      "skills-output",
    )
    expect(inspectionSpy).toHaveBeenCalledTimes(4)
  })

  it("preloads the textarea with the agent's stored system_prompt_override", () => {
    render(
      <AgentSettings
        open
        onOpenChange={() => {}}
        agent={makeAgent({ system_prompt_override: "Be terse." })}
        lang="en"
      />,
    )
    const textarea = screen.getByLabelText("System prompt") as HTMLTextAreaElement
    expect(textarea.value).toBe("Be terse.")
  })

  it("save button calls api.setAgentSystemPrompt and shows confirmation", async () => {
    const onSaved = vi.fn()
    render(
      <AgentSettings
        open
        onOpenChange={() => {}}
        agent={makeAgent()}
        lang="en"
        onSaved={onSaved}
      />,
    )

    const textarea = screen.getByLabelText("System prompt") as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: "You are terse." } })
    fireEvent.click(screen.getByText("Save"))

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledWith("local-default", "You are terse.")
      expect(screen.getByText("Saved")).toBeInTheDocument()
      expect(onSaved).toHaveBeenCalled()
    })
  })

  it("shows an error message when save fails", async () => {
    saveSpy.mockRejectedValueOnce(new Error("network"))
    render(
      <AgentSettings
        open
        onOpenChange={() => {}}
        agent={makeAgent()}
        lang="en"
      />,
    )
    fireEvent.click(screen.getByText("Save"))
    await waitFor(() => {
      expect(screen.getByText("Save failed.")).toBeInTheDocument()
    })
  })

  it("does not load inspection or render fields when closed", () => {
    render(
      <AgentSettings
        open={false}
        onOpenChange={() => {}}
        agent={makeAgent()}
        lang="en"
      />,
    )
    expect(inspectionSpy).not.toHaveBeenCalled()
  })

  it("shows a per-section error when an inspection fetch fails", async () => {
    inspectionSpy.mockImplementation(
      async (_id: string, kind: "skills" | "mcp" | "tools" | "config") => {
        if (kind === "tools") throw new Error("nope")
        return ok(`${kind}-output`)
      },
    )
    render(
      <AgentSettings
        open
        onOpenChange={() => {}}
        agent={makeAgent()}
        lang="en"
      />,
    )
    await waitFor(() => {
      expect(screen.getByText("nope")).toBeInTheDocument()
    })
    // Other sections still render.
    expect(screen.getByTestId("inspection-skills")).toBeInTheDocument()
  })
})
