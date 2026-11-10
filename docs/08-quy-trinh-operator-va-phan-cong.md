# SafeJourney — agent tự xử lý, xác nhận người nhận và HITL

**Cập nhật: 10/11/2026.** Agent phụ trách hồ sơ thông thường. Operator tập trung vào tình huống khẩn và can thiệp ngoại lệ. Tất cả SMS/cuộc gọi/hành động hỗ trợ vẫn là **mô phỏng**, không gửi ra bên ngoài. [Báo cáo 07](07-ket-qua-kiem-thu-va-tai.md) phân biệt kiểm thử chức năng, tải và các giới hạn.

## 1. Agent làm gì thay operator?

Agent chuẩn bị nội dung, chọn người nhận từ dữ liệu chuyến, chạy bước liên hệ được policy cho phép, chờ phản hồi, đối chiếu GPS và chuyển bước. Operator không phải nhận hay duyệt từng SMS/cuộc gọi thông thường.

| Tình huống | Agent thực hiện | Khi nào cần operator? |
|---|---|---|
| STOP/SPEED/DEVIATION/GPS_LOST mức dưới 3 | SMS mô phỏng cho tài xế được phân công, chờ xác nhận | Chỉ khi chuyển nhánh khẩn hoặc người trực chủ động can thiệp ngoại lệ |
| Sau SMS 120 giây chưa trả lời | Tạo và chạy cuộc gọi mô phỏng, chờ thêm 120 giây | Chưa cần duyệt bước gọi |
| Sau hai lần liên hệ chưa trả lời | Nâng mức 3, chuẩn bị gói HUMAN/PENDING | Operator đánh giá; không mặc định đã xảy ra tai nạn |
| Người nhận chọn “Tôi cần hỗ trợ” | Chuyển ngay mức 3, chuẩn bị gói chưa duyệt | Hành động khẩn phải qua HITL |
| Người nhận chọn an toàn | Theo dõi 60 giây rồi kiểm tra tín hiệu mới nhất | Tự đóng nếu đủ điều kiện; chuyển HITL nếu vẫn bất thường hoặc thiếu dữ liệu |
| SOS hoặc mức 3 từ đầu | Đưa vào nhánh khẩn và chuẩn bị đề xuất | Không tự gọi/nhắn người gửi SOS hoặc lực lượng khẩn |
| Cùng chuyến có hồ sơ mức 3 đang mở | Dừng bước thông thường tiếp theo và chuyển đánh giá khẩn | Không tự đóng hồ sơ thường khi đang có tình huống khẩn cùng chuyến |

Các mốc 120/120/60 giây nằm trong policy hiện tại ở [autoplaybooks.py](../backend/app/autoplaybooks.py) và [contacts.py](../backend/app/api/contacts.py), chưa phải cấu hình qua .env hoặc SLA. Scheduler kiểm tra khi chạy; máy bận hoặc Planner dừng có thể làm xử lý trễ hơn deadline.

Để tự đóng, phải có phản hồi **safe của đúng người nhận đã đăng nhập**, hết 60 giây theo dõi, GPS mới không quá 30 giây, chất lượng GPS tốt và điều kiện tương ứng không còn ở mẫu mới nhất. Đây là kiểm tra tại lúc hết thời gian, chưa chứng minh tín hiệu an toàn liên tục suốt 60 giây. Thiếu dữ liệu không được coi là an toàn. Hồ sơ khẩn không tự đóng bằng phản hồi safe.

### Ba loại xác nhận khác nhau

- **Đã tạo hành động mô phỏng:** có bản ghi mock_actions; chưa chứng minh SMS/cuộc gọi đã tới người nhận.
- **Người nhận xác nhận:** tài xế/khách đúng người nhận gửi safe hoặc needs_help qua API có xác thực. Operator không được giả phản hồi này.
- **Operator phê duyệt:** cho phép thực hiện đúng gói khẩn đang xem; không phải xác nhận hành trình đã an toàn.

Playbook thường hiện gửi cho **tài xế**. API hỗ trợ vai trò driver/passenger nhưng luôn đối chiếu người nhận cụ thể; khách không thể trả lời yêu cầu gửi cho tài xế. Khách vẫn gửi SOS theo quyền chuyến. Chưa có playbook tự chọn/chuyển giữa tài xế và khách, callback nhà cung cấp hay giao tiếp qua SMS thật.

