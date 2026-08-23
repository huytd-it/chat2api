SNAPSHOT_JS = """() => {
  const sel = 'input, textarea, button, [role=textbox], [role=button], [contenteditable=true]';
  const lines = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (!r.width && !r.height) continue;
    let s;
    if (el.id) s = '#' + CSS.escape(el.id);
    else if (el.name) s = el.tagName.toLowerCase() + '[name="' + el.name + '"]';
    else {
      s = el.tagName.toLowerCase();
      const sibs = [...el.parentElement.children].filter(e => e.tagName === el.tagName);
      if (sibs.length > 1) s += ':nth-of-type(' + (sibs.indexOf(el) + 1) + ')';
    }
    const label = (el.getAttribute('aria-label') || el.placeholder ||
                   (el.innerText || '')).trim().slice(0, 80);
    const role = el.getAttribute('role') || '';
    lines.push(el.tagName.toLowerCase() + ' role=' + role +
               ' label=' + JSON.stringify(label) + ' sel=' + s);
  }
  const bigTexts = [...document.querySelectorAll('div, p, section')]
    .filter(e => e.innerText && e.innerText.length > 60 && !e.querySelector(sel))
    .map(e => e.innerText.trim().replace(/\\s+/g, ' ').slice(0, 200));
  return lines.join('\\n') + '\\n---TEXT---\\n' + bigTexts.slice(-8).join('\\n');
}"""


async def snapshot(page) -> str:
    return await page.evaluate(SNAPSHOT_JS)
