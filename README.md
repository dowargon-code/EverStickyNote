# EverStickyNote

Evernote デスクトップアプリのローカルデータから、指定したノートブックのノートを読み取り専用の付箋として表示します。編集は Evernote 側で行い、このアプリは書き戻しません。

## 必要なもの

- Windows
- ログイン済みの Evernote デスクトップアプリ
- 64-bit の Python 3.12（PySide6 は 32-bit では入りません）

## フォルダ構成

```
EverStickyNote/
├── README.md
├── pyproject.toml              # パッケージ定義（版は src/everstickynote/__init__.py）
├── requirements.txt
├── build.ps1                   # ビルドの入口。dist\ に配布物を作る
├── config/                     # 配布する設定ファイルの原本（Git 管理）
│   └── config.toml
├── src/                        # ソースコード（Git 管理）
│   └── everstickynote/
│       ├── __main__.py         # python -m everstickynote の入口
│       ├── main.py
│       ├── ui/
│       └── assets/             # アプリアイコン
├── tests/
├── build/                      # 中間ファイル（Git 管理外）
└── dist/                       # build.ps1 が作る（Git 管理外）
    ├── EverStickyNote/         # EverStickyNote.exe、config.toml、README.md など
    └── EverStickyNote-v1.2.0.zip
```

## セットアップ

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
```

## 起動（ソースから）

```powershell
.\.venv\Scripts\python.exe -m everstickynote
```

## テスト

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## ビルド

```powershell
.\build.ps1
```

`dist\EverStickyNote\` に EXE と `config.toml`（`config\` からコピー）などがそろい、その中身を固めた `dist\EverStickyNote-v<版>.zip` もできます。

## 設定

設定ファイル `config.toml` は、EXE で動かすときは EXE と同じフォルダ、ソースから動かすときはプロジェクトのフォルダ（このファイルと同じ場所）から読みます。ソースから動かす場合は、原本 `config\config.toml` をコピーし、付箋として出すノートブック名を Evernote 上の表示名どおりに書きます。複数指定できます。プロジェクト直下の `config.toml` は端末ごとの設定なので、リポジトリには含めません（無ければ起動時にひな形を作ります）。

また、本体ウィンドウの「設定」ボタンから GUI で以下の項目を変更・保存し、即時反映することもできます。

- **表示するノートブック**: ローカル DB から見つかった全ノートブック一覧（設定済みで見つからないノートブック名も保持・解除可能）
- **監視間隔 (`watch_seconds`)**: ローカルデータ確認間隔（秒）
- **点滅時間 (`flicker_seconds`)**: 更新時の枠点滅時間（秒）
- **点滅後に再び閉じる (`close_after_flicker`)**: 非表示だった付箋を更新点滅後に自動で閉じるか
- **デフォルトのノートブック (`default_notebook`)**: 新規作成したノートが取り込まれる Evernote 側のデフォルトノートブック名（例: `"0. Inbox"`）。表示対象（`notebooks`）に含まれていなくても、本アプリから新規作成したノートだけを検知して付箋表示します

```powershell
copy config\config.toml config.toml
```

```toml
notebooks = ["ノートブック名"]
default_notebook = ""
```

複数のノートブックを設定した場合は、全許可ノートブックをバックグラウンドで横断監視し、メインフォームの一覧も「すべてのノートブック」でまとめて表示できます。

付箋の位置と、本体をトレイに格納したかは `config.toml` と同じフォルダの `position.toml` に保存され、次回起動時に復元されます。このファイルは端末ごとの状態なので、リポジトリには含めません。本体はタスクバーではなく通知領域（システムトレイ）に表示します。

## 付箋と本体の操作

- 上の行をドラッグして移動します。ダブルクリックすると、そのノートを Evernote で開きます。
- 付箋本文に含まれる `https://...` / `http://...` / `evernote:///...` などの URL をクリックすると、ブラウザまたは Evernote で開きます。
- 「整列」で、押した付箋があるモニターの右上から下へ、はみ出したら左の列へ並べます。押した付箋が先頭（右上）になります。
- 「色」で背景色を切り替えます。
- 「最前面」で、最前面固定のオンとオフを切り替えます。ウィンドウは閉じません。
- 付箋の「閉じる」は、その付箋をタスクバーへ最小化します。Evernote のノートは削除しません。
- 本体ウィンドウ・システムトレイ右クリックメニュー・付箋右クリックメニューの「新規作成」でタイトルと本文を入力して「作成」を押すと、`.enex`（Evernote Export XML）を生成して OS 関連付け（未関連付け時は保存ダイアログ）で Evernote に渡します。Evernote 側のデフォルトノートブックに取り込まれ、`default_notebook` 設定と一致していれば本アプリで作成したノートだけを自動検知して付箋表示します（後から Evernote 側で表示対象ノートブックへ移動しても付箋はそのまま維持されます）。
- 本体ウィンドウの「設定」で対象ノートブック・監視間隔・点滅設定・デフォルトのノートブックを編集できます。
- 本体ウィンドウの「開く」、または一覧の付箋名をダブルクリックすると、最小化・非表示にした付箋を再表示します。
- 本体ウィンドウの「閉じる」は、一覧で選んだ付箋をタスクバーへ最小化します。
- 本体ウィンドウはタスクバーではなくシステムトレイに格納されます。トレイアイコンをダブルクリックするか、右クリックメニューからメインフォームを開く・新規作成・終了ができます。
- 本体ウィンドウの × を押すと終了確認が出ます。はいを選ぶとアプリを終了します。
- 二重には起動しません。すでに動いているときに起動すると、動いている方のメインフォームを表示します。

## ライセンス

本リポジトリのソースコードは [MIT License](LICENSE) の下で公開しています。

## 第三者ライセンス

本アプリは次のオープンソースソフトウェアを利用しています。

| 名称 | 用途 | ライセンス |
|------|------|------------|
| [PySide6](https://www.qt.io/qt-for-python) | GUI | [LGPL v3](https://www.gnu.org/licenses/lgpl-3.0.html) |
| [evernote3](https://pypi.org/project/evernote3/) | Evernote API クライアント（レガシー経路） | Apache License 2.0 |
| [Apache Thrift](https://thrift.apache.org/) | evernote3 の依存 | Apache License 2.0 |

詳細な第三者ライセンスの記載は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。EXE を配布する場合、PySide6（LGPL v3）に関する要件にも留意してください。

## アプリアイコン

`src/everstickynote/assets/app-icon.png` および `src/everstickynote/assets/app-icon.ico` は、作者（Dowargon）が本プロジェクト用に作成したものです。MIT License と同じ条件で、本リポジトリに含まれる範囲で利用できます。

## 免責・商標

- 本ソフトウェアは Evernote 社の公式製品ではありません。Evernote デスクトップアプリのローカルデータを**非公式**に読み取る方式です。Evernote のアップデートや利用規約の変更により、動作しなくなる可能性があります。利用は自己責任でお願いします。
- 「Evernote」および Evernote のロゴは、Evernote Corporation の商標または登録商標です。本プロジェクトは Evernote 社とは無関係です。
