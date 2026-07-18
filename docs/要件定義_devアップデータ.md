# dev_updater 要件定義・設計

Version: 1.0.0

---

# 1. 目的・背景

ai-dev-council のパイプラインは「設計→設計レビュー→実装→実装レビュー」の
**新規生成専用**であり、生成したアプリケーションを後日「既存コード＋変更
要求→差分更新」する入口が無かった。実装プロンプトは新規作成前提のため、
既存アプリのディレクトリに対してパイプラインを再実行すると、既存構造を
無視した設計・上書き再生成が起きるリスクがある。

`dev_updater` は、**既存の生成済みアプリケーションを、変更指示と更新済み
設計ドキュメントに基づいて差分更新する**ツールである。

姉妹ツール ai-council 側の doc_updater（要件定義・設計書の更新）と対を
なし、これにより「ドキュメント更新 → 人間承認 → コード更新」の
保守サイクル全体が回るようになる。

# 2. 位置づけ（ai-dev-council 本体との関係）

- `dev_updater` は **ai-dev-council 本体（`ai_dev_council` パッケージ）に
  手を加えない**。外部から既存モジュールを呼び出す独立したトップレベル
  パッケージ（`dev_updater/`）として実装する。
- 流用する既存部品：
  - `claude_coding_agent`（Claude Agent SDKの実行・エラー処理、
    レビュー修正 `run_implementation_fix`）
  - `context_builder`（既存コードの列挙・連結）
  - `test_runner`（テスト実行と生ログ・CSV保存）
  - `gemini_provider.generate_code_review` / `openai_provider.generate_code_review`
  - `usage_tracker` / `config.yaml`（実行回数制限・エージェント設定を共通利用）
- **設計ドキュメントの生成（OpenAI設計ステージ）は行わない**。更新の設計は
  ai-council 側の doc_updater で更新し人間が承認済みのものを
  `--context-file` として受け取る。これにより「AI成果物は人間が確認して
  から次工程へ進む」運用原則を維持する。

```text
変更要求
  → ai-council / doc_updater：要件定義・設計書を更新
  → 人間レビュー・承認
  → dev_updater：更新済み設計書を --context-file に、既存アプリを差分更新
  → git diff で人間レビュー → コミット
```

# 3. 機能要件

## 3.1 入力

* `instruction`（必須）：変更指示（自由記述）。
* `--app-dir`（必須）：更新対象の既存アプリのディレクトリ。
  **存在しない、またはソースファイルが無い場合はエラー**とする
  （新規生成は `python -m ai_dev_council.pipeline` の役割）。
* `--context-file`（任意、複数回指定可）：更新方針の設計ドキュメント。
* `--max-implementation-rounds`（任意、デフォルト1）：実装レビュー→修正の
  ループ上限。
* `--no-review`（任意）：実装レビューを省略する（低コスト運用）。

## 3.2 処理

1. 対象ディレクトリの妥当性確認（既存コードがあること）
2. gitの作業ツリーが汚れている場合は警告し、続行確認を挟む
   （更新前の状態へ戻す手段はgitのため）
3. **更新専用プロンプト**でClaude Agent SDKを実行する。プロンプトでは
   以下を明示する：
   - 既存アプリの更新タスクであり新規作成ではないこと
   - まず既存ファイルをReadして構成・設計パターンを把握すること
   - 必要なファイルのみ修正・追加し、無関係のファイルは変更しないこと
   - 既存テストを壊さず、変更部分のテストを追加すること
   - 既存ファイル一覧（相対パス）を提示する
4. テスト実行（`update` ラベルで生ログ・CSV保存）
5. 実装レビュー（Gemini+OpenAI）→非承認なら修正、を上限回数まで。
   レビュー・修正には変更指示と設計ドキュメントを「擬似設計ドキュメント」
   の形に包んで渡す（既存関数のインターフェースに合わせるため）
6. 最終テスト実行（`update_final` ラベル）
7. 更新レポート（`{日時}_update_report.json`）と `更新履歴.md` を
   app-dir 配下に保存する

## 3.3 バージョン管理の方針

コードの旧版退避はファイルコピーでは行わず、**gitに委ねる**
（doc_updaterの `_history/` 方式と異なるのは、コードはリポジトリで
確実にgit管理されているため）。そのため実行前のクリーンな作業ツリーを
推奨し、汚れている場合は警告する。

## 3.4 コスト管理

- 固定回数呼び出し（実装レビュー: 2×ラウンド数）は実行前に `[Y/n]` 確認
- Claude Agent SDKの自律実行は費用変動的であることを明示した別の確認
  ゲートを挟む（pipeline.py と同じ2段階確認の思想）
- `config.yaml` の `max_runs_per_day` を pipeline と共通の
  `usage_tracker` でカウントする

# 4. 使い方

```
python -m dev_updater "<変更指示>" --app-dir <既存アプリのディレクトリ> \
  [--context-file <path>]... [--max-implementation-rounds N] [--no-review]
```

例（せどりアプリに横断価格比較機能を追加する）：

```
python -m dev_updater "楽天市場API・Yahoo!ショッピングAPIによる横断価格比較機能を追加する" \
  --app-dir output/sedori-app \
  --context-file 設計書_せどり支援Webアプリ.md
```

実行後は `git diff` で変更内容を人間がレビューし、問題なければコミットする。

# 5. 非機能要件・制約

- APIキー・モデル設定・実行回数制限は ai-dev-council の既存の仕組みを
  再利用する。
- Claude Agent SDKの操作範囲は `--app-dir` にスコープを限定する
  （`claude_coding_agent` の既存設定に従う）。
- 更新後のコードは人間が `git diff` で確認してからコミットする。
  自動コミット・自動プッシュは行わない。
