# Bộ sinh màn chơi và benchmark Bloxorz

## Cài đặt và chạy

```bash
uv sync --group dev --extra benchmark
uv run bloxorz-benchmark verify --corpus benchmarks/v1
uv run bloxorz-benchmark run --corpus benchmarks/v1 --output results/danh-gia --partition evaluation
uv run bloxorz-benchmark report --corpus benchmarks/v1 --results results/danh-gia --output results/bao-cao
```

Mở `results/bao-cao/bao-cao.md`. Báo cáo gồm 10 hình, mỗi hình có SVG và PNG 300 DPI, cùng dữ liệu thô trong `data/`. Tiêu đề, trục, chú giải và giải thích bằng tiếng Việt. Các tên thuật toán và khóa JSON giữ tiếng Anh để thuận tiện tích hợp. Không cần Pygame, trình duyệt hoặc kết nối mạng để chạy benchmark và tạo hình sau khi cài dependencies.

Runner giới hạn tài nguyên hiện hỗ trợ Linux. Thư mục đầu ra của `generate` và `run` phải chưa tồn tại để tránh ghi đè thí nghiệm. Lệnh `report` có thể ghi lại báo cáo từ kết quả cũ; không chạy solver.

Chạy nhanh 12 màn cố định:

```bash
uv run bloxorz-benchmark run --corpus benchmarks/v1 --output results/kiem-tra-nhanh --partition ci --repeats 1
```

Đo cả tập phát triển, đánh giá và vô nghiệm:

```bash
uv run bloxorz-benchmark run --corpus benchmarks/v1 --output results/toan-bo --partition all
```

Các tùy chọn: `--timeout 10`, `--memory-mib 1024`, `--repeats 3`, `--seed 42`, `--solvers bfs dfs ucs astar`. Giới hạn thời gian áp dụng cho phần tìm kiếm; tiến trình cha có thêm 5 giây dự phòng để khởi động, tải màn và kiểm tra kết quả. Giới hạn bộ nhớ là `RLIMIT_AS` cho toàn bộ không gian địa chỉ tiến trình, **không phải** giới hạn RSS hay đỉnh bộ nhớ Python được vẽ.

## Tái tạo và mở rộng dữ liệu

```bash
uv run bloxorz-generate --config configs/benchmark.json --output results/corpus-tai-tao
uv run bloxorz-generate --config configs/benchmark-smoke.json --output results/corpus-nho
```

Cấu hình chính yêu cầu 360 màn giải được và 20 màn vô nghiệm. Cấu hình nhỏ yêu cầu 36 màn giải được và 2 màn vô nghiệm. Mỗi bộ có seed, cấu hình và phiên bản bộ sinh trong `manifest.json`. Tái tạo cùng cấu hình, mã nguồn và môi trường cho cùng nội dung; khi nâng phiên bản Python hoặc bộ sinh, ưu tiên dùng corpus đã đóng băng thay vì chỉ dựa vào seed.

Bốn nhóm cơ chế:

1. **Ô thường:** khắc các ô đỡ từ bước lăn hợp lệ rồi thêm nhánh, hoặc sinh phòng/hành lang và địa hình ngẫu nhiên.
2. **Ô dễ vỡ:** với đường đi được khắc, chỉ đặt ô dễ vỡ ở vị trí không đứng thẳng trên đường chứng kiến. Các dạng khác được lọc bằng solver tham chiếu.
3. **Công tắc và cầu:** hai đảo được nối bởi cầu ban đầu đóng; công tắc nhẹ/nặng dùng hiệu ứng toggle hoặc set-open. Vị trí bắt đầu, đích, công tắc và cầu thay đổi theo seed.
4. **Tách khối:** đảo bắt đầu tách rời khu đích; công tắc chuyển hai khối tới hai vị trí khác nhau, cần di chuyển và hợp nhất. Hai vị trí xuất hiện giữ thứ tự A/B.

Trong nhóm cơ chế, cấu hình `walk` dùng đảo với ít lỗ; `rooms` dùng vách nội bộ có lối đi; `random` dùng lỗ ngẫu nhiên. Đây là các motif cơ chế có địa hình biến thiên, không phải lấy đường đi tĩnh rồi đảo ngược công tắc. Phiên bản đầu chưa kết hợp nhiều cầu với nhiều lần tách khối trong cùng một màn. Campaign hiện có vẫn là nguồn kiểm tra các tương tác phức tạp hơn.

