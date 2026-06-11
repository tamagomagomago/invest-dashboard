# Investment Dashboard

監視銘柄を `investment/watchlist.csv` で管理し、日足チャート、移動平均、RSI、出来高倍率、52週高値判定、トレンド判定、反転初動、リスク減点を `investment/dashboard.html` と `investment/report.md` に出力します。

スコアは売買推奨ではなく、監視優先度を決めるためのものです。株価データは Yahoo Finance 由来のデータ取得に依存するため、欠損や遅延があり得ます。

`investment/scripts/update_dashboard.py` は、Yahoo Finance から株価データを取得し、指標を計算し、チャート画像と HTML ダッシュボードを更新するためのスクリプトです。スコア計算は `investment/scripts/scoring.py` に分離しています。普段見るのは `investment/dashboard.html`、銘柄を増やすときは `investment/watchlist.csv`、ロジックを変えるときは `scoring.py` を編集します。

## セットアップ

仮想環境 `.venv` は移動済みです。作り直す場合だけ次を実行してください。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 監視銘柄の編集

`investment/watchlist.csv` を編集します。日本株はスクリプト側で自動的に `.T` を付与します。`list` 列を使うと、ダッシュボード上でリストごとに切り替えて確認できます。

```csv
code,name,memo,list
4011,ヘッドウォータース,,新高値ブレイク投資
3993,PKSHA,,監視銘柄
7721,東京計器,,中小テーマ株
```

## ダッシュボード更新

```bash
cd /Users/hiroto_nakamura/Documents/Codex/invest_dashboard
.venv/bin/python investment/scripts/update_dashboard.py
open investment/dashboard.html
```

上部固定のリストボタンで `全部`、`新高値ブレイク投資`、`監視銘柄`、`中小テーマ株` を切り替えられます。
`1M`、`3M`、`6M` タブで、全銘柄のチャート期間をまとめて切り替えられます。
`1`、`2`、`4` の列数ボタンでチャートの横並び数を切り替えられます。各銘柄の細かい指標と根拠は `詳細スコア・根拠` を開くと見られます。
`総合`、`反転`、`新高値`、`出来高`、`リスク` ボタンで銘柄カードを並び替えられます。

40銘柄程度を1日1回更新する運用は現実的です。ただし Yahoo Finance 由来の非保証データに依存するため、短時間に何度も再実行する使い方は避けてください。

## GitHub Pagesで自動更新

`.github/workflows/update-dashboard.yml` で GitHub Actions + GitHub Pages の自動更新を設定しています。

- 平日 17:00 JST に自動更新
- GitHub Actions の `workflow_dispatch` から手動更新も可能
- 公開対象は `investment/`
- `investment/index.html` と `investment/dashboard.html` を生成

GitHub側では、リポジトリの `Settings > Pages` で `Build and deployment` を `GitHub Actions` にしてください。

日経225は `watchlist.csv` の `list` に `日経225` として登録しています。既存の監視銘柄と重なる銘柄は `監視銘柄|日経225` のように複数リスト所属にして、二重取得を避けています。

## スマホで見る・実行する

スマホ単体で Python を実行するより、Macで更新してスマホからHTMLを見る運用が安定です。

同じWi-Fi内のスマホから見る場合は、Mac側で次を実行します。

```bash
cd /Users/hiroto_nakamura/Documents/Codex/invest_dashboard/investment
../.venv/bin/python -m http.server 8765
```

その後、スマホのブラウザで `http://MacのIPアドレス:8765/dashboard.html` を開きます。

スマホから更新まで行いたい場合は、iPhoneのショートカットアプリからMacへSSHして `.venv/bin/python investment/scripts/update_dashboard.py` を実行する構成にします。

出力先:

- `investment/dashboard.html`
- `investment/report.md`
- `investment/charts/YYYY-MM-DD/`
- `investment/charts/latest/`
- `investment/data/{code}.csv`
- `investment/data/latest_scores.json`
- `investment/reports/report.md`
- `investment/reports/YYYY-MM-DD/report.md`

## スコア

100点満点で、以下の合計から計算します。

- トレンド: 20点
- 新高値・ブレイク: 20点
- 出来高: 15点
- RSI: 15点
- 反転初動: 25点
- リスク減点: 最大-25点
