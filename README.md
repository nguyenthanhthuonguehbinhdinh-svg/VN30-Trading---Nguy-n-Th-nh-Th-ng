# VN30 Quant Desk

Dashboard **miễn phí** theo dõi chiến lược Breakout + Sideway trên rổ **VN30**, giả lập vốn **100 triệu** với phí, thuế, lô 100 và T+2 như thị trường thật.

- **Chi phí: 0đ.** Dùng GitHub Actions (máy chạy code) và GitHub Pages (host web), cả hai đều miễn phí với repo public.
- **Tự cập nhật mỗi ngày giao dịch:**
  - **~14:17–14:35:** tính *tín hiệu dự kiến* bằng giá trong phiên. Dashboard hiện "Việc cần làm" để bạn kịp đặt **lệnh ATC** (14:30–14:45).
  - **~15:23:** *chốt sổ*. Lệnh giấy khớp đúng **giá đóng cửa (ATC)**, cập nhật NAV, danh mục và lịch sử.
- **Dữ liệu:** gọi thẳng API công khai, lần lượt **VCI (Vietcap) → KBS → VNDirect**, nên không phụ thuộc thư viện `vnstock`.

```
config.json              ← vốn, phí, thuế, tham số chiến lược, danh sách VN30 dự phòng
engine/                  ← Python: data.py (lấy giá) · indicators.py · core.py (luật + khớp lệnh) · run.py
docs/                    ← trang web (GitHub Pages): index.html, app.js, style.css, data/*.json
state/portfolio.json     ← SỔ LỆNH LIVE (nguồn sự thật, tự sinh ở lần chạy đầu)
.github/workflows/daily.yml
tests/test_rules.py      ← kiểm thử luật giao dịch
```

---

## Cài đặt (khoảng 10 phút, chỉ làm một lần)

1. **Tạo repo mới** trên GitHub, ví dụ `vn30-dashboard`, chọn **Public**. GitHub Pages miễn phí chỉ áp dụng cho repo public; repo private cần gói Pro.
2. **Đưa code lên repo.** Cách dễ nhất: trên trang repo bấm *Add file → Upload files*, kéo thả toàn bộ nội dung thư mục này vào rồi *Commit*.
   Lưu ý thư mục ẩn `.github/workflows/daily.yml` phải được upload. Nếu kéo thả không lấy được, hãy tạo file đó bằng *Add file → Create new file*, gõ đúng đường dẫn rồi dán nội dung vào.
   Nếu dùng git:
   ```bash
   git init && git add . && git commit -m "init" && git branch -M main
   git remote add origin https://github.com/<user>/vn30-dashboard.git && git push -u origin main
   ```
3. **Bật Pages:** *Settings → Pages → Build and deployment → Source:* chọn **GitHub Actions**.
4. **Cho phép workflow ghi dữ liệu:** *Settings → Actions → General → Workflow permissions:* chọn **Read and write permissions** → *Save*.
5. **Chạy lần đầu:** *Actions → Daily VN30 update → Run workflow*, chọn mode `close`.
   Khi chạy xong (khoảng 1–2 phút), web có địa chỉ: `https://<user>.github.io/vn30-dashboard/`

Lần chạy `close` đầu tiên tạo **sổ live** bắt đầu từ phiên gần nhất, với 100 triệu tiền mặt. Từ đó hệ thống tự chạy mỗi ngày từ thứ 2 đến thứ 6.
Tab **Backtest** hiển thị ngay kết quả cùng chiến lược từ `backtest_start` (mặc định 01/01/2022) để bạn có cái nhìn lịch sử trong lúc chờ sổ live tích luỹ.

> Trước khi chạy dữ liệu thật, trang đang hiển thị **dữ liệu mô phỏng** (có banner vàng) để bạn xem giao diện.

## Hằng ngày dùng thế nào

