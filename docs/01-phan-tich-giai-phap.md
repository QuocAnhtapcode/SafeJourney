# SafeJourney — phân tích giải pháp và kiến trúc

**Cập nhật: 10/11/2026.** Tài liệu mô tả hệ thống đang có trong repository và các bước mở rộng được ghi rõ là **chưa triển khai**. Mã nguồn là nguồn chuẩn cho hành vi hiện tại; số đo kiểm thử nằm ở [báo cáo 07](07-ket-qua-kiem-thu-va-tai.md).

## 1. Bài toán và mục tiêu

Khi nhiều chuyến đang chạy đồng thời, nhân viên an toàn khó quan sát liên tục vị trí, tốc độ và tín hiệu SOS của từng chuyến. SafeJourney nhận tín hiệu hành trình, phát hiện điều kiện bất thường, tạo hồ sơ sự cố và đưa công việc cần xử lý lên dashboard.

Phạm vi mở rộng bổ sung việc đối chiếu cước, tuyến, dung lượng pin và chờ sạc khi cung–cầu thay đổi. Phần hiện có dùng một nhóm node chuyên trách trong LangGraph và công cụ tính toán xác định để tạo báo cáo vận hành mô phỏng; operator chọn kịch bản bằng nút/lựa chọn. Dữ liệu TLC thực được đánh giá ngoại tuyến riêng. Hai phần này tạo nền cho việc tích hợp dữ liệu xe điện/đơn hàng/thời tiết thật sau này, chưa thay thế hệ thống điều xe hoặc thanh toán thực.

Một cảnh báo là dấu hiệu cần xác minh, không phải kết luận có tai nạn. Ví dụ, xe dừng có thể do đèn đỏ, đón khách hoặc hỏng xe; GPS im lặng có thể do mất mạng hoặc thiết bị hết pin. Hệ thống phải trình bày bằng chứng và độ mới dữ liệu để nhân viên quyết định.

Mục tiêu của MVP:

- Theo dõi nhiều chuyến bằng dữ liệu GPS giả lập, có phân quyền theo người dùng.
- Phát hiện dừng lâu, lệch tuyến, tốc độ cao, mất tín hiệu và SOS mà không chờ LLM.
- Lưu sự cố, đề xuất, quyết định và kết quả mô phỏng để kiểm tra lại.
- Cho phép nâng cấp detector, LLM, kênh liên hệ và cách triển khai mà vẫn giữ các ràng buộc an toàn.
- Đo tải 1.000 xe bằng bài thử có lịch gửi và ngưỡng đạt công khai.
- Kiểm tra lộ trình, cước/hoàn tiền, pin và chờ sạc bằng công cụ; phân xe mô phỏng có ràng buộc; ghi nguồn và giả định cho từng báo cáo.
- Đánh giá nhu cầu theo vùng–giờ trên dữ liệu TLC thực, tách khỏi kiểm thử tải GPS và độ đúng của cảnh báo.

Đây là phần mềm học tập. SMS, cuộc gọi và yêu cầu cứu hộ hiện chỉ được ghi nhận dưới dạng **hành động mô phỏng trong database**.

## 2. Phạm vi đã có và phạm vi nâng cao