BFS tham chiếu độc lập với bốn solver benchmark nhưng dùng chung luật trò chơi. Nó duyệt hết đồ thị đạt tới, coi đích là trạng thái kết thúc, lưu lời giải ngắn nhất và thống kê số trạng thái/cạnh. Tính hợp lệ của đường đi được kiểm tra lại bằng engine; đây không phải hai implementation độc lập của luật vật lý.

Màn dễ vỡ phải không giải được nếu cấm mọi bước chạm ô dễ vỡ; màn công tắc phải không giải được nếu cấm kích hoạt công tắc; màn tách phải không giải được nếu cấm tách. Vượt giới hạn kiểm chứng dẫn tới `unknown`, không kết luận vô nghiệm.

## Phân tầng và chống trùng

- Pilot riêng gồm 60 mẫu mỗi cơ chế để lấy hai ngưỡng phân vị độ dài. Ngưỡng được cố định trước khi sinh tập chính; các khoảng là `d ≤ ngưỡng 1`, `ngưỡng 1 < d ≤ ngưỡng 2`, `d > ngưỡng 2`.
- Mỗi cơ chế/khoảng có 30 màn: 10 phát triển và 20 đánh giá. Tổng cộng 120 phát triển, 240 đánh giá.
- Mỗi cơ chế/khoảng có 10 màn cho mỗi loại địa hình. Ngưỡng phân theo cơ chế; không gọi các khoảng là độ khó với con người.
- Mã băm chuẩn hóa loại padding, tịnh tiến, xoay và phản chiếu; không đổi thứ tự khối A/B hoặc định danh công tắc vì thứ tự tác động đồng thời phụ thuộc ID.
- Không nhận lại màn của pilot. Mỗi ứng viên có seed riêng và không tạo các biến thể từ một màn đã nhận để đưa sang tập khác.
- Dừng sau ngân sách ứng viên; ghi đầy đủ số thiếu và trả mã thoát khác 0 nếu không đủ chỉ tiêu. Không tự hạ tiêu chuẩn.
- 20 trường hợp vô nghiệm có đích bị cô lập. Chúng kiểm tra tính đúng đắn khi thất bại, chưa đại diện cho các trường hợp vô nghiệm khó.

Có thể đặt `width_range` và `height_range` trong cấu hình corpus (hai đầu mút bao gồm), tối đa `[9, 40]` cột và `[7, 30]` hàng. Mặc định là `[11, 18]` và `[7, 12]`. Tăng kích thước cần giữ bộ dữ liệu mới ở thư mục khác; không sửa corpus v1.

Các ID trong `ci_ids` chọn một màn ở mỗi cơ chế/khoảng. Phân tập đánh giá là tập để tránh điều chỉnh solver theo kết quả benchmark; vì dữ liệu được lưu công khai trong repo, nó không phải tập bí mật.

## Thử nhiều heuristic A*

Xem [A* heuristic experiments](heuristics.md) để dùng `--heuristics`, thêm factory
`module:function`, và chọn heuristic trong game. Mặc định vẫn là `manhattan`.
Các biến thể A* có định danh riêng trong dữ liệu thô, báo cáo và checkpoint.

## Wrapper đo hiệu năng

`benchmark/measure.py` là adapter duy nhất truy cập hook `_search(initial_state)` hiện có. Không sửa `BaseSolver`, `SearchResult` hoặc các thuật toán. Adapter trả `Measurement` riêng:

- `path`, `expanded_nodes`: kết quả tìm kiếm.
- `search_time`: giây tìm kiếm, chỉ có ở lượt timing.
- `initialization_time`, `total_time`: thời gian khởi tạo solver/heuristic và tổng thời gian, chỉ có ở lượt timing qua `measure_solver`.
- `peak_memory`: byte cấp phát Python cực đại, chỉ có ở lượt memory; runner mới đo cả khởi tạo heuristic và tìm kiếm.
- Giá trị không đo là `None`, không dùng 0 thay thế.

`measure_search` gọi `perf_counter()` ngay trước và sau `_search()` khi tracing tắt. Runner dùng `measure_solver(factory, ...)` để đo thêm khởi tạo và bao gồm bảng tiền tính trong đỉnh bộ nhớ. Timeout áp dụng chung cho khởi tạo và tìm kiếm. Lượt bộ nhớ riêng bật `tracemalloc`, đo đỉnh rồi tắt trong `finally`. Nếu đã có tracing của caller, adapter từ chối thay vì chiếm quyền hoặc đo một baseline bị nhiễu. Mỗi lượt production chạy trong interpreter mới, nên không có tracing hay trạng thái solver từ lượt trước.

