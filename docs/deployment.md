# macOS 部署：HTTP / 50003

台中 NAS 的原生背景服務、資料搬遷與 DSM 開機排程，請見 [NAS 部署文件](nas-deployment.md)。目前 `.env.example` 預設 NVIDIA NIM，使用本地 Ollama 時需明確設定 `VISION_PROVIDER=ollama`。

## 啟動與網路

先依 README 安裝依賴、填 `.env`、初始化資料庫。`scripts/start.sh` 啟動一個 Web 與一個 Worker，Ctrl+C 結束兩者。也能分別執行 `uv run nameplate serve`、`uv run nameplate worker`。每次修改 `.env` 或 profiles 後重新啟動。

本機網址 `http://127.0.0.1:50003`。Tailscale 綁定該 Mac 的 100.x.x.x；DDNS／路由器轉發時設定 `APP_HOST=0.0.0.0`，並設定私人 ACCESS_PASSWORD、TRUSTED_HOSTS。外部綁定位址未設定至少 12 字元存取碼時，啟動會拒絕。

外部 DDNS 網址格式為 `http://你的網域:50003`。需由使用者提供實际網域，並確認社區與路由器皆將 TCP 50003 導向 Mac。程式不開啟／改動路由器，也不以 DNS 可解析就宣稱外部已可用。請用手機行動網路測試登入、上傳、確認、複製文字及 LINE 收件者。

原生分享與剪貼簿是否出現由瀏覽器能力決定。備援會選取文字，由使用者手動複製。分享成功只代表交給手機分享流程，無法證明公司官方帳號已收到。

## 存取與資料

不建立複雜帳號／RBAC。單一存取碼對全部技師共用，最多 8 次失敗登入／來源 IP／15 分鐘；目前單 Web process 的記憶體計數，重啟會清除。不要將此 PoC 當作完整身分稽核系統。

session 有效期 8 小時。存取碼修改並重啟後，舊 session 失效。SECRET_KEY 未設定時在 data/.session-secret 建立私人檔案。NVIDIA Key、存取碼與原始照片均不納入 Git。DEBUG_DATA 預設關閉。

服務只信任實際 TCP 來源，不信任使用者傳入的 X-Forwarded-For。若未來增加反向代理，仍須設定 ACCESS_PASSWORD，並另外檢查代理與來源辨識規則。

## 日常檢查

- `/healthz`：僅表示 Web 程序存活，不代表 Worker 或模型已就緒。
- 工作卡在 QUEUED：查看 Worker 是否啟動。
- MODEL_NOT_CONFIGURED：填入已安裝視覺模型的完整 tag。
- PROVIDER_UNAVAILABLE：確認 Ollama 服務與 OLLAMA_HOST。
- AI_TIMEOUT：比較圖片尺寸、模型大小、其他記憶體占用，再調整 timeout。
- AI_PARSE_FAILED：原始 observation 已保留，可開啟 DEBUG_DATA 調查。
- HTTP 400：檢查 TRUSTED_HOSTS 是否包含實際 IP／DDNS 名稱。
- 外部存取被拒：設定 ACCESS_PASSWORD 並重啟。

logs 只包含時間、job／attempt、provider、model、latency、成功／失敗代碼，不輸出 Authorization 或 Key。

## 備份與還原

PoC 採可驗證的停機備份。先停止 Web 與 Worker，完整備份 `data/`、`datasets/`、`.env`、`config/profiles.toml` 至私人磁碟。SQLite 的 database.sqlite3、若仍存在的 -wal/-shm 一起保留。原圖、處理圖、dataset manifest／images／ZIP 必須同批保存。

還原時先停機，回復同一專案絕對路徑與 DATA_DIR／DATASET_DIR 設定，再執行 `uv run nameplate init-db`，啟動後抽查一張原圖、一筆人工修改歷程與一個資料集下載。資料庫目前保存本機絕對儲存路徑，搬到不同根目錄前需遷移路徑欄位；不可直接刪掉舊目錄後假設自動找到照片。

不要以同一 SQLite 同時啟动多個 Worker，程序鎖會拒絕。備份檔也包含現場資訊與原始模型資料，預設 PRIVATE，無自動對外分享。

## 驗收邊界

自動測試涵蓋流程與資料保留；iPhone Safari、Android Chrome 的原生拍照／LINE／分享面板，需要實機完成。缺少現場照片時不填造 Ground Truth；缺少已安裝視覺模型或 NVIDIA Key 時不宣稱推論已驗證。
