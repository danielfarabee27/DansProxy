const $ = (id) => document.getElementById(id);

// Remove the service worker left behind by the earlier Scramjet-based version.
if (navigator.serviceWorker) {
  navigator.serviceWorker.getRegistrations().then((regs) => regs.forEach((r) => r.unregister()));
}
const home = $("home");
const viewer = $("viewer");
const frame = $("frame");
const spinner = $("spinner");
const progress = $("progress");

function normalizeUrl(input) {
  let value = input.trim();
  if (!value) throw new Error("Please enter a web address.");
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
    if (/\s/.test(value) || !value.includes(".")) {
      throw new Error("That doesn't look like a web address. Try something like example.com.");
    }
    value = "https://" + value;
  }
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error("That doesn't look like a valid web address.");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("Only http:// and https:// addresses are supported.");
  }
  return url.href;
}

function showError(el, message) {
  el.textContent = message;
  el.hidden = !message;
}

function setLoading(on, firstLoad = false) {
  progress.hidden = !on;
  spinner.hidden = !(on && firstLoad);
}

function openViewer(url, push = true) {
  home.hidden = true;
  viewer.hidden = false;
  showError($("bar-error"), "");
  $("bar-input").value = url;
  if (push) history.pushState({ url }, "", "/?url=" + encodeURIComponent(url));
  setLoading(true, true);
  frame.src = "/p/" + url;
}

function openHome() {
  frame.removeAttribute("src");
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
      openViewer(normalizeUrl($(inputId).value));
    } catch (err) {
      showError($(errorId), err.message);
    }
  });
  $(inputId).addEventListener("input", () => showError($(errorId), ""));
}

bindForm("home-form", "home-input", "home-error");
bindForm("bar-form", "bar-input", "bar-error");

frame.addEventListener("load", () => {
  if (!frame.getAttribute("src")) return;
  setLoading(false);
  try {
    const win = frame.contentWindow;
    const loc = win.location;
    if (loc.pathname.startsWith("/p/")) {
      const current = loc.pathname.slice(3) + loc.search + loc.hash;
      $("bar-input").value = current;
      history.replaceState({ url: current }, "", "/?url=" + encodeURIComponent(current));
    }
    document.title = (frame.contentDocument.title || "Page") + " \u2013 DansProxy";
    win.addEventListener("beforeunload", () => setLoading(true));
  } catch {
    /* page not readable; ignore */
  }
});

$("home-btn").addEventListener("click", (e) => {
  e.preventDefault();
  history.pushState({}, "", "/");
  openHome();
});

function route(push) {
  const url = new URLSearchParams(location.search).get("url");
  if (url) {
    try {
      openViewer(normalizeUrl(url), push);
      return;
    } catch { /* fall through to home */ }
  }
  openHome();
}

window.addEventListener("popstate", () => route(false));
route(false);
