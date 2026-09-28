# 驗證紀錄

本文件記錄軟體驗證，不代表現場辨識準確率。

以下依工作階段保留歷史狀態；目前 NAS 正式版本見末段「Gemini 預設與金鑰同步發布」，先前本地開發與 NIM 部署結果保留作為歷史紀錄。

## 已實測

- macOS arm64、Python 3.12.13、uv 0.11.20；依賴已寫入 uv.lock。
- 39 項自動化測試全部通過；Ruff 與 JavaScript 語法檢查通過。
- 手機介面調整另有 17 項前端測試：輪詢不重疊／中止晚到回覆、複製成功及拒絕、保留原圖 bytes／HEIC、檔案與文字分享參數、取消與不支援回退。原生分享以模擬瀏覽器 API 驗證，不代表已在 LINE 實際送達。
- 390×844 瀏覽器獨立 fixture：辨識中固定畫面、自動切換結果、確認與分享置頂、修改後隱藏舊分享、重新確認使用新文字均通過；一般 HTTP 位址顯示儲存原圖與 LINE 文字兩步操作。測試工具的虛擬剪貼簿無法讀回傳統複製結果，手機實際貼上仍待實機確認。
- SQLite 初始 migration 成功，Alembic metadata 差異檢查通過。
- 桌面與 390×844 手機尺寸瀏覽器：首頁、照片對照、修正室外機型號、儲存、已確認分享文字、私有 dataset 建立可操作；未發現 console error。
- Qwen3-VL 8B instruct 已下載並完成一次真實 Ollama 推論。
- 模型 digest：0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319。
- 合成英文測試卡 1200×920，成功回傳 JSON 並經 Normalize／Rule Validation；模型呼叫約 55.0 秒，包含該次載入條件，不能代表平均延遲。
- 合成圖未印出的欄位保持 null。該次沒有建立 Human Ground Truth，沒有納入現場資料庫或固定 Benchmark。
- 合成圖與原始回覆留在 data/verification/0e689659-f33a-4191-9489-14258bb310f9（Git 排除）。

## 2026-09-28 NVIDIA NIM 真實連線測試

