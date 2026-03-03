const counters = document.querySelectorAll("[data-counter]");

const animateCounter = (element) => {
  const target = Number(element.dataset.counter || "0");
  const decimals = Number.isInteger(target) ? 0 : 1;
  const duration = 1400;
  const start = performance.now();

  const tick = (now) => {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = target * eased;
    element.textContent = value.toFixed(decimals);
    if (progress < 1) {
      requestAnimationFrame(tick);
    }
  };

  requestAnimationFrame(tick);
};

const observer = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) {
        return;
      }
      animateCounter(entry.target);
      observer.unobserve(entry.target);
    });
  },
  {
    threshold: 0.35
  }
);

counters.forEach((counter) => observer.observe(counter));
