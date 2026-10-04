(function () {
  // Scout Code: on-screen buttons for phones and tablets. They press the same keys a keyboard would.
  if (!("ontouchstart" in window) && !(navigator.maxTouchPoints > 0)) return;
  var buttons = [["◀", "ArrowLeft", 0, 1], ["▶", "ArrowRight", 2, 1], ["▲", "ArrowUp", 1, 0], ["▼", "ArrowDown", 1, 2]];
  function send(type, key) {
    document.dispatchEvent(new KeyboardEvent(type, { key: key, code: key === " " ? "Space" : key, bubbles: true }));
  }
  function make(label, key, css) {
    var el = document.createElement("button");
    el.textContent = label;
    el.style.cssText = "position:fixed;z-index:99999;border-radius:50%;border:0;padding:0;" +
      "background:rgba(255,255,255,.3);color:#fff;font-weight:bold;font-family:sans-serif;" +
      "touch-action:none;user-select:none;-webkit-user-select:none;" + css;
    el.addEventListener("pointerdown", function (e) { e.preventDefault(); send("keydown", key); });
    ["pointerup", "pointerleave", "pointercancel"].forEach(function (t) {
      el.addEventListener(t, function () { send("keyup", key); });
    });
    document.body.appendChild(el);
  }
  window.addEventListener("load", function () {
    // Size the buttons to the game window, so they fit a small phone screen too.
    var s = Math.round(Math.max(26, Math.min(56, Math.min(innerWidth, innerHeight) * 0.15)));
    var gap = Math.round(s * 0.15);
    buttons.forEach(function (b) {
      make(b[0], b[1], "width:" + s + "px;height:" + s + "px;font-size:" + Math.round(s * 0.45) + "px;" +
        "left:" + (gap + b[2] * s) + "px;bottom:" + (gap + (2 - b[3]) * s) + "px");
    });
    var big = Math.round(s * 1.4);
    make("⎵", " ", "width:" + big + "px;height:" + big + "px;font-size:" + Math.round(s * 0.5) + "px;" +
      "right:" + gap * 2 + "px;bottom:" + (gap + s * 0.5) + "px");
  });
})();