### Phần nào dùng LLM?

LangGraph điều phối công việc ban đầu. LLM tùy chọn chọn bước xác minh trong danh sách giới hạn trên bằng chứng đã lọc. Backend dựng nội dung theo mẫu và kiểm soát toàn bộ quyền thực thi, deadline, số lần liên hệ và điều kiện chuyển bước. Agent đã thực thi quy trình nhiều bước; không phải LLM tự do viết thông điệp hoặc tự cấp quyền khẩn. Lượt gọi model ban đầu vẫn có thể làm chậm việc tạo gói; Detector và tiếp nhận SOS không chờ model.

## 2. Thao tác chủ yếu bằng nút bấm

### 2.1. Người nhận

1. Đăng nhập driver của chuyến có cảnh báo thường. Khu vực yêu cầu xác nhận hiển thị nội dung và kênh mô phỏng.
2. Chỉ khi đã dừng ở nơi an toàn, chọn đã an toàn hoặc **Tôi cần hỗ trợ**. Không yêu cầu tài xế thao tác khi đang lái.
3. Sau xác nhận, yêu cầu rời danh sách. Safe bắt đầu theo dõi; needs_help chuyển khẩn. Nếu request lỗi mạng, nút thử lại giữ UUID; server chặn phản hồi trùng hoặc mâu thuẫn.

### 2.2. Operator

1. Dashboard mặc định mở **Cần nhân viên**. **Agent tự xử lý** là hàng đợi quan sát; không cần tiếp nhận từng ca thường.
2. Chọn hồ sơ khẩn, đọc mức độ, nội dung soạn sẵn, người nhận và bằng chứng/checklist khi cần.
3. Bấm **Nhận xử lý khẩn**, rồi **Duyệt gói xử lý mô phỏng** hoặc **Từ chối**. Nhận quyền không phải phê duyệt. Duyệt không tự đóng hồ sơ.
4. Nếu có kết quả xác minh tiếp, chọn **chưa liên hệ được** hoặc **cần hỗ trợ** để chuẩn bị bước mới. Bước khẩn mới vẫn chờ duyệt riêng.
5. Khi kết thúc, chọn kết quả đã thực sự xác minh từ danh sách rồi **Xác nhận và đóng sự cố**. Khi bàn giao, chọn lý do rồi xác nhận trả hàng đợi. Không tự chọn sẵn “an toàn”.
6. Chỉ trường hợp đặc biệt mới mở sửa nội dung hoặc chọn lý do riêng để nhập tay. Bản sửa tăng revision; phải đọc lại trước khi duyệt. Không chỉnh người nhận tùy ý trên UI.

Can thiệp một hồ sơ agent đang xử lý sẽ chuyển nó sang nhánh đánh giá khẩn và dừng tự động. Không dùng nút này để biến mọi cảnh báo thường thành công việc thủ công.

Mỗi hồ sơ HITL chỉ có một người phụ trách còn hiệu lực. Người khác xem được nhưng không duyệt/sửa/đóng. Backend kiểm tra owner, assignment_version, thời hạn, proposal_revision, trạng thái và mức độ; HTTP trực tiếp không bỏ qua được các kiểm tra. Hành động lưu bản chụp nội dung/người nhận/revision đã duyệt và có unique proposal_id chống tạo lặp.

Danh sách sự cố cuộn riêng. Đổi trang/hàng đợi vẫn giữ hồ sơ và nội dung đang nhập. Hồ sơ chi tiết được tải độc lập; lỗi tải khóa thao tác tới khi xác nhận lại. **Bỏ chọn hồ sơ** chỉ đóng khung xem, không đóng sự cố hoặc trả quyền.

Role operator hiện xem toàn bộ dữ liệu demo; tenant/tổ chức chưa triển khai. Driver/passenger không nhận bằng chứng, lịch sử hoặc dữ liệu phân công nội bộ qua API xác nhận.

### 2.3. Bộ lọc hàng đợi

