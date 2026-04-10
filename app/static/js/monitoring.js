/**
 * Monitoring configuration — schedule + webhook settings.
 */
(function() {
  'use strict';

  function init() {
    var section = document.getElementById('monitoring-section');
    if (!section) return;

    var url = section.dataset.url;
    if (!url) return;

    loadConfig(url);

    var saveBtn = document.getElementById('monitoring-save-btn');
    if (saveBtn) {
      saveBtn.addEventListener('click', function() {
        saveConfig(url);
      });
    }
  }

  async function loadConfig(url) {
    try {
      var encoded = encodeURIComponent(url);
      var response = await fetch('/api/v1/monitoring/' + encoded);
      if (!response.ok) return;

      var data = await response.json();
      var config = data.config || {};
      document.getElementById('rescan-cron-select').value = config.rescan_cron || '';
      document.getElementById('webhook-url-input').value = config.webhook_url || '';
      document.getElementById('alert-threshold-input').value = config.alert_threshold || 0;
    } catch (error) {
      return;
    }
  }

  async function saveConfig(url) {
    var cron = document.getElementById('rescan-cron-select').value;
    var webhookUrl = document.getElementById('webhook-url-input').value.trim();
    var threshold = parseInt(
      document.getElementById('alert-threshold-input').value || '0',
      10
    );
    var statusEl = document.getElementById('monitoring-status');
    var saveBtn = document.getElementById('monitoring-save-btn');

    if (webhookUrl && !/^https?:\/\//.test(webhookUrl)) {
      statusEl.textContent = '⚠️ Webhook URL must start with http:// or https://';
      statusEl.className = 'monitoring-status error';
      return;
    }

    saveBtn.disabled = true;
    statusEl.textContent = 'Saving...';
    statusEl.className = 'monitoring-status';

    try {
      var response = await fetch('/api/v1/monitoring', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url,
          rescan_cron: cron,
          webhook_url: webhookUrl,
          alert_threshold: threshold
        })
      });

      if (!response.ok) {
        var data = await response.json();
        var msg = (
          data.detail &&
          data.detail.error &&
          data.detail.error.message
        ) || 'Save failed';
        throw new Error(msg);
      }

      statusEl.textContent = '✅ Saved';
      statusEl.className = 'monitoring-status success';
    } catch (error) {
      statusEl.textContent = '⚠️ ' + ((error && error.message) || 'Save failed');
      statusEl.className = 'monitoring-status error';
    } finally {
      saveBtn.disabled = false;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
