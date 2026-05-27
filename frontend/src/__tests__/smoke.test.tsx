import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

describe("frontend test runner smoke", () => {
  it("vitest runs and discovers this test", () => {
    expect(1 + 1).toBe(2);
  });

  it("renders a React node with Testing Library", () => {
    render(<p>hermes-companion</p>);
    expect(screen.getByText("hermes-companion")).toBeInTheDocument();
  });
});