| Năng lực | Hiện tại trong code | Phần cần phát triển |
|---|---|---|
| Đăng nhập | Cookie phiên, mật khẩu băm, vai trò operator/driver/passenger | Quản lý tài khoản, OIDC, MFA, nhiều đội xe |
| Theo dõi chuyến | Danh sách vị trí, độ mới GPS, bản đồ Mapbox tùy chọn | Mobile SDK, heartbeat thiết bị, map matching |
| Phát hiện | Rule theo cửa sổ thời gian, PostGIS đo lệch tuyến, watchdog GPS | Ngưỡng theo đường/loại xe, mô hình anomaly có dữ liệu đánh giá |
| Điều phối | Agent tự liên hệ, chờ người nhận, đối chiếu GPS; HITL khi khẩn | Timer/Planner chia tải, quota theo chuyến và SLA |
| Hành động | SMS → gọi mô phỏng tự động cho ca thường; gói khẩn HUMAN chờ duyệt | Adapter SMS/call thật, callback, đối soát và xử lý kết quả UNKNOWN |
| Leo thang | Ghi nhắc nội bộ sau 30/60 giây với sự cố mức 3 chưa tiếp nhận | Lịch trực, người dự phòng, điều phối liên đơn vị |
| Memory | Nhật ký, checkpoint, gói có phiên bản và phản hồi người nhận có cấu trúc | Tìm kiếm hồ sơ và bộ dữ liệu đánh giá được gán nhãn |
| Cụm khu vực | DBSCAN theo loại sự cố trên vị trí gần đây | ID cụm ổn định, vị trí tại thời điểm sự cố, phạm vi nhiều vùng |
| Kiểm tra vận hành | 5 kịch bản, LangGraph chuyên trách, lịch sử `operations_runs`; operator chỉ chọn và bấm chạy | Dữ liệu xe/đơn hàng/trạm sạc thật, kích hoạt theo sự kiện và queue bền vững |
| Công cụ định lượng | Decimal cước/hoàn, mô hình pin/SOH/dự trữ, chờ sạc FCFS; H3 và OSRM tùy chọn | Hiệu chuẩn biểu giá/xe, map matching và giao thông trực tiếp |
| Tối ưu | OR-Tools ghép tối đa một yêu cầu/xe, giới hạn ghế/pin/thời gian đón | Tối ưu cả ca, nhiều điểm, đặt chỗ sạc, phân vùng quy mô lớn |
| Dữ liệu thực | Benchmark TLC vùng–giờ và đối soát tổng tiền ngoại tuyến; xem [10](10-du-lieu-thuc-va-benchmark.md) | GPS có nhãn an toàn, thời tiết/EV, đánh giá dịch chuyển vùng và chất lượng cảnh báo |
| Chịu tải | Pool, batch GPS, dashboard gộp refresh, bộ đo tải local | Soak test, chia partition, event delta, HA và phục hồi đa vùng |

“Có code” không đồng nghĩa đã xác nhận trên môi trường triển khai thực tế. Trạng thái kiểm chứng hiện tại được cập nhật tại [lộ trình 03](03-lo-trinh-phat-trien.md) và [báo cáo 07](07-ket-qua-kiem-thu-va-tai.md).

## 3. Các nguyên tắc không được phá khi tối ưu

1. **Lưu trước khi xác nhận:** API chỉ trả `durable` sau khi inbox và outbox đã commit. Phản hồi này chưa khẳng định Detector đã xử lý.
2. **Phát hiện độc lập với LLM:** luật và SOS vẫn hoạt động khi mô hình chậm hoặc không dùng được.
3. **Quyền thực thi tại backend:** ca thường theo policy có giới hạn; hành động khẩn phải có người duyệt. LLM và payload resume graph không cấp quyền.
4. **Chống hiệu ứng lặp:** cùng UUID không tạo thêm GPS/SOS hoặc hành động đã được xử lý.
5. **Quyền theo đối tượng:** không chỉ kiểm tra “đã đăng nhập”; phải kiểm tra người đó được đọc/ghi chuyến nào.
6. **Không biến dữ liệu cũ thành vị trí hiện tại:** thời điểm quan sát, tiếp nhận và xử lý được phân biệt.
7. **Đo cả phần không gửi được:** bộ sinh tải bỏ lịch gửi phải ghi dropped và đánh trượt; không tính riêng các request thành công để tuyên bố đủ tải.
8. **Nâng cấp dữ liệu có phiên bản:** migration đã áp dụng không được sửa; thêm migration mới và chạy trên database thử nghiệm trước.
9. **Số liệu do công cụ kiểm chứng:** LLM không tính cước/pin hoặc ghi đè kết quả solver; mọi đầu vào có nguồn và đơn vị. Cảnh báo chênh lệch cước chưa là kết luận gian lận.
10. **Báo cáo khác với thực thi:** bộ vận hành hiện chỉ lưu phương án mô phỏng; nó không tự phân xe, hoàn tiền hoặc phê duyệt cứu hộ.

## 4. Kiến trúc triển khai hiện tại

Hệ thống là **một codebase chia module**, chạy ba loại tiến trình. Cách tổ chức này giữ việc học và triển khai đơn giản, đồng thời tạo ranh giới rõ để mở rộng sau này.

