export default function ({ parentElement, data, setStateValue }) {
  const root = parentElement.querySelector('.preference');
  const scale = root.querySelector('.scale');
  const stops = root.querySelector('.stops');
  const fill = root.querySelector('.fill');
  const clear = root.querySelector('.clear');
  const status = root.querySelector('.status');
  const feedback = root.querySelector('.feedback');
  const choices = data.choices;
  const middle = Math.floor(choices.length / 2);
  let selected = choices.findIndex(choice => choice.id === data.selected);
  let drag = null;

  root.querySelector('.left-name').textContent = data.left;
  root.querySelector('.right-name').textContent = data.right;
  for (const side of ['left', 'right']) {
    const description = root.querySelector(`.${side}-description`);
    description.textContent = data[`${side}_description`] || '';
    description.hidden = !description.textContent.trim();
  }
  scale.setAttribute('aria-label', `${data.left} compared with ${data.right}`);
  scale.style.setProperty('--count', choices.length);

  // Keep the DOM nodes on reruns, including focus and pointer targets.
  const signature = JSON.stringify(choices);
  if (stops.dataset.signature !== signature) {
    stops.replaceChildren();
    choices.forEach(choice => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'stop';
      button.setAttribute('role', 'radio');
      button.setAttribute('aria-label', choice.summary);
      const area = document.createElement('span');
      area.className = 'dot-area';
      area.setAttribute('aria-hidden', 'true');
      const dot = document.createElement('span');
      dot.className = 'dot';
      dot.textContent = '✓';
      area.append(dot);
      const label = document.createElement('span');
      label.className = 'stop-label desktop-label';
      label.textContent = choice.label;
      const mobileLabel = document.createElement('span');
      mobileLabel.className = 'stop-label mobile-label';
      mobileLabel.textContent = choice.summary;
      button.append(area, label, mobileLabel);
      stops.append(button);
    });
    stops.dataset.signature = signature;
  }
  const buttons = [...stops.querySelectorAll('.stop')];

  function paint(index) {
    buttons.forEach((button, i) => {
      button.setAttribute('aria-checked', String(i === index));
      button.tabIndex = i === (index < 0 ? middle : index) ? 0 : -1;
    });
    const position = index < 0 ? 50 : index / (choices.length - 1) * 100;
    fill.style.setProperty('--start', `${Math.min(position, 50)}%`);
    fill.style.setProperty('--length', `${Math.abs(position - 50)}%`);
    status.textContent = index < 0 ? 'No answer selected.' : choices[index].summary;
    feedback.classList.toggle('answered', index >= 0);
    root.querySelector('.status-icon').textContent = index < 0 ? '○' : '✓';
    clear.disabled = index < 0;
  }

  function commit(index, focus = true) {
    const changed = selected !== index;
    selected = index;
    paint(index);
    if (focus) buttons[index < 0 ? middle : index].focus({ preventScroll: true });
    if (changed) setStateValue('selected', index < 0 ? null : choices[index].id);
  }

  buttons.forEach((button, index) => {
    button.onclick = () => commit(index);
    button.onkeydown = event => {
      let next;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = Math.min(index + 1, choices.length - 1);
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = Math.max(index - 1, 0);
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = choices.length - 1;
      if (next !== undefined) {
        event.preventDefault();
        commit(next);
      }
    };
  });
  clear.onclick = () => commit(-1);

  function vertical() {
    return getComputedStyle(stops).gridTemplateColumns.split(' ').length === 1;
  }

  function nearest(event) {
    const rects = buttons.map(button => button.querySelector('.dot').getBoundingClientRect());
    const isVertical = vertical();
    const point = isVertical ? event.clientY : event.clientX;
    const centers = rects.map(rect => isVertical ? rect.top + rect.height / 2 : rect.left + rect.width / 2);
    return centers.reduce((best, center, i) => Math.abs(center - point) < Math.abs(centers[best] - point) ? i : best, 0);
  }

  scale.onpointerdown = event => {
    // On narrow touch screens retain natural page scrolling; stops remain tappable.
    if (event.button !== 0 || !event.isPrimary || (vertical() && event.pointerType === 'touch')) return;
    drag = { id: event.pointerId, startX: event.clientX, startY: event.clientY, moved: false };
    scale.setPointerCapture(event.pointerId);
  };
  scale.onpointermove = event => {
    if (!drag || drag.id !== event.pointerId) return;
    const dx = Math.abs(event.clientX - drag.startX);
    const dy = Math.abs(event.clientY - drag.startY);
    if (dx + dy > 5) drag.moved = true;
    if (drag.moved) paint(nearest(event));
  };
  scale.onpointerup = event => {
    if (!drag || drag.id !== event.pointerId) return;
    const index = nearest(event);
    drag = null;
    scale.releasePointerCapture(event.pointerId);
    commit(index);
  };
  scale.onpointercancel = scale.onlostpointercapture = () => {
    drag = null;
    paint(selected);
  };
  paint(selected);

  return () => {
    buttons.forEach(button => { button.onclick = null; button.onkeydown = null; });
    clear.onclick = null;
    scale.onpointerdown = scale.onpointermove = scale.onpointerup = null;
    scale.onpointercancel = scale.onlostpointercapture = null;
  };
}
