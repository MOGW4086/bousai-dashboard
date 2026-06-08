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
| 津波警報・注意報 | 気象庁 VTSE41 / VTWW53 XML | 遠地地震はVTSE41、近地地震はVTWW53 |
| 河川洪水予報 | (後続フェーズ) | スケルトン実装 |
| 環境情報 | 気象庁情報一覧JSON | スケルトン実装 |
| 大気汚染 | そらまめ君 (Phase2) | APIキー必要 |

## cronセットアップ

```bash
chmod +x cron/setup_cron.sh cron/run_collect.sh
./cron/setup_cron.sh
```

毎時0分にデータ収集が実行される。

## 津波電文について

気象庁の津波電文には近地地震と遠地地震で異なる電文種別コードが使用される。

| 電文種別 | 対象 | フィード |
|---|---|---|
| `VTWW53` | 近地地震の津波警報・注意報 | eqvol ATOMフィード |
| `VTSE41` | 遠地地震の津波警報・注意報・予報 | eqvol ATOMフィード |

遠地地震（例：フィリピン沖・チリ沖等の海外震源）の場合は `VTSE41` として配信される。
`fetchers/atom.py` の `HANDLERS` に両方を登録することで、どちらの震源の津波情報も受信・表示できる。
