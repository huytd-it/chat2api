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

function renderInline(value: string): string {
  return value
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
    );
}

export function renderMarkdown(src: string): string {
  let s = esc(src.replace(/\r\n?/g, "\n"));

  // Fenced code blocks được trích ra trước để các rule inline không đụng vào.
  const blocks: string[] = [];
  s = s.replace(/```([a-zA-Z0-9+#-]*)\n?([\s\S]*?)```/g, (_m, lang: string, code: string) => {
    const cls = lang ? ` class="lang-${esc(lang)}"` : "";
    blocks.push(`<pre><code${cls}>${code.replace(/\n$/, "")}</code></pre>`);
    return `\n\u0000B${blocks.length - 1}\u0000\n`;
  });
  // Fence chưa đóng (đang stream) — render phần có sẵn như code block.
  s = s.replace(/```([a-zA-Z0-9+#-]*)\n?([\s\S]*)$/g, (_m, lang: string, code: string) => {
    const cls = lang ? ` class="lang-${esc(lang)}"` : "";
    blocks.push(`<pre><code${cls}>${code}</code></pre>`);
    return `\n\u0000B${blocks.length - 1}\u0000\n`;
  });

  const out: string[] = [];
  let paragraph: string[] = [];
  const flushParagraph = () => {
    if (!paragraph.length) return;
    out.push(`<p>${paragraph.map(renderInline).join("\n")}</p>`);
    paragraph = [];
  };

  const lines = s.split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const block = line.trim().match(/^\u0000B(\d+)\u0000$/);
    if (block) {
      flushParagraph();
      out.push(blocks[Number(block[1])]);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      continue;
    }

    const heading = line.match(/^ {0,3}(#{1,6})(?:[ \t]+|$)(.*)$/);
    if (heading) {
      flushParagraph();
      const level = heading[1].length;
      const content = heading[2].replace(/[ \t]+#+[ \t]*$/, "").trim();
      out.push(`<h${level}>${renderInline(content)}</h${level}>`);
      continue;
    }

    if (/^ {0,3}((\* *){3,}|(- *){3,}|(_ *){3,})$/.test(line)) {
      flushParagraph();
      out.push("<hr>");
      continue;
    }

    const listItem = line.match(/^\s*([-+*]|\d+[.)])\s+(.+)$/);
    if (listItem) {
      flushParagraph();
      const ordered = /^\d/.test(listItem[1]);
      const tag = ordered ? "ol" : "ul";
      const items: string[] = [];
      let cursor = index;
      while (cursor < lines.length) {
        const item = lines[cursor].match(/^\s*([-+*]|\d+[.)])\s+(.+)$/);
        if (!item || /^\d/.test(item[1]) !== ordered) break;
        items.push(`<li>${renderInline(item[2].trim())}</li>`);
        cursor += 1;
      }
      out.push(`<${tag}>${items.join("")}</${tag}>`);
      index = cursor - 1;
      continue;
    }

    // Setext heading: dòng chữ theo sau bởi === hoặc ---.
    const underline = lines[index + 1]?.match(/^ {0,3}(=+|-+)[ \t]*$/);
    if (underline) {
      flushParagraph();
      const level = underline[1][0] === "=" ? 1 : 2;
      out.push(`<h${level}>${renderInline(line.trim())}</h${level}>`);
      index += 1;
      continue;
    }

    paragraph.push(line.trim());
  }
  flushParagraph();
  return out.join("");
}
