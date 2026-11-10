# SafeJourney — kiến trúc MVP, tối ưu và đường nâng cấp

**Cập nhật: 10/11/2026.** Tài liệu mô tả cấu trúc đang chạy. Kết quả xác nhận ở [07](07-ket-qua-kiem-thu-va-tai.md); hướng dẫn thao tác ở [02](02-huong-dan-cai-dat-va-lap-trinh.md).

## 1. Cách tổ chức hiện tại

SafeJourney giữ một codebase chia module, chạy **API, Detector và Planner riêng**. Cách này đủ đơn giản để học, cho phép tăng API workers và thay các adapter mà không cần tách ngay thành nhiều dịch vụ độc lập.

| Ranh giới | Sở hữu / trách nhiệm | Điểm mở rộng |
|---|---|---|
| app/api/auth.py + security.py | Phiên, đăng nhập, quyền vai trò/chuyến | OIDC, tenant, thiết bị |
| app/api/trips.py + schemas.py | Hợp đồng GPS/SOS và dữ liệu chuyến trả về | Batch ingestion, API version |
| db.py + migrations | Pool, transaction, thay đổi schema | Repository theo nghiệp vụ khi nhu cầu tăng |
| telemetry_policy.py | Đánh giá thời gian thuần, không I/O | Chính sách offline/clock skew |
| rules.py | Điều kiện rủi ro theo mẫu | Detector anomaly chạy song song có đánh giá |
| worker.py | Relay, Redis, batch xử lý, watchdog | Partition theo chuyến |
| planner.py | Graph và dispatch thường; chờ HITL cho nhánh khẩn | Planner adapter, claim job/lease |
| planner_context.py | Lọc số đo, giải thích bằng chứng, kiểm tra lựa chọn playbook | Thêm loại bằng chứng/bước xác minh có test; không chuyển văn bản tùy ý vào prompt |
| incident_ownership.py | Nhận/gia hạn/trả hồ sơ, kiểm tra chủ và phiên trong transaction | Queue/supervisor/tenant; giữ fencing qua nhiều API process |
| app/api/incidents.py | Quyết định, nhật ký, cụm khu vực | Action outbox và provider |
| response_playbooks.py + autoplaybooks.py | Mẫu nội dung, state machine, deadline và dispatch theo policy | Provider/outbox và timer chia partition |
| app/api/contacts.py | Phản hồi đúng người nhận, chống lặp | Callback có chữ ký và phiên xác nhận thiết bị |
| app/api/operations.py | Snapshot, quyền operator, UUID/lease/token, quota và lịch sử phân tích | Job queue/lease phân tán, quota toàn cụm và retention |
| operations/workflow.py + supervisor.py | Các node chuyên trách; LLM chỉ chọn ưu tiên, công cụ bắt buộc chạy | Điều phối trên dữ liệu thật có phiên bản, evaluation và ngân sách |
| operations/calculations.py + optimizer.py + spatial.py | Decimal, năng lượng/sạc, OR-Tools, H3 và OSRM có giới hạn | Hiệu chuẩn mô hình, provider tuyến, tối ưu theo vùng/cửa sổ |
| realtime.py | Thông báo refresh có xác thực | Event có phạm vi, snapshot/delta |
| frontend/src | UI, queue refresh, Mapbox | Phân trang server, cảnh báo và renderer lớn hơn |
| load_tests | Kiểm chứng tải độc lập | Soak, lỗi hạ tầng, bão SOS |
| research_benchmarks | Benchmark TLC ngoại tuyến theo vùng–giờ, đối soát tiền và provenance | Thêm tháng/mùa/nguồn phù hợp; không nối dữ liệu tùy tiện vào telemetry |

main.py ghép router, middleware, lifecycle và static UI. Không đưa nghiệp vụ mới vào một file main.py lớn. Chưa cần tạo thêm tầng abstraction chỉ để đổi tên các hàm đang rõ trách nhiệm.

## 2. Hợp đồng API cần giữ