Đây là phụ thuộc có chủ đích vào protected hook sẵn có. Kiểm thử đối chiếu adapter với `solve()` trên cả bốn solver nhằm phát hiện nếu hợp đồng hook thay đổi. Không monkey-patch hoặc sao chép thuật toán tìm kiếm.

Tất cả thuật toán dùng chi phí hành động bằng 1, gồm đổi khối đang điều khiển. UCS được khởi tạo với `cost_mode="unit"`. A* mặc định dùng heuristic sẵn có; `--heuristics` chọn nhiều biến thể cho cùng bộ dữ liệu. Thứ tự successor giữ nguyên của engine; runner chỉ xáo thứ tự các lượt đo với seed cố định. Không tối ưu thứ tự successor riêng cho một thuật toán.

Số trạng thái mở rộng giữ định nghĩa hiện tại của solver: BFS/UCS/A* đếm trạng thái không phải đích được lấy ra để mở rộng; DFS đếm khi bắt đầu duyệt successor, có thể chỉ duyệt một phần. Vì vậy không diễn giải số mở rộng thành số cạnh được kiểm tra bằng nhau giữa thuật toán.

Mỗi kết quả có mã băm corpus, cấu hình, thứ tự chạy, Python/dependency versions, thông tin CPU/RAM, git revision và trạng thái dirty. File JSONL được flush từng lượt để giữ tiến độ khi bị ngắt; báo cáo từ chối tập kết quả còn thiếu. CSV được ghi khi chạy hoàn tất.

## Cách đọc hình

### Hình dùng cho bài báo

Xuất hình nền trắng, nhãn tiếng Việt và phông **Times New Roman Regular**:

```bash
uv run bloxorz-benchmark figures \
  --corpus benchmarks/v1 \
  --results results/baseline-wrapper-v1 \
  --output results/paper-v1
```

Lệnh tự tìm phông đã cài, kể cả `~/.local/share/fonts/times.ttf` mới được thêm sau khi Matplotlib tạo cache. Có thể chỉ định `--font-dir /duong/dan/thu-muc-font`. Tên nội bộ phải là `Times New Roman`, có đủ ký tự tiếng Việt; không tự thay bằng Nimbus Roman hoặc phông serif khác.

Mỗi hình có PDF nhúng phông, SVG chuyển chữ thành đường nét và PNG 600 dpi. Chiều rộng là 85 hoặc 178 mm; nhãn 9 pt, vạch chia 8 pt. Mở **`captions.md` trước**: tài liệu có mục tiêu, điều kiện đo, bảng kết quả chính, ảnh xem trước và phần cách đọc/quan sát cho từng hình. `bo-hinh.pdf` tập hợp các hình theo cùng thứ tự để chèn vào báo cáo hoặc bài thuyết trình; `data/` chứa CSV để đối chiếu số liệu.

Mạch trình bày là: **hiệu năng → tỷ lệ giải → chất lượng lời giải → ví dụ cơ chế**. Hình hiệu năng dùng thanh ngang cho từng thuật toán, ghi trực tiếp giá trị trung vị và cỡ mẫu chung; trục tuyến tính bắt đầu từ 0. Thời gian và số trạng thái mở rộng dùng cùng các màn mọi thuật toán đều giải thành công; bộ nhớ yêu cầu thêm số đo hợp lệ của mọi thuật toán. Không xuất hình số màn theo nhóm/khoảng và quy mô đồ thị; thông tin cấu trúc dữ liệu vẫn có trong manifest corpus. Chất lượng lời giải chỉ dùng màn có nghiệm tối ưu được chứng nhận.

Chỉ xuất panel của tập có dữ liệu. Với v1 không có tập thử thách, hình khoảng nghiệm và panel thử thách được bỏ; không có telemetry thì bỏ hình tài nguyên pha sinh. Phần không xuất và lý do được ghi trong `captions.md` và `figure-manifest.json`. Nếu tập có dữ liệu nhưng không có mẫu thành công chung, ghi `n=0` cùng lý do, không coi timeout/mẫu thiếu là giá trị 0. Số hình và số trang PDF thay đổi theo dữ liệu; tên file giữ ổn định, số thứ tự hình theo thứ tự xuất. Khi xuất lại vào cùng thư mục, bộ sinh chỉ dọn các file hình/CSV do nó quản lý đã không còn phù hợp, không xóa file người dùng.

`figure-manifest.json` giữ các trường phông/kích thước và bổ sung phiên bản schema, số thứ tự/tiêu đề hình, danh sách `skipped`, số màn được đo, số màn thành công chung và thống kê trạng thái lượt đo. Không chạy lại solver khi tạo bộ hình.

