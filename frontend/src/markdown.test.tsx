import { render } from "@testing-library/react";
import { Markdown } from "./markdown";

test("renders bold, headings and bullets", () => {
  const { container } = render(<Markdown text={"**Worldwide Plaza, New York, NY**\n\n## Situation\n- one\n- *two*"} />);
  expect(container.querySelector("b")?.textContent).toBe("Worldwide Plaza, New York, NY");
  expect(container.querySelectorAll("li")).toHaveLength(2);
  expect(container.querySelector("i")?.textContent).toBe("two");
});

test("model output is text, never HTML", () => {
  const { container } = render(<Markdown text={'<script>alert(1)</script> <img src=x onerror="alert(2)"> **ok**'} />);
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(container.textContent).toContain("<script>alert(1)</script>");
});