- 使用 `.env` 的 `nvidia` profile，模型 `z-ai/glm-5.3-flash`，同步 Chat Completions、`prompt` 輸出模式及原設定的 4096 token 上限。模型的圖文輸入與端點格式已對照 [NVIDIA 模型文件](https://build.nvidia.com/z-ai/glm-5-3-flash/modelcard) 與 [API 文件](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash-infer)。
- 實際送出一張 1200×920 合成英文銘牌，HTTP 200，經 Upload → Worker → 前處理 → NIM → Normalize → Rule Validation，最終為 `SUCCEEDED`。
- 本次模型呼叫 74.87 秒，完整處理 74.92 秒；單次結果不能代表平均延遲或現場準確率。
- 六核心欄位 6/6 相符；全部 12 個有印出的欄位值與單位相符，其他 7 個欄位保持 null。
- 原始回覆為有效 JSON，不需語法修復，`finish_reason=stop`，沒有輸出截斷。API 回報輸入 2575、輸出 973、合計 3548 tokens；未提供固定模型版本識別。
- 序號 `E015283` 正確保留；規則提示易混字元，未自動修改序號。沒有建立人工 Ground Truth，也未寫入正式工作或資料集。
- Provider／Schema 相關 24 項測試及修改後測試腳本的 Ruff 檢查通過；API 金鑰沒有寫入驗證 JSON。
- 測試圖、原始回覆、結果及逐欄檢查摘要保存在 `data/verification/c0994d1a-56a3-4232-b56e-fbc0a3764259/`，Git 排除。
- 確認沒有排隊或辨識中的工作後，重啟 Web／Worker 載入新設定。Port 50003 健康檢查、登入及模型設定讀取通過，`nvidia` 顯示已設定 `z-ai/glm-5.3-flash`；預設仍為 `.env` 原有的 Ollama。

需要重新測試時執行下列命令。此命令會依指定 profile 真正呼叫模型服務，使用隔離的暫存資料庫；預設 profile 仍為 Ollama。

```sh
uv run python scripts/live_smoke.py --profile nvidia
```

## 2026-09-28 照片校正介面與 NAS 部署

- NIM 已設為本機與 NAS 預設 Provider。新介面完成照片預設展開、照片上方清晰文字摘要、點選定位／聚焦人工欄位、草稿同步及未儲存提示；原本人工確認與分享流程保留。
- 顯示辨識處理、模型回應、排隊、總耗時及輸入／輸出／總 token。既有 Observation 可回填用量，未知不當 0；沒有新增資料庫欄位或改寫 AI 結果。
- HTTP 402／明確 quota 代碼與一般 429 分開處理。額度不足、限流提示使用模擬回覆測試，沒有故意耗盡帳戶額度。
- 78 項 Python、27 項前端測試通過；Ruff、JavaScript 語法與 diff 檢查通過。
- 本地 390×844 手機尺寸與桌面瀏覽器完成照片展開、點選跳轉、輸入同步、確認保存、原有分享區、辨識等待計時、完成自動切換、額度與限流提示驗證。無瀏覽器 console error；測試使用隔離合成資料，不寫入正式工作。
- 先於本機實際 NIM 辨識成功，模型呼叫 77.67 秒；回報輸入 2575、輸出 983、合計 3558 tokens。結果位於 `data/verification/45c79b19-d146-44d2-a3da-63e2c4fa5213/`。
- NAS：Synology DS720+，獨立 Python 3.12.13／uv 0.11.20，release `20260928-nim-review-v1`。本地驗證後才推送 NAS；服務以受鎖保護的 supervisor 監督 Web／Worker，SSH 結束後仍在運作。
- 搬移 11 筆工作、13 次辨識、12 筆原始模型觀測、9 個人工確認版本與 171 筆欄位標註。儲存路徑交易式重定位，所有原圖雜湊、處理圖下載、SQLite 完整性及登入均通過。
- NAS 真實 NIM 呼叫成功，模型回應 72.91 秒、含前處理 73.08 秒；輸入 2575、輸出 983、合計 3558 tokens。12 個印出欄位皆相符、7 個未印欄位保持 null，正常 `finish_reason=stop`。這是單次合成卡測試，不代表現場準確率或平均效能。
- NAS 該次合成測試位於 `current/data/verification/94f01a76-acf0-49b9-8f76-357d32a39de3/`；沒有建立正式工作或 Ground Truth。本機部署摘要位於 `data/verification/deploy-20260928/`，Git 排除。
- NAS 主機內的 Port 50003 已驗證；外部 `home-taichung.myds.me:50003` 連線尚未通過。未修改路由器或新增 DSM 開機排程，限制與處理方式見 [NAS 部署](nas-deployment.md)。

## 2026-09-28 三欄位候選版與展示抬頭

- Mac mini 的正式 Web／Worker 已停止，Port 50003 無本專案監聽程序；本地測試使用隔離資料與暫時服務。
- 新工作預設使用 `nameplate_identity_v002`，只辨識室外機型號、室內機型號與序號。Schema、人工確認、分享及資料集範圍一併縮減；舊版 Prompt、19 欄歷史資料與人工確認版本保留。
- 83 項 Python、28 項前端測試通過；Ruff、JavaScript 語法與 diff 檢查通過。測試包含舊／新／舊三次辨識的修訂保存、失敗後人工確認、三欄資料集匯出及跨版本共同欄位 Benchmark 比較。
- 本地瀏覽器驗證新工作只有三個人工欄位、照片預設展開、點選序號聚焦正確欄位、修正後儲存與三欄分享文字；舊工作仍顯示 19 欄。未發現 console error。這些 UI 資料為隔離合成 fixture，未寫入正式資料庫。
- 真實 NIM 使用相同 1200×920 合成英文測試卡，三欄皆 Exact Match，模型回應 34.11 秒、總處理 34.14 秒；輸入 1,891、輸出 182、總共 2,073 tokens，`finish_reason=stop`。結果保存於 `data/verification/ad82646e-666d-4f9e-85e2-9a0e6729be14/`，Git 排除。
- 先前同一 Mac 的 19 欄測試為 77.67 秒、3,558 tokens。本次結果支持繼續評估精簡欄位，但兩者各只有一次、測試時間不同，不代表平均加速倍數、現場準確率或 95% KPI 達標。
- 依使用者要求，NAS 先只更新展示抬頭。正式版本為 `20260928-branding-v2`，主標題「陳憲隆自製 大金空調銘牌辨識」、副標題「AI 智慧影像辨識」。僅更新兩個模板及首頁標題；NAS 的 19 欄辨識流程與資料設定未更換。
- NAS 外部 DDNS 的 `/healthz`、登入頁、前端資源均已通過；新抬頭已在外部瀏覽器及 390×844 畫面核對。登入後的後端設定維持 NIM。使用者已設定路由轉發與 DSM 開機排程，重開機恢復仍未實測。
- 三欄候選版尚未部署 NAS。先完成本地驗收，再切換 release；目前 NAS 持續運作並保留舊 release 供回復。

## 2026-09-28 真實照片與相容性修正

2026-09-28 另抽取使用者指定資料夾中的三張真實照片進行本地開發驗證：完整圖兩次成功回覆、一次在 180 秒逾時；其中一次成功回覆仍有型號重複字母錯誤。補做一次局部重讀及一次低思考量實驗，結果見 [實照速度紀錄](recognition-speed.md)。低思考量雖完成回覆，兩個型號仍有錯字，沒有套用為預設，也沒有宣稱通過準確率驗收。

- 發現手機 MPO 多影像 JPEG 被拒絕，已修正為保留完整原始 bytes、僅以主影像作推論並校正 EXIF 方向。新前處理版本 `image_v002`，舊快照保留。
- 新增可選 `NVIDIA_REASONING_EFFORT` 及逐 profile 設定；空白維持原請求方式，錯誤值在網路呼叫前拒絕。
- 更新後 96 項 Python、既有 28 項前端測試通過，Ruff／diff／JavaScript 語法檢查通過。
- 真實照片、推論圖與裁切皆僅在專案外的系統暫存目錄處理，完成後已清除；沒有加入專案、GitHub、正式工作或 Ground Truth Dataset。保留的測試結果 JSON 也位於專案外。
- NAS 仍為 `20260928-branding-v2`，這次修正與實照實驗未部署 NAS；Mac 正式背景服務持續停止。

## 2026-09-28 手機驗收後部署 NAS 三欄版本

- 使用者完成 Mac 手機測試並同意發布；台中 NAS 已切至 `20260928-identity-e4a62f9`，程式 commit `e4a62f91a773bc4bd74e3dea36819bda6067d40a`。版本來自 Git archive，不含金鑰、Mac 資料庫、測試照片或本機 Python 環境。
- 使用 NAS 的獨立 Python 3.12 環境與既有鎖定依賴；Pillow 12.3.0、pillow-heif 1.8.0 匯入成功。本次沒有資料庫 migration。預設維持 NIM `z-ai/glm-5.3-flash`，Prompt 改為 `nameplate_identity_v002`，未設定低思考量。
- 停止服務後以 SQLite backup API 保存一致性資料庫，連同原圖、處理圖、資料集及設定備份至 `/volume1/homes/edward61221/nameplate/backups/20260928-identity-e4a62f9-retry1/`。沒有把 Mac 新資料覆蓋到 NAS。
- 所有既有資料列均核對不變：12 筆工作、14 次辨識、9 版人工確認、171 筆欄位標註、13 筆模型觀測。SQLite 完整性通過；透過登入後 API 核對 12 張原圖 SHA-256、9 版既有分享文字，以及所有舊 Attempt 的 19 欄範圍。
- 新服務 `/api/bootstrap` 的一般辨識範圍確為室外機型號、室內機型號、序號，歷史欄位目錄仍有 19 欄。從 Mac 經外部 DDNS 驗證健康檢查、登入頁、品牌文字，5 個前端檔案雜湊均符合已驗收程式；SSH 中斷後 Web／Worker 仍運作。
- 使用 NAS 既有的一張已人工確認照片，在專案外暫存資料庫執行新三欄流程，實際 NIM 回應成功。模型耗時 79.67 秒，含前處理 80.02 秒；輸入 2,592、輸出 524、總計 3,116 tokens。僅驗證新環境的推論、三欄範圍、耗時與用量紀錄，沒有建立正式工作或新 Ground Truth，也不代表平均速度或準確率。暫存照片與資料庫完成後移除。
- 首次切換因管理行程殘留舊 Prompt 環境變數而未通過三欄檢查，已自動恢復舊服務；清除繼承設定後再次切換並完成上述檢查。已有三欄資料後的回復必須考量舊分享程式不相容，見 [部署與回復流程](nas-deployment.md)。
- Mac 測試服務維持開啟。NAS 的 DSM 開機任務由使用者設定，本次未重開 NAS，實際重開機恢復仍待驗證。

## 2026-09-28 兩行 LINE 分享與 Gemini（本地，尚未部署 NAS）

- 分享文字對新三欄及舊 19 欄確認版本皆僅輸出人工確認的室外機型號、換行、序號；缺值保留空行。不附標題、室內機、欄位標籤、單位或頁尾。原圖分享與只有已確認版本可分享的限制保留；沒有改寫資料庫中的 AI 或人工答案。
- 新增原生 Gemini `generateContent` Provider，設定金鑰／模型後可由前端模型選單及 Benchmark 使用。NIM 仍為預設，兩個雲端 Provider 共用一個工作名額。金鑰由各自設定取得，僅在 HTTP header 傳送，不進設定快照、前端或 Git。模型實際版本與 token（含可取得的思考 token）存入既有觀測資料鏈。
- HTTP 200 的 JSON 物件若候選內容異常、拒答或達到輸出上限，先保存原始物件、耗時及可取得的 token，再標記失敗；不把截斷內容當成成功。非 JSON／非物件回覆沿用共用 HTTP 層的格式錯誤處理，不宣稱該原始位元組已保存。
- 167 項 Python 測試通過（12.93 秒），29 項前端測試通過；Ruff、JavaScript 語法與 diff 檢查通過。新增涵蓋供應商獨立金鑰、Gemini HTTP 格式／拒答／截斷／用量、雲端併發限制、失敗後人工確認、精確兩行分享及原圖檔案保留。
- 從使用者提供的照片資料夾讀取一張實照 `IMG_4632.jpeg`，在專案外隔離暫存環境測試。首次 HTTP 503／UNAVAILABLE，約 12.49 秒，沒有 token 回報；完成離線檢查後明確再試一次，未加入自動重試機制。
- 第二次 HTTP 200，模型別名 `gemini-flash-latest`，實際版本 `gemini-3.8-flash`，Prompt `nameplate_identity_v002`。模型回應 8.95 秒、含前處理 8.99 秒；輸入 1,302、輸出 556、合計 1,858 tokens。三個欄位皆有值。這是單張流程驗證，並非新的人工 Ground Truth、平均延遲或正式準確率；首次失敗用量仍未知，不能算成零。
- 測試照片、推論圖與測試資料庫只在專案外暫存，結束後清除，沒有加入專案、正式資料庫或 Git。金鑰只設定在被 Git 排除且權限 600 的本地 `.env`。Mac 正式背景服務仍關閉；NAS 維持前次 `20260928-identity-e4a62f9`，尚未發布本次修改。

## 2026-09-28 Gemini 預設與金鑰同步發布

- 使用者接受兩行 LINE 分享與 Gemini 版本後授權部署。NAS `current` 已切至 `releases/20260928-gemini-2099f39`，程式 commit `2099f394692646a3e3b040553d90397715889848`。未修改資料模型、migration 或鎖定依賴，採新 release 的獨立 Python 環境。
- NAS 與 Mac 的私人 `.env` 均已改為 `VISION_PROVIDER=gemini`、`GEMINI_MODEL=gemini-flash-latest`，同步使用本次新金鑰。直接比較兩端設定確認一致；金鑰未顯示於輸出或加入 Git，`.env` 權限均為 600，NAS 暫存傳送設定檔已刪除。Mac 背景服務保持停止。
- 新金鑰在 Mac 與 NAS 都通過 Google 模型資訊 API 的 HTTP 200 驗證。但本次 NAS 隔離實照辨識依序三次回傳 HTTP 503，耗時約 7.23、1.81、4.40 秒，第三次確認供應商訊息為模型需求量過高。三次均無 token 回報，不能當成零；沒有宣稱新金鑰的實照辨識成功，也沒有沿用上一節舊金鑰的成功成績。
- 依使用者指定部署 Gemini 預設，NIM 保留為手動可選模型，不自動切換或加入無限重試。正式服務實際 `/api/bootstrap` 已核對預設 Gemini、模型名稱、已配置狀態、三個辨識欄位與 19 欄歷史目錄；NIM 也仍為已配置。
- 切換前備份 NAS 共享設定、SQLite 一致性快照、原圖、處理圖與資料集，位置 `/volume1/homes/edward61221/nameplate/backups/20260928-gemini-2099f39/`。所有既有資料列保留：13 筆工作、15 次辨識、10 版人工確認、174 筆欄位標註、14 筆模型觀測；SQLite 完整性正常，13 張原圖透過登入後 API 取回並核對 SHA-256。
- 10 個既有人工確認版本的分享 API 均核對為「人工確認室外機型號 + 換行 + 人工確認序號」，恰好兩行；資料庫中的人工答案與原始 AI 資料未改寫，各次辨識的 3／19 欄範圍仍依快照保留。
- 外部 DDNS `/healthz`、登入頁及品牌文字檢查通過；5 個前端靜態檔案與已接受程式的雜湊一致。SSH 中斷後 Web／Worker 持續運作。測試使用 NAS 既有照片及專案外暫存資料庫，未新增正式工作、確認或 Ground Truth；暫存照片已清除。
- 實際影像辨識仍需在 Google 高需求狀態解除後驗證。這是供應商可用性限制；需要立即辨識時可在模型選單選 NIM。NAS 重開機恢復本次未測。

## 待持續現場驗證

真實照片的準確率／人工處理時間、iPhone Safari 與 Android Chrome 原生拍照／分享、LINE 公司官方帳號收件流程、NVIDIA NIM 的現場照片表現與持續使用穩定性、NAS 重開機恢復。

README 中的自動測試可隨時重跑；測試 fixtures 與 browser fixture 均為合成資料。
