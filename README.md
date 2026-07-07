# ai-dev-council

タスク説明から「設計 → 設計レビュー → 実装（自律コーディング）→ 実装レビュー →
GitHub issue記録」までを自動実行する、[ai-council](https://github.com/momokuomomo-crypto/ai-council)
の姉妹ツール（プログラミング特化版）。ai-councilは「テーマについて話し合う」
会話専用ツールだが、ai-dev-councilは実際にコードを生成・実行・修正する。

gitやコマンド操作に慣れていない場合は、まず
[かんたんセットアップガイド](かんたんセットアップガイド.md)を参照すること。

---

## 運用方法（最短手順）

1. `.env.example`を`.env`にコピーし、3社分のAPIキーを書き込む。

   ```
   ANTHROPIC_API_KEY=sk-ant-...
   OPENAI_API_KEY=sk-proj-...
   GEMINI_API_KEY=AQ...
   ```

2. 依存パッケージをインストールする（初回のみ、下記「セットアップ」参照。
   `pip install`だけでは不十分な点に注意）。

3. プロジェクトルート（このREADMEがあるディレクトリ）で実行する。

   ```
   python -m ai_dev_council.pipeline "作りたいものの説明" --output-dir ./output/my-project
   ```

4. 実行完了後に作成されるGitHub issue（このリポジトリ自身に作成される）で、
   設計・レビュー結果・テスト結果を確認する。生成されたコードは
   `--output-dir`で指定したディレクトリに置かれる。

実行のたびにClaude・OpenAI・Geminiへの課金APIが呼ばれる（固定回数）のに加え、
**Claude Agent SDKによる自律コーディングエージェントが起動し、ファイルの
作成・編集とbashコマンド（テスト実行等）を自動実行する**。実行前にそれぞれ
別々の`[Y/n]`確認が入る（詳細は下記「実行回数・費用の制限」参照）。

---

## セットアップ

1. Python 3.12以降を用意する。
2. **Node.jsをインストールする**（Claude Agent SDKがClaude Code CLIを
   サブプロセスとして起動するため必須。`pip install`だけでは動かない）。
3. **Claude Code CLIをインストールし、ログイン済みにする**
   （`npm install -g @anthropic-ai/claude-code` 等。Agent SDK単体では
   認証を代替しない。既にこのマシンでClaude Codeを使っているなら対応済み）。
4. 依存パッケージをインストールする。

   ```
   pip install -r requirements.txt
   ```

   （`requirements.txt`がない場合は
   `pip install anthropic openai google-genai python-dotenv pyyaml claude-agent-sdk==0.2.110`）

5. `gh` CLI（GitHub CLI）をインストールし、`gh auth login`済みにする
   （実行記録issueの作成に必要）。
6. `.env.example`を`.env`にコピーし、各社のAPIキーを設定する。
   `.env`はgit管理対象外（`.gitignore`済み）。

---

## 使い方

```
python -m ai_dev_council.pipeline "<タスク説明>" --output-dir <生成先> \
  [--context-file <path>] [--max-rounds N] [--max-implementation-rounds M]
```

* `<タスク説明>`（必須）：作りたいソフトウェアの説明（自由記述）
* `--output-dir`（必須）：コードの生成先ディレクトリ
* `--context-file`（任意）：参考情報を含むテキストファイル
* `--max-rounds`（任意、デフォルト1）：設計レビューのリビジョンループ上限回数
* `--max-implementation-rounds`（任意、デフォルト1）：実装レビュー→修正の
  リビジョンループ上限回数

### 実行例

```
python -m ai_dev_council.pipeline \
  "webで動く顧客管理システムを作る。顧客のCRUD操作ができればよい" \
  --output-dir ./output/customer-management --max-rounds 2 --max-implementation-rounds 2
```

---

## ai-councilと組み合わせた使い方（要件定義→実装）

ai-dev-council自身の設計ステージ（OpenAIが1回で設計を作る）だけでは
要件が固まりきらないことがある。その場合、まず
[ai-council](https://github.com/momokuomomo-crypto/ai-council)で
要件・仕様を3社に議論させて固めてから、その結果を`--context-file`で
ai-dev-councilに引き継ぐとよい。この連携のためにコードを変更する必要は
なく、既存の`--context-file`（参考情報を渡す仕組み）だけで実現できる。

### 手順

1. **要件定義・設計（ai-council側）**：作りたいものの要件について
   3社に話し合わせる。

   ```
   python -m ai_council.council "<作りたいものの要件・仕様について話し合わせたいテーマ>" --max-rounds 2
   ```

   実行すると`./output/`配下に`{タイムスタンプ}_ai_council_summary.txt`
   （共通認識・相違点・最終提案）が生成される。

2. **実装（ai-dev-council側）**：そのsummary.txtを参考情報として渡し、
   実装させる。

   ```
   python -m ai_dev_council.pipeline "<タスクの説明>" \
     --context-file "<ai-councilが出力したsummary.txtのパス>" \
     --output-dir ./output/<好きな名前>
   ```

   ai-dev-councilの設計ステージ（OpenAI）が、このcontext-fileの内容
   （3社の合意済み要件）を踏まえて設計ドキュメントを作成する。

### 役割分担

- **ai-council**：要件定義・仕様の合意形成（会話専用、コードは書かない）
- **ai-dev-council**：合意済みの要件を踏まえた実装（実際にコード＋テストを書く）

それぞれのツールの役割は変えず、間はファイル（summary.txt）を手動で
橋渡しするだけで連携できる。

---

## 実行回数・費用の制限

1日あたりの実行回数はデフォルトで3回まで（`config.yaml`の`max_runs_per_day`
で変更可能）。実行前に2段階の確認が入る。

1. **固定回数API呼び出しの確認**：設計・設計レビュー・実装レビューは
   スキーマ強制の単発API呼び出しなので、実行前に呼び出し回数の見込みを
   表示して`[Y/n]`確認する。
2. **自律コーディングエージェントの確認**：実装ステージ（Claude Agent SDK）は
   固定回数ではなく、ファイル書き込み・bashコマンド実行を伴う多ターンの
   自律実行になる。対象ディレクトリと最大ターン数を明示した上で、別途
   `[Y/n]`確認を行う。実装レビューで指摘があり修正ループに入る場合も、
   同じ確認が再度入る。

いずれかで`n`を選ぶと、その先のAPI呼び出し・自律実行は一切行われない
（1日あたりの実行回数も消費しない）。

---

## 処理の流れ

```text
タスク説明
    │
    ▼
設計（OpenAI）
    │
    ▼
設計レビュー（Claude + Gemini、最大N回、全員承認で早期終了）
    │
    ▼
実装（Claude Agent SDK：output_dirへファイル作成・テスト実行）
    │
    ▼
実装レビュー（Gemini + OpenAI、最大M回、指摘があればClaude Agent SDKで修正）
    │
    ▼
GitHub issue作成（ai-dev-council自身のリポジトリに、OPENのまま）
    │
    ▼
人が採否判断
```

各プロバイダーは自分が書いた成果物をレビューしない：設計レビューは
Claude+Gemini（OpenAIが書いた設計をOpenAI自身は見ない）、実装レビューは
Gemini+OpenAI（Claudeが書いたコードをClaude自身は見ない）。

---

## ディレクトリ構成

```
ai_dev_council/
  __init__.py
  llm_config.py        # APIキー読込
  config.yaml           # 各社のモデル名・max_tokens・claude_agent設定
  schema_repair.py       # 構造化出力の破損対処
  usage_tracker.py       # 1日あたり実行回数の制限
  openai_provider.py     # 設計生成・設計改訂・実装レビュー
  claude_provider.py     # 設計レビュー
  gemini_provider.py     # 設計レビュー・実装レビュー
  claude_coding_agent.py # Claude Agent SDKによる実装・修正
  context_builder.py     # 生成コードをレビュー用テキストへ連結
  github_issue.py        # 実行記録issueの作成（closeしない）
  pipeline.py            # オーケストレーター本体 + CLI
tests/                   # モックテスト（実APIも実Agent SDK実行も呼ばない）
docs/設計.md             # 詳細設計書
```

---

## GitHub issueについて

1回の実行につき1つのissueを、このリポジトリ（ai-dev-council自身）に作成する。
ai-councilの開発ワークフロー用issue（実装コミットを参照してcloseする運用）
とは異なり、ここでのissueは「パイプライン実行の成果物・記録」であるため、
作成後もopenのまま残す（closeしない）。

---

## テスト

```
python -m unittest discover -s tests
```

実APIも実Claude Agent SDK実行も呼ばない。モックで各段階の入出力を検証する。