```text
Tài xế / Simulator
        |
        v
FastAPI: phiên + validate + quyền chuyến
        |
        v
PostgreSQL: telemetry_inbox + telemetry_outbox
        |
        v
Relay theo lô -> Redis Stream -> Detector theo lô
                                     |
                  +------------------+------------------+
                  v                                     v
         Vị trí / trạng thái luật                 Sự cố / bằng chứng
                  |                                     |
                  v                                     v
         REST + WebSocket refresh               Planner / LangGraph
                  |                                     |
                  v                                     v
              Dashboard                  Gói thường AUTO / khẩn HUMAN
                                             |                  |
                                             v                  v
                                  SMS → gọi → xác nhận    Operator duyệt
                                             |                  |
                                             v                  v
                                  Đối chiếu GPS / HITL   Mock action + audit

SOS -> FastAPI -> PostgreSQL sự cố mức 3
      (không chờ Redis, Detector hoặc LLM)
```

Đường kiểm tra vận hành chạy riêng khi operator yêu cầu: **API chụp đầu vào → LangGraph chuyên trách → công cụ lộ trình/cước/pin/nhu cầu/OR-Tools → kiểm chứng → lưu báo cáo**. Không gọi solver/LLM trên từng GPS. Thiết kế, công thức, quyền và hướng dẫn thao tác ở [09](09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md). Mặc định OSRM chưa được cấu hình; số đo hình học được gắn nhãn chưa xác minh đường bộ.

| Thành phần | Trách nhiệm | File chính |
|---|---|---|
| API | Xác thực, đọc dữ liệu, nhận GPS/SOS, kiểm tra HITL | [main.py](../backend/app/main.py), [api/](../backend/app/api/) |
| Database | Giao dịch, inbox/outbox, sự cố, phiên và audit | [db.py](../backend/app/db.py), [schema.sql](../backend/schema.sql), [migrations/](../backend/migrations/) |
| Detector | Relay, xử lý GPS theo lô, cập nhật state, kiểm tra mất tín hiệu | [worker.py](../backend/app/worker.py), [rules.py](../backend/app/rules.py) |
| Planner | Tạo và tiếp tục graph, gọi LLM nếu bật, nhắc ca trực | [planner.py](../backend/app/planner.py) |
| Realtime | Báo cần làm mới trong phạm vi quyền của phiên | [realtime.py](../backend/app/realtime.py) |
| Frontend | Dashboard, bảng, thao tác sự cố, bản đồ | [frontend/src/](../frontend/src/) |
| Bộ sinh dữ liệu | Thực hành vài chuyến hoặc đo tải cả đội xe | [simulator.py](../simulator.py), [load_tests/](../load_tests/) |

Redis không phải nguồn dữ liệu chuẩn. Nếu Redis lỗi, bản tin đã được API nhận vẫn nằm trong PostgreSQL để relay lại. Watchdog mất GPS có nhánh kiểm tra riêng; nó không bị bỏ qua chỉ vì một lệnh Redis lỗi, nhưng vẫn chịu thời gian chờ của vòng lặp và database.

Một Detector và một Planner giữ khóa advisory để tránh hai bản cùng xử lý state. Planner có một luồng công việc mức 3 và một luồng công việc thường; phần bảo trì nhắc ca trực/hết hạn không chờ LLM. Đây chưa phải cơ chế phân tán nhiều Planner.

## 5. Hợp đồng telemetry và chính sách thời gian

Một điểm GPS gồm UUID `event_id`, số thứ tự `seq`, tọa độ, độ chính xác, tốc độ và `event_time` có múi giờ. Schema request nằm trong [schemas.py](../backend/app/schemas.py).

| Trường/thời điểm | Ý nghĩa |
|---|---|
| `event_id` | Khóa chống trùng; client retry cùng sự kiện phải dùng lại UUID và payload |
| `seq` | Số thứ tự do thiết bị gửi; MVP chưa dùng nó làm khóa toàn cục hoặc cơ chế phục hồi |
| `event_time` | Lúc thiết bị quan sát GPS |
| `received_at` | Lúc bản tin được ghi nhận ở server |
| `processed_at` | Lúc Detector đánh dấu đã xử lý trong giao dịch |
| `last_received_at` | Lần tiếp nhận GPS còn mới của chuyến, dùng cho watchdog |
| `last_seen` | Thời điểm quan sát cuối đã được áp dụng lên vị trí/state |

