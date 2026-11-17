# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend replay, phán quyết judge lưu sẵn trong CSV). Lớp dương là **FAIL**, vì việc của judge là tìm ra reply lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (exit 0) | **dùng**, chỉ làm metric báo cáo, không blocking |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** κ và R (exit 1) | **loại**, không dùng làm gate |

Ma trận nhầm lẫn (FAIL = dương):

| | tp | fp | fn | tn | specificity | Tỉ lệ FAIL quan sát → hiệu chỉnh Rogan-Gladen |
|---|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 66/70 = 0.943 | 0.28 → 0.30 |
| helpful | 9 | 0 | 21 | 70 | 70/70 = 1.000 | 0.09 → 0.30 |

Với helpful, judge chỉ báo 9% reply lỗi trong khi người chấm thấy 30%. Judge bỏ sót hơn hai phần ba số lỗi thật. Sau hiệu chỉnh Rogan-Gladen con số khớp lại 0.30, nhưng **hiệu chỉnh chỉ sửa được tỉ lệ tổng, không chỉ ra được reply nào sai**. Gate cần biết đúng trial nào fail, nên con số đã hiệu chỉnh vẫn không cứu được judge này.

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em", thêm "nha" là quá suồng sã với khách đang khiếu nại. **Rubric:** thêm luật xưng hô cố định "LogiX – anh/chị"; xưng "em/bạn" hoặc tiểu từ "nha/nhé" ⇒ FAIL. Thêm ví dụ âm này vào few-shot. |
| 2 | H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ bám vào từ lịch sự ("Dạ, vui lòng"), bỏ qua câu mang giọng ra lệnh. **Rubric:** chấm cả câu chứ không đếm từ khóa; câu cấm/đuổi khách ("không cần nhắn thêm") ⇒ FAIL dù có "Dạ". |
| 3 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". **Rubric:** xin lỗi không bắt buộc khi reply báo kết quả có lợi cho khách; ngắn mà đủ ý vẫn PASS. Bỏ "có lời xin lỗi" khỏi tiêu chí tone. |
| 4 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | Người | Style guide CS của LogiX cho phép từ "refund". **Rubric:** ghi rõ danh sách thuật ngữ tiếng Anh được phép (refund, ship, voucher). |
| 5 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge** | Ghi chú của người chấm cho biết họ đọc nhầm ticket. **Hành động:** sửa nhãn người trong bộ calibration lần sau (không sửa CSV public đang dùng làm tham chiếu test), và bắt buộc có người thứ hai duyệt mỗi nhãn đã gán. Nếu sửa, P của tone tăng lên 25/28 = 0.893. |
| 6 | H-063 "Dạ, LogiX đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người | Reply hứa một khoản hệ thống không ghi. Đây là lỗi **nội dung** (gần FM-08), không phải lỗi tone. **Rubric:** tách ra khỏi tone; lời hứa tiền chấm bằng code so với ledger. |
| 7 | H-070 "… cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người | **Rubric:** cấm emoji trong ngữ cảnh khiếu nại. |
| 8 | H-094 "Da, LogiX da hoan 40.000đ … xin loi vi su bat tien." | PASS | FAIL | Người | Mất dấu tiếng Việt. **Rubric:** reply không dấu ⇒ FAIL; có thể kiểm bằng code (tỉ lệ ký tự có dấu) trước khi gọi judge. |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ …" | FAIL | PASS | Hòa | Lỗi gõ lặp từ, người chấm cho qua. **Rubric:** ghi rõ lỗi gõ nhỏ không làm sai nghĩa ⇒ PASS, để hai bên chấm nhất quán. |
| 10 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | Người | Judge chỉ thấy reply, không thấy ledger, nên **không thể** biết số tiền sai. 18/21 lỗi judge helpful bỏ sót đều thuộc loại "sai tiền" (18/18 case sai tiền đều bị judge cho PASS). Không sửa được bằng rubric. **Hành động:** chuyển kiểm tra số tiền sang code (metric FM-08, M3). |
| 11 | HL-016 / HL-043 / HL-090 (xin lỗi dài lặp lại + số tiền sai) | PASS | FAIL | Người | Judge bị **verbosity/politeness bias**: reply càng dài, càng nhiều lời xin lỗi thì càng dễ được PASS. **Rubric:** chấm nội dung trước, tone sau; lặp câu xin lỗi ⇒ trừ điểm. |
| 12 | HL-047 / HL-091 / HL-097 "Ok bạn, đơn O-xxx xử lý rồi nhé." | PASS | FAIL | Người | Sai xưng hô và không nói kết quả cụ thể. Đây vốn là việc của judge tone, và judge tone đã có luật cho trường hợp này (case 1). |

## Kết luận

- **Judge tone_ok được dùng**, chỉ để báo cáo, không blocking. Judge này đạt cả ba sàn (κ 0.757 ≥ 0.6, P 0.857 ≥ 0.8, R 0.80 ≥ 0.7). Lỗi còn lại chủ yếu là 6 fn: judge cho qua giọng suồng sã/ra lệnh/emoji/không dấu (case 1, 2, 7, 8). Cả 6 đều sửa được bằng rubric và few-shot ở trên. Không cho judge này làm gate cứng, vì κ chỉ được đo trên 100 dòng replay.
- **Judge helpful bị loại khỏi gate.** Precision 1.0 trông đẹp, nhưng recall chỉ 0.30 (21 fn) và κ = 0.375 < 0.6. Nguyên nhân chính là judge không có ledger trong ngữ cảnh: 18/21 lỗi bỏ sót là reply báo sai số tiền, tức đúng FM-08. Nếu dùng judge này làm gate, agent báo sai tiền nhưng xin lỗi dài dòng vẫn sẽ được merge. Phần "helpful" có thể kiểm bằng code thì chuyển sang code: so số tiền trong reply với ledger (metric M3), status so với label. Phần còn lại (xưng hô, đúng trọng tâm) gộp vào rubric tone.
- **Tiền và approval không bao giờ chấm bằng judge**, kể cả khi judge đã đạt sàn: chúng chấm bằng code đọc ledger.
- **Rủi ro còn lại:**
  - Judge chỉ được kiểm trên dữ liệu replay đã công khai. Rubric đã sửa ở trên lại được viết sau khi nhìn chính các case này, nên số liệu nếu đo lại trên cùng bộ sẽ lạc quan hơn thực tế. Cần bộ nhãn người mới (held-out) để có số liệu thật.
  - n = 100 còn nhỏ: chỉ cần 2–3 nhãn đổi là κ dịch vài phần trăm.
  - Đã phát hiện ít nhất một nhãn người sai (H-081), nên nhãn người cũng cần được duyệt chéo.
