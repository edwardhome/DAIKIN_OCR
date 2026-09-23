# 驗證紀錄

本文件記錄軟體驗證，不代表現場辨識準確率。

## 已實測

- macOS arm64、Python 3.12.13、uv 0.11.20；依賴已寫入 uv.lock。
- 39 項自動化測試全部通過；Ruff 與 JavaScript 語法檢查通過。
- SQLite 初始 migration 成功，Alembic metadata 差異檢查通過。
- 桌面與 390×844 手機尺寸瀏覽器：首頁、照片對照、修正室外機型號、儲存、已確認分享文字、私有 dataset 建立可操作；未發現 console error。
- Qwen3-VL 8B instruct 已下載並完成一次真實 Ollama 推論。
- 模型 digest：0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319。
- 合成英文測試卡 1200×920，成功回傳 JSON 並經 Normalize／Rule Validation；模型呼叫約 55.0 秒，包含該次載入條件，不能代表平均延遲。
- 合成圖未印出的欄位保持 null。該次沒有建立 Human Ground Truth，沒有納入現場資料庫或固定 Benchmark。
- 合成圖與原始回覆留在 data/verification/0e689659-f33a-4191-9489-14258bb310f9（Git 排除）。

## 待現場驗收

真實照片的準確率／人工處理時間、iPhone Safari 與 Android Chrome 原生拍照／分享、LINE 公司官方帳號收件流程、NVIDIA NIM 真實憑證與所選模型、實際 DDNS 外部連線。

README 中的自動測試可隨時重跑；測試 fixtures 與 browser fixture 均為合成資料。
