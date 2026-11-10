# SafeJourney — trạng thái và lộ trình phát triển

**Cập nhật: 10/11/2026.** Tài liệu mô tả trạng thái hiện tại và việc cần làm tiếp. Kết quả đo chi tiết tập trung ở [07](07-ket-qua-kiem-thu-va-tai.md), thiết kế tổng thể ở [01](01-phan-tich-giai-phap.md).

## 1. Phạm vi đã xây

| Năng lực | Trạng thái code | Kiểm chứng / giới hạn |
|---|---|---|
| Môi trường local | Conda safejourney, Python 3.12 từ environment.yml; thêm H3/OR-Tools và PyArrow | Kết quả test/build/tải của mã hiện tại tập trung ở [07](07-ket-qua-kiem-thu-va-tai.md); không dùng số đo cũ thay cho bản nâng cấp |
| API và dữ liệu | Router theo nghiệp vụ, pool, migration checksum | Backend test trên PostgreSQL/Redis local đạt |
| Đăng nhập/phân quyền | Cookie phiên, tài khoản/role, quyền chuyến, giới hạn login đồng thời | Test truy cập chéo, SOS riêng tư, phê duyệt khẩn chỉ operator và xác nhận chỉ đúng người nhận |
| Nhiều operator | Owner có thời hạn, gia hạn, phiên xử lý, trả hàng đợi, queue server | Test PostgreSQL đồng thời và HTTP hai API process đạt; chưa đo hàng nghìn operator; quy trình ở [08](08-quy-trinh-operator-va-phan-cong.md) |
| Telemetry | Inbox/outbox, xử lý lô, chống trùng, policy thời gian | Test hồi quy và bài tải 1.000 xe bình thường đạt |
| Phát hiện | STOP, DEVIATION, SPEED, GPS_LOST, SOS | Rule có test; chưa đo precision/recall thực tế |
| Điều phối | Agent tự SMS → gọi → xác nhận/đối chiếu GPS; chỉ nhánh khẩn cần HITL; deadline DB | Test AUTO/timeout/đồng thời/quyền/auto-close có điều kiện đạt; chưa đo tải bão liên hệ |
| Dashboard | Bộ lọc nhóm/phụ trách/trạng thái ở server, hồ sơ độc lập với hàng đợi; thêm khu vực kiểm tra vận hành bằng lựa chọn/nút và xem lịch sử | Các test logic, build và luồng browser đã thực sự kiểm tra được ghi ở [07](07-ket-qua-kiem-thu-va-tai.md); không mặc định mọi tương tác đã được thử |
| Bản đồ | Mapbox tùy chọn, GeoJSON nguồn điểm/tuyến riêng | Đã thấy bản đồ trong smoke Chrome; chưa kiểm chứng chi tiết render/WebGL hoặc 1.000 điểm trực tiếp |
| LLM | Incident planner chọn bước xác minh; operations supervisor tùy chọn chỉ chọn ưu tiên chuyên trách, tất cả công cụ vẫn bắt buộc chạy | Chất lượng AI, năng lực LLM thật và mode thực tế của từng lượt kiểm chứng xem [07](07-ket-qua-kiem-thu-va-tai.md); mock không thay đánh giá model |
| Cụm khu vực | DBSCAN theo loại sự cố, 300 m, tối thiểu 2 chuyến | Quyền operator; dùng vị trí gần đây, chưa lưu vị trí sự cố riêng |
| Vận hành đa bước | LangGraph bảy vai trò, năm kịch bản, snapshot/lịch sử và retry có token | Các vai trò là node cùng tiến trình; dữ liệu fleet/pin/trạm/thời tiết là mô phỏng; [09](09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md) |
| Cước / EV / sạc | Decimal kiểm tra tiền; pin gồm SOH/dự trữ/đoạn đón, hàng chờ FCFS | Chưa có giá hợp đồng, pin/trạm live hoặc hiệu chuẩn xe; không có giao dịch tiền thật |
| Không gian / phân xe | PostGIS/H3, OSRM cấu hình tùy chọn; OR-Tools một yêu cầu/xe | Mặc định đường chưa xác minh; chưa tối ưu cả ca/đa điểm/đặt chỗ sạc; phương án advisory không giao đơn thật |
| Dữ liệu thực | CLI TLC ngoại tuyến, forecast vùng–giờ và đối soát thành phần tiền | Đã có báo cáo TLC thực ở [10](10-du-lieu-thuc-va-benchmark.md); không có GPS/SOS, chưa nối forecast vào runtime H3 |
| Đóng gói | Docker frontend + backend, user 10001 | Trạng thái kiểm chứng image hiện tại ở [07](07-ket-qua-kiem-thu-va-tai.md); chưa deploy Fly.io |
| Hiệu năng | Bộ tải 1.000 xe, nhiều API + một Detector/một Planner | Kết quả/source fingerprint ở [07](07-ket-qua-kiem-thu-va-tai.md); chưa xác nhận tải hỗn hợp tối ưu vận hành, bão cảnh báo hoặc một triệu xe |

