import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"

import { NewConversationDialog } from "@/components/new-conversation-dialog"
import type { AgentInstance } from "@/lib/types"

function makeAgent(overrides: Partial<AgentInstance> = {}): AgentInstance {
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
    ...overrides,
  }
}

describe("NewConversationDialog (AC-W1-U3)", () => {
  it("renders a select when more than one enabled agent exists", () => {
    const agents = [
      makeAgent({ id: "local-default", label: "Hermes (local)" }),
      makeAgent({
        id: "vps-prod",
        label: "Hermes (VPS prod)",
        transport: "remote-acp",
      }),
    ]
    render(
      <NewConversationDialog
        open
        agents={agents}
        lang="en"
        onSelect={() => {}}
        onCancel={() => {}}
      />,
    )

    const dialog = screen.getByRole("dialog")
    expect(dialog).toBeInTheDocument()
    const select = screen.getByLabelText("Agent") as HTMLSelectElement
    const options = Array.from(select.options).map((o) => o.value)
    expect(options).toEqual(["local-default", "vps-prod"])
  })

  it("submits the selected agent id to onSelect", () => {
    const onSelect = vi.fn()
    const agents = [
      makeAgent({ id: "local-default", label: "Hermes (local)" }),
      makeAgent({ id: "vps-prod", label: "VPS", transport: "remote-acp" }),
    ]
    render(
      <NewConversationDialog
        open
        agents={agents}
        lang="en"
        onSelect={onSelect}
        onCancel={() => {}}
      />,
    )

    const select = screen.getByLabelText("Agent") as HTMLSelectElement
    fireEvent.change(select, { target: { value: "vps-prod" } })
    fireEvent.click(screen.getByText("Create"))

    expect(onSelect).toHaveBeenCalledWith("vps-prod")
  })

  it("skips render and auto-fires onSelect when only one enabled agent", () => {
    const onSelect = vi.fn()
    const agents = [makeAgent({ id: "only-one" })]
    const { container } = render(
      <NewConversationDialog
        open
        agents={agents}
        lang="en"
        onSelect={onSelect}
        onCancel={() => {}}
      />,
    )

    // No dialog rendered.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(container.firstChild).toBeNull()
    expect(onSelect).toHaveBeenCalledWith("only-one")
  })

  it("ignores disabled agents when computing the count", () => {
    const onSelect = vi.fn()
    const agents = [
      makeAgent({ id: "local-default", enabled: true }),
      makeAgent({ id: "off", label: "Disabled", enabled: false }),
    ]
    render(
      <NewConversationDialog
        open
        agents={agents}
        lang="en"
        onSelect={onSelect}
        onCancel={() => {}}
      />,
    )

    // Only one enabled → auto-fire path.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(onSelect).toHaveBeenCalledWith("local-default")
  })

  it("does not render when open=false", () => {
    render(
      <NewConversationDialog
        open={false}
        agents={[makeAgent(), makeAgent({ id: "b" })]}
        lang="en"
        onSelect={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("cancel button calls onCancel", () => {
    const onCancel = vi.fn()
    render(
      <NewConversationDialog
        open
        agents={[
          makeAgent({ id: "a" }),
          makeAgent({ id: "b", label: "B" }),
        ]}
        lang="en"
        onSelect={() => {}}
        onCancel={onCancel}
      />,
    )
    fireEvent.click(screen.getByText("Cancel"))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})
