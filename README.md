# bloxorz-solver

## Getting Started

This project uses [uv](https://docs.astral.sh/uv/) to manage Python dependencies and run commands. Install it, then 
```sh 
uv sync
```

Chạy game với giao diện `pygame_gui`:

```sh
uv run bloxorz-solver
```

Chọn màn trong dropdown để tải ngay. Giao diện mặc định dùng **BFS**; chọn
**DFS**, **UCS**, **A*** hoặc **Manual**. A* có lựa chọn heuristic riêng.

Nhấn **Solve** để giải từ vị trí hiện tại và tự phát lời giải. Các nút **Pause/Resume**, **Step** xuất hiện khi còn lời giải đang phát hoặc tạm dừng.
Dropdown tốc độ **0.5× / 1× / 2× / 4×** luôn có trong chế độ solver.
Step thực hiện một hành động khi đã pause; đổi màn hoặc thuật toán bỏ lời giải cũ.

Trong Manual, dùng WASD/mũi tên để di chuyển, Space đổi khối. R chơi lại,
N sang màn tiếp sau khi thắng, Page Up/Page Down tải màn trước/sau.
Sau hoạt ảnh rơi, popup “You lose!” chờ nút Retry để chơi lại.
Khi thắng, popup có Next Stage và Replay; màn cuối hiện “All stages complete!”.
Popup chặn điều khiển bên dưới; R chơi lại, N sang màn kế sau khi thắng.
Escape đóng menu. Cửa sổ resize từ 800×600.

UI dùng nền tối đơn giản, bàn nghiêng 3D và chuyển động lăn của khối.
Bàn được cache theo màn, kích thước cửa sổ và trạng thái cầu; di chuyển khối
không dựng lại toàn bộ bàn. Không có cảnh trang trí hay asset tải qua mạng.

Sidebar dùng widget native `pygame_gui`: chọn màn, thuật toán, heuristic A*, tốc độ,
Solve, Pause/Resume, Step và Restart. Các nút phát lời giải và Restart nằm cùng hàng. Sidebar cuộn khi thiếu chiều cao;
font và controls scale cùng kích thước cửa sổ. Không có tiêu đề, hướng dẫn hay bảng trạng thái trên màn chơi.
Viền bàn và khối rõ nét; lỗi tìm kiếm được báo bằng thông báo ngắn rồi mờ dần.
Cảnh được vẽ trực tiếp bằng Pygame, không cần tải asset qua mạng khi chạy.

## For contributors

Before contributing, please read [CONTRIBUTING.md](CONTRIBUTING.md).

## Benchmark và sinh màn chơi

Bộ sinh có seed, 380 màn đã chứng nhận, runner đo độc lập và báo cáo biểu đồ tiếng Việt.
Xem [hướng dẫn benchmark](docs/benchmark.md) để cài đặt, chạy và tái tạo dữ liệu.
Xem [A* heuristic experiments](docs/heuristics.md) để thêm heuristic, so sánh các
triển khai và chọn heuristic trong giao diện game.

```sh
uv sync --group dev --extra benchmark
uv run bloxorz-benchmark run --corpus benchmarks/v1 --output results/quick --partition ci --repeats 1
uv run bloxorz-benchmark report --corpus benchmarks/v1 --results results/quick --output results/report
```