## 2. Ưu tiên tiếp theo

### P1 — Xác nhận trải nghiệm sử dụng

- Mở rộng kiểm tra browser: safe theo dõi → đóng, SOS của khách, từ chối và ngoại lệ sửa gói; luồng cần hỗ trợ → nhận/duyệt/đóng và SMS hết hạn → gọi đã kiểm chứng.
- Kiểm tra proposal hết hạn, yêu cầu mới và ngăn nhấp lặp.
- Kiểm tra mất mạng, reconnect, phiên hết hạn và chuyển tài khoản.
- Kiểm tra năm kịch bản vận hành, lịch sử, retry sau lỗi, đổi chuyến khi đang chạy và thông báo không đủ pin tới trạm; đối chiếu đúng giả định mô phỏng trên màn hình.
- Bật Mapbox, kiểm tra tuyến, điểm cũ, vị trí không hợp lệ và giao diện trên màn hình nhỏ.
- Đo render/CPU/bộ nhớ với đội xe 1.000 điểm; HTTP benchmark không đo các chỉ số này.

Hoàn thành khi có kịch bản chạy lặp được và bằng chứng kết quả theo từng vai trò.

### P2 — Đánh giá độ đúng của cảnh báo

- Tạo bộ dữ liệu được gán nhãn: dừng đèn đỏ, kẹt xe, đón khách, GPS nhiễu, mất mạng, sai đồng hồ, đi lệch tuyến và tình huống SOS.
- Đo precision/recall theo từng loại; tách cảnh báo giả trên chuyến khỏi lỗi kỹ thuật pipeline.
- Xác định ngưỡng theo loại đường/xe và vùng, version cấu hình rule.
- Chạy model anomaly hoặc LLM ở chế độ quan sát trước khi cho ảnh hưởng đến quy trình nhân viên.
- Mở rộng benchmark TLC theo tháng/mùa và đánh giá forecast trên vùng vận hành thực. Bổ sung nguồn thời tiết, EV/trạm sạc có quyền sử dụng; đánh giá riêng từng nguồn và mô hình, không gán nhãn tai nạn/gian lận từ chênh lệch cước.

Hoàn thành khi có bộ dữ liệu, cách gán nhãn và tiêu chí nghiệm thu; không sử dụng “không có cảnh báo trong đường GPS giả” làm bằng chứng độ chính xác thực tế.

### P3 — Bền vững khi chạy dài

- Soak test 30–60 phút rồi lâu hơn với dữ liệu riêng.
- Bão SOS, liên hệ/phản hồi/timeout đồng loạt, LLM timeout kéo dài, restart worker và gián đoạn DB/Redis. Đo tuổi timer quá hạn và tỷ lệ chuyển HITL.
- Theo dõi tuổi backlog, độ trễ nhận cảnh báo, số job chờ và tài nguyên từng tiến trình.
- Thiết kế thời hạn lưu GPS/inbox, phân vùng bảng và cơ chế xóa có kiểm soát.
- Có backup/restore, đối chiếu số sự kiện và kiểm chứng phục hồi.
- Đánh giá tỷ lệ tự hoàn tất, phản hồi an toàn sai và bỏ sót; gom các cảnh báo liên quan và giới hạn liên hệ chung theo người/chuyến.
- Tách đường liên hệ theo playbook dự phòng khỏi thời gian chờ model nếu đo incident-to-first-contact không đạt.

Hoàn thành khi đáp ứng ngưỡng đã định trên staging với máy sinh tải tách riêng.

### P4 — Mở rộng có kiểm soát

