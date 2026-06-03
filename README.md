# 防災ダッシュボード

日本の災害・防災情報を一元表示するWebダッシュボード。

## スタック
- Python + Flask + SQLite + cron
- ポート: 5001（5000はhealth-dashboardが使用中）

## セットアップ

```bash
cd /root/bousai-dashboard

# 仮想環境作成 & パッケージインストール
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 環境変数設定
cp .env.example .env
# .env を編集してSECRET_KEYを変更する

# DB初期化
.venv/bin/python db/init_db.py

# データ収集（初回）
.venv/bin/python scheduler/collect_all.py

# Webサーバー起動
.venv/bin/python web/app.py
```

## データソース

| ソース | URL | 備考 |
|---|---|---|
| 地震情報 | P2P地震情報v2 API | code=551のみ |
| 警報・注意報 | 気象庁警報JSON | 都道府県単位 |
| 台風情報 | 気象庁情報一覧JSON | 発生中のみ |
| 熱中症アラート | 気象庁 VPFT50 XML | 名前空間対応 |
| 噴火警報 | 気象庁情報一覧JSON | スケルトン実装 |
| 河川洪水予報 | (後続フェーズ) | スケルトン実装 |
| 環境情報 | 気象庁情報一覧JSON | スケルトン実装 |
| 大気汚染 | そらまめ君 (Phase2) | APIキー必要 |

## cronセットアップ

```bash
chmod +x cron/setup_cron.sh cron/run_collect.sh
./cron/setup_cron.sh
```

毎時0分にデータ収集が実行される。