API kiểm tra tài xế được phân công, trạng thái ACTIVE, kiểu dữ liệu và đồng hồ thiết bị đi trước quá mức cho phép. UUID đã tồn tại với cùng actor/chuyến/payload được trả là bản lặp; UUID dùng cho dữ liệu khác bị từ chối.

Detector phân loại từng bản tin:

| Kết quả | Ý nghĩa |
|---|---|
| APPLIED | Dữ liệu hợp lệ về thời gian và được áp dụng |
| STALE | Đã quá cũ hoặc lệch thời gian quá mức ngay tại lúc tiếp nhận |
| OUT_OF_ORDER | Thời điểm quan sát không mới hơn điểm đã áp dụng |
| INACTIVE | Chuyến không còn ACTIVE khi xử lý |

Chính sách nằm trong [telemetry_policy.py](../backend/app/telemetry_policy.py). Mặc định dung sai mới/cũ là 30 giây. Một điểm hợp lệ lúc nhận vẫn phải được xử lý nếu sau đó bị chậm trong hàng đợi; độ trễ hàng đợi được đo riêng. GPS cũ gửi lại không được làm mới `last_received_at` để che mất tín hiệu.

### Thứ tự, giao lặp và lỗi

API ghi inbox/outbox cùng transaction. Relay có thể gửi lặp nếu bị dừng giữa gửi Redis và cập nhật trạng thái outbox. Detector dùng UUID, khóa row và `processed_at` để không áp dụng lại; ACK Redis chỉ sau commit.

Trong một lô, worker khóa chuyến theo thứ tự ổn định rồi xử lý theo thời gian tiếp nhận. State luật được cập nhật tuần tự trong bộ nhớ; chỉ vị trí/state cuối mỗi chuyến trong lô cần được ghi trở lại. Inbox được giữ cho audit/chống trùng; outbox đã hoàn thành được dọn.

Dữ liệu nội bộ hỏng, worker chết liên tục và retention dài hạn vẫn cần cơ chế vận hành bổ sung. Không coi Redis Streams đơn thuần là bảo đảm “exactly once” cho mọi hệ thống bên ngoài.

## 6. Phát hiện và phân loại rủi ro

### 6.1. Các luật hiện có

Các ngưỡng sau là cấu hình **demo trong backend/.env.example**, dùng để dễ quan sát khi thực hành:

| Loại | Điều kiện chính | Thời lượng demo |
|---|---|---:|
| STOP | GPS đủ chất lượng và tốc độ dưới 3 km/h | 15 giây |
| DEVIATION | GPS đủ chất lượng và ngoài hành lang tuyến | 12 giây |
| SPEED | GPS đủ chất lượng, tốc độ lớn hơn SPEED_LIMIT_KMH + 10 | 9 giây |
| GPS_LOST | Không nhận GPS còn mới | 45 giây |
| SOS | Tài xế/khách gửi SOS hợp lệ | Ghi sự cố ngay khi API nhận |

Với SPEED_LIMIT_KMH=80, rule SPEED dùng điều kiện **lớn hơn 90 km/h**, không phải lớn hơn 80. Độ chính xác GPS phải trong khoảng trên 0 đến 30 m để tích lũy STOP/DEVIATION/SPEED. Hành lang tuyến được tính bằng PostGIS với khoảng cách lớn hơn giữa 100 m và hai lần accuracy.

Khoảng trống quan sát dài hơn 15 giây làm reset cửa sổ liên tục. Tốc độ lấy từ payload, chưa đối chiếu độc lập bằng quãng đường/thời gian. Một loại bất thường đang mở được cập nhật thay vì tạo incident mới ở mỗi điểm.

Ngưỡng mặc định trong code và cấu hình test tải có thể khác demo; luôn đọc file cấu hình của tiến trình đang chạy. Thay ngưỡng phải khởi động lại tiến trình dùng nó.

### 6.2. Mức độ và diễn giải

MVP tạo các cảnh báo rule ở mức 2 và SOS ở mức 3. Schema cho phép mức 1 nhưng chưa có một bộ classifier tự động đầy đủ cho mọi loại rủi ro.