| Mở rộng | Chuẩn bị trước | Tiêu chí |
|---|---|---|
| Nhiều Detector | Chia partition theo trip, xác định owner, lease/fencing | Giữ thứ tự mỗi chuyến và không tạo hiệu ứng lặp |
| Nhiều Planner | Claim job/lease, retry, dedupe; thay khóa singleton theo thiết kế | Không tạo proposal/action trùng |
| Nhiều người xem realtime | Event theo phạm vi, snapshot/delta và backpressure | Không poll toàn DB theo số WebSocket; reconnect không mất cập nhật |
| Vận hành nhiều operator | Queue theo tổ chức/kỹ năng, giới hạn lượng việc, supervisor thu hồi có audit và bàn giao ca | Không để hồ sơ mất người phụ trách; kiểm thử tải/ca trực và lỗi mạng; giữ owner/phiên/hạn ở backend |
| Provider SMS/call | Action outbox, policy ca thường/approval ca khẩn, callback có xác thực, quota người/chuyến, idempotency và đối soát | Có trạng thái UNKNOWN; không retry mù khi chưa biết kết quả |
| Vận hành với dữ liệu thật | Adapter xe/pin/trạm/đơn hàng có độ mới; OSRM quản lý riêng; forecast được đánh giá; queue và quota toàn cụm | Công cụ xác định kiểm tra lại dữ liệu mới trước thực thi, không vượt quyền khẩn |
| Dispatch / hoàn tiền thật | Policy nghiệp vụ, số dư/đơn hàng authoritative, outbox và khóa chống trùng với provider | Không dùng báo cáo lịch sử làm lệnh; kiểm tra cạnh tranh và đối soát trạng thái chưa rõ |
| Đội xe/đơn vị khác nhau | Tenant/organization scope xuyên dữ liệu và kênh realtime | Test chống đọc/ghi chéo tenant |
| Triển khai Fly | PostGIS/Redis, secret, process group, monitor và rollback | Smoke trên HTTPS; benchmark trên tài nguyên triển khai |

Không nhân bản Detector/Planner bằng cách bỏ khóa singleton. Ranh giới mở rộng và thứ tự khóa được mô tả ở [05](05-ra-soat-kien-truc-mvp.md).

### P5 — Kiểm chứng mục tiêu 1.000.000 xe

Đây là mục tiêu tương lai, chưa có code phân tán hoặc bài tải xác nhận. Phải phân biệt số xe đăng ký với số xe cùng gửi GPS: một triệu xe đồng thời, mỗi 3 giây, tương ứng khoảng 333.333 sự kiện/giây.

- Mốc 10.000: đo nút thắt, chạy dài, tăng người xem, thử burst/GPS_LOST/SOS và xử lý giới hạn được tìm thấy.
- Mốc 100.000: chia ownership theo chuyến, retention/dedupe rõ ràng, máy sinh tải tách riêng; kiểm thử chuyển owner, replay và lỗi hạ tầng.
- Mốc 1.000.000: tải phân tán, chạy nhiều giờ tới 24 giờ, phục hồi backlog và mất vùng hạ tầng; kiểm chứng đường cảnh báo tới nhân viên và năng lực ca trực.
- Tối ưu vận hành phải chia vùng/cửa sổ thời gian, lọc ứng viên và giới hạn kích thước bài toán. Không gọi LLM theo từng GPS hoặc dựng ma trận toàn bộ một triệu xe. Đo queue/deadline/chi phí và ảnh hưởng tới SOS trên tải hỗn hợp trước khi mở rộng.

Giữ quyền, idempotency và HITL khi nâng cấp; không đổi nghĩa “durable” của API mà chưa kiểm chứng cách phục hồi. Xem [mục 7 báo cáo 07](07-ket-qua-kiem-thu-va-tai.md#million-vehicles) cho công thức băng thông/lưu trữ, giới hạn code, kiến trúc đích và điều kiện nghiệm thu. Không suy ra số máy hoặc chi phí bằng cách nhân kết quả 1.000 xe.

## 3. Quy ước nghiệm thu

Mỗi hạng mục cần có hành vi quan sát được, code thực hiện, test phù hợp và tài liệu hiện tại. Đánh dấu riêng “đã có code”, “đã chạy kiểm thử” và “đã triển khai”.

Mọi hành động hiện vẫn mô phỏng. Tích hợp hành động khẩn thật phải giữ phê duyệt phía backend, phân quyền, nhật ký và cách xử lý kết quả không chắc chắn.