| API | Quyền và hành vi |
|---|---|
| POST /api/login | Phiên cookie, 10 lần/10 phút theo username+IP; kiểm tra đồng thời trong DB |
| GET /api/me, POST /api/logout | Đọc/hủy phiên hiện tại |
| GET /api/trips | Scoped; include_route và active_only tùy chọn |
| GET /api/trips/{id} | Chi tiết tuyến trong phạm vi; không trả passenger_id |
| POST /api/trips/{id}/telemetry | Chỉ driver được phân công; durable sau commit |
| POST /api/trips/{id}/sos | Driver/passenger trong chuyến; UUID chống lặp |
| GET /api/incidents | Operator thấy hồ sơ; người tham gia chỉ thấy biên nhận SOS họ gửi |
| GET /api/incidents/{id} | Chỉ operator; đọc hồ sơ và proposal mới nhất độc lập với trang/hàng đợi |
| POST .../{id}/ack | Nhận quyền phụ trách độc quyền có hạn; retry cùng người trả cùng phiên |
| POST .../{id}/lease, .../release | Gia hạn hoặc trả hàng đợi; phải đúng owner, phiên và còn hạn |
| POST .../{id}/decision | Chủ còn quyền duyệt/từ chối proposal cụ thể còn hiệu lực |
| POST .../{id}/replan | Chủ còn quyền yêu cầu thay proposal hết hạn; trả 202 |
| POST .../{id}/resolve | Chủ còn quyền đóng có lý do; hủy proposal đang chờ và kết thúc phân công |
| GET .../{id}/timeline | Operator; tối đa 500 sự kiện mới nhất, trả theo thứ tự |
| GET /api/area-alerts | Chỉ operator |
| GET /api/ops/metrics | Chỉ operator; backlog, queue job NEW, pool của API đang trả lời |
| GET /api/health | Kiểm tra kết nối PostgreSQL; không xác nhận worker/Redis/LLM khỏe |
| GET /api/operations/scenarios | Chỉ operator, danh mục kịch bản cố định |
| POST /api/operations/plans | Chỉ operator; UUID + chuyến + kịch bản, backend dựng snapshot; không nhận số tiền/pin do client tùy ý |
| GET /api/operations/plans và .../{id} | Chỉ operator; lịch sử có giới hạn và báo cáo đã lưu |
| /ws | Cookie + Origin hợp lệ, kiểm tra phiên lại trong vòng lặp |

Trip không thuộc phạm vi trả 404 để không tiết lộ đối tượng. Hành động không thuộc vai trò trả 403. UUID tái sử dụng sai hoặc trạng thái quyết định không còn phù hợp trả 409. Schema sai trả 422. Không đổi các mã lỗi này thành “thành công rỗng” ở frontend.

TripView là response model xác định rõ những trường công khai. Dashboard gọi include_route=false và active_only=true; mặc định API vẫn cho phép client chủ động chọn phạm vi khác. Danh sách chuyến hiện trả toàn bộ tập được phép, còn 50 dòng/trang là phân trang phía browser. Khi số chuyến lớn hơn, cần phân trang/bộ lọc server và cách lấy snapshot bản đồ riêng.

## 3. GPS: bền vững, theo thứ tự và có bằng chứng

### 3.1. Ba mốc thời gian

- event_time: thời điểm thiết bị quan sát.
- received_at: PostgreSQL nhận bản tin.
- processed_at: cuối xử lý của Detector, trước commit transaction.

Độ trễ queue không biến một mẫu hợp lệ khi nhận thành STALE. Policy so event_time với received_at, rồi so với last_seen đã áp dụng.

| processing_result | Ý nghĩa |
|---|---|
| APPLIED | Mẫu được dùng cập nhật trạng thái |
| STALE | Thời gian quan sát nằm ngoài cửa sổ chấp nhận |
| OUT_OF_ORDER | Thời gian không mới hơn mẫu đã áp dụng |
| INACTIVE | Chuyến không còn hoạt động lúc xử lý |

