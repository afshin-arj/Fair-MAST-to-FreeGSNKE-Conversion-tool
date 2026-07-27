/* Smooth tab media: defer off-screen image decode without changing layout. */
(function () {
  function markLazy(root) {
    var scope = root || document;
    var imgs = scope.querySelectorAll
      ? scope.querySelectorAll("img.media-img")
      : [];
    for (var i = 0; i < imgs.length; i++) {
      var img = imgs[i];
      if (!img.getAttribute("loading")) {
        img.setAttribute("loading", "lazy");
      }
      if (!img.getAttribute("decoding")) {
        img.setAttribute("decoding", "async");
      }
    }
  }

  function boot() {
    markLazy(document);
    if (typeof MutationObserver === "undefined") {
      return;
    }
    var obs = new MutationObserver(function (mutations) {
      for (var i = 0; i < mutations.length; i++) {
        var m = mutations[i];
        for (var j = 0; j < m.addedNodes.length; j++) {
          var n = m.addedNodes[j];
          if (n && n.nodeType === 1) {
            markLazy(n);
          }
        }
      }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
