# 大金空調銘牌 AI 辨識系統

手機拍照 → 模型辨識 → 人工確認／修正 → 分享至 LINE。每次確認另存為一版標註，AI 原值、原始回覆、人工答案與差異分開保存。

Python 3.12+、uv、Flask、SQLite、HTML/CSS/Vanilla JavaScript。預設 HTTP **50003**。無 React、無 LINE Messaging API、無自動微調。

## 快速啟動

在本專案目錄執行：

```sh
uv sync --frozen
cp .env.example .env
```

編輯 `.env`，填入已安裝的視覺模型。例如可先安裝規格要求的 Qwen3-VL 8B instruct 版本，再填入實際標籤：

```sh
ollama pull qwen3-vl:8b-instruct
```

```dotenv
OLLAMA_MODEL=qwen3-vl:8b-instruct
APP_PORT=50003
```

模型只由設定選擇，程式不會自行下載或改用雲端模型。[Ollama 官方模型頁](https://ollama.com/library/qwen3-vl:8b-instruct)

```sh
uv run nameplate init-db
```

分別在兩個終端啟動：

```sh
uv run nameplate worker
```

```sh
uv run nameplate serve
```

或使用 `./scripts/start.sh` 一起啟動。開啟 http://127.0.0.1:50003 。Worker 未啟動時，上傳會停在等待辨識；資料不會遺失。

## 手機與 DDNS

HTTP、Port 50003，配合既有路由器／社區 Port 轉發。外部部署請設定 `.env`：

```dotenv
APP_HOST=0.0.0.0
APP_PORT=50003
ACCESS_PASSWORD=請改成至少12字元的私人存取碼
TRUSTED_HOSTS=localhost,127.0.0.1,你的Mac內網IP,你的DDNS完整網域
```

`TRUSTED_HOSTS` 填主機名稱或 IP，不含通訊協定、路徑、Port。路由器的 TCP 50003 需轉發至這台 Mac 的 TCP 50003；Mac 的內網 IP 建議固定。實際網域與外部連線須於部署時驗證，程式不會修改路由器設定。

設定存取碼後，頁面、API、原圖、處理圖、歷史與資料集下載均需登入。僅使用 Tailscale 時也可將 `APP_HOST` 設為該 Mac 的 Tailscale IP，並加入 `TRUSTED_HOSTS`。無存取碼的服務只接受本機或 Tailscale 來源。

分享按鈕偵測瀏覽器功能：原生分享 → 剪貼簿 → 選取文字後手動複製。使用者自行在 LINE 選擇收件者並傳送；系統不宣稱訊息已送達。

詳細部署、停機與備份請見 [docs/deployment.md](docs/deployment.md)。

## 使用流程

1. 首頁選擇模型，拍攝或選擇 JPEG、PNG、HEIC，最多 20 MB。
2. 可標記照片難度與設備群組。同設備多張照片使用相同群組，避免調整集與驗收集洩漏。
3. 等待辨識，核對原圖與全部欄位。LOW 與規則警告會醒目提示。
4. 有值欄位標記已核實。空白需區分未標示、無法辨讀與尚未核對。
5. 修正原因可選指定分類，不確定保留 UNKNOWN；不會推測根因。
6. 按「確認資料並儲存」建立不可覆寫的標註版本。再修改會新增版本。
7. 分享或複製該確認版本。重新辨識新增 attempt，不會覆寫舊結果。

辨識失敗仍能重試、重拍，或人工填寫後確認。型號依規則轉大寫、移除空白；序號不替換易混淆字元。量測單位不明時保持 null。UI 的信心枚舉是模型自評，不是統計機率。

## NVIDIA NIM 與多模型比較

設定 `NVIDIA_API_KEY`、`NVIDIA_MODEL` 與 `NVIDIA_BASE_URL`。預設 adapter 使用同步 `/chat/completions`，圖片以 base64 傳送。按模型官方規格選擇 `NVIDIA_OUTPUT_MODE=prompt/json_object/json_schema` 與圖片大小限制。非同步 202 端點會回報明確的不支援訊息，不會無限輪詢或重試。

若以 NVIDIA 為一般辨識預設，設定 `VISION_PROVIDER=nvidia`。金鑰僅存 `.env`。缺少金鑰時無法實際驗證雲端推論；自動化測試使用模擬 HTTP 回覆。

複製 `config/benchmark_profiles.example.toml` 至 `config/profiles.toml`，填入其他本地／雲端模型識別。前端只可選伺服器已登記的 profile，不能指定任意服務網址。

## HITL 與 Benchmark

- 四層資料：原圖／處理圖、Machine Observation、Machine Decision、Human Ground Truth。
- 每次確認保存 19 筆欄位標註，含原 AI 值、人工輸入、標準化人工值、前版值、信心、警告、修正原因與備註。
- OCR、Decision Model、Cascade 第一版未啟用；OCR 原始結果為 null，數字門檻不作用於 LLM 自評枚舉。
- 私有 ZIP 匯出包含原圖、處理圖、原始模型回覆、設定快照、人工答案、修正差異與確認歷程。
- `confirmed`：全部欄位已核實、成功辨識且未修改；`corrected`：人工有改；`low_confidence`、`failed` 可包含尚未標註資料，Ground Truth 為 null。
- `benchmark`：人工確認且至少一個核心欄位可評分；每個固定版本有 manifest 與雜湊，後續修改不影響舊答案。
- 每次匯出最多取 100 張照片，相同原圖去重；同照片或設備群組不能跨 DEVELOPMENT／HOLDOUT。
- 只對 DEVELOPMENT 中 19 欄皆已核實的樣本產生 `training_ready.jsonl`；沒有執行訓練或對外上傳。

從「資料集」建立 Benchmark 版本，再至 Benchmark 選擇同圖多模型比較。報表提供逐欄正確率、六核心欄位全對率、難度分層、失敗率、空值率、基準差異率、耗時與人工審查後的幻覺率。前後比較必須同一固定資料集，任何核心欄位退步都獨立列出。小樣本不會判定通過。

95% 是待實際現場資料驗證的目標，不是目前已達成的成績。詳見 [評分定義](docs/benchmark.md) 與 [架構／資料鏈](docs/architecture.md)。

## 測試與開發

```sh
uv run pytest -q
uv run ruff check --config pyproject.toml app tests
node --check static/js/app.js
```

測試包括兩種 Provider HTTP 格式與錯誤、Schema／Normalize、規則驗證、JPEG／HEIC／EXIF、上傳限制、工作恢復、人工修正版本、分享資格、私有匯出、分組洩漏、逐欄回歸與存取保護。測試圖片及模型輸出都是合成 fixture，不是現場 Benchmark 成績。

`DEBUG_DATA=true` 才開放 `/api/attempts/<id>/debug`；仍受存取保護。一般 UI 不提供原始回覆。SQLite migrations 由 `uv run nameplate init-db` 套用；資料模型變更需新增 migration，不能覆寫已使用版本。

## 第一批驗收資料

尚未收到真實現場照片，因此沒有建立虛構 Ground Truth。請將正常、斜拍、遠距離、小字、髒污、龜裂、R22、R32 照片，以首頁「用途：Benchmark 樣本」上傳並人工標註；這些來源及其評測工作不納入現場工作 Dashboard。

真實部署另需所選視覺模型、NVIDIA 憑證（要比較雲端時）、實際 DDNS 與手機實機測試。未實作第二階段的 OCR、透視校正、自動裁切、Jev、模型路由、微調、LINE Login 或 Messaging API。
