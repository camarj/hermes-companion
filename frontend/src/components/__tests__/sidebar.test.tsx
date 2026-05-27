import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"

import { Sidebar, agentBadgeColor } from "@/components/sidebar"
import type { AgentInstance, Conversation, User } from "@/lib/types"

function user(): User {
  return {
    id: "u1",
    name: "Alice",
    role: "CEO",
    is_shared_space: false,
    is_reunion: false,
  }
}

function conv(over: Partial<Conversation> = {}): Conversation {
  return {
    id: "c-1",
    user_id: "u1",
    title: "Hello",
    agent_id: null,
    created_at: "2026-05-27T10:00:00Z",
    updated_at: "2026-05-27T10:00:00Z",
    ...over,
  }
}

function agent(over: Partial<AgentInstance> = {}): AgentInstance {
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

describe("Sidebar agent grouping (AC-W1-U2)", () => {
  it("renders one group header per distinct agent", () => {
    const conversations = [
      conv({ id: "c-1", agent_id: "local-default", title: "A1" }),
      conv({ id: "c-2", agent_id: "vps-prod", title: "B1" }),
      conv({ id: "c-3", agent_id: "local-default", title: "A2" }),
    ]
    const agents = [
      agent({ id: "local-default", label: "Hermes (local)" }),
      agent({ id: "vps-prod", label: "Hermes (VPS prod)", transport: "remote-acp" }),
    ]
    render(
      <Sidebar
        config={null}
        user={user()}
        conversations={conversations}
        agents={agents}
        activeId={null}
        lang="en"
        onSelect={() => {}}
        onNew={() => {}}
        onDelete={() => {}}
        onLogout={() => {}}
      />,
    )

    expect(screen.getByText("Hermes (local)")).toBeInTheDocument()
    expect(screen.getByText("Hermes (VPS prod)")).toBeInTheDocument()
  })

  it("each conversation row carries a badge colored from its agent_id", () => {
    const conversations = [
      conv({ id: "c-1", agent_id: "local-default", title: "A1" }),
      conv({ id: "c-2", agent_id: "vps-prod", title: "B1" }),
    ]
    const agents = [
      agent({ id: "local-default", label: "Local" }),
      agent({ id: "vps-prod", label: "VPS", transport: "remote-acp" }),
    ]
    render(
      <Sidebar
        config={null}
        user={user()}
        conversations={conversations}
        agents={agents}
        activeId={null}
        lang="en"
        onSelect={() => {}}
        onNew={() => {}}
        onDelete={() => {}}
        onLogout={() => {}}
      />,
    )

    const badge1 = screen.getByTestId("conv-badge-c-1")
    const badge2 = screen.getByTestId("conv-badge-c-2")
    const c1Color = badge1.style.backgroundColor
    const c2Color = badge2.style.backgroundColor
    // Both badges have a non-empty color, and the two distinct agents
    // produce distinct colors.
    expect(c1Color).not.toBe("")
    expect(c2Color).not.toBe("")
    expect(c1Color).not.toBe(c2Color)
  })

  it("conversations with no agent_id render under the Unassigned group", () => {
    const conversations = [conv({ id: "c-orph", agent_id: null, title: "Orphan" })]
    render(
      <Sidebar
        config={null}
        user={user()}
        conversations={conversations}
        agents={[]}
        activeId={null}
        lang="en"
        onSelect={() => {}}
        onNew={() => {}}
        onDelete={() => {}}
        onLogout={() => {}}
      />,
    )
    expect(screen.getByText("Unassigned")).toBeInTheDocument()
    expect(screen.getByTestId("conv-badge-c-orph")).toBeInTheDocument()
  })

  it("agent badge color is deterministic by agent_id", () => {
    const a = agentBadgeColor("local-default")
    const b = agentBadgeColor("local-default")
    const c = agentBadgeColor("vps-prod")
    expect(a).toBe(b)
    expect(a).not.toBe(c)
  })
})
