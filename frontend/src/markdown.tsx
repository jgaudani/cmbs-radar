import type { ReactNode } from "react";

// Minimal Markdown for briefs (bold, italics, headings, bullets, paragraphs)
// rendered as React elements: model output is always text, never HTML.

function inline(s: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|\*(.+?)\*/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    out.push(m[1] != null ? <b key={`${key}-${i++}`}>{m[1]}</b> : <i key={`${key}-${i++}`}>{m[2]}</i>);
    last = re.lastIndex;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: ReactNode[] | null = null;
  const flush = () => {
    if (list) blocks.push(<ul key={`ul-${blocks.length}`}>{list}</ul>);
    list = null;
  };
  text.split("\n").forEach((raw, n) => {
    const line = raw.trim();
    if (/^[-*] /.test(line)) {
      (list ??= []).push(<li key={n}>{inline(line.slice(2), `li${n}`)}</li>);
      return;
    }
    flush();
    if (!line) return;
    const h = line.match(/^#{1,4} (.*)/);
    blocks.push(<p key={n}>{h ? <b>{inline(h[1], `h${n}`)}</b> : inline(line, `p${n}`)}</p>);
  });
  flush();
  return <>{blocks}</>;
}
