(() => {
  const root = document.getElementById('chat');
  if (!root) return;

  const list = document.getElementById('messages');
  const form = document.getElementById('composer');
  const input = form.querySelector('textarea');
  const sendButton = form.querySelector('button[type=submit]');
  const modelSelect = document.getElementById('model-select');
  const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value;
  let conversationId = root.dataset.conversationId || null;
  let busy = false;

  const MODEL_KEY = 'rag:model';
  if (modelSelect) {
    try {
      const saved = localStorage.getItem(MODEL_KEY);
      if (saved && [...modelSelect.options].some((option) => option.value === saved)) modelSelect.value = saved;
    } catch {}
    modelSelect.addEventListener('change', () => {
      try { localStorage.setItem(MODEL_KEY, modelSelect.value); } catch {}
    });
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function renderMarkdown(node, text) {
    if (window.marked && window.DOMPurify) node.innerHTML = DOMPurify.sanitize(marked.parse(text));
    else node.textContent = text;
  }

  function truncate(text, size) {
    const clean = text.replace(/\s+/g, ' ').trim();
    return clean.length > size ? `${clean.slice(0, size)}…` : clean;
  }

  function scrollToBottom() {
    list.scrollTop = list.scrollHeight;
  }

  function addMessage(message) {
    document.getElementById('empty-state')?.remove();
    const row = el('div', `msg msg-${message.role}`);
    const bubble = el('div', 'bubble');
    const content = el('div', 'content');
    bubble.append(content);
    row.append(bubble);
    list.append(row);

    const view = { row, bubble, content };
    if (message.role === 'user') content.textContent = message.content;
    else fillAssistant(view, message);
    scrollToBottom();
    return view;
  }

  function fillAssistant(view, message) {
    view.content.classList.add('markdown');
    renderMarkdown(view.content, message.content || '');
    view.bubble.querySelectorAll('.options, .meta, .sources').forEach((node) => node.remove());

    const options = message.clarification_options || [];
    if (options.length) {
      const box = el('div', 'options');
      const choose = (ids, label) => send(label, ids);
      for (const option of options) {
        const button = el('button', 'chip', option.name);
        button.type = 'button';
        button.addEventListener('click', () => choose([option.id], option.name));
        box.append(button);
      }
      if (options.length > 1) {
        const all = el('button', 'chip chip-ghost', 'Todos esses temas');
        all.type = 'button';
        all.addEventListener('click', () => choose(options.map((option) => option.id), 'Todos esses temas'));
        box.append(all);
      }
      view.bubble.append(box);
    }

    const meta = el('div', 'meta');
    for (const topic of message.topics || []) meta.append(el('span', 'badge', topic));
    if (message.model) meta.append(el('span', 'model', message.model));
    if (meta.childElementCount) view.bubble.append(meta);

    const sources = message.sources || [];
    if (sources.length) {
      const details = el('details', 'sources');
      details.append(el('summary', null, `Fontes (${sources.length})`));
      const ol = el('ol');
      for (const source of sources) {
        const item = el('li');
        item.value = source.n;
        const link = el('a', null, source.page ? `${source.title}, p. ${source.page}` : source.title);
        link.href = source.url;
        link.target = '_blank';
        link.rel = 'noopener';
        item.append(link, el('span', 'source-topic', ` · ${source.topic}`), el('p', 'snippet', truncate(source.content, 280)));
        ol.append(item);
      }
      details.append(ol);
      view.bubble.append(details);
    }
  }

  function onConversation(event) {
    if (conversationId === String(event.id)) return;
    conversationId = String(event.id);
    history.replaceState(null, '', event.url);
    document.getElementById('chat-title').textContent = event.title;
    document.title = event.title;

    const nav = document.getElementById('conversation-list');
    nav.querySelector('.empty')?.remove();
    nav.querySelectorAll('a.active').forEach((link) => link.classList.remove('active'));
    const link = el('a', 'active', event.title);
    link.href = event.url;
    const item = el('li');
    item.append(link);
    nav.prepend(item);
  }

  function setBusy(value) {
    busy = value;
    if (input) input.disabled = value;
    if (sendButton) sendButton.disabled = value;
  }

  async function send(text, topicIds = []) {
    if (busy || !text.trim()) return;
    setBusy(true);
    // Botões de escolha de tema só valem para a última resposta
    list.querySelectorAll('.options').forEach((node) => node.remove());

    addMessage({ role: 'user', content: text });
    const view = addMessage({ role: 'assistant', content: '' });
    const status = el('div', 'status', 'Enviando...');
    view.bubble.prepend(status);

    let raw = '';
    let frame = null;
    const flush = () => {
      frame = null;
      renderMarkdown(view.content, raw);
      scrollToBottom();
    };

    const handle = (event) => {
      if (event.type === 'conversation') onConversation(event);
      else if (event.type === 'status') status.textContent = event.text;
      else if (event.type === 'token') {
        status.remove();
        raw += event.text;
        frame ??= requestAnimationFrame(flush);
      } else if (event.type === 'done') {
        if (frame) cancelAnimationFrame(frame);
        status.remove();
        fillAssistant(view, event.message);
      } else if (event.type === 'error') throw new Error(event.message);
    };

    try {
      const response = await fetch(root.dataset.sendUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({
          message: text,
          model: modelSelect?.value,
          conversation_id: conversationId,
          topic_ids: topicIds,
        }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Erro ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index;
        while ((index = buffer.indexOf('\n')) >= 0) {
          const line = buffer.slice(0, index).trim();
          buffer = buffer.slice(index + 1);
          if (line) handle(JSON.parse(line));
        }
      }
    } catch (error) {
      if (frame) cancelAnimationFrame(frame);
      status.remove();
      view.bubble.classList.add('error');
      view.content.textContent = error.message || 'Não foi possível enviar a mensagem.';
    } finally {
      setBusy(false);
      input?.focus();
      scrollToBottom();
    }
  }

  const initial = JSON.parse(document.getElementById('initial-messages').textContent);
  initial.forEach(addMessage);
  // Ao reabrir a conversa, só a última resposta mantém os botões de tema
  list.querySelectorAll('.options').forEach((node) => {
    if (node.closest('.msg') !== list.lastElementChild) node.remove();
  });

  if (!input) return;

  const resize = () => {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
  };
  input.addEventListener('input', resize);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const text = input.value;
    if (!text.trim()) return;
    input.value = '';
    resize();
    send(text);
  });
  input.focus();
})();