API từ chối timestamp đi trước máy chủ quá TELEMETRY_FRESH_SECONDS. Mẫu quá cũ được giữ để đối chiếu nhưng không cập nhật last_received_at theo cách che mất GPS_LOST. Gói UUID trùng đúng nội dung vẫn được xác nhận sau khi chuyến FINISHED; gói mới trên chuyến không hoạt động bị rollback và trả 409.

seq được lưu để kiểm tra, chưa là cơ chế sắp xếp/reorder buffer. Nếu cần phục hồi chuỗi offline, thiết kế policy riêng thay vì bỏ kiểm tra thời gian.

### 3.2. Inbox/outbox và Redis

API lưu telemetry_inbox + telemetry_outbox trong cùng transaction. Relay chỉ đưa event_id lên Redis; payload nằm ở PostgreSQL. Nếu Redis lỗi, API vẫn có thể nhận bền vững khi DB hoạt động, nhưng backlog có thể tăng.

Relay có thể phát lại do crash hoặc do chưa thấy xử lý sau 30 giây. Detector dedupe theo UUID và processed_at, nên giao nhận là **at least once**, hiệu ứng dữ liệu được chặn lặp. Không tuyên bố exactly once cho mạng hay provider ngoài hệ thống.

Sau khi DB commit, worker ACK và XDEL trong một Redis transaction. Nếu thao tác Redis lỗi, việc đọc pending và relay sẽ thử lại; không xóa inbox phục vụ audit/idempotency.

### 3.3. Tối ưu đường nóng

- Một pool hữu hạn cho mỗi tiến trình; mở lười để import/unit test không tự kết nối DB.
- Batch tối đa 200 sự kiện; truy vấn geometry theo lô thay vì một vòng query cho mỗi điểm.
- Khóa chuyến theo thứ tự ổn định, rồi inbox, rồi sự cố để giảm vòng chờ khóa.
- Chỉ chọn các cột cần thiết ở điểm nhận telemetry, khóa quyền và watchdog.
- Update trạng thái cuối mỗi chuyến trong lô, tăng version theo chuyến; không khóa global version cho từng GPS.
- Redis group chỉ tạo/kiểm tra khi cần. Đọc pending sau startup/lỗi, quét claim theo cursor thay vì lặp nhiều lệnh ở mỗi vòng khỏe.
- Typed response cho danh sách chuyến; không serialize geometry khi include_route=false.
- Migration 003 bổ sung index cho danh sách sự cố ưu tiên, telemetry theo trip/thời gian và ứng viên leo thang.

Chỉ số benchmark phản ánh toàn cấu hình local hiện tại. Không suy ra phần trăm cải thiện riêng của từng thay đổi khi chưa có phép đo đối chứng cùng điều kiện.

## 4. Detector và mất GPS

STOP/DEVIATION/SPEED là rule thuần theo thời gian, dùng mẫu có accuracy từ hơn 0 đến 30 m. SPEED cần vượt SPEED_LIMIT_KMH + 10. Khoảng mất mẫu hơn 15 giây làm reset cửa sổ liên tục. DEVIATION dùng khoảng cách địa lý tới tuyến, ngưỡng ít nhất 100 m hoặc gấp đôi accuracy.

Rule phát sự cố khi mới chuyển sang điều kiện active; không tạo sự cố mới cho mỗi điểm đang vượt cùng ngưỡng. Mỗi chuyến/loại chỉ có một sự cố OPEN, còn tín hiệu được lưu để đối chiếu. Đóng sự cố khi điều kiện vẫn active không nhất thiết tạo lại ngay; cần hiểu semantics active_flags trước khi thay hành vi.

Watchdog dùng last_received_at hoặc thời điểm tạo chuyến, không dựa vào LLM. Vòng kiểm tra vẫn được thử khi Redis lỗi vì nằm ngoài nhánh đọc Redis. Tuy vậy, thời gian chờ mạng và retry trong cùng tiến trình có thể làm watchdog trễ hơn chu kỳ danh nghĩa; đây chưa phải tiến trình watchdog độc lập với bảo đảm thời hạn cứng.

