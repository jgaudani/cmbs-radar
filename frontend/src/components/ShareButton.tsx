import { useEffect, useRef, useState } from "react";

/** Copies a link (default: this page's URL, which carries its filters). Falls back to showing it. */
export function ShareButton({ url, label = "Share", title }: { url?: string; label?: string; title?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "manual">("idle");
  const input = useRef<HTMLInputElement>(null);
  const link = url ?? window.location.href;

  useEffect(() => {
    if (state === "copied") {
      const t = setTimeout(() => setState("idle"), 2000);
      return () => clearTimeout(t);
    }
    if (state === "manual") input.current?.select();
  }, [state]);

  const share = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setState("copied");
    } catch {
      setState("manual"); // clipboard blocked: let the user copy it
    }
  };

  return (
    <span className="share">
      <button onClick={share} title={title ?? "Copy a link to this view"}>
        {state === "copied" ? "Link copied" : label}
      </button>
      {state === "manual" && (
        <span className="popover" role="dialog" aria-label="Link to share">
          <input ref={input} readOnly value={link} aria-label="Link" />
          <button className="link" onClick={() => setState("idle")}>Done</button>
        </span>
      )}
    </span>
  );
}
