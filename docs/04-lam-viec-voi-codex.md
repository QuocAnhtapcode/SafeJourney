# SafeJourney — làm việc trong Project Codex

**Cập nhật: 10/11/2026.** Dùng Project **SafeJourney**, thư mục **D:\SafeJourney**, làm nơi làm việc chung cho code và tài liệu.

## 1. Nguồn thông tin chuẩn

- [README](../README.md): điểm bắt đầu, cách chạy ngắn và trạng thái hiện tại.
- [Hướng dẫn 02](02-huong-dan-cai-dat-va-lap-trinh.md): thao tác từng bước cho người mới.
- [Lộ trình 03](03-lo-trinh-phat-trien.md): việc đã có và việc còn phải xây.
- [Kiến trúc 05](05-ra-soat-kien-truc-mvp.md): module, hợp đồng và cách mở rộng.
- [Đo tải 06](06-kiem-thu-tai-1000-xe.md), [kết quả 07](07-ket-qua-kiem-thu-va-tai.md): cách đo và bằng chứng mới nhất.
- [Agent và HITL 08](08-quy-trinh-operator-va-phan-cong.md): tự liên hệ, phản hồi người nhận, gói duyệt và phân công.
- [Vận hành và công cụ 09](09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md): cước/pin/sạc/lộ trình/phân xe, nguồn dữ liệu và giới hạn của phương án.
- [Dữ liệu thực 10](10-du-lieu-thuc-va-benchmark.md): cách tải và đánh giá TLC, nguồn tham chiếu và những gì dữ liệu không chứng minh được.
- [AGENTS.md](../AGENTS.md): quy tắc kỹ thuật cho tác vụ code.

Python local dùng môi trường Conda safejourney được tạo từ [environment.yml](../environment.yml). Trong mỗi terminal Python, chạy conda activate safejourney; tác vụ tự động có thể dùng conda run --no-capture-output -n safejourney python. Không dùng Python của base hoặc đường dẫn .venv.

Mã nguồn trong repository quyết định hành vi chạy. Tài liệu hướng dẫn trỏ đến file thật, không chứa bản source độc lập để trích xuất. Nếu phát hiện tài liệu lệch code, sửa tài liệu cùng thay đổi thay vì tạo thêm bản hướng dẫn “v2/final/mới nhất”.

## 2. Tổ chức công việc

Giữ tên tài liệu theo số thứ tự 01–10. Giữ đường dẫn backend, frontend, simulator.py, load_tests và research_benchmarks ổn định để lệnh chạy không bị hỏng.

Có thể đặt tên chat theo một việc cụ thể, ví dụ:

- SafeJourney — kiểm tra giao diện và quyền truy cập
- SafeJourney — xử lý GPS và chất lượng tín hiệu
- SafeJourney — tải đội xe và độ trễ
- SafeJourney — công cụ pin, cước và phân xe
- SafeJourney — đánh giá dữ liệu thực
- SafeJourney — triển khai staging

Một chat đang sửa nhóm file nào nên nêu rõ phạm vi đó. Nếu nhiều tác vụ chạy song song, tránh sửa cùng file và tránh chạy integration trong lúc benchmark đang dùng database test.

## 3. Cách giao việc dễ kiểm chứng

Ví dụ yêu cầu sửa:

> Trong D:\SafeJourney, bổ sung bộ lọc loại sự cố cho operator. Đọc hành vi hiện tại, giữ quyền SOS của từng người, sửa backend/frontend cần thiết, chạy test liên quan và cập nhật tài liệu. Báo rõ phần đã thử và phần chưa thử.

Ví dụ yêu cầu học:

> Giải thích đường đi từ simulator.py đến worker.py bằng các file hiện tại, rồi hướng dẫn tôi đổi ngưỡng STOP và tự kiểm chứng.

Ví dụ yêu cầu tải:

> Chạy lại cấu hình 1.000 xe trong tài liệu 06 trên stack local riêng, giữ nguyên ngưỡng và lưu cả báo cáo nếu FAIL. So sánh số gửi theo lịch, số APPLIED, p95 và backlog.

Không cần gửi lại mật khẩu hay toàn bộ .env trong chat. Mô tả triệu chứng, thao tác gây lỗi và thông báo lỗi đã che dữ liệu nhạy cảm là đủ.

## 4. Quy trình cho một thay đổi

1. Xác định hành vi và file liên quan.
2. Sửa trong workspace; không ghi đè công việc đang có.
3. Nếu đổi schema, thêm migration mới; không sửa migration đã áp dụng.
4. Chạy kiểm thử phù hợp, build khi ảnh hưởng frontend/đóng gói.
5. Cập nhật tài liệu hiện hành và báo cáo kết quả đo nếu cần.
6. Xem thay đổi rồi lưu bằng Git theo quy trình của bạn.

Không tự suy ra “đã production” từ việc build thành công. Cần phân biệt test giả lập, test dùng database thật local, HTTP smoke, kiểm tra browser và triển khai thực tế.

## 5. Dữ liệu và an toàn khi làm việc

- Secrets ở .env bị Git bỏ qua; frontend chỉ nhận cấu hình công khai.
- Integration dùng safejourney_test; tải dùng safejourney_loadtest với cổng riêng.
- Không xóa volume để giải quyết lỗi mà chưa xác định dữ liệu và cách khôi phục.
- Giữ JSON FAIL và log đo tải làm bằng chứng; báo cáo 07 chỉ trình bày kết quả hiện tại.
- Ca thường tự xử lý theo policy backend; xác nhận từ đúng người nhận. Hành động khẩn phải có người duyệt tại backend. Nội dung LLM không cấp quyền thực thi.
- Phương án vận hành hiện chỉ là báo cáo mô phỏng. Giữ số liệu trong công cụ xác định; ghi rõ nguồn, thời điểm và giả định; không gọi dữ liệu kịch bản là telemetry live.
- Giữ Parquet thô trong thư mục data bị Git bỏ qua. Báo cáo TLC phải có provenance/checksum và chia tập theo thời gian; không coi forecast accuracy là độ chính xác phát hiện tai nạn.
- Không đổi tên/move thư mục project chỉ để làm đẹp; thay đổi cấu trúc phải có lý do và cập nhật đường dẫn liên quan.

