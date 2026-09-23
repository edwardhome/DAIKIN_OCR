# Benchmark 與回歸規則 v001

核心欄位為 outdoor_model、indoor_model、serial_number、refrigerant、refrigerant_charge、manufacture_year。

## 評分

- Field Accuracy：KNOWN 欄位中，標準化 prediction value 與 unit 完全相同的數量／已知答案數。型號與序號為 exact match，不替換 0/O、1/I 等字元，不計字元近似分數。
- 95% 主目標：六核心欄位已知值的合併逐欄正確率。沒有已知答案時回傳 null，不回傳 100%。
- Exact Match Accuracy：六欄皆可評分（KNOWN 或 NOT_PRESENT）的照片中，六欄全部正確的比例。另行呈現，不和逐欄正確率混稱。
- Absence Accuracy：NOT_PRESENT 的正確留空率，與已知值分開。UNREADABLE／UNREVIEWED 不作有答案的評分。
- Benchmark Correction Rate：可評分欄位 prediction 與固定答案不同的比例，是基準差異率；現場 Dashboard 則以實際人工修改計算。
- Null Rate：成功輸出中六核心欄位 null 的比例。失敗工作另外列出 failure_count，但其已知欄位仍計入主準確率分母，不能藉 timeout 排除難例。
- Hallucination Rate：經人工標記 UNSUPPORTED 的非空 prediction／已人工標記 SUPPORTED 或 UNSUPPORTED 的非空 prediction。沒有審查時為 null。一般字元錯誤或與答案不同不自動叫 hallucination。人工審查變更保存 history。
- Average Latency：完整 Provider 呼叫毫秒，包含可能的模型載入，不含排隊／metadata 查詢。另記 queue_ms 與 processing_ms。雲端與本地冷啟動條件應在比較時留意。

所有比例附 numerator／denominator。難度報表分 EASY、MEDIUM、HARD、UNLABELED；難例標記不會自動改寫人工難度。

## 固定資料與前後比較

每次實驗鎖定 dataset version/hash、模型／可取得版本、Prompt 內容/hash、schema、影像處理參數、規則、decision version、inactive threshold 設定、程式碼 hash。多個 target 使用同一份原圖、Prompt、Schema、前處理；推論圖 hash 可追查。

Before/After 必須同 dataset ID 與 evaluation_version，且兩次已完成。各核心欄位的已知值率獨立比較；下降超過 REGRESSION_MAX_DROP（預設 0）列為 REGRESSION。失敗數增加也列退步。任一核心欄位樣本小於 REGRESSION_MIN_KNOWN_SAMPLES（預設 5）時，無退步也只能 INSUFFICIENT_DATA，不會 PASS。通過報告也不會自動改部署設定。

## 第一批資料

尚無實際照片。正常、斜拍、遠距離、小字、髒污、龜裂、R22、R32 均需涵蓋；由人工標註難度及情境。原本純人工處理時間應由同一批操作者、同一批樣本另行計時作為基準，與系統平均人工確認時間比較。以不同資料批次混用時間無法證明節省幅度。

上傳 Benchmark 來源時選 BENCHMARK_SOURCE，與 PRODUCTION 統計分開。先在調整集修改 prompt/rule，再用固定 HOLDOUT 驗收；同設備群組不能跨分組。這版只能辨認同圖片雜湊與人工填入的設備群組，無自動相似圖片／設備偵測。

Prompt 變更新增 nameplate_v002，保留 v001；Rule、Normalizer、Preprocessor、Decision 修改也須升版本。更新後重新執行同一固定集，檢查逐欄、難度、失敗率及人工修正率。測試用合成 fixture 不得宣稱為現場準確率。