| Mức | Cách dùng trong MVP |
|---|---|
| 1 | Dành cho mở rộng mức theo dõi; chưa được rule hiện tại tự sinh |
| 2 | Dấu hiệu cần xác minh; đề xuất MOCK_CHECK_IN |
| 3 | Ưu tiên khẩn; đề xuất MOCK_EMERGENCY và nhắc nội bộ nếu chưa tiếp nhận |

Một SOS mức 3 cho biết có yêu cầu cần ưu tiên, không tự chứng minh loại nguy hiểm. Hệ thống không tự gọi cảnh sát/cứu hộ thật. Với tình huống có thể liên quan đe dọa, việc gọi ngay cho hành khách có thể không phù hợp; nhân viên cần chọn kênh xác minh an toàn theo quy trình đã được tổ chức phê duyệt.

### 6.3. Giảm báo động giả khi nâng cấp

Phần **chưa triển khai đầy đủ** gồm: vùng đón/trả khách, giao lộ/ùn tắc, giới hạn tốc độ theo đường, hiệu chỉnh GPS, heartbeat riêng với tín hiệu vị trí, hành trình tạm dừng hợp lệ và đối chiếu nhiều cảm biến.

Quy trình đánh giá nên giữ tập dữ liệu gắn nhãn độc lập, chia theo chuyến/thiết bị/thời gian và lưu lý do kết luận của nhân viên. Chỉ số cần đo gồm precision/recall theo loại, cảnh báo giả trên 100 chuyến hoặc giờ lái, thời gian phát hiện và thời gian tiếp nhận. Không dùng một bài tải normal để chứng minh độ chính xác classifier.

## 7. Agent, HITL và vòng đời sự cố

### 7.1. Vai trò của LLM

LangGraph phân tích và lưu gói; ca thường chạy bước liên hệ rồi kết thúc job, ca khẩn interrupt chờ quyết định. Scheduler tiếp tục playbook thường theo deadline lưu tại DB. Checkpoint ở PostgreSQL giúp graph tiếp tục sau restart. Backend dựng phần giải thích số liệu từ bằng chứng; khi bật Ollama, model chọn các bước xác minh phù hợp trong playbook và trả khóa tham chiếu có kiểm tra. Khi LLM_MODE=mock hoặc model lỗi, backend dùng playbook dự phòng theo loại sự cố.

Thông tin gửi vào LLM gồm loại sự cố, severity, các số đo/ngưỡng cho phép và danh sách bước xác minh. Detector lưu ngưỡng và thời gian quan sát ngay lúc phát hiện; Planner lọc bằng chứng trước khi đưa vào graph/checkpoint và prompt. Không gửi tọa độ, định danh chuyến/người, số điện thoại, thời điểm chi tiết hoặc nội dung SOS tự do. LLM không nhận credential, không tự truy vấn vị trí và không tự gọi tool cứu hộ.

Phần số đo/giải thích luật được dựng bằng [planner_context.py](../backend/app/planner_context.py), không lấy số liệu do model viết lại. Model trả evidence_keys/check_ids theo JSON schema; khóa ngoài danh sách, khóa lặp hoặc trường tự thêm bị từ chối. Backend giữ bước xác minh nền tảng theo loại sự cố, riêng SOS luôn ưu tiên kênh liên hệ an toàn. Hồ sơ cũ thiếu ngưỡng sẽ ghi rõ thiếu dữ liệu, không suy ra từ cấu hình mới. Lỗi/timeout/JSON không hợp lệ dẫn tới mẫu dự phòng có bằng chứng. Nếu severity thay đổi trong lúc mô hình phân tích, kết quả cũ không được gắn cho hành động của mức mới.

Hai luồng ưu tiên của Planner tránh một LLM thường chậm chặn toàn bộ công việc mức 3. Nó không loại bỏ giới hạn của máy chạy mô hình: một backend LLM vẫn có thể tự xếp hàng hoặc quá tải.

### 7.2. Ba vòng đời cần phân biệt

| Đối tượng | Trạng thái chính |
|---|---|
| Incident | OPEN → RESOLVED; acknowledged_at/by là lần tiếp nhận đầu; owner/thời hạn/phiên xử lý riêng quyết định quyền ghi |
| Proposal | PENDING → EXECUTED / REJECTED / EXPIRED / CANCELLED |
| Graph job | NEW → WAITING → DONE cho HITL; ca AUTO hoàn tất sau chạy bước đầu |
| Playbook thường | WAITING_RESPONSE → MONITORING → COMPLETE, hoặc ESCALATED sang HITL |

