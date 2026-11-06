// Atualiza o status dos documentos enquanto algum estiver na fila ou processando
(() => {
  const table = document.getElementById('documents');
  if (!table) return;

  const pending = () => table.querySelector('.status-badge[data-status="pending"], .status-badge[data-status="processing"]');

  async function poll() {
    if (!pending()) return;
    try {
      const response = await fetch(table.dataset.statusUrl);
      const data = await response.json();
      for (const doc of data.documents) {
        const row = table.querySelector(`tr[data-id="${doc.id}"]`);
        if (!row) continue;
        const badge = row.querySelector('.status-badge');
        badge.dataset.status = doc.status;
        badge.textContent = doc.status_label;
        row.querySelector('.document-error').textContent = doc.error;
        row.querySelector('.chunk-count').textContent = doc.chunk_count;
      }
    } catch {}
    setTimeout(poll, 2000);
  }

  setTimeout(poll, 2000);
})();
