# NIM 用量、免費存取與錯誤提示

查核日期：2026-09-28。適用於本專案使用的 NVIDIA 託管 API，非自行架設 GPU 的授權或算力額度。

## 免費規則

NVIDIA 官方人員於 2025 年說明，build.nvidia.com 已移除舊 credits 制度。可用請求速率會依模型與同時使用情況變化，帳戶實際限制請登入 NVIDIA 網站右上角查看。網路上「初始 1,000 credits、再申請 4,000」是舊資訊，不作為目前剩餘額度的計算依據。[NVIDIA 官方說明](https://forums.developer.nvidia.com/t/cannot-find-the-amount-of-credits-left-on-nim-api/337051)

2026 年官方論壇再次說明，免費層速率限制受模型、使用情境與整體流量影響，不能透過論壇要求提高同一免費層的限制。因此本程式不寫死所有帳戶都是 40 RPM，也不以多把 Key 繞過限制。[2026 年官方公告](https://forums.developer.nvidia.com/t/api-rate-limit-increase-is-not-granted-by-requesting-it-here/368420)

目前 FAQ 說明 Developer Program 提供原型測試用的免費 NIM 端點存取；它不代表無限請求、正式營運 SLA 或免費自有 GPU。正式營運方案需另行確認。[NVIDIA FAQ](https://docs.api.nvidia.com/nim/docs/product)

## 系統顯示的數字

- 輸入 tokens：API 回報的 `prompt_tokens`，含模型所計入的圖文輸入。
- 輸出 tokens：API 回報的 `completion_tokens`。
- 總 tokens：API 的 `total_tokens`；若未提供總數但兩項有效，才以兩者相加。
- API 未提供或值無效時顯示「未提供」，不當作 0。
- 這些是該次辨識的用量，**不是帳戶剩餘額度或付費帳單**。目前沒有接入可核實的 NVIDIA 帳戶剩餘配額查詢。
- 原始回覆仍保留於後端；前端只取得標準化的數量，不取得 API Key 或原始模型回覆。

既有辨識只要保存過模型用量，也能顯示；沒有收到模型回覆的失敗請求不能估算或宣稱沒有消耗。Ollama 使用其回傳的輸入／輸出計數，同樣不是 NVIDIA 帳戶用量。

## 前端錯誤處理

| 回應 | 畫面提示與處理 |
| --- | --- |
| HTTP 402 或明確的不足額度代碼 | 額度不足／計費限制，請確認 NVIDIA 帳戶。可換已設定模型或人工填寫 |
| 一般 HTTP 429 | 暫時限流，稍後重試；不宣稱 token 已耗盡 |
| HTTP 401／403 | 驗證或權限問題，檢查後端 Key／帳戶設定 |
| 逾時／連線失敗 | 顯示原有錯誤，可重試或人工填寫 |

目前所選 GLM-5.3-Flash 的 API 文件列出 HTTP 402 Payment Required；因此保留明確額度錯誤的處理，但不以此推定所有免費帳戶都有固定 token 餘額。[模型 API 文件](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash-infer)

不會為了測試提示而故意耗盡使用者額度。相關錯誤用模擬 API 回覆驗證；真實連線測試僅確認實際辨識與用量欄位。