Nhóm xử lý và phân công là hai tiêu chí riêng, có thể kết hợp. Bộ lọc được áp dụng tại server trước LIMIT/OFFSET, không chỉ lọc 100 dòng đã tải về.

| Tiêu chí | Lựa chọn | Ý nghĩa |
|---|---|---|
| Nhóm xử lý | Cần nhân viên / Agent tự xử lý / Tất cả | Hồ sơ khẩn đang mở / ca thường agent đang theo dõi / phạm vi chung và lịch sử |
| Phụ trách | Không giới hạn / Chưa có người phụ trách / Tôi phụ trách | Quyền phụ trách đang có hiệu lực; hết hạn được tính là chưa có người phụ trách |
| Trạng thái | Đang mở / Đã đóng / Mọi trạng thái | Chọn được trong nhóm Tất cả; hai nhóm xử lý luôn là hồ sơ đang mở |

Mặc định là **Cần nhân viên + Không giới hạn + Đang mở**. Ví dụ chọn Cần nhân viên + Chưa có người phụ trách để tìm ca khẩn cần người nhận; chọn Tất cả + Đã đóng để tra cứu kết quả. Nhóm Agent tự xử lý khóa phân công vì các bước thường không yêu cầu operator nhận hồ sơ. Chuyển sang lịch sử tự bỏ phân công đang mở, tránh tổ hợp Tôi phụ trách + Đã đóng không có ý nghĩa.

**Về mặc định** đặt lại cả ba tiêu chí. Đổi bộ lọc đưa danh sách về trang 1 và giữ hồ sơ/nội dung đang xem ở khung chi tiết. Dòng tóm tắt hiển thị điều kiện đang áp dụng; số hồ sơ là số trên trang, không phải tổng toàn hệ thống. Xem [ảnh bộ lọc](benchmarks/queue-filters-20261102.png).

## 3. Thời hạn quyền phụ trách và mất kết nối

INCIDENT_LEASE_SECONDS trong backend/.env mặc định **300 giây**, chấp nhận từ 30 tới 3.600 giây. Nếu không đặt biến, backend dùng mặc định.

Khi hồ sơ đang được chọn và tab hiển thị, frontend tự gia hạn khoảng mỗi 60 giây ở cấu hình mặc định; với thời hạn ngắn hơn, nhịp gia hạn bằng một phần ba thời hạn. Chuyển sang hồ sơ khác, đóng tab hoặc tab bị ẩn sẽ dừng gia hạn hồ sơ cũ. Quyền còn hiệu lực tới hạn đã cấp, không bị thu hồi ngay khi mất một request.

Nếu gia hạn lỗi, giao diện khóa thao tác cho tới khi xác nhận lại. Quyền đã hết hạn không được gia hạn để hồi sinh phiên cũ; phải nhận lại hồ sơ. Đồng hồ trình duyệt chỉ dùng hiển thị, có hiệu chỉnh từ server_time và thời gian đã trôi qua; backend quyết định bằng đồng hồ database.

Nên **trả hồ sơ về hàng đợi trước khi đổi ca/đăng xuất**. Nếu quên, hồ sơ có thể còn bị giữ tới hết thời hạn. Heartbeat chỉ cho biết tab còn hoạt động; chưa chứng minh nhân viên thực sự đang xử lý. Cơ chế giám sát ca trực và supervisor thu hồi khẩn là phần cần bổ sung trước vận hành thực tế.

## 4. Vì sao hai operator không cùng sửa một hồ sơ?

Trạng thái nằm trong PostgreSQL, không nằm trong bộ nhớ của một API process:

| Trường | Ý nghĩa |
|---|---|
| assigned_operator_id / assigned_at | Người phụ trách và lúc nhận quyền hiện tại |
| assignment_expires_at | Hạn hiệu lực của quyền phụ trách |
| assignment_version | Mã thế hệ tăng mỗi lần nhận mới, trả hoặc đóng |
| unassigned_since | Mốc trở lại hàng đợi sau khi chủ động trả |
| acknowledged_at / acknowledged_by | Lần tiếp nhận đầu tiên trong lịch sử; không phải quyền phụ trách hiện tại |

