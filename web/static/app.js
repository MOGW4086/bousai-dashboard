/**
 * 防災ダッシュボード クライアントサイドJS
 * 手動更新ボタンの制御
 */
document.addEventListener('DOMContentLoaded', function () {
  const refreshBtn = document.getElementById('refresh-btn');
  const refreshMsg = document.getElementById('refresh-msg');

  if (!refreshBtn) return;

  refreshBtn.addEventListener('click', function () {
    refreshBtn.disabled = true;
    refreshBtn.textContent = '更新中...';
    if (refreshMsg) {
      refreshMsg.style.display = 'block';
    }

    fetch((typeof BASE_URL !== 'undefined' ? BASE_URL : '') + '/api/refresh', { method: 'POST' })
      .then(function (resp) {
        return resp.json();
      })
      .then(function (data) {
        if (data.ok) {
          // 収集完了を待ってからリロード（約5秒後）
          setTimeout(function () {
            location.reload();
          }, 5000);
        } else {
          alert('更新に失敗しました: ' + (data.message || '不明なエラー'));
          refreshBtn.disabled = false;
          refreshBtn.textContent = '手動更新';
          if (refreshMsg) refreshMsg.style.display = 'none';
        }
      })
      .catch(function (err) {
        alert('通信エラー: ' + err);
        refreshBtn.disabled = false;
        refreshBtn.textContent = '手動更新';
        if (refreshMsg) refreshMsg.style.display = 'none';
      });
  });
});
