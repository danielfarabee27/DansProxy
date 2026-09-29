const $ = (id) => document.getElementById(id);
const home = $("home");
const viewer = $("viewer");
const spinner = $("spinner");
const progress = $("progress");
const SEARCH_URL = "https://duckduckgo.com/?q=";

let scramjet = null;
let connection = null;
let frame = null;
let ready = null;

function visibleErrorEl() {
  return viewer.hidden ? $("home-error") : $("bar-error");
}

window.addEventListener("error", (e) => {
  showError(visibleErrorEl(), "Something went wrong: " + (e.message || "unknown error"));
});
window.addEventListener("unhandledrejection", (e) => {
  showError(visibleErrorEl(), "Something went wrong: " + ((e.reason && e.reason.message) || e.reason));
});

function initScramjet() {
  if (typeof $scramjetLoadController !== "function" || typeof BareMux === "undefined") {
    throw new Error("The proxy's files didn't load. A network filter may be blocking this site.");
  }
  const { ScramjetController } = $scramjetLoadController();
  scramjet = new ScramjetController({
    files: {
      wasm: "/scram/scramjet.wasm.wasm",
      all: "/scram/scramjet.all.js",
      sync: "/scram/scramjet.sync.js",
    },
  });
  scramjet.init();
  connection = new BareMux.BareMuxConnection("/baremux/worker.js");
}

function toUrl(input) {
  const value = input.trim();
  if (!value) throw new Error("Please enter a web address or search terms.");
  if (/^https?:\/\//i.test(value)) {
    try {
      return new URL(value).href;
    } catch {
      throw new Error("That doesn't look like a valid web address.");
    }
  }
  if (!/\s/.test(value) && /^[^/]+\.[a-z]{2,}(\/|$|:|\?)/i.test(value)) {
    return new URL("https://" + value).href;
  }
  return SEARCH_URL + encodeURIComponent(value);
}

// libcurl loads its WebAssembly asynchronously; requests made before that finishes fail.
async function waitForTransport() {
  const client = new BareMux.BareClient();
  for (let i = 0; i < 60; i++) {
    try {
      await client.fetch("https://example.com/", { method: "HEAD" });
      return;
    } catch (err) {
      if (!/wasm not loaded/i.test(String(err))) return;
      await new Promise((r) => setTimeout(r, 250));
    }
  }
  throw new Error("The proxy took too long to start. Please reload the page.");
}

function setup() {
  if (ready) return ready;
  ready = (async () => {
    if (!scramjet) initScramjet();
    if (!navigator.serviceWorker) {
      throw new Error("Your browser doesn't support this proxy. Try an up-to-date Chrome, Edge, or Firefox.");
    }
    await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    const wispUrl = (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + "/wisp/";
    if ((await connection.getTransport()) !== "/libcurl/index.mjs") {
      await connection.setTransport("/libcurl/index.mjs", [{ websocket: wispUrl }]);
    }
    await waitForTransport();
    frame = scramjet.createFrame();
    frame.frame.id = "frame";
    frame.frame.title = "Proxied page";
    frame.frame.allow = "fullscreen; autoplay; encrypted-media; picture-in-picture";
    frame.frame.allowFullscreen = true;
    $("frame-wrap").appendChild(frame.frame);
    frame.frame.addEventListener("load", () => setLoading(false));
    frame.addEventListener("navigate", () => setLoading(true));
    frame.addEventListener("urlchange", (e) => {
      const url = String(e.url);
      $("bar-input").value = url;
      history.replaceState({ url }, "", "/?url=" + encodeURIComponent(url));
      try {
        document.title = (frame.frame.contentDocument.title || "Page") + " \u2013 DansProxy";
      } catch { /* not readable yet */ }
    });
  })();
  ready.catch(() => { ready = null; });
  return ready;
}

function showError(el, message) {
  el.textContent = message;
  el.hidden = !message;
}

let loadingTimer = null;

// Heavy sites keep loading long after they're usable, so hide the spinner once the page renders
// and give up on the progress bar after a while.
function setLoading(on, firstLoad = false) {
  progress.hidden = !on;
  spinner.hidden = !(on && firstLoad);
  clearInterval(loadingTimer);
  if (!on) return;
  const started = Date.now();
  loadingTimer = setInterval(() => {
    let rendered = false;
    try {
      const doc = frame && frame.frame.contentDocument;
      rendered = !!doc && doc.readyState !== "loading" && !!doc.body && doc.body.childElementCount > 0;
    } catch { /* cross-origin or not ready */ }
    if (rendered) spinner.hidden = true;
    if (Date.now() - started > 15000) setLoading(false);
  }, 300);
}

async function openViewer(url, push = true) {
  home.hidden = true;
  viewer.hidden = false;
  showError($("bar-error"), "");
  $("bar-input").value = url;
  if (push) history.pushState({ url }, "", "/?url=" + encodeURIComponent(url));
  setLoading(true, true);
  try {
    await setup();
    frame.go(url);
  } catch (err) {
    setLoading(false);
    showError($("bar-error"), "Couldn't start the proxy: " + (err.message || err));
  }
}

function openHome() {
  if (frame) frame.frame.src = "about:blank";
  setLoading(false);
  viewer.hidden = true;
  home.hidden = false;
  document.title = "DansProxy";
  $("home-input").focus();
}

function bindForm(formId, inputId, errorId) {
  $(formId).addEventListener("submit", (e) => {
    e.preventDefault();
    try {
      openViewer(toUrl($(inputId).value));
    } catch (err) {
      showError($(errorId), err.message);
    }
  });
  $(inputId).addEventListener("input", () => showError($(errorId), ""));
}

bindForm("home-form", "home-input", "home-error");
bindForm("bar-form", "bar-input", "bar-error");

$("home-btn").addEventListener("click", (e) => {
  e.preventDefault();
  history.pushState({}, "", "/");
  openHome();
});

function route(push) {
  const url = new URLSearchParams(location.search).get("url");
  if (url) {
    try {
      openViewer(toUrl(url), push);
      return;
    } catch { /* fall through to home */ }
  }
  openHome();
}

window.addEventListener("popstate", () => route(false));
route(false);
