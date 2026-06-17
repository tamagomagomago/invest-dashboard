# External Cron Setup

GitHub Actions の `schedule` は遅延・未発火が起きることがあるため、外部cronから `workflow_dispatch` を直接叩いてダッシュボードを更新する。

GitHub Actions側の `schedule` は保険として残す。本命は外部cron。

## 方式

外部cronから次のGitHub APIを `POST` する。

```text
POST https://api.github.com/repos/tamagomagomago/invest-dashboard/actions/workflows/update-dashboard.yml/dispatches
```

Body:

```json
{"ref":"main"}
```

このbodyでは、同じ日本日付ですでに成功済みの更新がある場合は `gate` ジョブでスキップされる。

Headers:

```text
Accept: application/vnd.github+json
Authorization: Bearer YOUR_GITHUB_TOKEN
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

成功時はHTTP `204 No Content` が返る。

## 必要なGitHub token

GitHubで Fine-grained personal access token を作る。

Repository access:

- `tamagomagomago/invest-dashboard` のみ

Repository permissions:

- `Actions`: Read and write
- `Metadata`: Read-only

有効期限は短めでもよい。切れたら外部cron側のヘッダーを更新する。

## cron-job.orgで設定する場合

Job:

- Title: `invest-dashboard-update`
- URL: `https://api.github.com/repos/tamagomagomago/invest-dashboard/actions/workflows/update-dashboard.yml/dispatches`
- Schedule: 平日 17:05 JST
- Request method: `POST`
- Request body:

```json
{"ref":"main"}
```

Request headers:

```text
Accept: application/vnd.github+json
Authorization: Bearer YOUR_GITHUB_TOKEN
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

期待するHTTPステータス:

```text
204
```

## 手元での動作確認

GitHub tokenを環境変数に入れてから実行する。

```bash
export GITHUB_WORKFLOW_TOKEN="作成したtoken"
./scripts/trigger_dashboard_update.sh
```

成功するとGitHub Actionsに `workflow_dispatch` のrunが作成される。
すでに同じ日本日付で更新成功済みの場合は、`gate` ジョブだけ成功して本更新はスキップされる。

どうしても強制的に再更新したい場合だけ、次のように実行する。

```bash
FORCE=true ./scripts/trigger_dashboard_update.sh
```

## 運用メモ

- 外部cronは17:05 JSTに1回実行する。
- GitHub Actions内のgateジョブが、同じ日本日付で成功済みなら後続runをスキップする。
- GitHub Actionsのscheduleは17:05〜19:55 JSTの保険として残している。
- 更新完了後はLINE通知が来る。
