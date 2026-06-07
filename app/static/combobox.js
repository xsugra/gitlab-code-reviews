// Searchable model combobox: type a custom value, or pick from a panel of
// installed models. Generic over any [data-combobox] on the page; no-op when
// there are none. Used by the Settings page and the webhook form.
document.querySelectorAll('[data-combobox]').forEach(function (box) {
    const input = box.querySelector('[data-combobox-input]');
    const toggle = box.querySelector('[data-combobox-toggle]');
    const panel = box.querySelector('[data-combobox-panel]');
    const empty = box.querySelector('[data-combobox-empty]');
    const status = box.querySelector('[data-combobox-status]');
    const options = Array.from(box.querySelectorAll('.combobox-option'));
    const values = options.map(o => o.dataset.value);
    let activeIndex = -1;

    const visibleOptions = () => options.filter(o => o.style.display !== 'none');
    const isOpen = () => box.hasAttribute('data-open');

    function open() {
        box.setAttribute('data-open', '');
        panel.hidden = false;
        input.setAttribute('aria-expanded', 'true');
        filter();
    }

    function close() {
        box.removeAttribute('data-open');
        panel.hidden = true;
        input.setAttribute('aria-expanded', 'false');
        activeIndex = -1;
        options.forEach(o => o.removeAttribute('data-active'));
    }

    function syncSelection() {
        const v = input.value.trim();
        options.forEach(o => o.setAttribute('aria-selected', o.dataset.value === v ? 'true' : 'false'));
        if (!status) return;
        if (!v) {
            status.textContent = '';
            status.removeAttribute('data-state');
        } else if (values.includes(v)) {
            status.textContent = '✓ installed';
            status.dataset.state = 'installed';
        } else {
            status.textContent = '✎ custom model';
            status.dataset.state = 'custom';
        }
    }

    function filter() {
        const q = input.value.trim().toLowerCase();
        let shown = 0;
        options.forEach(o => {
            const match = o.dataset.value.toLowerCase().includes(q);
            o.style.display = match ? '' : 'none';
            if (match) shown++;
        });
        if (empty) empty.hidden = shown > 0 && options.length > 0;
    }

    function setActive(delta) {
        const vis = visibleOptions();
        if (!vis.length) return;
        options.forEach(o => o.removeAttribute('data-active'));
        activeIndex = (activeIndex + delta + vis.length) % vis.length;
        const el = vis[activeIndex];
        el.setAttribute('data-active', '');
        el.scrollIntoView({block: 'nearest'});
    }

    function choose(value) {
        input.value = value;
        syncSelection();
        close();
        input.focus();
    }

    input.addEventListener('focus', open);
    input.addEventListener('input', function () {
        if (!isOpen()) open();
        filter();
        syncSelection();
        activeIndex = -1;
        options.forEach(o => o.removeAttribute('data-active'));
    });

    toggle.addEventListener('click', function () {
        if (isOpen()) {
            close();
        } else {
            input.focus();
            open();
        }
    });

    box.querySelector('[data-combobox-list]').addEventListener('click', function (e) {
        const opt = e.target.closest('.combobox-option');
        if (opt) choose(opt.dataset.value);
    });

    input.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (!isOpen()) open();
            setActive(1);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (!isOpen()) open();
            setActive(-1);
        } else if (e.key === 'Enter') {
            const vis = visibleOptions();
            if (isOpen() && activeIndex >= 0 && vis[activeIndex]) {
                e.preventDefault();
                choose(vis[activeIndex].dataset.value);
            }
        } else if (e.key === 'Escape') {
            if (isOpen()) {
                e.preventDefault();
                close();
            }
        }
    });

    document.addEventListener('click', function (e) {
        if (!box.contains(e.target)) close();
    });

    syncSelection();
});