MVP không suy đoán xe đang di chuyển khi mất GPS. UI giữ vị trí cuối và tuổi tín hiệu. GPS_LOST là “không có dữ liệu mới”, không kết luận có tai nạn.

## 5. Planner và giới hạn quyền thực thi

### 5.1. Graph và lịch xử lý

Graph: analyze → persist proposal. AUTO chạy SMS mô phỏng trong transaction rồi kết thúc job. HUMAN interrupt chờ người → đọc quyết định DB → kết thúc. Deadline của bước gọi/xác nhận/theo dõi nằm trong DB, do scheduler bảo trì tiếp.

- Mỗi job/proposal có ID riêng; replay trước checkpoint không tạo proposal thứ hai.
- PostgreSQL lưu checkpoint; khởi động lại có thể tiếp tục graph.
- Một lane dành cho mức 3 và một lane cho mức thường, tối đa hai job chạy đồng thời.
- Mỗi job có checkpointer/connection riêng, tránh chia sẻ lock làm tuần tự hóa LLM.
- Bảo trì nhắc ca trực/hết hạn chạy trong scheduler khoảng 2 giây, không đợi lời gọi LLM.
- Job đang chờ PENDING không chiếm cửa sổ runnable; nhiều hồ sơ chờ người không che công việc mới.
- Lỗi job có khoảng lùi trước retry; job khác vẫn được chọn.

Một lane khẩn vẫn có thể bận nếu nhiều SOS cùng đến hoặc LLM chậm. Bài tải GPS bình thường không đo sức xử lý bão SOS. Muốn nhiều Planner phải thêm claim/lease/fencing và test recovery; không chỉ tăng số process.

