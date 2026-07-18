"""dev_updater: 生成済みアプリケーションを更新する独立ツール。

ai-dev-council 本体（`ai_dev_council` パッケージ）には手を加えず、外部から
既存モジュール（claude_coding_agent / context_builder / test_runner /
レビュー関数 / usage_tracker）を呼び出して、既存コードへの差分更新を行う。

ai-dev-council のパイプラインは「設計→実装」の新規生成専用であり、
後日「既存アプリ＋変更要求→差分更新」を行う入口が無い。本ツールが
その入口を提供する。設計ドキュメントは ai-council 側で更新・人間承認
済みのもの（--context-file）を入力とし、設計の再生成は行わない
（docs/運用フロー相当の「人間の確認を挟む」原則を維持するため）。
"""
