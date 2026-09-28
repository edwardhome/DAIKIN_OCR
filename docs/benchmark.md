# Benchmark 與回歸規則

本機三欄候選版使用 `nameplate_identity_v002`：`outdoor_model`、`indoor_model`、`serial_number`，三欄都是核心欄位。歷史 `nameplate_v001` 保留 19 欄，其中六個核心欄位另含 `refrigerant`、`refrigerant_charge`、`manufacture_year`。原 Prompt、既有 Attempt、人工答案及固定資料集不因改版而覆寫。

截至 2026-09-28，NAS 仍是 `20260928-branding-v2` 名稱修補版，未部署三欄功能；三欄版須先完成使用者本機驗收。速度的單次實測與後續實驗見 [辨識速度改善](recognition-speed.md)。

## 欄位範圍

每次辨識保存自己的欄位範圍。報表從辨識範圍與固定人工答案中取共同欄位，列出 `evaluated_fields`、`core_fields` 與 `excluded_fields`；同一報表使用一致的欄位分母，難度分層沿用相同範圍。

三欄結果配上歷史 19 欄資料集時，只評分共同的三個識別欄位，不把其餘 16 欄當成缺漏預測。若資料集混合不同範圍，報表也只使用所有相關樣本共有的欄位，應先查看排除欄位，再解讀總分。

## 評分

- Field Accuracy：KNOWN 欄位中，標準化 prediction value 與 unit 完全相同的數量／已知答案數。型號與序號為 exact match，不替換 0/O、1/I 等字元，不計字元近似分數。
- 95% 主目標：本次評分範圍內核心欄位已知值的合併逐欄正確率。沒有已知答案時回傳 null，不回傳 100%。新版本通常為三核心，歷史完整範圍為六核心，報告必須寫清楚欄位。
- Exact Match Accuracy：本次所有核心欄位皆可評分（KNOWN 或 NOT_PRESENT）的照片中，全部核心欄位正確的比例。另行呈現，不和逐欄正確率混稱，也不直接比較三欄與六欄全對率。
- Absence Accuracy：NOT_PRESENT 的正確留空率，與已知值分開。UNREADABLE／UNREVIEWED 不作有答案的評分。
- Benchmark Correction Rate：評分範圍內可評分欄位 prediction 與固定答案不同的比例，是基準差異率；現場 Dashboard 則以實際人工修改計算。
- Null Rate：成功輸出中本次核心欄位 null 的比例。失敗工作另外列出 failure_count，但其適用的已知欄位仍計入主準確率分母，不能藉 timeout 排除難例。
- Hallucination Rate：經人工標記 UNSUPPORTED 的非空 prediction／已人工標記 SUPPORTED 或 UNSUPPORTED 的非空 prediction，僅計本次評分欄位。沒有審查時為 null。一般字元錯誤或與答案不同不自動叫 hallucination。人工審查變更保存 history。
- Average Latency：完整 Provider 呼叫毫秒，包含可能的模型載入，不含排隊／metadata 查詢。另記 queue_ms 與 processing_ms。雲端與本地冷啟動條件應在比較時留意。

所有比例附 numerator／denominator。難度報表分 EASY、MEDIUM、HARD、UNLABELED；難例標記不會自動改寫人工難度。

## 固定資料與前後比較

每次實驗鎖定 dataset version/hash、模型／可取得版本、Prompt 內容/hash、schema、欄位範圍、影像處理參數、規則、decision version、inactive threshold 設定、程式碼 hash。同次實驗的多個 target 使用同一份原圖、Prompt、Schema、前處理；推論圖 hash 可追查。

Before/After 必須同 dataset ID 與 evaluation_version，且兩次已完成。範圍不同時，取兩次共同的辨識及人工標註欄位，重新計算兩邊指標。比較結果列出 `comparison_fields`、`core_fields`、`scope_changed`、`excluded_fields` 及重算的 `before_metrics`／`after_metrics`；沒有共同核心欄位時拒絕比較。這可以檢查三欄改版在識別任務上的進退，不能證明已排除的冷媒或其他欄位也沒有退步。

各共同核心欄位的已知值正確率獨立比較；下降超過 REGRESSION_MAX_DROP（預設 0）列為 REGRESSION。失敗數增加也列退步。任一共同核心欄位樣本小於 REGRESSION_MIN_KNOWN_SAMPLES（預設 5）時，無退步也只能 INSUFFICIENT_DATA，不會 PASS。通過報告也不會自動改部署設定。

## 第一批資料

現場品質驗收仍需具代表性的人工標註照片，涵蓋正常、斜拍、遠距離、小字、髒污、龜裂、R22、R32，並標記難度及情境。原本純人工處理時間應由同一批操作者、同一批樣本另行計時作為基準，與系統平均人工確認時間比較。以不同資料批次混用時間無法證明節省幅度。

上傳 Benchmark 來源時選 BENCHMARK_SOURCE，與 PRODUCTION 統計分開。先在調整集修改 prompt/rule，再用固定 HOLDOUT 驗收；同設備群組不能跨分組。這版只能辨認同圖片雜湊與人工填入的設備群組，無自動相似圖片／設備偵測。

三欄 Prompt 新增為 `nameplate_identity_v002`，保留原 `nameplate_v001`；Rule、Normalizer、Preprocessor、Decision 修改也須升版本。匯出資料保存每筆欄位範圍；`training_ready.jsonl` 只納入 DEVELOPMENT 中該樣本全部欄位可評分的資料，新三欄與歷史 19 欄不混稱完整標註。更新後重新執行同一固定集，檢查逐欄、難度、失敗率及人工修正率。測試用合成 fixture 不得宣稱為現場準確率。
