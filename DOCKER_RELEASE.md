# Docker Hubへの正式版・RC公開

[English](DOCKER_RELEASE.en.md) · 日本語

公開先は [sosboy/gmail-bridge](https://hub.docker.com/r/sosboy/gmail-bridge)。2026-09-30にv1.0.0の初回公開が完了しました。[公開ワークフロー](https://github.com/sosboy-san/gmail_bridge/actions/runs/36676882196)で両CPU向けのテスト、4タグのdigest一致、linux/amd64・linux/arm64のmanifestを確認しています。

## 管理者の初回設定

1. Docker Hubで `sosboy/gmail-bridge` リポジトリを作成し、公開用としてPublicを選びます。
2. Docker Hubで専用のアクセストークンを作成します。必要な権限はRead & Writeです。Delete権限は不要です。トークンをチャット、コード、ログへ貼らないでください。
3. GitHubのSettings → Environmentsで `dockerhub` を作成し、次のEnvironment variables / secretsを登録します。

| 種類 | 名前 | 値 |
| --- | --- | --- |
| Variable | DOCKERHUB_USERNAME | sosboy |
| Variable | DOCKERHUB_NAMESPACE | sosboy |
| Secret | DOCKERHUB_TOKEN | 専用アクセストークン |

## 公開手順とタグ

`.github/workflows/docker-publish.yml` は `v*` タグのpushでのみ自動公開します。mainへのpushでは公開しません。正式な `vMAJOR.MINOR.PATCH` または `vMAJOR.MINOR.PATCH-rc.N`（MAJORとNは1以上）のみを受け付けます。beta等の他のプレリリースは拒否します。アプリのコードは必ず指定タグのコミットから取得します。

| Gitタグ | 同じmulti-archイメージを指すDockerタグ |
| --- | --- |
| v1.0.0 | 1.0.0 / 1.0 / 1 / latest |
| v1.0.1 | 1.0.1 / 1.0 / 1 / latest |
| v1.1.1 | 1.1.1 / 1.1 / 1 / latest |
| v1.1.0-rc.2 | 1.1.0-rc.2のみ。latest / 1 / 1.1は変更しない |

amd64とarm64でそれぞれビルド・オフラインテスト・CLI起動を確認した後、linux/amd64とlinux/arm64を含むイメージを一度のbuild/pushで公開します。QEMUを使うARM検証はARM実機の動作保証ではありません。

既存の完全バージョンタグは上書きしません。公開処理は直列化します。古い正式Gitタグの再実行は拒否し、latestやメジャー・マイナータグの巻き戻りを防ぎます。この簡単な運用では、より新しい安定タグが存在する状態で旧系列を追加公開することも拒否します。旧系列の保守が必要になった際は、浮動タグを分ける方針を先に整備してください。

公開済みGitタグは付け替えません。依存パッケージ・ベースイメージを更新して再配布する場合も、新しいPATCH版を作成します。浮動タグ（1.0、1、latest）は後続の正式版で更新されます。latestは将来のMAJOR変更も追従します。NASが稼働中に勝手に更新される設定ではなく、pullとコンテナ再作成で適用します。

## 既存v1.0.0の初回公開

v1.0.0には後から追加した公開ワークフローが含まれていないため、タグを作り直しません。Actions → Publish Docker release → Run workflowでmain上のワークフローを選び、tagに `v1.0.0` を入力します。この手動入口も既存の正式版またはRCタグしか受け付けず、ビルドするコードはmainではなくv1.0.0です。新しいバージョンではワークフローを含むコミットへタグを付けます。

成功後はActionsのSummaryに記録されたdigestとDocker Hubの4タグを確認します。

```bash
docker buildx imagetools inspect sosboy/gmail-bridge:1.0.0
docker buildx imagetools inspect sosboy/gmail-bridge:1.0
docker buildx imagetools inspect sosboy/gmail-bridge:1
docker buildx imagetools inspect sosboy/gmail-bridge:latest
```

4タグのdigestが同一で、linux/amd64とlinux/arm64のmanifestがあることを確認します。途中でpushが失敗した場合は、完全版タグを削除してやり直さず、各タグとdigestを確認してから修復方法を決めてください。

## イメージから導入する

現在の正式版はv1.1.1です。v1.1.0にIMAP無応答待ちの修正を加えました。v1.0用の旧方式Composeは `docker-compose.image.example.yml`（既定sosboy/gmail-bridge:1.0.0）。v1.1用は `docker-compose.config.image.example.yml`（バージョン指定必須、単一/config）です。v1.0に/config方式を組み合わせないでください。

新規導入は [INSTALL.md](INSTALL.md)、既存環境更新・rollbackは [MAINTENANCE.md](MAINTENANCE.md) に従います。RCも正式版も同じComposeで完全タグを変更します。v1.1は未初期化待機→Console明示init→自動復帰、v1.0は常駐開始前の単発initです。ARM32は対象外です。


Docker HubのOverviewは [DOCKER_HUB.md](DOCKER_HUB.md) の日英説明を使用します。