1. Khoảng **14:25–14:35**, mở dashboard. Ô **Việc cần làm** có nhãn *DỰ KIẾN* cho biết mã nào cần mua/bán, khối lượng và giá tham chiếu. Nếu bạn đi tiền thật song song, đặt lệnh **ATC** theo danh sách này.
2. Sau **15:30**, lệnh giấy đã khớp theo giá đóng cửa. Xem NAV, danh mục và lịch sử.
3. Tab **Tín hiệu VN30** hiển thị cả 30 mã với hành động MUA / BÁN / GIỮ / CHỜ, cùng hai mốc giá cho phiên tới:
   - **Mốc Breakout:** giá đóng cửa cần vượt để có tín hiệu Breakout.
   - **Mốc RSI≤30:** giá đóng cửa làm RSI(14) chạm 30.

   Bấm vào mã để xem biểu đồ nến kèm MA10, MA50, đỉnh 55 phiên, RSI và các mốc thoát lệnh.

## Cơ chế giả lập (giống thị trường VN)

| Hạng mục | Mặc định (sửa trong `config.json`) |
|---|---|
| Phí môi giới mua / bán | 0,15% / 0,15% (`fees.buy_fee`, `fees.sell_fee`). Đặt đúng mức CTCK của bạn |
| Thuế TNCN khi bán | 0,1% giá trị bán |
| Lô giao dịch | 100 cp (HOSE), làm tròn xuống |
| Thanh toán | T+2: mua phiên T, bán được từ phiên T+2. Nếu chạm cắt lỗ trước đó thì chờ |
| Tỷ trọng | Mỗi mã ≈ NAV/5. Tối đa 5 mã |
| Thứ tự | Bán trước, mua sau. Tiền bán dùng mua ngay trong phiên (sức mua ứng trước) |
| Giá khớp | Giá đóng cửa (ATC) |
| Quyết định | Theo tín hiệu tính lúc ~14:20 (`use_preview_decisions: true`). Nếu lỡ lần chạy đó thì dùng tín hiệu theo giá đóng cửa |
| Cổ tức / chia tách | Nguồn giá đã điều chỉnh. Hệ thống phát hiện và điều chỉnh giá vốn và số lượng cho khớp |
| Lỡ ngày | Lần chạy sau tự bù các phiên còn thiếu |

Toàn bộ luật chiến lược (bộ lọc VNINDEX, Breakout Donchian 55, Sideway RSI, cách xếp hạng điểm) được ghi đầy đủ trong tab **Luật chiến lược** trên web và cài đặt trong `engine/core.py`.

## Lệnh hữu ích (chạy trên máy cá nhân)

```bash
pip install -r requirements.txt
python -m engine.run --mode close        # chốt sổ
python -m engine.run --mode preview      # tín hiệu dự kiến
python -m engine.run --demo              # dữ liệu mô phỏng (không cần mạng)
python -m engine.run --reset-live        # xoá sổ live, bắt đầu lại từ 100tr
python tests/test_rules.py               # kiểm thử luật
cd docs && python -m http.server 8000    # xem web tại http://localhost:8000
```

## Xử lý sự cố

- **Workflow báo lỗi “Không lấy được dữ liệu”.** Đôi khi API chứng khoán VN chặn IP nước ngoài, trong khi máy GitHub đặt ở Mỹ. Bạn có hai cách:
  - Thử *Run workflow* lại sau ít phút.
  - Chạy trên máy của bạn bằng Task Scheduler (Windows) hoặc cron lúc 14:20 và 15:25 với lệnh `python -m engine.run && git add -A && git commit -m data && git push`. Workflow trên GitHub vẫn sẽ deploy web.
- **Danh sách VN30 sai.** Hệ thống tự lấy danh sách VN30 từ Vietcap. Nếu thất bại, nó dùng `vn30_fallback` trong config. Để cố định danh sách, điền `vn30_override`.
- **GitHub tạm dừng lịch chạy.** Lịch bị tạm dừng nếu repo không có hoạt động trong 60 ngày. Commit dữ liệu hằng ngày thường đủ để giữ lịch hoạt động; nếu bị dừng, vào tab Actions bấm *Enable workflow*.
- **Thiên lệch sống sót.** Backtest dùng danh sách VN30 *hiện tại* nên có thiên lệch này (survivorship bias). Hãy xem kết quả backtest như tham khảo.

*Công cụ cá nhân để kiểm chứng chiến lược. Không phải khuyến nghị đầu tư.*