“Đã nhận SOS”, “nhân viên đã tiếp nhận” và “đã duyệt hành động” là ba mốc khác nhau. Dashboard và nhật ký cần dùng đúng từ để tránh tạo cảm giác đã có người đến hỗ trợ.

### 7.3. Playbook tự động và xác nhận

STOP/SPEED/DEVIATION/GPS_LOST dưới mức 3 được tự gửi SMS mô phỏng đến tài xế; sau 120 giây không phản hồi chuyển gọi mô phỏng, thêm 120 giây không phản hồi thì chuyển mức 3 để nhân viên đánh giá. Người nhận needs_help chuyển ngay HITL. Safe bắt đầu theo dõi 60 giây; chỉ tự đóng khi GPS mới nhất còn mới, chất lượng tốt và không còn điều kiện tương ứng. Không đủ dữ liệu hoặc cùng chuyến có hồ sơ khẩn thì chuyển người đánh giá.

Xác nhận là phản hồi có xác thực của đúng người nhận, không phải trạng thái gửi thành công. Khách không trả lời thay yêu cầu của tài xế; operator không giả phản hồi. SOS không tự liên hệ người gửi hoặc lực lượng khẩn. Quy trình và giới hạn chi tiết ở [08](08-quy-trinh-operator-va-phan-cong.md).

### 7.4. Duyệt nhánh khẩn và yêu cầu đề xuất mới

1. Nhân viên mở sự cố và xem bằng chứng/độ mới tín hiệu.
2. Planner lưu proposal với action type, nội dung, người nhận tham chiếu và hạn dùng.
3. Nhân viên duyệt hoặc từ chối tại API.
4. Backend kiểm tra role, owner/assignment_version/hạn, incident còn mở, đúng proposal HUMAN, proposal_revision, mức độ, trạng thái PENDING và chưa hết hạn.
5. Quyết định, mock action và audit được ghi cùng transaction; unique constraint ngăn hai mock action cho cùng proposal.
6. Nếu proposal hết hạn, nhân viên có thể **Yêu cầu đề xuất mới** cho đúng proposal. Yêu cầu lặp không tạo nhiều lần yêu cầu; proposal mới vẫn phải được duyệt mới.

Đề xuất hết hạn không tự gia hạn quyền. Nội dung LLM không quyết định action type và một payload resume LangGraph không được coi là phê duyệt.

### 7.5. Khi thay mock bằng hành động thật

Cần thêm action outbox, executor riêng, idempotency key được provider hỗ trợ, hạn dùng phê duyệt tại lúc gửi và trạng thái như SENDING/SUCCEEDED/FAILED/UNKNOWN. Timeout không có nghĩa provider chưa nhận yêu cầu; retry mù có thể gọi lặp.

Sửa nội dung trước duyệt tăng revision và lưu audit; phê duyệt phải khớp revision mới. Đổi người nhận/loại hành động cần gói mới; nội dung đã thực thi không được sửa. Chỉ tích hợp kênh khẩn thật sau khi đã có quy trình duyệt, quyền vận hành và kiểm chứng của đơn vị phụ trách.

## 8. Dữ liệu, quyền và bảo mật

### 8.1. Các bảng chính

| Nhóm | Bảng | Mục đích |
|---|---|---|
| Danh tính | users, sessions, login_attempts | Tài khoản, phiên và giới hạn đăng nhập |
| Hành trình | trips | Người được phân công, tuyến, vị trí cuối, state và revision |
| GPS | telemetry_inbox, telemetry_outbox | Lưu bền vững, chống trùng, relay và dấu vết xử lý |
| Sự cố | incidents, incident_events, sos_events | Hồ sơ, nhật ký và actor của SOS |
| Quyết định | proposals, mock_actions, contact_replies | Gói có revision, AUTO/HUMAN, người duyệt hoặc policy, deadline và phản hồi người nhận |
| Agent | graph_jobs và bảng checkpoint LangGraph | Lịch làm việc và tiếp tục graph |
| Hệ thống | system_state, schema_migrations | Tín hiệu làm mới và lịch sử nâng cấp schema |