Adapter Ollama mặc định timeout đọc 60 giây để dành thời gian nạp model local; kết nối tối đa 3 giây và không kế thừa proxy terminal. Đây không phải deadline tổng tuyệt đối. Lỗi gọi/định dạng trả về mẫu dự phòng và log loại lỗi/status/thời gian, không log URL, prompt hay nội dung sự cố. Chi tiết cấu hình và kiểm chứng ngày 01/11 ở [02, mục 11.2](02-huong-dan-cai-dat-va-lap-trinh.md#g11).

Detector chụp ngưỡng và thời gian đã quan sát vào evidence lúc tạo/cập nhật sự cố. Planner đưa bản lọc bằng chứng vào graph khi bắt đầu job; không gửi tọa độ/định danh/văn bản tự do cho model. Căn cứ phát hiện được backend dựng từ số đo đó, còn model chọn evidence_keys/check_ids trong JSON schema giới hạn. Backend kiểm tra tham chiếu, giữ bước kiểm tra nền tảng và ưu tiên kênh an toàn cho SOS; không hiển thị lời kể/số đo do model tự tạo. Đề xuất đã lưu và checkpoint đang chờ người không tự viết lại khi đổi prompt; hồ sơ cũ thiếu số liệu được đánh dấu rõ.

### 5.2. HITL

Chỉ nhánh HUMAN yêu cầu phê duyệt. Backend kiểm tra operator, incident OPEN, proposal PENDING/HUMAN, đúng revision/mức độ và chưa hết hạn. Duyệt ghi mock_actions với unique proposal_id và cập nhật trạng thái trong cùng transaction. Từ chối chỉ thay trạng thái, không tạo action.

Trước các thao tác trên, backend kiểm tra owner hiện tại, hạn giữ quyền và assignment_version trong cùng transaction đã khóa chuyến → sự cố. Clock được đọc sau khóa để không cho request chờ lâu dùng thời gian cũ. Nhận/nhận lại/trả/đóng làm đổi phiên; gia hạn không đổi. acknowledged_at/by chỉ giữ lần tiếp nhận đầu, không cấp quyền mãi mãi. Xem [08](08-quy-trinh-operator-va-phan-cong.md) cho heartbeat, hàng đợi, bàn giao và các bước mở rộng vận hành.

Payload resume của graph chỉ đánh thức graph. Graph đọc quyết định đã lưu; nội dung LLM, lời người dùng trong bằng chứng hoặc dữ liệu resume không cấp quyền.

Proposal có TTL 15 phút. Yêu cầu replan chỉ chấp nhận proposal hết hạn phù hợp, đánh needs_plan, lưu người yêu cầu/thời gian và giữ proposal cũ trong nhật ký. Retry cùng yêu cầu được nhận như duplicate. Proposal mới luôn cần phê duyệt mới.

Nếu sự cố tăng mức khi model đang chạy, proposal dựa trên mức cũ không được gắn vào mức hành động mới. Nếu sự cố đã đóng, Planner không tạo đề xuất hoạt động nữa.

### 5.3. Agent thực hiện playbook thông thường

[autoplaybooks.py](../backend/app/autoplaybooks.py) chạy SMS mô phỏng cho cảnh báo thường, tối đa một bước gọi tiếp khi SMS không có phản hồi sau 120 giây. Sau 120 giây tiếp tục không phản hồi thì chuyển HUMAN/PENDING. [contacts.py](../backend/app/api/contacts.py) xác minh đúng người nhận: needs_help chuyển khẩn; safe theo dõi 60 giây và chỉ tự đóng khi tín hiệu mới nhất phù hợp. Chi tiết ở [08](08-quy-trinh-operator-va-phan-cong.md).

Luật lưu good_gps và current_conditions trong detector_state. Không dùng việc thiếu active_flags để kết luận an toàn: điều kiện có thể đang tích lũy chưa đủ ngưỡng hoặc GPS kém chất lượng. Khi đóng tự động phải có safe thật của người nhận, dữ liệu mới tối đa 30 giây, chất lượng tốt và điều kiện loại sự cố đã hết ở mẫu cuối.

Bảo trì lấy tối đa 100 hồ sơ đến hạn/lượt, recheck dưới khóa chuyến → sự cố → proposal, không ngủ một task cho mỗi người nhận. Dispatch chỉ nhận loại thường/mức dưới 3, người nhận đúng tài xế, mẫu chưa sửa và không có hồ sơ mức 3 cùng chuyến. Action AUTO ghi approved_by=NULL và policy rõ ràng, không giả danh người duyệt. Unique proposal_id và contact_replies.proposal_id/request_id chặn lặp. Đề xuất khẩn mới luôn PENDING; không phát tác động khẩn từ timeout hoặc LLM.

Một chuyến có thể có nhiều loại cảnh báo thường; chưa có quota liên hệ chung theo chuyến/người. Với backlog lớn, LIMIT 100 và singleton vẫn là nút thắt. Cần đo độ trễ timer thực tế, tỷ lệ chuyển HITL và thời gian tạo gói khi LLM chậm.

### 5.4. Ranh giới khi dùng provider thật

Hiện cả dispatch AUTO và quyết định HUMAN chỉ tạo **kết quả mô phỏng** trong DB. Trước khi thay bằng SMS/call thật cần action outbox có khóa idempotency, trạng thái SENT/FAILED/UNKNOWN, callback có xác thực và đối soát.

Không gọi provider trong transaction khóa chuyến/sự cố. Không tự retry hành động khẩn khi chưa biết lần trước đã gửi chưa. Approval phải gắn phiên bản/nội dung/người nhận/hạn, backend kiểm tra lại ngay trước khi dispatch. Đây là thiết kế mở rộng, chưa triển khai.

## 6. Frontend và realtime

### 6.1. Giảm xử lý không cần thiết

- Queue gộp refresh liên tiếp, không chạy nhiều lượt tải danh sách chồng nhau; còn yêu cầu đến trong lúc tải thì giữ lượt tiếp.
- [IncidentFilters.jsx](../frontend/src/IncidentFilters.jsx) tách nhóm xử lý/phụ trách/trạng thái; [incidentFilters.js](../frontend/src/incidentFilters.js) chuẩn hóa khi chuyển agent/lịch sử và tạo query. API kết hợp các điều kiện trước LIMIT/OFFSET, giữ assignment=unassigned/mine cũ và quyền biên nhận của người tham gia.
- Danh sách sự cố có vùng cuộn riêng, tối đa 65vh hoặc 650 px. Khung chi tiết giữ ID/snapshot riêng và đọc GET /api/incidents/{id}; nhận xử lý làm hồ sơ rời hàng đợi chưa phân công nhưng không làm mất chi tiết hoặc lý do đang nhập. Đổi trang/hàng đợi vẫn giữ lựa chọn; Bỏ chọn hồ sơ chỉ đóng khung xem.
- [incidentSelection.js](../frontend/src/incidentSelection.js) bỏ kết quả chậm của hồ sơ khác hoặc phiên/thời gian server cũ hơn. Lỗi tải chi tiết được báo riêng và tạm khóa thao tác; 403/404 xóa snapshot. Snapshot không cấp quyền: backend vẫn kiểm tra chủ, phiên và hạn tại mỗi lệnh ghi.
- apiList kiểm tra đúng kiểu mảng; response JSON lỗi không biến thành thành công giả.
- reconcileTrips giữ lại tham chiếu hàng/mảng không đổi; LiveMap được memo để không dựng lại GeoJSON chỉ vì đồng hồ tick.
- Mapbox dùng source điểm và tuyến riêng. Chọn tuyến không nạp lại tất cả vị trí; đồng hồ đổi expression màu dữ liệu cũ thay vì setData toàn bộ mỗi giây.
- Lỗi cụm và timeline được lưu riêng; refresh chuyến thành công không xóa lỗi vùng khác.
- SOS giữ UUID sau request thất bại để retry, tạo UUID mới sau lần server xác nhận.
- Khóa thao tác qua ref chặn nhấp hai lần trước khi React render trạng thái busy.
- Đồng hồ tuổi GPS và proposal expiry chạy độc lập với thành công request.

### 6.2. Giới hạn realtime hiện tại

WebSocket gửi refresh/heartbeat mỗi giây; server kiểm tra version từ PostgreSQL theo từng kết nối và xác thực lại phiên. Nó không truyền điểm vị trí nhạy cảm trong broadcast chung.

Frontend reconnect có backoff, kiểm tra lại tài khoản, dùng REST dự phòng mỗi 5 giây khi kênh không khỏe và đồng bộ định kỳ khi kênh khỏe. Cụm khu vực/timeline có nhịp riêng khoảng 15 giây.

Cách này phù hợp MVP nhưng số truy vấn DB tăng theo số WebSocket. Chưa có broker fanout theo tenant/trip, cursor hoặc replay event. Lộ trình nâng cấp là snapshot + delta có phạm vi, backpressure và giới hạn kết nối; giữ kiểm tra quyền ở cả subscribe lẫn đọc dữ liệu.

Mapbox được lazy load, nhưng bundle riêng còn lớn. Cần đo tác động mạng/render trên thiết bị thực trước khi quyết định thay thư viện hoặc thiết kế renderer khác.

## 7. Dữ liệu, index và migration

| Nhóm bảng | Vai trò |
|---|---|
| users, sessions, login_attempts | Đăng nhập, hạn phiên, giới hạn thử |
| trips | Tuyến, người tham gia, trạng thái, vị trí/cuối nhận, detector_state, version |
| telemetry_inbox, telemetry_outbox | Dữ liệu nhận bền vững, chống lặp, retry relay |
| incidents, incident_events | Hồ sơ và nhật ký |
| sos_events | UUID/actor liên hệ sự cố, phục vụ quyền xem biên nhận |
| proposals, mock_actions, contact_replies | Gói có revision, mode AUTO/HUMAN, deadline, hành động và phản hồi có xác thực |
| graph_jobs, bảng checkpoint | Công việc và trạng thái LangGraph |
| system_state, schema_migrations | Revision thay đổi nghiệp vụ, phiên bản schema |

Bảy migration hiện có: 001_mvp_scale, 002_proposal_renewal, 003_query_indexes, 004_incident_ownership, 005_operator_response_plans, 006_autonomous_playbooks và 007_operations_assessments. Nâng cấp tiếp bằng file số mới. Checksum ngăn thay đổi ngầm lịch sử schema; không sửa file cũ để migration “chạy lại”. Khi chuyển sang ownership, không chạy API cũ chưa có guard cùng API mới trong giai đoạn nhận lệnh.

Index tăng tốc truy vấn chọn lọc nhưng cũng tốn dung lượng/chi phí ghi. Benchmark dùng database tích lũy nhiều lần chạy; chưa có chính sách retention/partition tự động. Nhật ký hiện ở DB thông thường, chưa là kho lưu chống sửa đổi.

Pool max 16 là **mỗi process**. Hai API + Detector + Planner có thể dùng tối đa 64 kết nối pool, cộng kết nối guard/checkpointer và quản trị. Cần đối chiếu giới hạn PostgreSQL trước khi scale.

Login rate limit được kiểm tra và ghi dưới advisory transaction lock theo username+IP; scrypt không chạy trong khóa đó. Đây chưa thay thế rate limit gateway, MFA hoặc chống tấn công phân tán. Không tin header IP từ client nếu proxy chưa được cấu hình đúng.

## 8. Đóng gói và cấu hình

Local dùng [environment.yml](../environment.yml): Conda quản lý Python 3.12 và môi trường safejourney; pip cài thư viện theo requirements hiện có. Các process con của bộ tải dùng sys.executable nên kế thừa đúng Python được chọn. File môi trường không chứa prefix máy cá nhân và không phải lock đầy đủ dependency bắc cầu. Mỗi terminal Python cần kích hoạt safejourney.

Docker build hai giai đoạn, chỉ chép source runtime và frontend dist; không chép .env hoặc test. Chạy user 10001. requirements-dev tách pytest khỏi production. Node frontend được khóa bằng package-lock; các dependency Python trực tiếp được chỉ định trong requirements, chưa có lock đầy đủ cho mọi dependency bắc cầu/image digest.

fly.toml.example có web/detector/planner riêng và app.db làm release command. Không triển khai đồng thời hai bản singleton. Hướng dẫn dùng --ha=false và chiến lược immediate có thể gián đoạn; cần cải tiến lease trước khi triển khai worker rolling không downtime.

Health API chỉ kiểm tra DB. Muốn vận hành cần heartbeat tiến trình, metric backlog/tuổi, log có cấu trúc, cảnh báo lỗi và kiểm chứng backup. Không suy ra pipeline khỏe chỉ từ HTTP 200 của /api/health.

## 9. Bộ đo tải và tính truy nguyên

Bộ tải có lịch open-loop, mỗi tài xế dùng phiên thật, các request phát theo thời điểm dự kiến thay vì đợi response. Dropped vì trễ/quá tải được tính fail. Lịch dùng monotonic và kiểm tra lại deadline sau timer wake để không phát sớm.

Lấy mẫu trong lúc chạy chỉ đọc count/pending/tuổi; percentile chi tiết tính ở cuối. Mỗi tập số liệu được sort một lần để lấy nhiều percentile. Cách này giảm phần công việc do chính công cụ đo tạo ra.

Báo cáo schema 3 có fingerprint SHA-256 của nguồn tham gia đo và gate nguồn không thay đổi giữa đầu/cuối lượt chạy. Nó không khóa code, không chứa secrets, không thay Git commit và không chứng minh mọi dependency/máy đo giống nhau. Danh sách chính xác được chọn trong source_fingerprint().

Kết quả HTTP, xử lý DB và UI end-to-end là ba lớp khác nhau. Xem [06](06-kiem-thu-tai-1000-xe.md) để hiểu ranh giới mẫu và [07](07-ket-qua-kiem-thu-va-tai.md) cho số đo hiện tại.

## 10. Đường nâng cấp ít phải viết lại

1. Giữ API/schema/quyền/idempotency; mở rộng bằng trường và migration tương thích.
2. Tách adapter LLM/provider khi có implementation thứ hai và yêu cầu vận hành rõ.
3. Đo query/CPU/queue trước khi tăng tài nguyên hoặc tách dịch vụ.
4. Chia Detector theo trip khi một process thật sự không đủ, giữ ordering và owner.
5. Thay polling revision bằng event delta theo phạm vi khi số người xem tăng.
6. Bổ sung tenant, retention và audit phù hợp trước khi sử dụng dữ liệu thật.
7. Chạy test mất kết nối/replay/duyệt lặp trên staging trước mọi tích hợp hành động thật.

Những bước này là công việc tiếp theo; không phải các tính năng đã hoàn tất trong MVP.

Phân tích cụ thể cho **1.000.000 xe đồng thời** ở [mục 7 báo cáo 07](07-ket-qua-kiem-thu-va-tai.md#million-vehicles): công thức tải, các giới hạn singleton/DB/realtime, thay đổi ownership và dedupe khi partition, ưu tiên SOS/HITL, retention và lộ trình kiểm chứng. Đây là mục tiêu cần phát triển; bài tải 1.000 xe PASS không xác nhận công suất một triệu xe.

## 11. Ranh giới của kiểm tra vận hành

Phần mới ở [09](09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md) chạy theo yêu cầu operator, tách khỏi đường xử lý từng GPS. Graph chuyên trách là các node trong cùng tiến trình. Quyền thực thi sự cố vẫn thuộc policy/backend hiện có; không có cạnh từ kết quả cước, pin hoặc solver sang hành động khẩn.

API chụp đầu vào trong transaction ngắn rồi nhả khóa trước khi gọi model/định tuyến/solver. Migration 007 lưu snapshot, trạng thái, báo cáo, token và lease. UUID đã hoàn thành trả lại báo cáo cũ; token chặn worker bị thay thế ghi đè. Lease hết hạn/lượt lỗi có thể retry trên snapshot cũ, nhưng chưa có daemon tự khôi phục job. Trước tác động thật trong tương lai phải đọc lại dữ liệu mới và tái kiểm tra ràng buộc.

Giới hạn hiện tại là 2 lượt tính/API process, 1 lượt còn lease/tài khoản và 10 lượt mới/phút/tài khoản. OR-Tools tối đa 100 xe × 100 yêu cầu; kịch bản UI chỉ dùng 4 xe và tối đa 10 yêu cầu. H3 helper giới hạn 20.000 điểm. OSRM có deadline/kích thước phản hồi và kiểm tra dữ liệu; lỗi dịch vụ cấu hình chặn phân xe. Các giới hạn này giảm công việc trên API, chưa thay queue/quota phân tán hoặc bằng chứng tải hỗn hợp.

Năng lượng và tiền được tính bằng công cụ Decimal; các số đo khoảng cách/thời gian giữ độ chính xác đầu vào đến lúc kiểm tra, chỉ làm tròn khi hiển thị hoặc khi solver cần chi phí nguyên. Phương án solver ưu tiên số yêu cầu phục vụ rồi chi phí đón; không tối ưu cả ca. Không tuyên bố tiết kiệm chi phí thực tế chỉ từ kết quả kịch bản.

Forecast TLC trong [10](10-du-lieu-thuc-va-benchmark.md) là CLI ngoại tuyến, có dữ liệu thực và chia tập theo thời gian. Runtime hiện dùng số đếm nhu cầu mô phỏng và ô H3. Khi tích hợp forecast thật, cần contract riêng cho vùng, cửa sổ thời gian, độ mới, phiên bản model và sai số; không dùng mã taxi zone như tọa độ hoặc nhãn sự cố.

