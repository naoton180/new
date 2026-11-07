# トレタ予約 空き枠ウォッチャー(ビストロシンサンテ用)

指定した日付・人数で予約枠が空いたら、スマホにプッシュ通知を送ります。

## 仕組み
- トレタの予約画面が裏で使っている公開API(ログイン不要)を1分おきに確認
  - `GET https://yoyaku.toreta.in/web/v1/web_reservations/{店舗キー}/days.json?year=&month=&seats=`
  - 日ごとに `null`=受付開始前 / `[]`=満席・休み / `[...]`=空き時間帯 が返る
- 新しく空いた枠だけを通知(同じ枠で何度も鳴らない。一度埋まって再び空けばまた通知)
- 通知は ntfy(無料・アカウント不要)。Discord Webhook も可
- **予約自体は自動で行いません**。通知をタップして自分で予約してください

## セットアップ(GitHub Actions で動かす:PCの電源オフでもOK)

1. **スマホに ntfy アプリを入れる**(iOS / Android)
   - 「+」→ トピック名に推測されにくい文字列を入力して購読(例: `shinsante-a8f3k2q9`)
2. **GitHub に新しいリポジトリを作る**し、このフォルダの中身を push
   - 1分間隔で回すと月約4万分使うため、**Public リポジトリ推奨**(無料・無制限)。Private だと無料枠2,000分/月をすぐ超えます
   - 通知先・日付は Secrets / Variables に入れるので、Public でも外部には見えません
3. リポジトリの **Settings → Secrets and variables → Actions** で設定
   - Secrets: `NTFY_TOPIC` = 手順1のトピック名
   - Variables:
     - `TARGET_DATES` = `2026-12-24`(複数ならカンマ区切り)
     - `SEATS` = `2`
     - `TIME_FROM` / `TIME_TO` = `18:00` / `20:00`(任意。入店時刻で絞り込み)
4. **Actions タブ → toreta-watch → Run workflow** で手動実行して動作確認
   - 空きがあればその場で通知が来ます。ログに現在の空き状況が出ます

監視をやめるときは Actions タブでワークフローを Disable、または日付が過ぎれば自動で何もしなくなります。

## PC で試す場合(Windows)
```
set TARGET_DATES=2026-12-24
set SEATS=2
set NTFY_TOPIC=shinsante-a8f3k2q9
python monitor.py
```
常時監視するならタスクスケジューラで「1分ごとに繰り返す」設定にして実行(PCは起動したままにする)。

## 注意
- 確認間隔は1分より短くしないでください(お店・トレタのサーバーに負荷をかけないため)
- GitHub の定期実行は混雑時に数分〜十数分遅れることがあります
- 予約画面の仕様変更で動かなくなる可能性があります
