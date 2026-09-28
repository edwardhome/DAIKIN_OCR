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

## 待現場驗收

真實照片的準確率／人工處理時間、iPhone Safari 與 Android Chrome 原生拍照／分享、LINE 公司官方帳號收件流程、NVIDIA NIM 的現場照片表現與持續使用穩定性、實際 DDNS 外部連線。

README 中的自動測試可隨時重跑；測試 fixtures 與 browser fixture 均為合成資料。
