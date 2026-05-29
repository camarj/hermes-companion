import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"
import { MessageBubble } from "@/components/chat/message-bubble"
import type { UIMessage } from "ai"
import type { Artifact, User } from "@/lib/types"

function user(): User {
  return {
    id: "u1",
    name: "Alice",
    role: "tester",
    is_shared_space: false,
    is_reunion: false,
  }
}

function assistantMessage(text: string): UIMessage {
  return {
    id: "msg-1",
    role: "assistant",
    parts: [{ type: "text", text }],
  }
}

function artifact(over: Partial<Artifact> = {}): Artifact {
  return {
    id: "art-001",
    name: "report.md",
    mime_type: "text/markdown",
    size_bytes: 13,
    message_id: "msg-1",
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  }
}

// Scenario 9 — message bubble shows download affordance
describe("MessageBubble with artifacts (Scenario 9)", () => {
  it("renders a download chip row when artifacts are provided", () => {
    render(
      <MessageBubble
        message={assistantMessage("Here is your report.")}
        currentUser={user()}
        artifacts={[artifact()]}
      />,
    )

    expect(screen.getByText("report.md")).toBeInTheDocument()
    const link = screen.getByRole("link", { name: /report\.md/i })
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute("href", expect.stringContaining("art-001"))
    expect(link).toHaveAttribute("download")
  })

  it("renders a chip for each artifact when multiple are present", () => {
    render(
      <MessageBubble
        message={assistantMessage("Two files produced.")}
        currentUser={user()}
        artifacts={[
          artifact({ id: "art-001", name: "file1.txt" }),
          artifact({ id: "art-002", name: "file2.csv" }),
        ]}
      />,
    )

    expect(screen.getByText("file1.txt")).toBeInTheDocument()
    expect(screen.getByText("file2.csv")).toBeInTheDocument()
    expect(screen.getAllByRole("link")).toHaveLength(2)
  })
})

// Scenario 10 — message bubble omits affordance when no artifacts
describe("MessageBubble without artifacts (Scenario 10)", () => {
  it("renders no download affordance when artifacts prop is omitted", () => {
    render(
      <MessageBubble
        message={assistantMessage("No files.")}
        currentUser={user()}
      />,
    )

    expect(screen.queryByRole("link")).not.toBeInTheDocument()
  })

  it("renders no download affordance when artifacts array is empty", () => {
    render(
      <MessageBubble
        message={assistantMessage("No files.")}
        currentUser={user()}
        artifacts={[]}
      />,
    )

    expect(screen.queryByRole("link")).not.toBeInTheDocument()
  })
})