Các API thay đổi hồ sơ khóa theo thứ tự chuyến → sự cố → proposal nếu cần. Nhận xử lý, kiểm tra quyền, thay đổi dữ liệu và ghi audit nằm trong transaction. Hai yêu cầu nhận đồng thời phải chờ cùng hàng database; yêu cầu thứ hai đọc trạng thái mới rồi bị từ chối nếu đã có chủ. Khóa hàng được PostgreSQL quản lý giữa các kết nối/tiến trình. [PostgreSQL 16 — Row-level locks](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS)

Backend đọc clock_timestamp() **sau khi lấy khóa** để kiểm tra thời hạn; không lấy thời gian bắt đầu transaction làm căn cứ khi đã chờ khóa lâu.

Mọi thao tác tiếp theo gửi assignment_version đã đọc. Ví dụ A giữ phiên 1, trả hồ sơ; B nhận phiên 3; sau đó A nhận lại phiên 5. Request chậm từ màn hình phiên 1 vẫn bị chặn dù lúc này A lại là người phụ trách. Đây là cách ngăn màn hình cũ ghi vào lần phân công mới.

Retry nhận khi cùng người vẫn giữ quyền còn hạn trả cùng phiên, không ghi thêm lần nhận. Gia hạn giữ nguyên phiên và không tạo audit cho mỗi heartbeat. Duyệt vẫn có unique proposal_id trong mock_actions, chỉ tạo một kết quả mô phỏng. Kết quả thực thi ghi người duyệt và phiên phân công trong payload/audit.

## 5. API cho client

Endpoint ghi yêu cầu cookie phiên và kiểm tra Origin khi có. Nhánh operator yêu cầu quyền phụ trách còn hạn; API xác nhận yêu cầu đúng người nhận của chuyến.

| Endpoint | Body/tham số | Hành vi |
|---|---|---|
| GET /api/incidents | assignment=human / agent / all; owner=all / unassigned / mine; status=all / open / resolved; limit, offset | Các tiêu chí kết hợp bằng AND trước phân trang; human là mức 3 đang mở |
| GET /api/incidents/{id} | Không | Chi tiết mới nhất, gói xử lý, lựa chọn kết thúc/bàn giao |
| POST .../{id}/ack | {} | Nhận độc quyền; can thiệp ca tự động sẽ chuyển HITL |
| POST .../{id}/lease | assignment_version | Gia hạn quyền còn hiệu lực |
| POST .../{id}/release | assignment_version, reason_code; reason khi other | Bàn giao có audit |
| POST .../{id}/decision | assignment_version, proposal_id, proposal_revision, approve | Duyệt/từ chối đúng bản gói HUMAN đang chờ, chưa hết hạn |
| POST .../{id}/proposal-edit | assignment_version, proposal_id, proposal_revision, message | Sửa nội dung ngoại lệ; tăng revision và ghi trước/sau |
| POST .../{id}/prepare | assignment_version, proposal_id | Chuẩn bị gói cho proposal cũ chưa có response_plan; không duyệt |
| POST .../{id}/follow-up | assignment_version, proposal_id, request_id UUID, outcome=no_response/needs_help | Kết quả operator đã xác minh; tạo tối đa một bước tiếp theo cho proposal nguồn |
| POST .../{id}/replan | assignment_version, proposal_id | Yêu cầu thay proposal hết hạn; không phê duyệt |
| POST .../{id}/resolve | assignment_version, reason_code; reason khi other | Đóng hồ sơ, hủy đề xuất chờ, kết thúc quyền phụ trách |
| GET /api/contact-requests | Không | Chỉ yêu cầu mới nhất đang chờ đúng tài xế/khách nhận |
| POST /api/contact-requests/{proposal_id}/reply | request_id UUID, outcome=safe/needs_help | Xác nhận của người nhận, idempotent; operator không được gọi thay |

API vẫn nhận assignment=unassigned/mine cũ. Các giá trị mặc định assignment=all, owner=all, status=all giữ hành vi GET cũ. Bộ lọc operator không được mở rộng quyền đọc của driver/passenger.

Client mới phải gửi proposal_revision của gói đang hiển thị. Proposal cũ chưa có gói vẫn được backend hỗ trợ; UI yêu cầu chuẩn bị gói để đọc trước khi duyệt. Nội dung đã duyệt không được chỉnh lại. Không tự tăng phiên hoặc kéo dài thời hạn ở client.

