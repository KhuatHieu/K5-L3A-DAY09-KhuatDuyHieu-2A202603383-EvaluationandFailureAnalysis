# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

## Case: hoàn thiếu do trừ hai lần (FM-05)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, run ID `R-seeded_regression-C-014-s11` |
| Triệu chứng | Lab 8 grader FAIL `proposal_mismatch`. Reply nói "đã hoàn 120.000đ cho đơn O-515", nhưng ledger ghi **90.000**, label 120.000. Khách bị hoàn thiếu 30.000 trong khi reply nói đúng số khách mong đợi |
| Bước sai đầu tiên | Event 5 `proposal {"amount_vnd": 120000}` |
| Vì sao là bước *đầu tiên* | Event 2 `investigator` đọc đúng O-515 (trễ 5 ngày, `damage_verified: true`). Event 3 `quote` 150.000 đúng luật (max của SHIP-LATE-03 30.000 và DMG-04 150.000). Event 4 `refund_history {refunded_vnd: 30000}` là bước đọc hợp lệ. Tới event 5 agent mới tự trừ 30.000 khỏi quote rồi gửi 120.000 cho host. Host đã có trần theo đơn nên trừ thêm 30.000 một lần nữa ⇒ ledger 90.000 |
| Failure mode | FM-05 `pre_deducted` (kéo theo FM-08: reply báo 120.000 trong khi ledger 90.000) |
| Đối chứng | `fixed C-014@11`: không có event `refund_history` / `proposal`. Quote 150.000 được truyền nguyên cho host, ledger 120.000, reply 120.000, Lab 8 grader PASS |
| Regression test | Item `E-014` trong eval set v1 có `provenance.from_trace = R-seeded_regression-C-014-s11`, `failure_modes = [FM-04, FM-05, FM-08]`. Grader bắt được: `TrialPass` (`proposal_mismatch`), đã thấy FAIL trên `seeded_regression` và PASS trên `fixed` ở cả 5 seed. `RefundAmountCorrect` (M3, ledger 90.000 ≠ 120.000) sẽ bắt thêm ở mức outcome |
| Chưa chắc chắn | Trace chỉ cho thấy agent trừ trước khi gọi host, không cho biết *vì sao* (MockLLM không có lập luận). Trên LLM thật, nguyên nhân có thể là prompt mô tả trần theo đơn chưa rõ, cần kiểm lại bằng trace có reasoning. Với C-013 (đơn đã hoàn đủ), cùng lỗi cho ra `denied` đúng status nhưng `proposal_amount` 0 thay vì 35.000. Lỗi này chỉ lộ qua `proposal_amount`, ledger không đổi |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai (case này: reply 120.000, ledger 90.000).
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
