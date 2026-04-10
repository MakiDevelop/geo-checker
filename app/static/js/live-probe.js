/**
 * Live AI Probe — BYOK client.
 * API key stored ONLY in localStorage, sent only as X-Perplexity-Key header.
 *
 * SECURITY: This file uses textContent + createElement exclusively.
 * No HTML string injection APIs are used because Perplexity responses are untrusted.
 */
(function() {
  "use strict";

  var STORAGE_KEY = "geo_checker_pplx_key";

  function getKey() {
    try {
      return localStorage.getItem(STORAGE_KEY) || "";
    } catch (e) {
      return "";
    }
  }

  function setKey(key) {
    try {
      if (key) {
        localStorage.setItem(STORAGE_KEY, key);
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch (e) {}
  }

  function maskKey(key) {
    if (!key || key.length < 12) {
      return "";
    }
    return key.slice(0, 6) + "..." + key.slice(-4);
  }

  function updateKeyStatus() {
    var key = getKey();
    var statusEl = document.getElementById("probe-key-status");
    var input = document.getElementById("pplx-key-input");
    var clearBtn = document.getElementById("probe-clear-key");
    var runBtn = document.getElementById("probe-run-btn");

    if (key) {
      statusEl.textContent = "Key configured: " + maskKey(key) + " (browser only)";
      statusEl.className = "probe-key-status configured";
      input.value = "";
      input.placeholder = "(key saved, enter new to replace)";
      clearBtn.hidden = false;
      runBtn.disabled = false;
    } else {
      statusEl.textContent = "No key configured";
      statusEl.className = "probe-key-status";
      clearBtn.hidden = true;
      runBtn.disabled = true;
      input.placeholder = "pplx-...";
    }
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    var key;
    var child;

    if (attrs) {
      for (key in attrs) {
        if (!Object.prototype.hasOwnProperty.call(attrs, key)) {
          continue;
        }
        if (key === "className") {
          node.className = attrs[key];
        } else if (key === "textContent") {
          node.textContent = attrs[key];
        } else if (key === "href") {
          node.setAttribute("href", attrs[key]);
        } else if (key === "target") {
          node.setAttribute("target", attrs[key]);
        } else if (key === "rel") {
          node.setAttribute("rel", attrs[key]);
        } else {
          node.setAttribute(key, attrs[key]);
        }
      }
    }

    if (children) {
      for (var i = 0; i < children.length; i++) {
        child = children[i];
        if (child == null) {
          continue;
        }
        if (typeof child === "string") {
          node.appendChild(document.createTextNode(child));
        } else {
          node.appendChild(child);
        }
      }
    }

    return node;
  }

  function safeHref(url) {
    if (!url) {
      return "#";
    }

    try {
      var parsed = new URL(url, window.location.origin);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") {
        return parsed.href;
      }
    } catch (e) {}

    return "#";
  }

  function renderQueryCard(q) {
    var icon = q.cited_target ? "✅" : "❌";
    var statusClass = "probe-query " + (q.cited_target ? "probe-cited" : "probe-not-cited");
    var children = [
      el("div", { className: "probe-query-header" }, [
        el("span", { className: "probe-query-icon", textContent: icon }),
        el("span", { className: "probe-query-text", textContent: q.query || "" })
      ])
    ];

    if (q.cited_target && q.cited_snippet) {
      children.push(el("div", {
        className: "probe-snippet",
        textContent: "\"" + q.cited_snippet + "\""
      }));
    }

    if (q.answer) {
      children.push(el("p", {
        className: "probe-answer",
        textContent: q.answer
      }));
    }

    var citations = q.citations || [];
    if (citations.length > 0) {
      var listItems = [];
      for (var i = 0; i < Math.min(citations.length, 3); i++) {
        var citation = citations[i] || {};
        var href = safeHref(citation.url || "");
        var label = citation.title || citation.url || "(no title)";
        var link = el("a", {
          href: href,
          target: "_blank",
          rel: "noopener noreferrer",
          textContent: label
        });
        listItems.push(el("li", null, [link]));
      }

      children.push(el("details", { className: "probe-citations" }, [
        el("summary", { textContent: "Top citations" }),
        el("ul", null, listItems)
      ]));
    }

    return el("div", { className: statusClass }, children);
  }

  function renderProbeResults(data) {
    var resultsEl = document.getElementById("probe-results");
    var rateEl = document.getElementById("probe-citation-rate");
    var queriesEl = document.getElementById("probe-queries");
    var queries = data.queries || [];

    rateEl.textContent = data.cited_count + "/" + data.total_queries;

    while (queriesEl.firstChild) {
      queriesEl.removeChild(queriesEl.firstChild);
    }

    for (var i = 0; i < queries.length; i++) {
      queriesEl.appendChild(renderQueryCard(queries[i]));
    }

    resultsEl.hidden = false;
  }

  function showError(msg) {
    var errorEl = document.getElementById("probe-error");
    errorEl.textContent = "⚠️ " + msg;
    errorEl.hidden = false;
  }

  function hideError() {
    var errorEl = document.getElementById("probe-error");
    errorEl.hidden = true;
  }

  async function runProbe() {
    var key = getKey();
    if (!key) {
      return;
    }

    var section = document.getElementById("live-probe-section");
    var resultId = section ? section.dataset.resultId : "";
    if (!resultId) {
      showError("No result ID available");
      return;
    }

    var runBtn = document.getElementById("probe-run-btn");
    var loading = document.getElementById("probe-loading");
    var results = document.getElementById("probe-results");

    runBtn.disabled = true;
    loading.hidden = false;
    results.hidden = true;
    hideError();

    try {
      var response = await fetch("/api/v1/probe", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Perplexity-Key": key
        },
        body: JSON.stringify({ result_id: resultId })
      });

      var data = await response.json();
      if (!response.ok) {
        var msg = "Probe failed";
        if (data && data.detail && data.detail.error && data.detail.error.message) {
          msg = data.detail.error.message;
        }
        throw new Error(msg);
      }

      renderProbeResults(data);
    } catch (e) {
      showError((e && e.message) || "Unknown error");
    } finally {
      loading.hidden = true;
      runBtn.disabled = false;
    }
  }

  function init() {
    var section = document.getElementById("live-probe-section");
    if (!section) {
      return;
    }

    updateKeyStatus();

    document.getElementById("probe-save-key").addEventListener("click", function() {
      var input = document.getElementById("pplx-key-input");
      var newKey = input.value.trim();
      if (!newKey) {
        return;
      }
      if (!newKey.startsWith("pplx-")) {
        showError("Perplexity key must start with pplx-");
        return;
      }
      hideError();
      setKey(newKey);
      updateKeyStatus();
    });

    document.getElementById("probe-clear-key").addEventListener("click", function() {
      setKey("");
      updateKeyStatus();
      hideError();
    });

    document.getElementById("probe-run-btn").addEventListener("click", runProbe);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
