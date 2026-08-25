/** Minimal escape-first markdown renderer cho bubble assistant.
 *  Escape toàn bộ HTML trước, rồi mới chuyển một tập whitelist cú pháp
 *  markdown sang thẻ — output an toàn để gắn bằng {@html} mà không cần
 *  sanitizer ngoài. Không hỗ trợ ảnh/thẻ HTML trong nội dung model. */

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

export function renderMarkdown(src: string): string {
  let s = esc(src);

  // Fenced code blocks được trích ra trước để các rule inline không đụng vào.
  const blocks: string[] = [];
  s = s.replace(/```([a-zA-Z0-9+#-]*)\n?([\s\S]*?)```/g, (_m, lang: string, code: string) => {
    const cls = lang ? ` class="lang-${esc(lang)}"` : "";
    blocks.push(`<pre><code${cls}>${code.replace(/\n$/, "")}</code></pre>`);
    return `\u0000B${blocks.length - 1}\u0000`;
  });
  // Fence chưa đóng (đang stream) — render phần có sẵn như code block.
  s = s.replace(/```([a-zA-Z0-9+#-]*)\n?([\s\S]*)$/g, (_m, lang: string, code: string) => {
    const cls = lang ? ` class="lang-${esc(lang)}"` : "";
    blocks.push(`<pre><code${cls}>${code}</code></pre>`);
    return `\u0000B${blocks.length - 1}\u0000`;
  });

  s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  s = s.replace(/^#{1,6}\s+(.+)$/gm, "<strong>$1</strong>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  // Bullets → dòng với dấu đầu dòng giữ nguyên (tránh xây cả cây list).
  // Gom paragraph: cách nhau bởi dòng trống; xuống dòng đơn thành <br>.
  const parts = s.split(/\u0000B(\d+)\u0000/);
  let out = "";
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 1) {
      out += blocks[Number(parts[i])];
      continue;
    }
    const seg = parts[i];
    if (!seg.trim()) continue;
    const paras = seg.split(/\n{2,}/);
    for (const p of paras) {
      const trimmed = p.trim();
      if (!trimmed) continue;
      out += `<p>${trimmed.replace(/\n/g, "<br>")}</p>`;
    }
  }
  return out;
}
