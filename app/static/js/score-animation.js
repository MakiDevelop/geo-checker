/**
 * GEO Checker Score Animation
 * Handles score counter animation and progress bar transitions
 */

(function() {
  'use strict';

  // Easing function: easeOutQuart for smooth deceleration
  function easeOutQuart(t) {
    return 1 - Math.pow(1 - t, 4);
  }

  /**
   * Animate a number from 0 to target value
   * @param {HTMLElement} element - Element to update
   * @param {number} target - Target number
   * @param {number} duration - Animation duration in ms
   */
  function animateCounter(element, target, duration) {
    if (!element || typeof target !== 'number') return;

    const startTime = performance.now();
    const startValue = 0;

    function tick(currentTime) {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = easeOutQuart(progress);
      const currentValue = Math.round(startValue + (target - startValue) * eased);

      element.textContent = currentValue;

      if (progress < 1) {
        requestAnimationFrame(tick);
      }
    }

    requestAnimationFrame(tick);
  }

  /**
   * Trigger CSS transition on progress bars
   * @param {HTMLElement} element - Progress bar fill element
   * @param {number} percentage - Target width percentage
   * @param {number} delay - Delay before animation starts
   */
  function animateProgressBar(element, percentage, delay) {
    if (!element) return;

    // Set initial state
    element.style.width = '0%';

    // Trigger transition after delay
    setTimeout(function() {
      element.classList.add('animate');
      element.style.width = percentage + '%';
    }, delay);
  }

  /**
   * Initialize all animations on page load
   */
  function initAnimations() {
    // Score circle animation
    var scoreCircle = document.querySelector('.score-circle');
    var scoreValue = document.querySelector('.score-value');

    if (scoreCircle && scoreValue) {
      var targetScore = parseInt(scoreValue.dataset.target || scoreValue.textContent, 10);

      // Add reveal animation class
      scoreCircle.classList.add('animate');

      // Animate the number
      if (!isNaN(targetScore)) {
        scoreValue.textContent = '0';
        animateCounter(scoreValue, targetScore, 1500);
      }
    }

    // Grade badge animation
    var gradeBadge = document.querySelector('.grade-badge');
    if (gradeBadge) {
      gradeBadge.classList.add('animate');
    }

    // Breakdown progress bars
    var breakdownFills = document.querySelectorAll('.breakdown-fill');
    breakdownFills.forEach(function(fill, index) {
      var percentage = parseFloat(fill.dataset.percentage || fill.style.width);
      if (!isNaN(percentage)) {
        animateProgressBar(fill, percentage, 300 + (index * 150));
      }
    });

    // Extended metrics items (stagger animation)
    var extendedItems = document.querySelectorAll('.extended-item');
    extendedItems.forEach(function(item, index) {
      setTimeout(function() {
        item.classList.add('animate');
      }, 600 + (index * 100));
    });

    // Issue groups (stagger animation)
    var issueGroups = document.querySelectorAll('.issue-group');
    issueGroups.forEach(function(group, index) {
      setTimeout(function() {
        group.classList.add('animate');
      }, 800 + (index * 150));
    });
  }

  // Run on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAnimations);
  } else {
    initAnimations();
  }
})();