Sai role trả 403; không có quyền với đối tượng có thể trả 404; phiên/revision cũ, phản hồi mâu thuẫn hoặc trạng thái không còn phù hợp trả 409; schema/lựa chọn sai trả 422. Tên trường và giới hạn chính xác ở [schemas.py](../backend/app/schemas.py).

## 6. Sự cố khẩn mất người phụ trách

Lần tiếp nhận đầu tiên không được dùng để tắt nhắc ca trực vĩnh viễn. Với mức 3:

- Chưa từng có chủ: tính từ created_at; ca thường vừa chuyển khẩn tính lại từ unassigned_since tại lúc chuyển.
- Chủ động trả hồ sơ: tính lại từ unassigned_since.
- Quyền hết hạn: tính từ assignment_expires_at.

Planner nhắc ca trực mô phỏng sau 30/60 giây không có chủ còn hiệu lực, một lần cho mỗi mốc trong từng thế hệ phân công. Việc này không tự gọi công an/cứu hộ. Nếu Planner dừng, việc nhắc có thể dừng; quyền API vẫn hết hạn và nhận lại được vì được kiểm tra trực tiếp tại database.

## 7. Chạy thử với hai tài khoản

Seed hiện có operator và operator2, cùng dùng DEMO_PASSWORD của môi trường demo. Đăng nhập bằng hai hồ sơ trình duyệt khác nhau hoặc một cửa sổ thường và một cửa sổ riêng tư. Hai tab dùng chung cookie trình duyệt không phải hai phiên tài khoản độc lập.

1. Hai người cùng mở một sự cố chưa có chủ.
2. Cùng bấm Nhận xử lý: một người nhận, người còn lại thấy thông báo xung đột.
3. Người không phụ trách chỉ xem được; không có nút duyệt/đóng.
4. Người phụ trách chọn lý do bàn giao, trả hồ sơ; người kia nhận lại.
5. Thử thao tác từ màn hình cũ: backend chặn phiên cũ.
6. Đóng/ẩn tab của người phụ trách, đợi quyền hết hạn; người khác nhận được hồ sơ.

Đây là tài khoản học tập. Production cần danh tính và mật khẩu riêng cho từng nhân viên, xác thực phù hợp và quyền theo tổ chức.

## 8. Nâng cấp dữ liệu và mở rộng

Các migration [004](../backend/migrations/004_incident_ownership.sql), [005](../backend/migrations/005_operator_response_plans.sql), [006](../backend/migrations/006_autonomous_playbooks.sql) lần lượt bổ sung quyền phụ trách, gói xử lý có phiên bản và trạng thái tự động/phản hồi người nhận. Không sửa migration đã áp dụng. Không xóa database/volume để nâng cấp.

