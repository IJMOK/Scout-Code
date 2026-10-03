// The "Testing" step of the agent loop, run in the scouts' own browser.
//
// 1. Check every <script> for syntax mistakes with Acorn.
// 2. Run the game in a small sandboxed window for a few seconds, pressing
//    SPACE and the arrow keys, and catch any crash.

const GameTester = (() => {
  const TEST_MS = 3500;

  function syntaxCheck(code) {
    const re = /<script(\s[^>]*)?>([\s\S]*?)<\/script>/gi;
    let m;
    while ((m = re.exec(code))) {
      if (m[1] && /\ssrc\s*=/.test(m[1])) return "The game tries to load a file from the internet, which won't work offline.";
      const before = code.slice(0, m.index + m[0].indexOf(">") + 1);
      const startLine = before.split("\n").length;
      try {
        acorn.parse(m[2], { ecmaVersion: "latest", sourceType: "script" });
      } catch (e) {
        const line = e.loc ? startLine + e.loc.line - 1 : "?";
        return `SyntaxError: ${e.message.replace(/\s*\(\d+:\d+\)$/, "")} (line ${line})`;
      }
    }
    return null;
  }

  // One line, no newlines, so the game's own line numbers stay correct.
  const HARNESS = "<script>(function(){var sent=0;function report(m){if(sent++<3)parent.postMessage({scoutTest:1,error:String(m)},'*');}" +
    "window.addEventListener('error',function(e){report((e.message||'Error')+(e.lineno?' (line '+e.lineno+')':''));});" +
    "window.addEventListener('unhandledrejection',function(e){report('Error: '+(e.reason&&e.reason.message||e.reason));});" +
    "var keys=[[' ','Space'],['ArrowRight','ArrowRight'],['ArrowUp','ArrowUp'],['ArrowLeft','ArrowLeft'],['ArrowDown','ArrowDown'],[' ','Space'],['ArrowRight','ArrowRight']];var i=0;" +
    "function press(){var k=keys[i%keys.length];var o={key:k[0],code:k[1],bubbles:true};document.dispatchEvent(new KeyboardEvent('keydown',o));" +
    "setTimeout(function(){document.dispatchEvent(new KeyboardEvent('keyup',o));},180);if(++i<keys.length)setTimeout(press,350);}" +
    "setTimeout(press,300);})();</script>";

  function withHarness(code) {
    const m = /<head[^>]*>/i.exec(code);
    if (m) return code.slice(0, m.index + m[0].length) + HARNESS + code.slice(m.index + m[0].length);
    return HARNESS + code;
  }

  // Resolves to { ok: true } or { ok: false, error: "..." }
  function test(code, holder) {
    const syntax = syntaxCheck(code);
    if (syntax) return Promise.resolve({ ok: false, error: syntax });

    return new Promise(resolve => {
      const frame = document.createElement("iframe");
      frame.setAttribute("sandbox", "allow-scripts");
      frame.setAttribute("title", "Testing the game");
      let done = false;
      const finish = result => {
        if (done) return;
        done = true;
        window.removeEventListener("message", onMessage);
        clearTimeout(timer);
        setTimeout(() => frame.remove(), 300);
        resolve(result);
      };
      const onMessage = ev => {
        if (ev.source === frame.contentWindow && ev.data && ev.data.scoutTest) {
          finish({ ok: false, error: ev.data.error });
        }
      };
      window.addEventListener("message", onMessage);
      const timer = setTimeout(() => finish({ ok: true }), TEST_MS);
      frame.srcdoc = withHarness(code);
      holder.appendChild(frame);
    });
  }

  return { test, syntaxCheck };
})();
