// Read-only code viewer: syntax colours, line numbers, and a glow on the
// lines the AI just changed. Uses the vendored Prism and jsdiff.

const CodeView = (() => {
  // Prism gives one big HTML string; split it into lines but keep the
  // colour <span>s open across line breaks (e.g. multi-line comments).
  function splitHighlighted(html) {
    const lines = [];
    const open = [];
    let current = "";
    const re = /(<span[^>]*>)|(<\/span>)|(\n)|([^<\n]+|<)/g;
    let m;
    while ((m = re.exec(html))) {
      if (m[1]) { open.push(m[1]); current += m[1]; }
      else if (m[2]) { open.pop(); current += m[2]; }
      else if (m[3]) {
        current += "</span>".repeat(open.length);
        lines.push(current);
        current = open.join("");
      } else current += m[4];
    }
    lines.push(current + "</span>".repeat(open.length));
    return lines;
  }

  function highlight(code) {
    try {
      return splitHighlighted(Prism.highlight(code, Prism.languages.markup, "markup"));
    } catch (e) {
      return code.split("\n").map(esc);
    }
  }

  // Which lines of `code` are new compared to `prev`, and where were lines removed?
  function changes(prev, code) {
    const added = new Set();
    const removedAbove = new Set();
    if (prev == null || prev === code) return { added, removedAbove };
    let line = 0;
    for (const part of Diff.diffLines(prev, code)) {
      if (part.added) {
        for (let i = 0; i < part.count; i++) added.add(line + i);
        line += part.count;
      } else if (part.removed) {
        removedAbove.add(line);
      } else {
        line += part.count;
      }
    }
    return { added, removedAbove };
  }

  function render(container, code, prev) {
    const lines = highlight(code);
    const { added, removedAbove } = changes(prev, code);
    const out = [];
    for (let i = 0; i < lines.length; i++) {
      const cls = ["ln"];
      if (added.has(i)) cls.push("added");
      if (removedAbove.has(i) && !added.has(i)) cls.push("removed-above");
      out.push(`<div class="${cls.join(" ")}" data-line="${i + 1}"><span class="num">${i + 1}</span><span class="src">${lines[i] || " "}</span></div>`);
    }
    container.innerHTML = `<div class="code language-markup">${out.join("")}</div>`;
    const first = container.querySelector(".ln.added, .ln.removed-above");
    if (first) first.scrollIntoView({ block: "center" });
    return { added: added.size, removed: removedAbove.size };
  }

  // The code the scouts have highlighted with the mouse, if it's inside `container`.
  function selection(container) {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !container.contains(sel.anchorNode)) return "";
    return sel.toString().trim();
  }

  // Text of the glowing (changed) lines, used when nothing is selected.
  function changedText(container) {
    return $all(".ln.added .src", container).map(el => el.textContent).join("\n").trim();
  }

  return { render, selection, changedText, changes };
})();