[007](../backend/migrations/007_operations_assessments.sql) bổ sung lịch sử phân tích vận hành độc lập. Bản nâng cấp cần cập nhật thư viện trong Conda trước khi khởi động API; thực hiện [09, mục 2](09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md#2-cập-nhật-project-đã-cài-từ-trước). Migration mới không biến báo cáo vận hành thành proposal sự cố và không đổi điều kiện HITL.

**Dừng API, Detector và Planner cũ** trong các terminal của bạn, rồi chạy trong Anaconda PowerShell Prompt:

~~~powershell
Set-Location 'D:\SafeJourney'
conda activate safejourney
Set-Location backend
python -m app.db
~~~

Sau đó khởi động lại ba tiến trình theo [hướng dẫn 02](02-huong-dan-cai-dat-va-lap-trinh.md#g07), cập nhật frontend bằng npm.cmd run dev hoặc build mới nếu dùng bản static. Không chạy đồng thời API cũ thiếu guard với bản mới. Đã áp dụng migration trên DB kiểm thử; database demo riêng của bạn vẫn cần chạy lệnh này.

Proposal cũ mặc định HUMAN, không tự phát lại thành cuộc gọi/SMS sau migration. Hồ sơ và quyết định cũ được giữ. Khi thử luồng mới, dùng sự cố mới của dữ liệu giả; không trông chờ proposal đã lưu tự thay đổi.

Deadline và phản hồi nằm trong PostgreSQL. Lượt bảo trì lấy tối đa 100 hồ sơ đến hạn, kiểm tra lại trong transaction theo thứ tự chuyến → sự cố → proposal. Không giữ một coroutine ngủ cho mỗi người nhận; SMS/cuộc gọi tối đa hai bước thường mỗi hồ sơ. Retry/restart không tự gửi lặp một proposal. Khi Planner dừng, lịch chuyển bước dừng và tiếp tục từ deadline khi chạy lại.

Để tiến tới một triệu xe còn cần: chia ownership/lease cho Planner và timer, queue theo tenant/vùng, quota liên hệ theo người/chuyến, gộp cảnh báo liên quan, ưu tiên SOS, outbox/provider có idempotency và callback xác thực. Hiện giới hạn hai lần liên hệ là **mỗi hồ sơ**, chưa chống nhiều loại sự cố cùng liên hệ một tài xế. Phải đo bão cảnh báo/phản hồi/hết hạn, không suy ra từ tải GPS bình thường. Giữ singleton Detector/Planner cho tới khi kiến trúc chia tải được triển khai và kiểm chứng.

## 9. Source và kiểm chứng

- [planner.py](../backend/app/planner.py): LangGraph, lưu và chạy bước đầu, scheduler bảo trì.
- [autoplaybooks.py](../backend/app/autoplaybooks.py): SMS → gọi → HITL; đối chiếu tín hiệu trước tự đóng.
- [response_playbooks.py](../backend/app/response_playbooks.py): nội dung, người nhận và mã lý do.
- [contacts.py](../backend/app/api/contacts.py): phản hồi đúng người nhận, chống lặp và phân quyền.
- [incidents.py](../backend/app/api/incidents.py), [incident_ownership.py](../backend/app/incident_ownership.py): HITL, revision, owner/phiên/hạn và audit.
- [OperatorAssist.jsx](../frontend/src/OperatorAssist.jsx): gói có sẵn, ngoại lệ nhập tay và kết thúc bằng lựa chọn.
- [test_autoplaybooks_integration.py](../backend/tests/test_autoplaybooks_integration.py), [test_operator_assist_integration.py](../backend/tests/test_operator_assist_integration.py): kiểm chứng transaction/đồng thời/trạng thái/quyền trên PostgreSQL thật.

Ngày 02/11: đã chạy Chrome với driver xác nhận cần hỗ trợ → operator nhận và duyệt → chọn kết quả đóng, dùng hai API workers và Planner/Detector thật, LLM mock. Bằng chứng ở [07](07-ket-qua-kiem-thu-va-tai.md) và [ảnh UI](benchmarks/autonomous-playbooks-20261102.png). Không có cuộc gọi/SMS ngoài hệ thống.

## 9. Phối hợp với agent kiểm tra vận hành

Dashboard có thêm khu vực **Agent kiểm tra vận hành** cho operator, mô tả ở [09](09-dieu-phoi-van-hanh-va-cong-cu-xac-dinh.md). Operator chọn chuyến/kịch bản rồi bấm chạy; các công cụ tự tính cước, pin, thời gian sạc/chờ và phương án phân xe. Báo cáo hiện chỉ tư vấn trong dữ liệu mô phỏng, không gửi liên hệ, hoàn tiền hoặc giao đơn.

Nếu snapshot ghi nhận chuyến có hồ sơ mở mức 3, graph chặn phân xe mô phỏng và nhắc ưu tiên HITL hiện có. Không đóng hồ sơ sự cố vì báo cáo vận hành hoàn tất, không xem một phương án đủ pin như xác nhận tài xế/khách an toàn. Báo cáo cũ giữ dữ liệu thời điểm chụp; sự cố mới phát sinh vẫn phải theo hàng đợi khẩn riêng.

Quy trình ca thường vẫn tự động SMS → gọi, tối đa hai lần liên hệ, chờ đúng người nhận trả lời và đối chiếu GPS. Operator không phải duyệt các bước ca thường; chỉ nhánh khẩn cần HITL. Việc thêm công cụ tính toán không thay đổi nguyên tắc này.
