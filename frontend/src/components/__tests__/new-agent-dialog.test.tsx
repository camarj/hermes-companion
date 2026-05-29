import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"

import { NewAgentDialog } from "@/components/new-agent-dialog"

describe("NewAgentDialog (AC-W2-U1)", () => {
  it("exposes a type selector with hermes / openclaw / custom", () => {
    render(
      <NewAgentDialog open lang="en" onCreate={() => {}} onCancel={() => {}} />,
    )
    const select = screen.getByLabelText("Type") as HTMLSelectElement
    const options = Array.from(select.options).map((o) => o.value)
    expect(options).toEqual(["hermes", "openclaw", "custom"])
  })

  it("reveals url + token fields only for remote-acp transport", () => {
    render(
      <NewAgentDialog open lang="en" onCreate={() => {}} onCancel={() => {}} />,
    )
    // Local by default: no remote fields.
    expect(screen.queryByLabelText("URL")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Token")).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("Transport"), {
      target: { value: "remote-acp" },
    })
    expect(screen.getByLabelText("URL")).toBeInTheDocument()
    expect(screen.getByLabelText("Token")).toBeInTheDocument()
  })

  it("submits a local payload with an empty transport_config", () => {
    const onCreate = vi.fn()
    render(
      <NewAgentDialog open lang="en" onCreate={onCreate} onCancel={() => {}} />,
    )
    fireEvent.change(screen.getByLabelText("ID"), {
      target: { value: "my-openclaw" },
    })
    fireEvent.change(screen.getByLabelText("Label"), {
      target: { value: "OpenClaw local" },
    })
    fireEvent.change(screen.getByLabelText("Type"), {
      target: { value: "openclaw" },
    })
    fireEvent.click(screen.getByText("Create"))

    expect(onCreate).toHaveBeenCalledWith({
      id: "my-openclaw",
      label: "OpenClaw local",
      type: "openclaw",
      transport: "local-acp",
      transport_config: {},
    })
  })

  it("submits a remote payload carrying url + token", () => {
    const onCreate = vi.fn()
    render(
      <NewAgentDialog open lang="en" onCreate={onCreate} onCancel={() => {}} />,
    )
    fireEvent.change(screen.getByLabelText("ID"), {
      target: { value: "vps-prod" },
    })
    fireEvent.change(screen.getByLabelText("Label"), {
      target: { value: "Hermes VPS" },
    })
    fireEvent.change(screen.getByLabelText("Transport"), {
      target: { value: "remote-acp" },
    })
    fireEvent.change(screen.getByLabelText("URL"), {
      target: { value: "wss://host/api/host/acp" },
    })
    fireEvent.change(screen.getByLabelText("Token"), {
      target: { value: "env:VPS_HOST_TOKEN" },
    })
    fireEvent.click(screen.getByText("Create"))

    expect(onCreate).toHaveBeenCalledWith({
      id: "vps-prod",
      label: "Hermes VPS",
      type: "hermes",
      transport: "remote-acp",
      transport_config: { url: "wss://host/api/host/acp", token: "env:VPS_HOST_TOKEN" },
    })
  })

  it("disables Create until id and label are filled", () => {
    const onCreate = vi.fn()
    render(
      <NewAgentDialog open lang="en" onCreate={onCreate} onCancel={() => {}} />,
    )
    fireEvent.click(screen.getByText("Create"))
    expect(onCreate).not.toHaveBeenCalled()
  })

  it("does not render when open=false", () => {
    render(
      <NewAgentDialog
        open={false}
        lang="en"
        onCreate={() => {}}
        onCancel={() => {}}
      />,
    )
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  })

  it("cancel button calls onCancel", () => {
    const onCancel = vi.fn()
    render(
      <NewAgentDialog open lang="en" onCreate={() => {}} onCancel={onCancel} />,
    )
    fireEvent.click(screen.getByText("Cancel"))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})
