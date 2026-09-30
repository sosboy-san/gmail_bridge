# Docker Hubへの正式版公開

公開先は `sosboy/gmail-bridge`。公開の自動化を準備した段階です。Docker Hubの初回pushが成功するまでは、イメージを取得できません。

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

`.github/workflows/docker-publish.yml` は `v*` タグのpushでのみ自動公開します。mainへのpushでは公開しません。正式な `vMAJOR.MINOR.PATCH`（MAJORは1以上）以外やプレリリースは拒否します。アプリのコードは必ず指定タグのコミットから取得します。

| Gitタグ | 同じmulti-archイメージを指すDockerタグ |
| --- | --- |
| v1.0.0 | 1.0.0 / 1.0 / 1 / latest |
| v1.0.1 | 1.0.1 / 1.0 / 1 / latest |
| v1.1.0 | 1.1.0 / 1.1 / 1 / latest |

amd64とarm64でそれぞれビルド・オフラインテスト・CLI起動を確認した後、linux/amd64とlinux/arm64を含むイメージを一度のbuild/pushで公開します。QEMUを使うARM検証はARM実機の動作保証ではありません。

既存の完全バージョンタグは上書きしません。公開処理は直列化します。古いGitタグの再実行は拒否し、latestやメジャー・マイナータグの巻き戻りを防ぎます。この簡単な運用では、より新しい安定タグが存在する状態で旧系列を追加公開することも拒否します。旧系列の保守が必要になった際は、浮動タグを分ける方針を先に整備してください。

公開済みGitタグは付け替えません。依存パッケージ・ベースイメージを更新して再配布する場合も、新しいPATCH版を作成します。浮動タグ（1.0、1、latest）は後続の正式版で更新されます。latestは将来のMAJOR変更も追従します。NASが稼働中に勝手に更新される設定ではなく、pullとコンテナ再作成で適用します。

## 既存v1.0.0の初回公開

v1.0.0には後から追加した公開ワークフローが含まれていないため、タグを作り直しません。Actions → Publish Docker release → Run workflowでmain上のワークフローを選び、tagに `v1.0.0` を入力します。この手動入口も既存の正式版タグしか受け付けず、ビルドするコードはmainではなくv1.0.0です。新しいバージョンではワークフローを含むコミットへタグを付けます。

成功後はActionsのSummaryに記録されたdigestとDocker Hubの4タグを確認します。

```bash
docker buildx imagetools inspect sosboy/gmail-bridge:1.0.0
docker buildx imagetools inspect sosboy/gmail-bridge:1.0
docker buildx imagetools inspect sosboy/gmail-bridge:1
docker buildx imagetools inspect sosboy/gmail-bridge:latest
```

4タグのdigestが同一で、linux/amd64とlinux/arm64のmanifestがあることを確認します。途中でpushが失敗した場合は、完全版タグを削除してやり直さず、各タグとdigestを確認してから修復方法を決めてください。

## イメージから導入する

初回公開成功後に利用できます。`docker-compose.image.example.yml` を `docker-compose.yml` へコピーします。既定は `sosboy/gmail-bridge:1.0.0`。ビルドは不要で、CPUアーキテクチャはDockerが選択します。ARM32には対応しません。

[INSTALL.md](INSTALL.md)のOAuth作成、config.ini、token.json、credentials.json、data/・backups/・logs/の準備と権限設定は必要です。常駐を起動する前に初期化します。

```bash
cp docker-compose.image.example.yml docker-compose.yml
export BRIDGE_UID=$(id -u)
export BRIDGE_GID=$(id -g)
docker compose config --quiet
docker compose pull
docker compose run --rm gmail-bridge python -m app.main init --latest 1 --dry-run
# 過去メールを取り込まず新着から開始する場合。初回のみ実行。
docker compose run --rm gmail-bridge python -m app.main init --from-now
docker compose up -d
```

QNAPのGUIでは必要に応じてマウント元を自分の共有フォルダの絶対パスへ変更し、UID/GIDを実機に合わせます。commandや別の常駐ループは追加しません。

追従する場合はローカルの `.env` に `BRIDGE_VERSION=latest`（または1、1.0）を指定します。更新は常駐停止・永続データのバックアップ後に `docker compose pull` と `docker compose up -d`。既存DBを再初期化しないでください。互換性を壊す更新ではリリースノートに従います。

## English

Release-tag-only multi-architecture publishing to `sosboy/gmail-bridge`. Set the Docker Hub username and namespace variables and token secret in the `dockerhub` GitHub environment. Manual dispatch accepts an existing stable tag for bootstrapping v1.0.0; it never builds main as a release. Exact version tags are not overwritten. Older stable tags are rejected to prevent floating-tag rollback. Use the image Compose example after the first successful publication, and complete OAuth, persistent mounts, permissions and initialization before starting the service.
