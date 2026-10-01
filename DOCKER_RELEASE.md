# Docker Hubへの正式版・RC公開

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
| v1.1.0 | 1.1.0 / 1.1 / 1 / latest |
| v1.1.0-rc.1（未公開・予定） | 1.1.0-rc.1のみ。latest / 1 / 1.1は変更しない |

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

現在の正式版はv1.0.0、v1.1.0-rc.1とv1.1.0はまだ未公開です。v1.0用の旧方式Composeは `docker-compose.image.example.yml`（既定sosboy/gmail-bridge:1.0.0）。v1.1用は `docker-compose.config.image.example.yml`（バージョン指定必須、単一/config）です。v1.0に/config方式を組み合わせないでください。

公開後の新規導入は [INSTALL.md](INSTALL.md)、既存環境更新・rollbackは [MAINTENANCE.md](MAINTENANCE.md) に従います。RCも正式版も同じComposeで完全タグを変更します。v1.1は未初期化待機→Console明示init→自動復帰、v1.0は常駐開始前の単発initです。ARM32は対象外です。

## 次の工程: v1.1.0-rc.1（このPhaseでは実行しない）

1. Phase 5差分をレビューし、別の指示を受けてcommit・pushします。CIでCompose config、Docker build、イメージ内検証を確認します。Cloud Workの静的成功だけをDocker実動作成功として扱いません。
2. RCに含めるコミットを固定し、指示された公開工程でv1.1.0-rc.1タグとGitHub **Pre-release** を作成します。ワークフローはタグでDocker公開を開始するため、タグpush時点で公開を伴う操作です。勝手に実行しません。
3. タグのコードでamd64/arm64のテスト、Docker Hub認証、既存完全タグの上書き拒否を通過後、**sosboy/gmail-bridge:1.1.0-rc.1だけ**を公開します。対応する正式版またはより新しい正式タグが既に存在すればRCは拒否します。RC公開にlatest等の浮動タグは含めません。
4. Actionsのdigestと両CPUのmanifestを確認し、公開前後のlatest / 1 / 1.1のdigestを比較します。RCからの変更がないことを確認します（未作成の1.1があれば未作成のまま）。公開済みRCを修正・上書きせず、修正はrc.2等の新しい番号にします。
5. QNAPの独立した検証保存先でHubからpullし、新規起動待機、Console init、中断再開、通知・TTL、v1.0 DB移行、永続化、token更新、NAS再起動を確認します。削除試験は専用メールでdry-runから行います。QEMUテストを実機合格の代用にしません。
6. 合格後に英語資料を整備し、別の指示で正式v1.1.0を公開します。正式版では1.1.0 / 1.1 / 1 / latestを公開します。同じComposeのBRIDGE_VERSIONだけを1.1.0へ変更し、停止・backup・pull・status・upの更新手順を使います。initは繰り返しません。

## English

The distribution workflow accepts existing stable or rc.N tags, builds the selected tag's commit and refuses exact-version overwrites. RC publishes only its exact Docker tag; stable releases publish version/minor/major/latest. Other prerelease formats are rejected. v1.1 and its RC are not published yet. The Japanese installation and maintenance guides describe the new /config layout and explicit init after safe waiting. A complete English revision is deferred.
