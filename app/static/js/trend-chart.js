/**
 * Trend chart and sparkline renderer for GEO Checker.
 */

(function() {
  'use strict';

  function parsePoints(element) {
    try {
      return JSON.parse(element.dataset.points || '[]');
    } catch (_error) {
      return [];
    }
  }

  function normalizePoints(rawPoints) {
    return rawPoints
      .map(function(point) {
        var scoreValue = point.total_score;
        if (scoreValue === undefined || scoreValue === null) {
          scoreValue = point.score;
        }
        if (scoreValue === undefined || scoreValue === null) {
          scoreValue = 0;
        }
        var score = Number(scoreValue);
        if (!Number.isFinite(score)) {
          return null;
        }

        return {
          score: score,
          grade: point.grade || '',
          scannedAt: point.scanned_at || point.created_at || '',
          label: (point.scanned_at || point.created_at || '').slice(0, 10),
        };
      })
      .filter(Boolean);
  }

  function sortPointsAscending(points) {
    return points.slice().sort(function(a, b) {
      return new Date(a.scannedAt || 0).getTime() - new Date(b.scannedAt || 0).getTime();
    });
  }

  function getChartGeometry(points, width, height, padding) {
    var scores = points.map(function(point) { return point.score; });
    var minScore = Math.min.apply(null, scores);
    var maxScore = Math.max.apply(null, scores);

    if (minScore === maxScore) {
      minScore = Math.max(0, minScore - 5);
      maxScore = Math.min(100, maxScore + 5);
    }

    var innerWidth = Math.max(width - (padding.left + padding.right), 1);
    var innerHeight = Math.max(height - (padding.top + padding.bottom), 1);

    return points.map(function(point, index) {
      var x = padding.left + (points.length === 1 ? innerWidth / 2 : (innerWidth * index) / (points.length - 1));
      var yRatio = (point.score - minScore) / Math.max(maxScore - minScore, 1);
      var y = height - padding.bottom - (innerHeight * yRatio);
      return {
        x: Number(x.toFixed(2)),
        y: Number(y.toFixed(2)),
        score: point.score,
        label: point.label,
        scannedAt: point.scannedAt,
      };
    });
  }

  function buildPath(points) {
    return points.map(function(point, index) {
      return (index === 0 ? 'M' : 'L') + point.x + ' ' + point.y;
    }).join(' ');
  }

  function renderTrendChart(container) {
    var rawPoints = normalizePoints(parsePoints(container));
    var emptyLabel = container.dataset.emptyLabel || 'Need more scans for trend';

    if (rawPoints.length <= 1) {
      container.innerHTML = '<div class="trend-empty">' + emptyLabel + '</div>';
      return;
    }

    var chartPoints = getChartGeometry(sortPointsAscending(rawPoints), 720, 200, {
      top: 20,
      right: 24,
      bottom: 28,
      left: 24,
    });
    var path = buildPath(chartPoints);

    var guides = [25, 50, 75].map(function(percent) {
      var y = (200 - 28) - ((200 - (20 + 28)) * (percent / 100)) + 20;
      return '<line x1="24" y1="' + y.toFixed(2) + '" x2="696" y2="' + y.toFixed(2) + '" class="trend-guide" />';
    }).join('');

    var pointsMarkup = chartPoints.map(function(point) {
      return (
        '<g class="trend-point">' +
          '<title>' + point.label + ': ' + point.score + '</title>' +
          '<circle cx="' + point.x + '" cy="' + point.y + '" r="5" class="trend-dot"></circle>' +
          '<text x="' + point.x + '" y="' + (point.y - 12) + '" text-anchor="middle" class="trend-point-label">' + point.score + '</text>' +
        '</g>'
      );
    }).join('');

    container.innerHTML = (
      '<svg class="trend-svg" viewBox="0 0 720 200" preserveAspectRatio="none" aria-label="Score trend">' +
        guides +
        '<path d="' + path + '" class="trend-line"></path>' +
        pointsMarkup +
      '</svg>'
    );
  }

  function renderSparkline(container) {
    var rawPoints = normalizePoints(parsePoints(container));

    if (!rawPoints.length) {
      container.innerHTML = '<span class="history-sparkline-empty">—</span>';
      return;
    }

    var chartPoints = getChartGeometry(sortPointsAscending(rawPoints), 100, 30, {
      top: 4,
      right: 3,
      bottom: 4,
      left: 3,
    });

    var path = buildPath(chartPoints);
    var pointMarkup = chartPoints.map(function(point) {
      return (
        '<g>' +
          '<title>' + point.label + ': ' + point.score + '</title>' +
          '<circle cx="' + point.x + '" cy="' + point.y + '" r="2.4" class="history-sparkline-dot"></circle>' +
        '</g>'
      );
    }).join('');

    container.innerHTML = (
      '<svg class="history-sparkline-svg" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">' +
        '<path d="' + path + '" class="history-sparkline-line"></path>' +
        pointMarkup +
      '</svg>'
    );
  }

  function copyText(text, button) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }

    return new Promise(function(resolve, reject) {
      var textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'absolute';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.select();

      try {
        document.execCommand('copy');
        document.body.removeChild(textarea);
        resolve();
      } catch (error) {
        document.body.removeChild(textarea);
        reject(error);
      }
    }).then(function() {
      if (button) {
        button.blur();
      }
    });
  }

  window.copyCode = function(button) {
    var codeWrapper = button && button.nextElementSibling;
    var text = codeWrapper ? codeWrapper.textContent.trim() : '';
    var originalLabel = button ? button.textContent : 'Copy';

    if (!text) {
      return;
    }

    copyText(text, button).then(function() {
      if (!button) {
        return;
      }
      button.textContent = 'Copied!';
      window.setTimeout(function() {
        button.textContent = originalLabel;
      }, 2000);
    });
  };

  function initTrendVisuals() {
    var chart = document.getElementById('trend-chart');
    if (chart) {
      renderTrendChart(chart);
    }

    document.querySelectorAll('[data-sparkline="true"]').forEach(renderSparkline);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTrendVisuals);
  } else {
    initTrendVisuals();
  }
})();