Đây là memory có cấu trúc, không phải vector database. Không cần vector search để lưu và kiểm chứng một quyết định HITL.

### 8.2. Ma trận quyền hiện tại

| Thao tác | Operator | Driver được phân công | Passenger được phân công |
|---|---:|---:|---:|
| Xem chuyến/vị trí | Các chuyến trong hệ thống demo | Chuyến của mình | Chuyến của mình |
| Gửi GPS | Không | Có, khi ACTIVE | Không |
| Gửi SOS | Không, dùng tài khoản tài xế/khách | Có trong phạm vi chuyến | Có trong phạm vi chuyến |
| Xem hồ sơ sự cố đầy đủ | Có | Không | Không |
| Xem biên nhận SOS đã tự gửi | Có qua hồ sơ | Có | Có |
| Tiếp nhận/duyệt/đóng/lập đề xuất mới | Có | Không | Không |
| Trả lời yêu cầu liên hệ | Không | Chỉ đúng người nhận | Chỉ đúng người nhận; mẫu hiện tại gửi tài xế |
| Xem cụm và metrics vận hành | Có | Không | Không |

Operator hiện chưa được chia theo tenant/đội xe. Khi phát triển nhiều tổ chức, mọi truy vấn và sự kiện realtime phải được gắn tenant scope; không chỉ thêm bộ lọc ở giao diện.

### 8.3. Ranh giới dữ liệu

Mật khẩu được băm, cookie phiên HttpOnly và role được đọc từ server. Backend kiểm tra Origin cho thao tác ghi và WebSocket. Cấu hình secret chỉ nằm trong `backend/.env` hoặc cơ chế secrets khi triển khai; biến `VITE_*` được đưa vào trình duyệt, nên không được chứa credential database hay khóa quản trị.

Cần bổ sung trước vận hành thực: TLS giữa dịch vụ, quản lý/thu hồi tài khoản, MFA theo vai trò, audit truy cập, chính sách thời gian lưu vị trí/SOS, backup/restore, giám sát bất thường truy cập và quy trình xóa dữ liệu. Tài liệu này không thay cho rà soát pháp lý/quy định bảo vệ dữ liệu của đơn vị vận hành.

## 9. Dashboard và cụm sự cố

Dashboard mặc định lấy chuyến ACTIVE và không tải hình học mọi tuyến mỗi lần refresh. Người dùng có thể đổi sang tất cả chuyến được cấp quyền; tuyến chi tiết được tải khi chọn chuyến. Bảng phân trang, bản đồ dùng danh sách trong phạm vi đang chọn và chỉ vẽ tuyến được chọn.

WebSocket gửi tín hiệu refresh/heartbeat; frontend tải dữ liệu có phạm vi qua REST. Các yêu cầu refresh được gộp để không chồng lên nhau. Khi kết nối mất, có polling dự phòng. Đây chưa phải stream delta vị trí có replay cursor.

Cụm khu vực hiện dùng PostGIS DBSCAN: sự cố cùng loại, còn OPEN, mới tạo trong 10 phút, vị trí còn tương đối mới; bán kính 300 m, tối thiểu hai chuyến. Hệ tọa độ EPSG:32648 phù hợp vùng demo quanh TP.HCM. Không dùng cách chiếu này như thiết kế toàn cầu.

Các cụm cho thấy tín hiệu gần nhau, chưa chứng minh cùng một nguyên nhân. Vị trí dùng để gom cụm là vị trí gần đây của chuyến; lưu snapshot địa điểm sự cố và ID cụm bền vững là phần cần mở rộng.

## 10. Hiệu năng, chi phí và vận hành

1.000 xe gửi mỗi 3 giây tạo khoảng **333,33 GPS/giây**, tương đương **28,8 triệu bản tin/ngày** nếu chạy liên tục. Vì vậy khả năng nhận tải ngắn và chiến lược lưu dữ liệu dài hạn là hai vấn đề riêng.

Các biện pháp hiện tại gồm pool giới hạn theo tiến trình, xử lý theo lô, index phục vụ truy vấn chính, revision theo chuyến, không gọi LLM cho từng GPS, không tải mọi tuyến khi refresh và giới hạn số job LLM đồng thời.

Đo ít nhất bốn loại thời gian:

| Số đo | Dùng để trả lời |
|---|---|
| HTTP nhận GPS | API mất bao lâu để phản hồi |
| received-to-processed | Hàng đợi và Detector chậm bao lâu |
| incident-to-proposal | Planner/LLM mất bao lâu |
| incident-to-ack/action | Nhân viên và quy trình phản ứng mất bao lâu |

Bài tải hiện tại và ngưỡng của nó nằm trong [tài liệu 06](06-kiem-thu-tai-1000-xe.md). Kết quả thực đo nằm trong [tài liệu 07](07-ket-qua-kiem-thu-va-tai.md); không suy từ thông lượng GPS sang năng lực xử lý bão SOS hoặc hàng nghìn dashboard.

Chi phí cần tính riêng: API/worker/Planner, PostgreSQL và dung lượng/backup, Redis, Mapbox, mô hình LLM, nhà cung cấp SMS/call, truyền dữ liệu và nhân sự trực. Dùng mẫu dự phòng cho MVP, giới hạn đồng thời, đo token/độ trễ và gom sự cố hợp lệ giúp kiểm soát chi phí. Giá nhà cung cấp phải được kiểm tra tại thời điểm mua, không cố định trong thiết kế này.

## 11. Lộ trình nâng cấp giữ ổn định MVP

| Bước | Công việc | Điều kiện xác nhận |
|---|---|---|
| Hoàn thiện vận hành thử | Metrics/tracing, readiness worker, backup/restore, retention, kiểm thử trình duyệt | Có báo cáo lỗi/độ trễ và khôi phục được dữ liệu thử |
| Đánh giá detector | Bộ dữ liệu gắn nhãn, ngữ cảnh hành trình, heartbeat, giảm báo giả | Chỉ số theo loại rủi ro trên tập test độc lập |
| Nhiều đội xe | Tenant scope, phân công, lịch trực, audit đọc dữ liệu | Test không truy cập hoặc phát sự kiện chéo tenant |
| Mở rộng Detector | Partition theo trip_id, ownership/lease, replay/rebalance | Cùng chuyến không bị xử lý song song sai state |
| Mở rộng realtime | Event có phạm vi, snapshot + delta/cursor, backpressure | Reconnect phục hồi đúng và không lộ vị trí ngoài quyền |
| Kênh liên hệ thật | Adapter, action outbox, callback/UNKNOWN, đối soát | Retry không nhân đôi và mọi hành động có quyết định hợp lệ |
| AI nâng cao | Adapter mô hình, structured output, eval, anomaly model | Có cải thiện đo được so với rule/mẫu hiện tại |

Không cần tách microservices ngay chỉ để “sẵn sàng nâng cao”. Giữ hợp đồng dữ liệu, transaction và test tốt trước; tách một module khi có nhu cầu triển khai độc lập hoặc số liệu chứng minh cần thiết.

Fly.io là phương án đóng gói/triển khai đã có cấu hình tham khảo. Process groups chạy trên các Machine riêng; database và Redis là dịch vụ riêng. Không tăng số Detector/Planner khi khóa singleton và thứ tự state chưa được thiết kế lại. [Tài liệu Fly process groups](https://docs.fly.io/launch/processes).

## 12. Nghiệm thu và cách sử dụng bộ tài liệu

Một bản demo hoàn chỉnh cần chứng minh được: đăng nhập đúng quyền, nhận GPS, tạo từng loại sự cố, SOS không phụ thuộc LLM, phê duyệt đúng một lần, proposal hết hạn không thực thi, restart graph tiếp tục đúng, vị trí cũ có nhãn rõ và bài tải có báo cáo đọc được.

Bắt đầu thực hành tại [hướng dẫn 02](02-huong-dan-cai-dat-va-lap-trinh.md). Khi sửa code, dùng [quy ước 04](04-lam-viec-voi-codex.md). Quyết định kỹ thuật hiện tại được trình bày tại [tài liệu 05](05-ra-soat-kien-truc-mvp.md); công việc tiếp theo nằm ở [lộ trình 03](03-lo-trinh-phat-trien.md).

Mọi nội dung “cần bổ sung”, “nâng cấp” hoặc “chưa triển khai” trong tài liệu này là kế hoạch. Chỉ chuyển thành trạng thái đã có sau khi source, hướng dẫn sử dụng và kiểm chứng tương ứng đều được cập nhật.

