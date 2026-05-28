import { describe, expect, it, vi } from "vitest"
import { resolveVoiceConversationId } from "../useRealtime"

describe("resolveVoiceConversationId", () => {
  it("reuses the active conversation and never creates a new one", async () => {
    const createConversation = vi.fn()
    const id = await resolveVoiceConversationId({
      activeConversationId: "conv-remote",
      activeAgentId: "loopback-remote",
      createConversation,
    })
    expect(id).toBe("conv-remote")
    expect(createConversation).not.toHaveBeenCalled()
  })

  it("creates a conversation bound to the selected agent when none is active", async () => {
    const createConversation = vi.fn().mockResolvedValue({ id: "conv-new" })
    const id = await resolveVoiceConversationId({
      activeConversationId: null,
      activeAgentId: "loopback-remote",
      createConversation,
    })
    expect(createConversation).toHaveBeenCalledWith("loopback-remote")
    expect(id).toBe("conv-new")
  })

  it("creates with no agent (backend default) when nothing is selected", async () => {
    const createConversation = vi.fn().mockResolvedValue({ id: "conv-default" })
    const id = await resolveVoiceConversationId({
      activeConversationId: null,
      activeAgentId: null,
      createConversation,
    })
    expect(createConversation).toHaveBeenCalledWith(undefined)
    expect(id).toBe("conv-default")
  })
})
