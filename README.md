# 陳憲隆自製 大金空調銘牌辨識

AI 智慧影像辨識

手機拍照 → 模型辨識 → 人工確認／修正 → 分享至 LINE。每次確認另存為一版標註，AI 原值、原始回覆、人工答案與差異分開保存。

Python 3.12+、uv、Flask、SQLite、HTML/CSS/Vanilla JavaScript。預設 HTTP **50003**。無 React、無 LINE Messaging API、無自動微調。

完整使用流程、狀態機、資料飛輪、模型評估及 M6 容量／價格參考，請見 [操作手冊](操作手冊.md)。

2026-09-28 版本狀態：NAS 已更新為 `20260928-gemini-busy-ac563ef`，加入高需求提示與更換模型操作，兩行 LINE 分享及 Gemini Provider 沿用。NAS 與 Mac 的預設模型均設為 Gemini `gemini-flash-latest`；NIM 仍可手動選用。新辨識使用 `nameplate_identity_v002`，只擷取**室外機型號、室內機型號、序號**；歷史 19 欄與人工版本保留。Mac 背景服務依使用者要求保持關閉。[NAS 入口](http://home-taichung.myds.me:50003/)・[部署與回復流程](docs/nas-deployment.md)

前次 Gemini 發布時，新金鑰在 Mac／NAS 均通過模型資訊查詢；NAS 實照推論的三次檢查皆收到 Gemini HTTP 503 高需求回覆，尚未完成新金鑰的成功實照驗證。本次提示更新使用隔離模擬回覆測試，沒有追加實際模型呼叫。供應商忙碌時可稍後重試或手動選 NIM；系統不會自動切換模型。詳見 [驗證紀錄](docs/verification.md)。

供應商明確回報需求過高時，結果頁顯示「需求量過高，請更換模型」。按「更換模型」會跳到重新辨識的模型選單，選擇其他已設定模型後再送出。較早僅保存 HTTP 503 的紀錄顯示「模型服務暫時無法使用，請更換模型」，不推測原因；失敗紀錄與原圖保留，用量未知時不填入零。

## 快速啟動

在本專案目錄執行：

```sh
uv sync --frozen
cp .env.example .env
```

編輯 `.env`，範例設定預設使用 Google AI Studio／Gemini。填入自己的 `GEMINI_API_KEY`，模型設定為 `gemini-flash-latest`；Key 不可提交至 Git。

```dotenv
VISION_PROVIDER=gemini
GEMINI_MODEL=gemini-flash-latest
PROMPT_VERSION=nameplate_identity_v002
APP_PORT=50003
```

若改用 NVIDIA NIM，填入 `NVIDIA_API_KEY`、`NVIDIA_MODEL`，並設定 `VISION_PROVIDER=nvidia`；目前驗證過的模型包含 `z-ai/glm-5.3-flash`。兩種雲端金鑰分開保存，切換預設不會刪除另一個供應商的設定。

若改用本地 Ollama，另設定 `VISION_PROVIDER=ollama`。例如安裝 Qwen3-VL 8B instruct，再填入實際模型標籤：

```sh
ollama pull qwen3-vl:8b-instruct
```

```dotenv
OLLAMA_MODEL=qwen3-vl:8b-instruct
VISION_PROVIDER=ollama
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

確認與分享操作位於結果頁最上方。辨識中維持固定載入畫面，只更新狀態，完成後才切換結果。

分享／複製文字僅有人工確認的室外機型號與序號兩行，沒有標題、欄位名稱、室內機或頁尾；照片分享保留。例如：

```text
RHF30RVLT
E045859
```

新三欄及歷史 19 欄確認版本皆使用此格式。缺值保留對應空行，不自行補字，也不改寫保存的 AI 或人工資料。

分享前會預載原始相片，支援檔案分享的瀏覽器可將原圖與已確認文字交給手機分享功能；不支援時提供「儲存原始相片」與「開啟 LINE 帶入文字」兩步操作。普通 HTTP 網址通常沒有 Web Share API，無法只靠前端強制叫出原生圖文分享；LINE 文字連結不會自動夾帶圖片。使用者自行加入原圖、選擇收件者並傳送；系統不宣稱訊息已送達。若 LINE 只接收圖片，可再使用複製文字。

「複製文字」與「複製紀錄連結」支援 HTTP 的傳統複製方式，只有瀏覽器回報複製成功才顯示成功；皆受阻時展開並選取文字供手動複製。原始圖片不轉檔、不公開上傳，紀錄連結仍受原本存取保護。

詳細部署、停機與備份請見 [docs/deployment.md](docs/deployment.md)。

NAS 原生背景服務與搬遷方式見 [NAS 部署](docs/nas-deployment.md)。辨識結果會顯示耗時與本次輸入／輸出／總 token 用量，照片預設展開；照片上方文字可點選跳到人工修改欄位。免費規則與額度／限流差異見 [NIM 用量說明](docs/nim-usage.md)。

目前維持單一模型辨識與 `MODEL_MAX_TOKENS=4096`。三欄縮減及後續思考量、圖片裁切實驗見 [辨識速度改善](docs/recognition-speed.md)；未驗證的加速選項不會自動套用到 NAS。

## 使用流程

1. 首頁選擇模型，拍攝或選擇 JPEG（含手機 MPO 多影像 JPEG）、PNG、HEIC，最多 20 MB。MPO 保留完整原檔，推論只使用主影像並校正方向。
2. 可標記照片難度與設備群組。同設備多張照片使用相同群組，避免調整集與驗收集洩漏。
3. 等待辨識，核對原圖與本次欄位：新三欄辨識核對兩個型號與序號；舊 19 欄紀錄仍顯示原欄位。LOW 與規則警告會醒目提示。
4. 有值欄位標記已核實。空白需區分未標示、無法辨讀與尚未核對。
5. 修正原因可選指定分類，不確定保留 UNKNOWN；不會推測根因。
6. 按「確認資料並儲存」建立不可覆寫的標註版本。再修改會新增版本。
7. 分享或複製該確認版本。重新辨識新增 attempt，不會覆寫舊結果。

辨識失敗仍能重試、重拍，或人工填寫後確認。型號依規則轉大寫、移除空白；序號不替換易混淆字元。量測單位不明時保持 null。UI 的信心枚舉是模型自評，不是統計機率。

## NVIDIA NIM、Gemini 與多模型比較

設定 `NVIDIA_API_KEY`、`NVIDIA_MODEL` 與 `NVIDIA_BASE_URL`。預設 adapter 使用同步 `/chat/completions`，圖片以 base64 傳送。按模型官方規格選擇 `NVIDIA_OUTPUT_MODE=prompt/json_object/json_schema` 與圖片大小限制。非同步 202 端點會回報明確的不支援訊息，不會無限輪詢或重試。

若以 NVIDIA 為一般辨識預設，設定 `VISION_PROVIDER=nvidia`。金鑰僅存 `.env`。缺少金鑰時無法實際驗證雲端推論；自動化測試使用模擬 HTTP 回覆。

Google AI Studio 的 Gemini 使用原生 `generateContent` 介面。於伺服器 `.env` 設定以下項目，並以 `VISION_PROVIDER=gemini` 選為預設，即可沿用上傳、人工確認、耗時、token 與 Benchmark 流程。NIM 仍可從首頁模型選單選用。

```dotenv
GEMINI_API_KEY=填入自己的金鑰
GEMINI_MODEL=gemini-flash-latest
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GEMINI_MAX_IMAGE_BYTES=10000000
```

部署預設由 `.env` 決定；程式在沒有 `VISION_PROVIDER` 設定時的相容性 fallback 仍為 `nvidia`。切換後需重啟 Web 與 Worker，並以首頁預選模型及 `/api/bootstrap` 確認生效。

金鑰只透過 `X-goog-api-key` header 送至供應商，不進 URL、設定快照、前端或 Git。推論圖以 inlineData 傳送，使用 JSON Schema 約束輸出；不另上傳至 Files API。模型名稱可設定，實際回傳的 `modelVersion` 另存，方便追蹤 `latest` 別名的版本差異。Gemini 輸出 token 含可取得的思考 token；總數優先使用 API 回報，缺資料顯示「未提供」。429 顯示流量限制，不宣稱免費額度已用完；拒答、截斷與不完整回覆均保留可取得的觀測並要求人工處理。[Google 官方 API 與用量欄位](https://ai.google.dev/api/generate-content)

Worker 維持一個本地、一個雲端工作名額，NIM 與 Gemini 共用雲端名額，不會因增加 Provider 而自動提高並發。`config/benchmark_profiles.example.toml` 提供 Gemini 比較設定；不會自動切換供應商或無限重試。

複製 `config/benchmark_profiles.example.toml` 至 `config/profiles.toml`，填入其他本地／雲端模型識別。前端只可選伺服器已登記的 profile，不能指定任意服務網址。

## HITL 與 Benchmark

- 四層資料：原圖／處理圖、Machine Observation、Machine Decision、Human Ground Truth。
- 每次確認依該次辨識的欄位範圍保存標註：新版本 3 欄、歷史版本 19 欄，含原 AI 值、人工輸入、標準化人工值、前版值、信心、警告、修正原因與備註。
- OCR、Decision Model、Cascade 第一版未啟用；OCR 原始結果為 null，數字門檻不作用於 LLM 自評枚舉。
- 私有 ZIP 匯出包含原圖、處理圖、原始模型回覆、設定快照、人工答案、修正差異與確認歷程。
- `confirmed`：全部欄位已核實、成功辨識且未修改；`corrected`：人工有改；`low_confidence`、`failed` 可包含尚未標註資料，Ground Truth 為 null。
- `benchmark`：人工確認且至少一個核心欄位可評分；每個固定版本有 manifest 與雜湊，後續修改不影響舊答案。
- 每次匯出最多取 100 張照片，相同原圖去重；同照片或設備群組不能跨 DEVELOPMENT／HOLDOUT。
- 只對 DEVELOPMENT 中該樣本全部欄位皆可評分的資料產生 `training_ready.jsonl`：新樣本 3 欄、歷史樣本 19 欄。匯出保存欄位範圍；沒有執行訓練或對外上傳。

從「資料集」建立 Benchmark 版本，再至 Benchmark 選擇同圖多模型比較。報表提供逐欄正確率、評分範圍內的核心欄位全對率、難度分層、失敗率、空值率、基準差異率、耗時與人工審查後的幻覺率。新版本核心為 3 欄，歷史完整範圍為 6 個核心欄位；前後比較必須使用同一固定資料集，並在共同辨識及標註欄位上重新計分，列出排除欄位。任何共同核心欄位退步都獨立列出。小樣本不會判定通過。

95% 是待實際現場資料驗證的目標，不是目前已達成的成績。詳見 [評分定義](docs/benchmark.md) 與 [架構／資料鏈](docs/architecture.md)。

## 測試與開發

```sh
uv run pytest -q
uv run ruff check --config pyproject.toml app tests
node --check static/js/app.js
node --test tests/frontend/*.test.cjs
```

測試包括三種 Provider HTTP 格式與錯誤、Schema／Normalize、規則驗證、JPEG／HEIC／EXIF、上傳限制、工作恢復、人工修正版本、兩行分享與資格、私有匯出、分組洩漏、逐欄回歸與存取保護。自動化測試圖片及模型輸出都是隔離 fixture，不是現場 Benchmark 成績；實際雲端辨識另使用現場照片。

`DEBUG_DATA=true` 才開放 `/api/attempts/<id>/debug`；仍受存取保護。一般 UI 不提供原始回覆。SQLite migrations 由 `uv run nameplate init-db` 套用；資料模型變更需新增 migration，不能覆寫已使用版本。

## 第一批驗收資料

已使用指定資料夾的真實現場照片進行隔離測試；照片未加入專案或 Git，模型輸出也未自動當成 Ground Truth。正式驗收仍需將正常、斜拍、遠距離、小字、髒污、龜裂、R22、R32 照片，以首頁「用途：Benchmark 樣本」上傳並人工標註；這些來源及其評測工作不納入現場工作 Dashboard。

真實部署另需所選視覺模型、對應雲端憑證、實際 DDNS 與手機實機測試。未實作第二階段的 OCR、透視校正、自動裁切、Jev、模型路由、微調、LINE Login 或 Messaging API。
