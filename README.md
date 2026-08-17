# Japan Drop Radar

公開ダッシュボード: https://aimaskaks.github.io/japan-drop-radar/

GitHubリポジトリ: https://github.com/aimaskaks/japan-drop-radar

日本限定、抽選、先着、予約販売の公開情報を集め、海外二次流通で価格が上がりやすい需給条件の順に並べるローカルツールです。媒体の直RSS／ニュースサイトマップから元記事本文を取得し、ブランド公式JSON/API・公式ストアを一次情報として扱います。Google Newsは通常運用では使いません。

現在の情報源はInside Games、Hypebeast Japan、アニメ！アニメ！、HOBBY Watch、GAME Watch、Fashion Press、ファミ通.com、電撃オンライン、ポケモンカード公式、プレミアムバンダイ、魂ウェブ公式、G-SHOCK公式です。

## 優先カテゴリ

初期設定は次の順を重視しています。

1. トレーディングカード（Pokémon、遊戯王、ONE PIECEなど）
2. フィギュア・玩具（アニメIP、ソフビ、ガンプラ、限定コレクティブル）
3. 限定スニーカー（日本別注、店舗限定、コラボ）
4. ゲーム機・周辺機器（限定版、amiiboなど）
5. 日本ブランド腕時計（G-SHOCK、Seiko等の限定・コラボ）
6. ファッション（強いIP・ブランドとの限定コラボのみ）

## 値上がり期待度

ランキングの `score` は次の公開情報を分解して0〜100点へ正規化します。

- 供給制約（最大40）: 抽選、数量明示、購入数制限、完売、販路限定
- 需要証拠（最大30）: カテゴリ実績、強IP、争奪戦・高騰、コラボ、周年
- 海外適性（最大20）: 日本限定、国内入手機会、国際系媒体掲載、輸送適性
- 価格帯（-12〜+10）: 3,000〜30,000円を主戦場とし、10万円超を減点
- 証拠充足（最大5）: 一次情報、本文/API、価格、日付
- リスク（最大-40）: 受注生産、再販・追加生産、世界同時発売、購入不可、中古情報
- 独立媒体の裏取り（最大+24）: 同じ商品の報道元が増えた場合だけ商品単位で加点

締切の近さは値上がり要因ではないため、本体スコアから分離して `urgency_score` に保存します。魂ウェブは原則 `made_to_order` として大幅減点しますが、商品名が抽選販売なら数量固定の例外として扱います。

この期待度は利益率や値上がり確率そのものではありません。実売相場の答え合わせが蓄積するまでは、供給・需要・海外適性の証拠を比較するランキング指標です。45点以上を相場確認候補、60点以上を優先確認候補の初期目安とします。

## 使い方（Windows）

PowerShellで次を実行します。

```powershell
.\run.ps1
```

初回だけ仮想環境と依存パッケージを作り、その後に収集します。結果は `output/dashboard.html` と `output/items.csv`、履歴は `data/radar.db` に保存されます。

手動セットアップする場合:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m japan_drop_radar collect
```

保存済みデータだけで50点以上のレポートを再生成:

```powershell
.\.venv\Scripts\python.exe -m japan_drop_radar report --min-score 50
```

現在の抽出精度を数値で確認:

```powershell
.\.venv\Scripts\python.exe -m japan_drop_radar audit
```

本文を再取得せず、解析規則とスコアだけを適用し直す場合:

```powershell
.\.venv\Scripts\python.exe -m japan_drop_radar rescore
```

## 30日後・90日後の答え合わせ

発売後にeBay等の成約済み価格の中央値を確認し、商品URLを指定して記録します。出品価格ではなく複数の成約値の中央値を使ってください。

```powershell
.\.venv\Scripts\python.exe -m japan_drop_radar outcome `
  --url "https://example.jp/item" `
  --marketplace ebay `
  --observed-price-jpy 42000 `
  --horizon-days 30 `
  --sample-count 8 `
  --source-url "https://www.ebay.com/..."
```

期待度と実プレミア率の相関を確認:

```powershell
.\.venv\Scripts\python.exe -m japan_drop_radar evaluate --horizon-days 30
.\.venv\Scripts\python.exe -m japan_drop_radar evaluate --horizon-days 90
```

相関は3件以上で算出されます。十分な件数が溜まったら、カテゴリ別・価格帯別に重みを再較正します。

## 通知

`.env.example` を `.env` にコピーし、DiscordまたはSlackのWebhook URLを設定します。既定では45点以上の未通知候補を最大10件送ります。

```powershell
Copy-Item .env.example .env
```

## 定期実行

Windowsタスクスケジューラで、1～3時間ごとに次を登録します。

- プログラム: `powershell.exe`
- 引数: `-NoProfile -ExecutionPolicy Bypass -File "（このフォルダの絶対パス）\run.ps1"`
- 開始: このプロジェクトフォルダ

抽選開始直後の更新を拾いたい場合でも、公式サイトへの負荷を考え1時間未満にはしないことを推奨します。

## GitHub Pagesで毎日公開

`.github/workflows/daily-pages.yml` は毎日07:15・15:15・23:15（Asia/Tokyo）、mainへのpush、手動実行で次を行います。

1. 前回のSQLite履歴をActionsキャッシュから復元
2. 全テストを実行
3. 公開情報を収集して値上がり期待度を再計算
4. HTML、CSV、監査JSONをGitHub Pagesへデプロイ

公開リポジトリのscheduled workflowが60日間の無活動で停止しないよう、毎月1日にheartbeatコミットも作成します。

リポジトリのSettings → Pages → Build and deploymentは `GitHub Actions` を使用します。Webhook URLなどの秘密情報はリポジトリへコミットしません。

## 情報源を増やす

`config/sources.yaml` を編集します。通常RSSは `rss`、Google News Sitemap等は `sitemap`、公式一覧ページは `html_links` を使います。本文取得を必須にする媒体では `deep_fetch: true` と `require_detail: true` を指定します。

```yaml
- name: ブランド公式ニュース
  type: html_links
  enabled: true
  url: https://example.jp/news/
  include_url_regex: '/news/[0-9]+/'
  include_text_regex: '限定|抽選|予約|発売'
  category_hint: figures_toys
  authoritative: true
  deep_fetch: true
```

`category_hint` は `trading_cards`, `figures_toys`, `sneakers`, `watches`, `games`, `fashion`, `other` のいずれかです。

## 運用上の注意

- robots.txtを確認し、サイトごとに最低1.5秒の間隔を空けます。
- ログイン、CAPTCHA回避、購入・応募の自動化は行いません。
- Google Newsフォールバックは難読化URLになるため初期設定で無効です。
- 記事は原則21日以内、ニュース量の多い媒体は14日以内に制限されます。期限切れ商品は履歴に残りますが通常の一覧には出ません。
- 同じ商品を扱う記事は商品キーでまとめ、ダッシュボードの「関連記事」から各媒体を確認できます。
- 各候補の「eBay成約相場」「StockX検索」から海外価格を照合できます。出品価格ではなく成約済み価格を重視してください。
- ダッシュボード上部の利益シミュレーターでは、当日の為替、国際送料、販売手数料を含めた概算利益とROIを確認できます。関税・梱包費・返品損失は必要に応じて送料欄へ上乗せしてください。
- スコアが高くても利益は保証されません。海外相場、販売手数料、国際送料、関税、返品率、真贋リスクを別途確認してください。
- 規制品、偽造品、チケット、購入規約で転売禁止の品は対象にしないでください。
