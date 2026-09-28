# 驗證紀錄

本文件記錄軟體驗證，不代表現場辨識準確率。

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

## 待現場驗收

真實照片的準確率／人工處理時間、iPhone Safari 與 Android Chrome 原生拍照／分享、LINE 公司官方帳號收件流程、NVIDIA NIM 的現場照片表現與持續使用穩定性、NAS 重開機恢復。

README 中的自動測試可隨時重跑；測試 fixtures 與 browser fixture 均為合成資料。
