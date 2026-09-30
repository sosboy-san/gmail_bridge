# GitHub Pages 公開手順

このリポジトリの紹介サイトは、`main` ブランチの `/docs` からGitHub Pagesで公開しています。以下は保守・再公開時の手順です。

## 公開前の確認

1. `index.html`、`privacy.html`、`terms.html` の記載を確認します。特に個人用OAuthの運用者がデータの取り扱いに同意できる内容か確認してください。
2. 公開対象検査を実行し、秘密情報や実機用ファイルが含まれていないことを確認します。
3. 所有者がPublic化を承認した後、公開対象だけをGitHubへ反映します。実機用 `test/` や `.release-work/` は反映しません。
4. GitHubのSettings → Pagesで、公開元を対象ブランチの `/docs` に設定します。利用可能な設定はリポジトリのプラン・権限に従います。
5. GitHubに表示される実際の公開URLを開き、全ページとリンクを確認します。

公開URL:

- 紹介: https://sosboy-san.github.io/gmail_bridge/
- プライバシー: https://sosboy-san.github.io/gmail_bridge/privacy.html
- 利用条件: https://sosboy-san.github.io/gmail_bridge/terms.html

## Google OAuthへの登録

公開先が到達可能になった後に、ホームページ・プライバシーポリシー・必要な場合の利用規約の各URLを登録します。アプリ名と既存のサポート連絡先は維持します。

承認済みドメインはGoogleの画面と最新の公式条件に従って確認してください。`github.com` や `github.io` 全体を所有していると申告しないでください。GitHub PagesのURLがあるだけで、Googleのドメイン条件や審査を満たすとは限りません。所有権確認を求められた場合は対応可能な確認方法を調べてから進めます。

個人利用の審査免除、本番環境への切替、ブランディングの入力条件はそれぞれ別です。この手順はGoogleによる承認を保証しません。

## 更新

静的HTML/CSSのみで、外部フォント・アクセス解析・JavaScript・フォームは使用していません。データ処理を変更した際はポリシーも見直します。