- **Toàn cảnh kết quả benchmark:** quy mô và số lượt lỗi/chạm giới hạn.
- Kết quả mới so sánh tổng thời gian khởi tạo và tìm kiếm; kết quả cũ giữ phạm vi chỉ tìm kiếm. Báo cáo có thêm bảng tách thời gian khởi tạo/tìm kiếm/tổng.
- **Tỷ lệ giải được theo thời gian:** mẫu số là toàn bộ màn đã biết có lời giải; yêu cầu mọi lượt timing thành công, lấy thời gian trung vị từng màn.
- **Chi phí tìm kiếm theo thuật toán:** cùng tập màn mọi thuật toán đều giải được; hộp Q1–Q3, vạch trung vị và râu 1,5 IQR. Ẩn điểm ngoại lệ để tránh che phần chính; số liệu thô giữ nguyên. Dùng thang symlog có ghi đơn vị.
- **Chất lượng lời giải:** tỷ lệ so với tối ưu; giá trị 1 là tối ưu. DFS được chấp nhận lời giải dài hơn.
- **Bản đồ độ phức tạp của bộ dữ liệu:** độ dài tối ưu và số trạng thái đạt tới; không phải số BFS mở rộng tới đích.
- **Độ đa dạng của màn chơi:** số lượng theo cơ chế, khoảng độ dài và địa hình của toàn bộ corpus.
- **Hiệu quả của bộ sinh:** mọi lý do loại ứng viên của tập chính; thống kê pilot nằm riêng trong manifest.
- **Bộ sưu tập màn chơi tiêu biểu:** chọn trung vị độ dài mỗi nhóm/khoảng, hiển thị ô và cơ chế kèm tọa độ.
- Hai sơ đồ thể hiện quy trình tạo dữ liệu và quy trình đo.

Các trạng thái `timeout`, `memory_limit`, `invalid_path`, `error` không được chuyển thành thời gian giải thành công. Màn vô nghiệm có bảng riêng. Với lượt bộ nhớ thất bại, biểu đồ chỉ dùng mẫu có bộ nhớ hợp lệ và ghi cỡ mẫu. Không kết luận thuật toán nhanh hơn chỉ từ trung vị trên các tập thành công khác nhau.

## Kiểm thử

```bash
uv run pytest -q
uv run ruff check .
uv run bloxorz-benchmark verify --corpus benchmarks/v1
```

Kiểm thử bao phủ chứng nhận tối ưu, replay, cơ chế bắt buộc, symmetry, tái tạo từ seed, phân tập, wrapper, cleanup tracing, timeout và lỗi bộ nhớ, tính đầy đủ của dữ liệu báo cáo. Hình phải được kiểm tra trực tiếp sau render để phát hiện lỗi dấu tiếng Việt, chữ bị cắt hoặc chú giải chồng lấn.

## Nghiên cứu và giới hạn

- [Van der Zanden & Bodlaender — PSPACE-completeness of Bloxorz and of Games with 2-Buttons](https://arxiv.org/abs/1411.5951): hỗ trợ việc xem cơ chế công tắc là một chiều riêng và đặt giới hạn kiểm chứng; không chứng minh corpus cụ thể này khó.
- [Sturtevant — Moving AI grid benchmarks](https://www.movingai.com/benchmarks/grids.html): tham khảo tổ chức nhiều họ địa hình và dữ liệu nghiệm tham chiếu. Không sao chép bản đồ của nguồn này.
- [Withington, Cook & Tokarchuk — On the Evaluation of Procedural Level Generation Systems](https://arxiv.org/abs/2404.18657): động lực đánh giá riêng độ đa dạng, tính hợp lệ và phương pháp tái lập.
- [Matplotlib savefig](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html): cơ chế xuất hình vector và raster.

Bộ đầu tiên ưu tiên tính đúng đắn, tái lập và khả năng chạy trên laptop. Kích thước ứng viên mặc định 11–18 cột, 7–12 hàng; nhiều màn giải nhanh. Giới hạn 200.000 trạng thái tạo thiên lệch về màn kiểm chứng được. Không dùng kết quả để suy rộng cho mọi Bloxorz hoặc độ khó với người chơi. Các bước nghiên cứu tiếp theo là một tập stress riêng với nhiều cầu/tách khối, các motif mới và miền kích thước lớn hơn; giữ nguyên corpus v1 để so sánh theo thời gian.
